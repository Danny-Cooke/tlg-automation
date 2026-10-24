"""Lambda behind the stop link in every marketing text: `/stop/<token>`.

The text carries `tlg-beauty.co.uk/stop/<token>`; the salon's website
redirects `/stop/*` to this route on the API (docs/setup.md 6), which keeps
the link short without a second domain in AWS.

GET shows a page with one button. The button POSTs, and only the POST changes
anything, so a phone's link preview or a carrier's link scanner fetching the
URL cannot opt anyone out. After stopping, the page offers "Get offers
again", which POSTs the other way. An unknown token is a plain 404 page.
Nothing here needs Fresha: the change is recorded on the row and carried
into Fresha by the sync once that call is known.
"""
from __future__ import annotations

import base64
import html
import logging
import os
from urllib.parse import parse_qs

from .store import ClientStore

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

ACTIONS = {"stop": True, "start": False}


def lambda_handler(event: dict, context=None, *, store: ClientStore | None = None) -> dict:
    method = (event.get("requestContext", {}).get("http", {}).get("method") or "GET").upper()
    token = ((event.get("pathParameters") or {}).get("token") or "").strip().lower()
    if method == "HEAD":  # link previews
        return _resp(200, "")
    store = store or ClientStore()
    row = store.by_token(token) if token else None
    if row is None:
        return _resp(404, page("This link isn't valid", "It may have been typed wrongly. Message the salon and we'll sort it."))
    first = html.escape((row.get("first_name") or row.get("name") or "").split(" ")[0])
    hi = f"Hi {first}" if first else "Hi"
    if method == "POST":
        action = _form(event).get("action", [""])[0]
        if action not in ACTIONS:
            return _resp(400, page("Something went wrong", "Please go back and try again."))
        store.set_opt_out(row["client_id"], ACTIONS[action], source="link")
        log.info("Opt-out %s for client %s via link", action, row["client_id"])
        if action == "stop":
            return _resp(200, page(f"Done, {first}" if first else "Done", f"You won't get offer texts from {salon()} any more.",
                                   button="Get offers again", action="start"))
        return _resp(200, page(f"Welcome back, {first}" if first else "Welcome back", f"You'll hear about {salon()} offers by text again.",
                               button="Stop texts", action="stop"))
    if row.get("sms_opt_out"):
        return _resp(200, page(hi, f"You're not getting offer texts from {salon()}.", button="Get offers again", action="start"))
    return _resp(200, page(hi, f"Stop offer texts from {salon()}? Appointment reminders are separate and carry on.",
                           button="Stop texts", action="stop"))


def salon() -> str:
    return os.environ.get("SALON_NAME", "The Looking Glass")


def page(title: str, body: str, *, button: str = "", action: str = "") -> str:
    form = ""
    if button:
        form = (f'<form method="post"><input type="hidden" name="action" value="{html.escape(action)}">'
                f'<button type="submit">{html.escape(button)}</button></form>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>{html.escape(title)} - {html.escape(salon())}</title>
<style>body{{font-family:-apple-system,system-ui,sans-serif;background:#faf7f5;color:#222;margin:0;padding:48px 20px;text-align:center}}
main{{max-width:420px;margin:0 auto}}h1{{font-weight:600;font-size:1.5rem}}p{{line-height:1.5;color:#444}}
button{{margin-top:20px;padding:14px 28px;font-size:1rem;border:0;border-radius:999px;background:#222;color:#fff}}</style></head>
<body><main><h1>{html.escape(title)}</h1><p>{html.escape(body)}</p>{form}<p style="margin-top:40px;font-size:.85rem;color:#888">{html.escape(salon())}</p></main></body></html>"""


def _form(event: dict) -> dict[str, list[str]]:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8", "replace")
    return parse_qs(raw)


def _resp(status: int, body: str) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "text/html; charset=utf-8", "cache-control": "no-store"},
        "body": body,
    }
