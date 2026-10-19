"""Lambda entry point for the scheduled monitor.

Runs every check, compares with the previous run (kept in one SSM parameter),
and publishes to the ops SNS topic when something is newly broken, newly
fixed, or has changed shape. A healthy, unchanged run is silent.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from . import checks
from .checks import CheckResult

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

GRAPH_VERSION = os.environ.get("GRAPH_API_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def lambda_handler(event: dict, context=None) -> dict:
    return run(http=_http(), ssm=_ssm(), sns=_sns(), cloudwatch=_cloudwatch(), secrets=_meta_secret())


def run(*, http, ssm, sns, cloudwatch, secrets: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    env = os.environ
    results = run_checks(http=http, cloudwatch=cloudwatch, secrets=secrets, env=env, now=now)

    param = env["MONITOR_STATE_PARAMETER"]
    previous = load_state(ssm, param)
    alerts = diff(previous, results)
    state = next_state(previous, results, now)
    save_state(ssm, param, state)

    summary = {
        "ok": all(r.ok for r in results),
        "checks": {r.name: {"ok": r.ok, "detail": r.detail, **({"fingerprint": r.fingerprint} if r.fingerprint else {})} for r in results},
        "alerts": alerts,
    }
    log.info("monitor %s", json.dumps(summary))

    topic = env.get("OPS_TOPIC_ARN")
    if alerts and topic:
        subject, body = format_alert(alerts, results, now)
        sns.publish(TopicArn=topic, Subject=subject[:100], Message=body)
    return summary


def run_checks(*, http, cloudwatch, secrets: dict, env, now: datetime) -> list[CheckResult]:
    results: list[CheckResult] = []

    def guarded(name: str, fn):
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001 - a crashing check is itself the finding
            log.exception("check %s crashed", name)
            results.append(CheckResult(name, False, f"check crashed: {exc}"))

    guarded("webhook_endpoint", lambda: checks.check_webhook(http, env["WEBHOOK_URL"], secrets["verify_token"]))
    guarded("meta_page", lambda: checks.check_meta_page(http, GRAPH_BASE, secrets["page_token"], env["META_PAGE_ID"]))

    links = json.loads(env.get("FRESHA_LINKS_JSON", "[]"))
    if links:
        guarded("fresha_links", lambda: checks.check_fresha_links(http, links, env.get("SALON_NAME", "")))

    dashboard = checks.check_fresha_dashboard(http)
    results.append(dashboard)
    if dashboard.ok:
        guarded(
            "fresha_create_contract",
            lambda: checks.check_fresha_create_contract(http, dashboard.info["runtime"]),
        )

    if env.get("BOT_FUNCTION_NAME"):
        guarded("bot_traffic", lambda: bot_traffic(cloudwatch, env["BOT_FUNCTION_NAME"], now))
    return results


def bot_traffic(cloudwatch, function_name: str, now: datetime) -> CheckResult:
    """Invocations and errors for the bot over the last 24 hours. Information for the
    alert body; the CloudWatch alarm is what pages on errors."""
    totals = {}
    for metric in ("Invocations", "Errors"):
        data = cloudwatch.get_metric_statistics(
            Namespace="AWS/Lambda",
            MetricName=metric,
            Dimensions=[{"Name": "FunctionName", "Value": function_name}],
            StartTime=now - timedelta(hours=24),
            EndTime=now,
            Period=86400,
            Statistics=["Sum"],
        )
        totals[metric] = int(sum(p["Sum"] for p in data.get("Datapoints", [])))
    return CheckResult(
        "bot_traffic",
        True,
        f"last 24h: {totals['Invocations']} invocations, {totals['Errors']} errors",
        info=totals,
    )


# ---------------------------------------------------------------------------
# State and diffing
# ---------------------------------------------------------------------------


def load_state(ssm, name: str) -> dict:
    try:
        raw = ssm.get_parameter(Name=name)["Parameter"]["Value"]
        return json.loads(raw) if raw and raw != "{}" else {}
    except Exception as exc:  # noqa: BLE001 - missing or unreadable means first run
        log.warning("no previous monitor state (%s)", exc)
        return {}


def save_state(ssm, name: str, state: dict) -> None:
    ssm.put_parameter(Name=name, Value=json.dumps(state), Type="String", Overwrite=True)


def next_state(previous: dict, results: list[CheckResult], now: datetime) -> dict:
    fingerprints = dict(previous.get("fingerprints", {}))
    for r in results:
        if r.fingerprint:
            fingerprints[r.name] = r.fingerprint
    return {
        "updated": now.isoformat(),
        "failing": sorted(r.name for r in results if not r.ok),
        "fingerprints": fingerprints,
        "info": {r.name: r.info for r in results if r.info},
    }


def diff(previous: dict, results: list[CheckResult]) -> list[dict]:
    """Transitions worth telling someone about. Steady state, good or bad, is quiet."""
    was_failing = set(previous.get("failing", []))
    old_fp = previous.get("fingerprints", {})
    alerts: list[dict] = []
    for r in results:
        if not r.ok and r.name not in was_failing:
            alerts.append({"check": r.name, "kind": "failed", "detail": r.detail})
        elif r.ok and r.name in was_failing:
            alerts.append({"check": r.name, "kind": "recovered", "detail": r.detail})
        if r.ok and r.fingerprint and r.name in old_fp and old_fp[r.name] != r.fingerprint:
            alerts.append(
                {
                    "check": r.name,
                    "kind": "changed",
                    "detail": f"{old_fp[r.name]} -> {r.fingerprint}. {r.detail}",
                }
            )
    return alerts


def format_alert(alerts: list[dict], results: list[CheckResult], now: datetime) -> tuple[str, str]:
    kinds = {a["kind"] for a in alerts}
    if "failed" in kinds:
        headline = "FAILING"
    elif "changed" in kinds:
        headline = "CHANGED"
    else:
        headline = "RECOVERED"
    names = ", ".join(sorted({a["check"] for a in alerts}))
    subject = f"[TLG monitor] {headline}: {names}"
    lines = [f"Run at {now.strftime('%Y-%m-%d %H:%M UTC')}", ""]
    for a in alerts:
        lines.append(f"{a['kind'].upper()}  {a['check']}: {a['detail']}")
    lines += ["", "All checks this run:"]
    for r in results:
        lines.append(f"  {'ok  ' if r.ok else 'FAIL'} {r.name}: {r.detail}")
    lines += [
        "",
        "What to do: see docs/architecture.md (Monitoring) and knowledge/fresha-internal-api.md.",
    ]
    return subject, "\n".join(lines)


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
def _cloudwatch():
    import boto3

    return boto3.client("cloudwatch")


@lru_cache(maxsize=1)
def _meta_secret() -> dict:
    import boto3

    raw = boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["META_SECRET_ARN"])["SecretString"]
    return json.loads(raw)
