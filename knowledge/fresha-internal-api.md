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
- Queries also carry `_query=<operationName>` in the query string; mutations
  carry `_mutation=<operationName>` instead.
- Request body (captured 2026-10-20): `application/x-www-form-urlencoded`
  with three fields, `operationName`, `query` (the full GraphQL text, no
  persisted-query hash) and `variables` (a JSON string). No other fields.
- Request headers: only `accept` and `content-type` beyond what the browser
  adds. The browser's CORS preflight to this host asks for `content-type`
  only, so there is no authorization, CSRF or fingerprint header.
- Auth is cookies on `.fresha.com`, sent with `credentials: include`. The
  ones that matter (all HttpOnly, Secure):
  - `fresha_partners_session` (88 chars): the login session. Expiry seen
    2026-11-14, about 25 days after the login it came from.
  - `_gatekeeper_session_token` (36 chars) and `_gatekeeper_user_id`: expiry
    a year out.
  - `fresha_partner_trusted_device` (88 chars): expiry about a year out;
    presumably what lets a known browser skip the login challenge.
  Everything else in the cookie jar is analytics (GA, TikTok, HubSpot,
  Amplitude, Bing) and not needed. No API response in the capture set or
  refreshed a cookie, so the session is set at login and not slid by use;
  whether a page load refreshes it is not known.
- Responses are standard GraphQL JSON with `__typename` on every object.
- The same cookies authenticate the other Fresha APIs the dashboard uses
  (see "Other APIs"), all of which take `__pid`, `_client_platform` and
  `_client_version` in the query string.
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

Exact variables as the dashboard sent them on 2026-10-20 (one service, one
employee, a known client, 90 minutes at 2pm):

```json
{"input": {
  "appointment": {
    "bookings": [{
      "bookedServiceAddOns": [],
      "employees": [{"id": "5029221", "requested": false}],
      "orderItemRef": "wq4xwxJrlfMGsrwUT9kqN",
      "resources": [],
      "servicePricingLevel": {"catalogPrice": "48", "id": "20472294"},
      "startDateAndTime": {
        "date": "2026-10-29",
        "timeOfDay": {"hours": 14, "minutes": 0, "seconds": 0},
        "timezone": "Europe/London",
        "wallClockTime": "14:00:00"
      },
      "timeSegments": [{"durationInSeconds": 5400, "isMainServicingTime": true,
                        "sortingId": 0, "type": "SERVICING"}]
    }],
    "customerId": "279113349",
    "locationId": "1530970",
    "priceModifiers": []
  },
  "appointmentProtection": {"appointmentProtectionAction": "DEFAULT_SETTINGS"},
  "metadata": {"idempotencyKey": "uc02FTprM05e62337Hcol", "source": "new"}
}}
```

`orderItemRef` and `idempotencyKey` are random 21-character ids made in the
browser (nanoid style). `catalogPrice` is the pricing level's list price as a
string; the duration comes from the pricing level too. Omit `customerId` for
a walk-in. The query text is 325 characters and is in `.local`.

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
3. Mutation `cancelAppointmentWithNoCharge`. Variables:
   `{"input": {"appointmentId": "1331531978", "cancellationOptions":
   {"cancelFutureAppointments": false}, "sendNotification": false}}`.
   Response: `{"cancelAppointmentWithNoCharge":{"appointmentId":"1331531978"}}`.
4. `calendar_dailyCalendarEvents` refetch.

Step 2's variables are `{"input": {"action": "CANCELLATION", "appointmentId":
"..."}}`. The cancel screen's "Send a cancellation notification" tick box is
`sendNotification` in step 3.

## Availability

Query `availableTimeSlots` returns, per date, `closed` and a list of
`possibleOffers[].startTime` at 5-minute granularity for the chosen service,
employee and location. Example for Jess, Gel polish, Friday 2026-10-23: starts
from 10:00 to 13:00 every 5 minutes, then 15:30, nothing later. This is the
call to use for "what can I offer the client", not the calendar events.

Variables as sent (one attendee, one service, a requested employee):

```json
{"input": {
  "attendees": [{"attendeeId": "1", "offerItems": [{
    "itemType": "SERVICE_PRICING_LEVEL", "offerItemId": "1", "position": 1,
    "servicePricingLevel": {
      "forceMaxDuration": false, "ignoreAssignments": true,
      "requestedEmployeeId": "5029221", "servicePricingLevelId": "20472294",
      "timeSegmentsOverride": [{"duration": 5400, "isMainServicingTime": true, "type": "SERVICING"}]
    }}]}],
  "dateRange": {"endDate": "2026-10-23", "startDate": "2026-10-23"},
  "locationId": "1530970",
  "timeslotSettingsMode": "UNRESTRICTED"
}, "withAttendees": false}
```

`UNRESTRICTED` is the dashboard's view: it ignores the online-booking
rules (lead time, cut-off) that the public flow applies. The bot should
probably keep using the public flow for what to offer and only use this one
to double-check before writing.

`SchedulingConflicts` returns `scheduledItemsConflicts: []` when the chosen
slot is clean.

## Client search

`GET https://customers-api.fresha.com/v2/customer-search` with the usual
`__pid`, `_client_platform`, `_client_version` plus `query=<text>`,
`limit`, `offset` and `include-customers-count=true`. Same cookies as the
GraphQL. Response is JSON:API (`application/vnd.api+json`): `data[]` of
`{id, attributes: {name, contact-number, email, blocked, created-at,
email-verified, phone-verified, labels, ...}}`. Matching by phone or email
is safer than by name; the salon has around 600 clients and names repeat.

The same host serves `GET /v2/customers/<id>` (full record) and
`GET /customer-duplicates/existence-check`. The mutation that creates a new
client was not captured (no new client was made during the recording).

## Other APIs

All under the same cookies and query-string ids:

- `partners-api.fresha.com` (REST, JSON:API): `/employees` and
  `/v2/employees?location-id=`, `/locations`, `/closed-dates?date-from=&
  date-to=&location-id=`, `/cancellation-reasons`, `/customers/<id>/...`
  (statistics, recently-booked-appointments, paid-plans).
- `staff-working-hours-api.fresha.com/graphql`: `blockedTimeOccurrences`
  (dateFrom, dateTo, location), i.e. blocked-out time on the calendar.
- `partners-calendar-api.fresha.com/alpha-graphql`: calendar provider
  settings, not needed.
- `unleash-proxy.fresha.com`: feature flags; the only host that gets an
  authorization header, and it is a public client key, not the session.

## Ids confirmed in this test

| Thing | Id |
|---|---|
| Location (The Looking Glass Beauty) | 1530970 |
| Owner / `__pid` | 1453889 |
| Jess (employee) | 3440861 |
| Service "Gel polish" (Senior Nail Services - TLG) | 22563223 |
| Its pricing level (from £34, 60 min) | 25845686 |
| Test client "Danny Cooke" | 279113349 |
| Sav (employee, 2026-10-20 booking) | 5029221 |
| Pricing level booked 2026-10-20 (£48, 90 min; not in the online menu export) | 20472294 |

Other employee ids are in `knowledge/fresha.md` and
`terraform/fresha-menu.auto.tfvars.json`. Pricing level ids for the bot's
services come from `pricingCatalogList` or the public flow; the menu export
does not carry them yet.

## Payment policy

The create flow queried `appointment_calculateAppointmentProtectionFees` and
got `strategy "CARD_CONFIRMATION"`, `cancellationFeeAmount "34.00"`,
`depositAmount "0.00"`. So new appointments for this client default to
"capture card details only" with a cancellation fee equal to the price. The
bot must decide what policy to send, or send none and accept the default.

## Login (recorded 2026-10-20 from a fresh incognito window)

There is no password. Fresha's partner login is one-time codes, with a
second code on a device it has not seen, and a reCAPTCHA token on each code
request. All mutations go to the same GraphQL endpoint with `_mutation=`:

1. `users_loginAvailableChannels` (query, before login): `["EMAIL", "SMS",
   "WHATSAPP"]`.
2. `auth_requestOtp` with `{email, recaptchaToken, capabilities:
   ["ACCOUNT_SELECTION"]}`. Returns a `flowId`, `codeExpiresAt`,
   `resendAvailableAt` (60 seconds later) and the channels the code can be
   resent on. The code went to the email address.
3. `auth_verifyOtp` with `{flowId, code}`. On a new device the result is not
   a session but a second step: `identifierType: "PHONE"` and the masked
   phone number the next code will go to.
4. `auth_requestDualVerificationOtp` with `{flowId, recaptchaToken}`: sends
   a code by SMS to the account's phone (WhatsApp also offered).
5. `auth_verifyOtp` again with `{flowId, code, shouldTrustDevice: true,
   deviceMetadata: {browserName, osName, deviceModel, deviceType}}`. The
   response sets the two cookies that matter:
   - `fresha_partners_session`, `max-age=2592000` (30 days), HttpOnly.
   - `fresha_partner_trusted_device`, `max-age=31536000` (1 year), HttpOnly.
6. The app then loads (`users_profileDetails`, `appInitializationQuery`,
   `currentEmployeePermissionsQuery`, ...).

Not seen: what the flow looks like on a trusted device. Presumably steps 1
to 3 only, with step 3 returning `succeeded: true` straight away. A device
is "trusted" by presenting the year-long cookie, so a browser profile that
keeps that cookie needs only the email code for the next twelve months.

Consequences for the bot (see `docs/plan.md`, job 4):

- Nothing to store but cookies. There is no password to put in a secret.
- A fully unattended login would need to receive email, receive SMS on a
  phone number we control, and produce reCAPTCHA tokens from a headless
  browser. The reCAPTCHA is the part that makes that fragile and
  questionable, so the plan does not do it.
- The session is 30 days from login, not refreshed by use. A person logs
  in once a month, through a script that keeps the trusted-device cookie
  between runs so only the email code is asked for, and stores the session
  cookie in Secrets Manager. Two minutes a month.

## Still unknown

- The create-client mutation, for a client the bot cannot find by search.
- Reschedule: not recorded yet. Likely an update mutation on the booking.
- Whether the session cookie's 30 days is also enforced server-side at
  exactly 30 days, or the server cuts it earlier on inactivity. The bot
  will see a 401 and say so either way.
- Whether `auth-api.fresha.com/pin-switching/session/heartbeat` (POST, 403
  before login) matters once logged in. Probably the staff-PIN feature.

## How this was captured

2026-10-19: patching `Response.prototype.json` and `.text` captured every
response and its URL. On that day patching `window.fetch` saw nothing; on
2026-10-20, with the hook installed after the page had loaded, `window.fetch`
did see every call with its body and headers, so the app does go through
`window.fetch` at least in the current bundle. Cookies are HttpOnly and
never visible to page scripts.

2026-10-20: the owner drove a booking, a cancel, the client list and a
booking from a client's page in the extension's tab with DevTools open, then
exported the HAR. Lessons: DevTools must be attached to the tab the clicks
happen in; the export only includes what the filter box shows (clear it so
the counter reads n/n); and only "Export HAR (with sensitive data)" keeps
the cookies, the sanitized export strips every cookie from every entry.

The three raw files live in `.local/` (git-ignored, contain the session and
client data): `fresha-booking.har`, `fresha-capture-2026-10-20.json` (the
hook's copy, no cookies) and `export_customer_list_2026-10-20.csv` (the
client list from Fresha's own export, 593 clients).
