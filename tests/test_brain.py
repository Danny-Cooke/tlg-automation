import json
from types import SimpleNamespace

from bot import brain


def fake_response(text=None, stop_reason="end_turn", category=None):
    content = [SimpleNamespace(type="text", text=text)] if text is not None else []
    stop_details = SimpleNamespace(category=category) if stop_reason == "refusal" else None
    return SimpleNamespace(content=content, stop_reason=stop_reason, stop_details=stop_details)


def test_parse_good_reply():
    payload = {
        "reply": "Lovely, here's the link for gel nails.",
        "escalate": False,
        "escalation_reason": "",
        "suggested_booking_link": "https://www.fresha.com/a/tlg?service=gel",
    }
    r = brain.parse_response(fake_response(json.dumps(payload)))
    assert r.reply == payload["reply"]
    assert r.escalate is False
    assert r.suggested_booking_link == payload["suggested_booking_link"]
    assert r.refused is False


def test_parse_escalation_flag():
    payload = {"reply": "Let me check.", "escalate": True, "escalation_reason": "Complaint", "suggested_booking_link": ""}
    r = brain.parse_response(fake_response(json.dumps(payload)))
    assert r.escalate is True
    assert r.escalation_reason == "Complaint"


def test_refusal_becomes_safe_escalation():
    r = brain.parse_response(fake_response(stop_reason="refusal", category="general_harms"))
    assert r.escalate is True
    assert r.refused is True
    assert r.reply == brain.SAFE_REPLY
    assert "general_harms" in r.escalation_reason


def test_truncation_becomes_safe_escalation():
    r = brain.parse_response(fake_response('{"reply": "half', stop_reason="max_tokens"))
    assert r.escalate is True
    assert r.reply == brain.SAFE_REPLY


def test_garbage_becomes_safe_escalation():
    r = brain.parse_response(fake_response("not json at all"))
    assert r.escalate is True
    assert r.reply == brain.SAFE_REPLY


def test_schema_is_strict():
    assert brain.REPLY_SCHEMA["additionalProperties"] is False
    assert set(brain.REPLY_SCHEMA["required"]) == set(brain.REPLY_SCHEMA["properties"])
