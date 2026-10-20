import hashlib
import hmac
import json

from bot import meta


def test_user_profile_asks_each_channel_only_for_fields_it_allows():
    """Messenger rejects `username` outright (error #12), so the field list is per channel."""
    calls = []

    class Http:
        def get(self, url, params, timeout):
            calls.append(params["fields"])

            class R:
                status_code = 200

                def json(self):
                    return {"first_name": "Danny", "last_name": "Cooke", "id": "1"}

            return R()

    assert meta.user_profile("1", "tok", channel="messenger", session=Http()) == {"first_name": "Danny", "last_name": "Cooke"}
    meta.user_profile("1", "tok", channel="instagram", session=Http())
    assert calls == ["first_name,last_name,name", "name,username"]
    assert meta.display_name({"first_name": "Danny", "last_name": "Cooke"}) == "Danny Cooke"
    assert meta.display_name({"username": "tlg"}) == "tlg" and meta.display_name({}) == ""

SECRET = "app-secret"


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_verify_challenge():
    q = {"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "12345"}
    assert meta.verify_challenge(q, "tok") == "12345"
    assert meta.verify_challenge({**q, "hub.verify_token": "wrong"}, "tok") is None
    assert meta.verify_challenge({}, "tok") is None


def test_verify_signature():
    body = b'{"object":"page"}'
    assert meta.verify_signature(body, sign(body), SECRET)
    assert not meta.verify_signature(body, sign(b"other"), SECRET)
    assert not meta.verify_signature(body, None, SECRET)
    assert not meta.verify_signature(body, "md5=abc", SECRET)


def messenger_body(text="hi", echo=False, mid="m1"):
    msg = {"mid": mid, "text": text}
    if echo:
        msg["is_echo"] = True
    return {
        "object": "page",
        "entry": [
            {
                "id": "page1",
                "time": 1,
                "messaging": [
                    {
                        "sender": {"id": "psid1"},
                        "recipient": {"id": "page1"},
                        "timestamp": 1700000000000,
                        "message": msg,
                    }
                ],
            }
        ],
    }


def test_parse_messenger_text():
    [m] = meta.parse_events(messenger_body("Can I book nails?"))
    assert m.channel == "messenger"
    assert m.sender_id == "psid1"
    assert m.text == "Can I book nails?"
    assert m.message_id == "m1"


def test_parse_skips_echo_and_non_message_events():
    assert meta.parse_events(messenger_body(echo=True)) == []
    body = messenger_body()
    body["entry"][0]["messaging"][0] = {"sender": {"id": "x"}, "recipient": {"id": "y"}, "delivery": {}}
    assert meta.parse_events(body) == []


def test_parse_instagram_object():
    body = messenger_body("hey")
    body["object"] = "instagram"
    [m] = meta.parse_events(body)
    assert m.channel == "instagram"


def test_parse_unknown_object():
    assert meta.parse_events({"object": "user", "entry": []}) == []


def test_chunk_text_splits_on_whitespace():
    long = " ".join(["word"] * 500)
    chunks = list(meta.chunk_text(long, limit=100))
    assert all(len(c) <= 100 for c in chunks)
    assert " ".join(chunks) == long


def test_send_text_posts_expected_payload():
    calls = []

    class FakeResp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"message_id": "out1"}

    class FakeSession:
        def post(self, url, **kw):
            calls.append((url, kw))
            return FakeResp()

    out = meta.send_text("psid1", "Hello!", "token", session=FakeSession())
    assert out == {"message_id": "out1"}
    url, kw = calls[0]
    assert url.endswith("/me/messages")
    assert kw["params"] == {"access_token": "token"}
    assert kw["json"]["recipient"] == {"id": "psid1"}

    # With the app secret the call carries the proof Meta's "Require app secret" setting demands.
    meta.send_text("psid1", "Hello!", "token", app_secret="shh", session=FakeSession())
    _, kw = calls[1]
    assert kw["params"]["appsecret_proof"] == meta.appsecret_proof("token", "shh")
    assert len(kw["params"]["appsecret_proof"]) == 64
    assert kw["json"]["message"] == {"text": "Hello!"}
    json.dumps(kw["json"])  # serialisable
