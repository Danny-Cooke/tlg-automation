"""The Fresha booking client: sends what the dashboard sends, reads what it reads."""
import json

import pytest

from bot import fresha, fresha_session
from bot.fresha_ops import OPS

SESSION = fresha_session.Session(cookie="SECRET", expires_at=None)


class Resp:
    def __init__(self, status, body, text=""):
        self.status_code, self._body, self.text = status, body, text or json.dumps(body)

    def json(self):
        return self._body


class Http:
    """Answers each operation from a script; records every call."""

    def __init__(self, answers=None, status=200):
        self.answers, self.status, self.calls = answers or {}, status, []

    def _answer(self, key):
        a = self.answers.get(key, {})
        if isinstance(a, list):
            return a.pop(0)
        return a

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        op = kw["data"]["operationName"]
        return Resp(self.status, self._answer(op))

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return Resp(self.status, self._answer("search"))


def variables(call):
    return json.loads(call[2]["data"]["variables"])


@pytest.fixture
def no_session_cache():
    fresha_session.forget()
    yield
    fresha_session.forget()


def test_graphql_transport_matches_the_dashboard():
    http = Http({"viewAppointment": {"data": {"appointment": {"id": "1"}}}})
    f = fresha.Fresha(SESSION, http)
    assert f.view("1") == {"id": "1"}
    method, url, kw = http.calls[0]
    assert url == fresha.GRAPHQL
    assert kw["params"] == {"_query": "viewAppointment", "_client_platform": "web", "_client_version": fresha_session.CLIENT_VERSION, "__pid": "1453889"}
    assert kw["cookies"] == {"fresha_partners_session": "SECRET"}
    assert kw["data"]["query"] == OPS["viewAppointment"][2]
    assert "json" not in kw


def test_mutations_use_the_mutation_query_string():
    http = Http({"cancelAppointmentWithNoCharge": {"data": {"cancelAppointmentWithNoCharge": {"appointmentId": "9"}}},
                 "initializeAppointmentProtectionEnforcement": {"errors": [{"message": "no fee", "extensions": {"code": "NO_FEE"}}], "data": None}})
    f = fresha.Fresha(SESSION, http)
    assert f.cancel("9") == "9"
    first, second = http.calls
    assert first[2]["params"]["_mutation"] == "initializeAppointmentProtectionEnforcement"
    assert variables(first) == {"input": {"action": "CANCELLATION", "appointmentId": "9"}}
    assert second[2]["params"]["_mutation"] == "cancelAppointmentWithNoCharge"
    assert variables(second) == {"input": {"appointmentId": "9", "cancellationOptions": {"cancelFutureAppointments": False}, "sendNotification": False}}


def test_create_sends_the_recorded_shape():
    http = Http({"createAppointmentByEmployee": {"data": {"AppointmentsManager_createAppointmentByEmployee": {
        "appointment": {"id": "1331547555"}, "primaryBookingId": "1798702895", "warnings": None}}}})
    f = fresha.Fresha(SESSION, http)
    b = f.create(customer_id="279113349", pricing_level_id="20472294", price="48", duration_s=5400,
                 employee_id="5029221", date="2026-10-23", start="11:45", idempotency_key="SYkQPlEAAYqfYX0Cuh_KP")
    assert b == fresha.Booking("1331547555", "1798702895", ())
    v = variables(http.calls[0])
    booking = v["input"]["appointment"]["bookings"][0]
    ref = booking.pop("orderItemRef")
    assert len(ref) == 21
    assert booking == {
        "bookedServiceAddOns": [], "employees": [{"id": "5029221", "requested": False}], "resources": [],
        "servicePricingLevel": {"catalogPrice": "48", "id": "20472294"},
        "startDateAndTime": {"date": "2026-10-23", "timeOfDay": {"hours": 11, "minutes": 45, "seconds": 0},
                             "timezone": "Europe/London", "wallClockTime": "11:45:00"},
        "timeSegments": [{"durationInSeconds": 5400, "isMainServicingTime": True, "sortingId": 0, "type": "SERVICING"}],
    }
    assert v["input"]["appointment"]["customerId"] == "279113349"
    assert v["input"]["appointment"]["locationId"] == "1530970"
    assert v["input"]["appointment"]["priceModifiers"] == []
    assert v["input"]["appointmentProtection"] == {"appointmentProtectionAction": "DEFAULT_SETTINGS"}
    assert v["input"]["metadata"] == {"idempotencyKey": "SYkQPlEAAYqfYX0Cuh_KP", "source": "new"}


def test_create_without_an_id_is_an_error():
    http = Http({"createAppointmentByEmployee": {"data": {"AppointmentsManager_createAppointmentByEmployee": {"appointment": None, "warnings": [{"message": "x"}]}}}})
    with pytest.raises(fresha.FreshaError):
        fresha.Fresha(SESSION, http).create(customer_id="1", pricing_level_id="2", price="3", duration_s=60, employee_id="4", date="2026-10-23", start="10:00")


def test_availability_variables_and_parsing():
    http = Http({"availableTimeSlots": {"data": {"availableTimeSlots": {"dailyAvailableTimeSlots": [
        {"date": "2026-10-23", "closed": False, "possibleOffers": [{"startTime": "10:00:00"}, {"startTime": "10:05:00"}]},
        {"date": "2026-10-24", "closed": True, "possibleOffers": []},
    ]}}}})
    f = fresha.Fresha(SESSION, http)
    assert f.available_starts("20472294", "5029221", "2026-10-23", 5400) == ["10:00:00", "10:05:00"]
    assert variables(http.calls[0]) == {"input": {
        "attendees": [{"attendeeId": "1", "offerItems": [{"itemType": "SERVICE_PRICING_LEVEL", "offerItemId": "1", "position": 1,
                                                          "servicePricingLevel": {"forceMaxDuration": False, "ignoreAssignments": True, "requestedEmployeeId": "5029221", "servicePricingLevelId": "20472294",
                                                                                  "timeSegmentsOverride": [{"duration": 5400, "isMainServicingTime": True, "type": "SERVICING"}]}}]}],
        "dateRange": {"endDate": "2026-10-23", "startDate": "2026-10-23"}, "locationId": "1530970", "timeslotSettingsMode": "UNRESTRICTED"}, "withAttendees": False}


def test_conflicts_flatten_and_quote_reads_strategy():
    http = Http({
        "SchedulingConflicts": {"data": {"schedulingConflicts": {"scheduledItemsConflicts": [{"scheduledItemId": "x", "conflicts": [{"conflictType": "EMPLOYEE_HAS_EXISTING_APPOINTMENT"}]}]}}},
        "appointment_calculateAppointmentProtectionFees": {"data": {"calculateAppointmentProtectionFees": {"strategy": "CARD_CONFIRMATION", "cancellationFeeAmount": "34.00", "depositAmount": "0.00"}}},
    })
    f = fresha.Fresha(SESSION, http)
    assert f.conflicts("2", "5", "2026-10-23", "11:45", 5400)[0]["conflictType"] == "EMPLOYEE_HAS_EXISTING_APPOINTMENT"
    item = variables(http.calls[0])["input"]["scheduledItems"][0]
    assert item["startTime"] == "11:45:00" and item["timeSegments"] == [{"duration": 5400, "isMainServicingTime": True, "type": "SERVICING"}]
    q = f.quote("279113349", "25845686", "34")
    assert (q.strategy, q.cancellation_fee, q.deposit) == ("CARD_CONFIRMATION", "34.00", "0.00")
    assert variables(http.calls[1]) == {"input": {"customerId": "279113349", "items": [{"id": "25845686", "quantity": 1, "salePrice": "34", "serviceAddOnCorrelationId": "0-25845686", "totalGross": "34", "type": "SERVICE_PRICING_LEVEL"}]}}


def test_client_search_is_the_customers_api():
    http = Http({"search": {"data": [
        {"id": "279113349", "attributes": {"name": "Danny Cooke", "contact-number": "+44...", "email": "d@example.com", "blocked": False}},
        {"id": "2", "attributes": {"name": "Danny Other", "contact-number": None, "email": None, "blocked": True}},
    ]}})
    rows = fresha.Fresha(SESSION, http).find_clients("danny")
    assert rows[0] == fresha.Client("279113349", "Danny Cooke", "+44...", "d@example.com", False)
    assert rows[1].blocked and rows[1].phone == ""
    method, url, kw = http.calls[0]
    assert method == "GET" and url == fresha.CUSTOMERS
    assert kw["params"]["query"] == "danny" and kw["params"]["__pid"] == "1453889"
    assert kw["cookies"] == {"fresha_partners_session": "SECRET"}


def test_catalog_pages_and_flattens_pricing_levels():
    page1 = {"data": {"catalog": {"pageInfo": {"hasNextPage": True, "endCursor": "MTAw"},
                                  "categories": [{"id": "c1", "name": "Senior Nail Services - TLG"}],
                                  "edges": [{"node": {"__typename": "Pricing_CatalogService", "id": "22563223", "categoryId": "c1", "name": "Gel polish ", "employeeIds": ["3440861"],
                                                      "isPatchTestRequired": False, "servicePricingLevels": [{"id": "25845686", "name": "", "minDurationInSeconds": 3600, "maxDurationInSeconds": 3600, "price": {"listPrice": "34.00", "priceType": "STARTS_AT"}}]}}]}}}
    page2 = {"data": {"catalog": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "categories": [], "edges": [{"node": {"__typename": "Pricing_CatalogBundle", "id": "b"}}]}}}
    http = Http({"pricingCatalogList": [page1, page2]})
    rows = fresha.Fresha(SESSION, http).catalog(employee_id="3440861")
    assert rows == [fresha.Service("22563223", "Gel polish", "Senior Nail Services - TLG", "25845686", "34.00", "STARTS_AT", 3600, ("3440861",), False, "")]
    v1, v2 = variables(http.calls[0]), variables(http.calls[1])
    assert v1["after"] is None and v2["after"] == "MTAw"
    assert v1["filters"] == {"employee": {"employeePerformsService": False, "id": "3440861"}}
    assert v1["first"] == 100 and v1["locationId"] == "1530970"


def test_401_raises_session_rejected_and_forgets_cache(monkeypatch, no_session_cache):
    monkeypatch.setenv("FRESHA_SESSION_PARAM", "/x")
    fresha_session._cache.update(name="/x", until=9e18, session=SESSION)
    with pytest.raises(fresha.SessionRejected):
        fresha.Fresha(SESSION, Http(status=401)).view("1")
    assert fresha_session._cache == {}


def test_graphql_errors_become_fresha_error_without_the_cookie():
    http = Http({"viewAppointment": {"errors": [{"message": "boom", "extensions": {"code": "OTHER"}}], "data": None}})
    with pytest.raises(fresha.FreshaError) as e:
        fresha.Fresha(SESSION, http).view("1")
    assert "boom" in str(e.value) and "SECRET" not in str(e.value)
    # a tolerated code is only tolerated where asked for
    http = Http({"cancelAppointmentWithNoCharge": {"errors": [{"message": "x", "extensions": {"code": "NO_FEE"}}], "data": None},
                 "initializeAppointmentProtectionEnforcement": {"data": {}}})
    with pytest.raises(fresha.FreshaError):
        fresha.Fresha(SESSION, http).cancel("9")


def test_cancel_checks_the_echoed_id():
    http = Http({"initializeAppointmentProtectionEnforcement": {"data": {}},
                 "cancelAppointmentWithNoCharge": {"data": {"cancelAppointmentWithNoCharge": {"appointmentId": "other"}}}})
    with pytest.raises(fresha.FreshaError):
        fresha.Fresha(SESSION, http).cancel("9")


def test_nanoid_shape():
    ids = {fresha.nanoid() for _ in range(50)}
    assert len(ids) == 50 and all(len(i) == 21 for i in ids)


def test_upcoming_asks_for_a_big_page_and_reads_the_card():
    http = Http({"CustomerOverviewUpcomingAppointmentQuery": {"data": {"appointments": {"edges": [
        {"node": {"id": "11", "status": "CANCELLED", "startWallClock": "2026-10-23T11:00:00[Europe/London]", "customerId": "5",
                  "bookings": [{"service": {"name": "Gel polish"}, "employee": {"firstName": "JESS"}, "price": "34.00"}]}},
        {"node": {"id": "12", "status": "UNCONFIRMED", "startWallClock": "2026-10-29T11:00:00[Europe/London]", "customerId": "5",
                  "bookings": [{"service": {"name": "Dry cut"}, "employee": {"firstName": "Lori-Dee"}, "price": "30.00"}]}},
    ]}}}})
    f = fresha.Fresha(SESSION, http)
    rows = f.upcoming("5")
    assert variables(http.calls[0]) == {"customerId": "5", "first": 100}  # cancelled ones are in the page too
    assert [(r.appointment_id, r.status, r.date, r.time, r.service, r.person) for r in rows] == [
        ("11", "CANCELLED", "2026-10-23", "11:00", "Gel polish", "Jess"),
        ("12", "UNCONFIRMED", "2026-10-29", "11:00", "Dry cut", "Lori-Dee"),
    ]
