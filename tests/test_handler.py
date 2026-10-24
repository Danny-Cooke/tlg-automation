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


def inbound(text="Can I book nails?", mid="m1", sender="psid1", channel="messenger", attachments=0):
    return meta.InboundMessage(
        channel=channel, sender_id=sender, recipient_id="page1",
        message_id=mid, text=text, timestamp_ms=0, attachments=attachments,
    )


@pytest.fixture
def wired(monkeypatch):
    """Stub everything that talks to the outside world and record calls.
    Default: simple mode, test mode off, page token present."""
    calls = {"ask": [], "sent": [], "escalated": [], "noticed": [], "profile": [], "context": []}
    monkeypatch.setattr(handler, "secrets", lambda: {"page_token": "tok", "app_secret": "s", "verify_token": "v"})
    monkeypatch.setattr(handler, "system_prompt", lambda: "SYSTEM")
    monkeypatch.setattr(handler, "tools", lambda *a: {"check_availability": lambda args: "nothing free"})
    monkeypatch.setattr(handler, "MODE", "simple")
    monkeypatch.setattr(handler, "TEST_MODE", False)
    monkeypatch.setattr(handler, "CHANNEL", "")
    monkeypatch.setattr(handler, "REPLY_DELAY_SECONDS", 0)
    calls["actions"] = []
    monkeypatch.setattr(meta, "send_action", lambda rid, action, token, **kw: calls["actions"].append((rid, action)))
    calls["slept"] = []
    monkeypatch.setattr(handler.time, "sleep", lambda s: calls["slept"].append(s))

    def fake_profile(sender_id, token, **kw):
        calls["profile"].append(sender_id)
        return {"first_name": "Danny", "last_name": "Cooke"}

    monkeypatch.setattr(meta, "user_profile", fake_profile)

    def fake_ask(system, history, text, **kw):
        calls["ask"].append((history, text))
        calls["context"].append(kw.get("context", ""))
        if "refund" in text.lower():
            return brain.BotReply(reply="Let me check that.", escalate=True, escalation_reason="Refund request", escalate_to="jess")
        return brain.BotReply(reply="Here's the link.", escalate=False)

    monkeypatch.setattr(brain, "ask", fake_ask)
    monkeypatch.setattr(meta, "send_text", lambda rid, text, token, **kw: calls["sent"].append((rid, text)))
    monkeypatch.setattr(escalation, "notify", lambda convo, reason, text, to="", **kw: calls["escalated"].append((convo.sender_id, reason, to)))
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


def test_reply_waits_with_typing_indicator(wired, monkeypatch):
    monkeypatch.setattr(handler, "REPLY_DELAY_SECONDS", 10)
    store = MemoryStore()
    handler.process_message(inbound("Hi", mid="m1"), store)
    assert wired["actions"] == [("psid1", "typing_on")]
    assert len(wired["slept"]) == 1 and 9.5 < wired["slept"][0] <= 10
    assert wired["sent"] == [("psid1", 'Hi, this is the TLG messenger test bot. I received "Hi".')]


def test_time_spent_thinking_counts_towards_the_pause(wired, monkeypatch):
    """Ten seconds from when the message arrived, not ten seconds after Claude answers."""
    monkeypatch.setattr(handler, "REPLY_DELAY_SECONDS", 10)
    handler._send("psid1", "hi", started=handler.time.monotonic() - 4)
    assert len(wired["slept"]) == 1 and 5.5 < wired["slept"][0] <= 6
    wired["slept"].clear()
    handler._send("psid1", "hi", started=handler.time.monotonic() - 30)
    assert wired["slept"] == []  # already slower than a person; send now


def test_message_is_marked_seen_before_the_wait(wired, monkeypatch):
    """A Meta retry that lands during the pause must find the message already seen."""
    monkeypatch.setattr(handler, "REPLY_DELAY_SECONDS", 10)
    store = MemoryStore()
    seen_during_sleep = []
    monkeypatch.setattr(handler.time, "sleep", lambda s: seen_during_sleep.append(store.items["psid1"].has_seen("m1")))
    handler.process_message(inbound("Hi", mid="m1"), store)
    assert seen_during_sleep == [True]


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
    handler.process_message(inbound("JoshSmells do you do lashes?", mid="m2"), store)
    handler.process_message(inbound("  joshsmells", mid="m3"), store)
    handler.process_message(inbound("I said joshsmells later", mid="m4"), store)

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
    handler.process_message(inbound("joshsmells hi", mid="m1"), store)
    assert wired["sent"] == [("psid1", 'Hi, this is the TLG messenger test bot. I received "joshsmells hi".')]


def test_test_mode_gates_claude_modes_too(wired, monkeypatch):
    monkeypatch.setattr(handler, "TEST_MODE", True)
    monkeypatch.setattr(handler, "MODE", "live")
    store = MemoryStore()
    handler.process_message(inbound("Can I book nails?", mid="m1"), store)
    assert wired["ask"] == [] and wired["sent"] == []
    handler.process_message(inbound("joshsmells Can I book nails?", mid="m2"), store)
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
    assert wired["escalated"] == [("psid1", "Refund request", "jess")]
    assert wired["sent"] == [("psid1", "Let me check that.")]
    assert store.items["psid1"].handed_to_jess is True

    handler.process_message(inbound("Hello??", mid="m2"), store)
    assert len(wired["sent"]) == 1  # bot stayed quiet
    assert len(wired["ask"]) == 1


def test_booking_handover_keeps_the_bot_talking(wired, monkeypatch):
    """A slot agreed in chat is told to the team, but the client is mid-conversation (user, 2026-10-20)."""
    monkeypatch.setattr(handler, "MODE", "live")
    calls = wired

    def ask(system, history, text, **kw):
        if "book" in text.lower():
            return brain.BotReply(reply="I'll get the girls to pop you in x", escalate=True, escalation_reason="Sav Fri 2.15",
                                  escalate_to="jess", area="nails", escalation_kind="booking")
        return brain.BotReply(reply="Still here x", escalate=False)

    monkeypatch.setattr(brain, "ask", ask)
    store = MemoryStore()
    handler.process_message(inbound("book me in", mid="m1"), store)
    assert store.items["psid1"].handed_to_jess is False
    handler.process_message(inbound("actually can we do thursday", mid="m2"), store)
    assert calls["sent"][-1] == ("psid1", "Still here x")
    assert handler.LOCKING_KINDS == {"complaint", "cancellation fee", "quote", "can't assist anymore", ""}


def test_hair_handovers_lock_the_thread_whatever_the_kind(wired, monkeypatch):
    """User, 2026-10-24: hair for Lori-Dee is hers to deal with completely in the inbox,
    Sophie's clients go to her WhatsApp; the bot goes quiet either way. A hair complaint
    is Jess's and locks like any complaint."""
    monkeypatch.setattr(handler, "MODE", "live")

    def ask(system, history, text, **kw):
        if "complain" in text.lower():
            return brain.BotReply(reply="So sorry lovely, let me get Jess x", escalate=True, escalation_reason="Unhappy with colour",
                                  escalate_to="jess", area="hair", escalation_kind="complaint")
        return brain.BotReply(reply="Hiya, that's one for Lori our hairdresser x", escalate=True, escalation_reason="Hair with Lori-Dee: cut Saturday",
                              escalate_to="lori-dee", area="hair", escalation_kind="booking")

    monkeypatch.setattr(brain, "ask", ask)
    store = MemoryStore()
    handler.process_message(inbound("can I book a cut with lori saturday", mid="m1"), store)
    assert wired["escalated"][-1] == ("psid1", "Hair with Lori-Dee: cut Saturday", "lori-dee")
    assert store.items["psid1"].handed_to_jess is True
    handler.process_message(inbound("hello?", mid="m2"), store)
    assert len(wired["sent"]) == 1  # Lori's thread now

    store = MemoryStore()
    handler.process_message(inbound("I want to complain about my colour", mid="m3", sender="psid2"), store)
    assert wired["escalated"][-1] == ("psid2", "Unhappy with colour", "jess") and store.items["psid2"].handed_to_jess is True
    assert handler.locks("booking", "hair") and not handler.locks("booking", "nails") and handler.locks("complaint", "hair")


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
    assert wired["escalated"] == [("psid1", "Non-text message (picture or attachment)", "jess")]
    assert wired["ask"] == []
    assert wired["sent"] == [("psid1", brain.SAFE_REPLY)] and brain.SAFE_REPLY == "Hi lovely, give me a little time to have a think and I'll get back to you x"
    assert store.items["psid1"].handed_to_jess is True  # a quote hand-over locks the thread


def test_a_picture_with_text_is_flagged_to_the_model(wired, monkeypatch):
    monkeypatch.setattr(handler, "MODE", "live")
    store = MemoryStore()
    handler.process_message(inbound("how much would a set of these cost?", attachments=1), store)
    assert wired["ask"][0][1] == "how much would a set of these cost? [1 picture(s) attached]"


# ---------------------------------------------------------------------------
# Name, context and the availability tool
# ---------------------------------------------------------------------------


def test_name_is_fetched_once_and_given_to_the_model(wired, monkeypatch):
    monkeypatch.setattr(handler, "MODE", "live")
    store = MemoryStore()
    handler.process_message(inbound("Hi", mid="m1"), store)
    handler.process_message(inbound("Any Friday slots?", mid="m2"), store)
    assert wired["profile"] == ["psid1"]  # second message reuses the stored name
    assert store.items["psid1"].client_name == "Danny Cooke"
    assert "Danny Cooke" in wired["context"][0] and "Today is" in wired["context"][0]
    assert "Channel: messenger" in wired["context"][1]


def test_message_is_claimed_before_claude_is_asked(wired, monkeypatch):
    """A Meta retry that arrives during a 20 second Claude call must find the message seen."""
    monkeypatch.setattr(handler, "MODE", "live")
    store = MemoryStore()
    seen_when_asked = []
    real_ask = brain.ask

    def spying_ask(system, history, text, **kw):
        seen_when_asked.append(store.items["psid1"].has_seen("m1"))
        return real_ask(system, history, text, **kw)

    monkeypatch.setattr(brain, "ask", spying_ask)
    handler.process_message(inbound("Hi", mid="m1"), store)
    assert seen_when_asked == [True]
    assert store.items["psid1"].seen_message_ids.count("m1") == 1  # record_turn does not double it


def test_live_mode_shows_typing_while_thinking(wired, monkeypatch):
    monkeypatch.setattr(handler, "MODE", "live")
    monkeypatch.setattr(handler, "REPLY_DELAY_SECONDS", 10)
    store = MemoryStore()
    handler.process_message(inbound("Hi", mid="m1"), store)
    assert wired["actions"][0] == ("psid1", "typing_on")  # before the Claude call


def test_context_block_wording():
    import datetime as dt

    convo = Conversation(sender_id="p", channel="instagram", client_name="Sam Jones")
    text = handler.context_block(convo, now=dt.datetime(2026, 10, 23, 9, 5, tzinfo=handler.SALON_TZ))
    assert text.startswith("Today is Friday 23 October 2026, 09:05 in Shrewsbury.")
    assert "Sam Jones" in text and "Channel: instagram." in text
    assert "not known" in handler.context_block(Conversation(sender_id="p"))


def test_run_availability_maps_first_names_to_fresha_ids(monkeypatch):
    from bot import availability
    from bot.config import SalonConfig, StaffMember

    cfg = SalonConfig(salon_name="S", address="", phone="", opening_hours={}, general_booking_link="", services=[],
                      staff=[StaffMember(name="Jess", role="m", employee_id="3440861"), StaffMember(name="Lori-Dee", role="h")],
                      venue_url="https://www.fresha.com/en-GB/a/x")
    seen = {}

    def fake_check(http, venue_url, *, service, people, dates):
        seen.update(venue_url=venue_url, service=service, people=people, dates=dates)
        return [availability.PersonAvailability("Jess", service, {"2026-10-23": ["10am"]})]

    monkeypatch.setattr(availability, "check", fake_check)
    text = handler.run_availability({"service": "Gel polish", "people": ["jess", "lori", "Bob"], "dates": ["2026-10-23"]}, cfg, http=object())
    assert seen == {"venue_url": "https://www.fresha.com/en-GB/a/x", "service": "Gel polish", "people": [("Jess", "3440861")], "dates": ["2026-10-23"]}
    assert text.splitlines() == ["Not on the team list or not bookable online: lori, Bob", "Gel polish with Jess, Fri 23 Oct: 10am"]


def test_tools_are_off_without_a_venue_url(monkeypatch):
    from bot.config import SalonConfig

    monkeypatch.setattr(handler, "salon", lambda: SalonConfig(salon_name="S", address="", phone="", opening_hours={}, general_booking_link="", services=[], staff=[]))
    assert handler.tools() == {}


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


def test_a_thread_with_lori_dee_is_still_read_and_nails_get_the_bot_back(wired, monkeypatch):
    """User, 2026-10-24: after a hair hand-over the bot keeps reading; hair messages and
    replies to Lori are left alone, a nails question is answered. With Jess the bot is silent."""
    monkeypatch.setattr(handler, "MODE", "live")
    contexts = []

    def ask(system, history, text, context="", **kw):
        contexts.append(context)
        low = text.lower()
        if "nails" in low:
            return brain.BotReply(reply="Absolutely lovely, gel polish is from £34 xx", escalate=False)
        if "cut" in low:
            return brain.BotReply(reply="Hiya, that's one for Lori x", escalate=True, escalation_reason="Hair with Lori-Dee: cut",
                                  escalate_to="lori-dee", area="hair", escalation_kind="booking")
        return brain.BotReply(reply="", escalate=False)  # a reply to Lori: send nothing

    monkeypatch.setattr(brain, "ask", ask)
    store = MemoryStore()
    handler.process_message(inbound("can I book a cut with lori", mid="m1"), store)
    convo = store.items["psid1"]
    assert convo.handed_to_jess and convo.handed_to == "lori-dee" and convo.handed_area == "hair" and convo.watching()

    handler.process_message(inbound("yes 2pm is fine", mid="m2"), store)  # for Lori
    assert len(wired["sent"]) == 1 and "This thread is with Lori-Dee for hair" in contexts[-1]
    assert convo.history[-1] == {"role": "user", "content": "yes 2pm is fine"}  # kept as context, no bot turn

    handler.process_message(inbound("also could I get my nails done while I'm in?", mid="m3"), store)
    assert wired["sent"][-1] == ("psid1", "Absolutely lovely, gel polish is from £34 xx")
    assert convo.handed_to_jess and convo.handed_to == "lori-dee"  # Lori still has the hair

    handler.process_message(inbound("and a trim on the fringe", mid="m4"), store)  # hair again: theirs, no second hand-over
    assert len(wired["sent"]) == 2 and len(wired["escalated"]) == 1

    # With Jess (a complaint) nothing is read or answered.
    convo.hand_over("jess", "nails")
    assert not convo.watching()
    before = len(contexts)
    handler.process_message(inbound("nails please", mid="m5"), store)
    assert len(contexts) == before and len(wired["sent"]) == 2


def test_handover_fields_round_trip_through_the_table():
    class Table:
        def __init__(self):
            self.item = None

        def put_item(self, Item):
            self.item = Item

        def get_item(self, Key):
            return {"Item": self.item} if self.item else {}

        def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
            assert "handed_to = :e" in UpdateExpression
            self.item.update(handed_to_jess=False, handed_to="", handed_area="")

    table = Table()
    store = ConversationStore(table=table)
    c = Conversation(sender_id="p")
    c.hand_over("carmen", "tattoos")
    store.save(c)
    back = store.load("p")
    assert back.handed_to == "carmen" and back.handed_area == "tattoos" and back.watching()
    store.clear_handover("p")
    assert store.load("p").handed_to_jess is False and store.load("p").handed_to == ""
