"""Patch tests, for the bot (plan job 12, user 2026-10-24: "when a customer
books in for a lash or brow I want the bot to check their patch status and
then book the appointment, or a patch test plus appointment").

What the clients table says about a client is the salon's own patch-test
column (`clients.model.patch_test_evidence`): a test logged in Fresha, or
assumed from a past lash or brow appointment. This module reads it for the
`patch_test_status` tool and for the booking tool's guard, and knows which
services need a test (the same lash/brow rule as the sync, plus Fresha's
own tick) and how far ahead the test must be (PATCH_TEST_LEAD_HOURS).
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import time

from clients import model as cmodel
from clients.store import ClientStore

log = logging.getLogger(__name__)

LEAD_HOURS = float(os.environ.get("PATCH_TEST_LEAD_HOURS", "24"))
CACHE_SECONDS = 300  # the table changes once a day; one scan per container per five minutes is plenty
PROJECTION = ("client_id", "name", "first_name", "last_name", "patch_tested", "patch_test_basis", "patch_test_date", "in_fresha")

_cache: dict = {}


def is_patch_test_service(service_name) -> bool:
    """The 10-minute patch-test appointment itself ("lash patch test")."""
    return "patch test" in _norm(service_name)


def needs_patch_test(service_name, fresha_flag: bool = False) -> bool:
    """Lash or brow treatments (not makeup, not removals), and anything Fresha
    flags; never the patch test itself."""
    if is_patch_test_service(service_name):
        return False
    return bool(fresha_flag) or cmodel.counts_as_patch_test(service_name, set())


def lookup(client_name: str, *, store: ClientStore | None = None) -> dict | None:
    """The client's row by name, as the booking tool matches names: the whole
    name, case and spacing ignored. Several rows with the name: the tested
    one wins, so a namesake cannot block a client who has been tested."""
    want = _norm(client_name)
    if not want:
        return None
    hits = [r for r in _rows(store) if _norm(r.get("name")) == want or _norm(f"{r.get('first_name', '')} {r.get('last_name', '')}") == want]
    if not hits:
        return None
    return sorted(hits, key=lambda r: (not r.get("patch_tested"), not r.get("in_fresha", True)))[0]


def is_tested(client_name: str, *, store: ClientStore | None = None) -> bool:
    row = lookup(client_name, store=store)
    return bool(row and row.get("patch_tested"))


def status(args: dict, *, store: ClientStore | None = None) -> str:
    """Tool body for `patch_test_status`: one line the model can act on."""
    name = str(args.get("client_name") or "").strip()
    if not name:
        return "Need the client's name."
    row = lookup(name, store=store)
    if row is None:
        return f"No client called '{name}' in the salon's records, so no patch test on record: arrange one before a lash or brow treatment."
    if row.get("patch_tested"):
        when = row.get("patch_test_date") or ""
        return f"Patch tested: {row.get('patch_test_basis') or 'on record'}{', ' + when if when and when not in (row.get('patch_test_basis') or '') else ''}. Book the treatment as normal."
    return f"No patch test on record for {name}: arrange one at least {LEAD_HOURS:g} hours before a lash or brow treatment."


def booked_in_conversation(convo, date: str, start: str, *, lead_hours: float | None = None) -> bool:
    """A patch-test appointment booked earlier in this thread, not cancelled,
    far enough before the treatment slot."""
    lead = LEAD_HOURS if lead_hours is None else lead_hours
    try:
        treatment = dt.datetime.fromisoformat(f"{date}T{start}")
    except ValueError:
        return False
    for b in getattr(convo, "bookings", None) or []:
        if b.get("cancelled_at") or not is_patch_test_service(b.get("service")):
            continue
        try:
            test = dt.datetime.fromisoformat(f"{b.get('date')}T{b.get('time')}")
        except (TypeError, ValueError):
            continue
        if test + dt.timedelta(hours=lead) <= treatment:
            return True
    return False


def forget() -> None:
    _cache.clear()


def _rows(store: ClientStore | None) -> list[dict]:
    if store is None and time.monotonic() < _cache.get("until", 0.0):
        return _cache["rows"]
    rows = (store or ClientStore()).all_rows(projection=PROJECTION)
    if store is None:
        _cache.update(until=time.monotonic() + CACHE_SECONDS, rows=rows)
    return rows


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()
