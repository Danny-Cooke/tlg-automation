"""Tell Jess when the bot hands a conversation over."""
from __future__ import annotations

import json
import logging
import os
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


@lru_cache(maxsize=1)
def _sns():
    import boto3

    return boto3.client("sns")
