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
MAX_TOOL_ROUNDS = 5  # a move is check, availability, book, cancel; more than this is a loop
NO_MORE_TOOLS = ("That is enough looking for this turn. Answer the client now from what the lookups above "
                 "already told you: offer what you found free, or say what was not and ask what other day suits.")

ESCALATE_TO = ["", "jess", "carmen", "lori-dee"]
AREAS = ["", "nails", "hair", "tattoos", "aesthetics", "beauty", "general"]
# The team's own words for why a thread is being handed over (user, 2026-10-20).
ESCALATION_KINDS = ["", "complaint", "booking", "cancellation or rebooking", "cancellation fee", "quote", "can't assist anymore", "spam",
                    "patch test"]  # patch test: the bot booked a test and a treatment; Jess is told, the bot carries on (2026-10-24)

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
            "description": "Who should pick it up: jess (nails, beauty, lashes, aesthetics, general, money, and every complaint including hair), carmen (tattoos), lori-dee (hair that is not a complaint). Empty if not escalating.",
        },
        "area": {
            "type": "string",
            "enum": AREAS,
            "description": "What the thread is about: nails, hair, tattoos, aesthetics, beauty, or general. Empty if not escalating.",
        },
        "escalation_kind": {
            "type": "string",
            "enum": ESCALATION_KINDS,
            "description": "Why: complaint; booking (a slot agreed in chat that the tool could not put in, or any hair booking, which is Lori-Dee's or Sophie's); cancellation or rebooking (one the tool could not do); cancellation fee (a client inside the 24-hour window who is unsure or asks not to pay; Jess decides, the bot goes quiet); quote (a price you cannot give straight from the salon details, including anything from a picture; the team prices it, the bot goes quiet); can't assist anymore (anything else you cannot handle); spam. Empty if not escalating.",
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

BOOKING_TOOL = {
    "name": "book_appointment",
    "description": (
        "Put one agreed appointment into the salon's Fresha diary for a client Fresha "
        "already knows. Call it only after the client has said yes to a specific service, "
        "person, date and time that you confirmed back to them in one message. It answers "
        "'Booked: ...' when the appointment is in, or says why it could not book and what to "
        "do instead; never tell the client it is booked unless the answer starts with 'Booked'. "
        "Nails, beauty, lashes, aesthetics, and for tattoos only Carmen's free consultation. Never hair: "
        "Sophie's clients go to her WhatsApp, Lori-Dee's to her booking link or a hand-over. A tattoo itself is not booked here."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Exact service name as listed in the salon details."},
            "person": {"type": "string", "description": "Team member's first name from the team list."},
            "date": {"type": "string", "description": "YYYY-MM-DD, worked out from today's date in the context."},
            "time": {"type": "string", "description": "Start time, 24-hour HH:MM, e.g. 13:30."},
            "client_name": {
                "type": "string",
                "description": "The client's full name as Fresha would have it: their profile name from the context unless they gave a different one in chat.",
            },
        },
        "required": ["service", "person", "date", "time", "client_name"],
        "additionalProperties": False,
    },
}

CANCEL_TOOL = {
    "name": "cancel_appointment",
    "description": (
        "Cancel one of the client's upcoming appointments in the salon's Fresha diary. Call it "
        "only after the client has asked to cancel and you have confirmed which appointment "
        "(day, and time if they have more than one that day). Without a date it lists their "
        "upcoming appointments so you can ask which. It answers 'Cancelled: ...' when done, "
        "or says why it did not cancel: a cancellation fee applies, nothing found, or Fresha "
        "could not be reached. With check_only it only reports whether cancelling would be free. "
        "Never tell the client it is cancelled unless the answer starts with 'Cancelled'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD of the appointment to cancel; empty to list their upcoming appointments."},
            "time": {"type": "string", "description": "Start time HH:MM, only needed when they have two appointments that day."},
            "client_name": {
                "type": "string",
                "description": "The client's full name as Fresha would have it: their profile name from the context unless they gave a different one in chat.",
            },
            "check_only": {
                "type": "boolean",
                "description": "True to only find the appointment and ask Fresha whether cancelling it now is free, without cancelling. Use this first when moving an appointment.",
            },
        },
        "required": ["date", "time", "client_name", "check_only"],
        "additionalProperties": False,
    },
}

PATCH_TEST_TOOL = {
    "name": "patch_test_status",
    "description": (
        "Whether the salon has a patch test on record for a client, from the salon's client list: a test logged in "
        "Fresha, or assumed from a past lash or brow appointment. Read only. Call it before booking any lash or brow "
        "treatment. 'Patch tested' means book as normal; anything else means a 10-minute 'lash patch test' is booked first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "client_name": {
                "type": "string",
                "description": "The client's full name as Fresha would have it: their profile name from the context unless they gave a different one in chat.",
            },
        },
        "required": ["client_name"],
        "additionalProperties": False,
    },
}

CREATE_CLIENT_TOOL = {
    "name": "create_client",
    "description": (
        "Onboard a client Fresha does not know, after `book_appointment` said there is no client with their name. "
        "Call it with their first name, last name, mobile number and email, asked for in one message. It first looks the "
        "number up: if Fresha already has it under another name it uses that record and adds nothing; otherwise it adds "
        "the client. After it answers, book for them as normal."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "first_name": {"type": "string"},
            "last_name": {"type": "string"},
            "mobile": {"type": "string", "description": "UK mobile as the client gave it, e.g. 07700 900123."},
            "email": {"type": "string"},
        },
        "required": ["first_name", "last_name", "mobile", "email"],
        "additionalProperties": False,
    },
}

TOOL_DEFINITIONS = {"check_availability": AVAILABILITY_TOOL, "patch_test_status": PATCH_TEST_TOOL, "book_appointment": BOOKING_TOOL,
                    "cancel_appointment": CANCEL_TOOL, "create_client": CREATE_CLIENT_TOOL}

SAFE_REPLY = "Hi lovely, give me a little time to have a think and I'll get back to you x"

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
        request["tools"] = [TOOL_DEFINITIONS[name] for name in TOOL_DEFINITIONS if name in tools]

    for _round in range(MAX_TOOL_ROUNDS + 1):
        try:
            response = client.beta.messages.create(messages=messages, **request)
        except Exception:  # noqa: BLE001 - any API failure becomes an escalation
            log.exception("Claude call failed")
            return _safe_escalation("Claude call failed")
        if response.stop_reason != "tool_use":
            return parse_response(response)
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        # The API refuses an empty text block echoed back, and a tool turn often has one.
        messages.append({"role": "assistant", "content": [d for d in map(_block_dict, response.content) if d]})
        results = []
        for use in tool_uses:
            results.append({"type": "tool_result", "tool_use_id": use.id, "content": _run_tool(tools or {}, use.name, use.input)})
        messages.append({"role": "user", "content": results})
    # The cap is for runaway loops, but the model usually has the answer by now
    # (2026-10-25: six lookups for "BIAB with Sav next week" when the first had
    # found Thursday free, then the holding line). One more call with the tools
    # closed, so it answers from what it found; the escalation only if it still cannot.
    log.warning("Tool cap after %d rounds; asking for an answer from what was found", MAX_TOOL_ROUNDS)
    messages[-1]["content"].append({"type": "text", "text": NO_MORE_TOOLS})
    try:
        response = client.beta.messages.create(messages=messages, tool_choice={"type": "none"}, **request)
    except Exception:  # noqa: BLE001
        log.exception("Claude call failed")
        return _safe_escalation("Claude call failed")
    if response.stop_reason != "tool_use":
        return parse_response(response)
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


def _block_dict(block) -> dict | None:
    """A response content block as a plain dict the API accepts back; None for an empty text block."""
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    text = getattr(block, "text", "") or ""
    return {"type": "text", "text": text} if text.strip() else None


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
