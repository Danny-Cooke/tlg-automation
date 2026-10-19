"""Read the salon's public Fresha data: team, services, and who does what.

No login. Two sources, both the same ones a client's browser uses:

- The venue page HTML carries the team list (name, Fresha employee id, job
  title) in its embedded Next.js data.
- The booking flow's first GraphQL call, a persisted mutation named
  BookingFlow_Initialize_Mutation, returns the full menu. Called again with an
  employeeId it returns only what that person can be booked for, which is how
  "who does what" is derived.

Verified 2026-10-19 by replaying both from a plain HTTP client. See
knowledge/fresha.md for the ids and knowledge/fresha-internal-api.md for the
partner-side API, which this module does not touch.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

GRAPHQL_URL = "https://www.fresha.com/graphql"
INIT_OPERATION = "BookingFlow_Initialize_Mutation"
# Persisted-query hash the web app sends for the operation above. If Fresha
# ships a new version of the query this stops matching and the call returns a
# PersistedQueryNotFound error, which the Lambda reports.
INIT_QUERY_HASH = "7de1649b0e3ab0fd2b3b9d0c4f09a1863106aaf99b969e9b9edb4c98042a5134"
INIT_CAPABILITIES = [
    "SERVICE_ADDONS",
    "CONFIRMATION",
    "FULL_UPFRONT_PAYMENT",
    "MARKETPLACE_REFRESH",
    "DISCOUNTS_AND_BENEFITS",
    "LOYALTY_POINTS_STORE",
    "TEAM_MEMBER_GENDER",
    "MEMBERSHIPS_SUBSCRIPTIONS",
    "ENHANCED_NOTES",
]
# Fresha repeats a few items under this heading; it is not a real category.
IGNORED_CATEGORIES = {"Featured"}

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HTTP_TIMEOUT = 30


@dataclass(frozen=True)
class TeamMember:
    employee_id: str
    name: str
    job_title: str


@dataclass(frozen=True)
class MenuItem:
    name: str
    duration: str
    price: str
    description: str
    service_id: str | None = None
    pricing_level_id: str | None = None


@dataclass
class MenuCategory:
    name: str
    items: list[MenuItem] = field(default_factory=list)


class FreshaError(RuntimeError):
    pass


def location_slug(venue_url: str) -> str:
    """'.../a/the-looking-glass-...-xa3bpl74' -> 'the-looking-glass-...-xa3bpl74'."""
    path = venue_url.split("?", 1)[0].rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    if not slug:
        raise ValueError(f"cannot read a location slug from {venue_url!r}")
    return slug


_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def fetch_team(http, venue_url: str) -> list[TeamMember]:
    resp = http.get(venue_url, headers={"User-Agent": BROWSER_UA}, timeout=HTTP_TIMEOUT)
    if resp.status_code != 200:
        raise FreshaError(f"venue page returned HTTP {resp.status_code}")
    return parse_team(resp.text)


def venue_data(html: str) -> dict:
    """The Next.js data block embedded in the venue page."""
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise FreshaError("venue page has no __NEXT_DATA__ block; Fresha changed the page")
    try:
        return json.loads(m.group(1))
    except ValueError as exc:
        raise FreshaError(f"venue page __NEXT_DATA__ is not JSON: {exc}") from exc


def parse_team(html: str) -> list[TeamMember]:
    return team_from_data(venue_data(html))


def team_from_data(data: dict) -> list[TeamMember]:
    try:
        edges = data["props"]["pageProps"]["data"]["location"]["employeeProfiles"]["edges"]
    except (KeyError, TypeError) as exc:
        raise FreshaError(f"team list not where expected in venue data: {exc}") from exc
    team = []
    for edge in edges:
        node = edge.get("node") or {}
        if not node.get("employeeId"):
            continue
        team.append(
            TeamMember(
                employee_id=str(node["employeeId"]),
                name=_clean(node.get("displayName") or ""),
                job_title=_clean(node.get("jobTitle") or ""),
            )
        )
    if not team:
        raise FreshaError("venue page lists no team members")
    return team


def fetch_menu(http, venue_url: str, employee_id: str | None = None) -> list[MenuCategory]:
    """Full menu, or only what one person can be booked for."""
    body = init_body(venue_url, employee_id)
    resp = http.post(
        GRAPHQL_URL,
        json=body,
        headers={
            "User-Agent": BROWSER_UA,
            "accept-language": "en-GB",
            "x-client-platform": "web",
            "x-graphql-operation-name": INIT_OPERATION,
        },
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code != 200:
        raise FreshaError(f"booking flow returned HTTP {resp.status_code}: {resp.text[:200]}")
    return parse_menu(resp.json())


def init_body(venue_url: str, employee_id: str | None) -> dict:
    """Request body for the booking-flow initialise mutation, optionally filtered to one person."""
    return {
        "operationName": INIT_OPERATION,
        "variables": {
            "input": {
                "locationSlug": location_slug(venue_url),
                "configToken": None,
                "referer": "",
                "options": {
                    "isGroupBooking": False,
                    "isRebook": False,
                    "employeeId": employee_id,
                    "shouldShowAllEmployees": False,
                    "isFromLinkBuilder": False,
                    "clientChannelType": "DIRECT",
                    "cartId": None,
                    "landingPageUrl": venue_url,
                },
                "shouldAutoContinue": False,
                "capabilities": INIT_CAPABILITIES,
            }
        },
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": INIT_QUERY_HASH}, "platform": "web"},
    }


def parse_menu(payload: dict) -> list[MenuCategory]:
    if payload.get("errors"):
        raise FreshaError(f"booking flow returned errors: {json.dumps(payload['errors'])[:300]}")
    try:
        categories = payload["data"]["bookingFlowInitialize"]["screenServices"]["categories"]
    except (KeyError, TypeError) as exc:
        raise FreshaError(f"menu not where expected in booking flow response: {exc}") from exc
    out: list[MenuCategory] = []
    for cat in categories:
        name = _clean(cat.get("name") or "")
        if name in IGNORED_CATEGORIES:
            continue
        items = [_parse_item(i) for i in cat.get("items", [])]
        out.append(MenuCategory(name=name, items=[i for i in items if i.name]))
    # Empty is legitimate for a person with nothing bookable; the caller
    # decides whether an empty full menu is an error.
    return out


def _parse_item(raw: dict) -> MenuItem:
    service_id = pricing_level_id = None
    action = (raw.get("secondaryAction") or {}).get("id")
    if action:
        try:
            first = json.loads(action)[0]
            service_id = _strip_prefix(first.get("catalogId"), "s:")
            pricing_level_id = _strip_prefix(first.get("bookableId"), "sv:")
        except (ValueError, IndexError, TypeError, AttributeError):
            pass
    return MenuItem(
        name=_clean(raw.get("name") or ""),
        duration=_clean(raw.get("caption") or ""),
        price=_clean((raw.get("price") or {}).get("formatted") or ""),
        description=_clean(raw.get("description") or ""),
        service_id=service_id,
        pricing_level_id=pricing_level_id,
    )


def _strip_prefix(value, prefix: str) -> str | None:
    if isinstance(value, str) and value.startswith(prefix):
        return value[len(prefix):]
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
