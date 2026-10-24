"""New clients: find by phone, add in Fresha, book by id (plan job 13, recorded 2026-10-24)."""
import json

import pytest

from bot import booking, fresha, fresha_session
from bot.config import SalonConfig
from test_booking import CONFIG, FakeFresha, convo, run

SESSION = fresha_session.Session(cookie="SECRET", expires_at=None)


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


class JsonHttp:
    """The customers API: GETs answered from the script by path, POSTs recorded with their JSON body."""

    def __init__(self, answers=None, status=200):
        self.answers, self.status, self.calls = answers or {}, status, []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return Resp(self.status, self.answers.get("referral" if "referral-sources" in url else "search", {}))

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return Resp(self.status, self.answers.get("create", {}))


@pytest.fixture
def cfg():
    return SalonConfig.from_json(json.dumps(CONFIG))


# -- the Fresha calls -----------------------------------------------------------


def test_phone_is_written_the_way_the_dashboard_writes_it():
    assert fresha.phone_for_fresha("+447700900123") == "+44 7700 900123"
    assert fresha.phone_for_fresha("+353871234567") == "+353871234567"
    assert fresha.phone_for_fresha("") == ""


def test_create_client_sends_the_recorded_form_with_the_default_referral_source():
    http = JsonHttp({
        "referral": {"data": [{"id": "10435303", "type": "referral-sources", "attributes": {"name": "Walk-In", "is-default": True, "is-deleted": False}},
                              {"id": "1", "type": "referral-sources", "attributes": {"name": "Old", "is-default": False, "is-deleted": True}}]},
        "create": {"data": {"id": "305999001", "type": "customers-v2", "attributes": {"name": "Amy Pond", "contact-number": "+44 7700 900123",
                                                                                       "email": "amy@example.com"}}},
    })
    f = fresha.Fresha(SESSION, http)
    c = f.create_client(first_name=" Amy ", last_name="Pond", mobile_e164="+447700900123", email="Amy@Example.com")
    assert c.id == "305999001" and c.name == "Amy Pond" and c.phone == "+44 7700 900123"
    method, url, kw = http.calls[-1]
    assert (method, url) == ("POST", fresha.CREATE_CLIENT) and kw["headers"]["content-type"] == "application/vnd.api+json"
    body = kw["json"]["data"]
    a = body["attributes"]
    assert body["type"] == "customer-create-requests"
    assert (a["first-name"], a["last-name"], a["email"], a["contact-number"]) == ("Amy", "Pond", "amy@example.com", "+44 7700 900123")
    assert a["creation-source"] == "client_list" and a["accepts-sms-marketing-notifications"] is True and a["tag-ids"] == []
    assert body["relationships"]["referral-source"] == {"data": {"attributes": {"id": "10435303"}, "type": "referral-source"}}
    assert [e["attributes"]["type"] for e in body["relationships"]["emergency-contacts"]["data"]] == ["primary", "secondary"]
    assert f.referral_source_id() == "10435303" and sum(1 for c in http.calls if "referral-sources" in c[1]) == 1  # cached


def test_create_client_without_an_id_is_an_error():
    http = JsonHttp({"referral": {"data": []}, "create": {"data": {}}})
    with pytest.raises(fresha.FreshaError):
        fresha.Fresha(SESSION, http).create_client(first_name="A", last_name="B", mobile_e164="+447700900123", email="a@b.co")
    assert http.calls[-1][2]["json"]["data"]["relationships"]["referral-source"] == {"data": None}


def test_send_reminder_replays_the_dashboards_mutation_and_checks_the_echo():
    class Gql(JsonHttp):
        def post(self, url, **kw):
            self.calls.append(("POST", url, kw))
            return Resp(200, {"data": {"sendAppointmentProtectionReminder": {"appointmentId": kw["data"] and json.loads(kw["data"]["variables"])["input"]["appointmentId"]}}})

    http = Gql()
    assert fresha.Fresha(SESSION, http).send_protection_reminder("1333772002") == "1333772002"
    method, url, kw = http.calls[-1]
    assert url == fresha.GRAPHQL and kw["params"]["_mutation"] == "sendAppointmentProtectionReminder"
    assert json.loads(kw["data"]["variables"]) == {"input": {"appointmentId": "1333772002"}}

    class Wrong(JsonHttp):
        def post(self, url, **kw):
            return Resp(200, {"data": {"sendAppointmentProtectionReminder": {"appointmentId": "1"}}})

    with pytest.raises(fresha.FreshaError):
        fresha.Fresha(SESSION, Wrong()).send_protection_reminder("1333772002")


def test_find_client_by_phone_matches_on_digits_whatever_the_name():
    rows = {"data": [
        {"id": "1", "attributes": {"name": "Amy Pond", "contact-number": "+44 7700 900123", "email": "", "blocked": False}},
        {"id": "2", "attributes": {"name": "Amelia Williams", "contact-number": "07700900123", "email": "", "blocked": False}},
        {"id": "3", "attributes": {"name": "Rory", "contact-number": "+44 7700 900999", "email": "", "blocked": False}},
    ]}
    http = JsonHttp({"search": rows})
    found = fresha.Fresha(SESSION, http).find_client_by_phone("+447700900123")
    assert [c.id for c in found] == ["1", "2"]
    assert http.calls[0][2]["params"]["query"] == "+44 7700 900123"
    assert fresha.Fresha(SESSION, JsonHttp({"search": {"data": []}})).find_client_by_phone("123") == []


# -- the tool and the booking ---------------------------------------------------


class OnboardingFresha(FakeFresha):
    def __init__(self, by_phone=(), **kw):
        super().__init__(**kw)
        self.by_phone, self.created_clients = list(by_phone), []

    def find_client_by_phone(self, mobile):
        self.searched.append(("phone", mobile))
        return self.by_phone

    def create_client(self, **kw):
        self.created_clients.append(kw)
        return fresha.Client("305999001", f"{kw['first_name']} {kw['last_name']}", kw["mobile_e164"], kw["email"])


def test_unknown_client_is_told_to_onboard_not_hand_over(cfg):
    out, f, _ = run(cfg, f=FakeFresha(clients=[]))
    assert out.startswith("No Fresha client called 'Danny Cooke'") and "`create_client`" in out and "Hand over" not in out


def test_create_client_matches_by_phone_first_and_then_books_by_id(cfg):
    saved = []
    c = convo(client_name="Dan C")
    f = OnboardingFresha(by_phone=[fresha.Client("279113349", "Danny Cooke", "+44 7700 900123", "d@example.com")], clients=[])
    out = booking.create_client({"first_name": "Dan", "last_name": "C", "mobile": "07700 900123", "email": "d@example.com"},
                                cfg=cfg, convo=c, dry_run=False, save=saved.append, session=SESSION, fresha=f)
    assert out.startswith("Already a client: that number belongs to 'Danny Cooke'") and f.created_clients == []
    assert c.fresha_client_id == "279113349" and c.fresha_client_name == "Danny Cooke" and saved == [c]
    assert f.searched == [("phone", "+447700900123")]
    # The booking now uses the matched record, whatever name the model passes, with no name search.
    out, f, _ = run(cfg, c=c, f=f, args={"client_name": "Dan C"})
    assert out.startswith("Booked: Gel polish with Jess, Thu 29 Oct 10am, for Danny Cooke") and f.created[0]["customer_id"] == "279113349"
    assert f.searched == [("phone", "+447700900123")]


def test_create_client_adds_a_record_when_nobody_has_the_number(cfg):
    c = convo(client_name="Amy Pond")
    f = OnboardingFresha(clients=[])
    out = booking.create_client({"first_name": "Amy", "last_name": "Pond", "mobile": "+44 7700 900555", "email": "Amy@Example.com"},
                                cfg=cfg, convo=c, dry_run=False, session=SESSION, fresha=f)
    assert out.startswith("Created: Amy Pond on Fresha (client 305999001)")
    assert f.created_clients == [{"first_name": "Amy", "last_name": "Pond", "mobile_e164": "+447700900555", "email": "amy@example.com"}]
    assert c.fresha_client_id == "305999001"
    out, f, _ = run(cfg, c=c, f=f, args={"client_name": "Amy Pond"})
    assert out.startswith("Booked: Gel polish with Jess") and f.created[0]["customer_id"] == "305999001"


def test_create_client_checks_the_details_and_writes_nothing_outside_live(cfg):
    c = convo()
    f = OnboardingFresha(clients=[])
    kw = dict(cfg=cfg, convo=c, dry_run=True, session=SESSION, fresha=f)
    assert booking.create_client({"first_name": "Amy", "last_name": "", "mobile": "07700900555", "email": "a@b.co"}, **kw).startswith("Need the client's")
    assert "mobile number does not look right" in booking.create_client({"first_name": "Amy", "last_name": "P", "mobile": "123", "email": "a@b.co"}, **kw)
    assert "email address does not look right" in booking.create_client({"first_name": "Amy", "last_name": "P", "mobile": "07700900555", "email": "nope"}, **kw)
    out = booking.create_client({"first_name": "Amy", "last_name": "P", "mobile": "07700900555", "email": "a@b.co"}, **kw)
    assert out.startswith("Would have created (not live)") and f.created_clients == [] and c.fresha_client_id == ""


def test_create_client_hands_over_when_fresha_refuses(cfg):
    class Refusing(OnboardingFresha):
        def create_client(self, **kw):
            raise fresha.FreshaError("422")

    out = booking.create_client({"first_name": "Amy", "last_name": "P", "mobile": "07700900555", "email": "a@b.co"},
                                cfg=cfg, convo=convo(), dry_run=False, session=SESSION, fresha=Refusing(clients=[]))
    assert out.startswith("Fresha would not add the client") and "Hand over to Jess" in out


def test_prompt_tells_the_bot_how_to_onboard(persona_text, salon_config_json):
    from bot.prompt import build_system_prompt

    prompt = build_system_prompt(persona_text, SalonConfig.from_json(salon_config_json))
    assert "# New clients" in prompt and "`create_client`" in prompt and "new to us" in prompt and "the number ending 123" in prompt
