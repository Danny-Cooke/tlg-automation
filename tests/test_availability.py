"""Fresha public-flow availability, against a fake HTTP that plays the screens
the real flow returned on 2026-10-20 (shapes only, no client data)."""
import json

import pytest

from bot import availability
from menu_sync import fresha_public

LOCATION = "1530970"


def add_action(bookable="sv:25845686", catalog="s:22563223"):
    return json.dumps([{"type": "onScreenServicesServiceVariantAdd", "bookableId": bookable, "catalogId": catalog,
                        "membershipId": None, "requiresPatchTest": False, "orderId": 0, "employeeRequired": True}, LOCATION])


def modal_action(catalog="s:24900277"):
    return json.dumps([{"type": "onScreenServicesModalServiceOpen", "catalogId": catalog,
                        "serviceVariants": [{"id": "sv:28451687", "requiresPatchTest": True}, {"id": "sv:28451688"}]}, LOCATION])


def date_entry(iso, available=True, selected=False):
    return {
        "date": {"iso": f"{iso}T00:00:00.000Z"},
        "isAvailableToBeBooked": available,
        "isSelected": selected,
        "action": None if selected else {"id": json.dumps([{"type": "onScreenTimeDaySelectorDateSet", "date": iso}, LOCATION])},
    }


def time_screen(selected_iso, slots_seconds, dates):
    return {
        "screen": {"__typename": "BookingFlowScreenTime"},
        "screenTime": {
            "dates": dates,
            "day": {"timeslots": [{"time": s} for s in slots_seconds]},
            "continueAction": {"id": "x"},
        },
    }


class Resp:
    def __init__(self, body, status=200):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class FakeFresha:
    """Serves the flow for one person: Jess, who offers Gel polish and a two-variant Apprentice gel."""

    def __init__(self):
        self.calls = []
        self.dates = [date_entry("2026-10-20", selected=True), date_entry("2026-10-21"), date_entry("2026-10-25", available=False)]
        self.slots = {"2026-10-20": [48600, 49500], "2026-10-21": [36000]}

    def post(self, url, json, headers, timeout):
        op = json["operationName"]
        self.calls.append((op, json["variables"]))
        if op == fresha_public.INIT_OPERATION:
            return Resp({"data": {"bookingFlowInitialize": {
                "cartId": "cart-1",
                "screenServices": {"categories": [{"items": [
                    {"name": "Gel polish", "primaryAction": {"id": add_action()}},
                    {"name": "Apprentice  Gel polish", "primaryAction": {"id": modal_action()}},
                ]}]},
            }}})
        action = json["variables"]["id"]
        first = __import__("json").loads(action)[0]
        if first["type"] == "onScreenServicesServiceVariantAdd":
            return Resp({"data": {"bookingFlowActionButtonPressed": {
                "screen": {"__typename": "BookingFlowScreenServices"},
                "screenServices": {"continueAction": {"id": json_continue()}},
            }}})
        if first["type"] == "onScreenServicesContinue":
            return Resp({"data": {"bookingFlowActionButtonPressed": time_screen("2026-10-20", self.slots["2026-10-20"], self.dates)}})
        if first["type"] == "onScreenTimeDaySelectorDateSet":
            return Resp({"data": {"bookingFlowActionButtonPressed": time_screen(first["date"], self.slots.get(first["date"], []), self.dates)}})
        return Resp({"errors": [{"message": f"unknown action {first['type']}"}]})


def json_continue():
    return json.dumps([{"type": "onScreenServicesContinue"}, LOCATION])


def test_check_walks_the_flow_and_reads_each_day():
    http = FakeFresha()
    out = availability.check(http, "https://www.fresha.com/en-GB/a/the-looking-glass-xa3bpl74", service="gel polish",
                             people=[("Jess", "3440861")], dates=["2026-10-21", "2026-10-20", "2026-10-25", "2026-12-25"])
    assert len(out) == 1 and out[0].note == ""
    assert out[0].days == {
        "2026-10-20": ["1:30pm", "1:45pm"],  # the selected day comes straight off the time screen
        "2026-10-21": ["10am"],  # another day needs one more press
        "2026-10-25": [],  # listed but not bookable (Sunday)
        "2026-12-25": [],  # not listed at all
    }
    ops = [op for op, _ in http.calls]
    assert ops == [fresha_public.INIT_OPERATION] + [availability.PRESS_OPERATION] * 3
    assert http.calls[0][1]["input"]["options"]["employeeId"] == "3440861"
    assert all(v.get("cartId") == "cart-1" for _, v in http.calls[1:])


def test_multi_variant_service_builds_the_add_action():
    http = FakeFresha()
    out = availability.check(http, "https://www.fresha.com/x", service="Apprentice gel polish", people=[("Jess", "1")], dates=["2026-10-20"])
    assert out[0].days["2026-10-20"] == ["1:30pm", "1:45pm"]
    built = json.loads(http.calls[1][1]["id"])
    assert built[0]["type"] == "onScreenServicesServiceVariantAdd"
    assert built[0]["bookableId"] == "sv:28451687" and built[0]["requiresPatchTest"] is True
    assert built[1] == LOCATION


def test_unknown_service_and_failures_become_notes_not_exceptions():
    http = FakeFresha()
    out = availability.check(http, "https://www.fresha.com/x", service="Unicorn wash", people=[("Jess", "1")], dates=["2026-10-20"])
    assert "does not list 'Unicorn wash'" in out[0].note and out[0].days == {}

    class Down:
        def post(self, *a, **k):
            return Resp({"errors": [{"message": "PersistedQueryNotFound"}]})

    out = availability.check(Down(), "https://www.fresha.com/x", service="Gel polish", people=[("Jess", "1")], dates=["2026-10-20"])
    assert "PersistedQueryNotFound" in out[0].note

    class Broken:
        def post(self, *a, **k):
            raise ConnectionError("boom")

    out = availability.check(Broken(), "https://www.fresha.com/x", service="Gel polish", people=[("Jess", "1")], dates=["2026-10-20"])
    assert "could not check Fresha" in out[0].note


def test_limits_people_and_dates_and_rejects_bad_dates():
    http = FakeFresha()
    out = availability.check(http, "https://www.fresha.com/x", service="Gel polish",
                             people=[("A", "1"), ("B", "2"), ("C", "3"), ("D", "4")], dates=["next friday"])
    assert [r.person for r in out] == ["A", "B", "C"]
    assert all("no valid dates" in r.note for r in out)
    assert http.calls == []  # nothing fetched for nonsense dates


def test_format_for_model_is_one_line_per_person_and_day():
    rows = [
        availability.PersonAvailability("Jess", "Gel polish", {"2026-10-23": ["10am", "10:15am"], "2026-10-24": []}),
        availability.PersonAvailability("Sav", "Gel polish", note="Fresha does not list 'Gel polish' for this person"),
    ]
    text = availability.format_for_model(rows)
    assert text.splitlines() == [
        "Gel polish with Jess, Fri 23 Oct: 10am, 10:15am",
        "Gel polish with Jess, Sat 24 Oct: nothing free",
        "Gel polish with Sav: Fresha does not list 'Gel polish' for this person",
    ]


@pytest.mark.parametrize("seconds,text", [(36000, "10am"), (48600, "1:30pm"), (0, "12am"), (43200, "12pm"), (60300, "4:45pm")])
def test_clock(seconds, text):
    assert availability._clock(seconds) == text
