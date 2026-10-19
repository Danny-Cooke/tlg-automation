"""Lambda entry point for the Fresha watch.

Runs the checks in checks.py against Fresha's public pages, compares with the
previous run (kept in one SSM parameter), and on any transition sends a text
message to the configured phone numbers and a fuller email to the ops topic.
Steady state, good or bad, is quiet: a broken page alerts once when it breaks
and once when it recovers, a changed shape alerts once when it changes.

Environment:
    FRESHA_VENUE_URL      the salon's public Fresha venue page
    FRESHA_GENERAL_LINK   the general booking link the bot hands out (optional)
    SALON_NAME            what the general link must mention (optional)
    STATE_PARAMETER       SSM parameter holding the previous run
    OPS_TOPIC_ARN         SNS topic for the email (optional)
    ALERT_PHONE_NUMBERS   comma-separated E.164 numbers for the text (optional)
    SMS_SENDER_ID         the End User Messaging sender ID the text comes from

Texts go through AWS End User Messaging (pinpoint-sms-voice-v2), not SNS:
SNS accepted texts from this account and silently dropped them, End User
Messaging with the sender ID delivered (2026-10-19). SNS is only the email.

Invoke with {"dry_run": true} to run the checks and see the diff without
saving state or sending anything. Invoke with {"test_sms": true} to send a
test text to the configured numbers through the real path.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import zlib
from datetime import datetime, timezone
from functools import lru_cache

from menu_sync import fresha_public

from . import checks, shape
from .checks import CheckResult

log = logging.getLogger("fresha_watch")
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DEFAULT_FUNCTION_NAME = "tlg-fresha-watch"
SUBJECT = "Fresha's public pages about staff, calendars or services"


def lambda_handler(event: dict, context=None) -> dict:
    event = event or {}
    if event.get("test_sms"):
        return test_sms(sms=_sms(), env=dict(os.environ))
    return run(
        http=_http(), ssm=_ssm(), sns=_sns(), sms=_sms(), env=dict(os.environ), dry_run=bool(event.get("dry_run"))
    )


def test_sms(*, sms, env: dict) -> dict:
    """Send one test text so the number, the sandbox and the IAM are proven
    before Fresha ever changes."""
    numbers = env.get("ALERT_PHONE_NUMBERS", "")
    if not numbers.strip():
        return {"test": True, "sms_sent_to": [], "error": "ALERT_PHONE_NUMBERS is empty; nothing to text"}
    text = f"{function_name(env)}: test message. A real one says: something has changed in {SUBJECT}."
    sent_to = send_sms(sms, numbers, text, env.get("SMS_SENDER_ID", ""))
    return {"test": True, "sms_sent_to": sent_to, "message": text}


def function_name(env: dict) -> str:
    return env.get("AWS_LAMBDA_FUNCTION_NAME") or DEFAULT_FUNCTION_NAME


def run(*, http, ssm, sns, sms, env: dict, dry_run: bool = False, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    results = run_checks(http, env)
    previous = load_state(ssm, env["STATE_PARAMETER"])
    alerts = diff(previous, results)

    result = {
        "ok": all(r.ok for r in results),
        "alerts": alerts,
        "checks": [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in results],
        "first_run": not previous,
        "dry_run": dry_run,
    }
    if dry_run:
        return result

    save_state(ssm, env["STATE_PARAMETER"], next_state(previous, results, now))
    if alerts:
        subject, body = format_email(alerts, results, now)
        text = format_sms(alerts, function_name(env))
        sent_to = send_sms(sms, env.get("ALERT_PHONE_NUMBERS", ""), text, env.get("SMS_SENDER_ID", ""))
        topic = env.get("OPS_TOPIC_ARN")
        if topic:
            sns.publish(TopicArn=topic, Subject=subject[:100], Message=body)
        result["sms_sent_to"] = sent_to
        log.warning("alerted: %s", json.dumps(alerts))
    else:
        log.info("quiet: %s", json.dumps(result["checks"]))
    return result


def run_checks(http, env: dict) -> list[CheckResult]:
    venue = env["FRESHA_VENUE_URL"]
    results = [checks.check_venue_page(http, venue), checks.check_booking_flow(http, venue)]
    # Who-does-what needs the per-person filter. Use the first listed person.
    # Skipped when the page or the flow is already broken: it would only
    # repeat the same failure.
    if results[0].ok and results[1].ok:
        try:
            team = fresha_public.fetch_team(http, venue)
            first = team[0]
            results.append(checks.check_booking_flow_per_person(http, venue, first.employee_id, first.name))
        except Exception as exc:  # noqa: BLE001 - venue page passed a moment ago; report, don't crash
            results.append(CheckResult("booking_flow_per_person", False, f"could not pick a person: {exc}"))
    general = env.get("FRESHA_GENERAL_LINK")
    if general:
        results.append(checks.check_general_link(http, general, env.get("SALON_NAME", "Looking Glass")))
    return results


# ---------------------------------------------------------------------------
# State and diffing
# ---------------------------------------------------------------------------


def load_state(ssm, name: str) -> dict:
    try:
        raw = ssm.get_parameter(Name=name)["Parameter"]["Value"]
        return decode_state(raw)
    except Exception as exc:  # noqa: BLE001 - missing or unreadable means first run
        log.warning("no previous state (%s)", exc)
        return {}


def save_state(ssm, name: str, state: dict) -> None:
    ssm.put_parameter(Name=name, Value=encode_state(state), Type="String", Overwrite=True, Tier="Intelligent-Tiering")


def encode_state(state: dict) -> str:
    """The shapes are a few KB of repetitive paths; an SSM parameter holds 4KB
    (8KB advanced). Deflate them and keep the rest readable in the console."""
    doc = {k: v for k, v in state.items() if k != "shapes"}
    packed = zlib.compress(json.dumps(state.get("shapes", {}), separators=(",", ":")).encode("utf-8"), 9)
    doc["shapes_z"] = base64.b64encode(packed).decode("ascii")
    return json.dumps(doc)


def decode_state(raw: str) -> dict:
    if not raw or raw == "{}":
        return {}
    doc = json.loads(raw)
    packed = doc.pop("shapes_z", None)
    doc["shapes"] = json.loads(zlib.decompress(base64.b64decode(packed))) if packed else doc.get("shapes", {})
    return doc


def next_state(previous: dict, results: list[CheckResult], now: datetime) -> dict:
    shapes = dict(previous.get("shapes", {}))
    for r in results:
        if r.ok and r.paths is not None:
            shapes[r.name] = r.paths
    return {
        "updated": now.isoformat(),
        "failing": sorted(r.name for r in results if not r.ok),
        "shapes": shapes,
        "info": {r.name: r.info for r in results if r.info},
    }


def diff(previous: dict, results: list[CheckResult]) -> list[dict]:
    """Transitions worth a message. Steady state, good or bad, is quiet."""
    was_failing = set(previous.get("failing", []))
    old_shapes = previous.get("shapes", {})
    alerts: list[dict] = []
    for r in results:
        if not r.ok and r.name not in was_failing:
            alerts.append({"check": r.name, "kind": "failed", "detail": r.detail, "lines": []})
        elif r.ok and r.name in was_failing:
            alerts.append({"check": r.name, "kind": "recovered", "detail": r.detail, "lines": []})
        if r.ok and r.paths is not None and r.name in old_shapes and old_shapes[r.name] != r.paths:
            lines = shape.describe(old_shapes[r.name], r.paths)
            alerts.append(
                {
                    "check": r.name,
                    "kind": "changed",
                    "detail": f"shape {shape.fingerprint(old_shapes[r.name])} -> {shape.fingerprint(r.paths)}; {r.detail}",
                    "lines": lines,
                }
            )
    return alerts


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def headline(alerts: list[dict]) -> str:
    kinds = {a["kind"] for a in alerts}
    if "failed" in kinds:
        return "BROKEN"
    if "changed" in kinds:
        return "CHANGED"
    return "RECOVERED"


def format_sms(alerts: list[dict], name: str = DEFAULT_FUNCTION_NAME) -> str:
    """One short sentence; the email has the detail. Wording chosen by the user."""
    what = headline(alerts)
    if what == "BROKEN":
        failing = ", ".join(sorted(a["check"] for a in alerts if a["kind"] == "failed"))
        body = f"{SUBJECT} are not working ({failing})"
    elif what == "CHANGED":
        body = f"something has changed in {SUBJECT}"
    else:
        body = f"{SUBJECT} are working again"
    return f"{name}: {body}. Details in the ops email."


def format_email(alerts: list[dict], results: list[CheckResult], now: datetime) -> tuple[str, str]:
    names = ", ".join(sorted({a["check"] for a in alerts}))
    subject = f"[TLG Fresha watch] {headline(alerts)}: {names}"
    lines = [f"Run at {now.strftime('%Y-%m-%d %H:%M UTC')}", ""]
    for a in alerts:
        lines.append(f"{a['kind'].upper()}  {a['check']}: {a['detail']}")
        lines.extend(f"    {line}" for line in a["lines"])
    lines += ["", "All checks this run:"]
    for r in results:
        lines.append(f"  {'ok  ' if r.ok else 'FAIL'} {r.name}: {r.detail}")
    lines += [
        "",
        "CHANGED means Fresha's page or response has a different shape; the menu sync may",
        "still work but check its next run. BROKEN means the menu sync will fail until fixed.",
        "See docs/architecture.md (Fresha watch) and knowledge/fresha.md.",
    ]
    return subject, "\n".join(lines)


def send_sms(sms, numbers: str, text: str, sender_id: str) -> list[str]:
    """One text per number through End User Messaging, from the sender ID.
    A failure is logged and skipped so the other numbers and the email still go."""
    sent: list[str] = []
    for number in [n.strip() for n in numbers.split(",") if n.strip()]:
        try:
            kwargs = {"DestinationPhoneNumber": number, "MessageBody": text, "MessageType": "TRANSACTIONAL"}
            if sender_id:
                kwargs["OriginationIdentity"] = sender_id
            sms.send_text_message(**kwargs)
            sent.append(number)
        except Exception as exc:  # noqa: BLE001 - the email still goes; log and carry on
            log.error("SMS to %s failed: %s", number[-4:], exc)
    return sent


# ---------------------------------------------------------------------------
# AWS clients
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _http():
    import requests

    return requests.Session()


@lru_cache(maxsize=1)
def _ssm():
    import boto3

    return boto3.client("ssm")


@lru_cache(maxsize=1)
def _sns():
    import boto3

    return boto3.client("sns")


@lru_cache(maxsize=1)
def _sms():
    import boto3

    return boto3.client("pinpoint-sms-voice-v2")
