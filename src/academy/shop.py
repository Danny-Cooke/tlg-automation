"""The academy shop (plan job 21): buy a place on a course, pay through Stripe
Checkout (card, wallets, Klarna), then choose a date; and the course-dates
calendar the school's administrators keep.

Nobody logs in (user, 2026-11-20: "pick a course and purchase it from there. no
portal login for anyone"). The buyer's pages sit on the main website's academy
page; this is the API behind them:

  GET  /shop/courses                         every course on sale: price and the open dates with places left
  POST /shop/courses/{course_id}/checkout    {"confirm": true} -> {"url": Stripe's payment page}
  GET  /shop/orders/{token}?cs=<checkout id> the order, and the dates it may choose from
  POST /shop/orders/{token}/book             {"session": "<key>"}
  POST /shop/stripe/webhook                  Stripe's signed events

The school's course-dates page has no login either: it is opened with a
private link carrying a long random key, sent on each request as the
x-admin-key header and compared with admin_key in the shop's secret.

  GET  /shop/admin                           every date with who is on it, and every order
  POST /shop/admin                           {"action": add_date | update_date | book | release | cancel_order, ...}

An order exists only once Stripe says it is paid. Two things can say so: the
webhook, and the learner's own browser arriving back from Stripe with the
checkout id, which is looked up at Stripe, never trusted. Whichever comes
first writes the order; the other finds it there.

A course is on sale when courses.json gives it "shop": {"on_sale": true,
"price_pence": N}. "places" there is the default size of a new date.

Combined courses ("bundles" in courses.json) are one payment for two courses
at one price. A bundle is on sale only while every course in it is. Paying
for one makes an order per course, each with its own token and its own date
to choose; the buyer's link opens the first and shows the others."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import re
import secrets as pysecrets
import zoneinfo

from . import content, mailer, stripe_api
from .store import ShopError, ShopStore

log = logging.getLogger("academy.shop")
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

SALON_TZ = zoneinfo.ZoneInfo("Europe/London")
DEFAULT_PLACES = 4
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,80}$")


def _json(status: int, body) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "body": json.dumps(body, default=_plain)}


def _plain(v):
    from decimal import Decimal

    return int(v) if isinstance(v, Decimal) and v == v.to_integral_value() else str(v)


def today() -> str:
    return dt.datetime.now(SALON_TZ).date().isoformat()


def booking_url(token: str) -> str:
    """The buyer's own page on the main website: the link is the booking."""
    base = os.environ.get("SHOP_BOOKING_URL", "https://tlg-beauty.co.uk/academy/booking/")
    return f"{base}?order={token}"


def courses_url() -> str:
    return os.environ.get("SHOP_COURSES_URL", "https://tlg-beauty.co.uk/academy/")


def shop_of(course: dict | None) -> dict | None:
    """The course's shop block when it can actually be bought."""
    shop = (course or {}).get("shop") or {}
    if shop.get("on_sale") and isinstance(shop.get("price_pence"), int) and shop["price_pence"] > 0:
        return shop
    return None


def product(pid: str, *, even_if_off: bool = False) -> dict | None:
    """What a product id buys: {"id", "title", "price_pence", "courses": [ids]}. A course or a bundle.
    None when it is not on sale; `even_if_off` is for honouring a payment already taken."""
    course = content.course(pid)
    if course:
        shop = shop_of(course)
        if shop:
            return {"id": pid, "title": course["title"], "price_pence": shop["price_pence"], "courses": [pid]}
        price = (course.get("shop") or {}).get("price_pence")
        return {"id": pid, "title": course["title"], "price_pence": price or 0, "courses": [pid]} if even_if_off else None
    b = content.bundles().get(pid)
    if not b or not all(content.course(c) for c in b.get("courses", [])) or len(b.get("courses", [])) < 2:
        return None
    live = b.get("on_sale") and isinstance(b.get("price_pence"), int) and b["price_pence"] > 0 and all(shop_of(content.course(c)) for c in b["courses"])
    if live or even_if_off:
        return {"id": pid, "title": b["title"], "price_pence": b.get("price_pence") or 0, "courses": list(b["courses"])}
    return None


def exists(pid: str) -> bool:
    return bool(content.course(pid) or content.bundles().get(pid))


def order_tokens(token: str, courses: list[str]) -> list[str]:
    """One order per course. The first keeps the token in the buyer's link; the
    rest are derived from it, so a second delivery of the same payment lands on
    the same orders and nobody can guess one from a course name."""
    return [token] + [base64.urlsafe_b64encode(hashlib.sha256(f"{token}:{c}".encode()).digest()).decode().rstrip("=") for c in courses[1:]]


def split_amount(total: int, courses: list[str]) -> list[int]:
    """Share a bundle's price between its courses in proportion to their own prices; the pennies left over go on the last."""
    own = [int(((content.course(c) or {}).get("shop") or {}).get("price_pence") or 0) or 1 for c in courses]
    parts = [total * o // sum(own) for o in own]
    parts[-1] += total - sum(parts)
    return parts


def money(pence: int) -> str:
    return f"£{int(pence) / 100:,.2f}".replace(".00", "")


def nice_date(date: str) -> str:
    d = dt.date.fromisoformat(date)
    return f"{d:%A} {d.day} {d:%B %Y}"


def public_session(s: dict) -> dict:
    return {"key": s["SK"], "date": s["date"], "start": s["start"], "end": s["end"], "note": s.get("note", ""),
            "places_left": max(0, int(s["capacity"]) - int(s["taken"]))}


def open_sessions(store: ShopStore, course_id: str) -> list[dict]:
    return [public_session(s) for s in store.sessions(course_id)
            if s["status"] == "open" and s["date"] >= today() and int(s["taken"]) < int(s["capacity"])]


def public_order(store: ShopStore, order: dict) -> dict:
    course = content.course(order["course_id"]) or {}
    session = store.get_session(order["session_key"]) if order.get("session_key") else None
    out = {"course_id": order["course_id"], "course_title": course.get("title", order["course_id"]), "name": order.get("name", ""),
           "email": order.get("email", ""), "amount": int(order["amount"]), "status": order["status"], "paid_at": order["created_at"],
           "test": not order.get("livemode", False), "bundle_title": order.get("bundle_title", ""),
           "session": public_session(session) | {"status": session["status"]} if session else None}
    if order["status"] == "paid":
        out["sessions"] = open_sessions(store, order["course_id"])
    # Bought together: the other course's order, so one link reaches both.
    out["others"] = []
    for t in order.get("siblings", []):
        o = store.get_order(t)
        if o:
            s = store.get_session(o["session_key"]) if o.get("session_key") else None
            out["others"].append({"token": t, "course_title": (content.course(o["course_id"]) or {}).get("title", o["course_id"]),
                                  "status": o["status"], "date": s["date"] if s else "", "start": s["start"] if s else "", "end": s["end"] if s else ""})
    return out


# ---------------------------------------------------------------- paid orders
def fulfil(store: ShopStore, checkout: dict) -> dict | None:
    """Turn a paid Checkout session into an order (once). None if it is not ours or not paid."""
    meta = checkout.get("metadata") or {}
    token = meta.get("token") or ""
    bought = product(meta.get("course_id", ""), even_if_off=True)  # metadata "course_id" carries the product: a course or a bundle
    if meta.get("source") != "tlg-academy" or not _TOKEN.match(token) or not bought:
        return None
    if checkout.get("payment_status") != "paid":
        return None
    who = checkout.get("customer_details") or {}
    total = int(checkout.get("amount_total") or 0)
    courses = bought["courses"]
    tokens = order_tokens(token, courses)
    first, any_new = None, False
    for cid, tok, amount in zip(courses, tokens, split_amount(total, courses) if len(courses) > 1 else [total]):
        order, created = store.create_order(
            tok, course_id=cid, email=who.get("email") or "", name=who.get("name") or "", phone=who.get("phone") or "",
            amount=amount, currency=checkout.get("currency") or "gbp", checkout_id=checkout.get("id", ""),
            payment_intent=str(checkout.get("payment_intent") or ""), livemode=bool(checkout.get("livemode")),
            siblings=[t for t in tokens if t != tok], bundle_title=bought["title"] if len(courses) > 1 else "")
        first, any_new = first or order, any_new or created
    if any_new:
        title = bought["title"]
        days = "the date of your taught day" if len(courses) == 1 else "a date for each of your taught days"
        log.info("SHOP paid: %s for %s (%s)", title, first["email"], money(total))
        mailer.send(first["email"], f"Your booking: {title}", "\n".join([
            f"Hi {first['name'].split(' ')[0] if first['name'] else 'there'},", "",
            f"Thank you for booking with The Looking Glass Beauty School: {title}. We have received your payment of {money(total)}.", "",
            f"Choose {days} here (keep this link, it is yours alone):", booking_url(token), "",
            "If none of the dates suit, reply to this email and we will help.", "", "The Looking Glass Beauty School", "4a Roushill, Shrewsbury SY1 1PQ"]))
        mailer.school(f"Course sold: {title}", "\n".join([
            f"{first['name']} ({first['email']}, {first['phone'] or 'no phone given'}) has paid {money(total)} for: {title}.",
            "They have not chosen a date yet. They are on your course dates page under 'Paid, no date chosen yet'."]))
    return first


def _book(store: ShopStore, token: str, key: str, by: str = "") -> dict:
    before = store.get_order(token) or {}
    order = store.book(token, key)
    session = store.get_session(key) or {}
    if before.get("session_key") == key:
        return order  # asked twice for the date they already have: nothing new to say
    title = (content.course(order["course_id"]) or {}).get("title", order["course_id"])
    when = f"{nice_date(session['date'])}, {session['start']} to {session['end']}"
    log.info("SHOP booked: %s on %s for %s%s", order["course_id"], session.get("date"), order.get("email"), f" by {by}" if by else "")
    mailer.send(order.get("email", ""), f"You are booked: {title}, {nice_date(session['date'])}", "\n".join([
        f"Hi {order['name'].split(' ')[0] if order.get('name') else 'there'},", "",
        f"You are booked on the {title}.", "", f"When: {when}", "Where: The Looking Glass Beauty School, 4a Roushill, Shrewsbury SY1 1PQ",
        *( [f"Note: {session['note']}"] if session.get("note") else [] ), "",
        "Your booking, any time:", booking_url(token), "",
        "To change your date, reply to this email.", "", "The Looking Glass Beauty School"]))
    mailer.school(f"Course date booked: {title}, {session.get('date')}", "\n".join([
        f"{order.get('name')} ({order.get('email')}, {order.get('phone') or 'no phone given'}) is booked on the {title}, {when}.",
        f"Places taken: {session.get('taken')} of {session.get('capacity')}."]))
    return order


# ---------------------------------------------------------------- public routes
def payments_mode() -> str:
    """live: real money. test: Stripe's sandbox key is in, nothing is charged. off: no key yet.
    The website shows its pay buttons to everyone only when this says live."""
    key = str(stripe_api.shop_secret().get("secret_key") or "")
    return "live" if key.startswith(("sk_live_", "rk_live_")) else "test" if key else "off"


def is_admin(event: dict) -> bool:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    given, held = headers.get("x-admin-key", ""), stripe_api.shop_secret().get("admin_key", "")
    return len(held) >= 32 and hmac.compare_digest(given.encode(), held.encode())


def handle(event: dict, store: ShopStore | None = None) -> dict:
    route = event.get("routeKey", "")
    params = event.get("pathParameters") or {}
    query = event.get("queryStringParameters") or {}
    store = store or ShopStore()
    try:
        if route == "POST /shop/stripe/webhook":
            return webhook(event, store)

        if route in ("GET /shop/admin", "POST /shop/admin"):
            if not is_admin(event):
                return _json(403, {"error": "this page needs the school's private link"})
            return handle_admin(route, event, store)

        if route == "GET /shop/courses":
            on_sale = [c for c in content.courses().values() if shop_of(c)]
            both = [product(b) for b in content.bundles()]
            return _json(200, {"payments": payments_mode(), "terms": content.shop_terms(), "courses": [
                {"course_id": c["id"], "title": c["title"], "price_pence": shop_of(c)["price_pence"],
                 "prerequisites": c.get("prerequisites", ""), "sessions": open_sessions(store, c["id"])} for c in on_sale],
                "bundles": [{"id": b["id"], "title": b["title"], "price_pence": b["price_pence"], "courses": b["courses"],
                             "short": content.bundles()[b["id"]].get("short", ""),
                             "saving_pence": sum(shop_of(content.course(c))["price_pence"] for c in b["courses"]) - b["price_pence"]}
                            for b in both if b]})

        if route == "POST /shop/courses/{course_id}/checkout":
            cid = params.get("course_id", "")  # a course id, or a bundle id
            if not exists(cid):
                return _json(404, {"error": "unknown course"})
            buying = product(cid)
            if not buying:
                return _json(409, {"error": "this course is not on sale yet"})
            body = json.loads(event.get("body") or "{}")
            if body.get("confirm") is not True:
                return _json(400, {"error": "please confirm that you meet the entry requirements"})
            token = pysecrets.token_urlsafe(24)
            checkout = stripe_api.create_checkout(
                course_id=cid, title=buying["title"], amount_pence=buying["price_pence"], token=token, places=len(buying["courses"]),
                success_url=f"{booking_url(token)}&cs={{CHECKOUT_SESSION_ID}}",
                cancel_url=courses_url(), terms=content.shop_terms())
            return _json(200, {"url": checkout["url"]})

        token = params.get("token", "")
        if not _TOKEN.match(token):
            return _json(404, {"error": "no such order"})

        if route == "GET /shop/orders/{token}":
            order = store.get_order(token)
            cs = query.get("cs", "")
            if not order and cs.startswith("cs_"):
                checkout = stripe_api.get_checkout(cs)
                if checkout.get("client_reference_id") == token:
                    order = fulfil(store, checkout)
            if not order:
                return _json(404, {"error": "We cannot find that order. If you have just paid, wait a moment and reload."})
            return _json(200, public_order(store, order))

        if route == "POST /shop/orders/{token}/book":
            key = str(json.loads(event.get("body") or "{}").get("session", ""))
            session = store.get_session(key)
            if not session or session["date"] < today():
                return _json(404, {"error": "that date is not available"})
            return _json(200, public_order(store, _book(store, token, key)))

        return _json(404, {"error": "no such route"})
    except ShopError as exc:
        return _json(409, {"error": str(exc)})
    except stripe_api.NotConfigured as exc:
        log.warning("SHOP payments not set up: %s", exc)
        return _json(503, {"error": "online payment is not switched on yet; please contact the school"})
    except stripe_api.StripeError as exc:
        log.error("SHOP Stripe: %s", exc)
        return _json(502, {"error": "the payment service did not answer; please try again"})
    except Exception:  # noqa: BLE001
        log.exception("shop request failed: %s", route)
        return _json(500, {"error": "something went wrong"})


def webhook(event: dict, store: ShopStore) -> dict:
    raw = event.get("body") or ""
    payload = base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode()
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    try:
        ev = stripe_api.verify_webhook(payload, headers.get("stripe-signature", ""), stripe_api.secrets().get("webhook_secret", ""))
    except stripe_api.NotConfigured:
        return _json(503, {"error": "not configured"})
    except stripe_api.StripeError as exc:
        log.warning("SHOP webhook refused: %s", exc)
        return _json(400, {"error": "bad signature"})
    if ev.get("type") in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        fulfil(store, ev["data"]["object"])
    return _json(200, {"received": True})


# ---------------------------------------------------------------- admin routes
def admin_view(store: ShopStore) -> dict:
    orders = store.orders()
    by_session: dict[str, list[dict]] = {}
    for o in orders:
        if o.get("session_key"):
            by_session.setdefault(o["session_key"], []).append(o)

    def person(o: dict) -> dict:
        return {"token": o["token"], "name": o.get("name", ""), "email": o.get("email", ""), "phone": o.get("phone", ""),
                "course_id": o["course_id"], "amount": int(o["amount"]), "status": o["status"], "paid_at": o["created_at"],
                "session_key": o.get("session_key", ""), "test": not o.get("livemode", False), "bundle_title": o.get("bundle_title", "")}

    sessions = [{"key": s["SK"], "course_id": s["course_id"], "date": s["date"], "start": s["start"], "end": s["end"],
                 "capacity": int(s["capacity"]), "taken": int(s["taken"]), "status": s["status"], "note": s.get("note", ""),
                 "past": s["date"] < today(), "learners": [person(o) for o in by_session.get(s["SK"], [])]}
                for s in store.sessions()]
    courses = [{"id": c["id"], "title": c["title"], "on_sale": bool(shop_of(c)), "price_pence": (c.get("shop") or {}).get("price_pence"),
                "places": (c.get("shop") or {}).get("places", DEFAULT_PLACES)} for c in content.courses().values()]
    return {"today": today(), "courses": courses, "sessions": sessions, "orders": [person(o) for o in orders]}


def handle_admin(route: str, event: dict, store: ShopStore) -> dict:
    admin_email = "the course dates page"
    try:
        if route == "GET /shop/admin":
            return _json(200, admin_view(store))
        body = json.loads(event.get("body") or "{}")
        action = body.get("action", "")
        if action == "add_date":
            cid, date, start, end = (str(body.get(k, "")) for k in ("course_id", "date", "start", "end"))
            course = content.course(cid)
            if not course:
                return _json(400, {"error": "choose a course"})
            if not _DATE.match(date) or not _TIME.match(start) or not _TIME.match(end) or end <= start:
                return _json(400, {"error": "give a date, a start time and a later end time"})
            try:
                dt.date.fromisoformat(date)
            except ValueError:
                return _json(400, {"error": "that is not a real date"})
            if date < today():
                return _json(400, {"error": "that date has passed"})
            places = body.get("capacity")
            places = int((course.get("shop") or {}).get("places") or DEFAULT_PLACES) if places in (None, "") else int(places)
            if not 1 <= places <= 30:
                return _json(400, {"error": "places must be between 1 and 30"})
            store.put_session(cid, date, start, end, places, str(body.get("note", "")))
            log.info("SHOP date added: %s %s %s by %s", cid, date, start, admin_email)
        elif action == "update_date":
            cap = body.get("capacity")
            if cap is not None and not 1 <= int(cap) <= 30:
                return _json(400, {"error": "places must be between 1 and 30"})
            end = body.get("end")
            if end is not None and not _TIME.match(str(end)):
                return _json(400, {"error": "end time must look like 17:30"})
            store.update_session(str(body.get("key", "")), capacity=int(cap) if cap is not None else None, status=body.get("status"),
                                 end=end, note=body.get("note"))
            log.info("SHOP date changed: %s %s by %s", body.get("key"), {k: body[k] for k in ("capacity", "status", "end", "note") if k in body}, admin_email)
        elif action == "book":
            _book(store, str(body.get("token", "")), str(body.get("key", "")), by=admin_email)
        elif action in ("release", "cancel_order"):
            store.release(str(body.get("token", "")), "paid" if action == "release" else "cancelled")
            log.info("SHOP order %s: %s by %s", action, str(body.get("token", ""))[:6], admin_email)
        else:
            return _json(400, {"error": "unknown action"})
        return _json(200, admin_view(store))
    except ShopError as exc:
        return _json(409, {"error": str(exc)})
    except (ValueError, TypeError):
        return _json(400, {"error": "that did not look right; check the numbers and times"})
