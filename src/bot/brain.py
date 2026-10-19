"""The Claude call. One function in, one structured reply out."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache

log = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("CLAUDE_EFFORT", "low")
MAX_TOKENS = 1024  # replies are two or three sentences; the JSON wrapper is small

REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "Message to send to the client."},
        "escalate": {"type": "boolean", "description": "True if Jess must take over."},
        "escalation_reason": {
            "type": "string",
            "description": "One line for Jess explaining why. Empty if not escalating.",
        },
        "suggested_booking_link": {
            "type": "string",
            "description": "Booking link given to the client, or empty string.",
        },
    },
    "required": ["reply", "escalate", "escalation_reason", "suggested_booking_link"],
    "additionalProperties": False,
}

SAFE_REPLY = "Thanks for your message. Let me check that with the team and come back to you shortly."


@dataclass(frozen=True)
class BotReply:
    reply: str
    escalate: bool
    escalation_reason: str = ""
    suggested_booking_link: str = ""
    refused: bool = False


@lru_cache(maxsize=1)
def _client():
    # Imported lazily so unit tests never need AWS credentials.
    from anthropic import AnthropicAWS

    return AnthropicAWS()


def ask(system_prompt: str, history: list[dict], user_message: str) -> BotReply:
    """Return the bot's reply for `user_message` given prior `history`.

    `history` is a list of {"role": "user"|"assistant", "content": str} in order.
    Any failure to get a usable reply comes back as an escalation, never as an
    exception, so the handler always has something safe to do.
    """
    messages = history + [{"role": "user", "content": user_message}]
    try:
        response = _client().beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
            output_config={
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": REPLY_SCHEMA},
            },
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except Exception:  # noqa: BLE001 - any API failure becomes an escalation
        log.exception("Claude call failed")
        return _safe_escalation("Claude call failed")

    return parse_response(response)


def parse_response(response) -> BotReply:
    """Turn an API response into a BotReply. Split out so tests can cover it."""
    if response.stop_reason == "refusal":
        category = getattr(getattr(response, "stop_details", None), "category", None)
        log.warning("Claude refused: %s", category)
        return _safe_escalation(f"Model refused ({category})", refused=True)
    if response.stop_reason == "max_tokens":
        log.warning("Claude reply truncated")
        return _safe_escalation("Reply truncated")

    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        data = json.loads(text)
        return BotReply(
            reply=data["reply"],
            escalate=bool(data["escalate"]),
            escalation_reason=data.get("escalation_reason", ""),
            suggested_booking_link=data.get("suggested_booking_link", ""),
        )
    except (ValueError, KeyError, TypeError):
        log.exception("Unparseable reply: %r", text)
        return _safe_escalation("Unparseable model output")


def _safe_escalation(reason: str, refused: bool = False) -> BotReply:
    return BotReply(reply=SAFE_REPLY, escalate=True, escalation_reason=reason, refused=refused)
