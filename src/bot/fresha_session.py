"""The Fresha dashboard session the bot books with.

A person refreshes it with scripts/fresha_session.py, which writes a JSON
document to an SSM SecureString parameter (FRESHA_SESSION_PARAM):

    {"cookie": "...", "expires_at": "2026-11-19T16:05:55+00:00", "refreshed_at": "..."}

This module reads it at run time, keeps it in memory for a few minutes so a
busy afternoon does not hammer SSM, and treats "unset" (Terraform's
placeholder), a missing parameter or a past expiry as "no session". The
booking code asks `get()` before every Fresha write and `forget()` after a
401, so the next message re-reads the parameter. Nothing here ever logs the
cookie.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

UNSET = "unset"
CACHE_SECONDS = 300
COOKIE_NAME = "fresha_partners_session"


@dataclass(frozen=True)
class Session:
    cookie: str
    expires_at: dt.datetime | None

    def days_left(self, now: dt.datetime | None = None) -> int | None:
        if self.expires_at is None:
            return None
        now = now or dt.datetime.now(dt.timezone.utc)
        return max(0, (self.expires_at - now).days)

    def cookies(self) -> dict[str, str]:
        return {COOKIE_NAME: self.cookie}


_cache: dict[str, object] = {}


def get(*, ssm=None, now: dt.datetime | None = None) -> Session | None:
    """The current session, or None when there is none to use. Never raises."""
    name = os.environ.get("FRESHA_SESSION_PARAM", "")
    if not name:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    if _cache.get("name") == name and time.monotonic() < _cache.get("until", 0.0):
        session = _cache.get("session")
    else:
        session = _read(name, ssm)
        _cache.update(name=name, until=time.monotonic() + CACHE_SECONDS, session=session)
    if session and session.expires_at and session.expires_at <= now:
        log.warning("Fresha session expired at %s; run scripts/fresha_session.py", session.expires_at.isoformat())
        return None
    return session


def forget() -> None:
    """Drop the cached copy, e.g. after Fresha answered 401."""
    _cache.clear()


GRAPHQL = "https://partners-api-gateway.fresha.com/graphql"
CLIENT_VERSION = "2.8.12165"  # the dashboard's own, from the 2026-10-20 recording
# A query the dashboard runs right after login; needs the session, changes nothing.
PROBE_QUERY = "query users_profileDetails { __typename profileDetails: Partners_profileDetails { __typename joinedAt location } }"


def probe(session: Session, http=None, *, owner_id: str = "") -> str | None:
    """Ask Fresha who this session is, over plain HTTP with only the cookie.
    Returns the profile location on success, None when Fresha rejects it.
    Same call scripts/fresha_session.py makes on the laptop; from Lambda it
    proves the cookie is accepted from AWS's address too."""
    if http is None:
        import requests

        http = requests.Session()
    params = {"_query": "users_profileDetails", "_client_platform": "web", "_client_version": CLIENT_VERSION}
    if owner_id:
        params["__pid"] = owner_id
    try:
        resp = http.post(
            GRAPHQL, params=params,
            data={"operationName": "users_profileDetails", "query": PROBE_QUERY, "variables": "{}"},
            cookies=session.cookies(),
            headers={"accept": "application/json", "origin": "https://partners.fresha.com", "referer": "https://partners.fresha.com/"},
            timeout=15,
        )
        body = resp.json()
    except Exception as e:  # noqa: BLE001 - a probe must never take the bot down
        log.warning("Fresha probe failed: %s", type(e).__name__)
        return None
    details = (body.get("data") or {}).get("profileDetails") if isinstance(body, dict) else None
    if resp.status_code == 200 and details:
        return details.get("location") or "an account with no location set"
    log.warning("Fresha probe rejected: HTTP %s %s", resp.status_code, str(body)[:200])
    return None


def parse(value: str) -> Session | None:
    """The parameter's JSON document to a Session; None for the placeholder or junk."""
    if not value or value == UNSET:
        return None
    try:
        doc = json.loads(value)
    except ValueError:
        return None
    cookie = doc.get("cookie") if isinstance(doc, dict) else None
    if not cookie:
        return None
    expires = None
    raw = doc.get("expires_at")
    if raw:
        try:
            expires = dt.datetime.fromisoformat(raw)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            expires = None
    return Session(cookie=str(cookie), expires_at=expires)


def _read(name: str, ssm) -> Session | None:
    try:
        client = ssm or _ssm()
        value = client.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    except Exception as e:  # noqa: BLE001 - a missing session is a state, not a crash
        log.warning("Could not read Fresha session parameter %s: %s", name, type(e).__name__)
        return None
    session = parse(value)
    if session is None:
        log.info("Fresha session parameter %s is not set yet", name)
    return session


def _ssm():
    import boto3

    return boto3.client("ssm")
