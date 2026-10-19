"""Meta (Facebook Messenger + Instagram) webhook helpers.

Covers: verification handshake, payload signature check, flattening the
webhook body into simple inbound messages, and sending replies.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from typing import Iterable

log = logging.getLogger(__name__)

GRAPH_VERSION = os.environ.get("GRAPH_API_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


@dataclass(frozen=True)
class InboundMessage:
    channel: str  # "messenger" or "instagram"
    sender_id: str  # PSID (Messenger) or IGSID (Instagram)
    recipient_id: str  # the page / IG account id
    message_id: str
    text: str
    timestamp_ms: int


def verify_challenge(query: dict, verify_token: str) -> str | None:
    """Return the challenge string if Meta's GET verification is valid."""
    if query.get("hub.mode") == "subscribe" and query.get("hub.verify_token") == verify_token:
        return query.get("hub.challenge")
    return None


def verify_signature(raw_body: bytes, header_value: str | None, app_secret: str) -> bool:
    """Check X-Hub-Signature-256 against the raw request body."""
    if not header_value or not header_value.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value[len("sha256="):])


def parse_events(body: dict) -> list[InboundMessage]:
    """Flatten a webhook body into text messages we should answer.

    Skips echoes (our own outbound messages), deliveries, reads, reactions and
    anything without text. Attachments-only messages are returned with empty
    text so the caller can decide what to do.
    """
    obj = body.get("object")
    channel = {"page": "messenger", "instagram": "instagram"}.get(obj)
    if channel is None:
        return []

    out: list[InboundMessage] = []
    for entry in body.get("entry", []):
        for event in entry.get("messaging", []):
            msg = event.get("message")
            if not msg or msg.get("is_echo"):
                continue
            out.append(
                InboundMessage(
                    channel=channel,
                    sender_id=str(event["sender"]["id"]),
                    recipient_id=str(event["recipient"]["id"]),
                    message_id=str(msg.get("mid", "")),
                    text=(msg.get("text") or "").strip(),
                    timestamp_ms=int(event.get("timestamp", 0)),
                )
            )
    return out


def appsecret_proof(access_token: str, app_secret: str) -> str:
    """HMAC the token with the app secret. Meta's "Require app secret" setting
    rejects token calls that lack this, and it stops a leaked token being
    usable without the secret."""
    return hmac.new(app_secret.encode(), access_token.encode(), hashlib.sha256).hexdigest()


def send_text(recipient_id: str, text: str, page_token: str, *, app_secret: str | None = None, session=None) -> dict:
    """Send a plain text reply. Same endpoint serves Messenger and Instagram."""
    import requests  # local import keeps unit tests free of network deps

    http = session or requests
    params = {"access_token": page_token}
    if app_secret:
        params["appsecret_proof"] = appsecret_proof(page_token, app_secret)
    resp = http.post(
        f"{GRAPH_BASE}/me/messages",
        params=params,
        json={
            "recipient": {"id": recipient_id},
            "messaging_type": "RESPONSE",
            "message": {"text": text},
        },
        timeout=10,
    )
    if resp.status_code >= 400:
        log.error("Graph API send failed %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()
    return resp.json()


def chunk_text(text: str, limit: int = 1000) -> Iterable[str]:
    """Messenger caps messages at 2000 chars; keep ours well under that."""
    text = text.strip()
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        yield text[:cut].strip()
        text = text[cut:].strip()
    if text:
        yield text
