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
