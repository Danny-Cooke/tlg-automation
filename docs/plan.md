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
calendar exports are required. Before design can finish, capture one
mutation's request body and the session cookie (steps in
`knowledge/fresha-internal-api.md`). Then: session storage and refresh,
booking queue (SQS) with idempotency key per conversation and slot, Jess
notified of every booking at first, shadow-mode week.

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
   while true only messages starting with "bootycall" are answered, so only
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

## Open questions for the user

1. Prod only, or a dev stack as well?
2. Pin Terraform 1.10+ for the S3 lockfile, or add a DynamoDB lock table for 1.7?
