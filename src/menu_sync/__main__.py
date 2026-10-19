"""Run the sync from a laptop.

    python -m menu_sync --venue-url URL --out terraform/fresha-menu.auto.tfvars.json

Writes the generated file and prints what changed against the existing one.
No GitHub, no AWS.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import model
from .handler import read_fresha


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the Terraform menu file from Fresha")
    ap.add_argument("--venue-url", required=True, help="Fresha venue page, e.g. https://www.fresha.com/en-GB/a/<slug>")
    ap.add_argument("--out", default=model.MENU_FILE, help="where to write the JSON tfvars file")
    ap.add_argument("--check", action="store_true", help="exit 1 if the file would change; do not write")
    args = ap.parse_args(argv)

    menu = read_fresha(requests.Session(), args.venue_url)
    out = Path(args.out)
    old = model.content_of(model.parse_existing(out.read_text(encoding="utf-8") if out.exists() else None))
    changes = model.describe_changes(old, menu.content())
    if old == menu.content():
        print(f"{out}: unchanged ({len(menu.staff)} staff, {len(menu.services)} services)")
        return 0
    for line in changes:
        print(line)
    if args.check:
        return 1
    out.write_text(model.render(menu.document(datetime.now(timezone.utc).strftime("%Y-%m-%d"))), encoding="utf-8")
    print(f"wrote {out}: {len(menu.staff)} staff, {len(menu.services)} services")
    return 0


if __name__ == "__main__":
    sys.exit(main())
