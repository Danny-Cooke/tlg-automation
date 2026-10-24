"""Talk to Fresha's partner dashboard API with the owner's stored session.

Everything here replays calls the dashboard itself makes (recorded
2026-10-20, texts in `fresha_ops.py`, notes in
`knowledge/fresha-internal-api.md`). Nothing is invented: variables are built
to the exact shape the web app sends, and the only writes are the two the
dashboard does for "save appointment" and "cancel, no charge".

Usage:

    session = fresha_session.get()          # from SSM, None if there is none
    fresha = Fresha(session)
    clients = fresha.find_clients("danny")
    starts = fresha.available_starts(level_id, staff_id, "2026-10-24", 3600)
    booking = fresha.create(customer_id=..., pricing_level_id=..., price="34",
                            duration_s=3600, employee_id=..., date="2026-10-24", start="11:00")
    fresha.cancel(booking.appointment_id)

A 401 or 403 raises SessionRejected and drops the cached session so the next
call re-reads the parameter. Any other failure raises FreshaError with
Fresha's own message. The cookie is never logged.
"""
from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass, field

from bot import fresha_session
from bot.fresha_ops import OPS

log = logging.getLogger(__name__)

GRAPHQL = "https://partners-api-gateway.fresha.com/graphql"
CUSTOMERS = "https://customers-api.fresha.com/v2/customer-search"
CUSTOMER = "https://customers-api.fresha.com/v2/customers/{id}"  # the full record, marketing ticks included
CREATE_CLIENT = "https://customers-api.fresha.com/v2/customers"  # POST: the dashboard's "Add a new client" (recorded 2026-10-24)
REFERRAL_SOURCES = "https://customers-api.fresha.com/referral-sources"  # the salon's list; "Walk-In" is the default
STATISTICS = "https://partners-api.fresha.com/customers/{id}/statistics"  # Fresha's counters per client
FORMS = "https://consultation-forms-api.fresha.com/requests"  # consultation forms requested of a client
OWNER_ID = "1453889"       # __pid, the owner's Fresha user
LOCATION_ID = "1530970"    # The Looking Glass Beauty, Shrewsbury
TIMEZONE = "Europe/London"
HEADERS = {"accept": "application/json", "origin": "https://partners.fresha.com", "referer": "https://partners.fresha.com/"}
NO_FEE = "NO_FEE"


class FreshaError(Exception):
    """Fresha said no, or answered in a shape we do not understand."""


class SessionRejected(FreshaError):
    """HTTP 401/403: the stored session is dead; run scripts/fresha_session.py."""


@dataclass(frozen=True)
class Client:
    id: str
    name: str
    phone: str = ""
    email: str = ""
    blocked: bool = False


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    category: str
    pricing_level_id: str
    price: str                 # list price as Fresha sends it, e.g. "34.00"
    price_type: str            # FIXED or STARTS_AT
    duration_s: int
    employee_ids: tuple[str, ...] = ()
    patch_test: bool = False
    level_name: str = ""


@dataclass(frozen=True)
class Booking:
    appointment_id: str
    booking_id: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Upcoming:
    """One future appointment of a client, as the dashboard's client card lists them."""
    appointment_id: str
    status: str                # UNCONFIRMED, CONFIRMED, CANCELLED, ...
    date: str                  # YYYY-MM-DD, salon wall clock
    time: str                  # HH:MM
    service: str
    person: str                # employee first name
    price: str = ""
    customer_id: str = ""


@dataclass(frozen=True)
class Quote:
    strategy: str              # NO_PROTECTION, CARD_CONFIRMATION, ...
    cancellation_fee: str
    deposit: str
    raw: dict = field(default_factory=dict, compare=False)


def phone_for_fresha(mobile_e164: str) -> str:
    """"+447700900123" the way the dashboard writes it: "+44 7700 900123"."""
    d = _digits(mobile_e164)
    if d.startswith("44") and len(d) == 12:
        return f"+44 {d[2:6]} {d[6:]}"
    return "+" + d if d else ""


def _digits(text: str | None) -> str:
    return "".join(ch for ch in (text or "") if ch.isdigit())


def nanoid() -> str:
    """A 21-character id like the dashboard's orderItemRef / idempotencyKey."""
    return secrets.token_urlsafe(16)[:21]


def _hms(start: str) -> tuple[int, int, int]:
    parts = [int(p) for p in start.split(":")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


class Fresha:
    def __init__(self, session: fresha_session.Session, http=None, *, owner_id: str = OWNER_ID,
                 location_id: str = LOCATION_ID, client_version: str = fresha_session.CLIENT_VERSION):
        self.session = session
        self.owner_id = owner_id
        self.location_id = location_id
        self.client_version = client_version
        self._http = http

    @property
    def http(self):
        if self._http is None:
            import requests

            self._http = requests.Session()
        return self._http

    # -- transport -----------------------------------------------------------

    def _ids(self) -> dict[str, str]:
        return {"_client_platform": "web", "_client_version": self.client_version, "__pid": self.owner_id}

    def _check(self, resp) -> None:
        if resp.status_code in (401, 403):
            fresha_session.forget()
            raise SessionRejected(f"Fresha rejected the session: HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise FreshaError(f"Fresha HTTP {resp.status_code}: {resp.text[:200]}")

    def graphql(self, name: str, variables: dict, *, tolerate: str = "") -> dict:
        """Run one recorded operation; returns the `data` object.
        `tolerate` names a GraphQL error code to swallow (returns {} then)."""
        kind, op, text = OPS[name]
        params = {"_" + kind: op, **self._ids()}
        resp = self.http.post(
            GRAPHQL, params=params,
            data={"operationName": op, "query": text, "variables": json.dumps(variables, separators=(",", ":"))},
            cookies=self.session.cookies(), headers=HEADERS, timeout=20,
        )
        self._check(resp)
        try:
            body = resp.json()
        except ValueError as e:
            raise FreshaError(f"{op}: Fresha did not answer with JSON") from e
        errors = body.get("errors") or []
        if errors:
            codes = {str((e.get("extensions") or {}).get("code", "")) for e in errors}
            if tolerate and codes <= {tolerate}:
                return {}
            msg = "; ".join(str(e.get("message", "")) for e in errors)[:300]
            raise FreshaError(f"{op}: {msg}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise FreshaError(f"{op}: no data in reply")
        return data

    # -- reads -----------------------------------------------------------------

    def find_clients(self, query: str, *, limit: int = 10) -> list[Client]:
        """Search the client list the way the dashboard's search box does."""
        resp = self.http.get(
            CUSTOMERS, params={"query": query, "limit": limit, "offset": 0, "include-customers-count": "true", **self._ids()},
            cookies=self.session.cookies(), headers={**HEADERS, "accept": "application/vnd.api+json"}, timeout=20,
        )
        self._check(resp)
        out = []
        for row in (resp.json().get("data") or []):
            a = row.get("attributes") or {}
            out.append(Client(
                id=str(row.get("id", "")), name=(a.get("name") or "").strip(),
                phone=a.get("contact-number") or "", email=a.get("email") or "",
                blocked=bool(a.get("blocked")),
            ))
        return out

    def client_page(self, *, offset: int = 0, limit: int = 50) -> tuple[list[dict], int | None]:
        """One page of the whole client list (empty query), raw JSON:API rows,
        and the total Fresha reports (None if it did not say). For the mirror
        in clients/sync.py."""
        resp = self.http.get(
            CUSTOMERS, params={"query": "", "limit": limit, "offset": offset, "include-customers-count": "true", **self._ids()},
            cookies=self.session.cookies(), headers={**HEADERS, "accept": "application/vnd.api+json"}, timeout=20,
        )
        self._check(resp)
        body = resp.json()
        count = (body.get("meta") or {}).get("results-count")
        return list(body.get("data") or []), (int(count) if isinstance(count, int) else None)

    def client_detail(self, client_id: str) -> dict:
        """The client's full record as the profile page loads it: name, contact
        details, blocked, and the marketing ticks (SMS, email, WhatsApp)."""
        resp = self.http.get(
            CUSTOMER.format(id=client_id), params={"include": "referred_by_customer", **self._ids()},
            cookies=self.session.cookies(), headers={**HEADERS, "accept": "application/vnd.api+json"}, timeout=20,
        )
        self._check(resp)
        return resp.json()

    def find_client_by_phone(self, mobile_e164: str) -> list[Client]:
        """Clients whose number is this one, whatever name they are under. The
        dashboard's search box takes a number; the match here is on digits."""
        want = _digits(mobile_e164)
        if len(want) < 10:
            return []
        rows = self.find_clients(phone_for_fresha(mobile_e164), limit=20) or self.find_clients(want[-10:], limit=20)
        return [c for c in rows if _digits(c.phone).endswith(want[-10:])]

    def referral_source_id(self) -> str:
        """The salon's default referral source ("Walk-In"), as the dashboard
        attaches to a new client. Empty if Fresha lists none."""
        if getattr(self, "_referral_source_id", None) is not None:
            return self._referral_source_id
        resp = self.http.get(REFERRAL_SOURCES, params=self._ids(), cookies=self.session.cookies(),
                             headers={**HEADERS, "accept": "application/vnd.api+json"}, timeout=20)
        self._check(resp)
        rows = [r for r in (resp.json().get("data") or []) if not (r.get("attributes") or {}).get("is-deleted")]
        default = [r for r in rows if (r.get("attributes") or {}).get("is-default")] or rows
        self._referral_source_id = str(default[0].get("id", "")) if default else ""
        return self._referral_source_id

    def create_client(self, *, first_name: str, last_name: str, mobile_e164: str, email: str) -> Client:
        """Add a client exactly as the dashboard's "Add a new client" form does
        (recorded 2026-10-24): the four fields the salon fills in, the form's
        own defaults for the rest (notifications and marketing on, the default
        referral source, no birthday, no address), creation source client_list."""
        attributes = {
            "first-name": first_name.strip(), "last-name": last_name.strip(), "gender": "", "pronoun": None,
            "email": email.strip().lower(), "contact-number": phone_for_fresha(mobile_e164),
            "additional-contact-number": None, "additional-email": "",
            "birthday-day": None, "birthday-month": None, "birthday-year": None,
            "enable-email-notifications": True, "enable-sms-notifications": True, "enable-whatsapp-notifications": True,
            "accepts-marketing-notifications": True, "accepts-sms-marketing-notifications": True,
            "accepts-whatsapp-marketing-notifications": True, "marketplace-appointment-confirmation-enabled": True,
            "is-changed": True, "occupation": None, "nationality": None, "avatar-filename": "",
            "referrer-reward-template-ids": None, "referee-reward-template-id": None, "tag-ids": [], "tag-names": [],
            "selected-language-locale-code": "", "creation-source": "client_list",
        }
        source = self.referral_source_id()
        relationships = {
            "referral-source": {"data": {"attributes": {"id": source}, "type": "referral-source"}} if source else {"data": None},
            "referred-by-customer": {"data": None},
            "addresses": {"data": []},
            "emergency-contacts": {"data": [
                {"type": "emergency-contact", "attributes": {"type": kind, "full-name": "", "relationship": "", "contact-number": None,
                                                             "email": "", "destroy": True}}
                for kind in ("primary", "secondary")
            ]},
        }
        resp = self.http.post(
            CREATE_CLIENT, json={"data": {"type": "customer-create-requests", "attributes": attributes, "relationships": relationships}},
            cookies=self.session.cookies(), headers={**HEADERS, "accept": "application/vnd.api+json", "content-type": "application/vnd.api+json"},
            timeout=20,
        )
        self._check(resp)
        data = (resp.json() or {}).get("data") or {}
        if not data.get("id"):
            raise FreshaError("create client: Fresha answered without an id")
        a = data.get("attributes") or {}
        return Client(id=str(data["id"]), name=(a.get("name") or f"{first_name} {last_name}").strip(),
                      phone=a.get("contact-number") or phone_for_fresha(mobile_e164), email=a.get("email") or email)

    def client_record(self, client_id: str) -> dict:
        """The rest of the profile page in one GraphQL call (`clientRecord` in
        fresha_ops.py): patch tests, allergies, tags, badges, staff alert,
        notes, files, upcoming and past appointments. Raw `data`."""
        return self.graphql("clientRecord", {"customerId": str(client_id)})

    def client_statistics(self, client_id: str) -> dict:
        """Fresha's own counters for the client: bookings, no-shows, sales. Raw JSON:API."""
        resp = self.http.get(
            STATISTICS.format(id=client_id), params=self._ids(),
            cookies=self.session.cookies(), headers={**HEADERS, "accept": "application/vnd.api+json"}, timeout=20,
        )
        self._check(resp)
        return resp.json()

    def client_forms(self, client_id: str, *, limit: int = 50) -> dict:
        """Consultation forms requested of the client, newest first. Raw JSON:API."""
        resp = self.http.get(
            FORMS, params={"customer-id": str(client_id), "limit": limit, "offset": 0,
                           "sort-by": "requested_at", "sort-order": "desc", **self._ids()},
            cookies=self.session.cookies(), headers={**HEADERS, "accept": "application/vnd.api+json"}, timeout=20,
        )
        self._check(resp)
        return resp.json()

    def catalog(self, *, employee_id: str = "", customer_id: str | None = None) -> list[Service]:
        """Every bookable service with its pricing level, price and duration.
        Pages through Fresha's catalog as the dashboard's service picker does."""
        services: list[Service] = []
        after = None
        while True:
            variables = {
                "after": after,
                "autoSelectedPriceModifiers": [
                    {"level": "ITEM", "type": "BUNDLE"}, {"level": "ITEM", "type": "PAID_PLAN_INSTANCE"},
                    {"level": "ITEM", "type": "REWARD"}, {"level": "ITEM", "type": "MEMBERSHIP"},
                ],
                "currentBasket": {"items": [], "paidPlanReservationTokens": [], "priceModifiers": []},
                "customerId": customer_id,
                "filters": {"employee": {"employeePerformsService": False, "id": employee_id}} if employee_id else None,
                "first": 100,
                "locationId": self.location_id,
            }
            cat = self.graphql("pricingCatalogList", variables).get("catalog") or {}
            names = {c.get("id"): c.get("name", "") for c in cat.get("categories") or []}
            for edge in cat.get("edges") or []:
                node = edge.get("node") or {}
                if node.get("__typename") != "Pricing_CatalogService":
                    continue
                for level in node.get("servicePricingLevels") or []:
                    price = level.get("price") or {}
                    services.append(Service(
                        id=str(node.get("id", "")), name=(node.get("name") or "").strip(),
                        category=names.get(node.get("categoryId"), ""),
                        pricing_level_id=str(level.get("id", "")),
                        price=str(price.get("listPrice", "")), price_type=str(price.get("priceType", "")),
                        duration_s=int(level.get("maxDurationInSeconds") or level.get("minDurationInSeconds") or 0),
                        employee_ids=tuple(str(e) for e in node.get("employeeIds") or ()),
                        patch_test=bool(node.get("isPatchTestRequired")), level_name=level.get("name") or "",
                    ))
            page = cat.get("pageInfo") or {}
            if not page.get("hasNextPage") or not page.get("endCursor"):
                return services
            after = page["endCursor"]

    def available_starts(self, pricing_level_id: str, employee_id: str, date: str, duration_s: int) -> list[str]:
        """Start times ("HH:MM:SS") Fresha offers for this service with this
        person on this date, ignoring online-booking lead-time rules. Empty
        when the day is closed or full."""
        variables = {"input": {
            "attendees": [{"attendeeId": "1", "offerItems": [{
                "itemType": "SERVICE_PRICING_LEVEL", "offerItemId": "1", "position": 1,
                "servicePricingLevel": {
                    "forceMaxDuration": False, "ignoreAssignments": True,
                    "requestedEmployeeId": employee_id, "servicePricingLevelId": pricing_level_id,
                    "timeSegmentsOverride": [{"duration": duration_s, "isMainServicingTime": True, "type": "SERVICING"}],
                }}]}],
            "dateRange": {"endDate": date, "startDate": date},
            "locationId": self.location_id,
            "timeslotSettingsMode": "UNRESTRICTED",
        }, "withAttendees": False}
        data = self.graphql("availableTimeSlots", variables)
        days = (data.get("availableTimeSlots") or {}).get("dailyAvailableTimeSlots") or []
        starts: list[str] = []
        for day in days:
            if day.get("date") != date or day.get("closed"):
                continue
            starts.extend(str(o.get("startTime")) for o in day.get("possibleOffers") or [] if o.get("startTime"))
        return starts

    def conflicts(self, pricing_level_id: str, employee_id: str, date: str, start: str, duration_s: int) -> list[dict]:
        """Fresha's own clash check for one slot; [] means clean."""
        h, m, s = _hms(start)
        variables = {"input": {
            "date": date, "excludedAppointmentIds": [], "locationId": self.location_id,
            "scheduledItems": [{
                "employeeId": employee_id, "id": nanoid(), "servicePricingLevelId": pricing_level_id,
                "startTime": f"{h:02d}:{m:02d}:{s:02d}",
                "timeSegments": [{"duration": duration_s, "isMainServicingTime": True, "type": "SERVICING"}],
            }],
        }}
        data = self.graphql("SchedulingConflicts", variables)
        items = (data.get("schedulingConflicts") or {}).get("scheduledItemsConflicts") or []
        return [c for item in items for c in (item.get("conflicts") or [])]

    def quote(self, customer_id: str | None, pricing_level_id: str, price: str) -> Quote:
        """What payment policy Fresha will apply to this booking (read-only)."""
        variables = {"input": {"customerId": customer_id, "items": [{
            "id": pricing_level_id, "quantity": 1, "salePrice": price,
            "serviceAddOnCorrelationId": f"0-{pricing_level_id}", "totalGross": price, "type": "SERVICE_PRICING_LEVEL",
        }]}}
        fees = self.graphql("appointment_calculateAppointmentProtectionFees", variables).get("calculateAppointmentProtectionFees") or {}
        return Quote(strategy=str(fees.get("strategy", "")), cancellation_fee=str(fees.get("cancellationFeeAmount", "")),
                     deposit=str(fees.get("depositAmount", "")), raw=fees)

    def view(self, appointment_id: str) -> dict:
        return self.graphql("viewAppointment", {"id": appointment_id}).get("appointment") or {}

    def upcoming(self, customer_id: str, *, first: int = 100) -> list[Upcoming]:
        """A client's future appointments, soonest first (the client card's query
        with its page size made a variable). Cancelled ones are in the page too,
        so the page is large: with 10, a client with ten cancelled future
        appointments looked like they had none (seen live 2026-10-21)."""
        data = self.graphql("CustomerOverviewUpcomingAppointmentQuery", {"customerId": customer_id, "first": first})
        out: list[Upcoming] = []
        for edge in (data.get("appointments") or {}).get("edges") or []:
            node = edge.get("node") or {}
            bookings = node.get("bookings") or []
            first_booking = bookings[0] if bookings else {}
            wall = str(node.get("startWallClock") or "")  # "2026-10-29T10:00:00[Europe/London]"
            emp = first_booking.get("employee") or {}
            out.append(Upcoming(
                appointment_id=str(node.get("id", "")), status=str(node.get("status", "")),
                date=wall[:10], time=wall[11:16],
                service=" + ".join((b.get("service") or {}).get("name", "").strip() for b in bookings) or "appointment",
                person=str(emp.get("firstName") or "").strip().title(),
                price=str(first_booking.get("price") or ""), customer_id=str(node.get("customerId", "")),
            ))
        return out

    def cancellation_fee(self, appointment_id: str) -> str:
        """What Fresha would charge to cancel now: "" when nothing (its NO_FEE
        answer), else the amount as a string. Same call the dashboard makes
        when the cancel dialog opens; it charges nothing by itself."""
        data = self.graphql("initializeAppointmentProtectionEnforcement",
                            {"input": {"action": "CANCELLATION", "appointmentId": appointment_id}}, tolerate=NO_FEE)
        enforcement = (data.get("initializeAppointmentProtectionEnforcement") or {}).get("appointmentProtectionEnforcement") or {}
        amount = str(enforcement.get("protectionAmount") or "")
        try:
            return amount if float(amount) > 0 else ""
        except ValueError:
            return ""

    # -- writes ----------------------------------------------------------------

    def create(self, *, customer_id: str, pricing_level_id: str, price: str, duration_s: int, employee_id: str,
               date: str, start: str, idempotency_key: str = "", requested: bool = False) -> Booking:
        """Save one appointment exactly as the dashboard's "Save" does, with the
        salon's default payment policy, so Fresha sends its usual confirmation
        and card request. `price` is the catalog price as a string, "34" or
        "34.00". Pass the same `idempotency_key` to retry safely."""
        h, m, s = _hms(start)
        variables = {"input": {
            "appointment": {
                "bookings": [{
                    "bookedServiceAddOns": [],
                    "employees": [{"id": employee_id, "requested": requested}],
                    "orderItemRef": nanoid(),
                    "resources": [],
                    "servicePricingLevel": {"catalogPrice": price, "id": pricing_level_id},
                    "startDateAndTime": {
                        "date": date, "timeOfDay": {"hours": h, "minutes": m, "seconds": s},
                        "timezone": TIMEZONE, "wallClockTime": f"{h:02d}:{m:02d}:{s:02d}",
                    },
                    "timeSegments": [{"durationInSeconds": duration_s, "isMainServicingTime": True, "sortingId": 0, "type": "SERVICING"}],
                }],
                "customerId": customer_id,
                "locationId": self.location_id,
                "priceModifiers": [],
            },
            "appointmentProtection": {"appointmentProtectionAction": "DEFAULT_SETTINGS"},
            "metadata": {"idempotencyKey": idempotency_key or nanoid(), "source": "new"},
        }}
        data = self.graphql("createAppointmentByEmployee", variables)
        payload = data.get("AppointmentsManager_createAppointmentByEmployee") or {}
        appt = (payload.get("appointment") or {}).get("id")
        if not appt:
            raise FreshaError("create: Fresha returned no appointment id")
        warnings = tuple(str(w.get("message", "")) for w in payload.get("warnings") or [])
        log.info("Fresha booked appointment %s (%s %s, level %s, staff %s)", appt, date, start, pricing_level_id, employee_id)
        return Booking(appointment_id=str(appt), booking_id=str(payload.get("primaryBookingId", "")), warnings=warnings)

    def cancel(self, appointment_id: str, *, notify: bool = False, enforce: bool = True) -> str:
        """Cancel without charging, the dashboard's two-step way. Never takes a
        fee: the salon decides fees by hand. `enforce=False` skips the first
        step when `cancellation_fee` was just called for this appointment."""
        if enforce:
            self.graphql("initializeAppointmentProtectionEnforcement",
                         {"input": {"action": "CANCELLATION", "appointmentId": appointment_id}}, tolerate=NO_FEE)
        data = self.graphql("cancelAppointmentWithNoCharge", {"input": {
            "appointmentId": appointment_id,
            "cancellationOptions": {"cancelFutureAppointments": False},
            "sendNotification": notify,
        }})
        done = (data.get("cancelAppointmentWithNoCharge") or {}).get("appointmentId")
        if str(done) != str(appointment_id):
            raise FreshaError(f"cancel: Fresha answered for {done!r}, not {appointment_id}")
        log.info("Fresha cancelled appointment %s (notify=%s)", appointment_id, notify)
        return str(done)
