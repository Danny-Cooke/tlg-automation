import json
from datetime import datetime, timezone

import pytest

from monitor import checks, handler

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class Resp:
    def __init__(self, status=200, text="", body=None):
        self.status_code = status
        self.text = text if body is None else json.dumps(body)

    def json(self):
        return json.loads(self.text)


class FakeHttp:
    """Routes GET by URL prefix. Records params so tests can assert on them."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                return resp(url, kw) if callable(resp) else resp
        return Resp(404, "no route")


class FakeSsm:
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


class FakeSns:
    def __init__(self):
        self.published = []

    def publish(self, **kw):
        self.published.append(kw)


class FakeCloudwatch:
    def get_metric_statistics(self, MetricName, **kw):
        return {"Datapoints": [{"Sum": 12.0 if MetricName == "Invocations" else 0.0}]}


# A minimal runtime bundle in the shape the real one has, plus a chunk that
# contains the create-variables builder.
RUNTIME = (
    'r.u=e=>"static/js/async/"+(({10:"module.calendar.rootView",20:"package.appointments.ViewAppointmentDrawer"})[e]||e)'
    '+"."+({10:"aaaaaaaaaa",20:"bbbbbbbbbb"})[e]+".js"'
)
BUILDER = (
    "let{appointmentDetails:t,appointmentProtection:n,idempotencyKey:a,locationId:s,priceModifiers:l,timezone:d,"
    "waitlistEntryId:c}=e,{customerId:m,startDate:p,completeBookingItems:u,bookingSequence:g,entryPoint:I}=t,"
    "f=(0,r.s2)({startDate:p,timezone:d})(u);return{appointment:{bookings:f,locationId:s,...m?{customerId:m}:{}},"
    "metadata:{idempotencyKey:a,source:I}}"
)
CHUNK = "n(381845);AppointmentsManager_createAppointmentByEmployee;availableTimeSlots;" + BUILDER + "}})},300178(e,t,n){"


def fresha_routes(chunk=CHUNK):
    return {
        checks.FRESHA_PARTNERS_URL: Resp(
            200, 'x APP_VERSION":"2.8.12070" y assets-v2/static/js/runtime.2d11722498.js z'
        ),
        checks.FRESHA_PARTNERS_CDN + "runtime.": Resp(200, RUNTIME),
        checks.FRESHA_PARTNERS_CDN + "async/package.appointments.ViewAppointmentDrawer.bbbbbbbbbb.js": Resp(200, chunk),
    }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def test_webhook_check_round_trips_challenge():
    http = FakeHttp({"https://api/webhook": lambda url, kw: Resp(200, kw["params"]["hub.challenge"])})
    r = checks.check_webhook(http, "https://api/webhook", "tok")
    assert r.ok
    assert http.calls[0][1]["params"]["hub.verify_token"] == "tok"


def test_webhook_check_fails_on_wrong_body():
    http = FakeHttp({"https://api/webhook": Resp(403, "verification failed")})
    r = checks.check_webhook(http, "https://api/webhook", "tok")
    assert not r.ok and "403" in r.detail


def test_meta_page_check_requires_messages_subscription():
    base = "https://graph.facebook.com/v21.0"
    http = FakeHttp(
        {
            f"{base}/me": Resp(body={"id": "page1", "name": "TLG"}),
            f"{base}/page1/subscribed_apps": Resp(body={"data": [{"subscribed_fields": ["messages", "feed"]}]}),
        }
    )
    r = checks.check_meta_page(http, base, "tok", "page1")
    assert r.ok and r.fingerprint
    http.routes[f"{base}/page1/subscribed_apps"] = Resp(body={"data": [{"subscribed_fields": ["feed"]}]})
    assert not checks.check_meta_page(http, base, "tok", "page1").ok


def test_meta_page_check_rejects_token_for_other_page():
    base = "https://graph.facebook.com/v21.0"
    http = FakeHttp({f"{base}/me": Resp(body={"id": "other", "name": "X"})})
    r = checks.check_meta_page(http, base, "tok", "page1")
    assert not r.ok and "other" in r.detail


def test_fresha_links_check_needs_salon_name_on_page():
    http = FakeHttp({"https://www.fresha.com/a": Resp(200, "Welcome to The Looking Glass Beauty"), "https://x": Resp(500)})
    assert checks.check_fresha_links(http, ["https://www.fresha.com/a"], "Looking Glass").ok
    r = checks.check_fresha_links(http, ["https://www.fresha.com/a", "https://x"], "Looking Glass")
    assert not r.ok and "HTTP 500" in r.detail
    r = checks.check_fresha_links(http, ["https://www.fresha.com/a"], "Other Salon")
    assert not r.ok and "does not mention" in r.detail


def test_fresha_dashboard_check_reads_version_and_runtime():
    r = checks.check_fresha_dashboard(FakeHttp(fresha_routes()))
    assert r.ok
    assert r.info == {"version": "2.8.12070", "runtime": "runtime.2d11722498.js"}
    assert r.fingerprint is None  # versions churn daily; never alert on them


def test_parse_chunk_map():
    assert checks.parse_chunk_map(RUNTIME) == {
        "module.calendar.rootView": "aaaaaaaaaa",
        "package.appointments.ViewAppointmentDrawer": "bbbbbbbbbb",
    }
    assert checks.parse_chunk_map("nothing here") == {}


def test_normalise_js_ignores_minifier_renames():
    a = checks.normalise_js("let{appointmentDetails:t,x:n}=e;n(381845)")
    b = checks.normalise_js("let{appointmentDetails:q,x:z}=w;z(990011)")
    assert a == b
    assert "appointmentDetails" in a


def test_create_contract_fingerprint_is_stable_across_builds():
    r1 = checks.check_fresha_create_contract(FakeHttp(fresha_routes()), "runtime.2d11722498.js")
    renamed = CHUNK.replace(":t,", ":q,").replace("=e,", "=w,").replace("381845", "5")
    r2 = checks.check_fresha_create_contract(FakeHttp(fresha_routes(renamed)), "runtime.2d11722498.js")
    assert r1.ok and r2.ok
    assert r1.fingerprint == r2.fingerprint


def test_create_contract_fingerprint_moves_when_shape_changes():
    r1 = checks.check_fresha_create_contract(FakeHttp(fresha_routes()), "runtime.2d11722498.js")
    changed = CHUNK.replace("locationId:s,", "locationId:s,venueId:v,")
    r2 = checks.check_fresha_create_contract(FakeHttp(fresha_routes(changed)), "runtime.2d11722498.js")
    assert r1.fingerprint != r2.fingerprint


def test_create_contract_fails_when_operation_or_builder_missing():
    gone = CHUNK.replace("AppointmentsManager_createAppointmentByEmployee", "somethingElse")
    r = checks.check_fresha_create_contract(FakeHttp(fresha_routes(gone)), "runtime.2d11722498.js")
    assert not r.ok and "AppointmentsManager_createAppointmentByEmployee" in r.detail
    r = checks.check_fresha_create_contract(FakeHttp(fresha_routes("no builder here")), "runtime.2d11722498.js")
    assert not r.ok and "builder not found" in r.detail


# ---------------------------------------------------------------------------
# Diffing and alerting
# ---------------------------------------------------------------------------


def R(name, ok=True, fp=None):
    return checks.CheckResult(name, ok, "detail", fingerprint=fp)


def test_diff_reports_transitions_only():
    prev = {"failing": ["a"], "fingerprints": {"c": "111"}}
    results = [R("a", ok=True), R("b", ok=False), R("c", fp="222"), R("d", fp="333")]
    kinds = {(x["check"], x["kind"]) for x in handler.diff(prev, results)}
    assert kinds == {("a", "recovered"), ("b", "failed"), ("c", "changed")}
    # steady state: same failures, same fingerprints -> nothing
    prev = {"failing": ["b"], "fingerprints": {"c": "222", "d": "333"}}
    assert handler.diff(prev, results) == []


def test_first_run_records_fingerprints_without_alerting_on_them():
    results = [R("c", fp="222")]
    assert handler.diff({}, results) == []
    state = handler.next_state({}, results, datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert state["fingerprints"] == {"c": "222"}
    assert state["failing"] == []


def test_format_alert_headline_prefers_failed():
    alerts = [
        {"check": "x", "kind": "changed", "detail": "1 -> 2"},
        {"check": "y", "kind": "failed", "detail": "boom"},
    ]
    subject, body = handler.format_alert(alerts, [R("x", fp="2"), R("y", ok=False)], datetime.now(timezone.utc))
    assert subject.startswith("[TLG monitor] FAILING: x, y")
    assert "FAILED  y: boom" in body and "CHANGED  x" in body


# ---------------------------------------------------------------------------
# End to end through run()
# ---------------------------------------------------------------------------


@pytest.fixture
def monitor_env(monkeypatch):
    monkeypatch.setenv("WEBHOOK_URL", "https://api/webhook")
    monkeypatch.setenv("META_PAGE_ID", "page1")
    monkeypatch.setenv("MONITOR_STATE_PARAMETER", "/tlg/monitor")
    monkeypatch.setenv("OPS_TOPIC_ARN", "arn:aws:sns:eu-west-2:1:ops")
    monkeypatch.setenv("FRESHA_LINKS_JSON", json.dumps(["https://www.fresha.com/a"]))
    monkeypatch.setenv("SALON_NAME", "Looking Glass")
    monkeypatch.setenv("BOT_FUNCTION_NAME", "tlg-dev-bot")


def healthy_http():
    base = "https://graph.facebook.com/v21.0"
    return FakeHttp(
        {
            "https://api/webhook": lambda url, kw: Resp(200, kw["params"]["hub.challenge"]),
            f"{base}/me": Resp(body={"id": "page1", "name": "TLG"}),
            f"{base}/page1/subscribed_apps": Resp(body={"data": [{"subscribed_fields": ["messages"]}]}),
            "https://www.fresha.com/a": Resp(200, "The Looking Glass Beauty"),
            **fresha_routes(),
        }
    )


def test_run_is_silent_when_healthy_and_unchanged(monitor_env):
    secrets = {"verify_token": "tok", "page_token": "pt"}
    ssm, sns = FakeSsm(), FakeSns()
    first = handler.run(http=healthy_http(), ssm=ssm, sns=sns, cloudwatch=FakeCloudwatch(), secrets=secrets)
    assert first["ok"] and first["alerts"] == []
    assert sns.published == []
    assert set(first["checks"]) == {
        "webhook_endpoint", "meta_page", "fresha_links", "fresha_dashboard", "fresha_create_contract", "bot_traffic",
    }
    second = handler.run(http=healthy_http(), ssm=ssm, sns=sns, cloudwatch=FakeCloudwatch(), secrets=secrets)
    assert second["alerts"] == [] and sns.published == []


def test_run_alerts_on_failure_then_recovery_once_each(monitor_env):
    secrets = {"verify_token": "tok", "page_token": "pt"}
    ssm, sns = FakeSsm(), FakeSns()
    handler.run(http=healthy_http(), ssm=ssm, sns=sns, cloudwatch=FakeCloudwatch(), secrets=secrets)

    broken = healthy_http()
    broken.routes["https://api/webhook"] = Resp(502, "bad gateway")
    handler.run(http=broken, ssm=ssm, sns=sns, cloudwatch=FakeCloudwatch(), secrets=secrets)
    handler.run(http=broken, ssm=ssm, sns=sns, cloudwatch=FakeCloudwatch(), secrets=secrets)
    assert len(sns.published) == 1
    assert sns.published[0]["Subject"] == "[TLG monitor] FAILING: webhook_endpoint"

    handler.run(http=healthy_http(), ssm=ssm, sns=sns, cloudwatch=FakeCloudwatch(), secrets=secrets)
    assert len(sns.published) == 2
    assert sns.published[1]["Subject"] == "[TLG monitor] RECOVERED: webhook_endpoint"


def test_run_alerts_when_fresha_contract_changes(monitor_env):
    secrets = {"verify_token": "tok", "page_token": "pt"}
    ssm, sns = FakeSsm(), FakeSns()
    handler.run(http=healthy_http(), ssm=ssm, sns=sns, cloudwatch=FakeCloudwatch(), secrets=secrets)
    drifted = healthy_http()
    drifted.routes.update(fresha_routes(CHUNK.replace("locationId:s,", "locationId:s,venueId:v,")))
    out = handler.run(http=drifted, ssm=ssm, sns=sns, cloudwatch=FakeCloudwatch(), secrets=secrets)
    assert [a["kind"] for a in out["alerts"]] == ["changed"]
    assert sns.published[-1]["Subject"] == "[TLG monitor] CHANGED: fresha_create_contract"


def test_run_survives_a_crashing_check(monitor_env):
    secrets = {"verify_token": "tok", "page_token": "pt"}

    class Exploding(FakeHttp):
        def get(self, url, **kw):
            if "graph.facebook" in url:
                raise OSError("dns")
            return super().get(url, **kw)

    http = Exploding(healthy_http().routes)
    out = handler.run(http=http, ssm=FakeSsm(), sns=FakeSns(), cloudwatch=FakeCloudwatch(), secrets=secrets)
    assert out["checks"]["meta_page"]["ok"] is False
    assert out["checks"]["webhook_endpoint"]["ok"] is True
