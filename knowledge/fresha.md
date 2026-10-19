# Fresha facts

Verified 2026-10-18 by reading Fresha's own booking payload and each team
member's booking page. Prices and the per-service staff lists are in
`terraform/salon.auto.tfvars`; this file holds the surrounding facts.

## Identifiers and links

- Business: TLG Beauty Limited, trading as The Looking Glass Beauty.
- Fresha venue slug: `the-looking-glass-beauty-shrewsbury-roushill-xa3bpl74`.
  Venue page: https://www.fresha.com/en-GB/a/the-looking-glass-beauty-shrewsbury-roushill-xa3bpl74
- Fresha location id 1530970, owner id (pId) 1453889.
- General "all offers" share link (the one Jess hands out):
  https://www.fresha.com/book-now/tlg-beauty-limited-xexbl23r/all-offer?share=true&pId=1453889
- Per-person booking link: the venue URL + `/booking?employeeId=<id>`. Opens
  the booking flow filtered to that person. Verified for all eight.

| Person | Fresha employeeId |
|---|---|
| Jess | 3440861 |
| Carmen | 3440872 |
| Lori-Dee | 5003108 |
| Bernadette | 5007255 |
| Sav | 5029221 |
| Amber | 5394887 |
| Lissy | 5487696 |
| Sophie | 5630580 |

## Categories

Eight real categories plus a "Featured" tab that repeats six nail items.
Names, spelled as Fresha spells them: "Senior Nail Services - TLG" (19),
"Nails by TLG" (6, junior tier), "Beauty - TLG" (9), "Lashes by Amber" (4),
"Hair by Lori-dee" (42), "Sophie cooper" (24), "Bernadettes ReFresh aethetics"
(60, labelled "Price Guide"), "Tattoos by Skin deep canvas" (3). 167 in total.

A category name is Fresha's heading, not a statement of who does the work.
Fresha sets bookable staff per service. Examples: the occasion make-up under
"Lashes by Amber" is bookable with Amber or Carmen; the children's pamper under
"Senior Nail Services - TLG" is bookable with all five nail people; Lori-Dee is
switched on for every item in the "Sophie cooper" category.

## Hours

Fresha: Tue, Wed, Fri, Sat 10:00 to 18:00; Thu 10:00 to 22:00; Sun and Mon
closed. The website says 9:30 starts and 9:00 on Saturday. The bot uses
Fresha's hours because those are the bookable ones. See open-questions.

## Other facts

- Website https://tlg-beauty.co.uk/, email info@tlg-beauty.co.uk, WhatsApp
  07512 574127, phone 01743 669166, address 4a Roushill, Shrewsbury SY1 1PQ.
- Facebook page id 61577501519464 (page name "The Looking Glass Shrewsbury").
  Instagram @lookingglassbeautysalons. Neither is readable without a login.
- Jess is Jess Preston: nail artist, academy trainer, salon director.
- Fresha rating 5.0 from 232 reviews at the time of reading.
- Fresha has no public API or webhooks. It does have native Google Calendar
  sync per team member (see `docs/calendar-sync.md`). The partner dashboard
  runs on an internal GraphQL gateway that can create and cancel appointments;
  what was observed is in `knowledge/fresha-internal-api.md`.

## Reading the menu and team without a browser (used by menu sync)

Verified 2026-10-19 by replaying from a plain HTTP client, no cookies:

- **Team:** GET the venue page. Its `__NEXT_DATA__` JSON has
  `props.pageProps.data.location.employeeProfiles.edges[].node` with
  `displayName`, `employeeId`, `jobTitle`.
- **Menu:** POST `https://www.fresha.com/graphql` with a persisted query:
  `operationName` `BookingFlow_Initialize_Mutation`, `extensions.persistedQuery`
  `{version: 1, sha256Hash: 7de1649b0e3ab0fd2b3b9d0c4f09a1863106aaf99b969e9b9edb4c98042a5134}`,
  `variables.input.locationSlug` = the venue slug, plus the options block the
  web app sends (see `src/menu_sync/fresha_public.py`). Headers
  `x-client-platform: web` and `x-graphql-operation-name`. Response:
  `data.bookingFlowInitialize.screenServices.categories[].items[]` with
  `name`, `caption` (duration), `price.formatted`, `description`, and
  `secondaryAction.id` (a JSON string whose `catalogId` is `s:<serviceId>` and
  `bookableId` is `sv:<pricingLevelId>`).
- **Who does what:** the same call with `variables.input.options.employeeId`
  set returns only that person's categories and items.
- Fresha ships new web builds daily; if the persisted hash is retired the
  call returns a `PersistedQueryNotFound` error and the hash must be
  re-captured from a browser.

## How to read Fresha's menu reliably (browser method)

The venue and booking pages are React apps. The menu is not in the page's
`__NEXT_DATA__`; it arrives in a GraphQL response named `bookingFlowInitialize`
after clicking "Book now" then "Book an appointment". The reliable method,
with Claude in Chrome or any browser console:

1. Load the venue page and patch `window.fetch` to keep any response whose
   body contains `bookingFlowInitialize`.
2. Click "Book now", then "Book an appointment" (both are client-side
   navigations, so the patch survives).
3. Read `data.bookingFlowInitialize.screenServices.categories[].items[]`:
   `name`, `caption` (duration), `price.formatted`, `description`.
4. For a person's own menu, open their team card on the venue page and click
   the "See all" link in the dialog; that triggers the same query with
   `employeeId`. Only the categories and items they can be booked for come
   back.

Reading the rendered list by scrolling misses items, because the list is
virtualised. The Claude in Chrome JavaScript tool truncates output at about a
thousand characters and blocks anything that looks like a query string, so
stash results on `window` and read them in slices.
