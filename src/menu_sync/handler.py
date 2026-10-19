"""Lambda entry point: read Fresha, compare with the repo, open a PR if needed.

Runs daily from EventBridge and on demand. Invoke with {"dry_run": true} to
get the diff back without touching GitHub or sending anything.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from functools import lru_cache

from . import fresha_public, model
from .github_client import GitHub

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

BRANCH = "menu-sync"


def lambda_handler(event: dict, context=None) -> dict:
    dry_run = bool((event or {}).get("dry_run"))
    return run(http=_http(), ssm=_ssm(), sns=_sns(), env=os.environ, dry_run=dry_run)


def run(*, http, ssm, sns, env, dry_run: bool = False, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    venue_url = env["FRESHA_VENUE_URL"]
    repo = env["GITHUB_REPO"]
    base = env.get("GITHUB_BASE_BRANCH", "main")
    path = env.get("MENU_FILE_PATH", model.MENU_FILE)

    menu = read_fresha(http, venue_url)
    new_content = menu.content()

    gh = GitHub(http, github_token(ssm, env["GITHUB_PAT_PARAMETER"]), repo)
    old_text, _ = gh.get_file(path, base)
    old_doc = model.parse_existing(old_text)
    old_content = model.content_of(old_doc)

    result = {
        "changed": old_content != new_content,
        "staff": len(menu.staff),
        "services": len(menu.services),
        "dry_run": dry_run,
    }
    if not result["changed"]:
        log.info("menu unchanged: %s", json.dumps(result))
        return result

    changes = model.describe_changes(old_content, new_content)
    result["changes"] = changes
    if dry_run:
        return result

    snapshot = now.strftime("%Y-%m-%d")
    text = model.render(menu.document(snapshot))
    pr_url = gh.open_pr_for(BRANCH)
    if pr_url:
        gh.ensure_branch(BRANCH, base)  # keep the open PR's history, add a commit
    else:
        gh.reset_branch(BRANCH, base)  # fresh branch from main: the last PR was merged or closed
    gh.put_file(path, text, f"Fresha menu sync {snapshot}", BRANCH)
    if not pr_url:
        pr_url = gh.create_pr(BRANCH, base, f"Fresha menu sync {snapshot}", pr_body(changes, snapshot))
    result["pr_url"] = pr_url

    topic = env.get("OPS_TOPIC_ARN")
    if topic:
        subject, body = format_alert(changes, pr_url, snapshot)
        sns.publish(TopicArn=topic, Subject=subject[:100], Message=body)
    log.info("menu changed: %s", json.dumps(result))
    return result


def read_fresha(http, venue_url: str) -> model.Menu:
    team = fresha_public.fetch_team(http, venue_url)
    full = fresha_public.fetch_menu(http, venue_url)
    if not full:
        raise fresha_public.FreshaError("booking flow returned no service categories for the venue")
    per_person = {m.employee_id: fresha_public.fetch_menu(http, venue_url, m.employee_id) for m in team}
    return model.build_menu(venue_url, team, full, per_person)


def pr_body(changes: list[str], snapshot: str) -> str:
    lines = [
        f"Automated sync of the Fresha staff list and service menu, read {snapshot}.",
        "",
        "Changes:",
        *[f"- {c}" for c in changes],
        "",
        "Merging updates the bot's menu at the next deploy. If a change looks wrong,",
        "fix it in Fresha and this PR will update itself on the next run.",
    ]
    return "\n".join(lines)


def format_alert(changes: list[str], pr_url: str, snapshot: str) -> tuple[str, str]:
    subject = f"[TLG menu sync] {len(changes)} change(s) in Fresha, PR opened"
    body = "\n".join([f"Fresha menu read {snapshot} differs from the repo.", "", *changes, "", f"Review: {pr_url}"])
    return subject, body


def github_token(ssm, parameter: str) -> str:
    return ssm.get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"]


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
