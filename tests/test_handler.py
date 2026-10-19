import json

import pytest

from bot import brain, escalation, handler, meta
from bot.state import Conversation, ConversationStore


class MemoryStore(ConversationStore):
    def __init__(self):
        super().__init__(table=object())
        self.items: dict[str, Conversation] = {}

    def load(self, sender_id):
        c = self.items.get(sender_id)
        return c if c else Conversation(sender_id=sender_id)

    def save(self, convo):
        self.items[convo.sender_id] = convo


def inbound(text="Can I book nails?", mid="m1", sender="psid1", channel="messenger"):
    return meta.InboundMessage(
        channel=channel, sender_id=sender, recipient_id="page1",
        message_id=mid, text=text, timestamp_ms=0,
    )


@pytest.fixture
def wired(monkeypatch):
    """Stub everything that talks to the outside world and record calls.
    Default: simple mode, test mode off, page token present."""
    calls = {"ask": [], "sent": [], "escalated": [], "noticed": []}
    monkeypatch.setattr(handler, "secrets", lambda: {"page_token": "tok", "app_secret": "s", "verify_token": "v"})
    monkeypatch.setattr(handler, "system_prompt", lambda: "SYSTEM")
    monkeypatch.setattr(handler, "MODE", "simple")
    monkeypatch.setattr(handler, "TEST_MODE", False)
    monkeypatch.setattr(handler, "CHANNEL", "")

    def fake_ask(system, history, text):
        calls["ask"].append((history, text))
        if "refund" in text.lower():
            return brain.BotReply(reply="Let me check that.", escalate=True, escalation_reason="Refund request")
        return brain.BotReply(reply="Here's the link.", escalate=False)

    monkeypatch.setattr(brain, "ask", fake_ask)
    monkeypatch.setattr(meta, "send_text", lambda rid, text, token, **kw: calls["sent"].append((rid, text)))
    monkeypatch.setattr(escalation, "notify", lambda convo, reason, text: calls["escalated"].append((convo.sender_id, reason)))
    monkeypatch.setattr(
        escalation, "notify_new_message",
        lambda convo, text, ts=0, reply=None: calls["noticed"].append((convo.sender_id, text, reply)),
    )
    return calls


# ---------------------------------------------------------------------------
# Simple mode: the two bots that just talk back
# ---------------------------------------------------------------------------


def test_simple_mode_acknowledges_and_records(wired):
    store = MemoryStore()
    handler.process_message(inbound("Hello there", mid="m1"), store)

    assert wired["sent"] == [("psid1", 'Hi, this is the TLG messenger test bot. I received "Hello there".')]
    assert wired["ask"] == [] and wired["escalated"] == []
    assert wired["noticed"] == [("psid1", "Hello there", 'Hi, this is the TLG messenger test bot. I received "Hello there".')]
    convo = store.items["psid1"]
    assert convo.history[0] == {"role": "user", "content": "Hello there"}
    assert convo.history[1]["role"] == "assistant"
    assert convo.has_seen("m1") and convo.handed_to_jess is False


def test_simple_mode_names_the_channel_and_handles_no_text(wired):
    store = MemoryStore()
    handler.process_message(inbound("", mid="m1", channel="instagram"), store)
    assert wired["sent"] == [("psid1", "Hi, this is the TLG instagram test bot. I received a message with no text.")]


def test_simple_mode_without_page_token_logs_instead_of_sending(wired, monkeypatch):
    monkeypatch.setattr(handler, "secrets", lambda: {"page_token": "", "app_secret": "s", "verify_token": "v"})
    store = MemoryStore()
    handler.process_message(inbound("Hi", mid="m1"), store)
    assert wired["sent"] == []
    assert wired["noticed"] == [("psid1", "Hi", None)]  # notice says nothing was sent
    assert store.items["psid1"].has_seen("m1")


def test_duplicate_delivery_is_ignored(wired):
    store = MemoryStore()
    handler.process_message(inbound(mid="m1"), store)
    handler.process_message(inbound(mid="m1"), store)
    assert len(wired["sent"]) == 1


# ---------------------------------------------------------------------------
# Test mode: only the trigger word opens the gate
# ---------------------------------------------------------------------------


def test_test_mode_answers_only_the_trigger_word(wired, monkeypatch):
    monkeypatch.setattr(handler, "TEST_MODE", True)
    store = MemoryStore()
    handler.process_message(inbound("Hi, do you do lashes?", mid="m1"), store)
    handler.process_message(inbound("BootyCall do you do lashes?", mid="m2"), store)
    handler.process_message(inbound("  bootycall", mid="m3"), store)
    handler.process_message(inbound("I said bootycall later", mid="m4"), store)

    assert wired["sent"] == [
        ("psid1", 'Hi, this is the TLG messenger test bot. I received "do you do lashes?".'),
        ("psid1", "Hi, this is the TLG messenger test bot. I received a message with no text."),
    ]
    convo = store.items["psid1"]
    assert all(convo.has_seen(m) for m in ("m1", "m2", "m3", "m4"))  # ignored ones are still stored
    assert convo.history[0] == {"role": "user", "content": "Hi, do you do lashes?"}
    assert wired["noticed"][0][1] == "do you do lashes?"  # the word never reaches anyone downstream


def test_test_mode_off_means_no_trigger_needed(wired, monkeypatch):
    monkeypatch.setattr(handler, "TEST_MODE", False)
    store = MemoryStore()
    handler.process_message(inbound("bootycall hi", mid="m1"), store)
    assert wired["sent"] == [("psid1", 'Hi, this is the TLG messenger test bot. I received "bootycall hi".')]


def test_test_mode_gates_claude_modes_too(wired, monkeypatch):
    monkeypatch.setattr(handler, "TEST_MODE", True)
    monkeypatch.setattr(handler, "MODE", "live")
    store = MemoryStore()
    handler.process_message(inbound("Can I book nails?", mid="m1"), store)
    assert wired["ask"] == [] and wired["sent"] == []
    handler.process_message(inbound("bootycall Can I book nails?", mid="m2"), store)
    assert wired["ask"][0][1] == "Can I book nails?"
    assert wired["sent"] == [("psid1", "Here's the link.")]


# ---------------------------------------------------------------------------
# Claude modes (unchanged behaviour, for when the framework comes back)
# ---------------------------------------------------------------------------


def test_live_mode_sends_reply_and_records_history(wired, monkeypatch):
    monkeypatch.setattr(handler, "MODE", "live")
    store = MemoryStore()
    handler.process_message(inbound(), store)

    assert wired["sent"] == [("psid1", "Here's the link.")]
    assert wired["escalated"] == []
    convo = store.items["psid1"]
    assert convo.history == [
        {"role": "user", "content": "Can I book nails?"},
        {"role": "assistant", "content": "Here's the link."},
    ]
    assert convo.has_seen("m1")
    assert convo.handed_to_jess is False


def test_history_is_passed_on_next_turn(wired, monkeypatch):
    monkeypatch.setattr(handler, "MODE", "live")
    store = MemoryStore()
    handler.process_message(inbound("Hi", mid="m1"), store)
    handler.process_message(inbound("Gel nails please", mid="m2"), store)
    history, text = wired["ask"][1]
    assert text == "Gel nails please"
    assert history[0] == {"role": "user", "content": "Hi"}


def test_escalation_locks_thread_in_live_mode(wired, monkeypatch):
    monkeypatch.setattr(handler, "MODE", "live")
    store = MemoryStore()
    handler.process_message(inbound("I want a refund", mid="m1"), store)
    assert wired["escalated"] == [("psid1", "Refund request")]
    assert wired["sent"] == [("psid1", "Let me check that.")]
    assert store.items["psid1"].handed_to_jess is True

    handler.process_message(inbound("Hello??", mid="m2"), store)
    assert len(wired["sent"]) == 1  # bot stayed quiet
    assert len(wired["ask"]) == 1


def test_shadow_mode_never_sends_to_client(wired, monkeypatch):
    monkeypatch.setattr(handler, "MODE", "shadow")
    store = MemoryStore()
    handler.process_message(inbound(), store)
    handler.process_message(inbound("I want a refund", mid="m2"), store)
    assert wired["sent"] == []
    assert len(wired["escalated"]) == 2
    assert store.items["psid1"].handed_to_jess is False


def test_attachment_only_message_escalates_in_live_mode(wired, monkeypatch):
    monkeypatch.setattr(handler, "MODE", "live")
    store = MemoryStore()
    handler.process_message(inbound(text=""), store)
    assert wired["escalated"] == [("psid1", "Non-text message")]
    assert wired["ask"] == []


# ---------------------------------------------------------------------------
# The HTTP layer
# ---------------------------------------------------------------------------


def test_webhook_ignores_the_other_channel(wired, monkeypatch):
    monkeypatch.setattr(handler, "CHANNEL", "instagram")
    monkeypatch.setattr(meta, "verify_signature", lambda body, header, secret: True)
    store = MemoryStore()
    body = {
        "object": "page",
        "entry": [{"messaging": [{"sender": {"id": "psid9"}, "recipient": {"id": "page1"}, "timestamp": 1,
                                  "message": {"mid": "m9", "text": "hello"}}]}],
    }
    event = {"requestContext": {"http": {"method": "POST"}}, "headers": {}, "body": json.dumps(body)}
    assert handler._handle_webhook(event, store=store)["statusCode"] == 200
    assert store.items == {} and wired["sent"] == []


def test_lambda_handler_refuses_an_unknown_mode(wired, monkeypatch):
    monkeypatch.setattr(handler, "MODE", "yolo")
    with pytest.raises(RuntimeError, match="BOT_MODE"):
        handler.lambda_handler({"requestContext": {"http": {"method": "GET"}}})


def test_bad_signature_rejected(wired):
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"x-hub-signature-256": "sha256=nope"},
        "body": "{}",
    }
    assert handler.lambda_handler(event)["statusCode"] == 403


def test_verify_handshake(wired):
    event = {
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {"hub.mode": "subscribe", "hub.verify_token": "v", "hub.challenge": "777"},
    }
    resp = handler.lambda_handler(event)
    assert resp["statusCode"] == 200
    assert resp["body"] == "777"
