"""Build the system prompt from the persona and the salon config.

The result must be byte-stable between invocations so it can be prompt-cached.
Do not put timestamps or per-request values in here.
"""
from __future__ import annotations

from .config import SalonConfig

DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def build_system_prompt(persona: str, cfg: SalonConfig) -> str:
    parts = [persona.strip(), "", "---", "", "# Salon details", ""]
    parts += [
        f"Salon: {cfg.salon_name}",
        f"Address: {cfg.address}",
        f"Phone: {cfg.phone}",
        f"Book anything: {cfg.general_booking_link}",
        "",
        "## Opening hours",
    ]
    for day in DAY_ORDER:
        if day in cfg.opening_hours:
            parts.append(f"- {day.title()}: {cfg.opening_hours[day]}")

    parts += ["", "## Team"]
    # Rendered as "Jess, Sav or Carmen" so the model reads it as a choice.
    for m in cfg.staff:
        line = f"- {m.name}, {m.role}"
        if m.services:
            line += f". Does: {', '.join(m.services)}"
        if m.booking_link:
            line += f". Book with {m.name}: {m.booking_link}"
        parts.append(line)

    parts += [
        "",
        "## Services",
        "",
        "Every service is bookable on the main link above unless a different link is shown. "
        "Clients pick the time on Fresha. Where a service says who does it, only those people "
        "can be booked for it; use that person's link if they have one.",
    ]
    by_category: dict[str, list] = {}
    for s in cfg.services:
        by_category.setdefault(s.category, []).append(s)
    for category, items in by_category.items():
        parts += ["", f"### {category}"]
        for s in items:
            line = f"- {s.name}: {s.price}, {s.duration}"
            if s.staff:
                line += f", with {_people(s.staff)}"
            if s.notes:
                line += f" ({s.notes})"
            if s.booking_link:
                line += f". Book: {s.booking_link}"
            parts.append(line)

    if cfg.extra_notes.strip():
        parts += ["", "## Other notes", cfg.extra_notes.strip()]

    parts += [
        "",
        "---",
        "",
        "# Checking availability",
        "",
        "You have a tool, `check_availability`, that reads live free start times from "
        "Fresha for one service, up to three named team members and up to four dates. "
        "Use it whenever a client asks what is free, or names a day, or asks to be "
        "booked in: pick the exact service name from the list above, the person they "
        "asked for (or the people who do that service if they have no preference), and "
        "the dates worked out from today's date in the context. Offer two or three of "
        "the returned times the way the team does (\"we have 10am or 1.30 on Friday?\"). "
        "Never invent a time; if the tool says nothing is free or could not check, say "
        "so and offer another day or the booking link. The tool only reads: it cannot "
        "hold or book a slot.",
        "",
        "# Output",
        "",
        "Reply with JSON matching the schema you were given. `reply` is the exact "
        "message to send the client. Set `escalate` to true whenever the hand-over "
        "rules apply, put a one-line reason in `escalation_reason`, and name who "
        "should pick it up in `escalate_to`: jess for nails, money, complaints and "
        "anything general; carmen for tattoos; lori-dee for hair. If you gave the "
        "client a booking link, repeat it in `suggested_booking_link`.",
    ]
    return "\n".join(parts)


def _people(names: list[str]) -> str:
    """'Jess', 'Jess or Sav', 'Jess, Sav or Carmen'."""
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " or " + names[-1]
