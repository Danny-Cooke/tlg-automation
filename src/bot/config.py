"""Salon configuration and persona loading.

Salon facts come from bot/salon_config.json, rendered at build time by
scripts/render_salon_config.py from the Terraform inputs and bundled next to
the code (SALON_CONFIG_PATH). The real menu is far over Lambda's 4KB limit
for environment variables, so it cannot travel that way; SALON_CONFIG_JSON
is still honoured for tests. The persona comes from the persona/ folder
(jess.md, voice-guide.md, vocabulary.md), bundled the same way.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Service:
    category: str
    name: str
    price: str
    duration: str
    staff: list[str] = field(default_factory=list)
    booking_link: str = ""
    notes: str = ""


@dataclass(frozen=True)
class StaffMember:
    name: str
    role: str
    booking_link: str = ""
    services: list[str] = field(default_factory=list)
    employee_id: str = ""  # Fresha's id; empty means availability cannot be looked up for them


def _lookup(table: dict[str, list[str]], service_name: str) -> list[str]:
    """The people banned from `service_name`, matched on the name ignoring case and spacing."""
    want = " ".join(service_name.split()).casefold()
    for k, names in table.items():
        if " ".join(k.split()).casefold() == want:
            return list(names)
    return []


def _hidden(name: str, hidden: list[str]) -> bool:
    """A Fresha team member the bot must not know about: the configured name
    equals the staff name, or one contains the other, case-insensitive, so a
    first name or a slightly mistyped name still matches."""
    n = " ".join(name.split()).casefold()
    if not n:
        return False
    for h in hidden:
        h = " ".join(str(h).split()).casefold()
        if h and (h == n or h in n or n in h):
            return True
    return False


@dataclass(frozen=True)
class SalonConfig:
    salon_name: str
    address: str
    phone: str
    opening_hours: dict[str, str]
    general_booking_link: str
    services: list[Service]
    staff: list[StaffMember]
    extra_notes: str = ""
    venue_url: str = ""  # Fresha venue page; the availability lookup starts from its slug
    hidden_staff: list[str] = field(default_factory=list)  # names the bot must never offer or book
    not_bookable_for: dict[str, list[str]] = field(default_factory=dict)  # service name -> people never offered for it

    @classmethod
    def from_json(cls, raw: str) -> "SalonConfig":
        data = json.loads(raw)
        hidden = [h for h in data.get("hidden_staff", []) if str(h).strip()]
        not_for = {str(k): [str(n) for n in v] for k, v in (data.get("not_bookable_for") or {}).items()}
        staff = [StaffMember(**s) for s in data.get("staff", [])]
        staff = [m for m in staff if not _hidden(m.name, hidden)]
        services = []
        for s in data.get("services", []):
            banned = hidden + _lookup(not_for, s.get("name", ""))
            s = dict(s, staff=[n for n in s.get("staff", []) if not _hidden(n, banned)])
            services.append(Service(**s))
        return cls(
            salon_name=data["salon_name"],
            address=data["address"],
            phone=data["phone"],
            opening_hours=data["opening_hours"],
            general_booking_link=data["general_booking_link"],
            services=services,
            staff=staff,
            extra_notes=data.get("extra_notes", ""),
            venue_url=data.get("venue_url", ""),
            hidden_staff=hidden,
            not_bookable_for=not_for,
        )

    def staff_named(self, first_name: str) -> StaffMember | None:
        want = first_name.strip().casefold()
        for m in self.staff:
            if m.name.casefold() == want or m.name.casefold().split()[0] == want:
                return m
        return None

    @classmethod
    def from_env(cls) -> "SalonConfig":
        raw = os.environ.get("SALON_CONFIG_JSON")
        if raw:
            return cls.from_json(raw)
        path = Path(os.environ.get("SALON_CONFIG_PATH") or _default_config_path())
        if not path.exists():
            raise RuntimeError(f"salon config not found at {path}; set SALON_CONFIG_PATH or SALON_CONFIG_JSON")
        return cls.from_json(path.read_text(encoding="utf-8"))


# The persona is three files, read in this order: who Jess is and the rules,
# how a reply is built, then the word bank. All three came from the Page's
# real message history (docs/voice-analysis.md).
PERSONA_FILES = ("jess.md", "voice-guide.md", "vocabulary.md")


def load_persona(path: str | os.PathLike | None = None) -> str:
    """Return the persona text.

    `path` (or PERSONA_PATH) may be a directory holding PERSONA_FILES, which
    are joined in order, or a single Markdown file. Defaults to the bundled
    persona/ folder next to this package."""
    candidate = Path(path or os.environ.get("PERSONA_PATH") or _default_persona_path())
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    parts = []
    for name in PERSONA_FILES:
        file = candidate / name
        if not file.exists():
            raise RuntimeError(f"persona file missing: {file}")
        parts.append(file.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(parts) + "\n"


def _default_config_path() -> Path:
    return Path(__file__).resolve().parent / "salon_config.json"


def _default_persona_path() -> Path:
    here = Path(__file__).resolve().parent
    # In the Lambda zip the persona folder sits inside the package; in the
    # repo it is two levels up under persona/.
    for candidate in (here / "persona", here.parent / "persona", here.parent.parent / "persona"):
        if (candidate / PERSONA_FILES[0]).exists():
            return candidate
    raise FileNotFoundError("persona/ folder not found; set PERSONA_PATH")
