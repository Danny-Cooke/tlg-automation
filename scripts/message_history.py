"""Pull the Page's Messenger history and measure how the team talks to clients.

The persona in persona/ was built from this. Re-run it when the voice guide
needs refreshing or to check the bot against the humans.

    python scripts/message_history.py dump          # Graph API -> .local/messages/raw.json
    python scripts/message_history.py stats         # raw.json -> stats.json + a summary
    python scripts/message_history.py transcript    # raw.json -> transcript.txt (names redacted)

`dump` reads the Page token and app secret from Secrets Manager
(tlg-prod/meta/messenger) with your AWS profile; nothing is printed. Output
goes to .local/messages/, which is git-ignored because it holds client
messages. Instagram is not included: the Page token lacks
instagram_manage_messages.

What counts as a human reply: a message sent by the Page that is not one of
the AUTO_REPLIES below (Meta instant replies, ad greetings, Meta's "Business
AI" agent, our own test bot). The AI agent is detected by its templates and
by the spaced em dash it uses, which no one at the salon types.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import hmac
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / ".local" / "messages"
GRAPH = "https://graph.facebook.com/v21.0"
SECRET_ID = "tlg-prod/meta/messenger"

# Lower-case substrings. A Page message containing one is not a human reply.
AUTO_REPLIES = {
    "instant reply": "drifted gently into",
    "away message": "we're away and can't respond",
    "ad greeting": "please let us know how we can help you.",
    "ad system note": "replied to an ad.",
    "meta ai handoff": "ai agent will respond",
    "meta ai transfer": "ai agent transferred this chat",
    "meta ai template": "i've connected you with our team",
    "meta ai greeting": "thanks for reaching out to the looking glass",
    "meta ai brief": "i'll keep it brief",
    "fresha-first auto reply": "would you mind trying to book through fresha first",
    "our test bot": "tlg messenger test bot",
}
EM_DASH = " — "  # Meta's AI writes " — "; the team never does.

ENDEARMENTS = ["lovely", "lovey", "lovley", "beaut", "babe", "beautiful", "angel", "my love", "hun", "girl", "queen", "my girl"]
OPENERS = ["hey lovely", "hi lovely", "hello lovely", "hiya", "hey there", "hi there", "hey", "hi", "hello", "morning", "good morning"]
PHRASES = [
    "absolutely", "amazing", "ace", "brill", "brilliant", "fab", "perfect", "no problem", "no worries", "of course",
    "sure", "okay lovely", "bless", "pop", "all booked", "booked for you", "all in for you", "all sorted", "sorted",
    "i'll have a look", "let me check", "can i take", "email and phone", "phone number", "would you like me to book",
    "book you in", "book in", "fresha", "website", "consultation", "patch test", "deposit", "booking fee",
    "sorry for the", "so sorry", "hope you're okay", "can't wait", "see you", "let me know", "send", "picture", "inspo",
    "from £", "start from", "depending on", "thank you", "thankyou", "thanks",
]
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐❤♡♥❤️]")
KISS_RE = re.compile(r"(?:^|\s)(x{1,6}|c{1,3}|cx|xc|zxz|xxxd)\s*[.!]?\s*$", re.I)


def _ts(m: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(m["created_time"].replace("+0000", "+00:00"))


def _page_id(threads: list[dict]) -> str:
    counts = collections.Counter(
        p["id"] for t in threads for p in t["conversation"]["participants"]["data"]
    )
    return counts.most_common(1)[0][0]


def auto_reply_kind(text: str) -> str | None:
    low = text.lower()
    for kind, needle in AUTO_REPLIES.items():
        if needle in low:
            return kind
    if EM_DASH in text:
        return "meta ai (em dash)"
    return None


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


def dump() -> Path:
    import boto3
    import requests

    secret = json.loads(
        boto3.client("secretsmanager", region_name="eu-west-2").get_secret_value(SecretId=SECRET_ID)["SecretString"]
    )
    token, app_secret = secret["page_token"], secret["app_secret"]
    base = {"access_token": token, "appsecret_proof": hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()}

    def pages(url: str, params: dict) -> list[dict]:
        out: list[dict] = []
        while url:
            r = requests.get(url, params=params, timeout=60)
            if r.status_code >= 400:
                sys.exit(f"Graph API {r.status_code}: {r.text[:300]}")
            body = r.json()
            out.extend(body.get("data", []))
            url = body.get("paging", {}).get("next")
            params = base  # the next link drops appsecret_proof; put it back
        return out

    convs = pages(f"{GRAPH}/me/conversations", {**base, "fields": "id,updated_time,message_count,participants", "limit": 100})
    threads = []
    for c in convs:
        msgs = pages(
            f"{GRAPH}/{c['id']}/messages",
            {**base, "fields": "id,created_time,from,message,attachments{mime_type},shares{link}", "limit": 100},
        )
        threads.append({"conversation": c, "messages": msgs})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "raw.json"
    path.write_text(json.dumps(threads, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(threads)} conversations, {sum(len(t['messages']) for t in threads)} messages -> {path}")
    return path


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def classify(threads: list[dict]) -> dict:
    """Split every message into client / human page reply / auto reply."""
    page = _page_id(threads)
    human: list[tuple[dict, float | None]] = []  # (message, seconds since the client's last message)
    client: list[dict] = []
    auto = collections.Counter()
    for t in threads:
        last_client: dt.datetime | None = None
        for m in sorted(t["messages"], key=_ts):
            text = m.get("message") or ""
            if m["from"]["id"] != page:
                client.append(m)
                last_client = _ts(m)
                continue
            kind = auto_reply_kind(text)
            if kind:
                auto[kind] += 1
                continue
            latency = (_ts(m) - last_client).total_seconds() if last_client else None
            human.append((m, latency))
            last_client = None  # only the first reply to a client message counts for latency
    return {"page_id": page, "human": human, "client": client, "auto": auto}


def stats(threads: list[dict]) -> dict:
    c = classify(threads)
    human_texts = [m.get("message") or "" for m, _ in c["human"]]
    texts = [h for h in human_texts if h.strip()]
    dates = [_ts(m) for t in threads for m in t["messages"]]
    words = [len(h.split()) for h in texts]
    kisses = collections.Counter()
    for h in texts:
        mt = KISS_RE.search(h)
        if mt:
            kisses[mt.group(1).lower()] += 1
    emoji_msgs = [h for h in texts if EMOJI_RE.search(h)]
    emojis = collections.Counter(e for h in texts for e in EMOJI_RE.findall(h) if e != "️")

    def count(pattern: str) -> int:
        rx = re.compile(r"(?<!\w)" + re.escape(pattern) + r"(?!\w)", re.I)
        return sum(1 for h in texts if rx.search(h))

    latencies = [lat for _, lat in c["human"] if lat is not None]
    latencies_min = sorted(lat / 60 for lat in latencies)

    def pct_within(minutes: float) -> float:
        return round(100 * sum(1 for lat in latencies_min if lat <= minutes) / len(latencies_min), 1)

    threads_with_human = sum(
        1 for t in threads if any(m["from"]["id"] == c["page_id"] and not auto_reply_kind(m.get("message") or "") for m in t["messages"])
    )
    return {
        "date_range": [min(dates).date().isoformat(), max(dates).date().isoformat()],
        "threads": len(threads),
        "threads_with_a_human_reply": threads_with_human,
        "messages": sum(len(t["messages"]) for t in threads),
        "client_messages": len(c["client"]),
        "page_messages": len(c["human"]) + sum(c["auto"].values()),
        "auto_replies_removed": dict(c["auto"].most_common()),
        "human_replies": len(c["human"]),
        "words_per_reply": {
            "median": statistics.median(words),
            "mean": round(statistics.mean(words), 1),
            "p90": sorted(words)[int(0.9 * len(words))],
        },
        "ends_with_kisses_pct": round(100 * sum(kisses.values()) / len(texts), 1),
        "kiss_forms": dict(kisses.most_common()),
        "has_emoji_pct": round(100 * len(emoji_msgs) / len(texts), 1),
        "top_emojis": emojis.most_common(15),
        "has_question_pct": round(100 * sum(1 for h in texts if "?" in h) / len(texts), 1),
        "has_exclamation_pct": round(100 * sum(1 for h in texts if "!" in h) / len(texts), 1),
        "starts_lower_case_pct": round(100 * sum(1 for h in texts if h[:1].islower()) / len(texts), 1),
        "openers": {o: sum(1 for h in texts if h.lower().lstrip("!., ").startswith(o)) for o in OPENERS},
        "endearments": {e: count(e) for e in ENDEARMENTS},
        "phrases": {p: count(p) for p in PHRASES},
        "reply_latency_minutes": {
            "n": len(latencies_min),
            "median": round(statistics.median(latencies_min), 1),
            "within_5_min_pct": pct_within(5),
            "within_1_hour_pct": pct_within(60),
            "within_24_hours_pct": pct_within(24 * 60),
        },
    }


def summary(s: dict) -> str:
    lines = [
        f"{s['date_range'][0]} to {s['date_range'][1]}: {s['threads']} threads, {s['messages']} messages",
        f"client {s['client_messages']}, page {s['page_messages']} of which human {s['human_replies']}",
        "auto replies removed: " + ", ".join(f"{k} {v}" for k, v in s["auto_replies_removed"].items()),
        f"words per reply median {s['words_per_reply']['median']}, p90 {s['words_per_reply']['p90']}",
        f"kisses {s['ends_with_kisses_pct']}%  emoji {s['has_emoji_pct']}%  question {s['has_question_pct']}%  lower-case start {s['starts_lower_case_pct']}%",
        "top emojis: " + " ".join(f"{e}{n}" for e, n in s["top_emojis"][:10]),
        "openers: " + ", ".join(f"{k} {v}" for k, v in sorted(s["openers"].items(), key=lambda kv: -kv[1]) if v),
        "endearments: " + ", ".join(f"{k} {v}" for k, v in sorted(s["endearments"].items(), key=lambda kv: -kv[1]) if v),
        "phrases: " + ", ".join(f"{k} {v}" for k, v in sorted(s["phrases"].items(), key=lambda kv: -kv[1]) if v),
        f"reply latency: median {s['reply_latency_minutes']['median']} min, {s['reply_latency_minutes']['within_5_min_pct']}% within 5 min, "
        f"{s['reply_latency_minutes']['within_1_hour_pct']}% within an hour",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# transcript
# ---------------------------------------------------------------------------


def transcript(threads: list[dict]) -> str:
    """Readable threads with client names redacted. Auto replies are dropped."""
    page = _page_id(threads)
    out = []
    for t in sorted(threads, key=lambda t: t["conversation"]["updated_time"]):
        names = [p["name"] for p in t["conversation"]["participants"]["data"] if p["id"] != page]
        lines = []
        for m in sorted(t["messages"], key=_ts):
            text = (m.get("message") or "").replace("\n", " / ")
            if m.get("attachments"):
                text += " [attachment]"
            if m.get("shares"):
                text += " [share]"
            if m["from"]["id"] == page:
                if auto_reply_kind(text):
                    continue
                lines.append(f"  TLG  {_ts(m):%d %b %H:%M}: {text}")
            else:
                lines.append(f"  CLI  {_ts(m):%d %b %H:%M}: {text}")
        for n in names:
            for part in n.split():
                if len(part) > 2:
                    lines = [re.sub(re.escape(part), "[name]", line, flags=re.I) for line in lines]
        if lines:
            out.append(f"\n### thread {t['conversation']['id'][-6:]} ({len(lines)} msgs)")
            out.extend(lines)
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["dump", "stats", "transcript"])
    p.add_argument("--raw", type=Path, default=OUT_DIR / "raw.json")
    a = p.parse_args()
    if a.command == "dump":
        dump()
        return
    if not a.raw.exists():
        sys.exit(f"{a.raw} not found; run `dump` first")
    threads = json.loads(a.raw.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if a.command == "stats":
        s = stats(threads)
        (OUT_DIR / "stats.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        print(summary(s))
    else:
        path = OUT_DIR / "transcript.txt"
        path.write_text(transcript(threads), encoding="utf-8")
        print(f"-> {path}")


if __name__ == "__main__":
    main()
