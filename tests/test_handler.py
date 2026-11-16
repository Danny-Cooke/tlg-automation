import datetime as dt
import json

import pytest

from bot import brain, escalation, handler, meta
from bot.state import Conversation, ConversationStore


class MemoryStore(ConversationStore):
    """The conversation rows and, apart from them as in the table, what the team sent."""

    def __init__(self):
        super().__init__(table=object())
        self.items: dict[str, Conversation] = {}
        self.team: dict[str, list[dict]] = {}

    def load(self, sender_id):
        c = self.items.get(sender_id) or Conversation(sender_id=sender_id)
        c.team_turns = list(self.team.get(sender_id, []))
        c.team_last_at = self.team_last_at(sender_id)
        return c

    def save(self, convo):
        self.items[convo.sender_id] = convo

    def note_team(self, sender_id, content, at, message_id=""):
        self.team.setdefault(sender_id, []).append({"at": at, "content": content, "mid": message_id})

    def team_last_at(self, sender_id):
        return max((t["at"] for t in self.team.get(sender_id, [])), default=0)


def turns(convo):
    """The stored turns without the time each carries."""
    return [{"role": t["role"], "content": t["content"]} for t in convo.history]


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
    calls["pictures"], calls["areas"] = [], []
    monkeypatch.setattr(meta, "fetch_images", lambda urls, **kw: [("image/jpeg", "QUJD")] * len(tuple(urls)))

    def fake_picture_area(history, images, **kw):
        calls["pictures"].append((list(history), images))
        return "nails" if any("acrylic" in t["content"] for t in history) else ""

    monkeypatch.setattr(brain, "picture_area", fake_picture_area)
    monkeypatch.setattr(meta, "send_text", lambda rid, text, token, **kw: calls["sent"].append((rid, text)))

    def fake_notify(convo, reason, text, to="", **kw):
        calls["escalated"].append((convo.sender_id, reason, to))
        calls["areas"].append(kw.get("area", ""))

    monkeypatch.setattr(escalation, "notify", fake_notify)
    monkeypatch.setattr(
        escalation, "notify_new_message",
        lambda convo, text, ts=0, reply=None: calls["noticed"].append((convo.sender_id, text, reply)),
    )
    return calls


# ---------------------------------------------------------------------------
# Simple mode: the two bots that just talk back
# ---------------------------------------------------------------------------


class SentinelTable:
    """Just enough DynamoDB for claim_daily: a conditional put on the sentinel row."""

    def __init__(self):
        self.rows = {}

    def put_item(self, Item, ConditionExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        from botocore.exceptions import ClientError
        assert ConditionExpression == "attribute_not_exists(sender_id) OR #d < :day" and ExpressionAttributeNames == {"#d": "day"}
        old = self.rows.get(Item["sender_id"])
        if old is not None and not old["day"] < ExpressionAttributeValues[":day"]:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.rows[Item["sender_id"]] = Item


def test_fresha_session_nag_posts_once_a_day_from_three_days_out():
    """Promised in docs/setup.md, built 2026-10-25: the team group hears when the
    Fresha login is about to run out, once a day however many containers start."""
    from bot import fresha_session
    from bot.state import ConversationStore

    store = ConversationStore(SentinelTable())
    posted = []
    now = dt.datetime(2026, 11, 15, 9, 0, tzinfo=dt.timezone.utc)
    far = fresha_session.Session("c", now + dt.timedelta(days=10))
    near = fresha_session.Session("c", now + dt.timedelta(days=2, hours=6))
    nag = lambda session, ok, day: handler.nag_about_session(session, ok, store=store, today=day, post=lambda text: posted.append(text) or True, now=now)  # noqa: E731
    assert nag(far, True, "2026-11-15") is False and posted == []
    assert nag(near, True, "2026-11-15") is True
    assert len(posted) == 1 and "runs out in 2 days" in posted[0] and "fresha_session.py" in posted[0]
    assert nag(near, True, "2026-11-15") is False and len(posted) == 1  # same day: once
    assert nag(near, True, "2026-11-16") and len(posted) == 2  # next day: again
    assert store.table.rows["_fresha-session-nag"]["day"] == "2026-11-16" and store.table.rows["_fresha-session-nag"]["expires_at"] > 0
    assert nag(None, False, "2026-11-17") and "has run out" in posted[-1]
    assert nag(far, False, "2026-11-18") and "rejecting the bot's login" in posted[-1]
    assert nag(fresha_session.Session("c", None), True, "2026-11-19") is False and len(posted) == 4  # no expiry known: nothing to say


def test_session_check_survives_a_broken_nag(monkeypatch):
    from bot import fresha_session

    handler.fresha_session_check.cache_clear()
    monkeypatch.setattr(fresha_session, "get", lambda **kw: fresha_session.Session("c", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)))
    monkeypatch.setattr(fresha_session, "probe", lambda s: "Shrewsbury")
    monkeypatch.setattr(handler, "nag_about_session", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("dynamo down")))
    assert handler.fresha_session_check() is True
    handler.fresha_session_check.cache_clear()


def test_simple_mode_acknowledges_and_records(wired):
    store = MemoryStore()
    handler.process_message(inbound("Hello there", mid="m1"), store)

    assert wired["sent"] == [("psid1", 'Hi, this is the TLG messenger test bot. I received "Hello there".')]
    assert wired["ask"] == [] and wired["escalated"] == []
    assert wired["noticed"] == [("psid1", "Hello there", 'Hi, this is the TLG messenger test bot. I received "Hello there".')]
    convo = store.items["psid1"]
    assert turns(convo)[0] == {"role": "user", "content": "Hello there"} and convo.history[0]["at"] > 0
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
    assert turns(convo)[0] == {"role": "user", "content": "Hi, do you do lashes?"}
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
    assert turns(convo) == [
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
    handler.process_message(inbound("Hi", mid="m0"), store)
    handler.process_message(inbound("I want a refund", mid="m1"), store)
    assert wired["escalated"] == [("psid1", "Refund request", "jess")]
    assert wired["sent"] == [("psid1", "Here's the link."), ("psid1", "Let me check that.")]
    convo = store.items["psid1"]
    assert convo.handed_to_jess is True and convo.handed_to == "jess" and convo.alerted_at > 0

    # User, 2026-11-16: with Jess the thread is still read. What the bot cannot
    # answer gets nothing at all, not a second holding line, and no second post.
    handler.process_message(inbound("any news on my refund?", mid="m2"), store)
    assert len(wired["sent"]) == 2 and len(wired["ask"]) == 3 and len(wired["escalated"]) == 1
    assert "This thread is with Jess for general" in wired["context"][-1]
    assert turns(convo)[-1] == {"role": "user", "content": "any news on my refund?"}

    # What it can answer, it answers; the refund stays with Jess.
    handler.process_message(inbound("what time do you close today?", mid="m3"), store)
    assert wired["sent"][-1] == ("psid1", "Here's the link.") and convo.handed_to_jess is True

    # Still unanswered half a day on: the team are told once more, as "waiting on you".
    posted = []
    monkeypatch.setattr(escalation, "notify", lambda convo, reason, text, **kw: posted.append((reason, kw.get("kind"), kw.get("to"))))
    convo.alerted_at -= handler.NUDGE_GAP_SECONDS + 60
    monkeypatch.setattr(brain, "ask", lambda *a, **kw: brain.BotReply(reply="", escalate=False))
    handler.process_message(inbound("hello??", mid="m4"), store)
    handler.process_message(inbound("anyone there", mid="m5"), store)
    assert posted == [("The client has written again and is waiting on a reply", "waiting on you", "jess")]
    assert len(wired["sent"]) == 3


def test_opening_message_the_bot_cannot_help_with_gets_no_reply(wired, monkeypatch):
    """User, 2026-10-29: if the bot has not replied yet and the first message is one it
    cannot help with, it sends nothing; the hand-over goes to Telegram marked
    "no reply sent" and Jess answers first. Mid-thread it still says it will
    speak to Jess (the test above)."""
    monkeypatch.setattr(handler, "MODE", "live")
    posted = []
    monkeypatch.setattr(
        escalation, "notify",
        lambda convo, reason, text, to="", **kw: posted.append((convo.sender_id, reason, kw.get("kind"), kw.get("no_reply"))),
    )
    store = MemoryStore()
    handler.process_message(inbound("I want a refund", mid="m1"), store)
    assert wired["sent"] == []
    assert posted == [("psid1", "Refund request", "", True)]
    convo = store.items["psid1"]
    assert convo.handed_to_jess is True
    assert turns(convo) == [{"role": "user", "content": "I want a refund"}]  # no blank bot turn for the model to see
    assert convo.has_seen("m1")

    handler.process_message(inbound("I want that refund today", mid="m2"), store)
    assert wired["sent"] == [] and len(posted) == 1  # Jess's thread: read, not answered, not posted twice

    # A booking told to the team on an opening message is not "cannot help": the bot keeps talking.
    monkeypatch.setattr(brain, "ask", lambda *a, **kw: brain.BotReply(
        reply="I'll get the girls to pop you in x", escalate=True, escalation_reason="Sav Fri 2.15",
        escalate_to="jess", area="nails", escalation_kind="booking"))
    handler.process_message(inbound("book me sav friday 2.15", mid="m3", sender="psid2"), store)
    assert wired["sent"] == [("psid2", "I'll get the girls to pop you in x")]
    assert posted[-1] == ("psid2", "Sav Fri 2.15", "booking", False)
    assert handler.has_replied(store.items["psid2"]) and not handler.has_replied(store.items["psid1"])


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
    assert handler.LOCKING_KINDS == {"complaint", "cancellation fee", "quote", "can't assist anymore", "enquiry", ""}
    # User, 2026-10-28: a job or competition enquiry gets one line and goes quiet for Jess.
    assert handler.locks("enquiry", "general") and not handler.locks("booking", "general")


def test_hair_handovers_lock_the_thread_whatever_the_kind(wired, monkeypatch):
    """User, 2026-10-24: hair for Lori-Dee is hers to deal with completely in the inbox,
    Sophie's clients go to her WhatsApp; the bot goes quiet either way. A hair complaint
    is Jess's and locks like any complaint."""
    monkeypatch.setattr(handler, "MODE", "live")

    def ask(system, history, text, **kw):
        if "hiya" in text.lower():
            return brain.BotReply(reply="Hey lovely x", escalate=False)
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
    assert wired["sent"] == []  # an opening hair message is Lori's from the start: nothing back (user, 2026-10-29)
    handler.process_message(inbound("hello?", mid="m2"), store)
    assert wired["sent"] == []  # Lori's thread now

    store = MemoryStore()
    handler.process_message(inbound("hiya", mid="m3", sender="psid2"), store)
    handler.process_message(inbound("I want to complain about my colour", mid="m4", sender="psid2"), store)
    assert wired["escalated"][-1] == ("psid2", "Unhappy with colour", "jess") and store.items["psid2"].handed_to_jess is True
    assert wired["sent"][-1] == ("psid2", "So sorry lovely, let me get Jess x")  # mid-thread: say so, then hand over
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
    handler.process_message(inbound("Hi", mid="m0"), store)
    handler.process_message(inbound(text=""), store)
    assert wired["escalated"] == [("psid1", "Non-text message (picture or attachment)", "jess")]
    assert len(wired["ask"]) == 1
    assert wired["sent"][-1] == ("psid1", brain.SAFE_REPLY) and brain.SAFE_REPLY == "Hi lovely, give me a little time to have a think and I'll get back to you x"
    assert store.items["psid1"].handed_to_jess is True  # a quote hand-over locks the thread

    # A bare picture as the first message: nothing back, Jess answers first (user, 2026-10-29).
    handler.process_message(inbound(text="", mid="m2", sender="psid2"), store)
    assert wired["escalated"][-1] == ("psid2", "Non-text message (picture or attachment)", "jess")
    assert all(rid != "psid2" for rid, _ in wired["sent"]) and store.items["psid2"].handed_to_jess is True


def test_a_bare_picture_is_handed_over_with_the_area_it_is_for(wired, monkeypatch):
    # 2026-11-10: a picture sent while booking acrylics reached the team as "General". Now the thread and the picture say.
    monkeypatch.setattr(handler, "MODE", "live")
    store = MemoryStore()
    handler.process_message(inbound("any acrylic slots tomorrow?", mid="m0"), store)
    pic = meta.InboundMessage(channel="messenger", sender_id="psid1", recipient_id="page1", message_id="m1", text="",
                              timestamp_ms=0, attachments=1, image_urls=("https://cdn.example/p.jpg",))
    handler.process_message(pic, store)
    assert wired["areas"] == ["nails"] and wired["escalated"][-1][2] == "jess"  # the label changes, who gets it does not
    history, images = wired["pictures"][0]
    assert history[0]["content"] == "any acrylic slots tomorrow?" and images == [("image/jpeg", "QUJD")]
    assert wired["sent"][-1] == ("psid1", brain.SAFE_REPLY) and store.items["psid1"].handed_area == "nails"
    # Cannot tell, or the lookup blows up: general, and the hand-over still goes out.
    handler.process_message(inbound(text="", mid="m2", sender="psid2"), store)
    assert wired["areas"][-1] == "general"
    monkeypatch.setattr(brain, "picture_area", lambda *a, **k: 1 / 0)
    handler.process_message(inbound(text="", mid="m3", sender="psid3"), store)
    assert wired["areas"][-1] == "general" and wired["escalated"][-1][0] == "psid3"


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
    monkeypatch.setattr(meta, "verify_signature", lambda body, header, *secrets: True)
    store = MemoryStore()
    body = {
        "object": "page",
        "entry": [{"messaging": [{"sender": {"id": "psid9"}, "recipient": {"id": "page1"}, "timestamp": 1,
                                  "message": {"mid": "m9", "text": "hello"}}]}],
    }
    event = {"requestContext": {"http": {"method": "POST"}}, "headers": {}, "body": json.dumps(body)}
    assert handler._handle_webhook(event, store=store)["statusCode"] == 200
    assert store.items == {} and wired["sent"] == []


def test_secrets_use_the_instagram_token_as_it_is(monkeypatch):
    """Instagram Login route (plan job 18): the account's own token comes from its own secret, no Page exchange."""
    import sys

    reads = []

    class SM:
        def get_secret_value(self, SecretId):
            reads.append(SecretId)
            if SecretId == "arn:token":
                return {"SecretString": json.dumps({"access_token": "IGTOKEN", "username": "salon"})}
            return {"SecretString": json.dumps({"app_secret": "ig-secret", "fallback_app_secret": "fb-secret", "verify_token": "v", "page_token": ""})}

    class Boto:
        @staticmethod
        def client(name):
            return SM()

    monkeypatch.setitem(sys.modules, "boto3", Boto)
    monkeypatch.setenv("META_SECRET_ARN", "arn:meta")
    monkeypatch.setenv("META_TOKEN_SECRET_ARN", "arn:token")
    monkeypatch.setattr(meta, "page_token_for", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no exchange on this route")))
    handler.secrets.cache_clear()
    try:
        s = handler.secrets()
    finally:
        handler.secrets.cache_clear()
    assert s["page_token"] == "IGTOKEN" and s["fallback_app_secret"] == "fb-secret"
    assert reads == ["arn:meta", "arn:token"]


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
    assert convo.handed_to_jess and convo.handed_to == "lori-dee" and convo.handed_area == "hair" and convo.handed_kind == "booking"
    assert wired["sent"] == []  # opened with hair: Lori answers first (user, 2026-10-29)
    wired["sent"].append(("psid1", "(Lori's line, sent by hand)"))  # keep the counts below readable

    handler.process_message(inbound("yes 2pm is fine", mid="m2"), store)  # for Lori
    assert len(wired["sent"]) == 1 and "This thread is with Lori-Dee for hair" in contexts[-1]
    assert turns(convo)[-1] == {"role": "user", "content": "yes 2pm is fine"}  # kept as context, no bot turn

    handler.process_message(inbound("also could I get my nails done while I'm in?", mid="m3"), store)
    assert wired["sent"][-1] == ("psid1", "Absolutely lovely, gel polish is from £34 xx")
    assert convo.handed_to_jess and convo.handed_to == "lori-dee"  # Lori still has the hair

    handler.process_message(inbound("and a trim on the fringe", mid="m4"), store)  # hair again: theirs, no second hand-over
    assert len(wired["sent"]) == 2 and len(wired["escalated"]) == 1

    # With Jess (a complaint) it is the same since 2026-11-16: read, and answered only when it is the bot's.
    convo.hand_over("jess", "nails", "complaint")
    handler.process_message(inbound("they have all lifted again", mid="m5"), store)
    assert "This thread is with Jess for nails (complaint)" in contexts[-1] and len(wired["sent"]) == 2

    # A new matter for someone else moves the thread to them and tells them, with nothing sent.
    handler.process_message(inbound("could lori cut my hair too", mid="m6"), store)
    assert len(wired["sent"]) == 2 and wired["escalated"][-1] == ("psid1", "Hair with Lori-Dee: cut", "lori-dee")
    assert convo.handed_to == "lori-dee" and convo.handed_area == "hair"


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
            self.item.update(handed_to_jess=False, handed_to="", handed_area="", handed_kind="")

    table = Table()
    store = ConversationStore(table=table)
    c = Conversation(sender_id="p")
    c.hand_over("carmen", "tattoos", "quote")
    c.fresha_client_id, c.fresha_client_name = "305", "Amy Pond"
    store.save(c)
    back = store.load("p")
    assert back.handed_to == "carmen" and back.handed_area == "tattoos" and back.handed_kind == "quote"
    assert back.fresha_client_id == "305" and back.fresha_client_name == "Amy Pond"
    store.clear_handover("p")
    assert store.load("p").handed_to_jess is False and store.load("p").handed_to == ""


def test_staff_threads_are_stored_and_never_answered(wired, monkeypatch):
    """User, 2026-10-25: staff message the Page as themselves; if the sender's
    name contains an entry of TLG_STAFF the bot stays quiet. Decorated names
    match their plain spelling; a hand-set flag on the thread does the same."""
    calls, store = wired, MemoryStore()
    sample = "Lori-dee," + chr(10) + "Sophie’s 𝐻𝐴𝐼𝑅 & 𝐵𝐸𝐴𝑈𝑇𝑌," + chr(10) + " carmen smith, "  # as TLG_STAFF holds it: newlines and all
    staff = tuple(handler._norm(x) for x in sample.split(",") if x.strip())
    monkeypatch.setattr(handler, "STAFF_SENDERS", staff)
    assert handler.is_staff("Lori-Dee Blucher") and handler.is_staff("Carmen Smith") and handler.is_staff("Sophie's HAIR & BEAUTY")
    assert not handler.is_staff("Danny Cooke") and not handler.is_staff("")
    monkeypatch.setattr(meta, "user_profile", lambda sender_id, token, **kw: {"name": "Lori-dee Blucher"})
    handler.process_message(inbound("hiya can you check my diary", sender="staff1"), store)
    assert calls["sent"] == [] and calls["escalated"] == [] and calls["noticed"] == []
    convo = store.items["staff1"]
    assert convo.staff is True and convo.history[-1]["content"] == "hiya can you check my diary"
    # Flag set by hand on a thread whose name matches nothing.
    monkeypatch.setattr(meta, "user_profile", lambda sender_id, token, **kw: {"name": "Pat Smith"})
    store.items["flagged"] = Conversation(sender_id="flagged", staff=True)
    handler.process_message(inbound("hello", mid="m2", sender="flagged"), store)
    assert calls["sent"] == []
    # A client is answered as before.
    handler.process_message(inbound("hello", mid="m3", sender="client1"), store)
    assert len(calls["sent"]) == 1



# ---------------------------------------------------------------------------
# The team's own replies (Meta's echoes): plan job 9 as rebuilt 2026-11-16
# ---------------------------------------------------------------------------


def echo(text="Hi lovely, Jess here x", mid="e1", client="psid1", at=None, app_id="", channel="messenger"):
    import time

    return meta.Echo(channel=channel, client_id=client, message_id=mid, text=text,
                     timestamp_ms=int((time.time() if at is None else at) * 1000), app_id=app_id)


def test_the_teams_reply_is_kept_and_the_bots_own_echo_is_not(wired, monkeypatch):
    monkeypatch.setattr(handler, "MODE", "live")
    monkeypatch.setattr(handler, "secrets", lambda: {"page_token": "tok", "app_secret": "s", "verify_token": "v", "app_id": "111"})
    store = MemoryStore()
    handler.process_message(inbound("Can I book nails?"), store)

    handler.process_echo(echo("Here's the  link.", mid="e0"), store)  # Meta's copy of the bot's own reply
    handler.process_echo(echo("anything at all", mid="e00", app_id="111"), store)  # sent by our app, says Messenger
    assert store.team == {}

    handler.process_echo(echo("Hi lovely, Jess here, I can do 2pm x", mid="e1", app_id="263902037430900"), store)
    handler.process_echo(echo("Hi lovely, Jess here, I can do 2pm x", mid="e1"), store)  # delivered twice
    handler.process_echo(echo("", mid="e2"), store)  # a picture from the team
    assert [t["content"] for t in store.team["psid1"]] == ["Hi lovely, Jess here, I can do 2pm x", "[picture or attachment]"]

    # A staff member's own thread is never the bot's business either way.
    store.items["staff1"] = Conversation(sender_id="staff1", staff=True)
    handler.process_echo(echo("see you tomorrow", mid="e3", client="staff1"), store)
    assert "staff1" not in store.team


def test_the_bot_keeps_out_while_one_of_the_team_is_in_the_conversation(wired, monkeypatch):
    """User, 2026-11-16: once a person replies the thread is theirs for half an
    hour; after that the bot is back, and it reads what they said."""
    import time

    monkeypatch.setattr(handler, "MODE", "live")
    store = MemoryStore()
    handler.process_message(inbound("Hi", mid="m1"), store)
    handler.process_echo(echo("Hi lovely, Jess here, I can do 2pm Friday x", at=time.time() - 60), store)

    handler.process_message(inbound("ok and how much is it?", mid="m2"), store)
    assert len(wired["sent"]) == 1 and len(wired["ask"]) == 1  # not even asked
    assert turns(store.items["psid1"])[-1] == {"role": "user", "content": "ok and how much is it?"}

    store.team["psid1"][0]["at"] = int(time.time()) - 31 * 60  # half an hour on
    handler.process_message(inbound("how much is gel polish?", mid="m3"), store)
    assert len(wired["sent"]) == 2
    history, _ = wired["ask"][-1]
    said = [t["content"] for t in history]
    assert f"{handler.TEAM_MARK} Hi lovely, Jess here, I can do 2pm Friday x" in said
    assert "One of the team has written on this thread" in wired["context"][-1]


def test_a_reply_is_dropped_when_the_team_answer_first(wired, monkeypatch):
    """The bot takes fifteen seconds or more; if a person answers in that time theirs stands."""
    monkeypatch.setattr(handler, "MODE", "live")
    monkeypatch.setattr(handler, "REPLY_DELAY_SECONDS", 10)
    store = MemoryStore()
    monkeypatch.setattr(handler.time, "sleep", lambda s: handler.process_echo(echo("Hiya, it's £34 lovely x"), store))
    handler.process_message(inbound("how much is gel polish?"), store)
    assert wired["sent"] == []
    assert turns(store.items["psid1"]) == [{"role": "user", "content": "how much is gel polish?"}]  # the unsent reply is not on record


def test_a_handover_nobody_has_touched_for_a_week_is_over(wired, monkeypatch):
    monkeypatch.setattr(handler, "MODE", "live")
    import time

    store = MemoryStore()
    old = Conversation(sender_id="psid1", history=[{"role": "user", "content": "refund please"}, {"role": "assistant", "content": "Let me check x"}])
    old.hand_over("jess", "nails", "complaint")
    old.updated_at = int(time.time()) - 8 * 86400
    store.items["psid1"] = old
    handler.process_message(inbound("Hi, can I book gel polish?", mid="m9"), store)
    assert wired["sent"] == [("psid1", "Here's the link.")] and old.handed_to_jess is False
    assert "This thread is with" not in wired["context"][-1]

    recent = Conversation(sender_id="psid2", updated_at=int(time.time()) - 2 * 86400)
    recent.hand_over("jess", "nails", "complaint")
    assert not recent.handover_lapsed() and old.thread()[0] == {"role": "user", "content": "refund please"}


def test_webhook_takes_echoes_and_messages_from_one_delivery(wired, monkeypatch):
    monkeypatch.setattr(handler, "MODE", "live")
    monkeypatch.setattr(meta, "verify_signature", lambda *a, **kw: True)
    store = MemoryStore()
    body = {"object": "page", "entry": [{"messaging": [
        {"sender": {"id": "page1"}, "recipient": {"id": "psid7"}, "timestamp": 1763320000000,
         "message": {"mid": "e9", "text": "Morning lovely, Jess here x", "is_echo": True, "app_id": 263902037430900}},
    ]}]}
    resp = handler._handle_webhook({"body": json.dumps(body), "headers": {}}, store=store)
    assert resp["statusCode"] == 200
    assert store.team["psid7"] == [{"at": 1763320000, "content": "Morning lovely, Jess here x", "mid": "e9"}]
    assert wired["sent"] == [] and wired["ask"] == []  # an echo is never answered


def test_team_replies_live_on_their_own_row_and_come_back_in_order():
    """`save` puts the whole conversation row, so the team's replies are kept
    on a second row with an atomic append and merged in by time on load."""

    class Table:
        def __init__(self):
            self.rows = {}

        def put_item(self, Item):
            self.rows[Item["sender_id"]] = Item

        def get_item(self, Key):
            row = self.rows.get(Key["sender_id"])
            return {"Item": row} if row else {}

        def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ReturnValues=None):
            row = self.rows.setdefault(Key["sender_id"], {"sender_id": Key["sender_id"]})
            v = ExpressionAttributeValues
            if ":kept" in v:
                row["turns"] = v[":kept"]
            else:
                assert "list_append(if_not_exists(turns, :none), :turn)" in UpdateExpression
                row.update(last_at=v[":at"], turns=row.get("turns", []) + v[":turn"], expires_at=v[":exp"])
            return {"Attributes": row}

    table = Table()
    store = ConversationStore(table=table)
    c = Conversation(sender_id="p")
    c.note_message("m1", "have you got anything Friday?", at=100)
    store.save(c)
    stale = store.load("p")  # another invocation, mid-reply, holding the row as it was
    store.note_team("p", "Yes lovely, 2pm with Sav x", 150, "e1")
    stale.record_turn("m2", "and how much is it", "Gel polish is £34 x", at=200)
    store.save(stale)  # a whole-row put: the team's reply survives it

    back = store.load("p")
    assert back.team_last_at == 150 and store.team_last_at("p") == 150 and set(table.rows) == {"p", "team#p"}
    assert [t["content"] for t in back.thread()] == [
        "have you got anything Friday?", f"{handler.TEAM_MARK} Yes lovely, 2pm with Sav x", "and how much is it", "Gel polish is £34 x",
    ]
    assert back.team_active(now=150 + 29 * 60) and not back.team_active(now=150 + 31 * 60)
    for i in range(45):
        store.note_team("p", f"line {i}", 300 + i, f"x{i}")
    assert len(table.rows["team#p"]["turns"]) <= 41 and len(store.load("p").team_turns) == 20
