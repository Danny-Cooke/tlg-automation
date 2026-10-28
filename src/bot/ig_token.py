"""Keep the salon's Instagram token alive (plan job 18, 2026-10-27).

The Instagram bot talks to graph.instagram.com with the salon account's own
token ("Instagram API with Instagram Login"). Meta issues it for 60 days and
lets it be refreshed any time after its first day, which starts the 60 days
again. This Lambda runs weekly from an EventBridge schedule, and once from
the deploy pipeline after every apply:

  1. checks the token works (GET /me) and notes the account id and name;
  2. subscribes the account to the app's `messages` webhook, which is what
     makes Meta deliver DMs (idempotent, re-asserted on every run);
  3. refreshes the token when it is older than a day, and writes the new
     one with its expiry back to the token's own secret. Terraform ignores
     that secret's value, so a deploy never puts a stale token back;
  4. tells the ops topic, and the team's Telegram group, when the refresh
     failed or the token has under IG_TOKEN_WARN_DAYS days left. A dead
     token needs someone with the salon's Instagram login to generate a new
     one in the Meta console and seed the secret (docs/setup.md step 6).

The secret holds {"access_token", "expires_at", "refreshed_at", "user_id",
"username"}. The first seed only needs access_token; the rest is filled in
on the first run. Weekly runs give eight tries before a token could die.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os

from . import telegram
from .meta import GRAPH_VERSION

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

IG_BASE = f"https://graph.instagram.com/{GRAPH_VERSION}"
TOKEN_LIFETIME = dt.timedelta(days=60)
MIN_AGE_TO_REFRESH = dt.timedelta(hours=24)
WARN_DAYS = int(os.environ.get("IG_TOKEN_WARN_DAYS", "10"))
SUBSCRIBED_FIELDS = os.environ.get("IG_SUBSCRIBED_FIELDS", "messages")


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def _parse(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def days_left(held: dict, now: dt.datetime) -> float | None:
    """Days until the stored token expires; None when the secret carries no expiry."""
    expires = _parse(held.get("expires_at"))
    return None if expires is None else (expires - now).total_seconds() / 86400


def due_for_refresh(held: dict, now: dt.datetime) -> bool:
    """Meta refuses to refresh a token under a day old; anything older is refreshed."""
    last = _parse(held.get("refreshed_at"))
    return last is None or now - last >= MIN_AGE_TO_REFRESH


def whoami(token: str, *, session=None) -> dict:
    """The account the token belongs to: {"user_id", "username"}. Raises on a bad token."""
    import requests

    http = session or requests
    resp = http.get(f"{IG_BASE}/me", params={"access_token": token, "fields": "user_id,username"}, timeout=10)
    if resp.status_code >= 400:
        raise RuntimeError(f"GET /me failed {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return {"user_id": str(data.get("user_id") or data.get("id") or ""), "username": data.get("username", "")}


def subscribe(token: str, *, session=None) -> dict:
    """Subscribe the account to the app's webhook fields. Raises on failure."""
    import requests

    http = session or requests
    resp = http.post(f"{IG_BASE}/me/subscribed_apps", params={"access_token": token, "subscribed_fields": SUBSCRIBED_FIELDS}, timeout=10)
    if resp.status_code >= 400:
        raise RuntimeError(f"POST /me/subscribed_apps failed {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def refresh(token: str, *, session=None) -> tuple[str, int]:
    """A fresh 60-day token for the same account: (token, seconds it lasts). Raises on failure."""
    import requests

    http = session or requests
    resp = http.get(f"{IG_BASE}/refresh_access_token", params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=10)
    if resp.status_code >= 400:
        raise RuntimeError(f"refresh_access_token failed {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return data["access_token"], int(data.get("expires_in") or TOKEN_LIFETIME.total_seconds())


def run(held: dict, now: dt.datetime, *, session=None) -> tuple[dict, list[str]]:
    """One pass over the stored token. Returns (what to store, problems to report)."""
    problems: list[str] = []
    token = held.get("access_token", "")
    if not token:
        return held, ["No Instagram token stored yet: generate one in the Meta console and seed the secret."]
    out = dict(held)
    out.setdefault("expires_at", _iso(now + TOKEN_LIFETIME))  # a seeded token is a fresh 60-day one

    try:
        out.update(whoami(token, session=session))
    except Exception as exc:  # noqa: BLE001
        problems.append(f"The Instagram token no longer works: {exc}")
        return out, problems

    try:
        subscribe(token, session=session)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"Could not subscribe the Instagram account to the webhook: {exc}")

    if due_for_refresh(out, now):
        try:
            new_token, seconds = refresh(token, session=session)
            out.update(access_token=new_token, expires_at=_iso(now + dt.timedelta(seconds=seconds)), refreshed_at=_iso(now))
            log.info("Instagram token refreshed; now good until %s", out["expires_at"])
        except Exception as exc:  # noqa: BLE001
            left = days_left(out, now)
            text = f"Instagram token refresh failed: {exc}"
            if left is not None and left < WARN_DAYS:
                problems.append(text)
            else:
                log.warning("%s (still %s days left, trying again next week)", text, None if left is None else round(left))

    left = days_left(out, now)
    if left is not None and left < WARN_DAYS:
        problems.append(f"The Instagram token runs out in {max(left, 0):.0f} days and could not be renewed.")
    return out, problems


def report(problems: list[str], *, sns=None, post=None) -> None:
    """Ops email always; the team group too, since renewing by hand needs the salon's Instagram login."""
    text = "Instagram bot: " + " ".join(problems) + " Until it is fixed the Instagram bot cannot answer DMs; see docs/setup.md step 6."
    log.error(text)
    topic = os.environ.get("OPS_TOPIC_ARN")
    if topic:
        import boto3

        (sns or boto3.client("sns")).publish(TopicArn=topic, Subject="[TLG bot] Instagram token needs attention"[:100], Message=text)
    (post or telegram.post_handover)(text)


def lambda_handler(event: dict | None = None, context=None) -> dict:
    import boto3

    arn = os.environ["META_TOKEN_SECRET_ARN"]
    sm = boto3.client("secretsmanager")
    now = dt.datetime.now(dt.timezone.utc)
    try:
        held = json.loads(sm.get_secret_value(SecretId=arn)["SecretString"] or "{}")
    except sm.exceptions.ResourceNotFoundException:
        # The secret is created by hand (docs/setup.md section 1 step 6), not by Terraform.
        held, out = {}, {}
        problems = [f"The Instagram token secret {arn} does not exist yet: create it from the Meta console token."]
    else:
        out, problems = run(held, now)
        if out != held:
            sm.put_secret_value(SecretId=arn, SecretString=json.dumps(out))
    if problems:
        report(problems)
    summary = {
        "source": (event or {}).get("source", ""),
        "account": out.get("username", ""),
        "expires_at": out.get("expires_at", ""),
        "refreshed": out.get("access_token") != held.get("access_token"),
        "problems": problems,
    }
    log.info("Instagram token check: %s", summary)
    return summary
