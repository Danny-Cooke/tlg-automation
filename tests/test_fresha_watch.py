import copy
import json
from datetime import datetime, timezone

import pytest

from fresha_watch import checks, handler, shape
from menu_sync import fresha_public

VENUE = "https://www.fresha.com/en-GB/a/the-looking-glass-beauty-shrewsbury-roushill-xa3bpl74"
GENERAL = "https://www.fresha.com/book-now/tlg-beauty-limited-xexbl23r/all-offer?share=true&pId=1453889"
NOW = datetime(2026, 10, 19, 20, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# A Fresha that can be bent out of shape
# ---------------------------------------------------------------------------


def venue_html(team, extra_location=None):
    nodes = [{"node": {"displayName": n, "employeeId": i, "jobTitle": r, "avatar": {}}} for i, n, r in team]
    location = {"name": "The Looking Glass Beauty", "employeeProfiles": {"edges": nodes}, "images": []}
    location.update(extra_location or {})
    data = {"props": {"pageProps": {"data": {"location": location}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def item(name, duration="1 hour", price="£30", description=None):
    action = json.dumps([{"type": "x", "bookableId": "sv:2", "catalogId": "s:1"}])
    return {
        "name": name,
        "caption": duration,
        "price": {"formatted": price},
        "description": description,
        "secondaryAction": {"id": action},
    }


def init_payload(categories):
    return {"data": {"bookingFlowInitialize": {"screenServices": {"categories": categories}, "screenTime": None}}}


TEAM = [("3440861", "Jess", "Salon Manager"), ("5029221", "Sav", "Nail tech")]
FULL = [
    {"name": "Senior Nail Services - TLG", "items": [item("Gel polish"), item("Biab Infill", description="BIAB")]},
    {"name": "Hair by Lori-dee", "items": [item("Cut and blow dry", "45 mins", "£38")]},
]


class Resp:
    def __init__(self, status=200, text="", body=None):
        self.status_code = status
        self.text = text if body is None else json.dumps(body)

    def json(self):
        return json.loads(self.text)


class Fresha:
    def __init__(self):
        self.team = list(TEAM)
        self.full = copy.deepcopy(FULL)
        self.extra_location = {}
        self.venue_status = 200
        self.flow_response = None  # override the whole booking-flow response
        self.general_text = "<html>The Looking Glass Beauty</html>"
        self.posts = []

    def get(self, url, **kw):
        if url == VENUE:
            return Resp(self.venue_status, venue_html(self.team, self.extra_location))
        if url == GENERAL:
            return Resp(200, self.general_text)
        raise AssertionError(url)

    def post(self, url, json=None, **kw):
        assert url == fresha_public.GRAPHQL_URL
        self.posts.append(json)
        if self.flow_response is not None:
            return self.flow_response
        emp = json["variables"]["input"]["options"]["employeeId"]
        cats = self.full if emp is None else self.full[:1]
        return Resp(200, body=init_payload(cats))


class FakeSsm:
    def __init__(self, value=None):
        self.value = value
        self.puts = []

    def get_parameter(self, Name):
        if self.value is None:
            raise RuntimeError("ParameterNotFound")
        return {"Parameter": {"Value": self.value}}

    def put_parameter(self, **kw):
        self.puts.append(kw)
        self.value = kw["Value"]


class FakeSns:
    def __init__(self):
        self.published = []

    def publish(self, **kw):
        if kw.get("PhoneNumber") == "+440000000000":
            raise RuntimeError("sandbox: number not verified")
        self.published.append(kw)


@pytest.fixture
def env():
    return {
        "FRESHA_VENUE_URL": VENUE,
        "FRESHA_GENERAL_LINK": GENERAL,
        "SALON_NAME": "Looking Glass",
        "STATE_PARAMETER": "/tlg/prod/fresha-watch/state",
        "OPS_TOPIC_ARN": "arn:aws:sns:eu-west-2:1:ops",
        "ALERT_PHONE_NUMBERS": "+447700900123, +447700900456",
    }


def settle(fresha, env, ssm=None, sns=None):
    """One run that establishes the baseline state."""
    ssm = ssm or FakeSsm()
    sns = sns or FakeSns()
    out = handler.run(http=fresha, ssm=ssm, sns=sns, env=env, now=NOW)
    return out, ssm, sns


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


def test_shape_merges_lists_and_ignores_values():
    a = shape.paths({"team": [{"name": "Jess", "id": 1}, {"name": "Sav", "id": 2, "bio": None}], "n": 2})
    b = shape.paths({"team": [{"name": "Amber", "id": 3, "bio": "hi"}], "n": "two"})
    assert a == b == ["n:value", "team:list", "team[].bio:value", "team[].id:value", "team[].name:value"]


def test_shape_sees_keys_and_kind_changes():
    old = shape.paths({"price": {"formatted": "£30"}, "caption": "1h"})
    new = shape.paths({"price": "£30", "duration": "1h"})
    assert shape.describe(old, new) == [
        "removed caption:value",
        "removed price.formatted:value",
        "added duration:value",
        "added price:value",
    ]
    assert shape.fingerprint(old) != shape.fingerprint(new)
    assert shape.describe(old, old) == []


def test_shape_depth_limit_and_empty_containers():
    assert shape.paths({"a": {"b": {"c": 1}}}, max_depth=2) == ["a.b:object"]
    assert shape.paths({"a": {}, "b": []}) == ["a:object", "b:list"]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def test_venue_page_check_reads_team_and_shape():
    r = checks.check_venue_page(Fresha(), VENUE)
    assert r.ok and r.detail == "2 team members listed"
    assert "location.employeeProfiles.edges[].node.displayName:value" in r.paths
    assert "location.name:value" in r.paths and "location.images:list" in r.paths
    # one level only for the location record: nested detail is not watched there
    assert not any(p.startswith("location.images[]") for p in r.paths)


def test_venue_page_check_fails_on_http_error_and_missing_data():
    f = Fresha()
    f.venue_status = 503
    assert not checks.check_venue_page(f, VENUE).ok

    class Plain:
        def get(self, url, **kw):
            return Resp(200, "<html>nothing</html>")

    r = checks.check_venue_page(Plain(), VENUE)
    assert not r.ok and "__NEXT_DATA__" in r.detail


def test_booking_flow_check_reads_menu_and_shape():
    r = checks.check_booking_flow(Fresha(), VENUE)
    assert r.ok and r.detail == "2 categories, 3 services"
    assert "bookingFlowInitialize.screenServices.categories[].items[].price.formatted:value" in r.paths
    assert "bookingFlowInitialize.screenTime:value" in r.paths


def test_booking_flow_check_fails_on_retired_query_and_empty_menu():
    f = Fresha()
    f.flow_response = Resp(200, body={"errors": [{"message": "PersistedQueryNotFound"}]})
    r = checks.check_booking_flow(f, VENUE)
    assert not r.ok and "PersistedQueryNotFound" in r.detail
    f.flow_response = Resp(200, body=init_payload([]))
    assert "empty" in checks.check_booking_flow(f, VENUE).detail
    f.flow_response = Resp(200, text="<html>blocked</html>")
    assert "non-JSON" in checks.check_booking_flow(f, VENUE).detail


def test_per_person_and_general_link_checks():
    f = Fresha()
    r = checks.check_booking_flow_per_person(f, VENUE, "3440861", "Jess")
    assert r.ok and r.detail == "Jess: 2 bookable services"
    assert f.posts[-1]["variables"]["input"]["options"]["employeeId"] == "3440861"
    assert checks.check_general_link(f, GENERAL, "Looking Glass").ok
    f.general_text = "<html>Page not found</html>"
    assert not checks.check_general_link(f, GENERAL, "Looking Glass").ok


# ---------------------------------------------------------------------------
# The handler: alert on transitions only
# ---------------------------------------------------------------------------


def test_first_run_saves_state_and_sends_nothing(env):
    out, ssm, sns = settle(Fresha(), env)
    assert out["ok"] and out["first_run"] and out["alerts"] == []
    assert sns.published == []
    state = handler.decode_state(ssm.value)
    assert set(state["shapes"]) == {"venue_page", "booking_flow"}
    assert state["failing"] == []
    assert ssm.puts[-1]["Tier"] == "Intelligent-Tiering"
    raw = json.loads(ssm.value)  # readable in the console, shapes packed
    assert raw["failing"] == [] and "shapes" not in raw and raw["shapes_z"]
    assert handler.decode_state("{}") == {} and handler.decode_state("") == {}


def test_unchanged_pages_stay_quiet(env):
    _, ssm, sns = settle(Fresha(), env)
    out = handler.run(http=Fresha(), ssm=ssm, sns=sns, env=env, now=NOW)
    assert out["alerts"] == [] and sns.published == []


def test_changed_shape_texts_and_emails_once(env):
    _, ssm, sns = settle(Fresha(), env)
    f = Fresha()
    for cat in f.full:
        for it in cat["items"]:
            it["pricing"] = it.pop("price")  # Fresha renames a field
    f.extra_location = {"openingHours": []}  # and adds a section to the venue page

    out = handler.run(http=f, ssm=ssm, sns=sns, env=env, now=NOW)
    kinds = {(a["check"], a["kind"]) for a in out["alerts"]}
    assert kinds == {("venue_page", "changed"), ("booking_flow", "changed")}
    flow = next(a for a in out["alerts"] if a["check"] == "booking_flow")
    assert "removed bookingFlowInitialize.screenServices.categories[].items[].price.formatted:value" in flow["lines"]
    assert "added bookingFlowInitialize.screenServices.categories[].items[].pricing.formatted:value" in flow["lines"]

    texts = [p for p in sns.published if "PhoneNumber" in p]
    emails = [p for p in sns.published if "TopicArn" in p]
    assert [t["PhoneNumber"] for t in texts] == ["+447700900123", "+447700900456"]
    assert texts[0]["Message"] == (
        "tlg-fresha-watch: something has changed in Fresha's public pages about staff, "
        "calendars or services. Details in the ops email."
    )
    assert texts[0]["MessageAttributes"]["AWS.SNS.SMS.SMSType"]["StringValue"] == "Transactional"
    assert len(emails) == 1 and emails[0]["Subject"] == "[TLG Fresha watch] CHANGED: booking_flow, venue_page"
    assert "removed bookingFlowInitialize" in emails[0]["Message"]
    assert out["sms_sent_to"] == ["+447700900123", "+447700900456"]

    # the new shape is now the baseline: the next run is quiet
    sns.published.clear()
    out = handler.run(http=f, ssm=ssm, sns=sns, env=env, now=NOW)
    assert out["alerts"] == [] and sns.published == []


def test_content_changes_are_not_structural(env):
    _, ssm, sns = settle(Fresha(), env)
    f = Fresha()
    f.team.append(("5394887", "Amber", "Lash tech"))
    f.full[0]["items"].append(item("Gel polish toes", "45 mins", "£28", description="toes"))
    f.full[0]["items"][0]["price"]["formatted"] = "£99"
    out = handler.run(http=f, ssm=ssm, sns=sns, env=env, now=NOW)
    assert out["alerts"] == [] and sns.published == []


def test_broken_then_recovered_alerts_once_each(env):
    _, ssm, sns = settle(Fresha(), env)
    broken = Fresha()
    broken.flow_response = Resp(200, body={"errors": [{"message": "PersistedQueryNotFound"}]})

    out = handler.run(http=broken, ssm=ssm, sns=sns, env=env, now=NOW)
    assert [(a["check"], a["kind"]) for a in out["alerts"]] == [("booking_flow", "failed")]
    assert sns.published[0]["Message"] == (
        "tlg-fresha-watch: Fresha's public pages about staff, calendars or services are not "
        "working (booking_flow). Details in the ops email."
    )
    assert json.loads(ssm.value)["failing"] == ["booking_flow"]
    assert handler.decode_state(ssm.value)["failing"] == ["booking_flow"]

    sns.published.clear()
    out = handler.run(http=broken, ssm=ssm, sns=sns, env=env, now=NOW)
    assert out["alerts"] == [] and sns.published == []  # still broken, already told

    out = handler.run(http=Fresha(), ssm=ssm, sns=sns, env=env, now=NOW)
    assert [(a["check"], a["kind"]) for a in out["alerts"]] == [("booking_flow", "recovered")]
    assert sns.published[0]["Message"].endswith("are working again. Details in the ops email.")


def test_venue_page_failure_skips_per_person_check(env):
    f = Fresha()
    f.venue_status = 500
    out = handler.run(http=f, ssm=FakeSsm(), sns=FakeSns(), env=env, now=NOW)
    names = [c["name"] for c in out["checks"]]
    assert "booking_flow_per_person" not in names and not out["ok"]
    assert [(a["check"], a["kind"]) for a in out["alerts"]] == [("venue_page", "failed")]


def test_dry_run_saves_and_sends_nothing(env):
    ssm, sns = FakeSsm(), FakeSns()
    f = Fresha()
    f.venue_status = 500
    out = handler.run(http=f, ssm=ssm, sns=sns, env=env, dry_run=True, now=NOW)
    assert out["dry_run"] and out["alerts"]
    assert ssm.puts == [] and sns.published == []


def test_sms_failure_does_not_stop_the_email(env):
    env["ALERT_PHONE_NUMBERS"] = "+440000000000"
    _, ssm, sns = settle(Fresha(), env)
    f = Fresha()
    f.venue_status = 500
    out = handler.run(http=f, ssm=ssm, sns=sns, env=env, now=NOW)
    assert out["sms_sent_to"] == []
    assert [p for p in sns.published if "TopicArn" in p]


def test_no_numbers_means_email_only(env):
    env["ALERT_PHONE_NUMBERS"] = ""
    _, ssm, sns = settle(Fresha(), env)
    f = Fresha()
    f.venue_status = 500
    out = handler.run(http=f, ssm=ssm, sns=sns, env=env, now=NOW)
    assert out["sms_sent_to"] == [] and len(sns.published) == 1 and "TopicArn" in sns.published[0]


def test_sms_names_the_function_and_stays_short():
    alerts = [{"check": "booking_flow", "kind": "changed", "detail": "x" * 500, "lines": ["removed " + "y" * 400]}]
    text = handler.format_sms(alerts, "tlg-prod-fresha-watch")
    assert text.startswith("tlg-prod-fresha-watch: something has changed")
    assert len(text) < 160  # one SMS segment


def test_test_sms_sends_through_the_real_path(env):
    sns = FakeSns()
    out = handler.test_sms(sns=sns, env={**env, "AWS_LAMBDA_FUNCTION_NAME": "tlg-prod-fresha-watch"})
    assert out["sms_sent_to"] == ["+447700900123", "+447700900456"]
    assert sns.published[0]["Message"].startswith("tlg-prod-fresha-watch: test message.")
    assert not any("TopicArn" in p for p in sns.published)  # no email for a test
    out = handler.test_sms(sns=FakeSns(), env={**env, "ALERT_PHONE_NUMBERS": ""})
    assert out["sms_sent_to"] == [] and "empty" in out["error"]
