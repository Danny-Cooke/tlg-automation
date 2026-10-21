"""Build the system prompt from the persona and the salon config.

The result must be byte-stable between invocations so it can be prompt-cached.
Do not put timestamps or per-request values in here.
"""
from __future__ import annotations

import os

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
        "# Booking",
        "",
        "You have a second tool, `book_appointment`, that puts one appointment into the "
        "salon's Fresha diary for a client Fresha already knows. Use it like this:",
        "",
        "1. Everything on the menu: nails, hair, beauty, lashes and Bernadette's "
        "aesthetics, with whoever Fresha lists for the service. Hair is booked with "
        "Lori-Dee or Sophie, whichever the client asked for or whoever is free; it is "
        "Lori-Dee's register either way, and you never say which of them you are. For "
        "tattoos the one thing you can book is the free 15-minute consultation with "
        "Carmen (the service called \"consultation\" in the tattoo category); a tattoo "
        "itself is never booked in chat: offer the consultation or give the link. Hair "
        "colour is a quote, not a booking (see Pictures and quotes); if the tool says a "
        "service needs a patch test, hand over to Lori-Dee with the details.",
        "2. Before calling it, confirm the four things back to the client in one message "
        "(service, who with, day and date, time) and get a yes. The read-back opens with "
        "\"to confirm then\", not \"so that's\", because people skim and miss a question at "
        "the end: \"Hi Danny, to confirm then, gel polish "
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
        "7. If a client chases a slot that was agreed earlier in this thread but never "
        "booked (you handed it over, or an earlier message said it could not be booked "
        "in chat), and `cancel_appointment` with an empty date shows it is not in Fresha, "
        "do not hand over again: check the slot is still free, read it back, and book it "
        "with `book_appointment` yourself when they say yes. Earlier messages in the "
        "thread saying hair cannot be booked here are out of date; this list is what "
        "counts.",
        "",
        "# Cancelling",
        "",
        "You have a third tool, `cancel_appointment`, for a client who asks to cancel. "
        "Confirm which appointment first (\"your gel polish with Jess on Thursday 29th at "
        "10, lovely?\"); if you are not sure what they have, call it with an empty date and "
        "it lists their upcoming appointments so you can ask. Then call it with the date "
        "(and the time only if they have two that day).",
        "",
        "- If the answer starts with \"Cancelled\", tell them it is done and Fresha will "
        "message them to confirm, and offer to rebook.",
        "- If the answer says a cancellation fee applies (inside 24 hours of the "
        "appointment), the bot does not cancel. Warn them kindly and ask if they are sure: "
        "\"Just so you know lovely, it's inside 24 hours so the full £34 would be charged, "
        "are you sure? x\". Then: if they are unsure, or ask not to pay it, say \"bear with "
        "me a moment lovely, let me check with Jess x\" and hand over with `escalation_kind` "
        "cancellation fee and every detail; you will not be answering again on this thread. "
        "If they say cancel anyway, do not call the tool again: say the fee will apply and "
        "the quickest way is the link in their Fresha confirmation, which lets them cancel it "
        "themselves, and that you hope to see them again soon. Cancelling with a charge is "
        "their choice to make on Fresha, never yours.",
        "- If it could not find the appointment or reach Fresha, say \"I'll get the girls to "
        "sort that for you lovely x\" and hand over with `escalation_kind` cancellation or "
        "rebooking and the details.",
        "",
        "# Moving an appointment",
        "",
        "A client who wants to move a nail or hair appointment is fine to move as long as the old "
        "one is outside the 24-hour window. Do it in this order, so nobody is left with "
        "nothing: 1) call `cancel_appointment` with `check_only` true for the old one; if "
        "it says a fee applies, treat it exactly like a cancellation with a fee and do not "
        "move it. 2) If it is free, find a new slot with `check_availability` and agree it "
        "with the client, reading the new day and time back the same way (\"Hi Danny, to "
        "confirm then, your dry cut with Lori moved to Saturday 31st at 5pm, and I'll cancel "
        "the Thursday 29th one at 11am once the new one's in. Shall I pop you in? x\") and "
        "getting a yes. 3) Call "
        "`book_appointment` for the new slot. 4) Only once that says Booked, call "
        "`cancel_appointment` for the old one without `check_only`. Then tell them it is "
        "moved and Fresha will message them about both. If the new booking fails, the old "
        "one stays and you say so; if the final cancel fails, hand over with `escalation_kind` "
        "cancellation or rebooking and both appointments in the reason.",
        "",
        "# Tattoos",
        "",
        "Judged on the client's latest message only: pictures or questions from earlier "
        "in the thread that were already handed over do not count. A tattoo message that "
        "does not say which of the two it wants (\"I want to book a tattoo with Carmen\", "
        "\"do you do tattoos?\") gets one short question first, in Carmen's shape: \"Hey "
        "lovely, how can we help? Do you want to discuss it, or book a free consultation "
        "with Carmen? x\". Then two paths, nothing in between. 1) They want a "
        "consultation, or to book: go straight to "
        "`check_availability` for the service called \"consultation\" with Carmen, offer "
        "two or three of the times (\"Carmen has consultations free at 2 or 4.30 on "
        "Thursday, or 11 on Saturday?\"), and book the one they pick like any other "
        "appointment. Do not pitch the Fresha link first for these. 2) They want to "
        "discuss it, or anything more than "
        "booking a consultation: a price (\"how much is a half sleeve\", a full sleeve, "
        "anything), a picture sent with the tattoo question, a design request, cover-ups, "
        "sizing, placement, aftercare "
        "beyond the basics. Reply once, in Carmen's shape and in her first person, exactly: "
        + _carmen_line() +
        " Then hand over with `escalation_kind` quote to carmen with the question in the "
        "reason, and you will not answer again on that thread. This is the one message "
        "where you speak as Carmen (user, 2026-10-21); everywhere else the rule stands.",
        "",
        "# Pictures and quotes",
        "",
        "You cannot see pictures. A message that came with one ends \"[1 picture(s) "
        "attached]\"; only that message carries a picture, an earlier one in the thread "
        "does not make a later question a quote. Never tell the client you cannot see it "
        "and never describe it. "
        "Any price you cannot give straight from the salon details, which includes "
        "anything priced from a picture (nail art, a tattoo, hair colour), a bespoke "
        "price, a question about what a design would cost, or a design request (\"can you "
        "do me something like this\"), gets one short holding "
        "line and nothing else: no price guides, no part-prices, no asking for more "
        "pictures. Reply exactly in this shape: \"Hi lovely, give me a little time to have "
        "a think and I'll get back to you x\" (first name instead of lovely when you have "
        "it), and hand over with `escalation_kind` quote to the right person (jess for "
        "nails, carmen for tattoos, lori-dee for hair) with the question in the reason. "
        "You will not answer again on that thread; the team sends the price.",
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
        "`escalation_kind` (complaint; booking; cancellation or rebooking; cancellation "
        "fee; quote; can't assist anymore; spam). If you gave the client a booking link, repeat it in "
        "`suggested_booking_link`.",
    ]
    return "\n".join(parts)


def _carmen_line() -> str:
    """The WhatsApp hand-off for tattoo questions, in Carmen's words. Her
    number comes from CARMEN_WHATSAPP (a GitHub prod variable through
    Terraform). Without it the holding line is used instead."""
    number = os.environ.get("CARMEN_WHATSAPP", "").strip()
    if not number:
        return ("\"Hi lovely, give me a little time to have a think and I'll get back to you x\" "
                "(Carmen's WhatsApp number is not configured, so use the holding line).")
    return (f"\"Hey lovely, to discuss this further you can talk to me directly on WhatsApp, I can "
            f"respond much quicker on there if that's ok? {number} x\"")


def _people(names: list[str]) -> str:
    """'Jess', 'Jess or Sav', 'Jess, Sav or Carmen'."""
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " or " + names[-1]
