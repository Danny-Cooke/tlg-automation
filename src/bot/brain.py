"""The Claude call. One function in, one structured reply out.

`ask` sends the cached persona, a small uncached context block (today's
date, the client's name), the thread and the new message. The model may
call `check_availability` (served by the handler from Fresha's public
booking flow) before answering; the loop runs the tool and feeds the result
back, a few rounds at most. The final answer is JSON against REPLY_SCHEMA.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

log = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("CLAUDE_EFFORT", "low")
MAX_TOKENS = 1024  # replies are two or three sentences; the JSON wrapper is small
MAX_TOOL_ROUNDS = 3  # a lookup per person or date range; more than this is a loop

ESCALATE_TO = ["", "jess", "carmen", "lori-dee"]
AREAS = ["", "nails", "hair", "tattoos", "aesthetics", "beauty", "general"]
# The team's own words for why a thread is being handed over (user, 2026-10-20).
ESCALATION_KINDS = ["", "complaint", "booking", "cancellation or rebooking", "can't assist anymore", "spam"]

REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "Message to send the client."},
        "escalate": {"type": "boolean", "description": "True if a person must take over this thread."},
        "escalation_reason": {
            "type": "string",
            "description": "One line for the team explaining why, with every detail they need (service, person, date, time). Empty if not escalating.",
        },
        "escalate_to": {
            "type": "string",
            "enum": ESCALATE_TO,
            "description": "Who should pick it up: jess (nails, general, complaints, money), carmen (tattoos), lori-dee (hair). Empty if not escalating.",
        },
        "area": {
            "type": "string",
            "enum": AREAS,
            "description": "What the thread is about: nails, hair, tattoos, aesthetics, beauty, or general. Empty if not escalating.",
        },
        "escalation_kind": {
            "type": "string",
            "enum": ESCALATION_KINDS,
            "description": "Why: complaint; booking (a slot agreed in chat that needs putting in); cancellation or rebooking; can't assist anymore (anything else you cannot handle); spam. Empty if not escalating.",
        },
        "suggested_booking_link": {
            "type": "string",
            "description": "Booking link given to the client, or empty string.",
        },
    },
    "required": ["reply", "escalate", "escalation_reason", "escalate_to", "area", "escalation_kind", "suggested_booking_link"],
    "additionalProperties": False,
}

AVAILABILITY_TOOL = {
    "name": "check_availability",
    "description": (
        "Look up free appointment start times on Fresha for one service with up to three "
        "named team members on up to four dates. Read only; it never books. Use the service's "
        "exact name from the salon details and team members' first names from the team list. "
        "If the client has no preference, pass the people who do that service."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Exact service name as listed in the salon details."},
            "people": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 3,
                "description": "First names from the team list.",
            },
            "dates": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 4,
                "description": "Dates to check, YYYY-MM-DD. Work them out from today's date in the context.",
            },
        },
        "required": ["service", "people", "dates"],
        "additionalProperties": False,
    },
}

SAFE_REPLY = "Thanks for your message. Let me check that with the team and come back to you shortly."

ToolRunner = Callable[[dict], str]


@dataclass(frozen=True)
class BotReply:
    reply: str
    escalate: bool
    escalation_reason: str = ""
    escalate_to: str = ""
    area: str = ""
    escalation_kind: str = ""
    suggested_booking_link: str = ""
    refused: bool = False


@lru_cache(maxsize=1)
def _client():
    # Imported lazily so unit tests never need AWS credentials.
    from anthropic import AnthropicAWS

    return AnthropicAWS()


def ask(
    system_prompt: str,
    history: list[dict],
    user_message: str,
    *,
    context: str = "",
    tools: dict[str, ToolRunner] | None = None,
    client=None,
) -> BotReply:
    """Return the bot's reply for `user_message` given prior `history`.

    `history` is a list of {"role": "user"|"assistant", "content": str} in order.
    `context` is the uncached block after the persona: today's date, the
    client's name, the channel. `tools` maps a tool name to a function that
    takes the tool input dict and returns text. Any failure to get a usable
    reply comes back as an escalation, never as an exception, so the handler
    always has something safe to do.
    """
    client = client or _client()
    system = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
    if context:
        system.append({"type": "text", "text": context})
    messages = history + [{"role": "user", "content": user_message}]
    request = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": REPLY_SCHEMA}},
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }
    if tools:
        request["tools"] = [AVAILABILITY_TOOL] if "check_availability" in tools else []

    for _round in range(MAX_TOOL_ROUNDS + 1):
        try:
            response = client.beta.messages.create(messages=messages, **request)
        except Exception:  # noqa: BLE001 - any API failure becomes an escalation
            log.exception("Claude call failed")
            return _safe_escalation("Claude call failed")
        if response.stop_reason != "tool_use":
            return parse_response(response)
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        messages.append({"role": "assistant", "content": [_block_dict(b) for b in response.content]})
        results = []
        for use in tool_uses:
            results.append({"type": "tool_result", "tool_use_id": use.id, "content": _run_tool(tools or {}, use.name, use.input)})
        messages.append({"role": "user", "content": results})
    log.warning("Gave up after %d tool rounds", MAX_TOOL_ROUNDS)
    return _safe_escalation("Too many availability lookups in one turn")


def _run_tool(tools: dict[str, ToolRunner], name: str, args: dict) -> str:
    fn = tools.get(name)
    if fn is None:
        return f"unknown tool {name}"
    try:
        out = fn(dict(args or {}))
    except Exception as exc:  # noqa: BLE001 - the model gets told, the client does not
        log.exception("Tool %s failed", name)
        return f"{name} failed: {type(exc).__name__}"
    log.info("TOOL %s %s -> %s", name, json.dumps(args)[:200], (out or "")[:300])
    return out or "no result"


def _block_dict(block) -> dict:
    """A response content block as a plain dict the API accepts back."""
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return {"type": "text", "text": getattr(block, "text", "")}


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
            escalate_to=_one_of(data.get("escalate_to"), ESCALATE_TO),
            area=_one_of(data.get("area"), AREAS),
            escalation_kind=_one_of(data.get("escalation_kind"), ESCALATION_KINDS),
            suggested_booking_link=data.get("suggested_booking_link", ""),
        )
    except (ValueError, KeyError, TypeError):
        log.exception("Unparseable reply: %r", text)
        return _safe_escalation("Unparseable model output")


def _one_of(value, allowed: list[str]) -> str:
    return value if isinstance(value, str) and value in allowed else ""


def _safe_escalation(reason: str, refused: bool = False) -> BotReply:
    return BotReply(
        reply=SAFE_REPLY, escalate=True, escalation_reason=reason, escalate_to="jess",
        area="general", escalation_kind="can't assist anymore", refused=refused,
    )
