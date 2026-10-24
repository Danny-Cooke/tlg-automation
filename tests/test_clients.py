"""The client mirror and the stop link (plan job 10)."""
import json
import re
from urllib.parse import urlencode

import pytest

from bot import fresha, fresha_session
from clients import model, sync, unsubscribe
from clients.store import ClientStore

SESSION = fresha_session.Session(cookie="SECRET", expires_at=None)


# ---------------------------------------------------------------------------
# A DynamoDB table in a dict: just the calls the store makes
# ---------------------------------------------------------------------------


class FakeTable:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None, ConditionExpression=None):
        names = ExpressionAttributeNames or {}
        row = self.items.setdefault(Key["client_id"], {"client_id": Key["client_id"]})
        if ConditionExpression:  # only the patch-test rule is used: a Fresha record is never replaced by an assumption
            assert "patch_test_basis <> :record" in ConditionExpression
            v = ExpressionAttributeValues
            if row.get("patch_tested") and row.get("patch_test_basis") == v[":record"] and v[":b"] != v[":record"]:
                raise Exception("An error occurred (ConditionalCheckFailedException) when calling the UpdateItem operation")
        assert UpdateExpression.startswith("SET ")
        for part in re.split(r",\s*(?![^()]*\))", UpdateExpression[4:]):  # commas inside if_not_exists(...) stay
            target, expr = [x.strip() for x in part.split(" = ", 1)]
            target = names.get(target, target)
            m = re.fullmatch(r"if_not_exists\((\S+), (:\S+)\)", expr)
            if m:
                existing = names.get(m.group(1), m.group(1))
                if existing in row:
                    continue
                row[target] = ExpressionAttributeValues[m.group(2)]
            else:
                row[target] = ExpressionAttributeValues[expr]

    def scan(self, **kw):
        return {"Items": [dict(r) for r in self.items.values()]}

    def query(self, IndexName, KeyConditionExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        assert IndexName == "by_token"
        want = ExpressionAttributeValues[":t"]
        return {"Items": [dict(r) for r in self.items.values() if r.get("token") == want]}


# ---------------------------------------------------------------------------
# Fresha as the sync sees it
# ---------------------------------------------------------------------------


def detail(cid, name, phone="+44 7700 900123", sms=True, email_mkt=True, blocked=False, source="Walk-In", labels=None):
    first, _, last = name.partition(" ")
    return {
        "data": {
            "id": cid, "type": "customers-v2",
            "attributes": {
                "name": name, "first-name": first, "last-name": last, "contact-number": phone, "email": f"{first}@example.com".upper(),
                "blocked": blocked, "accepts-sms-marketing-notifications": sms, "accepts-marketing-notifications": email_mkt,
                "accepts-whatsapp-marketing-notifications": False, "labels": labels, "created-at": "2026-04-27T18:54:16Z",
                "updated-at": "2026-10-20T10:00:00Z",
            },
            "relationships": {"referral-source": {"data": {"id": "7", "type": "referral-sources"}}},
        },
        "included": [{"id": "7", "type": "referral-sources", "attributes": {"name": source}}],
    }


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


def record(*, patch_tests=(), allergies=(), notes=(), tags=(), no_shows=0, staff_alert="", upcoming=(), past=()):
    """The `clientRecord` GraphQL data for one client, the shape Fresha answers with."""
    edges = lambda nodes: {"edges": [{"node": n} for n in nodes]}  # noqa: E731
    return {
        "customer": {
            "id": "1", "staffAlert": staff_alert, "hasPaymentMethod": True, "birthdayDay": 16, "birthdayMonth": 9, "birthdayYear": None,
            "gender": "FEMALE", "pronoun": None, "patchTestCount": len(patch_tests),
            "labels": edges([{"__typename": "Customers_NoShowLabel", "id": "ns", "count": no_shows}] if no_shows else []),
            "tags": edges([{"id": str(i), "name": t} for i, t in enumerate(tags)]),
            "segmentBadges": edges([{"id": "7", "definition": {"badgeName": "First visit"}}]),
            "allergies": edges([{"id": "a1", "name": a, "severity": "HIGH", "type": "PRODUCT", "reaction": "rash", "description": ""} for a in allergies]),
            "patchTests": edges([{"id": "p1", "title": t, "status": "PERFORMED", "performedDate": "2026-10-01", "isExpired": expired,
                                  "createdAt": "2026-10-01T10:00:00Z", "confirmationRequired": False, "expirationDate": exp}
                                 for t, expired, exp in patch_tests]),
        },
        "notes": edges([{"id": "n1", "body": n, "type": "CLIENT", "createdAt": "2026-10-02T10:00:00Z", "lastEditedAt": None,
                         "authorType": "EMPLOYEE", "author": {"id": "e1", "fullName": "Jess Example"}, "authorClient": None,
                         "appointment": None, "attachments": []} for n in notes]),
        "attachments": edges([{"id": "f1", "fileName": "before.jpg", "contentType": "image/jpeg", "fileSizeBytes": 1234, "kind": "IMAGE",
                               "createdAt": "2026-10-02T10:00:00Z"}]),
        "upcoming": edges([_appt("9001", s, "2026-11-03T09:00:00", "BOOKED") for s in upcoming]),
        "past": edges([_appt("9000", s, "2026-09-01T10:00:00", "COMPLETED") for s in past]),
    }


def _appt(aid, service, start, status):
    return {
        "id": aid, "status": status, "statusLabelId": status.lower(), "startWallClock": start, "primaryBookingId": "b", "salesOrderId": None,
        "consultationForms": [], "preferredNote": {"note": {"id": "pn", "body": "bring inspo"}},
        "bookings": [{"id": "b", "priceType": "FIXED", "price": 34.0, "startWallClock": start, "endDatetime": start,
                      "servicePricingLevelId": "lvl1", "service": {"name": service, "servicePricingLevels": [{"id": "lvl1", "name": "Standard"}]},
                      "employee": {"firstName": "Sophie", "lastName": "Cooper"},
                      "bookingServiceAddOns": [{"serviceAddOnId": "x", "serviceAddOn": {"name": "Toner"}}]}],
    }


STATS = {"data": {"id": "1", "type": "customer-statistics", "attributes": {"bookings-count": 3, "no-show-bookings-count": 1, "total-sales": 102.5}}}
FORMS = {"data": [{"id": "fr1", "type": "requests", "attributes": {"status": "completed", "requested-at": "2026-10-01T09:00:00Z", "form-name": "Colour consultation"}}],
         "meta": {"all-count": 1}}


class FreshaHttp:
    """Answers the client search in pages of `cap` whatever limit is asked for,
    each client's record, and the three profile-page calls. Records every URL."""

    def __init__(self, clients: list[dict], *, cap=25, count=True, status=200, records=None, record_status=200, flagged=()):
        self.clients, self.cap, self.count, self.status, self.calls = clients, cap, count, status, []
        self.records, self.record_status = records or {}, record_status
        self.flagged = list(flagged)  # services Fresha flags as needing a patch test

    def get(self, url, **kw):
        self.calls.append(url)
        if self.status != 200:
            return Resp(self.status, {})
        params = kw["params"]
        if url.endswith("customer-search"):
            offset, limit = int(params["offset"]), min(int(params["limit"]), self.cap)
            rows = [{"id": c["data"]["id"], "type": "customer-search-results-v2", "attributes": {"name": c["data"]["attributes"]["name"]}}
                    for c in self.clients[offset:offset + limit]]
            return Resp(200, {"data": rows, "meta": {"results-count": len(self.clients) if self.count else None}})
        if url.endswith("/statistics"):
            return Resp(200, STATS)
        if url.endswith("/requests"):
            return Resp(200, FORMS)
        cid = url.rsplit("/", 1)[1]
        return Resp(200, next(c for c in self.clients if c["data"]["id"] == cid))

    def post(self, url, **kw):
        self.calls.append(url)
        if self.record_status != 200:
            return Resp(self.record_status, {})
        data = kw["data"]
        if data["operationName"] == "pricingCatalogList":
            edges = [{"node": {"__typename": "Pricing_CatalogService", "id": str(i), "name": n, "categoryId": "c", "isPatchTestRequired": True,
                               "employeeIds": ["1"], "servicePricingLevels": [{"id": f"l{i}", "price": {"listPrice": "16.00", "priceType": "FIXED"},
                                                                               "maxDurationInSeconds": 1200}]}}
                     for i, n in enumerate(self.flagged)]
            return Resp(200, {"data": {"catalog": {"categories": [{"id": "c", "name": "Beauty - TLG"}], "edges": edges, "pageInfo": {}}}})
        assert data["operationName"] == "clientRecord" and kw["params"]["_query"] == "clientRecord"
        cid = json.loads(data["variables"])["customerId"]
        return Resp(200, {"data": self.records.get(cid) or record()})


@pytest.fixture
def table():
    return FakeTable()


# ---------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw, want", [
    ("+44 7517 048938", "+447517048938"),
    ("07517 048938", "+447517048938"),
    ("44 7428 858012", "+447428858012"),
    ("0044 7428 858012", "+447428858012"),
    ("+353 87 123 4567", "+353871234567"),
    ("", ""), (None, ""), ("12345", ""), ("not a number", ""),
])
def test_phone_numbers_become_e164(raw, want):
    assert model.e164(raw) == want


def test_fresha_record_becomes_a_row():
    c = model.from_detail(detail("279113349", "Danny Cooke", labels=["vip"], source="Book Now Link"))
    assert c.client_id == "279113349" and c.first_name == "Danny" and c.last_name == "Cooke"
    assert c.mobile == "+447700900123" and c.email == "danny@example.com"
    assert c.accepts_sms_marketing and c.accepts_email_marketing and not c.accepts_whatsapp_marketing
    assert c.labels == ["vip"] and c.referral_source == "Book Now Link" and not c.blocked


def test_textable_needs_everything_to_line_up():
    base = {"in_fresha": True, "mobile": "+447700900123", "accepts_sms_marketing": True, "sms_opt_out": False, "blocked": False}
    assert model.textable(base)
    for change in ({"in_fresha": False}, {"mobile": ""}, {"accepts_sms_marketing": False}, {"sms_opt_out": True}, {"blocked": True}):
        assert not model.textable({**base, **change}), change


def test_tokens_are_eight_safe_characters():
    for _ in range(50):
        t = model.new_token()
        assert len(t) == 8 and set(t) <= set(model.TOKEN_ALPHABET)


# ---------------------------------------------------------------------------
# store: Fresha's side and ours never overwrite each other
# ---------------------------------------------------------------------------


def test_sync_writes_fresha_fields_and_creates_ours_once(table):
    store = ClientStore(table)
    store.upsert_from_fresha(model.from_detail(detail("1", "Amy Pond")), now=100)
    row = table.items["1"]
    token = row["token"]
    assert row["name"] == "Amy Pond" and row["mobile"] == "+447700900123" and row["in_fresha"] is True
    assert row["sms_opt_out"] is False and row["lists"] == [] and row["fresha_pending"] is False and len(token) == 8

    store.set_opt_out("1", True, source="link", now=200)
    assert row["sms_opt_out"] is True and row["opt_out_changed_at"] == 200 and row["fresha_pending"] is True

    # The next sync changes what Fresha says, and nothing of ours.
    store.upsert_from_fresha(model.from_detail(detail("1", "Amy Williams", sms=False)), now=300)
    assert row["name"] == "Amy Williams" and row["accepts_sms_marketing"] is False and row["synced_at"] == 300
    assert row["sms_opt_out"] is True and row["token"] == token and row["fresha_pending"] is True


def test_clients_gone_from_fresha_are_flagged_not_deleted(table):
    store = ClientStore(table)
    for cid in ("1", "2", "3"):
        store.upsert_from_fresha(model.from_detail(detail(cid, f"Client {cid}")))
    assert store.mark_missing({"1", "3"}, now=50) == ["2"]
    assert table.items["2"]["in_fresha"] is False and table.items["2"]["synced_at"] == 50
    assert store.mark_missing({"1", "3"}) == []  # already flagged: not reported again
    assert store.summary()["in_fresha"] == 2


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


def test_sync_pages_the_whole_list_whatever_fresha_caps_a_page_at(table):
    clients = [detail(str(i), f"Client {i}", sms=i % 3 != 0, phone="" if i == 5 else "+44 7700 900123") for i in range(1, 61)]
    http = FreshaHttp(clients, cap=25)  # we ask for 50, Fresha gives 25
    out = sync.run(fresha.Fresha(SESSION, http=http), ClientStore(table), pause=0)
    assert out["fresha_clients"] == 60 and out["fetched"] == 60 and out["rows"] == 60
    assert sum(1 for u in http.calls if u.endswith("customer-search")) == 3
    assert out["fresha_sms_yes"] == 40 and out["with_mobile"] == 59 and out["textable"] == 39 and out["marked_missing"] == 0


def test_sync_stops_on_an_empty_page_when_fresha_gives_no_total(table):
    http = FreshaHttp([detail("1", "A"), detail("2", "B")], cap=25, count=False)
    out = sync.run(fresha.Fresha(SESSION, http=http), ClientStore(table), pause=0)
    assert out["fresha_clients"] == 2 and sum(1 for u in http.calls if u.endswith("customer-search")) == 2


def test_dry_run_writes_nothing(table):
    http = FreshaHttp([detail("1", "A")])
    out = sync.run(fresha.Fresha(SESSION, http=http), ClientStore(table), dry_run=True, pause=0)
    assert out["dry_run"] and out["fetched"] == 1 and table.items == {}


def test_sync_handler_without_a_session_tells_ops(monkeypatch):
    monkeypatch.delenv("FRESHA_SESSION_PARAM", raising=False)
    monkeypatch.setenv("OPS_TOPIC_ARN", "arn:topic")
    sent = []
    monkeypatch.setattr(sync, "_sns", lambda: type("S", (), {"publish": lambda self, **kw: sent.append(kw)})())
    assert sync.lambda_handler({}) == {"error": "no Fresha session"}
    assert "no Fresha session" in sent[0]["Subject"]


def test_rejected_session_is_reported_not_raised(table, monkeypatch):
    monkeypatch.setenv("FRESHA_SESSION_PARAM", "/x")
    monkeypatch.setattr(fresha_session, "get", lambda **kw: SESSION)
    monkeypatch.setattr(fresha.Fresha, "client_page", lambda self, **kw: (_ for _ in ()).throw(fresha.SessionRejected("HTTP 401")))
    monkeypatch.setattr(sync, "patch_test_services", lambda f: set())  # no real catalog call
    monkeypatch.setattr(sync, "ClientStore", lambda: ClientStore(table))
    sent = []
    monkeypatch.setenv("OPS_TOPIC_ARN", "arn:topic")
    monkeypatch.setattr(sync, "_sns", lambda: type("S", (), {"publish": lambda self, **kw: sent.append(kw)})())
    out = sync.lambda_handler({})
    assert "401" in out["error"] and "rejected" in sent[0]["Subject"]


# ---------------------------------------------------------------------------
# unsubscribe
# ---------------------------------------------------------------------------


def event(method, token, body=None):
    return {
        "requestContext": {"http": {"method": method}},
        "pathParameters": {"token": token},
        "body": urlencode(body) if body else "",
    }


@pytest.fixture
def stored(table):
    store = ClientStore(table)
    store.upsert_from_fresha(model.from_detail(detail("1", "Amy Pond")))
    return store, table.items["1"]["token"]


def test_get_shows_a_button_and_changes_nothing(stored):
    store, token = stored
    out = unsubscribe.lambda_handler(event("GET", token), store=store)
    assert out["statusCode"] == 200 and "Hi Amy" in out["body"] and 'value="stop"' in out["body"] and "Stop texts" in out["body"]
    assert store.by_token(token)["sms_opt_out"] is False


def test_post_stop_opts_out_and_offers_the_way_back(stored):
    store, token = stored
    out = unsubscribe.lambda_handler(event("POST", token, {"action": "stop"}), store=store)
    assert out["statusCode"] == 200 and "Done, Amy" in out["body"] and 'value="start"' in out["body"]
    row = store.by_token(token)
    assert row["sms_opt_out"] is True and row["opt_out_source"] == "link" and row["fresha_pending"] is True
    out = unsubscribe.lambda_handler(event("GET", token), store=store)
    assert "not getting offer texts" in out["body"] and "Get offers again" in out["body"]
    out = unsubscribe.lambda_handler(event("POST", token, {"action": "start"}), store=store)
    assert "Welcome back, Amy" in out["body"] and store.by_token(token)["sms_opt_out"] is False


def test_unknown_token_is_a_404_and_head_is_harmless(stored):
    store, token = stored
    assert unsubscribe.lambda_handler(event("GET", "nope1234"), store=store)["statusCode"] == 404
    assert unsubscribe.lambda_handler(event("POST", "nope1234", {"action": "stop"}), store=store)["statusCode"] == 404
    out = unsubscribe.lambda_handler(event("HEAD", token), store=store)
    assert out["statusCode"] == 200 and out["body"] == "" and store.by_token(token)["sms_opt_out"] is False


def test_bad_action_is_refused(stored):
    store, token = stored
    assert unsubscribe.lambda_handler(event("POST", token, {"action": "delete"}), store=store)["statusCode"] == 400
    assert store.by_token(token)["sms_opt_out"] is False


def test_page_escapes_and_names_the_salon(monkeypatch):
    monkeypatch.setenv("SALON_NAME", "The Looking Glass Beauty")
    html = unsubscribe.page("<b>", "a & b", button="Go", action="stop")
    assert "&lt;b&gt;" in html and "a &amp; b" in html and "The Looking Glass Beauty" in html and 'name="robots" content="noindex"' in html


# ---------------------------------------------------------------------------
# the two Fresha reads
# ---------------------------------------------------------------------------


def test_client_page_and_detail_send_what_the_dashboard_sends():
    http = FreshaHttp([detail("9", "Zed")])
    f = fresha.Fresha(SESSION, http=http)
    rows, count = f.client_page(offset=0, limit=50)
    assert [r["id"] for r in rows] == ["9"] and count == 1
    doc = f.client_detail("9")
    assert doc["data"]["attributes"]["accepts-sms-marketing-notifications"] is True
    assert http.calls[1].endswith("/v2/customers/9")


# ---------------------------------------------------------------------------
# the profile page: patch tests, allergies, notes, appointments (2026-10-24)
# ---------------------------------------------------------------------------


def test_profile_record_becomes_row_fields():
    rec = record(patch_tests=[("Colour patch test", False, "2027-04-01"), ("Old tint test", True, "2025-01-01")],
                 allergies=["PPD"], notes=["Prefers Sophie"], tags=["VIP"], no_shows=2, staff_alert="Owes £10",
                 upcoming=["Half a head of foils"], past=["Dry cut"])
    extra = model.from_record(rec, STATS, FORMS, now=500)
    assert extra["birthday"] == "09-16" and extra["gender"] == "FEMALE" and extra["staff_alert"] == "Owes £10"
    assert extra["flags"] == ["no-show x2"] and extra["tags"] == ["VIP"] and extra["segments"] == ["First visit"]
    assert extra["allergies"][0]["name"] == "PPD" and extra["allergy_count"] == 1
    assert [t["title"] for t in extra["patch_tests"]] == ["Colour patch test", "Old tint test"]
    assert extra["patch_tests"][0]["active"] is True and extra["patch_tests"][1]["active"] is False
    assert extra["patch_test_active"] is True and extra["patch_test_count"] == 2
    assert extra["notes"] == [{"id": "n1", "type": "CLIENT", "body": "Prefers Sophie", "created": "2026-10-02T10:00:00Z", "edited": "",
                               "author": "Jess Example", "appointment_id": "", "attachments": []}]
    assert extra["attachments"][0]["file_name"] == "before.jpg" and "signed" not in json.dumps(extra["attachments"])
    up = extra["upcoming"][0]
    assert up["status"] == "BOOKED" and up["services"][0]["name"] == "Half a head of foils" and up["services"][0]["with"] == "Sophie Cooper"
    assert up["services"][0]["level"] == "Standard" and up["services"][0]["price"] == "34.0" and up["services"][0]["add_ons"] == ["Toner"]
    assert up["note"] == "bring inspo" and extra["past"][0]["services"][0]["name"] == "Dry cut"
    assert extra["appointment_count"] == 3 and extra["stats"]["no_show_bookings_count"] == 1
    assert extra["forms"] == [{"id": "fr1", "status": "completed", "requested_at": "2026-10-01T09:00:00Z", "form_name": "Colour consultation"}]
    assert extra["record_synced_at"] == 500 and extra["record_error"] == ""


def test_patch_test_past_its_expiry_date_is_not_active_even_if_fresha_says_so():
    extra = model.from_record(record(patch_tests=[("Tint", False, "2020-01-01")]))
    assert extra["patch_test_active"] is False and extra["patch_tests"][0]["expired"] is True


def test_empty_profile_is_fine():
    extra = model.from_record({"customer": {}, "notes": None}, {}, [])
    assert extra["patch_tests"] == [] and extra["patch_test_active"] is False and extra["birthday"] == "" and extra["forms"] == []
    assert extra["appointment_count"] == 0 and extra["stats"] == {}


def test_row_has_no_floats_for_dynamodb():
    import decimal
    item = model.FreshaClient(client_id="1", name="A", stats={"total-sales": 102.5}, upcoming=[{"price": 1.5}]).as_item()
    assert isinstance(item["stats"]["total-sales"], decimal.Decimal) and isinstance(item["upcoming"][0]["price"], decimal.Decimal)


def test_sync_fetches_the_profile_page_and_stores_it(table):
    http = FreshaHttp([detail("1", "Amy Pond")], records={"1": record(patch_tests=[("Colour", False, "2027-01-01")], notes=["note"])})
    out = sync.run(fresha.Fresha(SESSION, http=http), ClientStore(table), pause=0, now=700)
    row = table.items["1"]
    assert out["records"] == 1 and out["record_errors"] == 0 and out["remaining"] == 0
    assert row["patch_test_active"] is True and row["note_count"] == 1 and row["record_synced_at"] == 700 and row["synced_at"] == 700
    assert out["with_patch_tests"] == 1 and out["patch_test_active"] == 1 and out["with_notes"] == 1 and out["with_profile"] == 1
    # The catalog (patch-test services), one search page, then per client: record, GraphQL profile, statistics, forms.
    assert [u.rsplit("/", 1)[1] for u in http.calls] == ["graphql", "customer-search", "1", "graphql", "statistics", "requests"]


def test_profile_failure_keeps_the_basic_row_and_says_why(table):
    http = FreshaHttp([detail("1", "Amy Pond")], record_status=500)
    out = sync.run(fresha.Fresha(SESSION, http=http), ClientStore(table), pause=0)
    row = table.items["1"]
    assert out["records"] == 0 and out["record_errors"] == 1 and out["profile_errors"] == 1
    assert row["name"] == "Amy Pond" and row["record_error"].startswith("Fresha HTTP 500") and row["record_synced_at"] == 0


def test_stalest_clients_are_refreshed_first_and_the_rest_wait_for_next_run(table):
    store = ClientStore(table)
    clients = [detail(str(i), f"Client {i}") for i in range(1, 5)]
    # 2 and 3 were fetched before, 3 longer ago; 1 and 4 never.
    for cid, when in (("2", 900), ("3", 100)):
        store.upsert_from_fresha(dataclasses_replace(model.from_detail(detail(cid, f"Client {cid}")), record_synced_at=when))
    assert store.stalest_first(["1", "2", "3", "4"]) == ["1", "4", "3", "2"]

    http = FreshaHttp(clients)
    out = sync.run(fresha.Fresha(SESSION, http=http), store, pause=0, limit=2, now=1000)
    assert out["fetched"] == 2 and table.items["1"]["record_synced_at"] == 1000 and table.items["4"]["record_synced_at"] == 1000
    assert table.items["3"]["record_synced_at"] == 100 and out["marked_missing"] == 0

    # A deadline already passed: nothing fetched, everything reported as remaining, missing still marked.
    out = sync.run(fresha.Fresha(SESSION, http=FreshaHttp(clients[:3])), store, pause=0, deadline=0.0)
    assert out["fetched"] == 0 and out["remaining"] == 3 and out["marked_missing"] == 1 and table.items["4"]["in_fresha"] is False


def dataclasses_replace(client, **kw):
    import dataclasses

    return dataclasses.replace(client, **kw)


def test_lambda_handler_passes_the_time_budget_and_limit(monkeypatch):
    seen = {}
    monkeypatch.setattr(fresha_session, "get", lambda: SESSION)
    monkeypatch.setattr(sync, "run", lambda f, store, **kw: seen.update(kw) or {"ok": True})
    monkeypatch.setattr(sync, "ClientStore", lambda: object())

    class Ctx:
        def get_remaining_time_in_millis(self):
            return 300_000

    assert sync.lambda_handler({"limit": "5", "dry_run": True}, Ctx()) == {"ok": True}
    assert seen["limit"] == 5 and seen["dry_run"] is True and seen["deadline"] is not None


def test_profile_calls_send_what_the_dashboard_sends():
    http = FreshaHttp([detail("9", "Zed")], records={"9": record(tags=["VIP"])})
    f = fresha.Fresha(SESSION, http=http)
    assert f.client_record("9")["customer"]["tags"]["edges"][0]["node"]["name"] == "VIP"
    assert f.client_statistics("9")["data"]["attributes"]["bookings-count"] == 3
    assert f.client_forms("9")["meta"]["all-count"] == 1
    assert http.calls == [fresha.GRAPHQL, "https://partners-api.fresha.com/customers/9/statistics", fresha.FORMS]


# ---------------------------------------------------------------------------
# our patch-test column (user, 2026-10-24)
# ---------------------------------------------------------------------------


def test_patch_test_is_assumed_from_the_latest_attended_flagged_service():
    past = [
        {"status": "COMPLETED", "start": "2026-03-01T10:00", "services": [{"name": "Brow Tint", "start": "2026-03-01T10:00"}]},
        {"status": "CANCELLED", "start": "2026-09-01T10:00", "services": [{"name": "Brow Tint", "start": "2026-09-01T10:00"}]},
        {"status": "NO_SHOW", "start": "2026-09-02T10:00", "services": [{"name": "Classic lashes", "start": "2026-09-02T10:00"}]},
        {"status": "UNCONFIRMED", "start": "2026-06-01T10:00", "services": [{"name": "brow  tint", "start": "2026-06-01T10:00"}]},
        {"status": "COMPLETED", "start": "2026-08-01T10:00", "services": [{"name": "Gel polish", "start": "2026-08-01T10:00"}]},
    ]
    ev = model.patch_test_evidence({"past": past, "patch_tests": []}, {"Brow Tint", "Classic lashes"})
    assert ev == {"patch_tested": True, "patch_test_basis": "assumed from brow  tint on 2026-06-01 (unconfirmed)",
                  "patch_test_date": "2026-06-01", "patch_test_service": "brow  tint"}
    assert model.patch_test_evidence({"past": past[4:], "patch_tests": []}, {"Brow Tint"}) is None
    # Any lash or brow appointment counts even with nothing flagged in Fresha; makeup and removals do not.
    assert model.patch_test_evidence({"past": past, "patch_tests": []}, set())["patch_test_service"] == "brow  tint"
    for name, want in (("Lash lift and tint", True), ("Classic lash infill", True), ("Brow Wax", True), ("lash patch test", True),
                       ("Make up by the lash goblin", False), ("Lash removal", False), ("Gel polish", False), ("", False)):
        assert model.counts_as_patch_test(name, set()) is want, name
    assert model.counts_as_patch_test("Gel polish", {"gel polish"}) is True


def test_a_fresha_record_beats_the_assumption():
    fields = {"past": [{"status": "COMPLETED", "start": "2026-03-01", "services": [{"name": "Brow Tint"}]}],
              "patch_tests": [{"active": False, "performed": "2024-01-01"}, {"active": True, "performed": "2026-10-01", "title": "Lash glue"}]}
    ev = model.patch_test_evidence(fields, {"Brow Tint"})
    assert ev["patch_test_basis"] == "fresha record" and ev["patch_test_date"] == "2026-10-01" and ev["patch_test_service"] == "Lash glue"


def test_store_keeps_a_record_over_an_assumption_and_the_sync_never_clears_it(table):
    store = ClientStore(table)
    store.upsert_from_fresha(model.from_detail(detail("1", "Amy Pond")))
    store.set_patch_tested("1", {"patch_test_basis": "assumed from Brow Tint on 2026-03-01 (completed)", "patch_test_date": "2026-03-01",
                                 "patch_test_service": "Brow Tint"}, now=10)
    row = table.items["1"]
    assert row["patch_tested"] is True and row["patch_test_set_at"] == 10
    store.set_patch_tested("1", {"patch_test_basis": "fresha record", "patch_test_date": "2026-10-01", "patch_test_service": "Lash glue"}, now=20)
    assert row["patch_test_basis"] == "fresha record" and row["patch_test_date"] == "2026-10-01"
    store.set_patch_tested("1", {"patch_test_basis": "assumed from Brow Tint on 2026-03-01 (completed)", "patch_test_date": "2026-03-01",
                                 "patch_test_service": "Brow Tint"}, now=30)
    assert row["patch_test_basis"] == "fresha record" and row["patch_test_set_at"] == 20  # the condition held
    store.upsert_from_fresha(model.from_detail(detail("1", "Amy Pond")), now=40)
    assert row["patch_tested"] is True  # Fresha's side of the sync never touches our column


def test_sync_reads_the_flagged_services_from_fresha_and_fills_the_column(table):
    recs = {"1": record(past=["Brow Tint"]), "2": record(past=["Gel polish"]), "3": record(patch_tests=[("Glue", False, "2027-01-01")])}
    http = FreshaHttp([detail(c, f"Client {c}") for c in ("1", "2", "3")], records=recs, flagged=["Brow Tint", "Classic lashes"])
    out = sync.run(fresha.Fresha(SESSION, http=http), ClientStore(table), pause=0, now=500)
    assert out["patch_test_services"] == ["Brow Tint", "Classic lashes"] and out["patch_test_evidence"] == 2
    assert out["patch_tested"] == 2 and out["patch_tested_from_record"] == 1
    assert table.items["1"]["patch_test_basis"] == "assumed from Brow Tint on 2026-09-01 (completed)"
    assert "patch_tested" not in table.items["2"] and table.items["3"]["patch_test_basis"] == "fresha record"
    assert sync.patch_test_services(fresha.Fresha(SESSION, http=http)) == {"Brow Tint", "Classic lashes"}

