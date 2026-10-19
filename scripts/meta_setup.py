"""One-off Meta wiring that can be done over the Graph API, no browser needed.

Prerequisites you must get from the Meta developer console once (there is no
API for these):
  - App ID and App Secret        (App settings > Basic)
  - A Page access token           (Messenger > API setup, or a System User
                                   token in Business Settings)

Then run:

  python scripts/meta_setup.py \
      --app-id 123 --app-secret ... --page-id 456 --page-token ... \
      --callback-url https://xxxx.execute-api.eu-west-2.amazonaws.com/webhook \
      --verify-token $(cd terraform && terraform output -raw webhook_verify_token)

What it does:
  1. Registers the webhook callback for the "page" and "instagram" objects on
     the app and subscribes to the messages fields. Meta calls GET on the
     callback during this step, so the Lambda must already be deployed.
  2. Subscribes the Page to the app so message events are delivered.
  3. Prints the Instagram account linked to the Page, if any.
"""
from __future__ import annotations

import argparse
import sys

import requests

GRAPH = "https://graph.facebook.com/v21.0"


def app_access_token(app_id: str, app_secret: str) -> str:
    return f"{app_id}|{app_secret}"


def subscribe_app(app_id: str, app_token: str, obj: str, fields: list[str], callback: str, verify: str) -> None:
    r = requests.post(
        f"{GRAPH}/{app_id}/subscriptions",
        params={"access_token": app_token},
        data={
            "object": obj,
            "callback_url": callback,
            "fields": ",".join(fields),
            "verify_token": verify,
            "include_values": "true",
        },
        timeout=30,
    )
    _check(r, f"subscribe app to {obj}")


def subscribe_page(page_id: str, page_token: str, fields: list[str]) -> None:
    r = requests.post(
        f"{GRAPH}/{page_id}/subscribed_apps",
        params={"access_token": page_token},
        data={"subscribed_fields": ",".join(fields)},
        timeout=30,
    )
    _check(r, "subscribe page to app")


def linked_instagram(page_id: str, page_token: str) -> str | None:
    r = requests.get(
        f"{GRAPH}/{page_id}",
        params={"access_token": page_token, "fields": "instagram_business_account{id,username}"},
        timeout=30,
    )
    _check(r, "read linked Instagram account")
    ig = r.json().get("instagram_business_account")
    return f"{ig['username']} ({ig['id']})" if ig else None


def _check(r: requests.Response, what: str) -> None:
    if r.status_code >= 400:
        sys.exit(f"{what} failed: {r.status_code} {r.text}")
    print(f"ok: {what}: {r.json()}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--app-id", required=True)
    p.add_argument("--app-secret", required=True)
    p.add_argument("--page-id", required=True)
    p.add_argument("--page-token", required=True)
    p.add_argument("--callback-url", required=True)
    p.add_argument("--verify-token", required=True)
    a = p.parse_args()

    app_token = app_access_token(a.app_id, a.app_secret)
    page_fields = ["messages", "messaging_postbacks", "message_deliveries", "message_reads"]
    ig_fields = ["messages"]

    subscribe_app(a.app_id, app_token, "page", page_fields, a.callback_url, a.verify_token)
    subscribe_app(a.app_id, app_token, "instagram", ig_fields, a.callback_url, a.verify_token)
    subscribe_page(a.page_id, a.page_token, page_fields)

    ig = linked_instagram(a.page_id, a.page_token)
    print(f"Linked Instagram: {ig or 'none. Link the IG professional account to the Page in Business Settings.'}")


if __name__ == "__main__":
    main()
