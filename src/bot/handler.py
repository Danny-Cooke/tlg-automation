"""Lambda entry point for the Meta webhook (API Gateway HTTP API, payload v2)."""
from __future__ import annotations

import base64
import json
import logging
import os
from functools import lru_cache

from . import brain, escalation, meta
from .config import SalonConfig, load_persona
from .prompt import build_system_prompt
from .state import ConversationStore

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Replies are drafted and escalated to Jess but never sent to the client.
SHADOW_MODE = os.environ.get("SHADOW_MODE", "true").lower() == "true"


@lru_cache(maxsize=1)
def secrets() -> dict:
    """Meta app secret, page token and verify token from Secrets Manager."""
    import boto3

    arn = os.environ["META_SECRET_ARN"]
    raw = boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"]
    return json.loads(raw)


@lru_cache(maxsize=1)
def system_prompt() -> str:
    return build_system_prompt(load_persona(), SalonConfig.from_env())


def lambda_handler(event: dict, context=None) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    if method == "GET":
        return _handle_verify(event)
    if method == "POST":
        return _handle_webhook(event)
    return _resp(405, "method not allowed")


def _handle_verify(event: dict) -> dict:
    challenge = meta.verify_challenge(event.get("queryStringParameters") or {}, secrets()["verify_token"])
    if challenge is None:
        return _resp(403, "verification failed")
    return _resp(200, challenge)


def _handle_webhook(event: dict, *, store: ConversationStore | None = None) -> dict:
    raw = event.get("body") or ""
    body_bytes = base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode()
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if not meta.verify_signature(body_bytes, headers.get("x-hub-signature-256"), secrets()["app_secret"]):
        log.warning("Bad webhook signature")
        return _resp(403, "bad signature")

    try:
        payload = json.loads(body_bytes)
    except ValueError:
        return _resp(400, "bad json")

    store = store or ConversationStore()
    for msg in meta.parse_events(payload):
        try:
            process_message(msg, store)
        except Exception:  # noqa: BLE001 - one bad thread must not fail the batch
            log.exception("Failed processing message %s", msg.message_id)
    # Always 200 so Meta does not retry; failures are logged and alarmed on.
    return _resp(200, "ok")


def process_message(msg: meta.InboundMessage, store: ConversationStore) -> None:
    convo = store.load(msg.sender_id)
    convo.channel = msg.channel
    if convo.has_seen(msg.message_id):
        log.info("Duplicate delivery %s, skipping", msg.message_id)
        return
    if convo.handed_to_jess:
        log.info("Thread %s is with Jess, staying quiet", msg.sender_id)
        convo.seen_message_ids.append(msg.message_id)
        store.save(convo)
        return
    if not msg.text:
        # Attachment-only message: let Jess see it rather than guess.
        reply = brain.BotReply(reply=brain.SAFE_REPLY, escalate=True, escalation_reason="Non-text message")
        user_text = "[attachment without text]"
    else:
        user_text = msg.text
        reply = brain.ask(system_prompt(), convo.history, user_text)

    convo.record_turn(msg.message_id, user_text, reply.reply)

    if reply.escalate:
        # In shadow mode nothing reaches the client, so keep drafting instead
        # of locking the thread.
        convo.handed_to_jess = not SHADOW_MODE
        escalation.notify(convo, reply.escalation_reason, user_text)

    if SHADOW_MODE:
        log.info("SHADOW reply to %s: %s", msg.sender_id, reply.reply)
        if not reply.escalate:
            escalation.notify(convo, f"Shadow mode draft: {reply.reply}", user_text)
    else:
        for chunk in meta.chunk_text(reply.reply):
            meta.send_text(msg.sender_id, chunk, secrets()["page_token"])

    store.save(convo)


def _resp(status: int, body: str) -> dict:
    return {"statusCode": status, "headers": {"content-type": "text/plain"}, "body": body}
