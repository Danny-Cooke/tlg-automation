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
   100%. Now in `terraform/salon.auto.tfvars`. Still open: 124 services have
   custom no-show settings; which, and what?
