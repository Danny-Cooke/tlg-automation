"""Tell Jess when the bot hands a conversation over."""
from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache

from .state import Conversation

log = logging.getLogger(__name__)


def business_suite_link(channel: str, page_id: str) -> str:
    # Both channels are handled in the Meta Business Suite inbox for the page.
    return f"https://business.facebook.com/latest/inbox/all?asset_id={page_id}"


def format_alert(
    convo: Conversation, reason: str, last_user_text: str, page_id: str, to: str = "", bot_quiet: bool = True
) -> tuple[str, str]:
    """Return (subject, body) for the escalation message. `to` names who should pick it up."""
    who = convo.client_name or convo.sender_id
    for_whom = f" for {to.title()}" if to else ""
    subject = f"[TLG bot] Needs you{for_whom}: {who} ({convo.channel})"
    lines = [
        f"Reason: {reason}",
        f"For: {to.title() or 'whoever is on the inbox'}",
        f"Channel: {convo.channel}",
        f"Client: {who}",
        f"Open inbox: {business_suite_link(convo.channel, page_id)}",
        "",
        "Latest message:",
        last_user_text,
        "",
        "Recent thread:",
    ]
    for turn in convo.history[-10:]:
        speaker = "Client" if turn["role"] == "user" else "Bot"
        lines.append(f"  {speaker}: {turn['content']}")
    lines += ["", "The bot will stay quiet on this thread until you clear the hand-over." if bot_quiet
              else "The bot is still answering on this thread; it has told the client you will sort this."]
    return subject, "\n".join(lines)


CHANNEL_SHORT = {"messenger": "FB", "instagram": "Insta"}


def format_telegram(convo: Conversation, page_id: str, *, area: str = "", kind: str = "", reason: str = "") -> str:
    """The team's one-liner (user, 2026-10-20): `Nails: complaint: Danny Cooke: FB`,
    then the link that opens the thread. The model's reason goes on a third line
    when it adds something, for example the slot a client agreed to."""
    who = convo.client_name or convo.sender_id
    channel = CHANNEL_SHORT.get(convo.channel, convo.channel or "?")
    first = f"{(area or 'general').capitalize()}: {kind or 'needs you'}: {who}: {channel}"
    lines = [first, business_suite_link(convo.channel, page_id)]
    if reason and reason.lower() not in (kind.lower(), ""):
        lines.append(reason)
    return "\n".join(lines)


def notify(
    convo: Conversation, reason: str, last_user_text: str, *,
    to: str = "", area: str = "", kind: str = "", bot_quiet: bool = True, sns=None, telegram=None,
) -> None:
    """Email the escalation topic and post the one-liner to the team's Telegram group.
    Spam goes to email only; nobody wants sellers buzzing their phone."""
    page_id = os.environ.get("META_PAGE_ID", "")
    if kind != "spam":
        poster = telegram or _telegram().post_handover
        try:
            poster(format_telegram(convo, page_id, area=area, kind=kind, reason=reason))
        except Exception:  # noqa: BLE001 - Telegram must never break the hand-over
            log.exception("Telegram hand-over failed")
    topic_arn = os.environ.get("ESCALATION_TOPIC_ARN")
    subject, body = format_alert(convo, reason, last_user_text, page_id, to, bot_quiet)
    if not topic_arn:
        log.warning("ESCALATION_TOPIC_ARN not set; would have sent: %s", subject)
        return
    client = sns or _sns()
    client.publish(
        TopicArn=topic_arn,
        Subject=subject[:100],  # SNS subject limit
        Message=body,
        MessageAttributes={
            "channel": {"DataType": "String", "StringValue": convo.channel or "unknown"},
            "sender_id": {"DataType": "String", "StringValue": convo.sender_id},
        },
    )
    log.info("Escalated %s", json.dumps({"sender_id": convo.sender_id, "reason": reason}))


def notify_booking(convo: Conversation, summary: str, appointment_id: str, *, kind: str = "booked by the bot", area: str = "nails",
                   sns=None, telegram=None) -> None:
    """The bot has just put an appointment into Fresha, or taken one out: tell
    the team group in the usual one-line shape, and the ops topic for the
    record. Best effort."""
    page_id = os.environ.get("META_PAGE_ID", "")
    text = format_telegram(convo, page_id, area=area, kind=kind, reason=f"{summary} (Fresha {appointment_id})")
    poster = telegram or _telegram().post_handover
    try:
        poster(text)
    except Exception:  # noqa: BLE001
        log.exception("Telegram booking post failed")
    topic_arn = os.environ.get("OPS_TOPIC_ARN")
    if not topic_arn:
        log.info("OPS_TOPIC_ARN not set; booking not emailed: %s", summary)
        return
    who = convo.client_name or convo.sender_id
    verb = kind.split(" by ")[0].capitalize()  # Booked / Cancelled
    body = "\n".join([
        f"{kind.capitalize()}: {summary}",
        f"Fresha appointment: {appointment_id}",
        f"Channel: {convo.channel}",
        f"Client: {who}",
        f"Open inbox: {business_suite_link(convo.channel, page_id)}",
    ])
    try:
        (sns or _sns()).publish(TopicArn=topic_arn, Subject=f"[TLG bot] {verb}: {summary}"[:100], Message=body)
    except Exception:  # noqa: BLE001
        log.exception("Booking email failed")


def notify_new_message(convo: Conversation, text: str, timestamp_ms: int = 0, *, reply: str | None = None, sns=None) -> None:
    """Simple mode: tell the ops topic (you, not Jess) what arrived and what went back."""
    topic_arn = os.environ.get("OPS_TOPIC_ARN")
    page_id = os.environ.get("META_PAGE_ID", "")
    when = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(timestamp_ms / 1000)) if timestamp_ms else "unknown time"
    subject = f"[TLG bot] New {convo.channel} message from {convo.sender_id}"
    body = "\n".join(
        [
            f"Channel: {convo.channel}",
            f"Sender: {convo.sender_id}",
            f"Received: {when}",
            f"Open inbox: {business_suite_link(convo.channel, page_id)}",
            "",
            "Message:",
            text,
            "",
            "Reply sent:" if reply else "Reply: none sent (no page token configured).",
            *( [reply] if reply else [] ),
            "",
            f"Thread so far: {len(convo.history)} message(s) stored.",
        ]
    )
    if not topic_arn:
        log.warning("OPS_TOPIC_ARN not set; would have sent: %s", subject)
        return
    (sns or _sns()).publish(TopicArn=topic_arn, Subject=subject[:100], Message=body)
    log.info("Listen notice sent for %s", convo.sender_id)


@lru_cache(maxsize=1)
def _sns():
    import boto3

    return boto3.client("sns")


def _telegram():
    from . import telegram

    return telegram
