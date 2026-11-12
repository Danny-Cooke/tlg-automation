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
# Messenger talks to graph.facebook.com with a Page token. Instagram, since
# plan job 18 (2026-10-27), talks to graph.instagram.com with the salon
# account's own token ("Instagram API with Instagram Login"): no Facebook
# Page in the path, and Standard Access reaches the public, so no App Review.
GRAPH_HOST = os.environ.get("META_GRAPH_HOST", "graph.facebook.com")
GRAPH_BASE = f"https://{GRAPH_HOST}/{GRAPH_VERSION}"
# appsecret_proof is a graph.facebook.com thing ("Require app secret" in the
# app's Advanced settings). graph.instagram.com is not documented to take it.
PROOF_HOSTS = frozenset({"graph.facebook.com"})


@dataclass(frozen=True)
class InboundMessage:
    channel: str  # "messenger" or "instagram"
    sender_id: str  # PSID (Messenger) or IGSID (Instagram)
    recipient_id: str  # the page / IG account id
    message_id: str
    text: str
    timestamp_ms: int
    attachments: int = 0  # pictures, videos, files that came with it; the bot cannot see them
    image_urls: tuple[str, ...] = ()  # Meta's links to the pictures among them, read only to name the area for the team


def verify_challenge(query: dict, verify_token: str) -> str | None:
    """Return the challenge string if Meta's GET verification is valid."""
    if query.get("hub.mode") == "subscribe" and query.get("hub.verify_token") == verify_token:
        return query.get("hub.challenge")
    return None


def verify_signature(raw_body: bytes, header_value: str | None, app_secret: str, *fallback_secrets: str) -> bool:
    """Check X-Hub-Signature-256 against the raw request body.

    Any of the secrets may have signed it: on the Instagram Login route Meta
    documents the Instagram app secret, and the Facebook app secret of the
    same app is kept as a fallback until a real delivery shows which one
    Meta uses (plan job 18)."""
    if not header_value or not header_value.startswith("sha256="):
        return False
    given = header_value[len("sha256="):]
    for secret in (app_secret, *fallback_secrets):
        if not secret:
            continue
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, given):
            return True
    return False


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
                    attachments=len(msg.get("attachments") or []),
                    image_urls=tuple(
                        str(a["payload"]["url"]) for a in (msg.get("attachments") or [])
                        if isinstance(a, dict) and a.get("type") == "image" and (a.get("payload") or {}).get("url")
                    ),
                )
            )
    return out


IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
MAX_IMAGE_BYTES = 3_500_000  # the Claude API takes 5 MB an image, measured after base64 (a third bigger)
MAX_IMAGES = 2


def fetch_images(urls: Iterable[str], *, session=None) -> list[tuple[str, str]]:
    """The pictures a client sent, as (media type, base64) pairs for Claude.

    Meta's attachment links are signed and open without a token. Best
    effort: a picture that will not download, is too big or is not a picture
    type Claude reads is left out, and the caller carries on without it."""
    import base64

    import requests

    http = session or requests
    out: list[tuple[str, str]] = []
    for url in list(urls)[:MAX_IMAGES]:
        try:
            resp = http.get(url, timeout=5)
            kind = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            if resp.status_code >= 400 or kind not in IMAGE_TYPES or len(resp.content) > MAX_IMAGE_BYTES:
                log.info("Picture not read (%s, %s, %d bytes)", resp.status_code, kind or "no type", len(resp.content))
                continue
            out.append((kind, base64.standard_b64encode(resp.content).decode()))
        except Exception as exc:  # noqa: BLE001
            log.warning("Picture download failed: %s", exc)
    return out


def appsecret_proof(access_token: str, app_secret: str) -> str:
    """HMAC the token with the app secret. Meta's "Require app secret" setting
    rejects token calls that lack this, and it stops a leaked token being
    usable without the secret."""
    return hmac.new(app_secret.encode(), access_token.encode(), hashlib.sha256).hexdigest()


def token_params(access_token: str, app_secret: str | None = None, **extra) -> dict:
    """Query parameters for a token call: the token, the proof where the host takes one, and `extra`."""
    params = {"access_token": access_token, **extra}
    if app_secret and GRAPH_HOST in PROOF_HOSTS:
        params["appsecret_proof"] = appsecret_proof(access_token, app_secret)
    return params


def page_token_for(token: str, page_id: str, *, app_secret: str | None = None, session=None) -> str:
    """A token the Page's "me" endpoints accept.

    A Page token comes back unchanged. A System User token (Business
    Settings, never expires; the Instagram channel's since 2026-10-25) is
    not the Page: to Meta its "me" is the system user, so /me/messages
    fails. Meta hands out the Page's own token for it, GET
    /{page_id}?fields=access_token, which carries the same permissions and
    never expires either. Anything that goes wrong returns the token as
    given, so a bad exchange changes nothing for a Page token.
    """
    if not token or not page_id:
        return token
    import requests

    http = session or requests
    try:
        resp = http.get(f"{GRAPH_BASE}/{page_id}", params=token_params(token, app_secret, fields="access_token"), timeout=10)
        if resp.status_code >= 400:
            log.info("Page token exchange not available (%s); using the token as given", resp.status_code)
            return token
        exchanged = resp.json().get("access_token") or token
    except Exception as exc:  # noqa: BLE001
        log.warning("Page token exchange failed: %s", exc)
        return token
    if exchanged != token:
        log.info("Using the Page token Meta issued for the stored token")
    return exchanged


def send_text(recipient_id: str, text: str, page_token: str, *, app_secret: str | None = None, session=None) -> dict:
    """Send a plain text reply. Same endpoint serves Messenger and Instagram."""
    import requests  # local import keeps unit tests free of network deps

    http = session or requests
    resp = http.post(
        f"{GRAPH_BASE}/me/messages",
        params=token_params(page_token, app_secret),
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


PROFILE_FIELDS = {
    "messenger": "first_name,last_name,name",  # asking Messenger for username is an error (#12)
    "instagram": "name,username",
}


def user_profile(sender_id: str, page_token: str, *, channel: str = "messenger", app_secret: str | None = None, session=None) -> dict:
    """The sender's name from Meta's User Profile API, best effort.

    Messenger returns first_name and last_name with the Page token only for
    people with a role on the Meta app (it worked for us on 2026-10-20); for
    the public it has answered 400 (error 100, subcode 33) on every lookup
    since 2026-10-26. So on Messenger a refused or empty lookup falls back
    to the Page's own conversation with them (`conversation_name`), which
    does carry the name; the hand-over shows a snippet of their message
    only when that fails too (`escalation.who_for_team`). Instagram needs
    instagram_manage_messages and returns name and username. Anything that
    goes wrong gives {} so a missing name never blocks a reply.
    """
    import requests

    http = session or requests
    params = token_params(page_token, app_secret, fields=PROFILE_FIELDS.get(channel, PROFILE_FIELDS["messenger"]))
    data: dict = {}
    try:
        resp = http.get(f"{GRAPH_BASE}/{sender_id}", params=params, timeout=10)
        if resp.status_code >= 400:
            log.info("User profile for %s refused %s: %s", sender_id, resp.status_code, resp.text[:120])
        else:
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("User profile for %s failed: %s", sender_id, exc)
    profile = {k: v for k, v in data.items() if k in ("first_name", "last_name", "name", "username") and v}
    if not profile and channel == "messenger":
        name = conversation_name(sender_id, page_token, app_secret=app_secret, session=http)
        if name:
            profile = {"name": name}
    return profile


def conversation_name(sender_id: str, page_token: str, *, app_secret: str | None = None, session=None) -> str:
    """The client's name as the Page's inbox shows it, or "".

    GET /me/conversations?user_id={PSID}&fields=participants lists the two
    sides of the Page's thread with that person, each with a name. It
    answers for the public with the Page token at Standard Access (checked
    live 2026-11-11), where the User Profile API does not. Never raises."""
    import requests

    http = session or requests
    params = token_params(page_token, app_secret, platform="messenger", user_id=sender_id, fields="participants")
    try:
        resp = http.get(f"{GRAPH_BASE}/me/conversations", params=params, timeout=10)
        if resp.status_code >= 400:
            log.warning("Conversation name for %s failed %s: %s", sender_id, resp.status_code, resp.text[:120])
            return ""
        for thread in resp.json().get("data") or []:
            for person in (thread.get("participants") or {}).get("data") or []:
                if str(person.get("id")) == str(sender_id) and person.get("name"):
                    return str(person["name"])
    except Exception as exc:  # noqa: BLE001
        log.warning("Conversation name for %s failed: %s", sender_id, exc)
    return ""


def display_name(profile: dict) -> str:
    """'Danny Cooke', or the Instagram name or username, or ''."""
    first, last = profile.get("first_name", ""), profile.get("last_name", "")
    if first:
        return f"{first} {last}".strip()
    return profile.get("name") or profile.get("username") or ""


def send_action(recipient_id: str, action: str, page_token: str, *, app_secret: str | None = None, session=None) -> None:
    """typing_on, typing_off or mark_seen. Best effort: a failure here must not stop the reply."""
    import requests

    http = session or requests
    try:
        resp = http.post(
            f"{GRAPH_BASE}/me/messages",
            params=token_params(page_token, app_secret),
            json={"recipient": {"id": recipient_id}, "sender_action": action},
            timeout=10,
        )
        if resp.status_code >= 400:
            log.warning("sender_action %s failed %s: %s", action, resp.status_code, resp.text[:120])
    except Exception as exc:  # noqa: BLE001
        log.warning("sender_action %s failed: %s", action, exc)


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
