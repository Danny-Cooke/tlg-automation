"""Conversation state in DynamoDB.

One item per sender. Holds the recent turns, the hand-over flag, and the
set of message ids we have already answered (Meta retries deliveries).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from functools import lru_cache

MAX_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "20"))
TTL_DAYS = int(os.environ.get("STATE_TTL_DAYS", "30"))
SEEN_IDS_KEPT = 50


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

    # With these people the bot keeps reading the thread and answers only what
    # is not theirs (user, 2026-10-24: a hair client with Lori who asks about
    # nails gets the bot back for nails). With Jess the bot is silent.
    WATCHED = ("lori-dee", "carmen")

    def has_seen(self, message_id: str) -> bool:
        return bool(message_id) and message_id in self.seen_message_ids

    def watching(self) -> bool:
        """Handed to Lori-Dee or Carmen: still read every message, answer only what is ours."""
        return self.handed_to_jess and self.handed_to in self.WATCHED

    def hand_over(self, to: str, area: str) -> None:
        self.handed_to_jess = True
        self.handed_to = to or "jess"
        self.handed_area = area or "general"

    def note_message(self, message_id: str, user_text: str) -> None:
        """Listen mode: remember the message and keep it as context, no reply."""
        if message_id:
            self.seen_message_ids = (self.seen_message_ids + [message_id])[-SEEN_IDS_KEPT:]
        self.history = (self.history + [{"role": "user", "content": user_text}])[-(MAX_TURNS * 2):]

    def mark_seen(self, message_id: str) -> None:
        """Claim the message before the slow part, so a Meta retry that lands
        while Claude is thinking is dropped as a duplicate."""
        if message_id and message_id not in self.seen_message_ids:
            self.seen_message_ids = (self.seen_message_ids + [message_id])[-SEEN_IDS_KEPT:]

    def record_turn(self, message_id: str, user_text: str, bot_text: str) -> None:
        """A reply sent. An empty one (an opening message left for Jess) is kept
        as the client's turn only, so the model never sees a blank answer."""
        if not bot_text.strip():
            self.note_message(message_id, user_text)
            return
        self.mark_seen(message_id)
        self.history += [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": bot_text},
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
        if not item:
            return Conversation(sender_id=sender_id)
        return Conversation(
            sender_id=sender_id,
            channel=item.get("channel", ""),
            history=list(item.get("history", [])),
            handed_to_jess=bool(item.get("handed_to_jess", False)),
            seen_message_ids=list(item.get("seen_message_ids", [])),
            client_name=item.get("client_name", ""),
            bookings=[dict(b) for b in item.get("bookings", [])],
            handed_to=item.get("handed_to", ""),
            handed_area=item.get("handed_area", ""),
            fresha_client_id=item.get("fresha_client_id", ""),
            fresha_client_name=item.get("fresha_client_name", ""),
            staff=bool(item.get("staff", False)),
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
                "updated_at": int(time.time()),
                "expires_at": int(time.time()) + TTL_DAYS * 86400,
            }
        )

    def clear_handover(self, sender_id: str) -> None:
        self.table.update_item(
            Key={"sender_id": sender_id},
            UpdateExpression="SET handed_to_jess = :f, handed_to = :e, handed_area = :e",
            ExpressionAttributeValues={":f": False, ":e": ""},
        )


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
