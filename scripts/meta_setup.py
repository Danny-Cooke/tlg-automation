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


def page_token_for(token: str, page_id: str, app_secret: str) -> str:
    """A System User token (the Instagram channel's) is not the Page; Meta
    gives out the Page's own token for it. A Page token comes back as is."""
    r = requests.get(
        f"{GRAPH}/{page_id}",
        params={"access_token": token, "appsecret_proof": appsecret_proof(token, app_secret), "fields": "access_token"},
        timeout=30,
    )
    if r.status_code >= 400 or not r.json().get("access_token"):
        return token
    if r.json()["access_token"] != token:
        print("ok: swapped the stored token for the Page's own token")
    return r.json()["access_token"]


def token_page(page_token: str, app_secret: str) -> dict:
    """Which Page the token belongs to, if the token may say (needs
    pages_read_engagement, which a Messenger-only token lacks). Best effort."""
    r = requests.get(
        f"{GRAPH}/me",
        params={"access_token": page_token, "appsecret_proof": appsecret_proof(page_token, app_secret), "fields": "id,name"},
        timeout=30,
    )
    if r.status_code >= 400:
        print(f"note: the token cannot read its Page's name ({r.json().get('error', {}).get('message', '')[:80]}); carrying on")
        return {}
    return r.json()


def subscribe_page(page_id: str, page_token: str, app_secret: str, fields: list[str]) -> bool:
    """Subscribe the token's own Page to the app. A Page token addresses its
    Page as "me". Returns False (with a warning, not a failure) when the token
    lacks pages_manage_metadata; the console can do it instead."""
    me = token_page(page_token, app_secret)
    if me.get("id") and str(me["id"]) != str(page_id):
        print(f"warning: the token is for Page {me['id']} ({me.get('name')}), not {page_id}; subscribing the token's Page")
    r = requests.post(
        f"{GRAPH}/me/subscribed_apps",
        params={"access_token": page_token, "appsecret_proof": appsecret_proof(page_token, app_secret)},
        data={"subscribed_fields": ",".join(fields)},
        timeout=30,
    )
    if r.status_code >= 400:
        print(
            f"::warning::Could not subscribe the Page to the app with this token: {r.status_code} {r.text[:200]}. "
            "Do it in the Meta console: the app > Messenger > Messenger API settings > Webhooks > "
            "Add subscriptions next to the Page > tick messages. Until then Meta delivers nothing."
        )
        return False
    print(f"ok: subscribe Page {me.get('name') or page_id} to app: {r.json()}")
    return True


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
        page_token = page_token_for(a.page_token, a.page_id, a.app_secret)
        subscribed = subscribe_page(a.page_id, page_token, a.app_secret, spec["fields"])
        if a.channel == "instagram":
            ig = linked_instagram(a.page_id, page_token, a.app_secret)
            print(f"Linked Instagram: {ig or 'none. Link the IG professional account to the Page in Business Settings.'}")
    else:
        print("No page token given: subscribe the Page to this app in the console (Webhooks > Add subscriptions).")


if __name__ == "__main__":
    main()
