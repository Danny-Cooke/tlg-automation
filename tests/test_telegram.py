"""The team's Telegram group: message format, chat id discovery, best-effort sending."""
from bot import escalation, telegram
from bot.state import Conversation


class Resp:
    def __init__(self, body, status=200):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class Http:
    def __init__(self, updates=None, send_status=200):
        self.updates = updates or []
        self.send_status = send_status
        self.sent = []

    def get(self, url, params, timeout):
        assert url.endswith("/getUpdates")
        return Resp({"ok": True, "result": self.updates})

    def post(self, url, json, timeout):
        assert url.endswith("/sendMessage")
        self.sent.append(json)
        return Resp({"ok": True}, self.send_status)


class Ssm:
    def __init__(self, value=None):
        self.value = value
        self.put = []

    def get_parameter(self, Name):
        if self.value is None:
            raise RuntimeError("ParameterNotFound")
        return {"Parameter": {"Value": self.value}}

    def put_parameter(self, **kw):
        self.put.append(kw)
        self.value = kw["Value"]


def group_update(chat_id, kind="message", type_="supergroup"):
    return {"update_id": 1, kind: {"chat": {"id": chat_id, "type": type_}}}


def test_format_is_the_teams_one_liner_then_the_link():
    convo = Conversation(sender_id="psid1", channel="messenger", client_name="Danny Cooke")
    text = escalation.format_telegram(convo, "61577501519464", area="nails", kind="complaint", reason="complaint")
    assert text.splitlines() == [
        "Nails: complaint: Danny Cooke: FB",
        "https://business.facebook.com/latest/inbox/all?asset_id=61577501519464",
    ]
    convo = Conversation(sender_id="ig9", channel="instagram")
    text = escalation.format_telegram(convo, "p", area="hair", kind="cancellation or rebooking",
                                      reason="Wants to move Friday's cut to next week")
    assert text.splitlines()[0] == "Hair: cancellation or rebooking: ig9: Insta"
    assert text.splitlines()[2] == "Wants to move Friday's cut to next week"  # detail the team needs, on its own line
    assert escalation.format_telegram(Conversation(sender_id="x", channel="messenger"), "p").startswith("General: needs you: x: FB")


def test_discovery_takes_the_latest_group_in_the_feed():
    http = Http(updates=[
        {"update_id": 1, "message": {"chat": {"id": 42, "type": "private"}}},  # a DM to the bot, not the group
        group_update(-1001, kind="my_chat_member"),  # the bot being added
        group_update(-1002),  # the group that spoke most recently wins
    ])
    assert telegram.discover_group_chat_id("tok", session=http) == "-1002"
    assert telegram.discover_group_chat_id("tok", session=Http(updates=[])) is None


def test_chat_id_prefers_env_then_cache_then_discovery(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID_PARAM", "/tlg/prod/telegram/chat_id")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-55")
    assert telegram.chat_id("tok", ssm=Ssm(), session=Http()) == "-55"

    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    assert telegram.chat_id("tok", ssm=Ssm("-66"), session=Http()) == "-66"

    ssm = Ssm("unset")  # Terraform's placeholder: not discovered yet
    http = Http(updates=[group_update(-77)])
    assert telegram.chat_id("tok", ssm=ssm, session=http) == "-77"
    assert ssm.put[0]["Name"] == "/tlg/prod/telegram/chat_id" and ssm.put[0]["Value"] == "-77"

    assert telegram.chat_id("tok", ssm=Ssm("unset"), session=Http(updates=[])) is None


def test_send_message_is_best_effort():
    http = Http()
    assert telegram.send_message("tok", "-1", "Nails: complaint: Danny Cooke: FB", session=http) is True
    assert http.sent == [{"chat_id": "-1", "text": "Nails: complaint: Danny Cooke: FB", "disable_web_page_preview": True}]
    assert telegram.send_message("tok", "-1", "x", session=Http(send_status=403)) is False

    class Dead:
        def post(self, *a, **k):
            raise ConnectionError("no network")

    assert telegram.send_message("tok", "-1", "x", session=Dead()) is False


def test_notify_posts_to_telegram_except_for_spam(monkeypatch):
    monkeypatch.setenv("META_PAGE_ID", "p1")
    monkeypatch.delenv("ESCALATION_TOPIC_ARN", raising=False)
    posted = []
    convo = Conversation(sender_id="psid1", channel="messenger", client_name="Danny Cooke")
    escalation.notify(convo, "Wants Sav, BIAB soak off and new set, Fri 2.15pm", "2.15 Friday please", to="jess",
                      area="nails", kind="booking", telegram=posted.append)
    assert posted == ["Nails: booking: Danny Cooke: FB\nhttps://business.facebook.com/latest/inbox/all?asset_id=p1\nWants Sav, BIAB soak off and new set, Fri 2.15pm"]
    escalation.notify(convo, "SEO seller", "buy my services", to="jess", area="general", kind="spam", telegram=posted.append)
    assert len(posted) == 1  # spam never buzzes the team

    def boom(text):
        raise RuntimeError("telegram down")

    escalation.notify(convo, "r", "t", to="jess", area="nails", kind="complaint", telegram=boom)  # must not raise


def test_post_handover_without_config_is_a_quiet_no(monkeypatch):
    monkeypatch.delenv("TELEGRAM_SECRET_ARN", raising=False)
    telegram.bot_token.cache_clear()
    assert telegram.post_handover("x") is False
