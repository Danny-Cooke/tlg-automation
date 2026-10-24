"""The confirmation chaser (plan job 14, 2026-10-24)."""
import datetime as dt
import zoneinfo

import pytest

from bot import fresha, fresha_session
from clients import chaser
from clients.store import ClientStore

SESSION = fresha_session.Session(cookie="SECRET", expires_at=None)
LONDON = zoneinfo.ZoneInfo("Europe/London")
NOW = dt.datetime(2026, 10, 28, 6, 0, tzinfo=LONDON)  # chases Friday 30th


class Table:
    def __init__(self, rows):
        self.rows = {r["client_id"]: dict(r) for r in rows}

    def scan(self, **kw):
        return {"Items": [dict(r) for r in self.rows.values()]}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, **kw):
        assert UpdateExpression == "SET chased = list_append(if_not_exists(chased, :empty), :one)"
        row = self.rows[Key["client_id"]]
        row["chased"] = row.get("chased", []) + ExpressionAttributeValues[":one"]


def appt(aid, start, status="UNCONFIRMED", service="Gel polish", person="Jess Preston"):
    return {"id": aid, "status": status, "start": f"{start}[Europe/London]", "services": [{"name": service, "with": person}]}


ROWS = [
    {"client_id": "1", "name": "Amy Pond", "first_name": "Amy", "mobile": "+447700900001",
     "upcoming": [appt("a1", "2026-10-30T14:00:00"), appt("a2", "2026-10-31T10:00:00")]},
    {"client_id": "2", "name": "Rory Williams", "first_name": "Rory", "mobile": "+447700900002",
     "upcoming": [appt("b1", "2026-10-30T10:30:00", service="Acrylic Infill", person="Sav Calvert")]},
    {"client_id": "3", "name": "River Song", "first_name": "River", "mobile": "",
     "upcoming": [appt("c1", "2026-10-30T11:00:00")]},
    {"client_id": "4", "name": "Clara Oswald", "first_name": "Clara", "mobile": "+447700900004",
     "upcoming": [appt("d1", "2026-10-30T12:00:00", status="CONFIRMED")]},
    {"client_id": "5", "name": "Danny Pink", "first_name": "Danny", "mobile": "+447700900005",
     "upcoming": [appt("e1", "2026-10-30T15:00:00")], "chased": [{"appointment_id": "e1", "at": 1}]},
    {"client_id": "6", "name": "Gone Client", "first_name": "Gone", "mobile": "+447700900006", "in_fresha": False,
     "upcoming": [appt("f1", "2026-10-30T16:00:00")]},
]


class Fresha:
    def __init__(self, live=None):
        self.live, self.viewed, self.reminded = live or {}, [], []

    def view(self, appointment_id):
        self.viewed.append(appointment_id)
        return {"id": appointment_id, "status": self.live.get(appointment_id, "UNCONFIRMED")}

    def send_protection_reminder(self, appointment_id):
        self.reminded.append(appointment_id)
        return appointment_id


class Sms:
    def __init__(self, fail=()):
        self.sent, self.fail = [], set(fail)

    def send_text_message(self, **kw):
        if kw["DestinationPhoneNumber"] in self.fail:
            raise RuntimeError("sandbox")
        self.sent.append(kw)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("CHASER_TEXT", "CHASER_EMAIL_SUBJECT"):
        monkeypatch.delenv(k, raising=False)


def test_dry_run_lists_who_would_be_chased_and_sends_nothing():
    table, f, sms = Table(ROWS), Fresha(), Sms()
    out = chaser.run(f, ClientStore(table), sms=sms, now=NOW, dry_run=True)
    assert out["date"] == "2026-10-30" and out["candidates"] == 4  # Amy a1, Rory b1, River c1, Danny e1 (Clara confirmed, Gone not in Fresha)
    assert out["would_chase"] == 2 and out["no_mobile"] == 1 and out["already_chased"] == 1 and out["chased"] == 0
    assert sms.sent == [] and sorted(f.viewed) == ["a1", "b1"] and all("chased" not in r or r["client_id"] == "5" for r in table.rows.values())
    assert any(l.startswith("  would text: Amy Pond: Gel polish Fri 30 Oct at 2pm") for l in out["lines"])
    assert any(l.startswith("  no mobile, ring them: River Song") for l in out["lines"])


def test_live_run_texts_in_jesss_voice_once_per_appointment_and_skips_the_newly_confirmed():
    table, f, sms = Table(ROWS), Fresha(live={"b1": "CONFIRMED"}), Sms()
    out = chaser.run(f, ClientStore(table), sms=sms, now=NOW, dry_run=False, sender_id="TLGWATCH")
    assert out["chased"] == 1 and out["confirmed_meanwhile"] == 1 and out["failed"] == 0
    assert len(sms.sent) == 1 and sms.sent[0]["DestinationPhoneNumber"] == "+447700900001"
    assert sms.sent[0]["MessageType"] == "TRANSACTIONAL" and sms.sent[0]["OriginationIdentity"] == "TLGWATCH"
    assert sms.sent[0]["MessageBody"] == ("Hi Amy, still ok for Gel polish with Jess on Fri 30 Oct at 2pm? Please tap Confirm in the email "
                                          "Fresha sent you, titled 'Please confirm your appointment'. Need to change it? Just message us x")
    assert table.rows["1"]["chased"] == [{"appointment_id": "a1", "at": int(NOW.timestamp())}]
    assert f.reminded == []
    # Run again the same morning: nothing more goes out.
    again = chaser.run(f, ClientStore(table), sms=sms, now=NOW, dry_run=False)
    assert again["chased"] == 0 and again["already_chased"] == 2 and len(sms.sent) == 1


def test_fresha_reminder_is_pressed_when_asked_and_a_failed_text_is_not_marked():
    table, f, sms = Table(ROWS), Fresha(), Sms(fail={"+447700900002"})
    out = chaser.run(f, ClientStore(table), sms=sms, now=NOW, dry_run=False, send_fresha_reminder=True)
    assert out["chased"] == 1 and out["failed"] == 1 and sorted(f.reminded) == ["a1", "b1"]
    assert "chased" not in table.rows["2"] and table.rows["1"]["chased"][0]["appointment_id"] == "a1"


def test_message_wording_is_configurable_and_the_date_can_be_forced(monkeypatch):
    monkeypatch.setenv("CHASER_EMAIL_SUBJECT", "New appointment")
    monkeypatch.setenv("CHASER_TEXT", "{first}: {service} / {person} / {when} / {subject}")
    out = chaser.run(Fresha(), ClientStore(Table(ROWS)), sms=Sms(), now=NOW, dry_run=True, target_date="2026-10-31")
    assert out["candidates"] == 1 and out["would_chase"] == 1
    assert chaser.message("Amy", appt("x", "2026-10-31T10:30:00", service="Biab", person="carmen smith")) == "Amy: Biab / carmen / Sat 31 Oct at 10.30am / New appointment"
    assert chaser._when("2026-10-30T09:05:00[Europe/London]") == "Fri 30 Oct at 9.05am" and chaser._when("") == ""
    assert chaser._services({"services": [{"name": "Biab"}, {"name": "Biab"}, {"name": "Toner"}]}) == "Biab and Toner"


def test_handler_keeps_texts_off_until_told_and_emails_the_report(monkeypatch):
    monkeypatch.setenv("FRESHA_SESSION_PARAM", "/x")
    monkeypatch.setenv("OPS_TOPIC_ARN", "arn:topic")
    monkeypatch.setenv("CHASER_SEND_TEXTS", "false")
    monkeypatch.setattr(fresha_session, "get", lambda **kw: SESSION)
    monkeypatch.setattr(chaser, "ClientStore", lambda: ClientStore(Table(ROWS)))
    monkeypatch.setattr(fresha, "Fresha", lambda session: Fresha())
    sent = []
    monkeypatch.setattr(chaser, "_sns", lambda: type("S", (), {"publish": lambda self, **kw: sent.append(kw)})())
    out = chaser.lambda_handler({"date": "2026-10-30"})
    assert out["dry_run"] is True and out["texts_enabled"] is False and out["would_chase"] == 2
    assert sent and "dry run" in sent[0]["Subject"] and "Texts are switched off" in sent[0]["Message"] and "Amy Pond" in sent[0]["Message"]

    monkeypatch.setenv("CHASER_SEND_TEXTS", "true")
    monkeypatch.setattr(chaser, "_sms", lambda: Sms())
    out = chaser.lambda_handler({"date": "2026-10-30"})
    assert out["dry_run"] is False and out["chased"] == 2 and sent[-1]["Subject"].startswith("[TLG] Confirmation chaser: 2 of 4")


def test_handler_without_a_session_tells_ops(monkeypatch):
    monkeypatch.setenv("OPS_TOPIC_ARN", "arn:topic")
    monkeypatch.setattr(fresha_session, "get", lambda **kw: None)
    sent = []
    monkeypatch.setattr(chaser, "_sns", lambda: type("S", (), {"publish": lambda self, **kw: sent.append(kw)})())
    assert chaser.lambda_handler({}) == {"error": "no Fresha session"} and "no Fresha session" in sent[0]["Subject"]
