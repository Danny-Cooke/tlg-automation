# Plan

Running list of agreed jobs and the decisions behind them. Planning is still
open: nothing below is built until the user says so, except where marked.
Started 2026-10-19. Design reasoning lives in `docs/decisions.md`; Fresha
facts in `knowledge/`.

## Agreed foundations

- **Region:** everything in eu-west-2 (London).
- **Environment:** GitHub environment `prod`, Terraform `environment = "prod"`,
  so resources are named `tlg-prod-<component>`. Whether a `dev` stack is
  wanted too is still open.
- **Terraform state:** S3 bucket `tlg-automation-terraform-state` (created by
  hand 2026-10-19: London, versioned, AES256, public access blocked, tagged
  Project=tlg). One key per stack, `<repo>/<environment>/<stack>.tfstate`:
  the menu sync uses `tlg-automation/prod/menu-sync.tfstate`, the bot
  `tlg-automation/prod/bot.tfstate`. Locking via the S3 lockfile, which
  needs Terraform 1.10 or later in the pipeline and locally (local is 1.7.5).
- **One stack per deployable job, deployed in order.** `terraform/menu_sync`
  goes first (decision 2026-10-19). `terraform/` holds the bot and monitor
  and is not applied by the pipeline until the menu sync is live.
- **Secrets path:** GitHub Actions, running under environment `prod`, passes
  the `gh_pat` environment secret to `terraform apply` as a sensitive
  variable. Terraform writes it to SSM Parameter Store as a SecureString at
  `/tlg/prod/github/pat`. Lambdas read it with decryption at run time; it is
  never put in a Lambda environment variable.
- **Tags:** provider `default_tags` on every resource: Project `tlg`,
  Environment, ManagedBy `terraform`, Owner; plus a Component tag per Lambda.
- **Naming:** every Lambda is prefixed `tlg-`.

## Jobs

### 1. Deploy pipeline (prerequisite for the rest)

GitHub Actions on merge to `main`, environment `prod`: OIDC into an AWS role,
`terraform init` against the S3 backend, `plan`, `apply`. Deploys
`terraform/menu_sync` only for now. Needs:

- The account's existing `github-oidc` role (AdministratorAccess, trusts
  `repo:Danny-Cooke/*`), the same one the other repos deploy with. No role
  or provider is created here and nothing is applied by hand.
- The GitHub `prod` environment with `GH_PAT` (secret) and `AWS_ROLE_ARN`
  (variable, set 2026-10-19).
- The repo pushed to the remote (one commit on `main` as of 2026-10-19; the
  stack split is uncommitted).

### 2. Menu sync Lambda: `tlg-prod-menu-sync` (LIVE 2026-10-19; stack `terraform/menu_sync`)

Every hour 07:00 to 22:00 London time (EventBridge Scheduler, changed from two-hourly 2026-10-19 evening) and on demand (invoke). Reads Fresha's public booking
data (no login): team list from the venue page, services with category,
price, duration and bookable staff from the booking flow. Builds what the
Terraform variables should say, compares with the repo, and when different
opens a pull request using the PAT from Parameter Store and emails the ops
topic. Silent when nothing changed.

Decisions taken while building:

- Generated `fresha-menu.auto.tfvars.json` holds staff and services; roles
  come from Fresha job titles and notes from Fresha descriptions, so nothing
  hand-written was lost. `salon.auto.tfvars` keeps hours, address, bot notes
  and `calendar_emails`.
- PR, not direct commit. Branch `menu-sync`, one open PR updated in place.
  Merged automatically by the deploy workflow once the tests pass (hands-off,
  2026-10-19 evening); the branch restarts from main for each new PR.
- Public booking flow request format captured and replayed from plain HTTP;
  details in `knowledge/fresha.md`.
- Apply after merge is job 1.
- Deployed by the pipeline 2026-10-19 18:25 UTC (run 39301305817, 10
  resources). Proven with a dry-run invoke: 8 staff, 166 services,
  unchanged against the repo. Schedule enabled, London time.

### 3. Monitor Lambda: `tlg-prod-monitor` (parked in `terraform/parked/`)

Hourly health and drift checks: our webhook handshake, Meta token and
subscription, Fresha booking links, Fresha dashboard, and a fingerprint of
the dashboard code that builds the create-appointment mutation. Alerts the
ops topic on transitions only. **Already written** (`src/monitor/`,
`terraform/monitor.tf`, tests) before planning was finished; parked and
uncommitted until the plan is agreed. Lives in the bot stack (`terraform/`),
which the pipeline does not apply yet; it reads the ops topic from the menu
sync stack's state. Details in `docs/architecture.md`.

### 4. Booking into Fresha (scope change, see decisions 2026-10-19)

The bot creates and cancels appointments through Fresha's internal GraphQL.
Availability comes from Fresha's own `availableTimeSlots`, so no staff
calendar exports are required. The request side is fully captured
(2026-10-20, `knowledge/fresha-internal-api.md`): form-encoded body with the
query text, cookies only for auth, no CSRF header, exact create and cancel
variables, and the client search endpoint. The login was recorded the
same evening and changed the runtime shape: Fresha has no password, it
sends one-time codes by email and, on a new device, by SMS, behind a
reCAPTCHA, and the session lasts 30 days from login. So there is no
unattended session keeper. Instead: a script on the owner's laptop
(`scripts/fresha_session.py`, built 2026-10-20 with the SSM parameter,
Lambda read permission and `bot/fresha_session.py` reader; run weekly)
opens a browser, the owner logs in with the emailed code, the script
keeps the trusted-device cookie in a local profile so the SMS step happens
once a year, and writes the session cookie to Secrets Manager. The bot
Lambda replays the dashboard's calls over plain HTTP with that cookie, and
posts to Telegram three days before the session runs out and on any 401.
Built 2026-10-21: `src/bot/fresha.py` (client search, catalog,
availability, clash check, payment quote, create, cancel; operation texts
in `fresha_ops.py`), proved by booking and cancelling a real appointment
from the laptop (`scripts/fresha_book.py`), and `src/bot/booking.py`, the
`book_appointment` tool: nails only, existing clients matched by exact
name, Fresha's own clash check before the write, an idempotency key per
conversation and slot (so no queue is needed), the booking recorded on the
conversation, a Telegram post and an ops email per booking, dry run outside
live mode. Widened to hair the same afternoon (decision 2026-10-21): the two
hair categories book with Lori-Dee or Sophie in Lori-Dee's register, colour
needing a patch test is refused and handed to Lori-Dee, and the Telegram
line says Hair or Nails from the service's category. The persona and prompt now read the slot back, ask "shall I pop
you in?", and only say booked when the tool said Booked. First live booking through Messenger the same day (Biab with Carmen, booked,
confirmed by email, cancelled). Cancel tool added the same afternoon: lists
the client's upcoming appointments, cancels free ones with Fresha's
notification, hands over when Fresha reports a fee. Not yet: creating new
clients (mutation unrecorded), the three-days-to-expiry Telegram nag. Next: a watched week with the trigger word, then the Telegram group id, then
new clients.

Behaviour as stated by the user, 2026-10-20 (planning, not yet built):

- Nails and hair bookings: encourage Fresha first, "but we can do it for you
  here if you'd rather". If they'd rather, go back and forth on days, look
  up availability (Fresha `availableTimeSlots`), and once a slot is agreed
  create the appointment through the Fresha integration.
- Easy queries the bot answers itself: "can I add nail art to my
  appointment", prices, what's included, where, parking.
- Complex queries, and anything the bot has no answer for, escalate to the
  right person: Jess (nails, general), Carmen (tattoos), Lori-Dee (hair).
- Complaints: never handled, always escalated.
- Rescheduling: ask them to do it through Fresha if they can; otherwise the
  bot does it.
- The client's name comes from the chat: Messenger's User Profile API
  returns first and last name with the Page token (checked 2026-10-20 with
  the owner's own PSID). Instagram needs `instagram_manage_messages`.

Decided 2026-10-20: the bot uses the owner's own Fresha login (see
decisions). Decided 2026-10-21: the first version books nails only (see
decisions), widened to hair the same afternoon; tattoos stay link-out and escalation. Open before
build: the payment policy to send
(Fresha's default is card confirmation with a cancellation fee equal to the
price); whether the bot may ask for email and phone in chat, as the team
does, to create or match the Fresha client; what "add nail art" means
(advice, or editing the booking, which needs an update mutation not yet
captured); the reschedule rule inside the cancellation-fee window.

### 5. Fresha watch Lambda: `tlg-prod-fresha-watch` (built 2026-10-19 evening; stack `terraform/fresha_watch`)

The user's ask: a Lambda that checks Fresha's public pages and sends a text
or WhatsApp when something structural changes. Every hour at half past,
07:30 to 22:30 London time, between menu sync runs. Loads the venue page and
the booking flow the same way the menu sync does, records the shape of the
parts the sync reads (keys and nesting, not values), and compares with the
previous run kept in Parameter Store. A failed page, a recovered page or a
changed shape sends an SMS through AWS End User Messaging (sender ID
TLGWATCH) to `alert_phone_numbers` and a fuller email to the ops topic. Steady state is quiet. `{"dry_run": true}` shows
the result without saving or sending.

Decisions taken while building:

- Text message first, WhatsApp later. WhatsApp from AWS (End User
  Messaging Social) needs a Meta Business verification, a WhatsApp Business
  account and a registered sender number; the text is one SNS call. The
  channel is one function (`send_sms`) so WhatsApp can replace it.
- SNS's own SMS path accepted texts from this account and silently
  dropped them, even after a sender ID and a verified number; End User
  Messaging with the sender ID delivered. So the Lambda texts through
  `pinpoint-sms-voice-v2` and SNS is only the email. The account is in the
  SMS sandbox: each number must be verified first. See `docs/setup.md`.
- Phone numbers come from the GitHub `prod` environment secret
  `ALERT_PHONE_NUMBERS` (JSON list, E.164), so they are not in the repo.
- Shapes merge list elements and treat every scalar as "value", so a new
  person, a new service or a null description is not a change. Only keys
  appearing, disappearing or changing kind (value, object, list) count.

### 6. Meta webhooks: a bot per channel, invoked on every message (BUILT 2026-10-19 evening, simple stage; stack `terraform/`)

The user's ask: event driven, and a Facebook bot and an Instagram bot
separately. Meta delivers each message to our HTTPS endpoint within
seconds. Two Meta apps (Tlg-app1 Messenger, Tlg-app2 Instagram), two
Lambdas from the same code (`tlg-prod-messenger-bot`,
`tlg-prod-instagram-bot`), one HTTP API with a route each, one conversation
table. The parked monitor moved to `terraform/parked/` so the bot stack
applies without it. Sequence, each step proven before the next:

1. **Simple.** `bot_mode = simple`: reply with a plain acknowledgement
   ("Hi, this is the TLG messenger test bot. I received ..."), store the
   thread, email the ops topic the message and the reply. No Claude, no
   persona (the framework and persona were built 2026-10-20 from the real
   Messenger history, see `docs/voice-analysis.md`; they are used from the
   shadow stage on). Deployed by the
   pipeline as the third stack, which also registers the webhooks with
   Meta. Guardrail (user, 2026-10-19): GitHub variable `MESSAGE_TEST_MODE`;
   while true only messages starting with "joshsmells" are answered, so only
   the user hears from the bots on the live Page; false answers everyone.
   Secrets are named `TLG_APP1_*` (Messenger) and `TLG_APP2_*`
   (Instagram); `TLG_PAGE_TOKEN` is needed before anything can be sent.
2. **Shadow.** `bot_mode = shadow`. Needs the Claude Platform on AWS
   workspace id and the Page token. Every message gets a drafted reply
   emailed to Jess; nothing goes to the client. Run for a week.
3. **Live.** `bot_mode = live`. Needs Meta app review of `pages_messaging`
   and `instagram_manage_messages` to message anyone who is not a tester.

Only the user can do, in the Meta developer console: the two apps (done),
"Require app secret" on each, link the salon's Instagram account to the
Page, generate a page token, add testers, submit for review. Steps in
`docs/setup.md`. Secrets go on the GitHub `prod` environment and into
Secrets Manager by Terraform, one secret per channel, as the PAT does.

### 7. Live availability and interactive chat (BUILT 2026-10-20; bot stack)

The user's ask: leave booking alone for now; let the bot look at the nails
and hair calendars and talk slots through, interactively, with the user on
the live Page behind the trigger word. Built:

- `src/bot/availability.py`: real free start times from Fresha's public
  booking flow, no login (how in `knowledge/fresha.md`). One service, up to
  three named people, up to four dates. Read only.
- `brain.ask` runs a tool loop: Claude may call `check_availability`, the
  handler serves it, the final answer is still the JSON reply. Three tool
  rounds at most; an API or tool failure is a safe escalation.
- The client's name from Meta's User Profile API, once per thread, stored
  on the conversation and given to the model in an uncached context block
  with today's date and the channel. Messenger works with the Page token;
  Instagram needs `instagram_manage_messages`.
- The reply pause now counts from when the message arrived, so Claude and
  Fresha time eats into the ten seconds instead of adding to it; the typing
  dots start before the Claude call.
- `escalate_to` on every hand-over (jess, carmen, lori-dee), in the email
  subject.
- Persona: Fresha first, "or I can sort it for you this end", back and
  forth on real times, then "I'll get the girls to pop that in" and a
  hand-over with the details. Easy add-ons answered; moves via the Fresha
  confirmation link first; complaints never handled.

To run it: `BOT_MODE=live`, `ANTHROPIC_AWS_WORKSPACE_ID`, `MESSAGE_TEST_MODE`
stays `true`. Meta's Business AI and the instant reply must be off in
Business Suite first. Booking itself stays job 4.

### 8. Hand-overs to the team's Telegram group (BUILT 2026-10-20; bot stack)

One Telegram bot, one group of Jess, Carmen and Lori-Dee. Every hand-over
posts `<Area>: <kind>: <client>: <FB|Insta>` plus the Business Suite link
and the detail; spam is email only. Token in Secrets Manager via the
`TELEGRAM_BOT_TOKEN` secret; chat id discovered by the Lambda and cached in
SSM (`TELEGRAM_CHAT_ID` variable overrides). Steps in `docs/setup.md` 4c.
Next, when wanted: an "I've got it" button and a reply that unlocks the
thread, both needing a Telegram webhook route on the API.

## Open questions for the user

1. Prod only, or a dev stack as well?
2. Pin Terraform 1.10+ for the S3 lockfile, or add a DynamoDB lock table for 1.7?
