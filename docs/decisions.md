# Decisions

Short records of choices that are not obvious from the code.

## 2026-10-16: Bot cannot book into Fresha

Fresha has no public API, webhooks or Zapier app. The bot hands the client a
targeted Fresha booking link (service and/or staff member pre-selected) or
escalates to Jess. Revisit if Fresha opens an API.

## 2026-10-17: Claude via Claude Platform on AWS, not Bedrock

Both run on AWS with IAM auth and AWS billing. Claude Platform on AWS is
Anthropic-operated with same-day API parity, bare model IDs, and supports the
server-side refusal fallbacks. Bedrock lags on features and needs
`anthropic.`-prefixed IDs. The user is an AWS engineer, so keeping auth and
billing inside AWS matters more than using the first-party endpoint. Switching
later is a one-line client change.

## 2026-10-17: Python on Lambda

Single-purpose webhook, bursty traffic, no servers to patch. Python has the
best-supported Anthropic SDK path for AWS (`anthropic[aws]`).

## 2026-10-17: Persona is a repo file, not a console setting

`persona/jess.md` is reviewed, versioned and tested like code. Jess can propose
changes by editing one Markdown file. Salon facts (services, prices, hours,
staff, links) are Terraform variables so they can change without touching the
persona text.

## 2026-10-17: Google Calendar mirror is config plus checklist, not code

Fresha's native sync is per staff member and only configurable in the Fresha UI.
Terraform owns the staff map and emits an onboarding checklist. No code mirror
until there is a real need for one.

## 2026-10-18: Fresha categories verbatim, per-person links, prices from a snapshot

The Fresha menu (read 2026-10-18 from Fresha's own booking payload, not the
scrolling page) has 167 services in eight categories, most of them run by
independent specialists under the salon's roof. Category names are kept
exactly as Fresha spells them ("Nails by TLG", "Senior Nail Services - TLG",
"Bernadettes ReFresh aethetics", ...) so a client can find the same heading
in the booking flow.

Fresha's booking page accepts an `employeeId` filter, which we verified for
all eight team members, so each person has a booking link that opens Fresha
filtered to them. The general "all offers" link stays for "just show me
everything". There is still no per-service deep link. Prices live in
`terraform/salon.auto.tfvars` as a snapshot and are marked with their date.
When prices change, that file changes.

Who does what is recorded per service (`staff` on each service), read from
each person's own Fresha booking page. A category name is just Fresha's
heading, not a statement of who does it: "Lashes by Amber" holds the make-up
item that both Amber and Carmen are bookable for, and "Senior Nail Services -
TLG" holds the children's pamper that all five nail people can take.

Fresha shows different opening hours (10:00 starts) from the website (9:30
starts). The bot uses Fresha's, since that is what clients can book. Jess to
confirm.

## 2026-10-19: Proposed scope change: the bot books into Fresha (not yet decided)

The user wants the bot to create Fresha appointments from DMs, not only hand
out links. Fresha still has no public API, but its partner dashboard is a
React app over a single internal GraphQL gateway, and a test on 2026-10-19
showed the whole create and cancel flow is a handful of named operations
(see `knowledge/fresha-internal-api.md`). Three ways to drive it were weighed:

1. Call the internal GraphQL directly from a Lambda with a saved session.
   Cheapest and the preferred route if the request format and auth can be
   replayed. Still to capture: the mutation request body and the auth cookie.
2. Headless Chromium (Playwright) on Fargate or a Lambda container image with
   stored login state. Fallback if the calls cannot be replayed.
3. An always-on desktop in EC2 with Chrome logged in. Last resort.

Facebook and Instagram stay on the Meta Graph API and webhooks; no browser
session is needed for the messaging side. If this goes ahead the 2026-10-16
decision is superseded, the bot gets a booking queue (SQS) and an idempotency
key per conversation and slot, Jess gets a notification for every booking at
first, and the shadow-mode week in `docs/architecture.md` still applies.
Fresha's terms, session expiry and UI changes make this a fragile dependency,
so escalation to Jess remains the fallback for every booking failure.

## 2026-10-19: Deploy pipeline, state and secrets

- Terraform state in S3 bucket `tlg-automation-terraform-state` (London,
  versioned, encrypted, created by hand), key `<repo>/<environment>/terraform.tfstate`.
  One bucket for every environment of every TLG repo, told apart by key.
- GitHub Actions deploys on merge to `main` under the `prod` environment,
  assuming an AWS role by OIDC. No long-lived AWS keys in GitHub.
- The GitHub PAT the automation needs lives as a GitHub environment secret
  (`gh_pat`). The pipeline passes it to Terraform, which stores it in SSM
  Parameter Store as a SecureString under `/tlg/prod/`. Lambdas read it at run
  time. Chosen over Secrets Manager for cost and because every other piece of
  run-time state already sits in Parameter Store. Consequence: the value is in
  Terraform state, which is why the state bucket is private and encrypted.
- Everything in eu-west-2. Resources are named `tlg-<env>-<component>` and
  tagged through provider default tags.
- Ops alerts (alarms, monitor, menu sync) go to a separate SNS topic from
  Jess's escalations.

## 2026-10-19: The menu is generated from Fresha, not hand-maintained

Fresha is the source of truth for staff, services, prices, durations and who
does what. A daily Lambda reads Fresha's public booking data and regenerates
`terraform/fresha-menu.auto.tfvars.json`; a difference becomes a pull request,
not a direct commit, so a Fresha slip is seen before the bot quotes it.
Hand-written facts live in `salon.auto.tfvars` and are never regenerated.
Consequence: nobody edits the menu in git; they fix it in Fresha and the PR
follows within two hours (or on demand).

## 2026-10-17: Escalation stops the bot on that thread

Once a thread is handed to Jess, the bot stays silent until she clears it. A bot
talking over a human in a complaint thread is worse than no bot.

## 2026-10-19: The menu sync is deployed on its own, first

The user's call: the first thing to go live is the Lambda that reads Fresha
and opens a PR when the menu changes. Nothing else ships until that is
proven. So the Terraform is split into one root per deployable job, each
with its own state key in the same bucket:

- `terraform/menu_sync`: the sync Lambda, its schedule and alarm, the PAT
  parameter and the ops SNS topic. The deploy workflow applies only this.
- `terraform/`: the bot and the monitor. Kept, validated, not applied by the
  pipeline yet. It reads the ops topic ARN from the menu sync stack's state
  rather than owning a second topic.

The Lambda bundle is built per package (`scripts/build_lambda.sh menu_sync`)
so the sync does not ship the bot or the persona.

The pipeline assumes the account's existing `github-oidc` role rather than
creating its own (the user's ruling: the OIDC route is already set up and
used by the other repos; the only manual step was creating the state
bucket). The role trusts `repo:Danny-Cooke/*` and has AdministratorAccess,
checked live 2026-10-19. The stack's own deploy role and OIDC provider were
removed before anything was applied.
