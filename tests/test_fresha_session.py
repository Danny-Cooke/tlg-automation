"""The Fresha session parameter: parsing, caching, expiry, and the laptop script's verify step."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

from bot import fresha_session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fresha_session as script  # noqa: E402  (scripts/fresha_session.py)

UTC = dt.timezone.utc


class Ssm:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def get_parameter(self, Name, WithDecryption):
        self.calls += 1
        assert WithDecryption is True
        if self.value is None:
            raise RuntimeError("ParameterNotFound")
        return {"Parameter": {"Value": self.value}}


def doc(cookie="abc", expires="2026-11-19T16:05:55+00:00"):
    return json.dumps({"cookie": cookie, "expires_at": expires, "refreshed_at": "2026-10-20T16:05:55+00:00"})


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("FRESHA_SESSION_PARAM", "/tlg/test/fresha/session")
    fresha_session.forget()
    yield
    fresha_session.forget()


def test_parse_document_and_placeholder():
    s = fresha_session.parse(doc())
    assert s.cookie == "abc"
    assert s.expires_at == dt.datetime(2026, 11, 19, 16, 5, 55, tzinfo=UTC)
    assert s.cookies() == {"fresha_partners_session": "abc"}
    assert fresha_session.parse("unset") is None
    assert fresha_session.parse("") is None
    assert fresha_session.parse("not json") is None
    assert fresha_session.parse(json.dumps({"expires_at": "x"})) is None


def test_get_reads_once_then_caches():
    ssm = Ssm(doc())
    now = dt.datetime(2026, 10, 21, tzinfo=UTC)
    assert fresha_session.get(ssm=ssm, now=now).cookie == "abc"
    assert fresha_session.get(ssm=ssm, now=now).cookie == "abc"
    assert ssm.calls == 1
    fresha_session.forget()
    fresha_session.get(ssm=ssm, now=now)
    assert ssm.calls == 2


def test_expired_session_is_none():
    ssm = Ssm(doc(expires="2026-10-01T00:00:00+00:00"))
    assert fresha_session.get(ssm=ssm, now=dt.datetime(2026, 10, 21, tzinfo=UTC)) is None


def test_missing_parameter_or_env_is_none(monkeypatch):
    assert fresha_session.get(ssm=Ssm(None)) is None
    assert fresha_session.get(ssm=Ssm("unset")) is None
    monkeypatch.delenv("FRESHA_SESSION_PARAM")
    assert fresha_session.get(ssm=Ssm(doc())) is None


def test_days_left():
    s = fresha_session.parse(doc())
    assert s.days_left(dt.datetime(2026, 10, 20, 16, 5, 55, tzinfo=UTC)) == 30
    assert s.days_left(dt.datetime(2026, 12, 1, tzinfo=UTC)) == 0


class Http:
    """What the script's probe sees: records the call, answers as told."""

    def __init__(self, status=200, body=None):
        self.status, self.body, self.calls = status, body, []

    def post(self, url, **kw):
        self.calls.append((url, kw))

        class R:
            status_code = self.status

            def json(inner):
                if self.body is None:
                    raise ValueError
                return self.body

        return R()


def test_script_verify_sends_only_the_session_cookie_form_encoded():
    http = Http(body={"data": {"__typename": "Query", "profileDetails": {"location": "Shrewsbury, United Kingdom"}}})
    assert script.verify("abc", http=http) == "Shrewsbury, United Kingdom"
    url, kw = http.calls[0]
    assert url == script.GRAPHQL
    assert kw["cookies"] == {"fresha_partners_session": "abc"}
    assert kw["data"]["operationName"] == "users_profileDetails"
    assert kw["params"]["_query"] == "users_profileDetails"
    assert "json" not in kw  # form-encoded, as the dashboard sends it


def test_script_verify_rejects_a_dead_session(capsys):
    assert script.verify("abc", http=Http(status=401, body={"errors": [{"message": "unauthenticated"}]})) is None
    assert script.verify("abc", http=Http(status=200, body={"data": {"profileDetails": None}})) is None
    assert "Probe failed" in capsys.readouterr().out


def test_lambda_probe_matches_the_script_and_never_raises(caplog):
    s = fresha_session.parse(doc())
    http = Http(body={"data": {"profileDetails": {"location": "Shrewsbury, United Kingdom"}}})
    assert fresha_session.probe(s, http, owner_id="1453889") == "Shrewsbury, United Kingdom"
    url, kw = http.calls[0]
    assert kw["cookies"] == {"fresha_partners_session": "abc"}
    assert kw["params"]["__pid"] == "1453889"
    assert kw["data"]["query"] == script.PROBE  # the laptop and the Lambda ask the same thing
    assert fresha_session.probe(s, Http(status=401, body={"errors": []})) is None
    assert fresha_session.probe(s, Http(status=500, body=None)) is None
    assert "abc" not in caplog.text


def test_handler_check_logs_and_survives_without_a_session(monkeypatch, caplog):
    from bot import handler

    monkeypatch.delenv("FRESHA_SESSION_PARAM", raising=False)
    handler.fresha_session_check.cache_clear()
    with caplog.at_level("INFO"):
        assert handler.fresha_session_check() is False
    assert "FRESHA SESSION none" in caplog.text
    handler.fresha_session_check.cache_clear()


def test_script_never_prints_the_cookie(capsys):
    script.verify("SECRETCOOKIE", http=Http(status=500, body=None))
    assert "SECRETCOOKIE" not in capsys.readouterr().out
