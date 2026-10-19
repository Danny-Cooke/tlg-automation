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
  Project=tlg). Key is `<repo>/<environment>/terraform.tfstate`, so prod uses
  `tlg-automation/prod/terraform.tfstate`. Locking via the S3 lockfile, which
  needs Terraform 1.10 or later in the pipeline and locally (local is 1.7.5).
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
`terraform init` against the S3 backend, `plan`, `apply`. Needs:

- The OIDC identity provider and a deploy role in AWS, trusted for this repo
  and the `prod` environment. Terraform can define them, but the first apply
  is run by hand from a laptop because the role does not exist yet.
- `terraform/backend.tf` pointing at the bucket and key above.
- The repo pushed to the remote (no commits yet as of 2026-10-19).

### 2. Menu sync Lambda: `tlg-prod-menu-sync` (built 2026-10-19, uncommitted)

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
uncommitted until the plan is agreed. Details in `docs/architecture.md`.

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
