"""Hand-overs to the team's Telegram group.

One bot (BotFather), one group with Jess, Carmen and Lori-Dee in it, the bot
added as an admin. Every hand-over is one message in the user's format:

    Nails: complaint: Danny Cooke: FB
    https://business.facebook.com/latest/inbox/all?asset_id=<page>

The bot token lives in Secrets Manager (TELEGRAM_SECRET_ARN). The group's
chat id is discovered once from the bot's update feed (someone has to have
said something in the group after the bot joined) and cached in an SSM
parameter (TELEGRAM_CHAT_ID_PARAM); TELEGRAM_CHAT_ID in the environment
overrides both. Everything here is best effort: a Telegram failure is
logged, never raised, because the email has already gone.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
UNSET = "unset"  # SSM strings cannot be empty; this stands for "not discovered yet"
GROUP_TYPES = ("group", "supergroup")


def post_handover(text: str, *, session=None) -> bool:
    """Send `text` to the team group. False (and a log line) when it could not."""
    token = bot_token()
    if not token:
        log.info("Telegram not configured; hand-over not posted")
        return False
    chat = chat_id(token, session=session)
    if not chat:
        log.warning("Telegram group not known yet: say something in the group so the bot can find it")
        return False
    return send_message(token, chat, text, session=session)


def send_message(token: str, chat_id: str, text: str, *, session=None) -> bool:
    import requests

    http = session or requests
    try:
        resp = http.post(
            API.format(token=token, method="sendMessage"),
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        if resp.status_code >= 400:
            log.warning("Telegram sendMessage failed %s: %s", resp.status_code, resp.text[:200])
            return False
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram sendMessage failed: %s", exc)
        return False
    return True


def discover_group_chat_id(token: str, *, session=None) -> str | None:
    """The most recent group the bot has seen in its update feed, or None.

    Telegram keeps undelivered updates for about a day, so this works when
    someone has spoken in the group recently; the result is cached so it
    only has to work once.
    """
    import requests

    http = session or requests
    try:
        resp = http.get(API.format(token=token, method="getUpdates"), params={"limit": 100, "timeout": 0}, timeout=10)
        updates = resp.json().get("result", []) if resp.status_code < 400 else []
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram getUpdates failed: %s", exc)
        return None
    found = None
    for update in updates:
        for key in ("message", "my_chat_member", "edited_message", "channel_post"):
            chat = (update.get(key) or {}).get("chat") or {}
            if chat.get("type") in GROUP_TYPES and chat.get("id") is not None:
                found = str(chat["id"])  # keep going: the latest wins
    return found


def chat_id(token: str, *, ssm=None, session=None) -> str | None:
    """Env override, then the cached SSM value, then discovery (cached on success)."""
    configured = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if configured and configured != UNSET:
        return configured
    param = os.environ.get("TELEGRAM_CHAT_ID_PARAM", "")
    client = ssm or (_ssm() if param else None)
    if param and client:
        try:
            value = client.get_parameter(Name=param)["Parameter"]["Value"].strip()
            if value and value != UNSET:
                return value
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not read %s: %s", param, exc)
    found = discover_group_chat_id(token, session=session)
    if found and param and client:
        try:
            client.put_parameter(Name=param, Value=found, Type="String", Overwrite=True)
            log.info("Telegram group discovered and cached: %s", found)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not cache the Telegram chat id: %s", exc)
    return found


@lru_cache(maxsize=1)
def bot_token() -> str:
    arn = os.environ.get("TELEGRAM_SECRET_ARN", "")
    if not arn:
        return ""
    import boto3

    try:
        raw = boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"]
        return json.loads(raw).get("bot_token", "")
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not read the Telegram token: %s", exc)
        return ""


@lru_cache(maxsize=1)
def _ssm():
    import boto3

    return boto3.client("ssm")
