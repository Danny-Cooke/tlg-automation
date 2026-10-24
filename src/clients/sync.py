"""Lambda: mirror Fresha's client list, and everything on each client's
profile page, into the clients table.

Pages through the dashboard's client search with the owner's stored session
(cheap: a dozen pages), then for each client fetches the four things the
profile page loads: the record with the marketing ticks, the GraphQL
profile (patch tests, allergies, tags, badges, staff alert, notes, files,
upcoming and past appointments), Fresha's statistics, and consultation
forms. Clients are refreshed stalest first, inside the Lambda's time budget;
whatever is left over is first in line next run, and the summary says how
many. Daily by schedule, or by hand:

    {}                        sync
    {"dry_run": true}         fetch, count, write nothing
    {"limit": 5}              only the five stalest clients (quick look)

Returns and logs a summary. Fresha rejecting the session emails the ops
topic, like the bot does, so someone runs scripts/fresha_session.py.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import time
from functools import lru_cache

from bot import fresha, fresha_session

from . import model
from .store import ClientStore

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

PAGE = 50
PAUSE_SECONDS = float(os.environ.get("FRESHA_PAUSE_SECONDS", "0.05"))  # between clients; be a polite dashboard
SAFETY_SECONDS = 45.0  # stop fetching this long before the Lambda would be killed


def lambda_handler(event: dict, context=None) -> dict:
    event = event or {}
    session = fresha_session.get()
    if session is None:
        _ops("Client sync: no Fresha session",
             "The clients table was not synced: the Fresha session parameter is unset or expired. Run scripts/fresha_session.py.")
        return {"error": "no Fresha session"}
    deadline = None
    if context is not None and hasattr(context, "get_remaining_time_in_millis"):
        deadline = time.monotonic() + context.get_remaining_time_in_millis() / 1000.0 - SAFETY_SECONDS
    try:
        return run(fresha.Fresha(session), ClientStore(), dry_run=bool(event.get("dry_run")),
                   limit=int(event.get("limit") or 0), deadline=deadline)
    except fresha.SessionRejected as exc:
        _ops("Client sync: Fresha rejected the session", f"{exc}\nRun scripts/fresha_session.py.")
        return {"error": str(exc)}


def patch_test_services(f: fresha.Fresha) -> set[str]:
    """Names of the services Fresha flags as needing a patch test (the tick on
    the service's Settings page), read from the catalog each run."""
    return {s.name for s in f.catalog() if s.patch_test}


def run(f: fresha.Fresha, store: ClientStore, *, dry_run: bool = False, pause: float | None = None,
        limit: int = 0, deadline: float | None = None, now: int | None = None, required: set[str] | None = None) -> dict:
    pause = PAUSE_SECONDS if pause is None else pause
    now = now or int(time.time())
    started = time.monotonic()
    if required is None:
        try:
            required = patch_test_services(f)
        except fresha.SessionRejected:
            raise
        except fresha.FreshaError as exc:  # the mirror still runs; the column just is not widened this time
            log.warning("Could not read the catalog for patch-test services: %s", exc)
            required = set()
    patch_tested = 0
    ids: list[str] = []
    for row in iter_search(f):
        cid = str(row.get("id", ""))
        if cid and cid not in ids:
            ids.append(cid)
    order = ids if dry_run else store.stalest_first(ids)
    if limit:
        order = order[:limit]

    fetched = records = record_errors = 0
    remaining = 0
    for i, cid in enumerate(order):
        if deadline is not None and time.monotonic() > deadline:
            remaining = len(order) - i
            log.warning("Out of time: %d client(s) left for the next run", remaining)
            break
        client = model.from_detail(f.client_detail(cid))
        fetched += 1
        try:
            extra = model.from_record(f.client_record(cid), f.client_statistics(cid), f.client_forms(cid), now=now)
            records += 1
        except fresha.SessionRejected:
            raise
        except fresha.FreshaError as exc:  # keep the basic row, say why the rest is missing
            record_errors += 1
            log.warning("Profile fetch failed for client %s: %s", cid, exc)
            extra = {"record_error": str(exc)[:200]}
        client = dataclasses.replace(client, **extra)
        evidence = model.patch_test_evidence(extra, required) if required else None
        if evidence:
            patch_tested += 1
        if not dry_run:
            store.upsert_from_fresha(client, now=now)
            if evidence:
                store.set_patch_tested(cid, evidence, now=now)
        if pause:
            time.sleep(pause)

    gone = [] if dry_run else store.mark_missing(set(ids), now=now)
    summary = {
        "dry_run": dry_run,
        "fresha_clients": len(ids),
        "fetched": fetched,
        "records": records,
        "record_errors": record_errors,
        "remaining": remaining,
        "patch_test_services": sorted(required),
        "patch_test_evidence": patch_tested,
        "marked_missing": len(gone),
        "seconds": round(time.monotonic() - started, 1),
        **({} if dry_run else store.summary()),
    }
    if summary.get("fresha_pending"):
        log.warning("%s opt-out change(s) waiting to be written back to Fresha (call not recorded yet, plan job 10 step 3)",
                    summary["fresha_pending"])
    log.info("CLIENT SYNC %s", json.dumps(summary, default=str))
    return summary


def iter_search(f: fresha.Fresha, *, page: int = PAGE):
    """Every row of the client search, in Fresha's order. Uses the total Fresha
    reports so a server-side page cap smaller than `page` cannot end it early."""
    offset = 0
    total = None
    while True:
        rows, count = f.client_page(offset=offset, limit=page)
        if count is not None:
            total = count
        if not rows:
            return
        yield from rows
        offset += len(rows)
        if total is not None and offset >= total:
            return


def _ops(subject: str, body: str) -> None:
    topic = os.environ.get("OPS_TOPIC_ARN")
    log.warning("%s: %s", subject, body)
    if not topic:
        return
    try:
        _sns().publish(TopicArn=topic, Subject=f"[TLG] {subject}"[:100], Message=body)
    except Exception:  # noqa: BLE001
        log.exception("Ops email failed")


@lru_cache(maxsize=1)
def _sns():
    import boto3

    return boto3.client("sns")
