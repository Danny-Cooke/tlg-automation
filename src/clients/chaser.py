"""Lambda: the confirmation chaser (plan job 14).

The salon's payment policy is card confirmation, so a new appointment stays
"unconfirmed" until the client taps Confirm in the email Fresha sent them
and adds a card. Every morning this looks at the mirrored client list for
appointments the day after tomorrow that are still unconfirmed, checks each
one live in Fresha (a client may have confirmed overnight), and sends the
client one text in Jess's voice asking them to find that email. One chase
per appointment, remembered on the client's row.

    {}                          chase (texts only go when CHASER_SEND_TEXTS is true)
    {"dry_run": true}           list who would be chased, send nothing
    {"date": "2026-10-30"}      chase that day instead of the day after tomorrow

Environment: CLIENTS_TABLE, FRESHA_SESSION_PARAM, OPS_TOPIC_ARN,
SMS_SENDER_ID, CHASER_SEND_TEXTS (false until the SMS sandbox is left),
CHASER_FRESHA_REMINDER (true also presses Fresha's own "Send reminder",
which re-sends its confirmation email), CHASER_EMAIL_SUBJECT (the subject
of the Fresha email the text points at), CHASER_TEXT (the template).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
import zoneinfo
from functools import lru_cache

from bot import fresha, fresha_session

from .store import ClientStore

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

SALON_TZ = zoneinfo.ZoneInfo(os.environ.get("SALON_TIMEZONE", "Europe/London"))
LEAD_DAYS = 2  # run in the morning, chase the day after tomorrow: 42 to 66 hours ahead
UNCONFIRMED = "UNCONFIRMED"  # Fresha's status for "booked, card confirmation still requested"
DEFAULT_SUBJECT = "Please confirm your appointment"
DEFAULT_TEXT = ("Hi {first}, still ok for {service} with {person} on {when}? Please tap Confirm in the email "
                "Fresha sent you, titled '{subject}'. Need to change it? Just message us x")
PROJECTION = ("client_id", "name", "first_name", "mobile", "upcoming", "chased", "in_fresha", "blocked")


def lambda_handler(event: dict, context=None) -> dict:
    event = event or {}
    session = fresha_session.get()
    if session is None:
        _ops("Confirmation chaser: no Fresha session",
             "Nobody was chased: the Fresha session parameter is unset or expired. Run scripts/fresha_session.py.")
        return {"error": "no Fresha session"}
    send = os.environ.get("CHASER_SEND_TEXTS", "false").lower() == "true"
    dry_run = bool(event.get("dry_run")) or not send
    try:
        out = run(fresha.Fresha(session), ClientStore(), dry_run=dry_run, target_date=event.get("date"),
                  send_fresha_reminder=os.environ.get("CHASER_FRESHA_REMINDER", "false").lower() == "true",
                  sender_id=os.environ.get("SMS_SENDER_ID", ""), texts_enabled=send)
    except fresha.SessionRejected as exc:
        _ops("Confirmation chaser: Fresha rejected the session", f"{exc}\nRun scripts/fresha_session.py.")
        return {"error": str(exc)}
    if out["candidates"]:
        _ops(f"Confirmation chaser: {out['chased'] if not dry_run else out['would_chase']} of {out['candidates']} "
             f"unconfirmed for {out['date']}" + (" (dry run)" if dry_run else ""), _report(out))
    return out


def run(f: fresha.Fresha, store: ClientStore, *, sms=None, now: dt.datetime | None = None, dry_run: bool = True,
        target_date: str | None = None, send_fresha_reminder: bool = False, sender_id: str = "", texts_enabled: bool = True) -> dict:
    now = now or dt.datetime.now(SALON_TZ)
    target = target_date or (now.date() + dt.timedelta(days=LEAD_DAYS)).isoformat()
    stamp = int(now.timestamp())
    lines: list[str] = []
    counts = {"date": target, "candidates": 0, "already_chased": 0, "no_mobile": 0, "confirmed_meanwhile": 0,
              "would_chase": 0, "chased": 0, "failed": 0, "dry_run": dry_run, "texts_enabled": texts_enabled}
    for row in store.all_rows(projection=PROJECTION):
        if not row.get("in_fresha", True) or row.get("blocked"):
            continue
        for appt in row.get("upcoming") or []:
            if appt.get("status") != UNCONFIRMED or str(appt.get("start") or "")[:10] != target:
                continue
            counts["candidates"] += 1
            appt_id = str(appt.get("id") or "")
            who = row.get("first_name") or (row.get("name") or "").split(" ")[0] or "there"
            label = f"{row.get('name') or who}: {_services(appt)} {_when(appt.get('start'))}"
            if any(str(c.get("appointment_id")) == appt_id for c in (row.get("chased") or [])):
                counts["already_chased"] += 1
                lines.append(f"  already chased: {label}")
                continue
            if not row.get("mobile"):
                counts["no_mobile"] += 1
                lines.append(f"  no mobile, ring them: {label}")
                continue
            try:
                live = f.view(appt_id)
            except fresha.SessionRejected:
                raise
            except fresha.FreshaError as exc:
                counts["failed"] += 1
                lines.append(f"  could not check Fresha: {label} ({exc})")
                continue
            if str(live.get("status") or "").upper() != UNCONFIRMED:
                counts["confirmed_meanwhile"] += 1
                lines.append(f"  now {str(live.get('status') or '?').lower()}: {label}")
                continue
            text = message(who, appt)
            if dry_run:
                counts["would_chase"] += 1
                lines.append(f"  would text: {label}")
                continue
            try:
                if send_fresha_reminder:
                    f.send_protection_reminder(appt_id)
                (sms or _sms()).send_text_message(**_sms_kwargs(row["mobile"], text, sender_id))
            except Exception as exc:  # noqa: BLE001 - one client's text must not stop the others
                counts["failed"] += 1
                log.error("Chase failed for client %s appointment %s: %s", row.get("client_id"), appt_id, exc)
                lines.append(f"  failed: {label}")
                continue
            store.mark_chased(row["client_id"], appt_id, now=stamp)
            counts["chased"] += 1
            lines.append(f"  texted: {label}")
    counts["lines"] = lines
    log.info("CONFIRMATION CHASER %s", json.dumps({k: v for k, v in counts.items() if k != "lines"}))
    return counts


def message(first: str, appt: dict) -> str:
    template = os.environ.get("CHASER_TEXT") or DEFAULT_TEXT
    services = appt.get("services") or [{}]
    return template.format(
        first=first, service=_services(appt), person=(services[0].get("with") or "us").split(" ")[0],
        when=_when(appt.get("start")), subject=os.environ.get("CHASER_EMAIL_SUBJECT") or DEFAULT_SUBJECT,
    )


def _services(appt: dict) -> str:
    names = [str(s.get("name") or "").strip() for s in (appt.get("services") or []) if s.get("name")]
    return " and ".join(dict.fromkeys(names)) or "your appointment"


def _when(start) -> str:
    """"2026-10-30T14:00:00[Europe/London]" -> "Thu 30 Oct at 2pm"."""
    raw = str(start or "")[:16]
    try:
        d = dt.datetime.fromisoformat(raw)
    except ValueError:
        return raw
    suffix = "am" if d.hour < 12 else "pm"
    hour = d.hour % 12 or 12
    clock = f"{hour}.{d.minute:02d}{suffix}" if d.minute else f"{hour}{suffix}"
    return f"{d:%a} {d.day} {d:%b} at {clock}"


def _sms_kwargs(number: str, text: str, sender_id: str) -> dict:
    kwargs = {"DestinationPhoneNumber": number, "MessageBody": text, "MessageType": "TRANSACTIONAL"}
    if sender_id:
        kwargs["OriginationIdentity"] = sender_id
    return kwargs


def _report(out: dict) -> str:
    head = [f"Appointments on {out['date']} still unconfirmed this morning: {out['candidates']}",
            f"Texted: {out['chased']}" if not out["dry_run"] else f"Would text: {out['would_chase']}",
            f"Confirmed since the mirror ran: {out['confirmed_meanwhile']}",
            f"No mobile on file: {out['no_mobile']}", f"Already chased: {out['already_chased']}", f"Failed: {out['failed']}"]
    if not out["texts_enabled"]:
        head.append("Texts are switched off (CHASER_SEND_TEXTS): nothing was sent.")
    return "\n".join(head + [""] + out.get("lines", []))


def _ops(subject: str, body: str) -> None:
    topic = os.environ.get("OPS_TOPIC_ARN")
    log.info("%s", subject)
    if not topic:
        return
    try:
        _sns().publish(TopicArn=topic, Subject=f"[TLG] {subject}"[:100], Message=body)
    except Exception:  # noqa: BLE001
        log.exception("Ops email failed")


@lru_cache(maxsize=1)
def _sns():
    import boto3

    return boto3.client("sns")


@lru_cache(maxsize=1)
def _sms():
    import boto3

    return boto3.client("pinpoint-sms-voice-v2")
