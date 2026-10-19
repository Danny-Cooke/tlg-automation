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


def format_alert(convo: Conversation, reason: str, last_user_text: str, page_id: str) -> tuple[str, str]:
    """Return (subject, body) for the escalation message."""
    who = convo.client_name or convo.sender_id
    subject = f"[TLG bot] Needs you: {who} ({convo.channel})"
    lines = [
        f"Reason: {reason}",
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
    lines += ["", "The bot will stay quiet on this thread until you clear the hand-over."]
    return subject, "\n".join(lines)


def notify(convo: Conversation, reason: str, last_user_text: str, *, sns=None) -> None:
    topic_arn = os.environ.get("ESCALATION_TOPIC_ARN")
    page_id = os.environ.get("META_PAGE_ID", "")
    subject, body = format_alert(convo, reason, last_user_text, page_id)
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
