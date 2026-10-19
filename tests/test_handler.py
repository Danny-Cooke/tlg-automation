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


def inbound(text="Can I book nails?", mid="m1", sender="psid1"):
    return meta.InboundMessage(
        channel="messenger", sender_id=sender, recipient_id="page1",
        message_id=mid, text=text, timestamp_ms=0,
    )


@pytest.fixture
def wired(monkeypatch):
    """Stub everything that talks to the outside world and record calls."""
    calls = {"ask": [], "sent": [], "escalated": []}
    monkeypatch.setattr(handler, "secrets", lambda: {"page_token": "tok", "app_secret": "s", "verify_token": "v"})
    monkeypatch.setattr(handler, "system_prompt", lambda: "SYSTEM")

    def fake_ask(system, history, text):
        calls["ask"].append((history, text))
        if "refund" in text.lower():
            return brain.BotReply(reply="Let me check that.", escalate=True, escalation_reason="Refund request")
        return brain.BotReply(reply="Here's the link.", escalate=False)

    monkeypatch.setattr(brain, "ask", fake_ask)
    monkeypatch.setattr(meta, "send_text", lambda rid, text, token: calls["sent"].append((rid, text)))
    monkeypatch.setattr(escalation, "notify", lambda convo, reason, text: calls["escalated"].append((convo.sender_id, reason)))
    return calls


def test_live_mode_sends_reply_and_records_history(wired, monkeypatch):
    monkeypatch.setattr(handler, "SHADOW_MODE", False)
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
    monkeypatch.setattr(handler, "SHADOW_MODE", False)
    store = MemoryStore()
    handler.process_message(inbound("Hi", mid="m1"), store)
    handler.process_message(inbound("Gel nails please", mid="m2"), store)
    history, text = wired["ask"][1]
    assert text == "Gel nails please"
    assert history[0] == {"role": "user", "content": "Hi"}


def test_duplicate_delivery_is_ignored(wired, monkeypatch):
    monkeypatch.setattr(handler, "SHADOW_MODE", False)
    store = MemoryStore()
    handler.process_message(inbound(mid="m1"), store)
    handler.process_message(inbound(mid="m1"), store)
    assert len(wired["sent"]) == 1


def test_escalation_locks_thread_in_live_mode(wired, monkeypatch):
    monkeypatch.setattr(handler, "SHADOW_MODE", False)
    store = MemoryStore()
    handler.process_message(inbound("I want a refund", mid="m1"), store)
    assert wired["escalated"] == [("psid1", "Refund request")]
    assert wired["sent"] == [("psid1", "Let me check that.")]
    assert store.items["psid1"].handed_to_jess is True

    handler.process_message(inbound("Hello??", mid="m2"), store)
    assert len(wired["sent"]) == 1  # bot stayed quiet
    assert len(wired["ask"]) == 1


def test_shadow_mode_never_sends_to_client(wired, monkeypatch):
    monkeypatch.setattr(handler, "SHADOW_MODE", True)
    store = MemoryStore()
    handler.process_message(inbound(), store)
    handler.process_message(inbound("I want a refund", mid="m2"), store)
    assert wired["sent"] == []
    assert len(wired["escalated"]) == 2
    assert store.items["psid1"].handed_to_jess is False


def test_attachment_only_message_escalates(wired, monkeypatch):
    monkeypatch.setattr(handler, "SHADOW_MODE", False)
    store = MemoryStore()
    handler.process_message(inbound(text=""), store)
    assert wired["escalated"] == [("psid1", "Non-text message")]
    assert wired["ask"] == []


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
