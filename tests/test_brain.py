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


def test_parse_escalate_to_area_and_kind_are_validated():
    good = {"reply": "x", "escalate": True, "escalation_reason": "hair colour", "escalate_to": "lori-dee",
            "area": "hair", "escalation_kind": "can't assist anymore", "suggested_booking_link": ""}
    r = brain.parse_response(fake_response(json.dumps(good)))
    assert (r.escalate_to, r.area, r.escalation_kind) == ("lori-dee", "hair", "can't assist anymore")
    bad = dict(good, escalate_to="the cat", area="feet", escalation_kind="whatever")
    r = brain.parse_response(fake_response(json.dumps(bad)))
    assert (r.escalate_to, r.area, r.escalation_kind) == ("", "", "")
    assert brain._safe_escalation("x").escalation_kind == "can't assist anymore"


# ---------------------------------------------------------------------------
# The tool loop
# ---------------------------------------------------------------------------


FINAL = json.dumps({"reply": "We have 10am or 1.30 Friday?", "escalate": False, "escalation_reason": "", "escalate_to": "", "suggested_booking_link": ""})


def tool_use_response(name, args, uid="tu1", text="Let me look."):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text), SimpleNamespace(type="tool_use", id=uid, name=name, input=args)],
        stop_reason="tool_use",
        stop_details=None,
    )


def test_empty_text_block_in_a_tool_turn_is_not_echoed_back():
    """Live failure 2026-10-20: the API rejects `text: ""` sent back, so the turn must carry only the tool call."""
    client = FakeClient([tool_use_response("check_availability", {"service": "x", "people": ["Jess"], "dates": ["2026-10-24"]}, text=""), fake_response(FINAL)])
    brain.ask("SYSTEM", [], "Saturday?", tools={"check_availability": lambda a: "nothing free"}, client=client)
    assistant_turn = client.requests[1]["messages"][-2]
    assert assistant_turn["content"] == [{"type": "tool_use", "id": "tu1", "name": "check_availability", "input": {"service": "x", "people": ["Jess"], "dates": ["2026-10-24"]}}]


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})  # snapshot; the loop appends to the same list
        return self.responses.pop(0)


def test_ask_runs_the_tool_and_feeds_the_result_back():
    client = FakeClient([tool_use_response("check_availability", {"service": "Gel polish", "people": ["Jess"], "dates": ["2026-10-23"]}), fake_response(FINAL)])
    seen = []

    def lookup(args):
        seen.append(args)
        return "Gel polish with Jess, Fri 23 Oct: 10am, 1:30pm"

    reply = brain.ask("SYSTEM", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hey"}], "Friday?",
                      context="Today is Tuesday 20 October 2026.", tools={"check_availability": lookup}, client=client)

    assert reply.reply == "We have 10am or 1.30 Friday?" and reply.escalate is False
    assert seen == [{"service": "Gel polish", "people": ["Jess"], "dates": ["2026-10-23"]}]
    first, second = client.requests
    assert first["tools"] == [brain.AVAILABILITY_TOOL]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"} and first["system"][1]["text"].startswith("Today is")
    assert first["messages"][-1] == {"role": "user", "content": "Friday?"}
    # Second round carries the assistant's tool call and our result, in order
    assert second["messages"][-2]["role"] == "assistant"
    assert second["messages"][-2]["content"][1] == {"type": "tool_use", "id": "tu1", "name": "check_availability", "input": seen[0]}
    assert second["messages"][-1] == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "Gel polish with Jess, Fri 23 Oct: 10am, 1:30pm"}]}


def test_ask_without_tools_sends_none_and_no_context_block():
    client = FakeClient([fake_response(FINAL)])
    brain.ask("SYSTEM", [], "hi", client=client)
    req = client.requests[0]
    assert "tools" not in req and len(req["system"]) == 1


def test_tool_failure_is_told_to_the_model_not_raised():
    client = FakeClient([tool_use_response("check_availability", {"service": "x", "people": [], "dates": []}), fake_response(FINAL)])

    def boom(args):
        raise ConnectionError("fresha down")

    reply = brain.ask("SYSTEM", [], "Friday?", tools={"check_availability": boom}, client=client)
    assert reply.escalate is False
    assert client.requests[1]["messages"][-1]["content"][0]["content"] == "check_availability failed: ConnectionError"


def test_ask_gives_up_after_too_many_tool_rounds():
    loops = [tool_use_response("check_availability", {}, uid=f"t{i}") for i in range(brain.MAX_TOOL_ROUNDS + 1)]
    client = FakeClient(loops + [fake_response(FINAL)])
    reply = brain.ask("SYSTEM", [], "Friday?", tools={"check_availability": lambda a: "nothing free"}, client=client)
    assert reply.escalate is True and reply.reply == brain.SAFE_REPLY and reply.escalate_to == "jess"
    assert len(client.requests) == brain.MAX_TOOL_ROUNDS + 1


def test_api_failure_is_a_safe_escalation():
    class Dead:
        beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("503"))))

    reply = brain.ask("SYSTEM", [], "hi", client=Dead())
    assert reply.escalate is True and reply.reply == brain.SAFE_REPLY


def test_patch_test_tool_and_kind_exist():
    assert "patch test" in brain.ESCALATION_KINDS
    assert brain.TOOL_DEFINITIONS["patch_test_status"]["input_schema"]["required"] == ["client_name"]
    assert list(brain.TOOL_DEFINITIONS) == ["check_availability", "patch_test_status", "book_appointment", "cancel_appointment"]
