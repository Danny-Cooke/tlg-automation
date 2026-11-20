"""The academy shop: an order exists only when Stripe says it is paid, a place
cannot be sold twice, and only the school's private key opens the calendar.
Nobody logs in."""
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("ACADEMY_CONTENT", str(ROOT / "academy" / "content" / "courses.json"))
os.environ.setdefault("TABLE_NAME", "tlg-test-academy")
os.environ.setdefault("FILES_BUCKET", "tlg-test-academy-files")
os.environ.setdefault("ADMIN_EMAILS", "jess@example.com")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

from academy import content, handler, mailer, shop, stripe_api  # noqa: E402
from academy.store import ShopStore, Store  # noqa: E402

COURSE = "acrylic"
BUNDLE = "acrylic-and-gel-polish"
WHSEC = "whsec_test"
ADMIN_KEY = "k" * 43
ADMIN = dict(headers={"X-Admin-Key": ADMIN_KEY})


@pytest.fixture
def world(monkeypatch):
    """A table, the acrylic course on sale at £350, a fake Stripe, and every email captured."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="eu-west-2")
        table = ddb.create_table(
            TableName="tlg-test-academy", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n in ("PK", "SK", "GSI1PK", "GSI1SK")],
            GlobalSecondaryIndexes=[{"IndexName": "GSI1", "KeySchema": [{"AttributeName": "GSI1PK", "KeyType": "HASH"}, {"AttributeName": "GSI1SK", "KeyType": "RANGE"}], "Projection": {"ProjectionType": "ALL"}}],
        )
        w = {"store": Store(table), "shop": ShopStore(table), "checkouts": {}, "emails": []}
        # The test's own price list, whatever courses.json says today: acrylic £350 and gel polish £300 on sale,
        # the two together £600; e-file priced but not on sale, so its combination with builder gel is not either.
        for cid, shop_block in {"acrylic": {"on_sale": True, "price_pence": 35000, "places": 4}, "gel-polish": {"on_sale": True, "price_pence": 30000, "places": 4},
                                "efile": {"on_sale": False, "price_pence": 28000, "places": 4}, "builder-gel": {"on_sale": True, "price_pence": 20000, "places": 4},
                                "lash-brow": {}}.items():
            monkeypatch.setitem(content.courses()[cid], "shop", shop_block)
        monkeypatch.setattr(content, "bundles", lambda: {
            BUNDLE: {"id": BUNDLE, "title": "Acrylic and Gel Polish: both courses", "courses": ["acrylic", "gel-polish"], "price_pence": 60000, "on_sale": True, "short": "Both."},
            "builder-gel-and-efile": {"id": "builder-gel-and-efile", "title": "Builder Gel and Electric File: both courses", "courses": ["builder-gel", "efile"], "price_pence": 37500, "on_sale": True}})
        monkeypatch.setenv("SHOP_BOOKING_URL", "https://site.example/academy/booking/")
        monkeypatch.setenv("SHOP_COURSES_URL", "https://site.example/academy/")
        monkeypatch.setattr(stripe_api, "shop_secret", lambda: {"admin_key": ADMIN_KEY})
        monkeypatch.setattr(shop, "today", lambda: "2027-01-01")
        monkeypatch.setattr(stripe_api, "secrets", lambda: {"secret_key": "sk_test_x", "webhook_secret": WHSEC})

        def create_checkout(**kw):
            cs = {"id": f"cs_test_{len(w['checkouts']) + 1}", "url": "https://checkout.stripe.com/c/pay/x", "client_reference_id": kw["token"],
                  "payment_status": "unpaid", "amount_total": kw["amount_pence"], "currency": "gbp", "livemode": False, "payment_intent": "pi_1",
                  "metadata": {"course_id": kw["course_id"], "token": kw["token"], "source": "tlg-academy"},
                  "customer_details": {"email": "Ann@Example.com", "name": "Ann Learner", "phone": "+447700900123"}, "_kw": kw}
            w["checkouts"][cs["id"]] = cs
            return cs

        monkeypatch.setattr(stripe_api, "create_checkout", create_checkout)
        monkeypatch.setattr(stripe_api, "get_checkout", lambda cid: w["checkouts"][cid])
        monkeypatch.setattr(mailer, "send", lambda to, subject, body, **kw: w["emails"].append((to, subject, body)) or True)
        monkeypatch.setattr(mailer, "school", lambda subject, body, **kw: w["emails"].append(("school", subject, body)) or True)
        yield w


def call(w, route, *, params=None, body=None, query=None, headers=None, raw=None, sub=None, email="", name="", groups="", verified="true"):
    ev = {"routeKey": route, "pathParameters": params or {}, "queryStringParameters": query or {}, "headers": headers or {},
          "body": raw if raw is not None else (json.dumps(body) if body is not None else None), "requestContext": {}}
    if sub:
        claims = {"sub": sub, "email": email, "name": name, "email_verified": verified}
        if groups:
            claims["cognito:groups"] = groups
        ev["requestContext"] = {"authorizer": {"jwt": {"claims": claims}}}
    res = handler.lambda_handler(ev, store=w["store"])
    return res["statusCode"], json.loads(res["body"])


def add_date(w, date="2027-02-01", start="09:00", end="18:00", **extra):
    return call(w, "POST /shop/admin", body={"action": "add_date", "course_id": COURSE, "date": date, "start": start, "end": end, **extra}, **ADMIN)


def buy(w, pay=True, what=COURSE):
    """Through checkout; returns (token, checkout id)."""
    code, body = call(w, "POST /shop/courses/{course_id}/checkout", params={"course_id": what}, body={"confirm": True})
    assert code == 200 and body["url"].startswith("https://checkout.stripe.com/")
    cs = list(w["checkouts"].values())[-1]
    if pay:
        cs["payment_status"] = "paid"
    return cs["client_reference_id"], cs["id"]


def signed(payload: dict, secret=WHSEC, when=None):
    raw = json.dumps(payload)
    t = str(int(when or time.time()))
    sig = hmac.new(secret.encode(), f"{t}.{raw}".encode(), hashlib.sha256).hexdigest()
    return raw, {"Stripe-Signature": f"t={t},v1={sig}"}


def test_course_page_shows_price_and_open_dates_without_a_login(world):
    w = world
    assert add_date(w)[0] == 200
    assert add_date(w, date="2027-03-01")[0] == 200
    call(w, "POST /shop/admin", body={"action": "update_date", "key": f"{COURSE}#2027-03-01#0900", "status": "closed"}, **ADMIN)
    code, body = call(w, "GET /shop/courses")
    assert code == 200 and sorted(c["course_id"] for c in body["courses"]) == [COURSE, "builder-gel", "gel-polish"]  # only what is on sale
    c = [c for c in body["courses"] if c["course_id"] == COURSE][0]
    assert c["price_pence"] == 35000 and "Level 2" in c["prerequisites"]
    assert [(s["date"], s["places_left"]) for s in c["sessions"]] == [("2027-02-01", 4)]  # the closed date is not offered
    # A course with no price is not on sale and cannot be bought.
    assert call(w, "POST /shop/courses/{course_id}/checkout", params={"course_id": "efile"}, body={"confirm": True})[0] == 409
    assert call(w, "POST /shop/courses/{course_id}/checkout", params={"course_id": "nope"}, body={"confirm": True})[0] == 404


def test_checkout_needs_the_entry_requirements_ticked_and_charges_the_course_price(world):
    w = world
    assert call(w, "POST /shop/courses/{course_id}/checkout", params={"course_id": COURSE}, body={})[0] == 400
    token, cs = buy(w, pay=False)
    kw = w["checkouts"][cs]["_kw"]
    assert kw["amount_pence"] == 35000 and "Acrylic" in kw["title"]
    assert kw["success_url"] == f"https://site.example/academy/booking/?order={token}&cs={{CHECKOUT_SESSION_ID}}"
    assert kw["cancel_url"] == "https://site.example/academy/"
    # Not paid: no order, whatever the browser says.
    assert call(w, "GET /shop/orders/{token}", params={"token": token}, query={"cs": cs})[0] == 404
    assert w["shop"].orders() == [] and w["emails"] == []


def test_paid_order_arrives_by_the_browser_or_the_webhook_but_only_once(world):
    w = world
    add_date(w)
    token, cs = buy(w)
    # Somebody else's checkout id does not open this token.
    other_token, other_cs = buy(w)
    assert call(w, "GET /shop/orders/{token}", params={"token": token}, query={"cs": other_cs})[0] == 404
    code, order = call(w, "GET /shop/orders/{token}", params={"token": token}, query={"cs": cs})
    assert code == 200 and order["status"] == "paid" and order["amount"] == 35000 and order["test"] is True
    assert [s["date"] for s in order["sessions"]] == ["2027-02-01"]
    # The webhook for the same payment changes nothing and sends nothing more.
    sent = len(w["emails"])
    raw, headers = signed({"type": "checkout.session.completed", "data": {"object": {k: v for k, v in w["checkouts"][cs].items() if k != "_kw"}}})
    assert call(w, "POST /shop/stripe/webhook", raw=raw, headers=headers)[0] == 200
    assert len(w["shop"].orders()) == 1 and len(w["emails"]) == sent == 2
    learner = w["emails"][0]
    assert learner[0] == "ann@example.com" and f"https://site.example/academy/booking/?order={token}" in learner[2] and "£350" in learner[2]
    # The webhook alone is enough (the learner closed the tab).
    raw, headers = signed({"type": "checkout.session.completed", "data": {"object": {k: v for k, v in w["checkouts"][other_cs].items() if k != "_kw"}}})
    assert call(w, "POST /shop/stripe/webhook", raw=raw, headers=headers)[0] == 200
    assert call(w, "GET /shop/orders/{token}", params={"token": other_token})[0] == 200


def test_webhook_is_refused_without_a_current_signature(world):
    w = world
    token, cs = buy(w)
    obj = {k: v for k, v in w["checkouts"][cs].items() if k != "_kw"}
    payload = {"type": "checkout.session.completed", "data": {"object": obj}}
    raw, headers = signed(payload, secret="whsec_wrong")
    assert call(w, "POST /shop/stripe/webhook", raw=raw, headers=headers)[0] == 400
    raw, headers = signed(payload, when=time.time() - 3600)
    assert call(w, "POST /shop/stripe/webhook", raw=raw, headers=headers)[0] == 400
    raw, headers = signed(payload)
    assert call(w, "POST /shop/stripe/webhook", raw=raw + " ", headers=headers)[0] == 400  # body altered after signing
    assert call(w, "POST /shop/stripe/webhook", raw=raw, headers={})[0] == 400
    assert w["shop"].orders() == []
    # A signed event for an unpaid session, or one that is not the academy's, makes no order.
    raw, headers = signed({"type": "checkout.session.completed", "data": {"object": {**obj, "payment_status": "unpaid"}}})
    assert call(w, "POST /shop/stripe/webhook", raw=raw, headers=headers)[0] == 200
    raw, headers = signed({"type": "checkout.session.completed", "data": {"object": {**obj, "metadata": {}}}})
    assert call(w, "POST /shop/stripe/webhook", raw=raw, headers=headers)[0] == 200
    assert w["shop"].orders() == []


def test_the_last_place_goes_once_and_an_order_holds_one_place(world):
    w = world
    add_date(w, capacity=1)
    add_date(w, date="2027-02-08")
    key = f"{COURSE}#2027-02-01#0900"
    (t1, c1), (t2, c2) = buy(w), buy(w)
    for t, c in ((t1, c1), (t2, c2)):
        assert call(w, "GET /shop/orders/{token}", params={"token": t}, query={"cs": c})[0] == 200
    code, order = call(w, "POST /shop/orders/{token}/book", params={"token": t1}, body={"session": key})
    assert code == 200 and order["status"] == "booked" and order["session"]["date"] == "2027-02-01" and "sessions" not in order
    code, body = call(w, "POST /shop/orders/{token}/book", params={"token": t2}, body={"session": key})
    assert code == 409 and "filled up" in body["error"]
    # The full date is no longer offered; the other is.
    assert [s["date"] for s in call(w, "GET /shop/orders/{token}", params={"token": t2})[1]["sessions"]] == ["2027-02-08"]
    # A booked order cannot take a second place, and booking the same date again is harmless.
    assert call(w, "POST /shop/orders/{token}/book", params={"token": t1}, body={"session": f"{COURSE}#2027-02-08#0900"})[0] == 409
    assert call(w, "POST /shop/orders/{token}/book", params={"token": t1}, body={"session": key})[0] == 200
    assert int(w["shop"].get_session(key)["taken"]) == 1
    assert int(w["shop"].get_session(f"{COURSE}#2027-02-08#0900")["taken"]) == 0
    # Nonsense tokens and dates.
    assert call(w, "POST /shop/orders/{token}/book", params={"token": "x" * 32}, body={"session": key})[0] == 409
    assert call(w, "POST /shop/orders/{token}/book", params={"token": "short"}, body={"session": key})[0] == 404
    assert call(w, "POST /shop/orders/{token}/book", params={"token": t2}, body={"session": "acrylic#1999-01-01#0900"})[0] == 404
    booked = [e for e in w["emails"] if e[1].startswith("You are booked")]
    assert len(booked) == 1 and "Monday 1 February 2027, 09:00 to 18:00" in booked[0][2]


def test_only_the_private_key_opens_the_calendar(world, monkeypatch):
    w = world
    new = {"action": "add_date", "course_id": COURSE, "date": "2027-02-01", "start": "09:00", "end": "18:00"}
    for headers in ({}, {"X-Admin-Key": ""}, {"X-Admin-Key": "k" * 42}, {"X-Admin-Key": "wrong" * 9}):
        assert call(w, "GET /shop/admin", headers=headers)[0] == 403, headers
        assert call(w, "POST /shop/admin", body=new, headers=headers)[0] == 403, headers
    # Being logged in to the student portal is not the key.
    assert call(w, "GET /shop/admin", sub="jess", email="jess@example.com", groups="[admins]")[0] == 403
    assert w["shop"].sessions() == []
    # No key set up yet (first deploy), or a short one: nothing opens, not even with a matching empty header.
    monkeypatch.setattr(stripe_api, "shop_secret", lambda: {})
    assert call(w, "GET /shop/admin", headers={"X-Admin-Key": ""})[0] == 403
    monkeypatch.setattr(stripe_api, "shop_secret", lambda: {"admin_key": "short"})
    assert call(w, "GET /shop/admin", headers={"X-Admin-Key": "short"})[0] == 403
    monkeypatch.setattr(stripe_api, "shop_secret", lambda: {"admin_key": ADMIN_KEY})
    code, view = add_date(w)
    assert code == 200 and [(s["date"], s["capacity"], s["taken"]) for s in view["sessions"]] == [("2027-02-01", 4, 0)]  # the course's default places
    assert add_date(w)[0] == 409  # same course, day and start
    for bad in ({"date": "2026-12-01"}, {"date": "2027-02-30"}, {"start": "18:00", "end": "09:00"}, {"capacity": 0}, {"course_id": "nope"}):
        assert call(w, "POST /shop/admin", body={"action": "add_date", "course_id": COURSE, "date": "2027-04-01", "start": "09:00", "end": "18:00", **bad}, **ADMIN)[0] == 400, bad
    assert call(w, "POST /shop/admin", body={"action": "explode"}, **ADMIN)[0] == 400


def test_admin_sees_who_is_on_each_date_and_can_move_or_cancel_them(world):
    w = world
    add_date(w)
    add_date(w, date="2027-02-08")
    k1, k2 = f"{COURSE}#2027-02-01#0900", f"{COURSE}#2027-02-08#0900"
    token, cs = buy(w)
    call(w, "GET /shop/orders/{token}", params={"token": token}, query={"cs": cs})
    view = call(w, "GET /shop/admin", **ADMIN)[1]
    assert [(o["name"], o["status"], o["session_key"]) for o in view["orders"]] == [("Ann Learner", "paid", "")]
    call(w, "POST /shop/orders/{token}/book", params={"token": token}, body={"session": k1})
    view = call(w, "GET /shop/admin", **ADMIN)[1]
    assert [l["email"] for l in view["sessions"][0]["learners"]] == ["ann@example.com"] and view["sessions"][0]["taken"] == 1
    # Places cannot drop below the people already booked.
    assert call(w, "POST /shop/admin", body={"action": "update_date", "key": k1, "capacity": 0}, **ADMIN)[0] == 400
    assert call(w, "POST /shop/admin", body={"action": "update_date", "key": k1, "capacity": 1}, **ADMIN)[0] == 200
    # Move: release, then book the other date on her behalf.
    code, view = call(w, "POST /shop/admin", body={"action": "release", "token": token}, **ADMIN)
    assert code == 200 and view["sessions"][0]["taken"] == 0 and view["orders"][0]["status"] == "paid"
    code, view = call(w, "POST /shop/admin", body={"action": "book", "token": token, "key": k2}, **ADMIN)
    assert code == 200 and view["sessions"][1]["taken"] == 1 and view["orders"][0]["session_key"] == k2
    # Cancel (after a refund in Stripe): the place comes back and the order cannot book again.
    code, view = call(w, "POST /shop/admin", body={"action": "cancel_order", "token": token}, **ADMIN)
    assert view["sessions"][1]["taken"] == 0 and view["orders"][0]["status"] == "cancelled"
    assert call(w, "POST /shop/orders/{token}/book", params={"token": token}, body={"session": k1})[0] == 409


def test_buying_changes_nothing_in_the_student_portal(world):
    w = world
    add_date(w)
    token, cs = buy(w)
    call(w, "GET /shop/orders/{token}", params={"token": token}, query={"cs": cs})
    me = call(w, "GET /me", sub="u1", email="ann@example.com", name="Ann")[1]
    assert me["enrolments"] == {} and "orders" not in me


def test_two_courses_bought_together_are_one_payment_and_a_date_each(world):
    w = world
    add_date(w)
    call(w, "POST /shop/admin", body={"action": "add_date", "course_id": "gel-polish", "date": "2027-02-10", "start": "09:00", "end": "17:30"}, **ADMIN)
    # Listed with its saving; a combination with a course that is not on sale is not offered and cannot be bought.
    body = call(w, "GET /shop/courses")[1]
    assert [(b["id"], b["price_pence"], b["saving_pence"], b["courses"]) for b in body["bundles"]] == [(BUNDLE, 60000, 5000, ["acrylic", "gel-polish"])]
    assert call(w, "POST /shop/courses/{course_id}/checkout", params={"course_id": "builder-gel-and-efile"}, body={"confirm": True})[0] == 409
    token, cs = buy(w, what=BUNDLE)
    kw = w["checkouts"][cs]["_kw"]
    assert kw["amount_pence"] == 60000 and kw["places"] == 2 and kw["title"].startswith("Acrylic and Gel Polish")
    code, order = call(w, "GET /shop/orders/{token}", params={"token": token}, query={"cs": cs})
    assert code == 200 and order["course_id"] == "acrylic" and order["status"] == "paid" and order["bundle_title"]
    assert [o["course_title"] for o in order["others"]] == ["Gel Polish Nails CPD Course"] and order["others"][0]["status"] == "paid"
    orders = w["shop"].orders()
    assert sorted((o["course_id"], int(o["amount"])) for o in orders) == [("acrylic", 32307), ("gel-polish", 27693)]  # £600 shared 350:300
    assert sum(int(o["amount"]) for o in orders) == 60000
    # One email to the learner and one to the school, not one per course; the webhook after it adds nothing.
    assert len(w["emails"]) == 2 and "a date for each" in w["emails"][0][2] and "£600" in w["emails"][0][2]
    raw, headers = signed({"type": "checkout.session.completed", "data": {"object": {k: v for k, v in w["checkouts"][cs].items() if k != "_kw"}}})
    call(w, "POST /shop/stripe/webhook", raw=raw, headers=headers)
    assert len(w["shop"].orders()) == 2 and len(w["emails"]) == 2
    # A date for each, from the one link.
    other = order["others"][0]["token"]
    assert call(w, "POST /shop/orders/{token}/book", params={"token": token}, body={"session": "gel-polish#2027-02-10#0900"})[0] == 409  # wrong course for this half
    assert call(w, "POST /shop/orders/{token}/book", params={"token": token}, body={"session": f"{COURSE}#2027-02-01#0900"})[0] == 200
    code, second = call(w, "POST /shop/orders/{token}/book", params={"token": other}, body={"session": "gel-polish#2027-02-10#0900"})
    assert code == 200 and second["status"] == "booked" and second["others"][0]["date"] == "2027-02-01"
    assert call(w, "GET /shop/orders/{token}", params={"token": token})[1]["others"][0]["date"] == "2027-02-10"
    view = call(w, "GET /shop/admin", **ADMIN)[1]
    assert sorted((s["course_id"], s["taken"]) for s in view["sessions"]) == [("acrylic", 1), ("gel-polish", 1)]
    assert all(o["bundle_title"] for o in view["orders"])


def test_stripe_form_encoding_and_signature_helper():
    flat = dict(stripe_api.flatten({"mode": "payment", "line_items": [{"quantity": 1, "price_data": {"unit_amount": 35000}}], "phone_number_collection": {"enabled": True}, "skip": None}))
    assert flat == {"mode": "payment", "line_items[0][quantity]": "1", "line_items[0][price_data][unit_amount]": "35000", "phone_number_collection[enabled]": "true"}
    raw, headers = signed({"type": "x"})
    assert stripe_api.verify_webhook(raw.encode(), headers["Stripe-Signature"], WHSEC) == {"type": "x"}
    with pytest.raises(stripe_api.StripeError):
        stripe_api.verify_webhook(raw.encode(), headers["Stripe-Signature"], "")
