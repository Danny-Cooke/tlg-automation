"""The `book_appointment` tool: put an agreed appointment into Fresha.

What the model sends: the service's exact name from the salon details, the
team member's first name, the date and the start time, plus the client's
name as they gave it. What it gets back is one line of plain text it can
act on: "Booked: ..." or a reason it could not book and what to do instead.

Guards, in order:

1. Nails, beauty, lashes, aesthetics, and for tattoos only Carmen's free
   consultation (decisions 2026-10-21). Never hair (decision 2026-10-24):
   Sophie's clients are sent to her WhatsApp, Lori-Dee's to her link or a
   hand-over. Anything else is refused and the model is told what to do
   instead. A service Fresha flags as needing a patch test is refused too,
   and handed over (no service carries that flag today).
2. The person must be on the team list with a Fresha id, and must do that
   service according to Fresha's catalog.
3. The client must already be a Fresha client, matched by name: exactly one
   non-blocked record with that name. No match, several matches or a
   blocked record means hand over to Jess; creating clients is parked until
   that mutation is recorded.
4. Fresha's own clash check must be clean for the slot.
5. The same conversation cannot book the same slot twice: a repeat is
   answered with the existing booking, and the Fresha idempotency key is
   derived from the conversation and the slot, so even a retried write
   cannot double book.

Outside live mode nothing is written: the tool does every check and
answers "Would have booked ..." so the draft reads right in shadow mode.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import logging
import re
import time
from dataclasses import dataclass

from . import fresha_session, patch_tests
from .config import SalonConfig
from .fresha import Fresha, FreshaError, Service, SessionRejected
from .state import Conversation

log = logging.getLogger(__name__)

# Fresha category -> the team's area word, for the Telegram line. Spelled as Fresha spells them.
AREAS = {
    "Senior Nail Services - TLG": "nails",
    "Nails by TLG": "nails",
    "Hair by Lori-dee": "hair",
    "Sophie cooper": "hair",
    "Tattoos by Skin deep canvas": "tattoos",
    "Beauty - TLG": "beauty",
    "Lashes by Amber": "beauty",
    "Bernadettes ReFresh aethetics": "aesthetics",
}
# What the bot may book in chat. Hair is out (user, 2026-10-24: "no hair
# bookings automatic at all"): Sophie's clients are sent to her WhatsApp,
# Lori-Dee's to her link or handed over.
BOOKABLE_CATEGORIES = {k: v for k, v in AREAS.items() if v != "hair"}
NOT_IN_CHAT = {
    "hair": ("which the bot does not book in chat. If the client named Sophie, send her WhatsApp line (see Hair in "
             "the rules); otherwise say it is one for Lori and hand over to lori-dee (kind: booking) with the details. "
             "Either way you will not answer again on the thread."),
}
# Categories where only some services may be booked in chat (normalised names).
ONLY_THESE = {"Tattoos by Skin deep canvas": frozenset({"consultation"})}
CATALOG_CACHE_SECONDS = 600
HAND_OVER = "Hand over to Jess (kind: booking) with the service, person, date, time and client name; tell the client the girls will pop it in and send a confirmation."


@dataclass(frozen=True)
class Request:
    service: str
    person: str
    date: str
    time: str
    client_name: str

    @classmethod
    def from_args(cls, args: dict, convo: Conversation) -> "Request":
        return cls(
            service=str(args.get("service") or "").strip(),
            person=str(args.get("person") or "").strip(),
            date=str(args.get("date") or "").strip(),
            time=_normalise_time(str(args.get("time") or "")),
            client_name=str(args.get("client_name") or convo.client_name or "").strip(),
        )


def book(args: dict, *, cfg: SalonConfig, convo: Conversation, dry_run: bool, save=None, notify=None,
         session=None, fresha: Fresha | None = None, now: dt.datetime | None = None, tested=None) -> str:
    """Tool body. Returns text for the model; never raises for a business
    reason, only for a programming error (which brain reports as a failure)."""
    req = Request.from_args(args, convo)
    problem = _validate(req, cfg, now or dt.datetime.now(dt.timezone.utc))
    if problem:
        return problem

    existing = _already_booked(convo, req)
    if existing:
        return f"Already booked earlier in this conversation: {existing}. Do not book again; tell the client it is in."

    member = cfg.staff_named(req.person)
    session = session or fresha_session.get()
    if session is None:
        log.warning("book_appointment: no Fresha session")
        return "Cannot book right now: the salon's Fresha connection is not available. " + HAND_OVER
    f = fresha or Fresha(session)

    try:
        service = _find_service(f, member.employee_id, req.service)
        if service is None:
            return f"Fresha does not list '{req.service}' for {member.name}. Offer someone who does it, or give the Fresha link."
        if service.patch_test and area_of(service.category) == "hair":
            return f"'{service.name}' needs a patch test first, so it is not booked in chat. " + HAND_OVER.replace("Jess", "Lori-Dee")
        if patch_tests.needs_patch_test(service.name, service.patch_test):
            # Lash and brow treatments (plan job 12): the client's patch-test
            # column, or a patch test booked earlier in this thread far enough
            # ahead; otherwise the test is booked first.
            is_tested = (tested or patch_tests.is_tested)(req.client_name)
            if not is_tested and not patch_tests.booked_in_conversation(convo, req.date, req.time):
                return (f"'{service.name}' needs a patch test and {req.client_name} has none on record and none booked far enough "
                        f"ahead in this conversation. Book the service 'lash patch test' first (10 minutes, with Amber, Carmen or Jess, "
                        f"any free time in opening hours) at least {patch_tests.LEAD_HOURS:g} hours before this slot, then book this.")

        client, why = _match_client(f, req.client_name)
        if client is None:
            return why

        clashes = f.conflicts(service.pricing_level_id, member.employee_id, req.date, req.time, service.duration_s)
        if clashes:
            kinds = ", ".join(sorted({str(c.get("conflictType", "conflict")) for c in clashes}))
            return f"That slot is not free any more ({kinds}). Check availability again and offer another time."

        summary = f"{service.name} with {member.name}, {_pretty(req.date, req.time)}, for {client.name}"
        if dry_run:
            log.info("book_appointment dry run: %s", summary)
            return f"Would have booked (not live): {summary}. Tell the client it is booked and Fresha will text them to confirm with card details."

        key = idempotency_key(convo.sender_id, req, service.pricing_level_id)
        booking = f.create(
            customer_id=client.id, pricing_level_id=service.pricing_level_id, price=_price_for_fresha(service.price),
            duration_s=service.duration_s, employee_id=member.employee_id, date=req.date, start=req.time, idempotency_key=key,
        )
    except SessionRejected:
        log.warning("book_appointment: Fresha rejected the session")
        return "Cannot book right now: Fresha rejected the salon's login. " + HAND_OVER
    except FreshaError as e:
        log.warning("book_appointment: %s", e)
        return "Cannot book right now: Fresha refused the request. " + HAND_OVER

    convo.bookings.append({
        "appointment_id": booking.appointment_id, "service": service.name, "person": member.name,
        "date": req.date, "time": req.time, "client_id": client.id, "client_name": client.name,
        "booked_at": int(time.time()),
    })
    if save:
        save(convo)  # the write happened; remember it even if the reply fails
    if notify:
        try:
            notify(convo, summary, booking.appointment_id, area=area_of(service.category))
        except Exception:  # noqa: BLE001 - the team's ping must never undo a booking
            log.exception("Booking notification failed")
    log.info("BOOKED %s for %s: %s", booking.appointment_id, convo.sender_id, summary)
    return (f"Booked: {summary} (Fresha appointment {booking.appointment_id}). "
            "Tell the client it is in and that Fresha will text or email them to confirm with their card details.")


LIVE_STATUSES = frozenset({"UNCONFIRMED", "CONFIRMED", "ARRIVED", "STARTED"})
FEE_HAND_OVER = "Hand over to Jess (kind: cancellation or rebooking) with the appointment details; tell the client the girls will sort it."


def cancel(args: dict, *, cfg: SalonConfig, convo: Conversation, dry_run: bool, save=None, notify=None,
           session=None, fresha: Fresha | None = None, now: dt.datetime | None = None) -> str:
    """The `cancel_appointment` tool. Finds the client's future appointment on
    the given date (and time, if given), and cancels it with Fresha's
    notification on when Fresha says there is nothing to charge. When a fee
    applies the bot does not decide about money: it warns and the client or
    Jess decides. `check_only` stops after the fee check, for a move: the bot
    books the new slot first and cancels the old one after, so a failed
    booking never leaves the client with nothing."""
    date = str(args.get("date") or "").strip()
    time_ = _normalise_time(str(args.get("time") or ""))
    client_name = str(args.get("client_name") or convo.client_name or "").strip()
    check_only = bool(args.get("check_only"))
    now = now or dt.datetime.now(dt.timezone.utc)
    if not client_name:
        return "The client's name is not known. Ask for it, then cancel."
    if date:
        try:
            if dt.date.fromisoformat(date) < now.date():
                return f"{date} is in the past; work the date out from today's date in the context."
        except ValueError:
            return f"Date {date!r} is not YYYY-MM-DD."
    session = session or fresha_session.get()
    if session is None:
        log.warning("cancel_appointment: no Fresha session")
        return "Cannot reach Fresha right now. " + FEE_HAND_OVER
    f = fresha or Fresha(session)

    try:
        client, why = _match_client(f, client_name)
        if client is None:
            return why.replace(HAND_OVER, FEE_HAND_OVER)
        live = [u for u in f.upcoming(client.id) if u.status in LIVE_STATUSES]
        if not live:
            return f"Fresha shows no upcoming appointments for {client.name}. Ask them to check the date, or hand over."
        if not date:
            return "Which one? " + _list(live)
        on_day = [u for u in live if u.date == date and (not time_ or u.time == time_)]
        if not on_day:
            return f"Nothing on {date}{' at ' + time_ if time_ else ''} for {client.name}. Their upcoming appointments: " + _list(live)
        if len(on_day) > 1:
            return "More than one that day; ask which: " + _list(on_day)
        appt = on_day[0]
        summary = f"{appt.service} with {appt.person}, {_pretty(appt.date, appt.time)}, for {client.name}"
        fee = f.cancellation_fee(appt.appointment_id)
        if fee:
            return (f"Not cancelled: {summary} is inside the 24-hour window, so cancelling now carries a £{fee} "
                    "cancellation fee under the salon's policy, and the bot never cancels when a fee applies. "
                    "Warn the client of the fee and ask if they are sure. If they are unsure, or ask not to pay it, "
                    "say you will just check with Jess and hand over with escalation_kind 'cancellation fee'; "
                    "the thread then goes quiet for Jess. If they say cancel anyway, do not call this tool again: "
                    "tell them the fee will apply and that the quickest way is the link in their Fresha "
                    "confirmation, which lets them cancel it themselves, and say you hope to see them again soon.")
        if check_only:
            return (f"Free to cancel: {summary} (Fresha appointment {appt.appointment_id}) is outside the 24-hour window, "
                    "nothing charged. Not cancelled yet: book the new slot first if this is a move, then call again without check_only.")
        if dry_run:
            log.info("cancel_appointment dry run: %s", summary)
            return f"Would have cancelled (not live): {summary}. Tell the client it is cancelled and Fresha will confirm by message."
        f.cancel(appt.appointment_id, notify=True, enforce=False)
    except SessionRejected:
        log.warning("cancel_appointment: Fresha rejected the session")
        return "Cannot reach Fresha right now. " + FEE_HAND_OVER
    except FreshaError as e:
        log.warning("cancel_appointment: %s", e)
        return "Fresha refused the cancellation. " + FEE_HAND_OVER

    for b in convo.bookings:
        if b.get("appointment_id") == appt.appointment_id:
            b["cancelled_at"] = int(time.time())
    convo.bookings.append({
        "appointment_id": appt.appointment_id, "service": appt.service, "person": appt.person, "date": appt.date,
        "time": appt.time, "client_id": client.id, "client_name": client.name, "cancelled_at": int(time.time()),
    }) if not any(b.get("appointment_id") == appt.appointment_id for b in convo.bookings) else None
    if save:
        save(convo)
    if notify:
        try:
            notify(convo, summary, appt.appointment_id, kind="cancelled by the bot", area=area_of_service(cfg, appt.service))
        except Exception:  # noqa: BLE001
            log.exception("Cancellation notification failed")
    log.info("CANCELLED %s for %s: %s", appt.appointment_id, convo.sender_id, summary)
    return f"Cancelled: {summary} (Fresha appointment {appt.appointment_id}). Tell the client it is cancelled and Fresha will send them a message confirming."


def _list(rows) -> str:
    return "; ".join(f"{u.service} with {u.person}, {_pretty(u.date, u.time)}" for u in rows)


# -- pieces --------------------------------------------------------------------


def _validate(req: Request, cfg: SalonConfig, now: dt.datetime) -> str:
    if not req.service or not req.person or not req.date or not req.time:
        return "Need the service, the person, the date (YYYY-MM-DD) and the start time (HH:MM) before booking."
    if not req.client_name:
        return "The client's name is not known. Ask for it, then book."
    try:
        day = dt.date.fromisoformat(req.date)
    except ValueError:
        return f"Date {req.date!r} is not YYYY-MM-DD."
    if day < now.date():
        return f"{req.date} is in the past; work the date out from today's date in the context."
    if not re.fullmatch(r"\d{2}:\d{2}", req.time):
        return f"Time {req.time!r} is not HH:MM (24-hour)."
    listed = _config_service(cfg, req.service)
    if listed is None:
        return f"'{req.service}' is not a service in the salon details. Use the exact name from the list."
    if listed.category not in BOOKABLE_CATEGORIES:
        why = NOT_IN_CHAT.get(AREAS.get(listed.category, ""),
                              "which the bot does not book in chat. Give the client the booking link for it and hand over if a slot was agreed.")
        return f"'{listed.name}' is {area_of(listed.category)}, {why}"
    if not bookable(listed.category, listed.name):
        return (f"'{listed.name}' is a tattoo, and the only tattoo appointment the bot books is the free "
                "consultation with Carmen. Offer that, or give the booking link, and hand over (kind: quote) "
                "if they want a price or a design.")
    member = cfg.staff_named(req.person)
    if member is None or not member.employee_id:
        return f"'{req.person}' is not on the team list. Use a first name from the team."
    if listed.staff and not any(_same_person(member.name, n) for n in listed.staff):
        others = ", ".join(listed.staff)
        return (f"{member.name} is not booked for '{listed.name}' here; it is done by {others}. "
                "Offer one of them, or give the booking link.")
    return ""


def _same_person(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return a == b or a.split()[0] == b.split()[0]


def bookable(category: str, service_name: str) -> bool:
    if category not in BOOKABLE_CATEGORIES:
        return False
    only = ONLY_THESE.get(category)
    return only is None or _norm(service_name) in only


def area_of(category: str) -> str:
    return AREAS.get(category, "general")


def area_of_service(cfg: SalonConfig, service_name: str) -> str:
    """The area word for a service named the way Fresha names it (an upcoming appointment)."""
    listed = _config_service(cfg, service_name)
    return area_of(listed.category) if listed else "general"


def _config_service(cfg: SalonConfig, name: str):
    want = _norm(name)
    for s in cfg.services:
        if _norm(s.name) == want:
            return s
    return None


_catalog_cache: dict[str, object] = {}


def _find_service(f: Fresha, employee_id: str, name: str) -> Service | None:
    """The Fresha pricing level for this service, as this person does it."""
    want = _norm(name)
    for s in _catalog(f):
        if bookable(s.category, s.name) and _norm(s.name) == want and employee_id in s.employee_ids:
            return s
    return None


def _catalog(f: Fresha) -> list[Service]:
    if time.monotonic() < _catalog_cache.get("until", 0.0):
        return _catalog_cache["services"]  # type: ignore[return-value]
    services = f.catalog()
    _catalog_cache.update(until=time.monotonic() + CATALOG_CACHE_SECONDS, services=services)
    return services


def forget_catalog() -> None:
    _catalog_cache.clear()


def _match_client(f: Fresha, name: str):
    """(Client, "") when exactly one usable record carries this name, else (None, why)."""
    rows = f.find_clients(name, limit=20)
    exact = [c for c in rows if _norm(c.name) == _norm(name)]
    if not exact:
        return None, (f"No Fresha client called '{name}'. They may be new or use a different name on Fresha; "
                      "the bot cannot create clients yet. " + HAND_OVER)
    if len(exact) > 1:
        return None, f"More than one Fresha client is called '{name}', so the bot cannot tell which to book. " + HAND_OVER
    client = exact[0]
    if client.blocked:
        return None, f"The Fresha record for '{name}' is blocked. " + HAND_OVER
    return client, ""


def _already_booked(convo: Conversation, req: Request) -> str:
    for b in convo.bookings:
        if b.get("cancelled_at"):
            continue  # a cancelled slot may be booked again
        if b.get("date") == req.date and b.get("time") == req.time and _norm(b.get("service", "")) == _norm(req.service):
            return f"{b.get('service')} with {b.get('person')}, {_pretty(req.date, req.time)} (Fresha appointment {b.get('appointment_id')})"
    return ""


def idempotency_key(sender_id: str, req: Request, pricing_level_id: str) -> str:
    """21 url-safe characters, stable for the same conversation and slot."""
    raw = f"{sender_id}|{req.date}|{req.time}|{pricing_level_id}".encode()
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode()[:21]


def _price_for_fresha(price: str) -> str:
    """Fresha's catalog says "34.00"; the dashboard sends "34". Keep pence only when there are some."""
    return price[:-3] if price.endswith(".00") else price


def _normalise_time(value: str) -> str:
    """"10:00", "10.00", "1000", "10am", "1.30pm" -> "HH:MM". Anything else is returned as given."""
    v = value.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})[:.]?(\d{2})?(am|pm)?", v)
    if not m:
        return value.strip()
    h, mins, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm == "pm" and h < 12:
        h += 12
    if ampm == "am" and h == 12:
        h = 0
    if h > 23 or mins > 59:
        return value.strip()
    return f"{h:02d}:{mins:02d}"


def _pretty(date: str, start: str) -> str:
    d = dt.date.fromisoformat(date)
    h, m = (int(p) for p in start.split(":"))
    suffix = "am" if h < 12 else "pm"
    hour = h % 12 or 12
    clock = f"{hour}.{m:02d}{suffix}" if m else f"{hour}{suffix}"
    return f"{d:%a} {d.day} {d:%b} {clock}"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()
