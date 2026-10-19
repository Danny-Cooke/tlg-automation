import json
from datetime import datetime, timezone

import pytest

from menu_sync import fresha_public, handler, model
from menu_sync.github_client import GitHub, GitHubError

VENUE = "https://www.fresha.com/en-GB/a/the-looking-glass-beauty-shrewsbury-roushill-xa3bpl74"


# ---------------------------------------------------------------------------
# Fixtures that look like Fresha
# ---------------------------------------------------------------------------


def venue_html(team):
    nodes = [{"node": {"displayName": n, "employeeId": i, "jobTitle": r, "avatar": {}}} for i, n, r in team]
    data = {"props": {"pageProps": {"data": {"location": {"employeeProfiles": {"edges": nodes}}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def item(name, duration, price, description="", service_id="1", level_id="2"):
    action = json.dumps([{"type": "x", "bookableId": f"sv:{level_id}", "catalogId": f"s:{service_id}"}])
    return {
        "name": name,
        "caption": duration,
        "price": {"formatted": price},
        "description": description,
        "secondaryAction": {"id": action},
    }


def init_payload(categories):
    return {"data": {"bookingFlowInitialize": {"screenServices": {"categories": categories}}}}


FULL = [
    {"name": "Featured", "items": [item("Gel polish", "1 hour", "from £34")]},
    {"name": "Senior Nail Services - TLG", "items": [item("Gel polish ", "1 hour", "from £34", "Gel colour on natural nails"), item("Biab Infill", "1 hour 15 mins", "from £40")]},
    {"name": "Hair by Lori-dee", "items": [item("Cut and blow dry", "45 mins", "£38")]},
]
TEAM = [("3440861", "Jess", "Salon Manager"), ("5003108", "Lori-Dee", "Senior Hair stylist/manager "), ("5029221", "Sav", "Nail tech ")]
PER_PERSON = {
    "3440861": [{"name": "Senior Nail Services - TLG", "items": [item("Gel polish", "1 hour", "from £34"), item("Biab Infill", "1 hour 15 mins", "from £40")]}],
    "5003108": [{"name": "Hair by Lori-dee", "items": [item("Cut and blow dry", "45 mins", "£38")]}],
    "5029221": [{"name": "Senior Nail Services - TLG", "items": [item("Gel polish", "1 hour", "from £34")]}],
}


class Resp:
    def __init__(self, status=200, text="", body=None):
        self.status_code = status
        self.text = text if body is None else json.dumps(body)

    def json(self):
        return json.loads(self.text)


class FreshaHttp:
    """Serves the venue page and the booking-flow mutation, per employee."""

    def __init__(self, team=TEAM, full=FULL, per_person=PER_PERSON):
        self.team, self.full, self.per_person = team, full, per_person
        self.posts = []

    def get(self, url, **kw):
        assert url == VENUE
        return Resp(200, venue_html(self.team))

    def post(self, url, json=None, **kw):
        self.posts.append(json)
        assert url == fresha_public.GRAPHQL_URL
        assert json["extensions"]["persistedQuery"]["sha256Hash"] == fresha_public.INIT_QUERY_HASH
        emp = json["variables"]["input"]["options"]["employeeId"]
        cats = self.full if emp is None else self.per_person.get(emp, [])
        return Resp(200, body=init_payload(cats))


# ---------------------------------------------------------------------------
# Reading Fresha
# ---------------------------------------------------------------------------


def test_location_slug():
    assert fresha_public.location_slug(VENUE) == "the-looking-glass-beauty-shrewsbury-roushill-xa3bpl74"
    assert fresha_public.location_slug(VENUE + "/?x=1") == "the-looking-glass-beauty-shrewsbury-roushill-xa3bpl74"


def test_parse_team_reads_next_data():
    team = fresha_public.parse_team(venue_html(TEAM))
    assert [t.name for t in team] == ["Jess", "Lori-Dee", "Sav"]
    assert team[1].job_title == "Senior Hair stylist/manager"  # whitespace cleaned
    assert team[0].employee_id == "3440861"


def test_parse_team_fails_loudly_when_page_changes():
    with pytest.raises(fresha_public.FreshaError):
        fresha_public.parse_team("<html>no data</html>")


def test_parse_menu_drops_featured_and_cleans_names():
    cats = fresha_public.parse_menu(init_payload(FULL))
    assert [c.name for c in cats] == ["Senior Nail Services - TLG", "Hair by Lori-dee"]
    gel = cats[0].items[0]
    assert gel.name == "Gel polish" and gel.price == "from £34" and gel.duration == "1 hour"
    assert gel.service_id == "1" and gel.pricing_level_id == "2"


def test_parse_menu_surfaces_graphql_errors():
    with pytest.raises(fresha_public.FreshaError, match="PersistedQueryNotFound"):
        fresha_public.parse_menu({"errors": [{"message": "PersistedQueryNotFound"}]})


def test_fetch_menu_sends_employee_id():
    http = FreshaHttp()
    fresha_public.fetch_menu(http, VENUE, "3440861")
    assert http.posts[-1]["variables"]["input"]["options"]["employeeId"] == "3440861"
    assert http.posts[-1]["variables"]["input"]["locationSlug"].endswith("xa3bpl74")


# ---------------------------------------------------------------------------
# Building the menu
# ---------------------------------------------------------------------------


def built():
    return handler.read_fresha(FreshaHttp(), VENUE)


def test_display_name_capitalises_first_letter_only():
    assert model.display_name("carmen") == "Carmen"
    assert model.display_name("Lori-Dee") == "Lori-Dee"
    assert model.display_name("") == ""


def test_build_menu_staff_and_who_does_what():
    menu = built()
    assert list(menu.staff) == ["jess", "lori-dee", "sav"]
    assert menu.staff["jess"]["role"] == "Salon Manager"
    assert menu.staff["jess"]["booking_link"] == VENUE + "/booking?employeeId=3440861"
    assert menu.staff["jess"]["services"] == ["Senior Nail Services - TLG"]
    assert menu.staff["lori-dee"]["services"] == ["Hair by Lori-dee"]

    by_name = {s["name"]: s for s in menu.services}
    assert by_name["Gel polish"]["staff"] == ["Jess", "Sav"]
    assert by_name["Biab Infill"]["staff"] == ["Jess"]
    assert by_name["Cut and blow dry"]["staff"] == ["Lori-Dee"]
    assert by_name["Gel polish"]["notes"] == "Gel colour on natural nails"
    assert "Featured" not in {s["category"] for s in menu.services}


def test_render_is_stable_and_dated_separately():
    menu = built()
    a = model.render(menu.document("2026-10-19"))
    b = model.render(menu.document("2026-10-20"))
    assert a != b
    assert model.content_of(json.loads(a)) == model.content_of(json.loads(b)) == menu.content()
    assert a.endswith("\n") and "£" in a  # not ascii-escaped


def test_describe_changes_covers_add_remove_change():
    old = built().content()
    new = handler.read_fresha(
        FreshaHttp(
            team=TEAM[:2] + [("9", "Newbie", "Apprentice")],
            full=[FULL[0], {"name": "Senior Nail Services - TLG", "items": [item("Gel polish", "1 hour", "from £36")]}, FULL[2]],
            per_person={**PER_PERSON, "9": []},
        ),
        VENUE,
    ).content()
    lines = model.describe_changes(old, new)
    assert any(l.startswith("Staff added: Newbie") for l in lines)
    assert "Staff removed: Sav" in lines
    assert "Service removed: Senior Nail Services - TLG / Biab Infill" in lines
    assert any("Gel polish price: 'from £34' -> 'from £36'" in l for l in lines)
    assert any("Gel polish staff: ['Jess', 'Sav'] -> ['Jess']" in l for l in lines)
    assert model.describe_changes(old, old) == []


# ---------------------------------------------------------------------------
# GitHub client and the handler
# ---------------------------------------------------------------------------


class FakeGitHubHttp:
    """Enough of the contents, refs and pulls endpoints to exercise the flow."""

    def __init__(self, main_file=None):
        self.files = {("main", model.MENU_FILE): main_file} if main_file else {}
        self.branches = {"main": "sha-main"}
        self.prs = []
        self.log = []

    def request(self, method, url, headers=None, params=None, json=None, timeout=None):
        assert headers["Authorization"] == "Bearer tok"
        path = url.replace("https://api.github.com", "")
        self.log.append((method, path))
        if path.startswith("/repos/o/r/contents/"):
            fpath = path[len("/repos/o/r/contents/"):]
            if method == "GET":
                text = self.files.get((params["ref"], fpath))
                if text is None:
                    return Resp(404, "{}")
                import base64

                return Resp(body={"content": base64.b64encode(text.encode()).decode(), "sha": "blob-" + params["ref"]})
            if method == "PUT":
                import base64

                self.files[(json["branch"], fpath)] = base64.b64decode(json["content"]).decode()
                return Resp(body={"commit": {"sha": "c1"}})
        if path.startswith("/repos/o/r/git/ref/heads/"):
            b = path.rsplit("/", 1)[-1]
            return Resp(body={"object": {"sha": self.branches[b]}}) if b in self.branches else Resp(404, "{}")
        if path == "/repos/o/r/git/refs" and method == "POST":
            self.branches[json["ref"].split("/")[-1]] = json["sha"]
            return Resp(201, body={})
        if path == "/repos/o/r/pulls":
            if method == "GET":
                return Resp(body=[{"html_url": p} for p in self.prs if params["head"].endswith("menu-sync")])
            self.prs.append("https://github.com/o/r/pull/1")
            return Resp(201, body={"html_url": self.prs[-1]})
        raise AssertionError(f"unexpected {method} {path}")


class CombinedHttp(FreshaHttp):
    def __init__(self, gh, **kw):
        super().__init__(**kw)
        self.gh = gh

    def request(self, *a, **kw):
        return self.gh.request(*a, **kw)


class FakeSsm:
    def get_parameter(self, Name, WithDecryption):
        assert WithDecryption and Name == "/tlg/prod/github/pat"
        return {"Parameter": {"Value": "tok"}}


class FakeSns:
    def __init__(self):
        self.published = []

    def publish(self, **kw):
        self.published.append(kw)


@pytest.fixture
def env():
    return {
        "FRESHA_VENUE_URL": VENUE,
        "GITHUB_REPO": "o/r",
        "GITHUB_PAT_PARAMETER": "/tlg/prod/github/pat",
        "OPS_TOPIC_ARN": "arn:aws:sns:eu-west-2:1:ops",
    }


def test_github_client_get_file_and_put_file():
    gh = GitHub(FakeGitHubHttp(main_file="{}"), "tok", "o/r")
    assert gh.get_file(model.MENU_FILE, "main") == ("{}", "blob-main")
    assert gh.get_file("missing.txt", "main") == (None, None)
    gh.ensure_branch("menu-sync", "main")
    assert gh.put_file(model.MENU_FILE, "new", "msg", "menu-sync") == "c1"
    assert gh.get_file(model.MENU_FILE, "menu-sync")[0] == "new"


def test_github_client_raises_on_error():
    class Bad:
        def request(self, *a, **kw):
            return Resp(401, "bad credentials")

    with pytest.raises(GitHubError, match="401"):
        GitHub(Bad(), "tok", "o/r").branch_sha("main")


def test_run_is_quiet_when_repo_matches_fresha(env):
    current = model.render(built().document("2026-10-01"))
    http = CombinedHttp(FakeGitHubHttp(main_file=current))
    sns = FakeSns()
    out = handler.run(http=http, ssm=FakeSsm(), sns=sns, env=env)
    assert out["changed"] is False and "pr_url" not in out
    assert sns.published == []
    assert not any(m == "PUT" for m, _ in http.gh.log)


def test_run_opens_pr_and_alerts_when_fresha_differs(env):
    stale = built().document("2026-10-01")
    stale["services"][0]["price"] = "£1"
    http = CombinedHttp(FakeGitHubHttp(main_file=model.render(stale)))
    sns = FakeSns()
    out = handler.run(http=http, ssm=FakeSsm(), sns=sns, env=env, now=datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert out["changed"] and out["pr_url"] == "https://github.com/o/r/pull/1"
    assert any("price: '£1' ->" in c for c in out["changes"])
    written = json.loads(http.gh.files[("menu-sync", model.MENU_FILE)])
    assert written["menu_snapshot_date"] == "2026-10-19"
    assert len(sns.published) == 1 and "PR opened" in sns.published[0]["Subject"]

    # second run with the PR still open: updates the branch, no second PR
    handler.run(http=http, ssm=FakeSsm(), sns=sns, env=env)
    assert len(http.gh.prs) == 1


def test_run_dry_run_touches_nothing(env):
    http = CombinedHttp(FakeGitHubHttp(main_file=None))
    sns = FakeSns()
    out = handler.run(http=http, ssm=FakeSsm(), sns=sns, env=env, dry_run=True)
    assert out["changed"] and out["dry_run"]
    assert out["changes"] == ["First menu snapshot; no previous file to compare with."]
    assert sns.published == [] and not http.gh.prs
