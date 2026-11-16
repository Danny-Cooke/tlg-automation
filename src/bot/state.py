"""Conversation state in DynamoDB.

One item per sender. Holds the recent turns, the hand-over flag, and the
set of message ids we have already answered (Meta retries deliveries).

What the team themselves send from the inbox (Meta's echoes, plan job 9
as rebuilt 2026-11-16) lives on a second row, `team#<sender id>`, written
with an atomic append and never by `save`: an echo lands while another
invocation is mid-reply holding its own copy of the conversation, and a
whole-item put from there must not wipe it out.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from functools import lru_cache

MAX_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "20"))
TTL_DAYS = int(os.environ.get("STATE_TTL_DAYS", "30"))
SEEN_IDS_KEPT = 50
TEAM_TURNS_KEPT = 20
# How a message a person on the team sent from the inbox is shown to the model
# and in the hand-over email, so neither takes it for the bot's own words.
TEAM_MARK = "[sent by the team from the inbox]"
# After one of the team replies on a thread the bot says nothing there for
# this long: the conversation is theirs while they are in it (user, 2026-11-16).
TEAM_QUIET_SECONDS = int(float(os.environ.get("TEAM_QUIET_MINUTES", "30")) * 60)
# A hand-over on a thread nobody has written on for this long is over: the
# next message starts fresh (the backstop agreed for job 9, 2026-10-22).
HANDOVER_IDLE_SECONDS = int(float(os.environ.get("HANDOVER_IDLE_DAYS", "7")) * 86400)


@dataclass
class Conversation:
    sender_id: str
    channel: str = ""
    history: list[dict] = field(default_factory=list)
    handed_to_jess: bool = False  # the thread is with a person; the name is historical, see handed_to
    seen_message_ids: list[str] = field(default_factory=list)
    client_name: str = ""
    bookings: list[dict] = field(default_factory=list)  # appointments the bot put into Fresha for this thread
    handed_to: str = ""  # jess | carmen | lori-dee, when handed_to_jess is True
    handed_area: str = ""  # what was handed over: hair, tattoos, nails ...
    fresha_client_id: str = ""  # the Fresha client this thread books for, once matched by phone or created (job 13)
    fresha_client_name: str = ""
    staff: bool = False  # a staff member's own thread: never answered (user, 2026-10-25); set by name match or by hand
    handed_kind: str = ""  # why it was handed over: complaint, quote ...
    alerted_at: int = 0  # when the team was last told about this thread (Telegram and email), epoch seconds
    updated_at: int = 0  # when the row was last saved; read from the table, written by save
    # From the team row, never written by save: what the team sent from the inbox and when they last did.
    team_turns: list[dict] = field(default_factory=list)  # {"at": epoch seconds, "content": str, "mid": str}
    team_last_at: int = 0

    def has_seen(self, message_id: str) -> bool:
        return bool(message_id) and message_id in self.seen_message_ids

    def hand_over(self, to: str, area: str, kind: str = "") -> None:
        self.handed_to_jess = True
        self.handed_to = to or "jess"
        self.handed_area = area or "general"
        self.handed_kind = kind

    def clear_handover(self) -> None:
        self.handed_to_jess = False
        self.handed_to = self.handed_area = self.handed_kind = ""

    def team_active(self, now: float | None = None) -> bool:
        """Has one of the team replied here in the last TEAM_QUIET_SECONDS? Then it is their conversation."""
        return bool(self.team_last_at) and (now or time.time()) - self.team_last_at < TEAM_QUIET_SECONDS

    def handover_lapsed(self, now: float | None = None) -> bool:
        """Handed over, and neither the client, the bot nor the team has written for HANDOVER_IDLE_SECONDS."""
        last = max(self.updated_at, self.team_last_at)
        return self.handed_to_jess and bool(last) and (now or time.time()) - last > HANDOVER_IDLE_SECONDS

    def thread(self) -> list[dict]:
        """The conversation as it happened, for the model and the hand-over
        email: the client's and the bot's turns with the team's inbox replies
        slotted in by time, each marked TEAM_MARK. Turns stored before turns
        were timed keep their order and come first."""
        timed, at = [], 0
        for i, turn in enumerate(self.history):
            at = max(at, int(turn.get("at") or 0))
            timed.append((at, 0, i, {"role": turn["role"], "content": turn["content"]}))
        for i, turn in enumerate(self.team_turns):
            timed.append((int(turn.get("at") or 0), 1, i, {"role": "assistant", "content": f"{TEAM_MARK} {turn.get('content', '')}"}))
        return [t[3] for t in sorted(timed, key=lambda t: t[:3])]

    def drop_reply(self, bot_text: str) -> None:
        """Take back the reply recorded for sending when it was never sent (the team answered first)."""
        for i in range(len(self.history) - 1, -1, -1):
            turn = self.history[i]
            if turn.get("role") == "assistant":
                if turn.get("content") == bot_text:
                    del self.history[i]
                return

    def note_message(self, message_id: str, user_text: str, at: float = 0) -> None:
        """Listen mode: remember the message and keep it as context, no reply."""
        if message_id:
            self.seen_message_ids = (self.seen_message_ids + [message_id])[-SEEN_IDS_KEPT:]
        self.history = (self.history + [{"role": "user", "content": user_text, "at": int(at or time.time())}])[-(MAX_TURNS * 2):]

    def mark_seen(self, message_id: str) -> None:
        """Claim the message before the slow part, so a Meta retry that lands
        while Claude is thinking is dropped as a duplicate."""
        if message_id and message_id not in self.seen_message_ids:
            self.seen_message_ids = (self.seen_message_ids + [message_id])[-SEEN_IDS_KEPT:]

    def record_turn(self, message_id: str, user_text: str, bot_text: str, at: float = 0) -> None:
        """A reply sent. An empty one (an opening message left for Jess) is kept
        as the client's turn only, so the model never sees a blank answer.
        `at` is when the client's message arrived; the reply is timed now."""
        if not bot_text.strip():
            self.note_message(message_id, user_text, at)
            return
        self.mark_seen(message_id)
        now = int(time.time())
        self.history += [
            {"role": "user", "content": user_text, "at": min(int(at or now), now)},
            {"role": "assistant", "content": bot_text, "at": now},
        ]
        self.history = self.history[-(MAX_TURNS * 2):]


class ConversationStore:
    """Thin DynamoDB wrapper. Pass a table resource for tests."""

    def __init__(self, table=None):
        self._table = table

    @property
    def table(self):
        if self._table is None:
            self._table = _default_table()
        return self._table

    def load(self, sender_id: str) -> Conversation:
        item = self.table.get_item(Key={"sender_id": sender_id}).get("Item")
        team = self.table.get_item(Key={"sender_id": team_key(sender_id)}).get("Item") or {}
        team_fields = dict(
            team_turns=[dict(t) for t in team.get("turns", [])][-TEAM_TURNS_KEPT:],
            team_last_at=int(team.get("last_at") or 0),
        )
        if not item:
            return Conversation(sender_id=sender_id, **team_fields)
        return Conversation(
            sender_id=sender_id,
            channel=item.get("channel", ""),
            history=[dict(t) for t in item.get("history", [])],
            handed_to_jess=bool(item.get("handed_to_jess", False)),
            seen_message_ids=list(item.get("seen_message_ids", [])),
            client_name=item.get("client_name", ""),
            bookings=[dict(b) for b in item.get("bookings", [])],
            handed_to=item.get("handed_to", ""),
            handed_area=item.get("handed_area", ""),
            fresha_client_id=item.get("fresha_client_id", ""),
            fresha_client_name=item.get("fresha_client_name", ""),
            staff=bool(item.get("staff", False)),
            handed_kind=item.get("handed_kind", ""),
            alerted_at=int(item.get("alerted_at") or 0),
            updated_at=int(item.get("updated_at") or 0),
            **team_fields,
        )

    def save(self, convo: Conversation) -> None:
        self.table.put_item(
            Item={
                "sender_id": convo.sender_id,
                "channel": convo.channel,
                "history": convo.history,
                "handed_to_jess": convo.handed_to_jess,
                "seen_message_ids": convo.seen_message_ids,
                "client_name": convo.client_name,
                "bookings": convo.bookings,
                "handed_to": convo.handed_to,
                "handed_area": convo.handed_area,
                "fresha_client_id": convo.fresha_client_id,
                "fresha_client_name": convo.fresha_client_name,
                "staff": convo.staff,
                "handed_kind": convo.handed_kind,
                "alerted_at": convo.alerted_at,
                "updated_at": int(time.time()),
                "expires_at": int(time.time()) + TTL_DAYS * 86400,
            }
        )

    def clear_handover(self, sender_id: str) -> None:
        self.table.update_item(
            Key={"sender_id": sender_id},
            UpdateExpression="SET handed_to_jess = :f, handed_to = :e, handed_area = :e, handed_kind = :e",
            ExpressionAttributeValues={":f": False, ":e": ""},
        )

    def note_team(self, sender_id: str, content: str, at: int, message_id: str = "") -> None:
        """One of the team sent `content` to this client from the inbox.
        Appended to the team row in one atomic update, so it survives whatever
        another invocation is doing with the conversation row."""
        turn = {"at": int(at), "content": content, "mid": message_id}
        out = self.table.update_item(
            Key={"sender_id": team_key(sender_id)},
            UpdateExpression="SET last_at = :at, turns = list_append(if_not_exists(turns, :none), :turn), expires_at = :exp",
            ExpressionAttributeValues={":at": int(at), ":none": [], ":turn": [turn], ":exp": int(time.time()) + TTL_DAYS * 86400},
            ReturnValues="ALL_NEW",
        )
        turns = ((out or {}).get("Attributes") or {}).get("turns", [])
        if len(turns) > TEAM_TURNS_KEPT * 2:  # keep the row small; an append lost to this rare trim is only context
            self.table.update_item(
                Key={"sender_id": team_key(sender_id)},
                UpdateExpression="SET turns = :kept",
                ExpressionAttributeValues={":kept": list(turns)[-TEAM_TURNS_KEPT:]},
            )

    def team_last_at(self, sender_id: str) -> int:
        """When the team last replied to this client, read fresh: asked just before a reply is sent."""
        item = self.table.get_item(Key={"sender_id": team_key(sender_id)}).get("Item") or {}
        return int(item.get("last_at") or 0)


def team_key(sender_id: str) -> str:
    return f"team#{sender_id}"


def claim_daily(store: "ConversationStore", name: str, day: str) -> bool:
    """True the first time `name` is claimed for `day`, False after that, whichever
    container asks: a sentinel row `_<name>` keyed like a conversation, written
    with a condition. Used for once-a-day team nags (2026-10-25)."""
    from botocore.exceptions import ClientError

    try:
        store.table.put_item(
            Item={"sender_id": f"_{name}", "day": day, "expires_at": int(time.time()) + 7 * 86400},
            ConditionExpression="attribute_not_exists(sender_id) OR #d < :day",
            ExpressionAttributeNames={"#d": "day"},
            ExpressionAttributeValues={":day": day},
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


@lru_cache(maxsize=1)
def _default_table():
    import boto3

    name = os.environ["CONVERSATIONS_TABLE"]
    return boto3.resource("dynamodb").Table(name)
