# Service coverage: what the bot does with every item on the menu

Audit of 2026-10-24 against the Fresha menu snapshot of 2026-10-21
(`terraform/fresha-menu.auto.tfvars.json`: 171 services in 8 categories,
8 bookable people). The question it answers: for every service, does a
client's message end in a reply that settles it, or in a hand-over the team
sees in Telegram? Where the answer is "neither", or "only by luck", it is
listed under Gaps.

## The guarantee the code gives, and the one switch that breaks it

Every text message that reaches `brain.ask` ends one of two ways
(`src/bot/handler.py`, `src/bot/brain.py`):

- the model answers in the JSON schema, with `escalate` false (a reply that
  settles it) or true (a reply plus a hand-over: Telegram post, email, and
  the thread locked for complaint, cancellation fee, quote and "can't assist
  anymore"; not locked for booking, cancellation or rebooking);
- or anything goes wrong (API failure, refusal, truncated or unparseable
  output, too many tool rounds) and the client gets the holding line while
  the team gets a "can't assist anymore" hand-over. A picture with no text is
  a quote hand-over.

So no message is silently dropped once it is answered at all. Two things
are email-only by design: spam, and shadow-mode drafts.

**The switch.** Both live Lambdas (`tlg-prod-messenger-bot`,
`tlg-prod-instagram-bot`, checked 2026-10-24) run with `BOT_MODE=live` and
`MESSAGE_TEST_MODE=true`. In test mode only a message that starts with the
trigger word is answered; every other client message is stored and never
answered, never posted to Telegram. That is the guardrail from job 6, not a
fault, but while it is on the answer to "is every service dealt with" is no
for every service. Turning it off is the GitHub `prod` variable
`MESSAGE_TEST_MODE=false` and a deploy.

## The matrix

Area words are the ones the Telegram line carries (`booking.BOOKABLE_CATEGORIES`).
"Price in chat" means the bot may quote the menu price; "from" prices are
quoted as "from". "Quote" means the holding line and a quiet hand-over.

| Fresha category | Services | Area | Price in chat | Booked in chat | Hand-over, and to whom | Enforced by |
|---|---|---|---|---|---|---|
| Senior Nail Services - TLG | 19 | nails | yes | yes, Sav, Carmen or Jess | custom art or anything from a picture: quote, Jess | persona, prompt, booking tool |
| Nails by TLG | 6 | nails | yes | yes, Amber or Lissy | same | same |
| Hair by Lori-dee | 41 | hair | listed prices yes; colour is a quote | never (ruling 2026-10-24) | anything beyond a listed price: "one for Lori", hand-over to Lori-Dee, thread locked for her to deal with in the inbox; complaints: Jess | booking tool refuses hair; prompt Hair section; `handler.locks` on area hair |
| Sophie cooper | 29 | hair | as above | never | Sophie named: her WhatsApp line (`SOPHIE_PHONE`), hand-over, locked; complaints: Jess | same |
| Beauty - TLG | 10 | beauty | yes | yes, whoever Fresha lists; lash and brow treatments only once the patch-test column says tested or a patch test is booked first (job 12) | health or skin questions: Jess; patch test booked: Jess told | booking tool, `patch_tests` guard |
| Lashes by Amber | 5 | beauty | yes (makeup "from £25") | yes, Amber, lashes behind the patch-test guard | Jess | booking tool, `patch_tests` guard |
| Bernadettes ReFresh aethetics | 60 | aesthetics | yes, from the list | yes, Bernadette | suitability, what to have, anything medical: hand-over (lands with Jess, see gap 6) | persona |
| Tattoos by Skin deep canvas | 3 | tattoos | Tiny Tattoo prices are listed; everything else is a quote | the free consultation only | Carmen's WhatsApp line, then Carmen | `booking.ONLY_THESE`, prompt |

Once a thread is with Lori-Dee or Carmen the bot still reads it and answers
anything that is its own (nails, beauty, lashes, aesthetics); with Jess it
is silent (decision 2026-10-24).

Everything in the table is "dealt with" in the sense the user means, with
the exceptions below.

## Gaps, most important first

1. **Test mode is on** (above). Nothing is handled for a client who does not
   type the trigger word.

2. **Hair colour in chat: settled by the 2026-10-24 ruling.** Nothing in
   either hair category is booked in chat any more, so the missing
   patch-test flag no longer matters for booking. Still undecided: whether
   the bot may quote the fixed colour prices on the list (Basic colour
   roots £45, Toner £27, Sophie's foils £50 to £120) or holds every colour
   price for Lori-Dee as the persona says. And whether the team records
   patch tests in Fresha at all (the client mirror will say).

3. **Same name, two prices, same person.** "Classic lashes" is £48 under
   Beauty - TLG and £52 under Lashes by Amber, both Amber; "Classic lash
   infill" the same (£45 and £52). The tool matches by name and person, so
   it takes whichever Fresha lists first and may book the wrong price. The
   other duplicates ("gel polish" £25 Amber vs "Gel polish" from £34
   seniors, "Dry cut" Lori-Dee £35 vs Sophie £30, "Consultation" Sophie vs
   "consultation" Carmen) are told apart by the person, so they are safe as
   long as the model names one. Fix in Fresha: remove or rename the
   Beauty - TLG copies.

4. **Add-ons can be booked as appointments of their own.** The tool books
   one pricing level per appointment, and these are add-ons by their own
   descriptions: "Extra time for simple nail art" (from £0.50), "extra time
   for extreme nail art" (from £1.50), "Luxury manicure" ("an additional
   treatment to add on"), "Extra bowls", "K18", "Conditioning treatment",
   "Blowdry & style after colour", "Fringe trim" (£3), both toners. "Can I
   add nail art to my appointment" was an open question in job 4 and still
   is. Options: the bot quotes the add-on and says to mention it on the
   day; or hands over (kind: booking) so the girls add it; either way the
   tool should refuse to book an add-on on its own.

5. **Items the bot should never book, or book with fewer people.**
   "Competition winner" (free, Sophie) is a prize, not a service. "Two week
   Botox review" (free) is for Bernadette's own clients. "Shampoo and blow
   dry long hair" lists all eight people including Bernadette, Carmen, Jess
   and Lissy, so the bot could book a blow dry with the aesthetician.
   "Mini hatters pamper" lists five people and is a children's party item;
   the persona hands parties over, but a single child's booking is on the
   menu. All fixable in `terraform/salon.auto.tfvars` (`not_bookable_for`,
   or a new never-book list) once the user says who does what.

6. **Hand-overs for Bernadette, Amber and Sophie land with Jess or
   Lori-Dee.** `escalate_to` allows jess, carmen and lori-dee, and the
   Telegram group is those three. Aesthetics advice, lash questions and
   Sophie's clients still reach Telegram (the area word says aesthetics,
   beauty or hair), so nothing is lost, but someone relays. If the three
   should pick up their own, add them to the group and to the enum.

7. **Tiny Tattoos are a fixed product the bot cannot book.** "Tiny Tattoo"
   £50 and "Tiny tattoo (TUESDAYS ONLY)" £40 have list prices, but
   `ONLY_THESE` lets the bot book only Carmen's consultation, so "book me a
   tiny tattoo Tuesday" ends in the consultation or the link. Carmen's
   call whether these two become bookable. Open question 2 (£40 or £30)
   still stands.

8. **Free consultations are a resolution the prompt only uses for tattoos.**
   Bernadette has "Free Consultation" (10 mins), Lori-Dee "Hair
   consultation" (30 mins), Sophie "Consultation" (15 mins). Today an
   aesthetics "what should I have" or a colour question is a hand-over. The
   tattoo pattern (offer the free consultation, book it, done) would settle
   most of these in chat, and it is what Lori-Dee says herself ("best if you
   come in for a consultation"). A prompt and persona change, no code.

9. **There is no end-to-end proof.** The 224 unit tests check parsing and
   the tool guards with a scripted model; nothing checks what the real model
   does with "how much is profhilo", "can I book a lash lift Saturday" or
   "my acrylics have lifted". The fix is an evaluation run (plan job 11): one
   scenario per service family and per hand-over rule, run against the real
   model with a fake Fresha, asserting the outcome class (answered, booked,
   quote, hand-over and to whom). A few pence a run; run it before any
   persona or prompt change and record the result here.

## Last evaluation run

None yet. See plan job 11.
