"""Salon configuration and persona loading.

Salon facts come from one JSON blob in the SALON_CONFIG_JSON environment
variable, rendered by Terraform from variables. The persona comes from
persona/jess.md, bundled next to the code at build time.
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
        if not raw:
            raise RuntimeError("SALON_CONFIG_JSON is not set")
        return cls.from_json(raw)


def load_persona(path: str | os.PathLike | None = None) -> str:
    """Return the persona text. Defaults to the bundled persona/jess.md."""
    candidate = Path(path or os.environ.get("PERSONA_PATH") or _default_persona_path())
    return candidate.read_text(encoding="utf-8")


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
