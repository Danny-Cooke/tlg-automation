"""Salon configuration and persona loading.

Salon facts come from bot/salon_config.json, rendered at build time by
scripts/render_salon_config.py from the Terraform inputs and bundled next to
the code (SALON_CONFIG_PATH). The real menu is far over Lambda's 4KB limit
for environment variables, so it cannot travel that way; SALON_CONFIG_JSON
is still honoured for tests. The persona comes from persona/jess.md, bundled
the same way.
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

    @classmethod
    def from_json(cls, raw: str) -> "SalonConfig":
        data = json.loads(raw)
        return cls(
            salon_name=data["salon_name"],
            address=data["address"],
            phone=data["phone"],
            opening_hours=data["opening_hours"],
            general_booking_link=data["general_booking_link"],
            services=[Service(**s) for s in data.get("services", [])],
            staff=[StaffMember(**s) for s in data.get("staff", [])],
            extra_notes=data.get("extra_notes", ""),
        )

    @classmethod
    def from_env(cls) -> "SalonConfig":
        raw = os.environ.get("SALON_CONFIG_JSON")
        if raw:
            return cls.from_json(raw)
        path = Path(os.environ.get("SALON_CONFIG_PATH") or _default_config_path())
        if not path.exists():
            raise RuntimeError(f"salon config not found at {path}; set SALON_CONFIG_PATH or SALON_CONFIG_JSON")
        return cls.from_json(path.read_text(encoding="utf-8"))


def load_persona(path: str | os.PathLike | None = None) -> str:
    """Return the persona text. Defaults to the bundled persona/jess.md."""
    candidate = Path(path or os.environ.get("PERSONA_PATH") or _default_persona_path())
    return candidate.read_text(encoding="utf-8")


def _default_config_path() -> Path:
    return Path(__file__).resolve().parent / "salon_config.json"


def _default_persona_path() -> Path:
    here = Path(__file__).resolve().parent
    # In the Lambda zip the persona sits next to the package; in the repo it is
    # two levels up under persona/.
    for candidate in (
        here / "jess.md",
        here.parent / "persona" / "jess.md",
        here.parent.parent / "persona" / "jess.md",
    ):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("persona/jess.md not found; set PERSONA_PATH")
