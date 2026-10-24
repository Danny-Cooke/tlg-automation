"""The bot's view of patch tests (plan job 12, 2026-10-24)."""
import pytest

from bot import patch_tests
from bot.state import Conversation
from clients.store import ClientStore


class Table:
    def __init__(self, rows):
        self.rows, self.scans = rows, 0

    def scan(self, **kw):
        self.scans += 1
        return {"Items": [dict(r) for r in self.rows]}


ROWS = [
    {"client_id": "1", "name": "Amy Pond", "first_name": "Amy", "last_name": "Pond", "patch_tested": True,
     "patch_test_basis": "assumed from Brow Tint on 2026-09-01 (completed)", "patch_test_date": "2026-09-01"},
    {"client_id": "2", "name": "Rory Williams", "first_name": "Rory", "last_name": "Williams"},
    {"client_id": "3", "name": "Amy Pond", "first_name": "Amy", "last_name": "Pond", "in_fresha": False},
    {"client_id": "4", "name": "", "first_name": "River", "last_name": "Song", "patch_tested": True, "patch_test_basis": "fresha record",
     "patch_test_date": "2026-10-01"},
]


@pytest.fixture(autouse=True)
def no_cache():
    patch_tests.forget()
    yield
    patch_tests.forget()


def store():
    return ClientStore(Table(ROWS))


def test_which_services_need_a_test():
    for name, want in (("Lash lift and tint", True), ("Brow Tint", True), ("Classic lash infill", True), ("Gel polish", False),
                       ("Make up by the lash goblin", False), ("Lash removal", False), ("lash patch test", False), ("", False)):
        assert patch_tests.needs_patch_test(name) is want, name
    assert patch_tests.needs_patch_test("Gel polish", True) is True  # Fresha's tick counts too
    assert patch_tests.needs_patch_test("lash patch test", True) is False  # the test itself never needs a test
    assert patch_tests.is_patch_test_service("Lash Patch Test") and not patch_tests.is_patch_test_service("lash tint")


def test_status_reads_the_column_and_prefers_the_tested_namesake():
    s = store()
    assert patch_tests.status({"client_name": "amy  pond"}, store=s) == (
        "Patch tested: assumed from Brow Tint on 2026-09-01 (completed). Book the treatment as normal.")
    assert patch_tests.status({"client_name": "Rory Williams"}, store=s).startswith("No patch test on record for Rory Williams: arrange one at least 24 hours")
    assert patch_tests.status({"client_name": "River Song"}, store=s) == "Patch tested: fresha record, 2026-10-01. Book the treatment as normal."
    assert patch_tests.status({"client_name": "Nobody Here"}, store=s).startswith("No client called 'Nobody Here'")
    assert patch_tests.status({}, store=s) == "Need the client's name."
    assert patch_tests.is_tested("Amy Pond", store=s) and not patch_tests.is_tested("Rory Williams", store=s)


def test_rows_are_cached_per_container(monkeypatch):
    table = Table(ROWS)
    monkeypatch.setattr(patch_tests, "ClientStore", lambda: ClientStore(table))
    assert patch_tests.is_tested("Amy Pond") and patch_tests.is_tested("Amy Pond") and not patch_tests.is_tested("Rory Williams")
    assert table.scans == 1


def test_a_patch_test_booked_earlier_in_the_thread_counts_if_far_enough_ahead():
    c = Conversation(sender_id="p", bookings=[{"service": "lash patch test", "date": "2026-10-28", "time": "11:00", "appointment_id": "1"}])
    assert patch_tests.booked_in_conversation(c, "2026-10-29", "11:00")  # exactly 24 hours
    assert patch_tests.booked_in_conversation(c, "2026-10-30", "09:00")
    assert not patch_tests.booked_in_conversation(c, "2026-10-29", "10:30")  # too close
    assert not patch_tests.booked_in_conversation(c, "2026-10-28", "15:00")
    assert patch_tests.booked_in_conversation(c, "2026-10-29", "09:00", lead_hours=12)
    c.bookings[0]["cancelled_at"] = 5
    assert not patch_tests.booked_in_conversation(c, "2026-10-30", "11:00")
    c.bookings = [{"service": "Gel polish", "date": "2026-10-28", "time": "11:00"}]
    assert not patch_tests.booked_in_conversation(c, "2026-10-30", "11:00")
    assert not patch_tests.booked_in_conversation(Conversation(sender_id="p"), "bad", "date")
