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
Client (Messenger / Instagram DM)
        |
        v
Meta Platform  --webhook POST-->  API Gateway (HTTP API)
                                        |
                                        v
                               Lambda: webhook handler
                                 - verify X-Hub-Signature-256
                                 - dedupe message id (DynamoDB)
                                 - load conversation history (DynamoDB)
                                 - build prompt from persona/jess.md + salon config
                                 - call Claude (Claude Platform on AWS, SigV4)
                                 - structured reply: {reply_text, escalate, reason, booking_link}
                                 - send reply via Graph API
                                 - if escalate: publish to SNS -> email/SMS to Jess
                                        |
                                        v
                              Secrets Manager: Meta page token, app secret
```

### Webhook handler (`src/bot/`)

One Lambda behind an HTTP API. Two routes:

- `GET /webhook` answers Meta's verification challenge.
- `POST /webhook` receives message events for both Messenger and Instagram.

The handler is deliberately thin. All salon knowledge lives in `persona/jess.md`
and in Terraform variables (services, staff, opening hours, booking links), which
are rendered into the system prompt at deploy time.

### Claude call

- Client: `AnthropicAWS` from the `anthropic[aws]` package. Auth is the Lambda's
  IAM role via SigV4, so there is no Anthropic API key to store or rotate.
  Billing goes through AWS Marketplace.
- Model: `claude-opus-5-5`, adaptive thinking, effort `low` (chat workload).
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

### Escalation

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

Lambda `tlg-<env>-menu-sync`, run every two hours from 07:00 to 21:00 London time by
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
aws lambda invoke --function-name $(terraform output -raw monitor_function_name) /dev/stdout
```

## Build order

1. Persona and salon config, with unit tests on the prompt builder.
2. Lambda handler with Meta signature verification and the Graph API send.
3. Terraform: HTTP API, Lambda, DynamoDB, SNS, Secrets Manager, IAM, and the
   scheduled monitor with its ops topic.
4. Meta app setup (manual): app, webhook subscription, page token, app review
   for `pages_messaging` and `instagram_manage_messages`.
5. Shadow mode: bot drafts replies and escalates everything to Jess for a week.
6. Live mode for standard booking conversations only.

## Not in scope yet

- Writing bookings into Fresha (no API).
- Posting to Facebook/Instagram (marketing automation). Separate module later.
- Fresha "AI Concierge" add-on. Revisit if the DM bot is not enough.
