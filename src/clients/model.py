"""One client as the salon's systems know them.

Fresha is the source of truth for who the client is, what they ticked, and
everything the profile page shows (patch tests, allergies, notes, files,
appointments, forms, statistics); all of that is overwritten on every sync.
Our own fields (opt-out with us, segments, the unsubscribe token, the send
log) live on the same row and are never touched by the sync.
"""
from __future__ import annotations

import datetime as dt
import re
import secrets
from dataclasses import asdict, dataclass, field
from decimal import Decimal

TOKEN_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o/1/l/i: typed from a text sometimes
TOKEN_LENGTH = 8


@dataclass(frozen=True)
class FreshaClient:
    """What Fresha says about a client: the profile record from
    `GET /v2/customers/<id>` plus, when the sync fetched it, the rest of the
    profile page (`from_record`)."""

    client_id: str
    name: str
    first_name: str = ""
    last_name: str = ""
    mobile: str = ""  # E.164, or "" when Fresha has no usable number
    email: str = ""
    blocked: bool = False
    accepts_sms_marketing: bool = False  # Fresha's "SMS marketing" tick
    accepts_email_marketing: bool = False
    accepts_whatsapp_marketing: bool = False
    labels: list[str] = field(default_factory=list)
    referral_source: str = ""
    created_at: str = ""
    updated_at: str = ""
    # The rest of the profile page, one GraphQL call plus two small REST calls.
    birthday: str = ""  # YYYY-MM-DD, or MM-DD when Fresha has no year
    gender: str = ""
    pronoun: str = ""
    staff_alert: str = ""  # the yellow note the desk sees when the client is picked
    has_payment_method: bool = False
    flags: list[str] = field(default_factory=list)  # Fresha's badges: "no-show x2", "unpaid 10", "birthday"
    tags: list[str] = field(default_factory=list)
    segments: list[str] = field(default_factory=list)  # "First visit", "Loyal" and the like
    allergies: list[dict] = field(default_factory=list)
    patch_tests: list[dict] = field(default_factory=list)
    patch_test_active: bool = False  # a test on file that Fresha does not call expired
    patch_test_count: int = 0
    allergy_count: int = 0
    notes: list[dict] = field(default_factory=list)
    note_count: int = 0
    attachments: list[dict] = field(default_factory=list)  # files on the profile, names only (links expire)
    upcoming: list[dict] = field(default_factory=list)  # appointments, soonest first
    past: list[dict] = field(default_factory=list)  # appointments, latest first (capped)
    appointment_count: int = 0
    forms: list[dict] = field(default_factory=list)  # consultation forms requested of the client
    stats: dict = field(default_factory=dict)  # Fresha's own counters: bookings, no-shows, sales
    record_synced_at: int = 0  # epoch; 0 means the profile page has never been fetched
    record_error: str = ""  # why the profile page could not be fetched this time, or ""

    def as_item(self) -> dict:
        return dynamo_safe(asdict(self))


def new_token() -> str:
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))


def e164(raw: str | None, *, default_country: str = "44") -> str:
    """Fresha's "+44 7517 048938" (or "07517 048938", or "44 7517...") as
    "+447517048938". Anything that is not a plausible number is ""."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if (raw or "").strip().startswith("+"):
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = default_country + digits[1:]
    elif len(digits) <= 10:  # no country code and no leading zero: assume local
        digits = default_country + digits
    if not 10 <= len(digits) <= 15:
        return ""
    return "+" + digits


def from_detail(doc: dict) -> FreshaClient:
    """Build the row from the JSON:API document of `GET /v2/customers/<id>?include=referred_by_customer`."""
    data = doc.get("data") or {}
    a = data.get("attributes") or {}
    source = ""
    rel = ((data.get("relationships") or {}).get("referral-source") or {}).get("data") or {}
    for inc in doc.get("included") or []:
        if inc.get("type") == rel.get("type") and str(inc.get("id")) == str(rel.get("id")):
            source = ((inc.get("attributes") or {}).get("name") or "").strip()
    labels = a.get("labels") or []
    return FreshaClient(
        client_id=str(data.get("id", "")),
        name=(a.get("name") or f"{a.get('first-name', '')} {a.get('last-name', '')}").strip(),
        first_name=(a.get("first-name") or "").strip(),
        last_name=(a.get("last-name") or "").strip(),
        mobile=e164(a.get("contact-number")),
        email=(a.get("email") or "").strip().lower(),
        blocked=bool(a.get("blocked")),
        accepts_sms_marketing=bool(a.get("accepts-sms-marketing-notifications")),
        accepts_email_marketing=bool(a.get("accepts-marketing-notifications")),
        accepts_whatsapp_marketing=bool(a.get("accepts-whatsapp-marketing-notifications")),
        labels=[str(x) for x in labels] if isinstance(labels, list) else [],
        referral_source=source,
        created_at=a.get("created-at") or "",
        updated_at=a.get("updated-at") or "",
    )


def from_record(record: dict, stats: dict | None = None, forms: list | None = None, *, now: int = 0) -> dict:
    """The profile-page fields, from the `clientRecord` GraphQL data (one
    call: customer, notes, attachments, upcoming and past appointments), the
    statistics REST call and the consultation-forms REST call. Returns the
    keyword arguments to put on a FreshaClient."""
    c = record.get("customer") or {}
    tests = [_patch_test(n) for n in _nodes(c.get("patchTests"))]
    birthday = ""
    if c.get("birthdayDay") and c.get("birthdayMonth"):
        md = f"{int(c['birthdayMonth']):02d}-{int(c['birthdayDay']):02d}"
        birthday = f"{int(c['birthdayYear']):04d}-{md}" if c.get("birthdayYear") else md
    notes = [_note(n) for n in _nodes(record.get("notes"))]
    upcoming = [_appointment(n) for n in _nodes(record.get("upcoming"))]
    past = [_appointment(n) for n in _nodes(record.get("past"))]
    stat = {k.replace("-", "_"): v for k, v in ((stats or {}).get("data") or {}).get("attributes", {}).items()}
    return {
        "birthday": birthday,
        "gender": c.get("gender") or "",
        "pronoun": c.get("pronoun") or "",
        "staff_alert": c.get("staffAlert") or "",
        "has_payment_method": bool(c.get("hasPaymentMethod")),
        "flags": [_flag(n) for n in _nodes(c.get("labels")) if _flag(n)],
        "tags": [str(n.get("name") or "") for n in _nodes(c.get("tags")) if n.get("name")],
        "segments": [str((n.get("definition") or {}).get("badgeName") or "") for n in _nodes(c.get("segmentBadges"))
                     if (n.get("definition") or {}).get("badgeName")],
        "allergies": [{k: n.get(k) or "" for k in ("name", "severity", "type", "reaction", "description")}
                      for n in _nodes(c.get("allergies"))],
        "patch_tests": tests,
        "patch_test_active": any(t["active"] for t in tests),
        "patch_test_count": int(c.get("patchTestCount") or len(tests)),
        "allergy_count": len(_nodes(c.get("allergies"))),
        "notes": notes,
        "note_count": len(notes),
        "attachments": [{"id": str(n.get("id") or ""), "file_name": n.get("fileName") or "", "content_type": n.get("contentType") or "",
                         "kind": n.get("kind") or "", "bytes": int(n.get("fileSizeBytes") or 0), "created": n.get("createdAt") or ""}
                        for n in _nodes(record.get("attachments"))],
        "upcoming": upcoming,
        "past": past,
        "appointment_count": int(stat.get("bookings_count") or (len(upcoming) + len(past))),
        "forms": [{"id": str(f.get("id") or ""), **{k.replace("-", "_"): v for k, v in (f.get("attributes") or {}).items()}}
                  for f in ((forms or {}) if isinstance(forms, dict) else {"data": forms or []}).get("data") or []],
        "stats": stat,
        "record_synced_at": now,
        "record_error": "",
    }


def textable(item: dict) -> bool:
    """Can this row be sent a marketing text? In Fresha, has a mobile, Fresha's
    tick is yes, not opted out with us, not blocked."""
    return bool(
        item.get("in_fresha", True)
        and item.get("mobile")
        and item.get("accepts_sms_marketing")
        and not item.get("sms_opt_out")
        and not item.get("blocked")
    )


def dynamo_safe(value):
    """DynamoDB takes Decimal, not float, and the GraphQL answers carry floats for prices."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: dynamo_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [dynamo_safe(v) for v in value]
    return value


# -- pieces of the GraphQL answer ------------------------------------------------


def _nodes(connection) -> list[dict]:
    return [e.get("node") or {} for e in ((connection or {}).get("edges") or []) if isinstance(e, dict)]


def _patch_test(n: dict) -> dict:
    expires = (n.get("expirationDate") or "")[:10]
    expired = bool(n.get("isExpired"))
    if not expired and expires:
        try:
            expired = dt.date.fromisoformat(expires) < dt.date.today()
        except ValueError:
            pass
    return {
        "id": str(n.get("id") or ""),
        "title": n.get("title") or "",
        "status": str(n.get("status") or ""),  # Fresha's own word; values not yet seen on a real test
        "performed": (n.get("performedDate") or "")[:10],
        "expires": expires,
        "expired": expired,
        "confirmation_required": bool(n.get("confirmationRequired")),
        "created": n.get("createdAt") or "",
        "active": not expired,
    }


def _flag(n: dict) -> str:
    kind = str(n.get("__typename") or "")
    if "NoShow" in kind:
        return f"no-show x{n.get('count') or 1}"
    if "Unpaid" in kind:
        return f"unpaid {n.get('amount') or ''}".strip()
    if "Birthday" in kind:
        return "birthday"
    return kind.replace("Customers_", "").replace("Label", "").lower() if kind else ""


def _note(n: dict) -> dict:
    author = n.get("author") or n.get("authorClient") or {}
    return {
        "id": str(n.get("id") or ""),
        "type": str(n.get("type") or ""),
        "body": n.get("body") or "",
        "created": n.get("createdAt") or "",
        "edited": n.get("lastEditedAt") or "",
        "author": author.get("fullName") or "",
        "appointment_id": str((n.get("appointment") or {}).get("id") or ""),
        "attachments": [a.get("fileName") or "" for a in (n.get("attachments") or [])],
    }


def _appointment(n: dict) -> dict:
    services = []
    for b in n.get("bookings") or []:
        svc = b.get("service") or {}
        levels = {str(l.get("id")): l.get("name") or "" for l in (svc.get("servicePricingLevels") or [])}
        emp = b.get("employee") or {}
        services.append({
            "name": svc.get("name") or "",
            "level": levels.get(str(b.get("servicePricingLevelId")), ""),
            "price": str(b.get("price") if b.get("price") is not None else ""),
            "with": " ".join(x for x in (emp.get("firstName"), emp.get("lastName")) if x),
            "start": b.get("startWallClock") or "",
            "end": b.get("endDatetime") or "",
            "add_ons": [str((a.get("serviceAddOn") or {}).get("name") or "") for a in (b.get("bookingServiceAddOns") or [])],
        })
    note = ((n.get("preferredNote") or {}).get("note") or {}).get("body") or ""
    return {
        "id": str(n.get("id") or ""),
        "status": str(n.get("status") or ""),
        "label": str(n.get("statusLabelId") or ""),
        "start": n.get("startWallClock") or "",
        "services": services,
        "note": note,
        "forms": [{"id": str(f.get("id") or ""), "status": str(f.get("status") or "")} for f in (n.get("consultationForms") or [])],
    }


# -- patch tests: what the row can prove, and what the salon assumes --------------

DONE_STATUSES_NOT = ("CANCEL", "NO_SHOW", "NOSHOW")  # a past appointment with any other status counts as attended


def patch_test_evidence(fields: dict, required: set[str]) -> dict | None:
    """Our own patch-test column, worked out from Fresha's side of the row.

    The salon's assumption (user, 2026-10-24): a client who has had a service
    that needs a patch test has been patch tested. So, in order of trust:
    an active patch test on the Fresha record; otherwise the most recent
    past appointment, not cancelled and not a no-show, for a service whose
    name is in `required` (the services Fresha flags as needing a test).
    Returns the fields to write, or None when there is nothing to go on.
    """
    for t in fields.get("patch_tests") or []:
        if t.get("active"):
            return {"patch_tested": True, "patch_test_basis": "fresha record", "patch_test_date": t.get("performed") or (t.get("created") or "")[:10],
                    "patch_test_service": t.get("title") or ""}
    want = {_norm(n) for n in required}
    best = None
    for a in fields.get("past") or []:
        status = str(a.get("status") or "").upper()
        if any(x in status for x in DONE_STATUSES_NOT):
            continue
        for s in a.get("services") or []:
            if _norm(s.get("name")) in want:
                when = (s.get("start") or a.get("start") or "")[:10]
                if best is None or when > best[0]:
                    best = (when, s.get("name") or "", status)
    if best is None:
        return None
    when, name, status = best
    return {"patch_tested": True, "patch_test_basis": f"assumed from {name} on {when} ({status.lower()})",
            "patch_test_date": when, "patch_test_service": name}


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()
