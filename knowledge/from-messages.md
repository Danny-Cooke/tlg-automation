# Facts the team told clients in Messenger (to confirm)

Taken from the Page's Messenger history, February to October 2026, while
building the voice guide (`docs/voice-analysis.md`). None of this is in
`terraform/salon.auto.tfvars` or the Fresha menu, so the bot does not quote
it yet. Each item says when it was said, because prices and policies moved
during the year. Jess confirms, then the keepers move to `salon.auto.tfvars`
(`extra_notes`) or into Fresha, and the item is deleted here.

## Opening and finding us

- Open Tuesday to Saturday, shut Sundays and Mondays (said many times, all
  year). Matches the tfvars hours.
- Summer-holiday hours were quoted in August as 10:30 to 10pm Tuesday to
  Friday and 10 to 5 Saturday, "temporary". Not in Fresha.
- Lori-Dee's days as told to clients: Mondays and Tuesdays plus every other
  Saturday until November 2026, "full time from the start of November".
  Sav: Fridays and Saturdays. The apprentice (Lissy): Saturdays. Fresha
  shows the live rota; the bot should not quote days.
- Directions used with clients: "4a Roushill, just up from the Salopian",
  "next door to the kitchen depot, Ku Ku Poke and the carpet shop", "walking
  distance from the station, just behind the Darwin centre", "we have a huge
  frog in the window".
- Parking: Frankwell car park over the bridge is the cheapest; the Gap car
  park is close.
- Access: downstairs desk and an accessible toilet; aesthetics is upstairs
  but Bernadette can treat downstairs for wheelchair users. A client's dog
  was allowed in once. Children can come along.

## Booking and paying

- Since about June 2026 Fresha emails a confirmation that asks for card
  details to secure the appointment; "nothing is taken until after the
  appointment, it's just to protect us from no-shows". Without confirming,
  the booking is not on the system (one client turned up to no booking in
  September).
- Before June, a £10 deposit by bank transfer, off the bill on the day, with
  the salon's account details pasted into chat. Lori-Dee takes her own
  non-refundable booking fee (£10 to £30 depending on the service) into her
  own business account and asks to be told when it is paid. **Decision for
  the bot: never send bank details, never ask for a deposit.**
- Cancellation policy as told to clients: a same-day cancellation is
  chargeable; a late cancellation needs a fresh deposit to rebook; a 50%
  deposit to rebook after a no-show; an all-day tattoo cancelled on the day
  drew a £60 fee (July). Parties: 50% deposit, rest on the day.
- Gift vouchers: physical ones in the salon (from May) and digital ones by
  email; vouchers and prizes expire after 6 months.
- Payment is cash or card.

## Nails

- Standard nail art is 50p per nail; French tips £2 extra; gems or pearls
  50p per nail; glitters, chromes and cat-eye are free (Feb to June quotes).
  Extreme art is a separate booking.
- Products are TPO and HEMA free, made in the UK; the team called themselves
  "El Nail Systems ambassadors" (March). Confirm the brand.
- Gel polish lasts about three weeks. BIAB can be painted over with normal
  polish; avoid acetone remover.
- Minimum age for acrylics: insurance sets none; Jess prefers 10 and over.
  A child's gel polish with the apprentice was £10 (August).
- Infill versus new set is decided on the day ("I'll have to take a look").
- Lifting or damage after a set: Carmen offered a free removal and new set
  (August). Touch-ups on tattoos are free once healed.

## Hair (Lori-Dee)

- Curly cuts from £65 depending on length and thickness (medium £65, long
  £75, as quoted September). Dry cut first, then wash and diffuse. Arrive
  with clean hair styled as usual; a little product is fine.
- Colour is quoted after photos in natural daylight plus inspiration photos,
  or a consultation. Patch test needed before colour; clients can pop in and
  one of the girls does it. Strand test offered for lightening.
- Prices quoted in 2026: half head highlights £95, full head £128 (Sept);
  keratin, shoulder length £115 (Aug); cut and blow dry, long hair £57 (Mar);
  wolf cut with colour from £140 (June); colour correction first visit £177
  then £124 (Apr). Offer in Aug/Sept: free cut and style with a colour.
- Products mentioned: K18 with all blonding, Keratin Revolution, Wella
  Color shampoo recommended after colour.

## Tattoos (Carmen)

- Consultations free. Hourly £50; day sit from £280 (both all year). Small
  tattoo "around £50 depending on size and complexity".
- Tiny Tattoo Tuesday: £30 (August), later £40 on a Tuesday and £50 any other
  day (October). Must meet a size rule, checked at consultation.
- Red and brown inks need a patch test.
- Inspiration pictures are not copied; "our version". Carmen prints several
  stencil sizes on the day for positioning.
- Carmen's tattoo Instagram: thelookingglasstattoos. Registered with the
  council; artist holds infection-control training (Jess, August).

## Aesthetics (Bernadette)

- Trades as "Re Fresh Aesthetics", own Facebook page, self-employed, own
  diary; the salon sends every aesthetics enquiry there. Free consultation.
- Hayfever injection: "yes, £80" (17 March) and "sorry we don't" (5 April).
  Contradictory; ask.
- B12 injections: offered via Bernadette (June).

## Parties and groups

- Mini Hatters pamper party: £28 per child, age 6 and over, maximum 4 (to
  June) then 6 (August), Fridays and Saturdays. Hosted by Lady Hatter;
  "rock star or princess"; silk robes, crowns, thrones; mini pedicure and
  mini manicure with varnish; make-up, glitter tattoos; mocktails, cakes,
  sweets; party bag. Parents stay with a hot drink or prosecco. Dietary
  requirements asked for. The long party description used in August is in
  the transcript if Jess wants it as a template.
- Hatters High Tea pedicure: for two, luxury pedicure with gel toes plus
  local sandwiches, cakes, scones, tea and prosecco, 1 hour 30, £65 each
  (Feb to April; £58 quoted once). Gluten-free possible.
- Adult groups (hen do, 7 to 8 people): two pedicures at a time while others
  have nails; bespoke per-head prices (£18 to £25 per treatment, plus £10 a
  head for cakes and tea, April). Always a human.

## Other

- Jess's WhatsApp for business enquiries (rent, jobs) is the number already
  in `salon.auto.tfvars`.
- Room and chair rental, jobs, models and work-experience requests all go
  to Jess for "a chat and a coffee".
- The salon opened on Roushill in February 2026 ("this is our 8th week" on 8
  April).
- Tagline used with clients: "Where Glamour Meets Gears". The tfvars say
  "Where Beauty Meets Alchemy". Which is current?
