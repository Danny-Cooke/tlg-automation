"""Turn Fresha's team and menu into the Terraform menu file, and diff versions.

The generated file is terraform/fresha-menu.auto.tfvars.json. Terraform loads
*.auto.tfvars.json on its own, so the file only has to contain the variables
it owns: staff, services and menu_snapshot_date. Hand-written facts stay in
salon.auto.tfvars.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .fresha_public import MenuCategory, TeamMember

MENU_FILE = "terraform/fresha-menu.auto.tfvars.json"
NOTES_MAX = 220


@dataclass
class Menu:
    """What the Terraform variables should say."""

    staff: dict[str, dict] = field(default_factory=dict)  # slug -> staff object
    services: list[dict] = field(default_factory=list)

    def content(self) -> dict:
        """The part that is compared between runs. No dates, so an unchanged
        menu produces an identical document."""
        return {"staff": self.staff, "services": self.services}

    def document(self, snapshot_date: str) -> dict:
        return {"menu_snapshot_date": snapshot_date, **self.content()}


def display_name(name: str) -> str:
    """Fresha shows names exactly as typed into the team profile, so a lower
    case first letter ("carmen") gets through. Capitalise the first character
    only; everything else ("Lori-Dee", "McKay") is left alone."""
    return name[:1].upper() + name[1:] if name else name


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "unnamed"


def build_menu(
    venue_url: str,
    team: list[TeamMember],
    full_menu: list[MenuCategory],
    per_person: dict[str, list[MenuCategory]],
) -> Menu:
    """Combine the full menu with each person's own menu to get who does what.

    per_person maps employee id -> the categories that person can be booked for.
    """
    # (category, service name) -> [staff first names], in team order
    doers: dict[tuple[str, str], list[str]] = {}
    categories_by_person: dict[str, set[str]] = {m.employee_id: set() for m in team}
    for member in team:
        for cat in per_person.get(member.employee_id, []):
            for item in cat.items:
                doers.setdefault((cat.name, item.name), []).append(display_name(member.name))
                categories_by_person[member.employee_id].add(cat.name)

    category_order = {cat.name: i for i, cat in enumerate(full_menu)}

    staff: dict[str, dict] = {}
    for member in team:
        slug = _unique_slug(slugify(member.name), staff)
        staff[slug] = {
            "name": display_name(member.name),
            "role": member.job_title,
            "employee_id": member.employee_id,
            "booking_link": f"{venue_url.rstrip('/')}/booking?employeeId={member.employee_id}",
            "services": sorted(categories_by_person[member.employee_id], key=lambda c: category_order.get(c, 999)),
        }

    services: list[dict] = []
    for cat in full_menu:
        for item in cat.items:
            services.append(
                {
                    "category": cat.name,
                    "name": item.name,
                    "price": item.price,
                    "duration": item.duration,
                    "staff": doers.get((cat.name, item.name), []),
                    "notes": _notes(item.description),
                }
            )

    return Menu(
        staff=dict(sorted(staff.items())),
        services=sorted(services, key=lambda s: (s["category"].lower(), s["name"].lower())),
    )


def _unique_slug(slug: str, taken: dict) -> str:
    candidate, n = slug, 2
    while candidate in taken:
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


def _notes(description: str) -> str:
    if len(description) <= NOTES_MAX:
        return description
    cut = description.rfind(" ", 0, NOTES_MAX)
    return description[: cut if cut > 0 else NOTES_MAX].rstrip(" ,;") + "..."


def render(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def parse_existing(text: str | None) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def content_of(document: dict | None) -> dict | None:
    if document is None:
        return None
    return {"staff": document.get("staff", {}), "services": document.get("services", [])}


# ---------------------------------------------------------------------------
# Diff, for the PR body and the alert
# ---------------------------------------------------------------------------


def describe_changes(old: dict | None, new: dict) -> list[str]:
    """Human-readable lines. Empty list means nothing changed."""
    if old is None:
        return ["First menu snapshot; no previous file to compare with."]
    lines: list[str] = []

    old_staff, new_staff = old.get("staff", {}), new["staff"]
    for slug in sorted(set(new_staff) - set(old_staff)):
        lines.append(f"Staff added: {new_staff[slug]['name']} ({new_staff[slug].get('role', '')})")
    for slug in sorted(set(old_staff) - set(new_staff)):
        lines.append(f"Staff removed: {old_staff[slug]['name']}")
    for slug in sorted(set(old_staff) & set(new_staff)):
        a, b = old_staff[slug], new_staff[slug]
        for key in ("name", "role", "booking_link", "services"):
            if a.get(key) != b.get(key):
                lines.append(f"Staff changed: {b['name']} {key}: {a.get(key)!r} -> {b.get(key)!r}")

    old_services = {(s["category"], s["name"]): s for s in old.get("services", [])}
    new_services = {(s["category"], s["name"]): s for s in new["services"]}
    for key in sorted(set(new_services) - set(old_services)):
        s = new_services[key]
        lines.append(f"Service added: {key[0]} / {key[1]} ({s['price']}, {s['duration']}, staff {s['staff']})")
    for key in sorted(set(old_services) - set(new_services)):
        lines.append(f"Service removed: {key[0]} / {key[1]}")
    for key in sorted(set(old_services) & set(new_services)):
        a, b = old_services[key], new_services[key]
        for attr in ("price", "duration", "staff", "notes"):
            if a.get(attr) != b.get(attr):
                lines.append(f"Service changed: {key[0]} / {key[1]} {attr}: {a.get(attr)!r} -> {b.get(attr)!r}")
    return lines
