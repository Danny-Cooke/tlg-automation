"""TLG Academy API. HTTP API (payload 2.0) behind a Cognito JWT authoriser, so
every request arrives with verified claims. Routes:

  GET  /me                                             profile, enrolments, progress, is_admin
  POST /courses/{course_id}/request                    ask for access (pending)
  POST /courses/{course_id}/lessons/{lesson_id}/complete
  GET  /courses/{course_id}/files/{file_id}            presigned link, approved learners only
  GET  /admin/requests?status=pending                  admins only
  POST /admin/requests/{user_id}/{course_id}           admins only: {"decision": "approved"|"rejected", "note": ""}

The browser never decides who may see a lesson: the file link and the
completion write both check the enrolment status here."""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

import boto3

from . import content
from .store import Store

log = logging.getLogger("academy")
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

ADMIN_GROUP = "admins"
LINK_SECONDS = 300


def _json(status: int, body) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body, default=str)}


def _claims(event: dict) -> dict:
    return event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {}) or {}


def _is_admin(claims: dict) -> bool:
    groups = claims.get("cognito:groups", "")
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.strip("[]").split(",")]
    if ADMIN_GROUP in groups:
        return True
    admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
    return claims.get("email", "").lower() in admins


@lru_cache(maxsize=1)
def _s3():
    return boto3.client("s3")


def lambda_handler(event: dict, context=None, store: Store | None = None, s3=None) -> dict:
    claims = _claims(event)
    sub = claims.get("sub")
    if not sub:
        return _json(401, {"error": "no identity"})
    email = claims.get("email", "")
    name = claims.get("name") or email
    route = event.get("routeKey") or f"{event.get('requestContext', {}).get('http', {}).get('method')} {event.get('rawPath')}"
    params = event.get("pathParameters") or {}
    query = event.get("queryStringParameters") or {}
    store = store or Store()
    admin = _is_admin(claims)

    try:
        if route == "GET /me":
            profile = store.touch_profile(sub, email, name)
            enrols = store.enrolments(sub)
            progress = {cid: store.completed_lessons(sub, cid) for cid, e in enrols.items() if e.get("status") == "approved"}
            return _json(200, {
                "user": {"id": sub, "email": email, "name": name, "created_at": profile.get("created_at")},
                "is_admin": admin,
                "enrolments": {cid: {"status": e["status"], "requested_at": e.get("requested_at"), "decided_at": e.get("decided_at"), "note": e.get("note", "")} for cid, e in enrols.items()},
                "progress": progress,
            })

        if route == "POST /courses/{course_id}/request":
            cid = params.get("course_id", "")
            c = content.course(cid)
            if not c:
                return _json(404, {"error": "unknown course"})
            if c.get("placeholder"):
                return _json(409, {"error": "this course is not open for requests yet"})
            store.touch_profile(sub, email, name)
            item = store.request_access(sub, email, name, cid)
            return _json(200, {"course_id": cid, "status": item["status"]})

        if route == "POST /courses/{course_id}/lessons/{lesson_id}/complete":
            cid, lid = params.get("course_id", ""), params.get("lesson_id", "")
            if lid not in content.lesson_ids(cid):
                return _json(404, {"error": "unknown lesson"})
            if store.status(sub, cid) != "approved":
                return _json(403, {"error": "not approved for this course"})
            store.complete_lesson(sub, cid, lid)
            return _json(200, {"course_id": cid, "completed": store.completed_lessons(sub, cid)})

        if route == "GET /courses/{course_id}/files/{file_id}":
            cid, fid = params.get("course_id", ""), params.get("file_id", "")
            entry = content.file_entry(cid, fid)
            if not entry:
                return _json(404, {"error": "unknown file"})
            if store.status(sub, cid) != "approved" and not admin:
                return _json(403, {"error": "not approved for this course"})
            url = (s3 or _s3()).generate_presigned_url(
                "get_object", Params={"Bucket": os.environ["FILES_BUCKET"], "Key": entry["key"]}, ExpiresIn=LINK_SECONDS)
            return _json(200, {"url": url, "expires_in": LINK_SECONDS, "label": entry.get("label", fid)})

        if route.startswith("GET /admin/") or route.startswith("POST /admin/"):
            if not admin:
                return _json(403, {"error": "admins only"})
            if route == "GET /admin/requests":
                status = query.get("status", "pending")
                try:
                    items = store.list_by_status(status)
                except ValueError:
                    return _json(400, {"error": "status must be pending, approved or rejected"})
                return _json(200, {"status": status, "requests": [
                    {"user_id": i["user_id"], "course_id": i["course_id"], "email": i.get("email"), "name": i.get("name"),
                     "status": i["status"], "requested_at": i.get("requested_at"), "decided_at": i.get("decided_at"), "note": i.get("note", "")}
                    for i in items]})
            if route == "POST /admin/requests/{user_id}/{course_id}":
                body = json.loads(event.get("body") or "{}")
                decision = body.get("decision", "")
                if decision not in ("approved", "rejected"):
                    return _json(400, {"error": "decision must be approved or rejected"})
                item = store.decide(params["user_id"], params["course_id"], decision, email, body.get("note", ""))
                if not item:
                    return _json(404, {"error": "no such request"})
                log.info("ACADEMY %s %s for %s by %s", decision, params["course_id"], item.get("email"), email)
                return _json(200, {"user_id": params["user_id"], "course_id": params["course_id"], "status": item["status"]})

        return _json(404, {"error": "no such route"})
    except Exception:  # noqa: BLE001
        log.exception("academy request failed: %s", route)
        return _json(500, {"error": "something went wrong"})
