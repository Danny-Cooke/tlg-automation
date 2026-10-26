"""TLG Academy API: the approval gate decides what a learner may see, and it is
enforced by the API, not the browser."""
import json
import os
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

from academy import content, handler, triggers  # noqa: E402
from academy.store import Store  # noqa: E402

COURSE = "builder-gel"


@pytest.fixture
def store():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="eu-west-2")
        table = ddb.create_table(
            TableName="tlg-test-academy",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n in ("PK", "SK", "GSI1PK", "GSI1SK")],
            GlobalSecondaryIndexes=[{"IndexName": "GSI1", "KeySchema": [{"AttributeName": "GSI1PK", "KeyType": "HASH"}, {"AttributeName": "GSI1SK", "KeyType": "RANGE"}], "Projection": {"ProjectionType": "ALL"}}],
        )
        yield Store(table)


def event(route, sub="u1", email="ann@example.com", name="Ann", groups="", params=None, body=None, query=None):
    claims = {"sub": sub, "email": email, "name": name}
    if groups:
        claims["cognito:groups"] = groups
    return {"routeKey": route, "pathParameters": params or {}, "queryStringParameters": query or {},
            "body": json.dumps(body) if body is not None else None,
            "requestContext": {"authorizer": {"jwt": {"claims": claims}}}}


def call(store, *a, **kw):
    res = handler.lambda_handler(event(*a, **kw), store=store, s3=FakeS3())
    return res["statusCode"], json.loads(res["body"])


class FakeS3:
    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://signed/{Params['Bucket']}/{Params['Key']}?x={ExpiresIn}"


def test_content_catalogue_matches_the_site_files():
    c = content.course(COURSE)
    assert c and "CPD Course" in c["title"]
    assert content.lesson_ids(COURSE) >= {"01-welcome", "08-before-the-day"}
    for lesson in c["lessons"]:
        assert (ROOT / "academy" / "content" / lesson["file"]).exists(), lesson["file"]
    assert content.file_entry(COURSE, "manual")["key"].startswith("builder-gel/")
    assert content.file_entry(COURSE, "nope") is None


def test_registering_gives_a_profile_and_nothing_else(store):
    code, me = call(store, "GET /me")
    assert code == 200 and me["user"]["email"] == "ann@example.com" and me["is_admin"] is False
    assert me["enrolments"] == {} and me["progress"] == {}
    code, body = call(store, "POST /courses/{course_id}/lessons/{lesson_id}/complete", params={"course_id": COURSE, "lesson_id": "01-welcome"})
    assert code == 403
    code, body = call(store, "GET /courses/{course_id}/files/{file_id}", params={"course_id": COURSE, "file_id": "manual"})
    assert code == 403


def test_request_then_approval_unlocks_lessons_and_files(store):
    code, body = call(store, "POST /courses/{course_id}/request", params={"course_id": COURSE})
    assert code == 200 and body["status"] == "pending"
    assert call(store, "GET /me")[1]["enrolments"][COURSE]["status"] == "pending"
    # still locked while pending
    assert call(store, "POST /courses/{course_id}/lessons/{lesson_id}/complete", params={"course_id": COURSE, "lesson_id": "01-welcome"})[0] == 403
    # a learner cannot approve themselves
    code, body = call(store, "POST /admin/requests/{user_id}/{course_id}", params={"user_id": "u1", "course_id": COURSE}, body={"decision": "approved"})
    assert code == 403
    # Jess (admins group) sees it pending and approves
    code, body = call(store, "GET /admin/requests", sub="jess", email="jess@example.com", name="Jess", groups="[admins]")
    assert code == 200 and [r["user_id"] for r in body["requests"]] == ["u1"]
    code, body = call(store, "POST /admin/requests/{user_id}/{course_id}", sub="jess", email="jess@example.com", groups="[admins]",
                      params={"user_id": "u1", "course_id": COURSE}, body={"decision": "approved"})
    assert code == 200 and body["status"] == "approved"
    assert call(store, "GET /admin/requests", sub="jess", email="jess@example.com", groups="[admins]")[1]["requests"] == []
    # now unlocked
    code, body = call(store, "POST /courses/{course_id}/lessons/{lesson_id}/complete", params={"course_id": COURSE, "lesson_id": "01-welcome"})
    assert code == 200 and body["completed"] == ["01-welcome"]
    me = call(store, "GET /me")[1]
    assert me["enrolments"][COURSE]["status"] == "approved" and me["progress"][COURSE] == ["01-welcome"]
    code, body = call(store, "GET /courses/{course_id}/files/{file_id}", params={"course_id": COURSE, "file_id": "manual"})
    assert code == 200 and body["url"].startswith("https://signed/tlg-test-academy-files/builder-gel/") and body["expires_in"] == 300
    # requesting again after approval changes nothing
    assert call(store, "POST /courses/{course_id}/request", params={"course_id": COURSE})[1]["status"] == "approved"


def test_rejection_carries_a_note_and_can_be_requested_again(store):
    call(store, "POST /courses/{course_id}/request", params={"course_id": COURSE})
    code, body = call(store, "POST /admin/requests/{user_id}/{course_id}", sub="jess", email="jess@example.com", groups="[admins]",
                      params={"user_id": "u1", "course_id": COURSE}, body={"decision": "rejected", "note": "Please send your Level 2 certificate."})
    assert code == 200 and body["status"] == "rejected"
    me = call(store, "GET /me")[1]
    assert me["enrolments"][COURSE]["status"] == "rejected" and "Level 2" in me["enrolments"][COURSE]["note"]
    assert call(store, "GET /admin/requests", sub="jess", email="jess@example.com", groups="[admins]", query={"status": "rejected"})[1]["requests"][0]["user_id"] == "u1"
    assert call(store, "POST /courses/{course_id}/request", params={"course_id": COURSE})[1]["status"] == "pending"


def test_admin_by_email_fallback_and_bad_inputs(store):
    # ADMIN_EMAILS counts even before the group is attached
    assert call(store, "GET /me", sub="jess", email="jess@example.com")[1]["is_admin"] is True
    assert call(store, "POST /courses/{course_id}/request", params={"course_id": "nope"})[0] == 404
    assert call(store, "POST /courses/{course_id}/request", params={"course_id": "gel-polish"})[0] == 409  # placeholder course
    assert call(store, "GET /admin/requests", sub="jess", email="jess@example.com", query={"status": "weird"})[0] == 400
    code, body = call(store, "POST /admin/requests/{user_id}/{course_id}", sub="jess", email="jess@example.com", params={"user_id": "ghost", "course_id": COURSE}, body={"decision": "approved"})
    assert code == 404
    assert call(store, "GET /nothing")[0] == 404
    res = handler.lambda_handler({"routeKey": "GET /me", "requestContext": {}}, store=store)
    assert res["statusCode"] == 401


def test_post_confirmation_puts_admin_emails_in_the_group(monkeypatch):
    calls = []

    class Idp:
        def admin_add_user_to_group(self, **kw):
            calls.append(kw)

    ev = {"userPoolId": "pool", "userName": "abc", "request": {"userAttributes": {"email": "Jess@Example.com"}}}
    assert triggers.post_confirmation(ev, idp=Idp()) is ev
    assert calls == [{"UserPoolId": "pool", "Username": "abc", "GroupName": "admins"}]
    calls.clear()
    triggers.post_confirmation({"userPoolId": "pool", "userName": "x", "request": {"userAttributes": {"email": "ann@example.com"}}}, idp=Idp())
    assert calls == []
