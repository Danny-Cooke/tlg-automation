"""Register one channel's webhook with its Meta app, over the Graph API.

There are two Meta apps, one per channel, and two Lambdas behind one API:

  Tlg-app1  messenger   object "page"       callback .../webhook/messenger
  Tlg-app2  instagram   object "instagram"  callback .../webhook/instagram

Run once per channel after `terraform apply` of the bot stack (Meta calls
GET on the callback during registration, so the Lambda must exist):

  cd terraform
  python ../scripts/meta_setup.py --channel messenger \
      --app-id <Tlg-app1 id> --app-secret <Tlg-app1 secret> \
      --callback-url "$(terraform output -json webhook_urls | jq -r .messenger)" \
      --verify-token "$(terraform output -json webhook_verify_tokens | jq -r .messenger)" \
      [--page-id <page id> --page-token <page token>]

What it does:
  1. Subscribes the app to the channel's webhook object with the messages
     fields, pointing at the callback. Uses the app access token
     (id|secret), which needs no appsecret_proof.
  2. With --page-id and --page-token: subscribes the Page to the app so
     Meta actually delivers its messages, and for instagram prints the
     linked Instagram account. Token calls carry appsecret_proof, so the
     app's "Require app secret" setting can stay on. Without a token, do
     this step in the console: Messenger (or Instagram) > Settings >
     Webhooks > Add subscriptions on the Page.

Prerequisites from the Meta developer console (no API for these): the App
ID and App Secret (Settings > Basic); a Page access token (Messenger >
API setup > Generate token, or a System User token).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import sys

import requests

GRAPH = "https://graph.facebook.com/v21.0"

CHANNELS = {
    "messenger": {"object": "page", "fields": ["messages", "messaging_postbacks"]},
    "instagram": {"object": "instagram", "fields": ["messages"]},
}


def app_access_token(app_id: str, app_secret: str) -> str:
    return f"{app_id}|{app_secret}"


def appsecret_proof(token: str, app_secret: str) -> str:
    return hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


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
    _check(r, f"subscribe app to {obj} webhooks at {callback}")


def token_page(page_token: str, app_secret: str) -> dict:
    """Which Page the token belongs to. A Page token addresses its own Page as
    "me", which is more reliable than naming the id."""
    r = requests.get(
        f"{GRAPH}/me",
        params={"access_token": page_token, "appsecret_proof": appsecret_proof(page_token, app_secret), "fields": "id,name"},
        timeout=30,
    )
    _check(r, "read the token's Page")
    return r.json()


def subscribe_page(page_id: str, page_token: str, app_secret: str, fields: list[str]) -> None:
    me = token_page(page_token, app_secret)
    if str(me.get("id")) != str(page_id):
        print(f"warning: the token is for Page {me.get('id')} ({me.get('name')}), not {page_id}; subscribing the token's Page")
    r = requests.post(
        f"{GRAPH}/me/subscribed_apps",
        params={"access_token": page_token, "appsecret_proof": appsecret_proof(page_token, app_secret)},
        data={"subscribed_fields": ",".join(fields)},
        timeout=30,
    )
    _check(r, f"subscribe Page {me.get('name')} to app")


def linked_instagram(page_id: str, page_token: str, app_secret: str) -> str | None:
    r = requests.get(
        f"{GRAPH}/me",
        params={
            "access_token": page_token,
            "appsecret_proof": appsecret_proof(page_token, app_secret),
            "fields": "instagram_business_account{id,username}",
        },
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
    p.add_argument("--channel", required=True, choices=sorted(CHANNELS))
    p.add_argument("--app-id", required=True)
    p.add_argument("--app-secret", required=True)
    p.add_argument("--callback-url", required=True)
    p.add_argument("--verify-token", required=True)
    p.add_argument("--page-id")
    p.add_argument("--page-token")
    a = p.parse_args()

    spec = CHANNELS[a.channel]
    if not a.callback_url.rstrip("/").endswith(f"/webhook/{a.channel}"):
        sys.exit(f"callback for {a.channel} should end with /webhook/{a.channel}: {a.callback_url}")

    subscribe_app(a.app_id, app_access_token(a.app_id, a.app_secret), spec["object"], spec["fields"], a.callback_url, a.verify_token)

    if a.page_id and a.page_token:
        subscribe_page(a.page_id, a.page_token, a.app_secret, spec["fields"])
        if a.channel == "instagram":
            ig = linked_instagram(a.page_id, a.page_token, a.app_secret)
            print(f"Linked Instagram: {ig or 'none. Link the IG professional account to the Page in Business Settings.'}")
    else:
        print("No page token given: subscribe the Page to this app in the console (Webhooks > Add subscriptions).")


if __name__ == "__main__":
    main()
