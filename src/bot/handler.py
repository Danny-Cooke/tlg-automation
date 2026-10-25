"""Lambda entry point for one Meta channel's webhook (API Gateway HTTP API, payload v2).

One deployment per channel, from the same code: CHANNEL=messenger (the
Facebook Page, Meta app Tlg-app1) or CHANNEL=instagram (Meta app Tlg-app2).
Each has its own Lambda, secret, logs and alarm; they share the conversation
table. Meta invokes it the moment a message arrives, so nothing polls.

MESSAGE_TEST_MODE=true: only a message whose text starts with the trigger
word is answered; the word is stripped before the bot sees the text. Anything
else is stored and logged, never answered. false: every message is answered.

BOT_MODE decides how a message is answered:
    simple  a plain acknowledgement, no Claude, no persona. The ops topic
            gets an email per message so the path can be watched.
    shadow  draft a reply with Claude and email it to Jess. Nothing reaches
            the client.
    live    reply with Claude; hand over to a person when the bot says so.

In the Claude modes the bot knows the client's name (Meta's profile call,
once per thread), can look up real availability on Fresha's public booking
flow, and in live mode can put an agreed nail or hair appointment into Fresha with
the owner's stored session (bot/booking.py). In shadow mode the booking tool
checks everything and writes nothing.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import os
import time
import zoneinfo
from functools import lru_cache

from . import availability, booking, brain, escalation, fresha_session, meta, patch_tests
from .config import SalonConfig, load_persona
from .prompt import build_system_prompt
from .state import Conversation, ConversationStore

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

MODES = ("simple", "shadow", "live")
MODE = os.environ.get("BOT_MODE", "simple")
CHANNEL = os.environ.get("CHANNEL", "")  # messenger | instagram; empty accepts both
TEST_MODE = os.environ.get("MESSAGE_TEST_MODE", "true").lower() == "true"
TEST_TRIGGER = os.environ.get("MESSAGE_TEST_TRIGGER", "joshsmells")
# A human does not answer in under a second. Typing indicator on, wait, reply.
# The wait is measured from when the message arrived, so time spent asking
# Claude and Fresha counts towards it. Kept under Meta's 20 second webhook
# deadline; the message is marked seen in the store before the wait, so a
# retry during it is ignored.
REPLY_DELAY_SECONDS = float(os.environ.get("REPLY_DELAY_SECONDS", "10"))
# Hand-over kinds after which the bot stays quiet on the thread. The rest
# (booking, cancellation or rebooking, spam) notify the team and carry on.
# A cancellation-fee plea locks too: Jess decides about money (user, 2026-10-21).
LOCKING_KINDS = frozenset({"complaint", "cancellation fee", "quote", "can't assist anymore", ""})
# Areas that always lock, whatever the kind: a hair thread is Lori-Dee's to
# deal with completely in the inbox, or has been sent to Sophie's WhatsApp
# (user, 2026-10-24). Complaints about hair still go to Jess, and lock anyway.
LOCKING_AREAS = frozenset({"hair"})


def locks(kind: str, area: str) -> bool:
    return kind in LOCKING_KINDS or area in LOCKING_AREAS
SALON_TZ = zoneinfo.ZoneInfo(os.environ.get("SALON_TIMEZONE", "Europe/London"))


@lru_cache(maxsize=1)
def secrets() -> dict:
    """This channel's Meta app secret, page token and verify token from Secrets Manager."""
    import boto3

    arn = os.environ["META_SECRET_ARN"]
    raw = boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"]
    s = json.loads(raw)
    if s.get("page_token"):  # a System User token is swapped for the Page's own; a Page token passes through
        s["page_token"] = meta.page_token_for(s["page_token"], os.environ.get("META_PAGE_ID", ""), app_secret=s.get("app_secret"))
    return s


@lru_cache(maxsize=1)
def salon() -> SalonConfig:
    return SalonConfig.from_env()


@lru_cache(maxsize=1)
def system_prompt() -> str:
    return build_system_prompt(load_persona(), salon())


@lru_cache(maxsize=1)
def fresha_session_check() -> bool:
    """Once per container: does the stored Fresha session work from here?
    Logged so the owner can see it in CloudWatch; the bot does not yet book,
    so a bad session changes nothing else."""
    session = fresha_session.get()
    if session is None:
        log.info("FRESHA SESSION none (parameter not set, or expired)")
        return False
    where = fresha_session.probe(session)
    if where:
        log.info("FRESHA SESSION ok (%s, %s days left)", where, session.days_left())
        return True
    log.warning("FRESHA SESSION rejected; run scripts/fresha_session.py")
    return False


def lambda_handler(event: dict, context=None) -> dict:
    if MODE not in MODES:
        raise RuntimeError(f"BOT_MODE must be one of {MODES}, not {MODE!r}")
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    if method == "GET":
        return _handle_verify(event)
    if method == "POST":
        return _handle_webhook(event)
    return _resp(405, "method not allowed")


def _handle_verify(event: dict) -> dict:
    challenge = meta.verify_challenge(event.get("queryStringParameters") or {}, secrets()["verify_token"])
    if challenge is None:
        return _resp(403, "verification failed")
    return _resp(200, challenge)


def _handle_webhook(event: dict, *, store: ConversationStore | None = None) -> dict:
    raw = event.get("body") or ""
    body_bytes = base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode()
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if not meta.verify_signature(body_bytes, headers.get("x-hub-signature-256"), secrets()["app_secret"]):
        log.warning("Bad webhook signature")
        return _resp(403, "bad signature")

    try:
        payload = json.loads(body_bytes)
    except ValueError:
        return _resp(400, "bad json")

    store = store or ConversationStore()
    for msg in meta.parse_events(payload):
        if CHANNEL and msg.channel != CHANNEL:
            log.warning("Ignoring %s message on the %s bot", msg.channel, CHANNEL)
            continue
        try:
            process_message(msg, store)
        except Exception:  # noqa: BLE001 - one bad thread must not fail the batch
            log.exception("Failed processing message %s", msg.message_id)
    # Always 200 so Meta does not retry; failures are logged and alarmed on.
    return _resp(200, "ok")


def test_gate(text: str) -> tuple[bool, str]:
    """(answer it?, text to answer). Only the trigger word opens the gate in test mode."""
    if not TEST_MODE:
        return True, text
    stripped = text.strip()
    if stripped.lower().startswith(TEST_TRIGGER.lower()):
        return True, stripped[len(TEST_TRIGGER):].strip()
    return False, text


def process_message(msg: meta.InboundMessage, store: ConversationStore) -> None:
    started = time.monotonic()
    convo = store.load(msg.sender_id)
    convo.channel = msg.channel
    if convo.has_seen(msg.message_id):
        log.info("Duplicate delivery %s, skipping", msg.message_id)
        return

    allowed, text = test_gate(msg.text)
    if not allowed:
        convo.note_message(msg.message_id, msg.text or "[attachment without text]")
        store.save(convo)
        log.info("TEST MODE: not answering %s on %s (no trigger word)", msg.sender_id, msg.channel)
        return

    user_text = text or "[attachment without text]"
    if text and msg.attachments:
        user_text = f"{text} [{msg.attachments} picture(s) attached]"  # the model knows, without being able to see

    if MODE == "simple":
        reply_text = simple_reply(msg.channel, text)
        convo.record_turn(msg.message_id, user_text, reply_text)
        store.save(convo)  # seen before the wait, so a Meta retry is a duplicate
        sent = _send(msg.sender_id, reply_text, started)
        escalation.notify_new_message(convo, user_text, msg.timestamp_ms, reply=reply_text if sent else None)
        store.save(convo)
        log.info("SIMPLE %s from %s: %r -> %r (sent=%s)", msg.channel, msg.sender_id, user_text[:200], reply_text, sent)
        return

    if convo.handed_to_jess and not convo.watching():
        log.info("Thread %s is with %s, staying quiet", msg.sender_id, convo.handed_to or "the team")
        convo.note_message(msg.message_id, user_text)
        store.save(convo)
        return
    watching = convo.watching()  # with Lori-Dee or Carmen: read it, answer only if it is ours

    _ensure_name(convo)
    convo.mark_seen(msg.message_id)
    store.save(convo)  # claimed before the Claude call: a retry during it is a duplicate
    if MODE == "live":
        _typing(msg.sender_id)  # dots while we think, not just during the pause
    fresha_session_check()

    if not text:
        # Attachment-only message: let a person see it rather than guess.
        reply = brain.BotReply(
            reply=brain.SAFE_REPLY, escalate=True, escalation_reason="Non-text message (picture or attachment)",
            escalate_to="jess", area="general", escalation_kind="quote",
        )
    else:
        reply = brain.ask(system_prompt(), convo.history, user_text, context=context_block(convo), tools=tools(convo, store))

    if watching and (not reply.reply.strip() or (reply.escalate and reply.area == convo.handed_area)):
        # Theirs, or a reply to them: Lori-Dee or Carmen is answering in the inbox.
        log.info("Thread %s is with %s for %s; this message is theirs", msg.sender_id, convo.handed_to, convo.handed_area)
        convo.note_message(msg.message_id, user_text)
        store.save(convo)
        return

    convo.record_turn(msg.message_id, user_text, reply.reply)
    store.save(convo)  # seen before the wait, so a Meta retry is a duplicate

    if reply.escalate:
        # A complaint, or something the bot cannot handle, goes quiet so a
        # person takes the thread. A booking or a move just tells the team and
        # the bot keeps talking: the client is mid-conversation (user,
        # 2026-10-20). Shadow mode never locks, nothing reaches the client.
        lock = MODE == "live" and locks(reply.escalation_kind, reply.area)
        if lock:
            convo.hand_over(reply.escalate_to, reply.area)
        elif not watching:
            convo.handed_to_jess = False
        escalation.notify(
            convo, reply.escalation_reason, user_text,
            to=reply.escalate_to, area=reply.area, kind=reply.escalation_kind, bot_quiet=lock,
        )

    if MODE == "shadow":
        log.info("SHADOW reply to %s: %s", msg.sender_id, reply.reply)
        if not reply.escalate:
            escalation.notify(convo, f"Shadow mode draft: {reply.reply}", user_text, kind="shadow draft")
    else:
        _send(msg.sender_id, reply.reply, started)

    store.save(convo)


def simple_reply(channel: str, text: str) -> str:
    """The stand-in reply of the first stage."""
    what = f'"{text}"' if text else "a message with no text"
    return f"Hi, this is the TLG {channel} test bot. I received {what}."


def context_block(convo: Conversation, now: dt.datetime | None = None) -> str:
    """The small uncached block after the persona: today, the client, the channel."""
    now = now or dt.datetime.now(SALON_TZ)
    lines = [f"Today is {now:%A} {now.day} {now:%B %Y}, {now:%H:%M} in Shrewsbury."]
    if convo.client_name:
        lines.append(f"The client's name from their {convo.channel or 'Meta'} profile is {convo.client_name}. Use their first name.")
    else:
        lines.append("The client's name is not known.")
    lines.append(f"Channel: {convo.channel or 'unknown'}.")
    if convo.watching():
        who = WATCHED_NAMES.get(convo.handed_to, convo.handed_to)
        lines.append(
            f"This thread is with {who} for {convo.handed_area}: {who} is answering the client here in the inbox, "
            f"and those messages are not shown to you. Answer only if the new message is clearly about something "
            f"else that is yours (nails, beauty, lashes, aesthetics, hours, the salon). If it is about {convo.handed_area}, "
            f"could be a reply to {who}, or you are not sure, set `reply` to an empty string and `escalate` to false: "
            f"nothing is sent."
        )
    return " ".join(lines)


WATCHED_NAMES = {"lori-dee": "Lori-Dee", "carmen": "Carmen"}


def tools(convo: Conversation | None = None, store: ConversationStore | None = None) -> dict[str, brain.ToolRunner]:
    """What the model may call. Availability needs the venue URL and staff ids
    from the salon config. Booking needs the Fresha session parameter and a
    conversation to book for; it only writes in live mode."""
    cfg = salon()
    out: dict[str, brain.ToolRunner] = {}
    if cfg.venue_url:
        out["check_availability"] = lambda args: run_availability(args, cfg)
    if convo is not None and os.environ.get("FRESHA_SESSION_PARAM"):
        common = dict(cfg=cfg, convo=convo, dry_run=MODE != "live", save=store.save if store else None, notify=escalation.notify_booking)
        out["book_appointment"] = lambda args: booking.book(args, **common)
        out["cancel_appointment"] = lambda args: booking.cancel(args, **common)
        out["create_client"] = lambda args: booking.create_client(args, **common)
    if os.environ.get("CLIENTS_TABLE"):
        out["patch_test_status"] = patch_tests.status
    return out


def run_availability(args: dict, cfg: SalonConfig, http=None) -> str:
    """Tool body: map first names to Fresha ids, look up, format for the model."""
    import requests

    people = []
    unknown = []
    for name in args.get("people") or []:
        member = cfg.staff_named(str(name))
        if member and member.employee_id:
            people.append((member.name, member.employee_id))
        else:
            unknown.append(str(name))
    lines = []
    if unknown:
        lines.append(f"Not on the team list or not bookable online: {', '.join(unknown)}")
    if people:
        results = availability.check(
            http or requests.Session(),
            cfg.venue_url,
            service=str(args.get("service") or ""),
            people=people,
            dates=[str(d) for d in (args.get("dates") or [])],
        )
        lines.append(availability.format_for_model(results))
    return "\n".join(lines) or "nobody to check"


def _ensure_name(convo: Conversation) -> None:
    """Fetch the client's name once per thread. Best effort; a missing name is fine."""
    if convo.client_name:
        return
    s = secrets()
    if not s.get("page_token"):
        return
    profile = meta.user_profile(convo.sender_id, s["page_token"], channel=convo.channel, app_secret=s.get("app_secret"))
    convo.client_name = meta.display_name(profile)
    if convo.client_name:
        log.info("Client %s is %s", convo.sender_id, convo.client_name)


def _typing(recipient_id: str) -> None:
    s = secrets()
    if s.get("page_token") and REPLY_DELAY_SECONDS > 0:
        meta.send_action(recipient_id, "typing_on", s["page_token"], app_secret=s.get("app_secret"))


def _send(recipient_id: str, text: str, started: float | None = None) -> bool:
    """Reply through the Graph API after a human-length pause with the typing
    indicator showing. The pause counts from `started` (time.monotonic), so a
    slow Claude or Fresha call eats into it rather than adding to it. Without
    a page token nothing can be sent; say so in the log rather than fail, so
    the rest of the path still works."""
    s = secrets()
    if not s.get("page_token"):
        log.warning("No page token configured; cannot reply to %s", recipient_id)
        return False
    if not text.strip():
        log.info("Nothing to send to %s", recipient_id)
        return False
    if REPLY_DELAY_SECONDS > 0:
        meta.send_action(recipient_id, "typing_on", s["page_token"], app_secret=s.get("app_secret"))
        elapsed = time.monotonic() - started if started is not None else 0.0
        remaining = REPLY_DELAY_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)
    chunks = list(meta.chunk_text(text))
    for chunk in chunks:
        meta.send_text(recipient_id, chunk, s["page_token"], app_secret=s.get("app_secret"))
    log.info("SENT %d message(s) to %s: %r", len(chunks), recipient_id, text[:200])
    return True


def _resp(status: int, body: str) -> dict:
    return {"statusCode": status, "headers": {"content-type": "text/plain"}, "body": body}
