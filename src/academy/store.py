"""One DynamoDB table. PK=USER#<sub>; SK=PROFILE | ENROL#<course> | LESSON#<course>#<lesson>.
Enrolments also carry GSI1PK=ENROL#<status>, GSI1SK=<requested_at> so the
admin page can list what is pending without scanning."""
from __future__ import annotations

import datetime as dt
import os
from functools import lru_cache

import boto3
from boto3.dynamodb.conditions import Key

STATUSES = ("pending", "approved", "rejected")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


@lru_cache(maxsize=1)
def _default_table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


class Store:
    def __init__(self, table=None):
        self.table = table or _default_table()

    # ---- profiles -------------------------------------------------------

    def touch_profile(self, sub: str, email: str, name: str) -> dict:
        """Create the profile on first sight, update last_seen after that."""
        now = now_iso()
        res = self.table.update_item(
            Key={"PK": f"USER#{sub}", "SK": "PROFILE"},
            UpdateExpression="SET email = :e, #n = :n, last_seen = :t, created_at = if_not_exists(created_at, :t)",
            ExpressionAttributeNames={"#n": "name"},
            ExpressionAttributeValues={":e": email, ":n": name, ":t": now},
            ReturnValues="ALL_NEW",
        )
        return res["Attributes"]

    def user_items(self, sub: str) -> list[dict]:
        res = self.table.query(KeyConditionExpression=Key("PK").eq(f"USER#{sub}"))
        return res.get("Items", [])

    def enrolments(self, sub: str) -> dict[str, dict]:
        return {i["SK"].split("#", 1)[1]: i for i in self.user_items(sub) if i["SK"].startswith("ENROL#")}

    def completed_lessons(self, sub: str, course_id: str) -> list[str]:
        prefix = f"LESSON#{course_id}#"
        return [i["SK"][len(prefix):] for i in self.user_items(sub) if i["SK"].startswith(prefix)]

    # ---- enrolment requests -------------------------------------------

    def request_access(self, sub: str, email: str, name: str, course_id: str) -> dict:
        """pending, unless already approved (then unchanged)."""
        existing = self.table.get_item(Key={"PK": f"USER#{sub}", "SK": f"ENROL#{course_id}"}).get("Item")
        if existing and existing.get("status") == "approved":
            return existing
        now = now_iso()
        item = {
            "PK": f"USER#{sub}", "SK": f"ENROL#{course_id}", "course_id": course_id, "user_id": sub,
            "email": email, "name": name, "status": "pending", "requested_at": now,
            "GSI1PK": "ENROL#pending", "GSI1SK": now,
        }
        self.table.put_item(Item=item)
        return item

    def status(self, sub: str, course_id: str) -> str | None:
        item = self.table.get_item(Key={"PK": f"USER#{sub}", "SK": f"ENROL#{course_id}"}).get("Item")
        return item.get("status") if item else None

    def decide(self, sub: str, course_id: str, decision: str, decided_by: str, note: str = "") -> dict | None:
        if decision not in ("approved", "rejected"):
            raise ValueError(decision)
        key = {"PK": f"USER#{sub}", "SK": f"ENROL#{course_id}"}
        if not self.table.get_item(Key=key).get("Item"):
            return None
        now = now_iso()
        res = self.table.update_item(
            Key=key,
            UpdateExpression="SET #s = :s, decided_at = :t, decided_by = :b, note = :n, GSI1PK = :g, GSI1SK = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": decision, ":t": now, ":b": decided_by, ":n": note[:500], ":g": f"ENROL#{decision}"},
            ReturnValues="ALL_NEW",
        )
        return res["Attributes"]

    def list_by_status(self, status: str, limit: int = 100) -> list[dict]:
        if status not in STATUSES:
            raise ValueError(status)
        res = self.table.query(IndexName="GSI1", KeyConditionExpression=Key("GSI1PK").eq(f"ENROL#{status}"),
                               ScanIndexForward=False, Limit=limit)
        return res.get("Items", [])

    # ---- progress -------------------------------------------------------

    def complete_lesson(self, sub: str, course_id: str, lesson_id: str) -> None:
        self.table.put_item(Item={"PK": f"USER#{sub}", "SK": f"LESSON#{course_id}#{lesson_id}", "completed_at": now_iso()})


# ---------------------------------------------------------------------------
# The shop (plan job 21): course dates and paid orders, in the same table.
#
#   PK=SESSION        SK=<course>#<date>#<HHMM>   a taught day: start, end, capacity, taken, status, note
#   PK=ORDER#<token>  SK=ORDER                    a paid order; GSI1PK=ORDER, GSI1SK=<created_at> for the admin list
#   PK=EMAIL#<email>  SK=ORDER#<token>            pointer from the buyer's email to their orders
#
# The token is the order's key and the secret in the learner's "choose your
# date" link. A place is taken and the order marked in one transaction, so the
# last place cannot go twice and an order cannot hold two places.
# ---------------------------------------------------------------------------

SESSION_STATUSES = ("open", "closed", "cancelled")


class ShopError(Exception):
    """Something the caller can be told: the date is full, the order already has one."""


class ShopStore:
    def __init__(self, table=None):
        self.table = table or _default_table()
        self.client = self.table.meta.client

    # ---- course dates -------------------------------------------------

    @staticmethod
    def session_key(course_id: str, date: str, start: str) -> str:
        return f"{course_id}#{date}#{start.replace(':', '')}"

    def put_session(self, course_id: str, date: str, start: str, end: str, capacity: int, note: str = "") -> dict:
        key = self.session_key(course_id, date, start)
        item = {"PK": "SESSION", "SK": key, "course_id": course_id, "date": date, "start": start, "end": end,
                "capacity": int(capacity), "taken": 0, "status": "open", "note": note[:300], "created_at": now_iso()}
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
        except self.client.exceptions.ConditionalCheckFailedException:
            raise ShopError("there is already a date for that course at that time") from None
        return item

    def update_session(self, key: str, *, capacity: int | None = None, status: str | None = None, end: str | None = None,
                       note: str | None = None) -> dict:
        sets, names, values = [], {}, {}
        cond = "attribute_exists(PK)"
        if capacity is not None:
            sets.append("#c = :c")
            names["#c"], values[":c"] = "capacity", int(capacity)
            cond += " AND taken <= :c"  # never fewer places than people already on it
        if status is not None:
            if status not in SESSION_STATUSES:
                raise ShopError("status must be open, closed or cancelled")
            sets.append("#s = :s")
            names["#s"], values[":s"] = "status", status
        if end is not None:
            sets.append("#e = :e")
            names["#e"], values[":e"] = "end", end
        if note is not None:
            sets.append("#n = :n")
            names["#n"], values[":n"] = "note", note[:300]
        if not sets:
            raise ShopError("nothing to change")
        try:
            res = self.table.update_item(Key={"PK": "SESSION", "SK": key}, UpdateExpression="SET " + ", ".join(sets),
                                         ConditionExpression=cond, ExpressionAttributeNames=names,
                                         ExpressionAttributeValues=values, ReturnValues="ALL_NEW")
        except self.client.exceptions.ConditionalCheckFailedException:
            raise ShopError("no such date, or more people are booked on it than that number of places") from None
        return res["Attributes"]

    def get_session(self, key: str) -> dict | None:
        return self.table.get_item(Key={"PK": "SESSION", "SK": key}).get("Item")

    def sessions(self, course_id: str = "") -> list[dict]:
        cond = Key("PK").eq("SESSION")
        if course_id:
            cond = cond & Key("SK").begins_with(f"{course_id}#")
        items, kw = [], {"KeyConditionExpression": cond}
        while True:
            res = self.table.query(**kw)
            items += res.get("Items", [])
            if not res.get("LastEvaluatedKey"):
                return sorted(items, key=lambda s: (s["date"], s["start"], s["course_id"]))
            kw["ExclusiveStartKey"] = res["LastEvaluatedKey"]

    # ---- orders ---------------------------------------------------------

    def create_order(self, token: str, *, course_id: str, email: str, name: str, phone: str, amount: int, currency: str,
                     checkout_id: str, payment_intent: str, livemode: bool, siblings: list[str] | None = None,
                     bundle_title: str = "") -> tuple[dict, bool]:
        """(order, created). Stripe delivers an event more than once and the
        learner's browser may get here first: only the first write counts."""
        now = now_iso()
        email = email.strip().lower()
        item = {"PK": f"ORDER#{token}", "SK": "ORDER", "token": token, "course_id": course_id, "email": email, "name": name,
                "phone": phone, "amount": int(amount), "currency": currency, "checkout_id": checkout_id,
                "payment_intent": payment_intent, "livemode": bool(livemode), "status": "paid", "created_at": now,
                "GSI1PK": "ORDER", "GSI1SK": now}
        if siblings:  # bought with another course in one payment: the other orders' tokens
            item["siblings"], item["bundle_title"] = list(siblings), bundle_title
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
        except self.client.exceptions.ConditionalCheckFailedException:
            return self.get_order(token), False
        if email:
            self.table.put_item(Item={"PK": f"EMAIL#{email}", "SK": f"ORDER#{token}", "course_id": course_id, "created_at": now})
        return item, True

    def get_order(self, token: str) -> dict | None:
        return self.table.get_item(Key={"PK": f"ORDER#{token}", "SK": "ORDER"}).get("Item")

    def orders(self, limit: int = 300) -> list[dict]:
        res = self.table.query(IndexName="GSI1", KeyConditionExpression=Key("GSI1PK").eq("ORDER"), ScanIndexForward=False, Limit=limit)
        return res.get("Items", [])

    def orders_for_email(self, email: str) -> list[dict]:
        res = self.table.query(KeyConditionExpression=Key("PK").eq(f"EMAIL#{email.strip().lower()}"))
        found = [self.get_order(i["SK"].split("#", 1)[1]) for i in res.get("Items", [])]
        return [o for o in found if o]

    def book(self, token: str, key: str) -> dict:
        """Take a place on a date for a paid order that has none yet."""
        order = self.get_order(token)
        if not order:
            raise ShopError("no such order")
        if order.get("session_key") == key:
            return order
        if order["status"] != "paid":
            raise ShopError("this order already has a date; contact the school to change it"
                            if order["status"] == "booked" else "this order is not open for booking")
        if not key.startswith(f"{order['course_id']}#"):
            raise ShopError("that date is for a different course")
        try:
            self.client.transact_write_items(TransactItems=[
                {"Update": {"TableName": self.table.name, "Key": {"PK": "SESSION", "SK": key},
                            "UpdateExpression": "SET taken = taken + :one",
                            "ConditionExpression": "attribute_exists(PK) AND #s = :open AND taken < #c",
                            "ExpressionAttributeNames": {"#s": "status", "#c": "capacity"},
                            "ExpressionAttributeValues": {":one": 1, ":open": "open"}}},
                {"Update": {"TableName": self.table.name, "Key": {"PK": f"ORDER#{token}", "SK": "ORDER"},
                            "UpdateExpression": "SET session_key = :k, #s = :booked, booked_at = :t",
                            "ConditionExpression": "#s = :paid AND attribute_not_exists(session_key)",
                            "ExpressionAttributeNames": {"#s": "status"},
                            "ExpressionAttributeValues": {":k": key, ":booked": "booked", ":paid": "paid", ":t": now_iso()}}},
            ])
        except self.client.exceptions.TransactionCanceledException:
            raise ShopError("that date has just filled up or closed; please choose another") from None
        return self.get_order(token)

    def release(self, token: str, new_status: str = "paid") -> dict:
        """Give the place back: the learner can then choose again (paid), or the
        order is finished with (cancelled, after a refund made in Stripe)."""
        if new_status not in ("paid", "cancelled"):
            raise ShopError("status must be paid or cancelled")
        order = self.get_order(token)
        if not order:
            raise ShopError("no such order")
        key = order.get("session_key")
        if not key:
            self.table.update_item(Key={"PK": f"ORDER#{token}", "SK": "ORDER"}, UpdateExpression="SET #s = :s",
                                   ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": new_status})
            return self.get_order(token)
        self.client.transact_write_items(TransactItems=[
            {"Update": {"TableName": self.table.name, "Key": {"PK": "SESSION", "SK": key},
                        "UpdateExpression": "SET taken = taken - :one", "ConditionExpression": "taken >= :one",
                        "ExpressionAttributeValues": {":one": 1}}},
            {"Update": {"TableName": self.table.name, "Key": {"PK": f"ORDER#{token}", "SK": "ORDER"},
                        "UpdateExpression": "SET #s = :s REMOVE session_key, booked_at",
                        "ConditionExpression": "session_key = :k",
                        "ExpressionAttributeNames": {"#s": "status"}, "ExpressionAttributeValues": {":s": new_status, ":k": key}}},
        ])
        return self.get_order(token)
