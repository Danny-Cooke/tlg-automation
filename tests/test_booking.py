"""The book_appointment tool: guards, the write, the record, the team ping."""
import datetime as dt
import json

import pytest

from bot import booking, brain, escalation, fresha, fresha_session, handler
from bot.config import SalonConfig
from bot.state import Conversation

NOW = dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.timezone.utc)
SESSION = fresha_session.Session(cookie="SECRET", expires_at=None)

CONFIG = {
    "salon_name": "TLG", "address": "", "phone": "", "opening_hours": {}, "general_booking_link": "https://fresha/tlg",
    "venue_url": "https://www.fresha.com/a/tlg",
    "services": [
        {"category": "Senior Nail Services - TLG", "name": "Gel polish", "price": "from £34", "duration": "1 hour", "staff": ["Jess", "Sav"]},
        {"category": "Hair by Lori-dee", "name": "Dry cut", "price": "£30", "duration": "45 mins", "staff": ["Lori-Dee"]},
        {"category": "Sophie cooper", "name": "Curling hair", "price": "£30", "duration": "45 mins", "staff": ["Sophie", "Lori-Dee"]},
        {"category": "Tattoos by Skin deep canvas", "name": "Small tattoo", "price": "from £50", "duration": "1 hour", "staff": ["Carmen"]},
        {"category": "Tattoos by Skin deep canvas", "name": "consultation", "price": "free", "duration": "15 mins", "staff": ["Carmen"]},
        {"category": "Beauty - TLG", "name": "Brow wax", "price": "£10", "duration": "15 mins", "staff": ["Jess"]},
        {"category": "Bernadettes ReFresh aethetics", "name": "Lip filler", "price": "£150", "duration": "45 mins", "staff": ["Bernadette"]},
        {"category": "Gift vouchers", "name": "Voucher", "price": "£20", "duration": "5 mins", "staff": ["Jess"]},
        {"category": "Lashes by Amber", "name": "Make up by the lash goblin", "price": "from £25", "duration": "1 hour 15 mins", "staff": ["Amber", "Carmen"]},
    ],
    "not_bookable_for": {"Make up by the lash goblin": ["Carmen"]},
    "staff": [
        {"name": "Jess", "role": "Manager", "employee_id": "3440861"},
        {"name": "Sav", "role": "Nail tech", "employee_id": "5029221"},
        {"name": "Lori-Dee", "role": "Hairdresser", "employee_id": "3440849"},
        {"name": "Sophie", "role": "Hair stylist", "employee_id": "5630580"},
        {"name": "Carmen", "role": "Nail & Tattoo Tech", "employee_id": "3440872"},
        {"name": "Bernadette", "role": "Aesthetic practitioner", "employee_id": "5007255"},
        {"name": "Lissy", "role": "Apprentice"},
    ],
}
GEL = fresha.Service("22563223", "Gel polish", "Senior Nail Services - TLG", "25845686", "34.00", "STARTS_AT", 3600, ("3440861", "5029221"))
DRY_CUT = fresha.Service("22563300", "Dry cut", "Hair by Lori-dee", "25845700", "30.00", "FIXED", 2700, ("3440849",))
CURLS = fresha.Service("22563301", "Curling hair", "Sophie cooper", "25845701", "30.00", "FIXED", 2700, ("5630580", "3440849"))
TATTOO = fresha.Service("22563302", "Small tattoo", "Tattoos by Skin deep canvas", "25845702", "50.00", "STARTS_AT", 3600, ("3440872",))
CONSULT = fresha.Service("22563303", "consultation", "Tattoos by Skin deep canvas", "25845703", "0.00", "FREE", 900, ("3440872",))
BROWS = fresha.Service("22563304", "Brow wax", "Beauty - TLG", "25845704", "10.00", "FIXED", 900, ("3440861",))
FILLER = fresha.Service("22563305", "Lip filler", "Bernadettes ReFresh aethetics", "25845705", "150.00", "FIXED", 2700, ("5007255",))
DANNY = fresha.Client("279113349", "Danny Cooke", "+44", "d@example.com")


class FakeFresha:
    """Stands in for bot.fresha.Fresha: scripted answers, recorded writes."""

    def __init__(self, clients=(DANNY,), services=(GEL,), conflicts=(), create_error=None):
        self.clients, self.services, self.conflict_list = list(clients), list(services), list(conflicts)
        self.create_error, self.created, self.searched = create_error, [], []

    def catalog(self, **kw):
        return self.services

    def find_clients(self, query, *, limit=10):
        self.searched.append(query)
        return [c for c in self.clients if query.casefold() in c.name.casefold()]

    def conflicts(self, *a):
        return self.conflict_list

    def create(self, **kw):
        if self.create_error:
            raise self.create_error
        self.created.append(kw)
        return fresha.Booking("1332159791", "1799522735", ())


@pytest.fixture
def cfg():
    return SalonConfig.from_json(json.dumps(CONFIG))


@pytest.fixture(autouse=True)
def fresh_catalog():
    booking.forget_catalog()
    yield
    booking.forget_catalog()


def convo(**kw):
    fields = {"sender_id": "psid1", "channel": "messenger", "client_name": "Danny Cooke", **kw}
    return Conversation(**fields)


def args(**over):
    base = {"service": "Gel polish", "person": "Jess", "date": "2026-10-29", "time": "10:00", "client_name": "Danny Cooke"}
    return {**base, **over}


def run(cfg, f=None, c=None, dry_run=False, **kw):
    f = f or FakeFresha()
    c = c or convo()
    out = booking.book(args(**kw.pop("args", {})), cfg=cfg, convo=c, dry_run=dry_run, session=SESSION, fresha=f, now=NOW, **kw)
    return out, f, c


def test_books_and_records_and_tells_the_team(cfg):
    saved, pinged = [], []
    out, f, c = run(cfg, save=saved.append, notify=lambda convo, summary, appt, **kw: pinged.append((summary, appt)))
    assert out.startswith("Booked: Gel polish with Jess, Thu 29 Oct 10am, for Danny Cooke (Fresha appointment 1332159791)")
    assert "card details" in out
    create = f.created[0]
    assert create["customer_id"] == "279113349" and create["pricing_level_id"] == "25845686" and create["employee_id"] == "3440861"
    assert create["price"] == "34" and create["duration_s"] == 3600 and (create["date"], create["start"]) == ("2026-10-29", "10:00")
    assert len(create["idempotency_key"]) == 21
    assert c.bookings[0]["appointment_id"] == "1332159791" and c.bookings[0]["client_id"] == "279113349"
    assert saved == [c]  # remembered before anything else can go wrong
    assert pinged == [("Gel polish with Jess, Thu 29 Oct 10am, for Danny Cooke", "1332159791")]


def test_idempotency_key_is_stable_per_conversation_and_slot():
    req = booking.Request("Gel polish", "Jess", "2026-10-29", "10:00", "Danny Cooke")
    a = booking.idempotency_key("psid1", req, "25845686")
    assert a == booking.idempotency_key("psid1", req, "25845686") and len(a) == 21
    assert a != booking.idempotency_key("psid2", req, "25845686")
    assert a != booking.idempotency_key("psid1", booking.Request("Gel polish", "Jess", "2026-10-29", "10:30", "Danny Cooke"), "25845686")


def test_same_slot_twice_in_one_conversation_is_not_booked_again(cfg):
    out, f, c = run(cfg)
    out2, f2, _ = run(cfg, c=c)
    assert out2.startswith("Already booked earlier in this conversation") and "1332159791" in out2
    assert f2.created == []


def test_dry_run_checks_everything_and_writes_nothing(cfg):
    out, f, c = run(cfg, dry_run=True)
    assert out.startswith("Would have booked (not live): Gel polish with Jess, Thu 29 Oct 10am")
    assert f.created == [] and c.bookings == []


def test_everything_but_a_tattoo_itself_is_booked(cfg):
    out, f, _ = run(cfg, args={"service": "Voucher", "person": "Jess"})
    assert "which the bot does not book in chat" in out and f.created == []
    posted = []
    for service, person, fake, area in (("Brow wax", "Jess", BROWS, "beauty"), ("Lip filler", "Bernadette", FILLER, "aesthetics")):
        booking.forget_catalog()
        out, f, _ = run(cfg, args={"service": service, "person": person}, f=FakeFresha(services=[fake]),
                        notify=lambda convo, summary, appointment_id, **kw: posted.append(kw["area"]))
        assert out.startswith(f"Booked: {service} with {person}"), out
    assert posted == ["beauty", "aesthetics"]
    booking.forget_catalog()
    out, f, _ = run(cfg, args={"service": "Small tattoo", "person": "Carmen"}, f=FakeFresha(services=[TATTOO]))
    assert "only tattoo appointment the bot books is the free consultation with Carmen" in out and f.created == []
    out, f, _ = run(cfg, args={"service": "Unicorn wash"})
    assert "not a service in the salon details" in out


def test_tattoo_consultation_is_booked_with_carmen(cfg):
    posted = []
    booking.forget_catalog()
    out, f, _ = run(cfg, args={"service": "consultation", "person": "Carmen"}, f=FakeFresha(services=[CONSULT]),
                    notify=lambda convo, summary, appointment_id, **kw: posted.append(kw))
    assert out.startswith("Booked: consultation with Carmen, Thu 29 Oct 10am, for Danny Cooke")
    assert f.created[0]["employee_id"] == "3440872" and f.created[0]["price"] == "0"
    assert posted[0]["area"] == "tattoos"


def test_hair_is_booked_with_lori_dee_or_sophie(cfg):
    posted = []

    def notify(convo, summary, appointment_id, **kw):
        posted.append((summary, kw))

    out, f, c = run(cfg, args={"service": "Dry cut", "person": "Lori-Dee"}, f=FakeFresha(services=[DRY_CUT]), notify=notify)
    assert out.startswith("Booked: Dry cut with Lori-Dee, Thu 29 Oct 10am, for Danny Cooke")
    assert f.created[0]["employee_id"] == "3440849" and f.created[0]["pricing_level_id"] == "25845700"
    assert posted[0][1]["area"] == "hair"

    booking.forget_catalog()
    out, f, c = run(cfg, args={"service": "Curling hair", "person": "Sophie"}, f=FakeFresha(services=[CURLS]), notify=notify)
    assert out.startswith("Booked: Curling hair with Sophie") and f.created[0]["employee_id"] == "5630580"
    assert posted[1][1]["area"] == "hair"

    booking.forget_catalog()
    out, f, _ = run(cfg, args={"service": "Dry cut", "person": "Sophie"}, f=FakeFresha(services=[DRY_CUT]))
    assert "Sophie is not booked for 'Dry cut' here; it is done by Lori-Dee" in out and f.created == []


def test_hair_colour_with_a_patch_test_hands_over_to_lori_dee(cfg):
    colour = fresha.Service("1", "Dry cut", "Hair by Lori-dee", "9", "30.00", "FIXED", 2700, ("3440849",), patch_test=True)
    out, f, _ = run(cfg, args={"service": "Dry cut", "person": "Lori-Dee"}, f=FakeFresha(services=[colour]))
    assert "patch test" in out and "Hand over to Lori-Dee" in out and f.created == []


def test_person_must_be_on_the_team_with_a_fresha_id(cfg):
    out, f, _ = run(cfg, args={"person": "Lissy"})
    assert "not on the team list" in out
    out, f, _ = run(cfg, args={"service": "Gel polish", "person": "Carmen"})
    assert "Carmen is not booked for 'Gel polish' here; it is done by Jess, Sav" in out and f.created == []


def test_hand_written_exclusions_beat_fresha(cfg):
    """Fresha lists Carmen on makeup; the salon says only Amber does it. The tool
    must refuse Carmen even though Fresha's catalog would accept the booking."""
    makeup = fresha.Service("22563306", "Make up by the lash goblin", "Lashes by Amber", "25845706", "25.00", "STARTS_AT", 4500, ("5394887", "3440872"))
    booking.forget_catalog()
    out, f, _ = run(cfg, args={"service": "Make up by the lash goblin", "person": "Carmen"}, f=FakeFresha(services=[makeup]))
    assert "Carmen is not booked for 'Make up by the lash goblin' here; it is done by Amber" in out and f.created == []
    out, f, _ = run(cfg, f=FakeFresha(services=[fresha.Service("1", "Gel polish", "Senior Nail Services - TLG", "9", "34.00", "FIXED", 3600, ("5029221",))]))
    assert "does not list 'Gel polish' for Jess" in out and f.created == []


def test_client_matching_rules(cfg):
    out, f, _ = run(cfg, f=FakeFresha(clients=[]))
    assert out.startswith("No Fresha client called 'Danny Cooke'") and "Hand over to Jess" in out
    out, f, _ = run(cfg, f=FakeFresha(clients=[DANNY, fresha.Client("2", "Danny Cooke")]))
    assert "More than one Fresha client" in out
    out, f, _ = run(cfg, f=FakeFresha(clients=[fresha.Client("2", "Danny Cooke", blocked=True)]))
    assert "blocked" in out
    # A near miss is not a match: "Danny Cooke" must not book "Danny Cooker"
    out, f, _ = run(cfg, f=FakeFresha(clients=[fresha.Client("3", "Danny Cooker")]))
    assert out.startswith("No Fresha client") and f.created == []
    # The profile name is the default; the model may override it with what the client said
    out, f, c = run(cfg, c=convo(client_name="Dan C"), args={"client_name": "Danny Cooke"})
    assert out.startswith("Booked")


def test_a_clash_means_no_booking(cfg):
    out, f, _ = run(cfg, f=FakeFresha(conflicts=[{"conflictType": "EMPLOYEE_HAS_EXISTING_APPOINTMENT"}]))
    assert "not free any more (EMPLOYEE_HAS_EXISTING_APPOINTMENT)" in out and f.created == []


def test_bad_inputs_are_explained_not_booked(cfg):
    assert "in the past" in run(cfg, args={"date": "2026-10-01"})[0]
    assert "not YYYY-MM-DD" in run(cfg, args={"date": "29/10/2026"})[0]
    assert "not HH:MM" in run(cfg, args={"time": "ten"})[0]
    assert "Need the service" in run(cfg, args={"service": ""})[0]
    assert "name is not known" in run(cfg, c=convo(client_name=""), args={"client_name": ""})[0]


def test_times_in_the_teams_shapes_are_understood():
    for given, want in [("10:00", "10:00"), ("10.00", "10:00"), ("1000", "10:00"), ("10am", "10:00"), ("1.30pm", "13:30"),
                        ("13:30", "13:30"), ("12pm", "12:00"), ("12am", "00:00"), ("9", "09:00")]:
        assert booking._normalise_time(given) == want, given


def test_no_session_or_rejected_session_hands_over(cfg, monkeypatch):
    monkeypatch.setattr(fresha_session, "get", lambda **kw: None)
    out = booking.book(args(), cfg=cfg, convo=convo(), dry_run=False, now=NOW)
    assert out.startswith("Cannot book right now") and "Hand over to Jess" in out

    out, f, _ = run(cfg, f=FakeFresha(create_error=fresha.SessionRejected("401")))
    assert "rejected the salon's login" in out
    out, f, _ = run(cfg, f=FakeFresha(create_error=fresha.FreshaError("boom")))
    assert "Fresha refused the request" in out


def test_patch_test_services_are_not_booked_in_chat(cfg):
    pt = fresha.Service("1", "Gel polish", "Senior Nail Services - TLG", "9", "34.00", "FIXED", 3600, ("3440861",), patch_test=True)
    out, f, _ = run(cfg, f=FakeFresha(services=[pt]))
    assert "patch test" in out and f.created == []


def test_catalog_is_fetched_once_per_container(cfg):
    class Counting(FakeFresha):
        calls = 0

        def catalog(self, **kw):
            Counting.calls += 1
            return self.services

    f = Counting()
    run(cfg, f=f)
    run(cfg, f=f, args={"time": "11:00"})
    assert Counting.calls == 1


def test_price_shape_matches_the_dashboard():
    assert booking._price_for_fresha("34.00") == "34"
    assert booking._price_for_fresha("1.50") == "1.50"


# -- wiring -------------------------------------------------------------------


def test_brain_sends_both_tool_definitions_when_offered():
    from types import SimpleNamespace

    final = json.dumps({"reply": "hi", "escalate": False, "escalation_reason": "", "escalate_to": "", "area": "", "escalation_kind": "", "suggested_booking_link": ""})
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text=final)], stop_reason="end_turn", stop_details=None)

    class FakeClient:
        def __init__(self):
            self.requests = []
            self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

        def create(self, **kw):
            self.requests.append(kw)
            return response

    client = FakeClient()
    brain.ask("SYSTEM", [], "hi", tools={"check_availability": lambda a: "", "book_appointment": lambda a: ""}, client=client)
    assert client.requests[0]["tools"] == [brain.AVAILABILITY_TOOL, brain.BOOKING_TOOL]
    assert set(brain.BOOKING_TOOL["input_schema"]["required"]) == {"service", "person", "date", "time", "client_name"}


def test_handler_offers_booking_only_with_a_session_parameter_and_a_conversation(monkeypatch):
    monkeypatch.setenv("SALON_CONFIG_JSON", json.dumps(CONFIG))
    handler.salon.cache_clear()
    monkeypatch.delenv("FRESHA_SESSION_PARAM", raising=False)
    assert set(handler.tools(convo())) == {"check_availability"}
    monkeypatch.setenv("FRESHA_SESSION_PARAM", "/tlg/test/fresha/session")
    assert set(handler.tools()) == {"check_availability"}
    assert set(handler.tools(convo())) == {"check_availability", "book_appointment", "cancel_appointment"}
    handler.salon.cache_clear()


def test_handler_booking_tool_is_a_dry_run_outside_live_mode(monkeypatch):
    monkeypatch.setenv("SALON_CONFIG_JSON", json.dumps(CONFIG))
    monkeypatch.setenv("FRESHA_SESSION_PARAM", "/tlg/test/fresha/session")
    handler.salon.cache_clear()
    seen = {}

    def fake_book(args, **kw):
        seen.update(kw)
        return "ok"

    monkeypatch.setattr(booking, "book", fake_book)
    monkeypatch.setattr(handler, "MODE", "shadow")
    handler.tools(convo())["book_appointment"](args())
    assert seen["dry_run"] is True and seen["notify"] is escalation.notify_booking
    monkeypatch.setattr(handler, "MODE", "live")
    handler.tools(convo())["book_appointment"](args())
    assert seen["dry_run"] is False
    handler.salon.cache_clear()


def test_state_round_trips_bookings():
    from bot.state import ConversationStore

    class Table:
        def __init__(self):
            self.items = {}

        def put_item(self, Item):
            self.items[Item["sender_id"]] = Item

        def get_item(self, Key):
            return {"Item": self.items.get(Key["sender_id"])}

    store = ConversationStore(Table())
    c = convo()
    c.bookings.append({"appointment_id": "1", "service": "Gel polish", "date": "2026-10-29", "time": "10:00"})
    store.save(c)
    assert store.load("psid1").bookings == c.bookings


def test_booking_notification_is_email_only(monkeypatch):
    """A booking the bot completed is a record for the ops topic, never a
    Telegram post: the group is for the point where the bot cannot continue."""
    monkeypatch.setenv("META_PAGE_ID", "page1")
    monkeypatch.setenv("OPS_TOPIC_ARN", "arn:ops")
    published = []

    class Sns:
        def publish(self, **kw):
            published.append(kw)

    monkeypatch.setattr(escalation, "_telegram", lambda: (_ for _ in ()).throw(AssertionError("Telegram must not be touched")))
    escalation.notify_booking(convo(), "Gel polish with Jess, Thu 29 Oct 10am, for Danny Cooke", "1332159791", sns=Sns())
    assert published[0]["Subject"].startswith("[TLG bot] Booked: Gel polish with Jess")
    assert "Fresha appointment: 1332159791" in published[0]["Message"] and "Area: nails" in published[0]["Message"]
    escalation.notify_booking(convo(), "Dry cut with Lori-Dee, Thu 29 Oct 10am, for Danny Cooke", "2", area="hair", kind="cancelled by the bot", sns=Sns())
    assert published[1]["Subject"].startswith("[TLG bot] Cancelled: Dry cut with Lori-Dee") and "Area: hair" in published[1]["Message"]


def test_prompt_and_persona_carry_the_booking_rules(persona_text, salon_config_json):
    from bot.prompt import build_system_prompt

    prompt = build_system_prompt(persona_text, SalonConfig.from_json(salon_config_json))
    assert "# Booking" in prompt and "`book_appointment`" in prompt and "Bernadette's" in prompt
    assert "Lori-Dee or Sophie" in prompt
    assert "do not hand over again" in prompt
    assert "shall I pop you in" in prompt and prompt.count("to confirm then") >= 3
    assert "# Pictures and quotes" in prompt and "give me a little time to have a think" in prompt and "quote;" in prompt
    assert "# Tattoos" in prompt and "consultation" in prompt
    assert "card details" in prompt
    assert "Only say \"all booked" in persona_text


def test_tattoo_questions_go_to_carmens_whatsapp_when_configured(persona_text, salon_config_json, monkeypatch):
    from bot.prompt import build_system_prompt

    cfg = SalonConfig.from_json(salon_config_json)
    monkeypatch.delenv("CARMEN_WHATSAPP", raising=False)
    without = build_system_prompt(persona_text, cfg)
    assert "WhatsApp number is not configured" in without and "07" not in without.split("# Tattoos")[1].split("# Pictures")[0]
    monkeypatch.setenv("CARMEN_WHATSAPP", "07700 900123")
    with_number = build_system_prompt(persona_text, cfg)
    assert ("\"Hey lovely, to discuss this further you can talk to me directly on WhatsApp, I can "
            "respond much quicker on there if that's ok? 07700 900123 x\"") in with_number


# -- cancelling ---------------------------------------------------------------


UP = [
    fresha.Upcoming("1332159791", "UNCONFIRMED", "2026-10-29", "10:00", "Gel polish", "Jess", "34.00", "279113349"),
    fresha.Upcoming("1332196579", "CANCELLED", "2026-10-27", "11:30", "Biab", "Carmen", "40.00", "279113349"),
    fresha.Upcoming("1332200000", "CONFIRMED", "2026-10-29", "14:00", "Biab", "Sav", "40.00", "279113349"),
]


class CancelFresha(FakeFresha):
    def __init__(self, upcoming=UP, fee="", **kw):
        super().__init__(**kw)
        self.upcoming_rows, self.fee, self.cancelled, self.fee_checked = list(upcoming), fee, [], []

    def upcoming(self, customer_id, *, first=10):
        return self.upcoming_rows

    def cancellation_fee(self, appointment_id):
        self.fee_checked.append(appointment_id)
        return self.fee

    def cancel(self, appointment_id, *, notify=False, enforce=True):
        self.cancelled.append((appointment_id, notify, enforce))
        return appointment_id


def run_cancel(cfg, f=None, c=None, dry_run=False, **kw):
    f = f or CancelFresha()
    c = c or convo()
    a = {"date": "2026-10-29", "time": "10:00", "client_name": "Danny Cooke", **kw.pop("args", {})}
    return booking.cancel(a, cfg=cfg, convo=c, dry_run=dry_run, session=SESSION, fresha=f, now=NOW, **kw), f, c


def test_cancels_a_free_appointment_with_notification(cfg):
    saved, pinged = [], []
    out, f, c = run_cancel(cfg, save=saved.append, notify=lambda convo, summary, appt, kind="", **kw: pinged.append((summary, appt, kind)))
    assert out.startswith("Cancelled: Gel polish with Jess, Thu 29 Oct 10am, for Danny Cooke (Fresha appointment 1332159791)")
    assert f.fee_checked == ["1332159791"] and f.cancelled == [("1332159791", True, False)]
    assert c.bookings[-1]["appointment_id"] == "1332159791" and c.bookings[-1]["cancelled_at"]
    assert saved == [c] and pinged == [("Gel polish with Jess, Thu 29 Oct 10am, for Danny Cooke", "1332159791", "cancelled by the bot")]


def test_a_fee_means_hand_over_not_cancel(cfg):
    out, f, _ = run_cancel(cfg, f=CancelFresha(fee="34.00"))
    assert out.startswith("Not cancelled:") and "£34.00" in out and "'cancellation fee'" in out
    assert f.cancelled == []


def test_cancel_finds_the_right_one(cfg):
    out, f, _ = run_cancel(cfg, args={"time": ""})
    assert out.startswith("More than one that day") and "Gel polish with Jess" in out and "Biab with Sav" in out and f.cancelled == []
    out, f, _ = run_cancel(cfg, args={"time": "14:00"})
    assert out.startswith("Cancelled: Biab with Sav")
    out, f, _ = run_cancel(cfg, args={"date": "2026-10-27", "time": ""})  # that one is already cancelled
    assert out.startswith("Nothing on 2026-10-27") and "Gel polish with Jess, Thu 29 Oct 10am" in out
    out, f, _ = run_cancel(cfg, args={"date": "", "time": ""})
    assert out.startswith("Which one?") and "Biab with Carmen" not in out
    out, f, _ = run_cancel(cfg, f=CancelFresha(upcoming=[]))
    assert "no upcoming appointments" in out


def test_cancel_dry_run_and_errors(cfg):
    out, f, _ = run_cancel(cfg, dry_run=True)
    assert out.startswith("Would have cancelled (not live)") and f.cancelled == []
    out, f, _ = run_cancel(cfg, f=CancelFresha(clients=[]))
    assert out.startswith("No Fresha client") and "cancellation or rebooking" in out
    assert "in the past" in run_cancel(cfg, args={"date": "2026-10-01"})[0]
    assert "name is not known" in run_cancel(cfg, c=convo(client_name=""), args={"client_name": ""})[0]

    class Broken(CancelFresha):
        def cancel(self, *a, **kw):
            raise fresha.FreshaError("Appointment already cancelled")

    out, f, _ = run_cancel(cfg, f=Broken())
    assert out.startswith("Fresha refused the cancellation")


def test_a_cancelled_slot_can_be_booked_again(cfg):
    c = convo()
    run(cfg, c=c)
    run_cancel(cfg, c=c)
    out, f, _ = run(cfg, c=c)
    assert out.startswith("Booked") and f.created


def test_fresha_upcoming_and_fee_parse_the_dashboard_shapes():
    from test_fresha import Http

    node = {"id": "1332159791", "status": "UNCONFIRMED", "startWallClock": "2026-10-29T10:00:00[Europe/London]", "customerId": "279113349",
            "bookings": [{"price": "34.00", "service": {"name": "Gel polish "}, "employee": {"firstName": "jess", "lastName": "preston"}}]}
    http = Http({"CustomerOverviewUpcomingAppointmentQuery": {"data": {"appointments": {"edges": [{"node": node}]}}}})
    rows = fresha.Fresha(SESSION, http).upcoming("279113349", first=5)
    assert rows == [fresha.Upcoming("1332159791", "UNCONFIRMED", "2026-10-29", "10:00", "Gel polish", "Jess", "34.00", "279113349")]
    assert json.loads(http.calls[0][2]["data"]["variables"]) == {"customerId": "279113349", "first": 5}

    no_fee = Http({"initializeAppointmentProtectionEnforcement": {"errors": [{"message": "x", "extensions": {"code": "NO_FEE"}}], "data": None}})
    assert fresha.Fresha(SESSION, no_fee).cancellation_fee("1") == ""
    fee = Http({"initializeAppointmentProtectionEnforcement": {"data": {"initializeAppointmentProtectionEnforcement": {"appointmentProtectionEnforcement": {"protectionAmount": "34.00"}}}}})
    assert fresha.Fresha(SESSION, fee).cancellation_fee("1") == "34.00"


def test_handler_offers_cancel_with_the_booking_tool(monkeypatch):
    monkeypatch.setenv("SALON_CONFIG_JSON", json.dumps(CONFIG))
    monkeypatch.setenv("FRESHA_SESSION_PARAM", "/tlg/test/fresha/session")
    handler.salon.cache_clear()
    assert set(handler.tools(convo())) == {"check_availability", "book_appointment", "cancel_appointment"}
    handler.salon.cache_clear()
    assert set(brain.CANCEL_TOOL["input_schema"]["required"]) == {"date", "time", "client_name", "check_only"}


def test_prompt_and_persona_carry_the_cancel_rules(persona_text, salon_config_json):
    from bot.prompt import build_system_prompt

    prompt = build_system_prompt(persona_text, SalonConfig.from_json(salon_config_json))
    assert "# Cancelling" in prompt and "`cancel_appointment`" in prompt and "cancellation fee applies" in prompt
    assert "Never waive, argue or decide a fee" in persona_text


def test_fee_answer_scripts_the_three_way_conversation(cfg):
    out, f, _ = run_cancel(cfg, f=CancelFresha(fee="34.00"))
    assert out.startswith("Not cancelled:") and "£34.00" in out and "24-hour" in out
    assert "are sure" in out and "'cancellation fee'" in out and "Fresha confirmation" in out
    assert f.cancelled == []


def test_cancellation_fee_hand_over_locks_the_thread():
    assert "cancellation fee" in brain.ESCALATION_KINDS
    assert "cancellation fee" in handler.LOCKING_KINDS
    assert "cancellation or rebooking" not in handler.LOCKING_KINDS


def test_prompt_and_persona_carry_the_fee_script(persona_text, salon_config_json):
    from bot.prompt import build_system_prompt

    prompt = build_system_prompt(persona_text, SalonConfig.from_json(salon_config_json))
    for phrase in ["are you sure", "bear with me a moment", "link in their Fresha confirmation", "their choice to make on Fresha"]:
        assert phrase in prompt, phrase
    assert "Never waive, argue or decide a fee" in persona_text


def test_check_only_reports_the_window_without_cancelling(cfg):
    out, f, c = run_cancel(cfg, args={"check_only": True})
    assert out.startswith("Free to cancel: Gel polish with Jess, Thu 29 Oct 10am") and "1332159791" in out
    assert f.cancelled == [] and c.bookings == []
    out, f, _ = run_cancel(cfg, f=CancelFresha(fee="34.00"), args={"check_only": True})
    assert out.startswith("Not cancelled:") and f.cancelled == []
    assert "check_only" in brain.CANCEL_TOOL["input_schema"]["required"]


def test_prompt_and_persona_carry_the_move_order(persona_text, salon_config_json):
    from bot.prompt import build_system_prompt

    prompt = build_system_prompt(persona_text, SalonConfig.from_json(salon_config_json))
    assert "# Moving an appointment" in prompt
    assert prompt.index("`check_only` true for the old one") < prompt.index("`book_appointment` for the new slot") < prompt.index("without `check_only`")
    assert "book the new one, then cancel\n  the old one, in that order" in persona_text
