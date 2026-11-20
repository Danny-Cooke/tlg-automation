"""Give the academy shop its Stripe keys (plan job 21). Run by the Academy
workflow after terraform apply; safe to run again.

    STRIPE_SECRET_KEY   the Stripe secret key (GitHub secret TLG_ACADEMY_STRIPE_SECRET_KEY); sk_test_... is the sandbox
    --secret-arn        the Secrets Manager secret the Lambda reads (terraform output stripe_secret_arn)
    --webhook-url       where Stripe should send payment events (terraform output stripe_webhook_url)

It makes sure the secret has an admin_key (the long random key in the
school's private course-dates link; made once and then kept), that Stripe has
exactly one webhook endpoint for that URL, and that the secret holds
{"secret_key", "webhook_secret", "webhook_id", "admin_key"}. Stripe shows a
webhook's signing secret only when the endpoint is created, so if the stored
one is missing, or belongs to a different key, the endpoint is replaced.
Nothing secret is printed; scripts/academy_admin_link.py prints the link.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from academy import stripe_api  # noqa: E402

EVENTS = ["checkout.session.completed", "checkout.session.async_payment_succeeded"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secret-arn", required=True)
    ap.add_argument("--webhook-url", required=True)
    args = ap.parse_args()
    import boto3

    sm = boto3.client("secretsmanager")
    try:
        held = json.loads(sm.get_secret_value(SecretId=args.secret_arn)["SecretString"] or "{}")
    except sm.exceptions.ResourceNotFoundException:
        held = {}
    if not held.get("admin_key"):
        held["admin_key"] = secrets.token_urlsafe(32)
        sm.put_secret_value(SecretId=args.secret_arn, SecretString=json.dumps(held))
        print("Course-dates page key created.")

    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not key:
        print("STRIPE_SECRET_KEY is not set; the buy buttons stay switched off.")
        return 0
    if not key.startswith(("sk_test_", "sk_live_", "rk_test_", "rk_live_")):
        print("STRIPE_SECRET_KEY does not look like a Stripe secret key.")
        return 1
    mode = "sandbox" if "_test_" in key else "LIVE"

    endpoints = [e for e in stripe_api.request("GET", "/webhook_endpoints", {"limit": 100}, key=key)["data"] if e["url"] == args.webhook_url]
    keep = held.get("secret_key") == key and held.get("webhook_secret") and held.get("webhook_id") in {e["id"] for e in endpoints}
    if keep and len(endpoints) == 1 and sorted(endpoints[0]["enabled_events"]) == sorted(EVENTS) and endpoints[0]["status"] == "enabled":
        print(f"Stripe ({mode}): webhook already in place, keys unchanged.")
        return 0

    for e in endpoints:
        stripe_api.request("DELETE", f"/webhook_endpoints/{e['id']}", key=key)
    made = stripe_api.request("POST", "/webhook_endpoints", {
        "url": args.webhook_url, "enabled_events": EVENTS, "description": "TLG Academy shop: paid course orders"}, key=key)
    sm.put_secret_value(SecretId=args.secret_arn, SecretString=json.dumps(
        {**held, "secret_key": key, "webhook_secret": made["secret"], "webhook_id": made["id"]}))
    print(f"Stripe ({mode}): webhook registered for {args.webhook_url}; keys stored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
