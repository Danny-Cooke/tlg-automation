# Fresha partner dashboard: internal GraphQL API

Observed 2026-10-19 by creating and cancelling one test appointment in the
partner dashboard (partners.fresha.com) while recording the responses. This is
Fresha's private API for its own web app, not a public or supported one. It can
change without notice and using it is probably outside Fresha's terms. Treat it
as a reverse-engineered dependency with an escalation path behind it.

Related: `knowledge/fresha.md` (public facts and ids), `docs/decisions.md`
(2026-10-16 "bot cannot book" and 2026-10-19 scope change).

## Transport

- Endpoint: `POST https://partners-api-gateway.fresha.com/graphql`
- Query string on every call: `_client_platform=web`,
  `_client_version=<app version, e.g. 2.8.12057>`, `__pid=<owner id 1453889>`.
- Queries also carry `_query=<operationName>` in the query string. Mutations
  do not; they are a plain POST to the same URL.
- Auth is the dashboard's browser session. Which cookie or header carries it
  has not been captured yet (see "Still unknown").
- Responses are standard GraphQL JSON with `__typename` on every object.
- The app's calendar page polls `CustomerConnect_unreadConversationsCount`
  roughly every 30 seconds.

## Booking flow as the dashboard does it

Order of calls seen for "Add > Appointment > pick slot > pick service >
pick client > Save" (names are the `_query` values):

1. `calendar_dailyCalendarEventsPrefetch`, `calendar_dailyCalendarEvents`,
   `calendar_offerCatalogItems`, `resourcesSettings` (calendar load)
2. `pricingCatalogList` (service picker), `servicesShared_serviceAddOnsQuery`,
   `addOnsGateway`
3. `availableTimeSlots` (see below), `SchedulingConflicts`
4. `appointmentCatalogItemsWithAssignments` (service + pricing level + duration)
5. `offerCatalogAssignmentsAndColors`, `purchaseOrderPreviewV2` (price preview)
6. `CustomerLeftDrawer`, `CustomerMembershipSubscriptions`,
   `GetCustomerPatchTestsForServiceCallouts` (client picked)
7. `appointment_calculateAppointmentProtectionFees` (deposit / card policy)
8. Mutation `AppointmentsManager_createAppointmentByEmployee`
9. `calendar_dailyCalendarEvents` refetch

Only step 8 writes. Steps 3, 4 and 8 are the ones a bot needs.

## Create appointment

Mutation `AppointmentsManager_createAppointmentByEmployee`.

Input shape, read from the dashboard's JavaScript (the function that builds
the variables before calling the mutation):

```
{
  appointment: {
    bookings: [ ...built from (startDate, timezone, completeBookingItems) ],
    locationId,
    customerId?,          // omit for walk-in
    recurrenceSettings?,
    waitlist?: { entryId },
    priceModifiers?
  },
  appointmentProtection?,   // deposit / card capture policy
  metadata: { idempotencyKey, source }   // source is the UI entry point
}
```

The exact fields inside each `bookings[]` item have not been captured. The
calendar event that comes back (below) shows what a booking carries, so the
input is most likely: service id, service pricing level id, employee id,
start time, duration or time segments.

Response seen:

```json
{"data":{"__typename":"Mutation",
  "AppointmentsManager_createAppointmentByEmployee":{
    "__typename":"AppointmentsManager_CreateAppointmentByEmployeePayload",
    "appointment":{"__typename":"AppointmentsManager_Appointment","id":"1330548061"},
    "primaryBookingId":"1797380236",
    "warnings":null}}}
```

The appointment then appears in `calendar_dailyCalendarEvents` as a booking
with these fields (abridged):

```
status "CONFIRMED", isOnline false, isProtected false,
customerId "279113349", serviceId "22563223", servicePricingLevelId "25845686",
bookingTimeSegments [{durationType "SERVICING", totalDurationInSeconds 3600,
  isMainServicingTime true}],
employees [{id "3440861", isRequested false}],
customer {id, fullName}, service {...}
```

## Cancel appointment

From the appointment drawer, "Cancel" does:

1. Query `appointment_appointmentTerminationSummary` (fee position, customer,
   location, `cancellableFutureAppointmentsCount`).
2. Mutation `initializeAppointmentProtectionEnforcement`. When there is no fee
   to charge it returns a GraphQL error with code `NO_FEE` and null data. The
   dashboard treats that as normal.
3. Mutation `cancelAppointmentWithNoCharge` with the appointment id. Response:
   `{"cancelAppointmentWithNoCharge":{"appointmentId":"1330548061"}}`.
4. `calendar_dailyCalendarEvents` refetch.

The cancel screen has a "Send a cancellation notification" tick box, on by
default. Whatever flag carries it was not captured.

## Availability

Query `availableTimeSlots` returns, per date, `closed` and a list of
`possibleOffers[].startTime` at 5-minute granularity for the chosen service,
employee and location. Example for Jess, Gel polish, Friday 2026-10-23: starts
from 10:00 to 13:00 every 5 minutes, then 15:30, nothing later. This is the
call to use for "what can I offer the client", not the calendar events.

`SchedulingConflicts` returns `scheduledItemsConflicts: []` when the chosen
slot is clean.

## Ids confirmed in this test

| Thing | Id |
|---|---|
| Location (The Looking Glass Beauty) | 1530970 |
| Owner / `__pid` | 1453889 |
| Jess (employee) | 3440861 |
| Service "Gel polish" (Senior Nail Services - TLG) | 22563223 |
| Its pricing level (from £34, 60 min) | 25845686 |
| Test client "Danny Cooke" | 279113349 |

Other employee ids are in `knowledge/fresha.md`.

## Payment policy

The create flow queried `appointment_calculateAppointmentProtectionFees` and
got `strategy "CARD_CONFIRMATION"`, `cancellationFeeAmount "34.00"`,
`depositAmount "0.00"`. So new appointments for this client default to
"capture card details only" with a cancellation fee equal to the price. The
bot must decide what policy to send, or send none and accept the default.

## Still unknown (capture next)

- The request body of a mutation: whether it carries the full query text, a
  persisted query id, or both, and the exact `variables` for create.
- The auth cookie or header, and how long a session lasts without a browser.
- Whether a CSRF or client-fingerprint header is required.
- The exact `bookings[]` item fields.

Cheapest way to get all four: Chrome DevTools, Network tab, filter `graphql`,
make one booking, right-click the POST with no `_query` and use
"Copy > Copy request" or "Export HAR with content". Keep the result out of
the repo; it contains the session.

## How this was captured

The app keeps private references to `fetch` and `JSON.stringify`, so patching
either on `window` sees nothing. Patching `Response.prototype.json` and
`.text` does work and gives every response plus its URL, which is where the
operation name lives. The Claude in Chrome extension's own network reader only
records during tool-driven actions and redacts the `_query` value, so it is
not enough on its own.
