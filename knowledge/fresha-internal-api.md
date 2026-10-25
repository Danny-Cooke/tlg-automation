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

## A client's upcoming appointments, and whether cancelling costs

`CustomerOverviewUpcomingAppointmentQuery {customerId}` is the client
card's "next appointment" query: `Appointments_appointments(first: 1,
customerId, onlyFuture: true, order START_DATETIME asc)`. The recorded text
had `first: 1` hard-coded; `src/bot/fresha_ops.py` carries it with a
`$first` variable instead, and Fresha accepted that (checked live
2026-10-21, nine rows back). `onlyFuture` still includes cancelled
appointments, so filter on `status` (UNCONFIRMED, CONFIRMED, CANCELLED seen),
and ask for a big page: the bot sends `first: 100` because with 10 a client
with ten cancelled future appointments ahead of a live one looked as if
they had nothing booked (seen live 2026-10-21 on the owner's test client).
Each node has `startWallClock` ("2026-10-29T10:00:00[Europe/London]"),
`bookings[].service.name`, `bookings[].employee.firstName/lastName`,
`bookings[].price`.

`initializeAppointmentProtectionEnforcement {action: CANCELLATION,
appointmentId}` is the fee signal: the `NO_FEE` error means cancelling is
free now; otherwise `appointmentProtectionEnforcement.protectionAmount` is
what the salon's policy would charge. On an already-cancelled appointment it
errors with "Appointment already cancelled". The bot's cancel tool cancels
only in the `NO_FEE` case and hands over otherwise, so the team keeps every
fee decision.

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

The same host serves `GET /v2/customers/<id>?include=referred_by_customer`
(full record, type `customers-v2`) and `GET /customer-duplicates/existence-check`.
The full record is where the marketing ticks live; the search rows do not
carry them. Attributes (2026-10-23, from the same capture): `name`,
`first-name`, `last-name`, `contact-number`, `additional-contact-number`,
`email`, `additional-email`, `blocked`, `block-note`,
`accepts-sms-marketing-notifications`, `accepts-marketing-notifications`
(email), `accepts-whatsapp-marketing-notifications`,
`enable-sms-notifications`, `enable-email-notifications`,
`enable-whatsapp-notifications`, `birthday-day/month/year`, `gender`,
`created-at`, `updated-at`, `deleted-at`, `is-obfuscated`, `labels`, and a
`referral-source` relationship whose name is in `included` (type
`referral-sources`). `GET /v2/customers/<id>/marketing-consent-log` exists
too (empty for the client viewed). The client search with an empty `query`
and `include-customers-count=true` lists everyone, 25 a page in the
recording, with `meta.results-count` as the total; the client mirror
(`src/clients/sync.py`) pages it that way.

Not captured: the mutation that creates a new client, and the call that
saves a client's marketing ticks (needed for job 10 step 3; record it by
toggling "SMS marketing" on a profile with DevTools open).

## A client's profile page (recorded 2026-10-24)

Opening a client from Clients list (`/clients/list/drawer/clients/<id>`)
and its Records tabs sends, with the usual ids and cookies:

GraphQL (`partners-api-gateway.fresha.com/graphql`, `_query=<name>`):

- `CustomerLeftDrawer($customerId)`: names, contact, blocked, birthday,
  gender, pronoun, `staffAlert`, `hasPaymentMethod`, `onlineProfile`,
  `labels` (typed badges: `Customers_NoShowLabel{count}`,
  `Customers_BirthdayLabel{date}`, `Customers_UnpaidLabel{amount}`),
  `tags(first:50){id name assignedAt}`, `segmentBadges(first:50)
  {definition{badgeName badgeColor}}`, `allergies(first:50){name severity
  type reaction description}`, `patchTests(first:1, onlyActive:true)`.
- `PatchTestFieldsForCounter($customerId)`: `patchTestCount`.
- `ListCustomerPatchTests($customerId, $after, $first:20)`:
  `patchTests{ id title status performedDate isExpired createdAt
  confirmationRequired expirationDate }`. Status values have not been seen
  on a real test yet (every client opened so far had none).
- `ListClientNotes($customerId, $after, $first:5, $sort:"ACTIVITY_DATE",
  $includeClientNote:true)`: `Notes_notes` with `NoteCard` (body, type,
  author, appointment, sale, attachments with signed and CDN urls).
  `ClientNotesCounts` gives the counts.
- `ListCustomerAttachments($customerId, $first:10)` and
  `CustomerAttachmentsCount`: `Notes_attachmentsByCustomer`.
- `CustomerUpcomingAppointmentQuery($customerId, $after)`:
  `Appointments_appointments(first:5, customerId, onlyFuture:true,
  order:{field:START_DATETIME, direction:ASC})`;
  `CustomerPastAppointmentQuery` the same with `onlyPast:true`, `first:10`,
  DESC. Each appointment: id, status, statusLabelId, startWallClock,
  consultationForms{id status}, preferredNote{note{body}}, bookings{ price
  priceType startWallClock endDatetime servicePricingLevelId service{name
  servicePricingLevels{id name}} employee{firstName lastName}
  bookingServiceAddOns{serviceAddOn{name}} }.
- Also fired, empty for this salon: `CustomerMembershipSubscriptions`,
  `CustomerPackageInstances`, loyalty, `reviewsV2_customerReviewsSummary`,
  `reviewsV2_customerAppointmentRatings`, `forms_formsExperience`.

REST, same cookies, `accept: application/vnd.api+json`:

- `GET customers-api.fresha.com/v2/customers/<id>` (the record, see Client
  search above) and the older `GET customers-api.fresha.com/customers/<id>`
  (adds `note`, `display-note`, `telephone`, `notification-setting`).
- `GET partners-api.fresha.com/customers/<id>/statistics`: attributes
  `bookings-count`, `completed-`, `cancelled-`, `no-show-`, `confirmed-`,
  `unconfirmed-bookings-count`, `total-sales`, `total-sales-count`,
  `outstanding-sales`, `paid-/unpaid-/part-paid-/refunded-/voided-sales-count`.
- `GET partners-api.fresha.com/customers/<id>/service-sale-items`,
  `/product-sale-items`, `/paid-plans`, `/ncf-events`: sales history
  (empty for the client opened).
- `GET consultation-forms-api.fresha.com/requests?customer-id=<id>&limit=1
  &offset=0&sort-by=requested_at&sort-order=desc`: forms requested of the
  client, `meta.all-count`.
- `GET customers-api.fresha.com/v2/customers/<id>/marketing-consent-log`.

The client mirror (`src/clients/sync.py`) does not replay these one by one:
`clientRecord` in `src/bot/fresha_ops.py` is one composed query carrying the
same fields (patch tests `first:50` without `onlyActive`, notes 50,
attachments 30, upcoming 20, past 50), followed by the statistics and
forms calls. Four requests a client.

## A service's cancellation and no-show fees (recorded 2026-10-24)

Edit service > Settings shows "Require late cancellation fee" and "Require
no-show fee", each with a Default/custom amount, plus "Require patch test".
The fees are not on the service record: they are per-service overrides on
the workspace's appointment-protection setting.

- Read, one call for every service: `serviceAppointmentProtectionSettingQuery`
  (no variables) returns `AppointmentProtection_appointmentProtectionSetting
  { strategy lateCancellationAndRescheduleWindowInMinutes strategySetting
  { ... on AppointmentProtection_CardConfirmationStrategySetting {
  cancellationFee{value type} noShowFeePercentage serviceSettings {
  serviceId cancellationFee{value type} cancellationFeeVariant
  noShowFeePercentage noShowFeeVariant } } ... on
  AppointmentProtection_DepositStrategySetting { depositFee ... } } }`.
  The salon: strategy CARD_CONFIRMATION, window 1440 minutes, default
  100% cancellation fee and 100% no-show fee. A service with no entry in
  `serviceSettings` inherits the defaults (both ticks on). Variants seen:
  `DEFAULT` (tick on, default amount) and `DISABLED` (tick off).
- Write, one service: mutation `setAppointmentProtectionServiceSetting`
  (`_mutation=` in the URL, no `__pid`) with `{"input": {
  "cardConfirmationStrategySetting": {"cancellationFee": null,
  "cancellationFeeVariant": "DEFAULT", "noShowFeePercentage": null,
  "noShowFeeVariant": "DEFAULT"}, "serviceId": "<id>", "strategy":
  "CARD_CONFIRMATION"}}`; the answer echoes the variants. The dashboard
  sends it alongside `services_updateServiceMutation` on Save, but it
  stands alone. Replayed 2026-10-24 for 25 services (user's request: the
  no-show fee on for every nails, Amber, beauty and tattoo service), each
  answer checked, then the read query run again: none left DISABLED in
  those categories. 96 DISABLED overrides remain, all under Sophie,
  Bernadette and Lori-Dee, untouched on the user's instruction.
- The patch-test tick is on the service itself (`patchTestRequired` in
  `services_getServiceById`, saved by `services_updateServiceMutation`),
  which is what the catalog's `isPatchTestRequired` reflects.

## Adding a client (recorded 2026-10-24)

Clients list > Add > first name, last name, email, phone > Save. The form
has more fields (birthday, gender, pronouns, addresses, emergency
contacts); the salon fills in the four. The phone box has a +44 prefix
and the number is typed without its leading 0.

- While typing, the dashboard asks `GET customers-api.fresha.com/customer-duplicates/closest-duplicates-check?contact-number=<n>&email=<e>`
  (usual ids too) and gets `{"meta": {"duplicates-check": false}}`: a yes
  or no, never which client. `GET /customer-duplicates/existence-check`
  (no params) answers `{"meta": {"existence-check": true}}`.
- `GET customers-api.fresha.com/referral-sources` lists the salon's
  sources: one, "Walk-In", id 10435303, `is-default`.
- Save: `POST https://customers-api.fresha.com/v2/customers` (no query
  string), JSON body `{"data": {"type": "customer-create-requests",
  "attributes": {...}, "relationships": {...}}}`. Attributes as the form
  sent them: `first-name`, `last-name`, `gender` "", `pronoun` null,
  `email`, `contact-number` "+44 7700 900123" (space after the country
  code and after four digits), `additional-contact-number` null,
  `additional-email` "", `birthday-day/month/year` null,
  `enable-email-notifications`, `enable-sms-notifications`,
  `enable-whatsapp-notifications` true, `accepts-marketing-notifications`,
  `accepts-sms-marketing-notifications`,
  `accepts-whatsapp-marketing-notifications` true (the form's defaults:
  every client added at the desk is opted in to marketing),
  `marketplace-appointment-confirmation-enabled` true, `is-changed` true,
  `occupation` null, `nationality` null, `avatar-filename` "",
  `referrer-reward-template-ids` null, `referee-reward-template-id` null,
  `tag-ids` [], `tag-names` [], `selected-language-locale-code` "",
  `creation-source` "client_list". Relationships: `referral-source`
  `{"data": {"attributes": {"id": "10435303"}, "type": "referral-source"}}`,
  `referred-by-customer` `{"data": null}`, `addresses` `{"data": []}`,
  `emergency-contacts` two empty entries (`type` primary and secondary,
  `destroy` true). The answer is the new record, type `customers-v2`, with
  its `id` and the attributes the v2 record carries.
- The bot (`Fresha.create_client`) sends the same body with the four
  fields filled and the default referral source looked up once. It never
  creates a second record for a number Fresha already has: `find_client_by_phone`
  searches the client list by the number first and matches on digits.
  Recorded by adding "TLG Bot Test" with the salon's own number and email;
  the user deletes that record.

## Confirmation requests and the "Send reminder" button (recorded 2026-10-24)

What "unconfirmed" means here: the salon's payment policy is card
confirmation, so a new appointment shows "Requires card confirmation,
confirmation by card requested" and Fresha asks the client to add a card.
The appointment is Confirmed once they do. Fresha sends that request
itself when the appointment is made (`confirmation_required`, by email
and by WhatsApp) and a `confirmation` message once the client confirms.

- `GET customer-notifier-api.fresha.com/appointment-notifications-history/<appointment id>`
  (usual ids): `data[]` of `appointment-history-entries` with `metadata`
  `{notification-id, status: sent|error, transport-method: email|whatsapp,
  type: confirmation_required|confirmation}` and a timestamp. On the
  appointments looked at, every WhatsApp send was `error`; the dashboard
  also runs `automatedMessages_messageAccountingZeroBalanceWarning`, so
  Fresha's paid message balance is the likely reason.
- `GET customer-notifier-api.fresha.com/messages/<notification uuid>`:
  the rendered copy (`attributes.content` HTML, `header`, `type`). The
  Confirm and Manage links in the copy are replaced with "#", so the
  client's real confirm link cannot be read back.
- The ⋮ next to the payment-policy line on an appointment offers Send
  reminder, Show policy, Edit policy, Remove policy. Send reminder is
  mutation `sendAppointmentProtectionReminder` with `{"input":
  {"appointmentId": "<id>"}}`, answer `{appointmentId}`. Fresha then
  re-sends its card-confirmation request. Recorded on a real
  appointment, button pressed by the user. The quick-actions menu at the
  bottom of the drawer has no resend.
- The bot replays it as `Fresha.send_protection_reminder` (plan job 14).

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

## Booked from code (2026-10-21)

`src/bot/fresha.py` (operation texts in `src/bot/fresha_ops.py`, driven by
`scripts/fresha_book.py`) replayed the dashboard's calls with the stored
session and no browser: client search found four Cookes, the catalog query
listed the 25 nail pricing levels, `availableTimeSlots` gave Jess's and
Sav's real gaps for the next eleven days, the protection quote came back
`CARD_CONFIRMATION` with a £34 fee, and `createAppointmentByEmployee`
booked appointment 1332159791 (Gel polish, Jess, 2026-10-29 10:00, client
279113349), status `UNCONFIRMED`. Jess's employee record is "Jess Preston".
The client got Fresha's booking confirmation with a "confirm" call to
action (the card step), so a code-made booking with `DEFAULT_SETTINGS`
triggers the same card-confirmation flow as a dashboard one. Cancelled from
code the same day with `sendNotification: true`; status read back
`CANCELLED`. The 2026-10-20 dashboard test, cancelled after eleven seconds,
produced no email, so a notification is probably held briefly and dropped
on cancel.

The catalog query (`pricingCatalogList`, 100 per page, cursor paging) is the
source of pricing level ids, list prices and durations; the two nail
categories are "Senior Nail Services - TLG" and "Nails by TLG".

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

- Reschedule: not recorded yet. Likely an update mutation on the booking.
- Whether the session cookie's 30 days is also enforced server-side at
  exactly 30 days, or the server cuts it earlier on inactivity. The bot
  will see a 401 and say so either way.

Confirmed 2026-10-20 evening: the session cookie alone, sent from AWS
CloudShell in eu-west-2 with no browser headers beyond origin and referer,
is accepted (`users_profileDetails` returned the account). Fresha does not
tie the session to the login address or browser.
- Whether `auth-api.fresha.com/pin-switching/session/heartbeat` (POST, 403
  before login) matters once logged in. Probably the staff-PIN feature.

## Two services in one appointment (recorded 2026-10-25)

The owner saved "Acrylic removal and new set" plus "Extra time for simple
nail art", both with Carmen, from the calendar's Add > Appointment with the
recorder on (`window.fetch` hook, see below). Same mutation,
`createAppointmentByEmployee`, same envelope; the only difference from a
single service is a second entry in `appointment.bookings`:

- entry 0: level 26079057, `catalogPrice "54"`, start 10:30:00, one
  SERVICING segment of 8100 s (135 min);
- entry 1: level 25845773, `catalogPrice "0.5"`, start 12:45:00 (= entry
  0's start plus its duration), one SERVICING segment of 900 s (15 min),
  the same `employees [{id, requested false}]`, its own `orderItemRef`
  (nanoid), `bookedServiceAddOns []`, `resources []`.

`priceModifiers []`, `appointmentProtection DEFAULT_SETTINGS`, `metadata
source "new"` as before. The dashboard sends the request as a form body
(`operationName`, `query`, `variables` fields), not JSON. The reply carried
one appointment id and one `primaryBookingId` (the first service's);
`viewAppointment` then lists both bookings with their own ids and levels.
No client was picked that time, and the request simply had no
`customerId` key, so a walk-in save is the same call minus that field.
Appointment 1335465114, Tue 27 Oct 10:30 with Carmen, left for the owner to cancel (the script cancel was blocked from this session).

So `Fresha.create` can take a list of (level, price, duration) and emit one
booking per service, each starting where the previous one ends. The
public availability flow would need the combined duration (plan job 16).

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
