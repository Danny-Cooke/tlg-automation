# Open questions for Jess

Things the data says that a human should confirm before the bot goes live.
Remove an item once it is settled and update the source file.

1. **Opening hours.** Fresha says 10:00 starts; the website says 9:30 (9:00
   Saturday). Which is right? The bot currently quotes Fresha.
2. **Tiny Tattoo Tuesday price.** Fresha lists £40 but the description says
   £30. Which does Carmen charge?
3. **Carmen and occasion make-up.** Fresha lets clients book "Make up by the
   lash goblin" with Carmen as well as Amber. Deliberate, or a setup slip?
4. **Lori-Dee on Sophie's menu.** Fresha lets clients book every item in the
   "Sophie cooper" category with Lori-Dee. Deliberate?
5. **Quoting prices.** Should the bot quote prices from the snapshot, or only
   link to Fresha? Both work from the same file.
6. **Google Calendar sync.** Export only for everyone, or two-way for the
   independents? See `docs/calendar-sync.md` for the trade-off.
7. **Cancellation window.** Answered 2026-10-21 from Fresha's payment policy
   page: free until 24 hours before the appointment starts (counted back from
   the appointment, not from booking), inside that 100% of the price, no-show
   100%. Now in `terraform/salon.auto.tfvars`. The custom settings were
   answered 2026-10-24: "no-show fee off" on 122 services. The user had it
   switched on for every nails, Amber, beauty and tattoo service (26
   changed); 96 remain off under Sophie, Bernadette and Lori-Dee, left as
   they are on the user's instruction.
8. **Patch tests for beauty and lashes.** Fresha flags no service as needing
   one (the "patch test required" tick is off everywhere, checked
   2026-10-24). The message history shows the team patch-testing lash glue
   ("clients we definitely will patch test"). Usual UK practice is a test
   24 to 48 hours before any tint (Brow Tint, Brow Wax & Tint, lash tint,
   Lash lift and tint) and before lash extensions (the adhesive); a lash
   lift on its own varies by product. Jess and Amber to confirm which of
   the nine beauty and four lash services need one, and how far ahead, so
   the bot can say so when booking and the mirror's patch-test records can
   be matched to services.

