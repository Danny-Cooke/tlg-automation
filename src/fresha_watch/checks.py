"""The checks the Fresha watch runs against Fresha's public pages.

Each check takes a requests-style HTTP session and returns a CheckResult with
two separate findings:

- ``ok``: the page or call still works and still yields what the menu sync
  needs (a team, a menu).
- ``paths``: the shape of the part of the response the sync depends on (see
  shape.py). The handler compares it with the previous run and alerts when
  it changes, even if everything still works.

Nothing here touches AWS, so every check is unit-testable with a fake session.
The venue page and booking flow are read exactly the way src/menu_sync does.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from menu_sync import fresha_public
from menu_sync.fresha_public import BROWSER_UA, HTTP_TIMEOUT, FreshaError

from . import shape


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    paths: list[str] | None = None
    info: dict = field(default_factory=dict)


def check_venue_page(http, venue_url: str) -> CheckResult:
    """The venue page loads, carries its Next.js data, and lists the team.

    Shape watched: the top-level keys of the location record (one level, so a
    renamed or vanished section is seen) and the whole employeeProfiles
    subtree the team list is read from.
    """
    name = "venue_page"
    try:
        resp = http.get(venue_url, headers={"User-Agent": BROWSER_UA}, timeout=HTTP_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - any transport failure is the finding
        return CheckResult(name, False, f"request failed: {exc}")
    if resp.status_code != 200:
        return CheckResult(name, False, f"venue page returned HTTP {resp.status_code}")
    try:
        data = fresha_public.venue_data(resp.text)
        location = data["props"]["pageProps"]["data"]["location"]
        team = fresha_public.team_from_data(data)
    except (FreshaError, KeyError, TypeError) as exc:
        return CheckResult(name, False, f"venue page changed: {exc}")
    leaf_paths = shape.paths(location, prefix="location", max_depth=1) + shape.paths(
        location.get("employeeProfiles"), prefix="location.employeeProfiles", max_depth=5
    )
    return CheckResult(name, True, f"{len(team)} team members listed", paths=leaf_paths, info={"team": len(team)})


def check_booking_flow(http, venue_url: str) -> CheckResult:
    """The persisted booking-flow query still exists and returns the menu.

    Shape watched: the top of the bookingFlowInitialize payload (two levels)
    and the categories/items subtree the menu is read from.
    """
    name = "booking_flow"
    payload, failure = _init(http, venue_url, None, name)
    if failure:
        return failure
    try:
        categories = fresha_public.parse_menu(payload)
        flow = payload["data"]["bookingFlowInitialize"]
        raw_categories = flow["screenServices"]["categories"]
    except (FreshaError, KeyError, TypeError) as exc:
        return CheckResult(name, False, f"booking flow changed: {exc}")
    services = sum(len(c.items) for c in categories)
    if not categories or not services:
        return CheckResult(name, False, "booking flow returned an empty menu")
    leaf_paths = shape.paths(flow, prefix="bookingFlowInitialize", max_depth=2) + shape.paths(
        raw_categories, prefix="bookingFlowInitialize.screenServices.categories", max_depth=6
    )
    return CheckResult(
        name,
        True,
        f"{len(categories)} categories, {services} services",
        paths=leaf_paths,
        info={"categories": len(categories), "services": services},
    )


def check_booking_flow_per_person(http, venue_url: str, employee_id: str, person: str) -> CheckResult:
    """Filtering the booking flow by employee still works; who-does-what depends on it."""
    name = "booking_flow_per_person"
    payload, failure = _init(http, venue_url, employee_id, name)
    if failure:
        return failure
    try:
        categories = fresha_public.parse_menu(payload)
    except FreshaError as exc:
        return CheckResult(name, False, f"per-person booking flow changed: {exc}")
    services = sum(len(c.items) for c in categories)
    return CheckResult(name, True, f"{person}: {services} bookable services", info={"services": services})


def check_general_link(http, url: str, salon_name: str) -> CheckResult:
    """The general booking link the bot hands out still lands on the salon."""
    name = "general_link"
    try:
        resp = http.get(url, headers={"User-Agent": BROWSER_UA}, timeout=HTTP_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name, False, f"request failed: {exc}")
    if resp.status_code != 200:
        return CheckResult(name, False, f"general booking link returned HTTP {resp.status_code}")
    if salon_name.lower() not in resp.text.lower():
        return CheckResult(name, False, f"general booking link no longer mentions {salon_name!r}")
    return CheckResult(name, True, "loads and names the salon")


def _init(http, venue_url: str, employee_id: str | None, name: str):
    """POST the booking-flow initialise mutation. Returns (payload, None) or (None, failure)."""
    body = fresha_public.init_body(venue_url, employee_id)
    try:
        resp = http.post(
            fresha_public.GRAPHQL_URL,
            json=body,
            headers={
                "User-Agent": BROWSER_UA,
                "accept-language": "en-GB",
                "x-client-platform": "web",
                "x-graphql-operation-name": fresha_public.INIT_OPERATION,
            },
            timeout=HTTP_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        return None, CheckResult(name, False, f"request failed: {exc}")
    if resp.status_code != 200:
        return None, CheckResult(name, False, f"booking flow returned HTTP {resp.status_code}: {resp.text[:120]}")
    try:
        payload = resp.json()
    except ValueError:
        return None, CheckResult(name, False, f"booking flow returned non-JSON: {resp.text[:120]!r}")
    if not isinstance(payload, dict):
        return None, CheckResult(name, False, "booking flow returned something other than an object")
    return payload, None
