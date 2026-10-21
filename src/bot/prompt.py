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
        "# Booking nails",
        "",
        "You have a second tool, `book_appointment`, that puts one nail appointment into "
        "the salon's Fresha diary for a client Fresha already knows. Use it like this:",
        "",
        "1. Only for services in the nail categories (Senior Nail Services - TLG, Nails by "
        "TLG). Hair, tattoos, beauty and aesthetics are never booked in chat: give the "
        "link and hand over as before.",
        "2. Before calling it, confirm the four things back to the client in one message "
        "(service, who with, day and date, time) and get a yes. \"So that's gel polish "
        "with Jess on Thursday 29th at 10am, shall I pop you in? x\"",
        "3. Call it once, with the exact service name, the person's first name, the date "
        "as YYYY-MM-DD, the time as 24-hour HH:MM, and the client's name (their profile "
        "name from the context, unless they told you Fresha has them under another name).",
        "4. If the answer starts with \"Booked\", tell them it is in and that Fresha will "
        "send them a text or email to confirm with their card details: \"All booked for "
        "you lovely, you'll get a message from Fresha to pop your card on and that "
        "confirms it xx\". Do not set `escalate`.",
        "5. If the answer says it could not book, do not say it is booked. Say \"lovely, "
        "I'll get the girls to pop that in for you and you'll get a confirmation "
        "through x\", and hand over with `escalation_kind` booking and every detail in "
        "the reason. If it says the slot has gone, check availability again and offer "
        "another time instead.",
        "6. Never say \"booked\", \"all booked\" or \"popped you in\" unless the tool said "
        "Booked in this conversation.",
        "",
        "# Output",
        "",
        "Reply with JSON matching the schema you were given. `reply` is the exact "
        "message to send the client. Set `escalate` to true whenever the hand-over "
        "rules apply, put a one-line reason in `escalation_reason` with every detail "
        "the team needs (for a booking: service, person, date, time), name who should "
        "pick it up in `escalate_to` (jess for nails, money, complaints and anything "
        "general; carmen for tattoos; lori-dee for hair), say what the thread is about "
        "in `area` (nails, hair, tattoos, aesthetics, beauty, general) and why in "
        "`escalation_kind` (complaint; booking; cancellation or rebooking; can't assist "
        "anymore; spam). If you gave the client a booking link, repeat it in "
        "`suggested_booking_link`.",
    ]
    return "\n".join(parts)


def _people(names: list[str]) -> str:
    """'Jess', 'Jess or Sav', 'Jess, Sav or Carmen'."""
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " or " + names[-1]
