"""The Instagram token refresher (plan job 18, 2026-10-27)."""
import datetime as dt
import json

from bot import ig_token

NOW = dt.datetime(2026, 11, 2, 7, 0, tzinfo=dt.timezone.utc)


class Http:
    """graph.instagram.com, scripted: which calls fail, and what refresh returns."""

    def __init__(self, fail=(), expires_in=5184000):
        self.fail, self.expires_in, self.calls = set(fail), expires_in, []

    def _resp(self, name, body):
        class R:
            status_code = 400 if name in self.fail else 200
            text = "nope"

            def json(inner):
                return body

        return R()

    def get(self, url, params, timeout):
        self.calls.append((url.rsplit("/", 1)[-1], dict(params)))
        if url.endswith("/me"):
            return self._resp("me", {"user_id": "178", "username": "lookingglassbeautysalons"})
        return self._resp("refresh", {"access_token": "NEW", "token_type": "bearer", "expires_in": self.expires_in})

    def post(self, url, params, timeout):
        self.calls.append(("subscribed_apps", dict(params)))
        return self._resp("subscribe", {"success": True})


def test_first_run_fills_in_the_account_subscribes_and_refreshes():
    http = Http()
    out, problems = ig_token.run({"access_token": "SEED"}, NOW, session=http)
    assert problems == []
    assert out["username"] == "lookingglassbeautysalons" and out["user_id"] == "178"
    assert out["access_token"] == "NEW" and out["refreshed_at"] == "2026-11-02T07:00:00+00:00"
    assert out["expires_at"] == "2027-01-01T07:00:00+00:00"  # 60 days from the refresh
    names = [c[0] for c in http.calls]
    assert names == ["me", "subscribed_apps", "refresh_access_token"]
    assert http.calls[1][1]["subscribed_fields"] == "messages"
    assert http.calls[2][1] == {"grant_type": "ig_refresh_token", "access_token": "SEED"}


def test_a_token_refreshed_today_is_left_alone_but_still_resubscribed():
    held = {"access_token": "T", "refreshed_at": (NOW - dt.timedelta(hours=3)).isoformat(), "expires_at": (NOW + dt.timedelta(days=59)).isoformat()}
    http = Http()
    out, problems = ig_token.run(held, NOW, session=http)
    assert problems == [] and out["access_token"] == "T"
    assert [c[0] for c in http.calls] == ["me", "subscribed_apps"]


def test_refresh_failure_is_only_reported_when_time_is_short():
    held = {"access_token": "T", "refreshed_at": (NOW - dt.timedelta(days=7)).isoformat(), "expires_at": (NOW + dt.timedelta(days=40)).isoformat()}
    out, problems = ig_token.run(held, NOW, session=Http(fail=["refresh"]))
    assert problems == [] and out["access_token"] == "T"  # plenty of time: try again next week

    held["expires_at"] = (NOW + dt.timedelta(days=5)).isoformat()
    out, problems = ig_token.run(held, NOW, session=Http(fail=["refresh"]))
    assert len(problems) == 2 and "refresh failed" in problems[0] and "runs out in 5 days" in problems[1]


def test_a_dead_token_is_reported_without_further_calls():
    http = Http(fail=["me"])
    out, problems = ig_token.run({"access_token": "T", "refreshed_at": NOW.isoformat()}, NOW, session=http)
    assert len(problems) == 1 and "no longer works" in problems[0]
    assert [c[0] for c in http.calls] == ["me"]


def test_empty_secret_asks_for_a_seed():
    out, problems = ig_token.run({}, NOW, session=Http())
    assert "generate one in the Meta console" in problems[0]


def test_lambda_writes_the_secret_back_and_reports(monkeypatch):
    stored = {"SecretString": json.dumps({"access_token": "SEED"})}
    puts, posted, published = [], [], []

    class SM:
        def get_secret_value(self, SecretId):
            return stored

        def put_secret_value(self, SecretId, SecretString):
            puts.append(json.loads(SecretString))

    class SNS:
        def publish(self, **kw):
            published.append(kw)

    class Boto:
        @staticmethod
        def client(name):
            return SM() if name == "secretsmanager" else SNS()

    monkeypatch.setitem(__import__("sys").modules, "boto3", Boto)
    monkeypatch.setenv("META_TOKEN_SECRET_ARN", "arn:token")
    monkeypatch.setenv("OPS_TOPIC_ARN", "arn:ops")
    monkeypatch.setattr(ig_token, "run", lambda held, now, session=None: ({**held, "access_token": "NEW"}, ["The Instagram token runs out in 3 days and could not be renewed."]))
    monkeypatch.setattr(ig_token.telegram, "post_handover", lambda text: posted.append(text) or True)

    summary = ig_token.lambda_handler({"source": "schedule"})
    assert puts == [{"access_token": "NEW"}] and summary["refreshed"] is True
    assert published[0]["TopicArn"] == "arn:ops" and "runs out in 3 days" in published[0]["Message"]
    assert posted and "docs/setup.md step 6" in posted[0]
