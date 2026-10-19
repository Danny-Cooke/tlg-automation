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

### 2. Menu sync Lambda: `tlg-prod-menu-sync` (built 2026-10-19, uncommitted; stack `terraform/menu_sync`)

Every two hours 07:00 to 22:00 London time (EventBridge Scheduler) and on demand (invoke). Reads Fresha's public booking
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
- Public booking flow request format captured and replayed from plain HTTP;
  details in `knowledge/fresha.md`.
- Apply after merge is job 1.

### 3. Monitor Lambda: `tlg-prod-monitor`

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

## Open questions for the user

1. Prod only, or a dev stack as well?
2. Pin Terraform 1.10+ for the S3 lockfile, or add a DynamoDB lock table for 1.7?
