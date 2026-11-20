"""Plain-text emails to a learner and to the school, through SES. Best effort:
with no SENDER_EMAIL set, or if SES refuses, the order and the booking still
stand and the learner still has the page in front of them."""
from __future__ import annotations

import logging
import os
from functools import lru_cache

log = logging.getLogger("academy.mailer")


@lru_cache(maxsize=1)
def _ses():
    import boto3

    return boto3.client("sesv2")


def send(to: str, subject: str, body: str, *, ses=None) -> bool:
    sender = os.environ.get("SENDER_EMAIL", "").strip()
    if not sender or not to:
        log.info("EMAIL not sent (no sender or no recipient): %s", subject)
        return False
    try:
        (ses or _ses()).send_email(
            FromEmailAddress=f"The Looking Glass Beauty School <{sender}>",
            Destination={"ToAddresses": [to]},
            ReplyToAddresses=[os.environ.get("CONTACT_EMAIL", "").strip() or sender],
            Content={"Simple": {"Subject": {"Data": subject[:200]}, "Body": {"Text": {"Data": body}}}},
        )
        return True
    except Exception:  # noqa: BLE001 - an email must never undo a payment or a booking
        log.exception("EMAIL failed: %s", subject)
        return False


def school(subject: str, body: str, *, ses=None) -> bool:
    return send(os.environ.get("CONTACT_EMAIL", "").strip(), subject, body, ses=ses)
