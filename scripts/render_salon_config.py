"""Render the bot's salon config file from the Terraform inputs.

The bots used to get the salon facts in a Lambda environment variable; with
the real menu (166 services) that is 49KB against Lambda's 4KB limit. So the
same facts are rendered to JSON at build time and shipped inside the bundle
as bot/salon_config.json, read through SALON_CONFIG_PATH.

Sources, the same files Terraform reads:
  terraform/salon.auto.tfvars            hand-written facts (hours, address, notes)
  terraform/fresha-menu.auto.tfvars.json staff and services, generated from Fresha

Usage: python scripts/render_salon_config.py terraform build/bot/bot/salon_config.json
(written as UTF-8 regardless of the console encoding; the menu has £ signs and emoji).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import hcl2


def render(terraform_dir: Path) -> dict:
    with open(terraform_dir / "salon.auto.tfvars", encoding="utf-8") as fh:
        salon = hcl2.load(fh)["salon"]
    menu = json.loads((terraform_dir / "fresha-menu.auto.tfvars.json").read_text(encoding="utf-8"))

    services = [
        {
            "category": s["category"],
            "name": s["name"],
            "price": s["price"],
            "duration": s["duration"],
            "staff": s.get("staff", []),
            "booking_link": s.get("booking_link", ""),
            "notes": s.get("notes", ""),
        }
        for s in menu["services"]
    ]
    staff = [
        {
            "name": m["name"],
            "role": m["role"],
            "booking_link": m.get("booking_link", ""),
            "services": m.get("services", []),
        }
        for _, m in sorted(menu["staff"].items())
    ]
    return {
        "salon_name": salon["name"],
        "address": salon["address"],
        "phone": salon["phone"],
        "opening_hours": salon["opening_hours"],
        "general_booking_link": salon["general_booking_link"],
        "extra_notes": salon.get("extra_notes", ""),
        "services": services,
        "staff": staff,
    }


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: render_salon_config.py <terraform dir> <output json>")
    terraform_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.write_text(json.dumps(render(terraform_dir), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
