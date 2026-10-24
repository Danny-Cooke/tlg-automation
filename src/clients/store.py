"""The clients table. One row per Fresha client id.

Fresha's fields are written with a single UpdateItem that only SETs those
fields, so a tap on the unsubscribe link between two syncs can never be
overwritten: the two sides of the row are disjoint.
"""
from __future__ import annotations

import os
import time
from functools import lru_cache

from . import model

OURS = ("sms_opt_out", "opt_out_changed_at", "opt_out_source", "fresha_pending", "lists", "token", "sent",
        "patch_tested", "patch_test_basis", "patch_test_date", "patch_test_service", "patch_test_set_at", "chased")


class ClientStore:
    def __init__(self, table=None):
        self._table = table

    @property
    def table(self):
        if self._table is None:
            self._table = _default_table()
        return self._table

    # -- the Fresha side ------------------------------------------------------

    def upsert_from_fresha(self, client: model.FreshaClient, *, now: int | None = None) -> None:
        """Write what Fresha says; create our fields only when the row is new."""
        now = now or int(time.time())
        fields = {**client.as_item(), "in_fresha": True, "synced_at": now}
        fields.pop("client_id")
        names = {f"#{k}": k for k in fields}
        values = {f":{k}": v for k, v in fields.items()}
        sets = [f"#{k} = :{k}" for k in fields]
        # Ours, created once and never touched by the sync again.
        names.update({"#token": "token", "#sms_opt_out": "sms_opt_out", "#lists": "lists", "#fresha_pending": "fresha_pending"})
        values.update({":new_token": model.new_token(), ":false": False, ":empty_list": []})
        sets += [
            "#token = if_not_exists(#token, :new_token)",
            "#sms_opt_out = if_not_exists(#sms_opt_out, :false)",
            "#lists = if_not_exists(#lists, :empty_list)",
            "#fresha_pending = if_not_exists(#fresha_pending, :false)",
        ]
        self.table.update_item(
            Key={"client_id": client.client_id},
            UpdateExpression="SET " + ", ".join(sets),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def stalest_first(self, ids: list[str]) -> list[str]:
        """`ids` ordered for refreshing: clients the table has never seen
        first, then by when their profile page was last fetched, oldest
        first. Keeps every id, so a run cut short by time leaves the rest
        first in line next time."""
        when = {r["client_id"]: int(r.get("record_synced_at") or 0)
                for r in self.all_rows(projection=("client_id", "record_synced_at"))}
        return sorted(ids, key=lambda cid: (cid in when, when.get(cid, 0)))

    def mark_missing(self, seen_ids: set[str], *, now: int | None = None) -> list[str]:
        """Rows Fresha no longer lists (merged or deleted there): flag, keep."""
        now = now or int(time.time())
        gone = []
        for item in self.all_rows(projection=("client_id", "in_fresha")):
            if item["client_id"] not in seen_ids and item.get("in_fresha", True):
                self.table.update_item(
                    Key={"client_id": item["client_id"]},
                    UpdateExpression="SET in_fresha = :f, synced_at = :now",
                    ExpressionAttributeValues={":f": False, ":now": now},
                )
                gone.append(item["client_id"])
        return gone

    # -- our side -------------------------------------------------------------

    def by_token(self, token: str) -> dict | None:
        if not token:
            return None
        resp = self.table.query(
            IndexName="by_token",
            KeyConditionExpression="#t = :t",
            ExpressionAttributeNames={"#t": "token"},
            ExpressionAttributeValues={":t": token},
        )
        items = resp.get("Items") or []
        return items[0] if items else None

    def set_opt_out(self, client_id: str, opted_out: bool, *, source: str, now: int | None = None) -> None:
        """The client's answer to us. `fresha_pending` asks the sync to carry
        it into Fresha once that call is known (plan job 10, step 3)."""
        now = now or int(time.time())
        self.table.update_item(
            Key={"client_id": client_id},
            UpdateExpression="SET sms_opt_out = :v, opt_out_changed_at = :now, opt_out_source = :src, fresha_pending = :t",
            ExpressionAttributeValues={":v": bool(opted_out), ":now": now, ":src": source, ":t": True},
        )

    def set_patch_tested(self, client_id: str, evidence: dict, *, now: int | None = None) -> None:
        """Our patch-test column (user, 2026-10-24): set when Fresha's side of
        the row shows a test or a service that needed one; never cleared by
        the sync. A Fresha record replaces an assumption; an assumption never
        replaces a record."""
        now = now or int(time.time())
        try:
            self.table.update_item(
                Key={"client_id": client_id},
                UpdateExpression="SET patch_tested = :t, patch_test_basis = :b, patch_test_date = :d, patch_test_service = :s, patch_test_set_at = :now",
                ConditionExpression="attribute_not_exists(patch_tested) OR patch_tested = :f OR :b = :record OR patch_test_basis <> :record",
                ExpressionAttributeValues={":t": True, ":f": False, ":b": evidence.get("patch_test_basis", ""), ":d": evidence.get("patch_test_date", ""),
                                           ":s": evidence.get("patch_test_service", ""), ":now": now, ":record": "fresha record"},
            )
        except Exception as exc:  # noqa: BLE001 - the row already holds a Fresha record; keep it
            if "ConditionalCheckFailed" not in str(exc) and type(exc).__name__ != "ConditionalCheckFailedException":
                raise

    def mark_chased(self, client_id: str, appointment_id: str, *, now: int | None = None) -> None:
        """The confirmation chaser texted this client about this appointment (job 14). Ours; never cleared."""
        self.table.update_item(
            Key={"client_id": client_id},
            UpdateExpression="SET chased = list_append(if_not_exists(chased, :empty), :one)",
            ExpressionAttributeValues={":empty": [], ":one": [{"appointment_id": str(appointment_id), "at": now or int(time.time())}]},
        )

    def all_rows(self, *, projection: tuple[str, ...] = ()) -> list[dict]:
        kw: dict = {}
        if projection:
            kw["ProjectionExpression"] = ", ".join(f"#{p}" for p in projection)
            kw["ExpressionAttributeNames"] = {f"#{p}": p for p in projection}
        items: list[dict] = []
        while True:
            resp = self.table.scan(**kw)
            items += resp.get("Items") or []
            if not resp.get("LastEvaluatedKey"):
                return items
            kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    SUMMARY_FIELDS = ("client_id", "in_fresha", "mobile", "accepts_sms_marketing", "sms_opt_out", "blocked", "fresha_pending",
                      "record_synced_at", "record_error", "patch_test_count", "patch_test_active", "allergy_count", "note_count",
                      "appointment_count", "staff_alert", "patch_tested", "patch_test_basis")

    def summary(self) -> dict:
        rows = self.all_rows(projection=self.SUMMARY_FIELDS)  # the rows carry whole profiles; read only the counters
        return {
            "rows": len(rows),
            "in_fresha": sum(1 for r in rows if r.get("in_fresha", True)),
            "with_mobile": sum(1 for r in rows if r.get("mobile")),
            "fresha_sms_yes": sum(1 for r in rows if r.get("accepts_sms_marketing")),
            "opted_out_with_us": sum(1 for r in rows if r.get("sms_opt_out")),
            "textable": sum(1 for r in rows if model.textable(r)),
            "fresha_pending": sum(1 for r in rows if r.get("fresha_pending")),
            "with_profile": sum(1 for r in rows if r.get("record_synced_at")),
            "profile_errors": sum(1 for r in rows if r.get("record_error")),
            "with_patch_tests": sum(1 for r in rows if r.get("patch_test_count")),
            "patch_test_active": sum(1 for r in rows if r.get("patch_test_active")),
            "with_allergies": sum(1 for r in rows if r.get("allergy_count")),
            "with_notes": sum(1 for r in rows if r.get("note_count")),
            "with_staff_alert": sum(1 for r in rows if r.get("staff_alert")),
            "with_appointments": sum(1 for r in rows if r.get("appointment_count")),
            "patch_tested": sum(1 for r in rows if r.get("patch_tested")),
            "patch_tested_from_record": sum(1 for r in rows if r.get("patch_tested") and r.get("patch_test_basis") == "fresha record"),
        }


@lru_cache(maxsize=1)
def _default_table():
    import boto3

    return boto3.resource("dynamodb").Table(os.environ["CLIENTS_TABLE"])
