"""Book, inspect and cancel Fresha appointments from the laptop, with the
session that scripts/fresha_session.py stored in SSM.

This is the same code path the bot will use (src/bot/fresha.py), driven by
hand so a real booking can be made and watched before Messenger is wired up.

    python scripts/fresha_book.py clients danny
    python scripts/fresha_book.py services --nails [--staff 3440861]
    python scripts/fresha_book.py slots --level 25845686 --staff 3440861 --date 2026-10-24 --minutes 60
    python scripts/fresha_book.py book --client 279113349 --level 25845686 --staff 3440861 \
        --date 2026-10-24 --time 11:00 --minutes 60 --price 34
    python scripts/fresha_book.py view 1331547555
    python scripts/fresha_book.py cancel 1331547555 [--notify]

Needs: requests, boto3 (requirements-ops.txt), the AWS "default" profile with
ssm:GetParameter on the session parameter. Never prints the cookie.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bot import fresha_session  # noqa: E402
from bot.fresha import Fresha, FreshaError, SessionRejected  # noqa: E402

DEFAULT_PARAM = "/tlg/prod/fresha/session"
NAIL_CATEGORIES = ("Senior Nail Services - TLG", "Nails by TLG")


def load_session(param: str, region: str, profile: str) -> fresha_session.Session:
    import boto3

    os.environ["FRESHA_SESSION_PARAM"] = param
    ssm = boto3.Session(profile_name=profile, region_name=region).client("ssm")
    session = fresha_session.get(ssm=ssm)
    if session is None:
        sys.exit(f"No usable Fresha session in {param}; run scripts/fresha_session.py first.")
    print(f"Session from {param}: {session.days_left()} days left")
    return session


def cmd_clients(f: Fresha, a) -> None:
    rows = f.find_clients(a.query, limit=a.limit)
    if not rows:
        print("no clients match")
    for c in rows:
        flags = " BLOCKED" if c.blocked else ""
        phone = "phone on file" if c.phone else "no phone"
        email = "email on file" if c.email else "no email"
        print(f"{c.id}  {c.name}  ({phone}, {email}){flags}")


def cmd_services(f: Fresha, a) -> None:
    rows = f.catalog(employee_id=a.staff or "")
    if a.nails:
        rows = [s for s in rows if s.category in NAIL_CATEGORIES]
    for s in rows:
        pt = " PATCH TEST" if s.patch_test else ""
        lvl = f" [{s.level_name}]" if s.level_name else ""
        print(f"level {s.pricing_level_id}  {s.category} / {s.name}{lvl}  £{s.price} {s.price_type}  {s.duration_s // 60} min  staff {','.join(s.employee_ids)}{pt}")
    print(f"{len(rows)} pricing levels")


def cmd_slots(f: Fresha, a) -> None:
    starts = f.available_starts(a.level, a.staff, a.date, a.minutes * 60)
    print(f"{a.date}: {len(starts)} possible starts")
    if starts:
        print("  " + " ".join(s[:5] for s in starts))


def cmd_book(f: Fresha, a) -> None:
    quote = f.quote(a.client, a.level, a.price)
    print(f"Payment policy Fresha will apply: {quote.strategy}, cancellation fee £{quote.cancellation_fee}, deposit £{quote.deposit}")
    clashes = f.conflicts(a.level, a.staff, a.date, a.time, a.minutes * 60)
    if clashes:
        print("Fresha reports conflicts for that slot:")
        for c in clashes:
            print("  ", c.get("conflictType"), {k: v for k, v in c.items() if k not in ("__typename", "conflictType")})
        if not a.force:
            sys.exit("Not booking. Pass --force to book anyway.")
    if a.dry_run:
        print("Dry run: not booking.")
        return
    b = f.create(customer_id=a.client, pricing_level_id=a.level, price=a.price, duration_s=a.minutes * 60,
                 employee_id=a.staff, date=a.date, start=a.time)
    print(f"BOOKED appointment {b.appointment_id} (booking {b.booking_id})")
    for w in b.warnings:
        print("  warning:", w)
    show(f.view(b.appointment_id))


def cmd_view(f: Fresha, a) -> None:
    show(f.view(a.id))


def cmd_upcoming(f: Fresha, a) -> None:
    rows = f.upcoming(a.client, first=a.limit)
    print(f"{len(rows)} upcoming appointment(s) for client {a.client}")
    for u in rows:
        print(f"  {u.appointment_id}  {u.date} {u.time}  {u.service} with {u.person}  £{u.price}  {u.status}")
    if a.fee:
        for u in rows:
            print(f"  fee to cancel {u.appointment_id} now: {f.cancellation_fee(u.appointment_id) or 'none'}")


def cmd_cancel(f: Fresha, a) -> None:
    print("cancelled", f.cancel(a.id, notify=a.notify))


def show(appt: dict) -> None:
    if not appt:
        print("no such appointment")
        return
    print(f"appointment {appt.get('id')}  status {appt.get('status')}  starts {appt.get('startWallClock')}  created {appt.get('createdAt')}")
    cust = appt.get("customer") or {}
    print(f"  client {appt.get('customerId')} {cust.get('firstName', '')}")
    for b in appt.get("bookings") or []:
        svc = (b.get("service") or {}).get("name")
        staff = ", ".join((e.get("employee") or {}).get("fullName", "") for e in b.get("employees") or [])
        secs = sum(int(t.get("durationInSeconds") or 0) for t in b.get("bookingTimeSegments") or [])
        print(f"  booking {b.get('id')}: {svc} with {staff}, {secs // 60} min, level {b.get('servicePricingLevelId')}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--param", default=DEFAULT_PARAM)
    p.add_argument("--region", default="eu-west-2")
    p.add_argument("--aws-profile", default="default")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("clients"); s.add_argument("query"); s.add_argument("--limit", type=int, default=10); s.set_defaults(fn=cmd_clients)
    s = sub.add_parser("services"); s.add_argument("--staff", default=""); s.add_argument("--nails", action="store_true"); s.set_defaults(fn=cmd_services)
    s = sub.add_parser("slots")
    for name in ("--level", "--staff", "--date"):
        s.add_argument(name, required=True)
    s.add_argument("--minutes", type=int, required=True); s.set_defaults(fn=cmd_slots)
    s = sub.add_parser("book")
    for name in ("--client", "--level", "--staff", "--date", "--time", "--price"):
        s.add_argument(name, required=True)
    s.add_argument("--minutes", type=int, required=True)
    s.add_argument("--force", action="store_true", help="book even if Fresha reports a conflict")
    s.add_argument("--dry-run", action="store_true", help="quote and conflict-check only")
    s.set_defaults(fn=cmd_book)
    s = sub.add_parser("view"); s.add_argument("id"); s.set_defaults(fn=cmd_view)
    s = sub.add_parser("upcoming"); s.add_argument("client"); s.add_argument("--limit", type=int, default=10)
    s.add_argument("--fee", action="store_true", help="also ask Fresha what cancelling each one now would charge")
    s.set_defaults(fn=cmd_upcoming)
    s = sub.add_parser("cancel"); s.add_argument("id"); s.add_argument("--notify", action="store_true"); s.set_defaults(fn=cmd_cancel)

    a = p.parse_args(argv)
    f = Fresha(load_session(a.param, a.region, a.aws_profile))
    try:
        a.fn(f, a)
    except SessionRejected as e:
        print(e)
        print("Run scripts/fresha_session.py to log in again.")
        return 2
    except FreshaError as e:
        print("Fresha error:", e)
        return 3
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    sys.exit(main())
