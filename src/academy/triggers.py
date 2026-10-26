"""Cognito post-confirmation trigger: an email listed in ADMIN_EMAILS joins the
admins group the moment it registers, so Jess's account needs no manual step."""
from __future__ import annotations

import logging
import os
from functools import lru_cache

import boto3

log = logging.getLogger("academy.triggers")
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


@lru_cache(maxsize=1)
def _idp():
    return boto3.client("cognito-idp")


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}


def post_confirmation(event: dict, context=None, idp=None) -> dict:
    attrs = event.get("request", {}).get("userAttributes", {}) or {}
    email = attrs.get("email", "").lower()
    if email and email in admin_emails():
        (idp or _idp()).admin_add_user_to_group(
            UserPoolId=event["userPoolId"], Username=event["userName"], GroupName=os.environ.get("ADMIN_GROUP", "admins"))
        log.info("ACADEMY admin registered: %s", email)
    return event
