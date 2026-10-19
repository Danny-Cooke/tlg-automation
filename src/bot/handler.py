"""Lambda entry point for one Meta channel's webhook (API Gateway HTTP API, payload v2).

One deployment per channel, from the same code: CHANNEL=messenger (the
Facebook Page, Meta app Tlg-app1) or CHANNEL=instagram (Meta app Tlg-app2).
Each has its own Lambda, secret, logs and alarm; they share the conversation
table. Meta invokes it the moment a message arrives, so nothing polls.

MESSAGE_TEST_MODE=true: only a message whose text starts with the trigger
word is answered; the word is stripped before the bot sees the text. Anything
else is stored and logged, never answered. false: every message is answered.

BOT_MODE decides how a message is answered:
    simple  a plain acknowledgement, no Claude, no persona (the first stage;
            the user adds the framework and persona later). The ops topic
            gets an email per message so the path can be watched.
    shadow  draft a reply with Claude and email it to Jess. Nothing reaches
            the client.
    live    reply with Claude; hand over to Jess when the bot says so.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from functools import lru_cache

from . import brain, escalation, meta
from .config import SalonConfig, load_persona
from .prompt import build_system_prompt
from .state import ConversationStore

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

MODES = ("simple", "shadow", "live")
MODE = os.environ.get("BOT_MODE", "simple")
CHANNEL = os.environ.get("CHANNEL", "")  # messenger | instagram; empty accepts both
TEST_MODE = os.environ.get("MESSAGE_TEST_MODE", "true").lower() == "true"
TEST_TRIGGER = os.environ.get("MESSAGE_TEST_TRIGGER", "bootycall")
# A human does not answer in under a second. Typing indicator on, wait, reply.
# Kept under Meta's 20 second webhook deadline; the message is marked seen in
# the store before the wait, so a retry during it is ignored.
REPLY_DELAY_SECONDS = float(os.environ.get("REPLY_DELAY_SECONDS", "10"))


@lru_cache(maxsize=1)
def secrets() -> dict:
    """This channel's Meta app secret, page token and verify token from Secrets Manager."""
    import boto3

    arn = os.environ["META_SECRET_ARN"]
    raw = boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"]
    return json.loads(raw)


@lru_cache(maxsize=1)
def system_prompt() -> str:
    return build_system_prompt(load_persona(), SalonConfig.from_env())


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

    if MODE == "simple":
        reply_text = simple_reply(msg.channel, text)
        convo.record_turn(msg.message_id, user_text, reply_text)
        store.save(convo)  # seen before the wait, so a Meta retry is a duplicate
        sent = _send(msg.sender_id, reply_text)
        escalation.notify_new_message(convo, user_text, msg.timestamp_ms, reply=reply_text if sent else None)
        store.save(convo)
        log.info("SIMPLE %s from %s: %r -> %r (sent=%s)", msg.channel, msg.sender_id, user_text[:200], reply_text, sent)
        return

    if convo.handed_to_jess:
        log.info("Thread %s is with Jess, staying quiet", msg.sender_id)
        convo.seen_message_ids.append(msg.message_id)
        store.save(convo)
        return

    if not text:
        # Attachment-only message: let Jess see it rather than guess.
        reply = brain.BotReply(reply=brain.SAFE_REPLY, escalate=True, escalation_reason="Non-text message")
    else:
        reply = brain.ask(system_prompt(), convo.history, user_text)

    convo.record_turn(msg.message_id, user_text, reply.reply)
    store.save(convo)  # seen before the wait, so a Meta retry is a duplicate

    if reply.escalate:
        # In shadow mode nothing reaches the client, so keep drafting instead
        # of locking the thread.
        convo.handed_to_jess = MODE == "live"
        escalation.notify(convo, reply.escalation_reason, user_text)

    if MODE == "shadow":
        log.info("SHADOW reply to %s: %s", msg.sender_id, reply.reply)
        if not reply.escalate:
            escalation.notify(convo, f"Shadow mode draft: {reply.reply}", user_text)
    else:
        _send(msg.sender_id, reply.reply)

    store.save(convo)


def simple_reply(channel: str, text: str) -> str:
    """The stand-in reply until the framework and persona exist."""
    what = f'"{text}"' if text else "a message with no text"
    return f"Hi, this is the TLG {channel} test bot. I received {what}."


def _send(recipient_id: str, text: str) -> bool:
    """Reply through the Graph API after a human-length pause with the typing
    indicator showing. Without a page token nothing can be sent; say so in the
    log rather than fail, so the rest of the path still works."""
    s = secrets()
    if not s.get("page_token"):
        log.warning("No page token configured; cannot reply to %s", recipient_id)
        return False
    if REPLY_DELAY_SECONDS > 0:
        meta.send_action(recipient_id, "typing_on", s["page_token"], app_secret=s.get("app_secret"))
        time.sleep(REPLY_DELAY_SECONDS)
    for chunk in meta.chunk_text(text):
        meta.send_text(recipient_id, chunk, s["page_token"], app_secret=s.get("app_secret"))
    return True


def _resp(status: int, body: str) -> dict:
    return {"statusCode": status, "headers": {"content-type": "text/plain"}, "body": body}
