"""Live availability from Fresha's public booking flow. No login, no cookies.

This is the same server-driven flow a client walks through on fresha.com:

  1. BookingFlow_Initialize_Mutation with an employeeId (menu_sync already
     has the body and hash): returns a cartId and that person's services,
     each with an "Add service" action id.
  2. BookingFlow_ActionButtonPressed_Mutation with the service's action id,
     then again with the screen's continueAction id: returns screenTime,
     which lists about five months of dates flagged bookable and the
     selected day's time slots.
  3. The same mutation with a date's action id switches the selected day.

Everything is a persisted query: operation name plus a sha256 the web app
ships in its bundle. Fresha keeps old hashes valid for a long time (the
initialise hash from 2026-10-19 still works after several daily builds), and
the Fresha watch alarms if any of this changes shape. How the hashes were
found is in knowledge/fresha.md.

The bot only reads. Nothing here books, holds or changes anything.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass, field

from menu_sync import fresha_public

log = logging.getLogger(__name__)

PRESS_OPERATION = "BookingFlow_ActionButtonPressed_Mutation"
PRESS_HASH = "6bd8507eeae4c39450fd5b72d436414939ed7176d943ba4f57dd0627f518f565"
HTTP_TIMEOUT = 12
MAX_PEOPLE = 3  # one person is three or four HTTP calls; keep a lookup under Meta's clock
MAX_DATES = 4


class AvailabilityError(RuntimeError):
    pass


@dataclass
class PersonAvailability:
    person: str
    service: str
    days: dict[str, list[str]] = field(default_factory=dict)  # "2026-10-24" -> ["10:00am", "10:15am"]
    note: str = ""  # why a lookup gave nothing, in words the model can pass on


def check(http, venue_url: str, *, service: str, people: list[tuple[str, str]], dates: list[str]) -> list[PersonAvailability]:
    """Slots for `service` with each (name, employee_id) in `people` on each ISO date.

    Never raises: a person whose lookup failed comes back with a note instead
    of days, so the bot can say "I couldn't check that just now".
    """
    wanted = sorted({d for d in dates if _is_iso_date(d)})[:MAX_DATES]
    out: list[PersonAvailability] = []
    for name, employee_id in people[:MAX_PEOPLE]:
        result = PersonAvailability(person=name, service=service)
        if not wanted:
            result.note = "no valid dates given (use YYYY-MM-DD)"
            out.append(result)
            continue
        try:
            result.days = _lookup(http, venue_url, employee_id, service, wanted)
        except AvailabilityError as exc:
            result.note = str(exc)
        except Exception as exc:  # noqa: BLE001 - one person's failure must not sink the reply
            log.exception("Availability lookup failed for %s", name)
            result.note = f"could not check Fresha just now ({type(exc).__name__})"
        out.append(result)
    return out


def format_for_model(results: list[PersonAvailability]) -> str:
    """Compact text for a tool result. Times are start times a client could pick."""
    lines = []
    for r in results:
        if r.note:
            lines.append(f"{r.service} with {r.person}: {r.note}")
            continue
        for day, slots in r.days.items():
            label = _day_label(day)
            if slots:
                shown = ", ".join(slots[:20]) + (f" and {len(slots) - 20} more" if len(slots) > 20 else "")
                lines.append(f"{r.service} with {r.person}, {label}: {shown}")
            else:
                lines.append(f"{r.service} with {r.person}, {label}: nothing free")
    return "\n".join(lines) or "nothing to report"


# ---------------------------------------------------------------------------
# The flow
# ---------------------------------------------------------------------------


def _lookup(http, venue_url: str, employee_id: str, service: str, dates: list[str]) -> dict[str, list[str]]:
    init = _post(http, fresha_public.INIT_OPERATION, fresha_public.INIT_QUERY_HASH, fresha_public.init_body(venue_url, employee_id)["variables"])
    flow = init.get("bookingFlowInitialize") or {}
    cart_id = flow.get("cartId")
    if not cart_id:
        raise AvailabilityError("Fresha did not start a booking flow")
    item = _find_item(flow, service)
    if item is None:
        raise AvailabilityError(f"Fresha does not list '{service}' for this person")

    screen = _press(http, cart_id, _add_action(item))
    cont = ((screen.get("screenServices") or {}).get("continueAction") or {}).get("id")
    if cont:
        screen = _press(http, cart_id, cont)
    time_screen = screen.get("screenTime")
    if not time_screen or not time_screen.get("dates"):
        raise AvailabilityError("Fresha did not show a time screen")

    listed = {d["date"]["iso"][:10]: d for d in time_screen["dates"]}
    days: dict[str, list[str]] = {}
    for date in dates:
        entry = listed.get(date)
        if entry is None:
            days[date] = []
            continue
        if not entry.get("isAvailableToBeBooked"):
            days[date] = []
            continue
        if entry.get("isSelected"):
            days[date] = _slots(time_screen)
            continue
        action = (entry.get("action") or {}).get("id")
        if not action:
            days[date] = []
            continue
        day_screen = _press(http, cart_id, action).get("screenTime") or {}
        days[date] = _slots(day_screen)
    return days


def _post(http, operation: str, sha256: str, variables: dict) -> dict:
    resp = http.post(
        fresha_public.GRAPHQL_URL,
        json={
            "operationName": operation,
            "variables": variables,
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha256}, "platform": "web"},
        },
        headers={
            "User-Agent": fresha_public.BROWSER_UA,
            "accept-language": "en-GB",
            "x-client-platform": "web",
            "x-graphql-operation-name": operation,
        },
        timeout=HTTP_TIMEOUT,
    )
    if resp.status_code != 200:
        raise AvailabilityError(f"Fresha returned HTTP {resp.status_code}")
    body = resp.json()
    if body.get("errors"):
        message = (body["errors"][0] or {}).get("message", "")
        raise AvailabilityError(f"Fresha refused the request ({message[:80]})")
    return body.get("data") or {}


def _press(http, cart_id: str, action_id: str) -> dict:
    data = _post(http, PRESS_OPERATION, PRESS_HASH, {"id": action_id, "cartId": cart_id, "shouldAutoContinue": True})
    return data.get("bookingFlowActionButtonPressed") or {}


def _find_item(flow: dict, service: str) -> dict | None:
    want = _norm(service)
    for category in (flow.get("screenServices") or {}).get("categories") or []:
        for item in category.get("items") or []:
            if _norm(item.get("name") or "") == want:
                return item
    return None


def _add_action(item: dict) -> str:
    """The action id that adds this service to the cart.

    A single-variant service carries it directly. A service with several
    variants opens a modal instead; its action lists the variants, so build
    the add action for the first one the same way the web app does.
    """
    raw = (item.get("primaryAction") or item.get("secondaryAction") or {}).get("id")
    if not raw:
        raise AvailabilityError("service has no booking action")
    try:
        first, location_id = json.loads(raw)
    except (ValueError, TypeError):
        raise AvailabilityError("unreadable booking action") from None
    if first.get("type") == "onScreenServicesServiceVariantAdd":
        return raw
    variants = first.get("serviceVariants") or []
    if first.get("type") != "onScreenServicesModalServiceOpen" or not variants:
        raise AvailabilityError(f"unexpected booking action {first.get('type')}")
    variant = variants[0]
    add = {
        "type": "onScreenServicesServiceVariantAdd",
        "bookableId": variant.get("id"),
        "catalogId": first.get("catalogId"),
        "membershipId": None,
        "requiresPatchTest": bool(variant.get("requiresPatchTest", False)),
        "orderId": 0,
        "employeeRequired": True,
    }
    return json.dumps([add, location_id], separators=(",", ":"))


def _slots(time_screen: dict) -> list[str]:
    day = time_screen.get("day") or {}
    out = []
    for slot in day.get("timeslots") or []:
        seconds = slot.get("time")
        if isinstance(seconds, int):
            out.append(_clock(seconds))
        elif slot.get("time"):
            out.append(re.sub(r"\s+", "", str(slot["time"])))  # "1:30 pm" with a narrow space
    return out


def _clock(seconds_since_midnight: int) -> str:
    hours, minutes = divmod(seconds_since_midnight // 60, 60)
    suffix = "am" if hours < 12 else "pm"
    hour12 = hours % 12 or 12
    return f"{hour12}:{minutes:02d}{suffix}" if minutes else f"{hour12}{suffix}"


def _day_label(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%a} {d.day} {d:%b}"


def _is_iso_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()
