# Architecture

## Constraints that shape everything

- **Fresha has no public write API, no webhooks and no Zapier app** (checked
  September and October 2026). The bot cannot create bookings in Fresha.
  What Fresha does give us:
  - Shareable booking links that can be pre-filtered to a service and/or a
    team member.
  - Native per-team-member Google Calendar sync (export, import or two-way,
    roughly 15 minute delay, times only, no client details).
  - Notification emails for new, changed and cancelled bookings.
  - A read-only Snowflake data connector for reporting.
- Facebook and Instagram are both Meta, so one Meta app, one webhook and one
  Graph API token cover both channels.

## Components

```
Client (Messenger DM)                     Client (Instagram DM)
        |                                         |
        v                                         v
Meta app Tlg-app1 --webhook POST-->  API Gateway (HTTP API)  <--webhook POST-- Meta app Tlg-app2
                        /webhook/messenger   |   /webhook/instagram
                                             v
                     Lambda per channel: tlg-prod-messenger-bot, tlg-prod-instagram-bot
                               (same code, CHANNEL env var; BOT_MODE simple | shadow | live;
                                MESSAGE_TEST_MODE gates replies behind a trigger word)
                                 - verify X-Hub-Signature-256
                                 - dedupe message id (DynamoDB)
                                 - load conversation history (DynamoDB)
                                 - build prompt from persona/ (jess, voice guide, vocabulary) + salon config
                                 - call Claude (Claude Platform on AWS, SigV4)
                                 - structured reply: {reply_text, escalate, reason, booking_link}
                                 - send reply via Graph API
                                 - if escalate: publish to SNS -> email/SMS to Jess
                                        |
                                        v
                              Secrets Manager: Meta page token, app secret
```

### Webhook handlers (`src/bot/`)

Two Lambdas from one package behind one HTTP API, one per Meta app (the
user's call, 2026-10-19: each channel goes live, gets reviewed and is
debugged on its own). Per channel:

- `GET /webhook/<channel>` answers Meta's verification challenge.
- `POST /webhook/<channel>` receives that channel's message events, signed
  with that app's secret. Meta sends it the moment a message arrives.

While `MESSAGE_TEST_MODE` is true a message is answered only if it starts
with the trigger word (default "joshsmells"), which is stripped before the
bot reads it; everything else is stored and logged, never answered, in every
mode. This is the user's guardrail for testing against the live Page.

`BOT_MODE` says how a message is answered. `simple`: a plain acknowledgement
naming the channel and echoing the text, no Claude, no persona, and an email
to the ops topic with the message and the reply (the first stage; the user
adds the framework and persona later). `shadow`: draft a reply with Claude
and email it to Jess. `live`: reply with Claude. Every Graph call carries an
appsecret_proof, so the apps' "Require app secret" setting is on.

Replies are not instant: the bot shows the typing indicator and sends
`reply_delay_seconds` (default 10, user's call: a person does not answer in
under a second) after the message arrived; time spent on Claude and Fresha
counts towards it. The message is marked seen in the store before the wait,
so a Meta retry during it is dropped as a duplicate.

In the Claude modes the bot also fetches the client's name once per thread
(Meta User Profile API) and can look up real availability: Claude gets a
`check_availability` tool, served from Fresha's public booking flow with no
login (`src/bot/availability.py`, `knowledge/fresha.md`), one service, up to
three people, up to four dates, read only. Every hand-over names who should
pick it up (`escalate_to`: jess, carmen, lori-dee), what it is about (`area`)
and why (`escalation_kind`). A complaint or "can't assist anymore" locks the
thread: the bot stays quiet until a person clears the hand-over. A booking
or a cancellation hand-over tells the team and the bot keeps talking, since
the client is mid-conversation.

The handler is deliberately thin. The voice lives in `persona/` (three files, see
`docs/voice-analysis.md` for where it came from) and all salon knowledge lives
and in Terraform variables (services, staff, opening hours, booking links), which
are rendered into the system prompt at deploy time.

### Claude call

- Client: `AnthropicAWS` from the `anthropic[aws]` package. Auth is the Lambda's
  IAM role via SigV4, so there is no Anthropic API key to store or rotate.
  Billing goes through AWS Marketplace.
- Model: `claude-opus-5-5` (Terraform `claude_model`), adaptive thinking, effort `low` (chat
  workload). Sonnet 5.5 was tried for a few hours on 2026-10-25 because the first Instagram
  reply took 20 s end to end, 14 s of it the Opus call: Sonnet's call took 12.4 s and it
  over-searched availability, so Opus is back. The time to win is around the call (cold
  start, the Fresha session check), see decisions.
- Output: structured JSON via `output_config.format`, so the handler never has to
  parse prose. Fields: `reply`, `escalate`, `escalation_reason`,
  `suggested_booking_link`.
- Prompt caching: the system prompt (persona + salon config) is stable and
  cached. Conversation history follows it.
- Refusals: on Claude Platform on AWS the server-side `fallbacks: "default"` is
  available and is enabled. A refusal that still gets through is treated as an
  escalation, never sent to the client.

### Conversation state

DynamoDB table keyed by `sender_id` (Meta PSID or IGSID). Stores the last N turns,
a `handed_to_jess` flag, and the last seen message id for dedupe. TTL of 30 days.

When `handed_to_jess` is set the bot stays silent on that thread until Jess
clears it (a small admin endpoint, or a TTL). This stops the bot talking over
her.

### Client list (plan job 10)

DynamoDB `tlg-prod-clients`, one row per Fresha client id, filled daily by
`tlg-prod-client-sync` from Fresha's client search, each client's record
(marketing ticks) and each client's profile page (owner's session, same as
booking): patch tests, allergies, tags, badges, staff alert, notes, files,
upcoming and past appointments, consultation forms, statistics. Four calls
a client, stalest first inside the Lambda's time budget, leftovers next
run. Fresha's fields are overwritten each run; ours (`sms_opt_out`,
`lists`, `token`, the send log) are created once and never touched by the
sync. The row is the salon's view of a client for any automation (a
colour booking checks `patch_test_active`; an offer checks `textable`). `tlg-prod-unsubscribe` answers
`/stop/{token}` on the webhook API: a page with a button, the button POSTs
the opt-out. Texts carry `tlg-beauty.co.uk/stop/<token>`; the website
redirects `/stop/*` to the API. Rows that leave Fresha are flagged `in_fresha=false`, kept.

### Escalation

A hand-over records who has the thread and for what. With Jess the bot
goes silent. With Lori-Dee (hair) or Carmen (tattoos) it keeps reading and
answers only what is its own (nails, beauty, lashes, aesthetics, the
salon), leaving their area and any reply to them alone; the thread stays
theirs (decision 2026-10-24).

SNS topic `tlg-escalations`. Subscriptions are Terraform variables (Jess's email
and mobile). The message includes the client's name, the thread so far, and a
deep link to the conversation in Meta Business Suite.

Triggers for escalation (also written into the persona):

- Complaints, refunds, anything about a bad result.
- Medical questions (patch tests, pregnancy, allergies) beyond the standard
  patch-test rule.
- Requests the bot cannot resolve with a booking link (group bookings, events,
  bespoke pricing).
- Any message the model is not confident about.
- Any model error or refusal.

### Google Calendar mirror

Fresha's own Google Calendar sync is per team member. Each person can switch it
on from their own Fresha profile, or the owner can do it for them from Team >
Team members. It is not reachable by API, so it cannot be Terraformed. The
step-by-step guide is in `docs/calendar-sync.md`.

What Terraform **can** own: the staff list (`var.staff`, generated from
Fresha by the menu sync) with each person's Fresha booking link, plus
`var.calendar_emails` for their Google accounts. That list drives the bot's prompt and an
onboarding checklist output (`terraform output staff_onboarding`) that tells a
new staff member exactly what to switch on in Fresha. Offboarding is removing
the map entry. If a code-driven mirror is ever needed, the only input available
is Fresha's notification emails (SES inbound -> Lambda -> Google Calendar API).
That is a later phase.

### Menu sync (`src/menu_sync/`)

Lambda `tlg-<env>-menu-sync`, run every hour from 07:00 to 22:00 London time by
EventBridge Scheduler, and on demand. It keeps the bot's menu equal to Fresha's:

1. Reads the team (name, Fresha employee id, job title) from the public venue
   page, and the full service menu from the public booking flow. Then calls
   the booking flow once per person to learn who can be booked for what. No
   login; these are the calls a client's browser makes.
2. Builds `terraform/fresha-menu.auto.tfvars.json`: the `staff` map (slug,
   name, role, employee id, booking link, categories) and the `services`
   list (category, name, price, duration, staff, notes). Sorted, so an
   unchanged menu renders byte-for-byte the same.
3. Fetches the same file from the base branch on GitHub and compares the
   staff and services parts (the snapshot date is ignored).
4. If different: pushes the new file to branch `menu-sync`, opens a pull
   request (or updates the open one) listing every added, removed and changed
   person and service, and emails the ops topic. If equal: does nothing.

The GitHub token is a fine-grained PAT read from Parameter Store at run time
(`/tlg/<env>/github/pat`, SecureString, written by the deploy pipeline).
The deploy workflow runs the tests on that PR and merges it with the PAT when
they pass, which triggers the deploy; nobody has to touch it. Hand-written facts
(hours, address, notes to the bot, calendar emails) stay in
`salon.auto.tfvars` and are never touched by the sync.

Run it from a laptop without AWS or GitHub:

```
PYTHONPATH=src python -m menu_sync --venue-url <fresha venue url> --out terraform/fresha-menu.auto.tfvars.json
```

Failure modes it reports: Fresha changed the venue page layout, changed or
retired the persisted booking-flow query (`PersistedQueryNotFound`), or the
GitHub token lost access. The Lambda error alarm pages the ops topic.

### Fresha watch (`src/fresha_watch/`)

Lambda `tlg-<env>-fresha-watch`, run hourly at half past from 07:30 to 22:30
London time by EventBridge Scheduler, and on demand. It answers one question:
have Fresha's public pages changed shape under the menu sync. Checks:

| Check | What it does | Shape watched |
|---|---|---|
| `venue_page` | Loads the venue page, reads its Next.js data, parses the team | Top-level keys of the location record; the whole `employeeProfiles` subtree |
| `booking_flow` | Sends the persisted booking-flow query, parses the menu | Top of `bookingFlowInitialize`; the `categories[].items[]` subtree |
| `booking_flow_per_person` | Same query filtered to the first listed person | None; works or not |
| `general_link` | Loads the general booking link and expects the salon's name | None; works or not |

A shape (`shape.py`) is the sorted list of leaf paths with a coarse kind
(value, object, list). List elements are merged and scalars are all "value",
so content changes are invisible; only keys and nesting count. The previous
run lives in `/tlg/<env>/fresha-watch/state` (SSM). On a transition (a check
fails, recovers, or its shape differs) the Lambda texts `alert_phone_numbers`
through AWS End User Messaging from the sender ID TLGWATCH, and emails the
ops topic through SNS with the added and removed paths. Nothing
is sent when nothing moved. The Lambda error alarm goes to the ops topic.

Run the checks without saving or sending: invoke with `{"dry_run": true}`.

### Monitoring (`src/monitor/`)

A second Lambda from the same build, run by EventBridge (default every hour,
`var.monitor_schedule`). It answers two questions: is everything still
working, and has anything we depend on changed shape. Findings go to the
`tlg-ops` SNS topic (`var.ops_alert_emails`, meaning you), never to Jess. The
bot's Lambda error alarm goes there too.

Checks, in order:

| Check | What it does | Alerts when |
|---|---|---|
| `webhook_endpoint` | Replays Meta's GET verification handshake against our API Gateway URL with the real verify token | Not a 200 echoing the challenge |
| `meta_page` | `GET /me` with the page token, then `/{page}/subscribed_apps` | Token invalid, token for another page, or app no longer subscribed to `messages` |
| `fresha_links` | Loads the venue page, the general link and every per-person booking link | Any link not 200, or page no longer names the salon |
| `fresha_dashboard` | Loads partners.fresha.com and reads the app version and runtime bundle | Shell down or unreadable. Version changes are logged, not alerted (Fresha ships several builds a day) |
| `fresha_create_contract` | Follows the dashboard's chunk map to the appointment drawer code, extracts the function that builds the create-appointment mutation input, strips minifier renames and hashes it | The hash moves (the mutation input shape changed), the expected operation names are gone, or the chunk vanished |
| `bot_traffic` | Bot invocations and errors in the last 24 hours | Never; it is context in the alert body |

The monitor only reports transitions. A check that is newly failing, newly
recovered, or whose fingerprint has changed produces one message. A check that
stays broken is quiet until it recovers, so an hourly schedule does not mean
hourly email. State lives in one SSM parameter.

Two CloudWatch alarms watch the monitor itself: errors, and no invocation for
three hours. Silence is therefore a signal too.

What it cannot see yet: whether a logged-in call to Fresha's GraphQL still
works. That check is added once the booking integration exists and the
session handling is settled (see `knowledge/fresha-internal-api.md`). Until
then the contract fingerprint is the early warning.

Run it by hand after a deploy:

```
aws lambda invoke --region eu-west-2 --function-name $(terraform output -raw monitor_function_name) --cli-binary-format raw-in-base64-out --payload "{}" out.json && cat out.json
```

### TLG Academy (plan job 17, separate stack and workflow)

- **Site:** static files in `academy/web/` (no build step; plain ES
  modules, Markdown lessons rendered in the browser) on a private S3
  bucket behind CloudFront with origin access control, security headers,
  and `academy.tlg-beauty.co.uk` once Krystal's CNAMEs exist.
- **Login:** Cognito user pool, hosted UI, authorization code with PKCE
  done by `academy/web/auth.js`; `admins` group; a post-confirmation
  Lambda puts `TLG_ACADEMY_ADMIN_EMAILS` into the group on sign-up.
- **API:** HTTP API with the Cognito JWT authoriser on every route,
  one Lambda (`src/academy/handler.py`): profile, request access, lesson
  complete, signed file link, admin list and decide. Approval status is
  checked server-side on every lesson and file request.
- **Data:** one DynamoDB table (PK/SK, GSI1 on enrolment status) and a
  private files bucket for the manual.
- **CPD rules in the templates:** provider logo only on home/about and the
  footer, linked to the register; per-course badge slot empty until
  accredited; `TLG_ACADEMY_ACCREDITATION_PENDING` forces "pending"
  everywhere; no certificates generated.

## Build order

1. Persona and salon config, with unit tests on the prompt builder.
2. Lambda handler with Meta signature verification and the Graph API send.
3. Terraform: HTTP API, Lambda, DynamoDB, SNS, Secrets Manager, IAM, and the
   scheduled monitor with its ops topic.
4. Meta app setup (manual): app, webhook subscription, page token. No app
   review: Messenger's `pages_messaging` reaches the public at Standard
   Access, and Instagram runs on the Instagram Login route with the salon
   account's own token (plan job 18, 2026-10-27), which Meta exempts for an
   app serving only the business's own account.
5. Shadow mode: bot drafts replies and escalates everything to Jess for a week.
6. Live mode for standard booking conversations only.

## Not in scope yet

- Writing bookings into Fresha (no API).
- Posting to Facebook/Instagram (marketing automation). Separate module later.
- Fresha "AI Concierge" add-on. Revisit if the DM bot is not enough.
