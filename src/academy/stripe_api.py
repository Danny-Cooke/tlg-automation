"""The three things the shop needs from Stripe, over plain HTTPS so the Lambda
bundle stays dependency-free: create a Checkout session, read one back, and
check a webhook's signature.

The secret key and the webhook signing secret live in one Secrets Manager
secret (STRIPE_SECRET_ARN) as {"secret_key": ..., "webhook_secret": ...},
written by scripts/academy_stripe_setup.py in the deploy workflow. A key
starting sk_test_ is Stripe's sandbox: nothing is charged."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

API = "https://api.stripe.com/v1"
TOLERANCE_SECONDS = 300


class StripeError(Exception):
    pass


class NotConfigured(StripeError):
    pass


SECRET_TTL_SECONDS = 300
_held: tuple[float, dict] = (0.0, {})


@lru_cache(maxsize=1)
def _sm():
    import boto3

    return boto3.client("secretsmanager")


def shop_secret() -> dict:
    """Everything in the shop's secret: secret_key, webhook_secret, webhook_id, admin_key. {} if not set up.
    The workflow writes it after the Lambda is deployed and the admin key can be replaced, so a complete
    answer is kept for five minutes and an incomplete one is not kept at all."""
    global _held
    arn = os.environ.get("STRIPE_SECRET_ARN", "")
    if not arn:
        return {}
    at, held = _held
    if held and time.time() - at < SECRET_TTL_SECONDS:
        return held
    try:
        held = json.loads(_sm().get_secret_value(SecretId=arn)["SecretString"] or "{}")
    except Exception:  # noqa: BLE001 - an empty secret is "not set up yet", not a crash
        return {}
    if all(held.get(k) for k in ("secret_key", "webhook_secret", "admin_key")):
        _held = (time.time(), held)
    return held


def secrets() -> dict:
    held = shop_secret()
    if not held.get("secret_key"):
        raise NotConfigured("the Stripe secret has no secret_key")
    return held


def flatten(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's form encoding: {"a": {"b": 1}, "c": [{"d": 2}]} -> a[b]=1, c[0][d]=2."""
    out: list[tuple[str, str]] = []
    for k, v in data.items():
        key = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, dict):
            out += flatten(v, key)
        elif isinstance(v, (list, tuple)):
            for i, item in enumerate(v):
                out += flatten(item, f"{key}[{i}]") if isinstance(item, dict) else [(f"{key}[{i}]", str(item))]
        elif isinstance(v, bool):
            out.append((key, "true" if v else "false"))
        elif v is not None:
            out.append((key, str(v)))
    return out


def request(method: str, path: str, data: dict | None = None, *, key: str | None = None, opener=None) -> dict:
    key = key or secrets()["secret_key"]
    body = urllib.parse.urlencode(flatten(data)).encode() if data else None
    url = API + path
    if method == "GET" and body:
        url, body = f"{url}?{body.decode()}", None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/x-www-form-urlencoded", "Stripe-Version": "2024-06-20"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=12) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read()).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            message = ""
        raise StripeError(f"Stripe said {exc.code}: {message}") from None
    except urllib.error.URLError as exc:
        raise StripeError(f"Stripe could not be reached: {exc.reason}") from None


def create_checkout(*, course_id: str, title: str, amount_pence: int, token: str, success_url: str, cancel_url: str,
                    terms: str = "", places: int = 1, **kw) -> dict:
    """One course, one place, paid in full. No payment_method_types: Stripe
    shows whatever is switched on in the dashboard for this buyer and amount,
    which is where Klarna comes from."""
    meta = {"course_id": course_id, "token": token, "source": "tlg-academy"}
    data = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": token,
        "line_items": [{"quantity": 1, "price_data": {
            "currency": "gbp", "unit_amount": int(amount_pence),
            "product_data": {"name": title, "description": (
                "One place on the taught day at The Looking Glass Beauty School, Shrewsbury. You choose your date after paying."
                if places == 1 else
                "One place on each course's taught day at The Looking Glass Beauty School, Shrewsbury. You choose a date for each after paying.")}}}],
        "phone_number_collection": {"enabled": True},
        "billing_address_collection": "auto",
        "metadata": meta,
        "payment_intent_data": {"metadata": meta, "description": title},
    }
    if terms:
        data["custom_text"] = {"submit": {"message": terms[:1100]}}
    return request("POST", "/checkout/sessions", data, **kw)


def get_checkout(checkout_id: str, **kw) -> dict:
    return request("GET", f"/checkout/sessions/{urllib.parse.quote(checkout_id, safe='')}", **kw)


def verify_webhook(payload: bytes, header: str, secret: str, now: float | None = None) -> dict:
    """The event, if `Stripe-Signature` is a current signature of this exact body."""
    parts = [p.split("=", 1) for p in (header or "").split(",") if "=" in p]
    stamp = next((v for k, v in parts if k.strip() == "t"), "")
    given = [v for k, v in parts if k.strip() == "v1"]
    if not stamp.isdigit() or not given or not secret:
        raise StripeError("no usable signature")
    if abs((now or time.time()) - int(stamp)) > TOLERANCE_SECONDS:
        raise StripeError("signature too old")
    expected = hmac.new(secret.encode(), stamp.encode() + b"." + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, g) for g in given):
        raise StripeError("signature does not match")
    return json.loads(payload)
