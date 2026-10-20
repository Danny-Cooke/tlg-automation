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

## 2026-10-20: The voice is built from the real message history, not written from guesses

The first persona was written before anyone had read how the team actually
talks; the user stopped that ("you got ahead of yourself"). The replacement
was built from every Messenger thread on the Page (283 threads, 924 human
replies after removing Meta's instant replies, ad greetings and Business AI
answers). Method and numbers: `docs/voice-analysis.md`. The persona is now
three files in `persona/`, loaded in order: `jess.md` (identity, rules,
hand-over), `voice-guide.md` (how a reply is built, by situation),
`vocabulary.md` (the word bank with counts). `scripts/message_history.py`
re-pulls and re-measures the history, so the guide can be checked against
the humans again later. Client data stays in git-ignored `.local/`.

Two rules fell out of the reading:

- **The bot never sends bank details or asks for a deposit.** The humans
  pasted the salon's account number into chat for most of the year; that is
  not something an automated reply should ever do.
- **"lovely" and first names only.** Jess's "babe", "angel", "my love" are
  for people she knows. The bot has no history with anyone.

Also found: Meta's Business AI has been answering clients on the Page since
mid-October in a voice nothing like the salon's, alongside the instant
reply. Both must be switched off in Meta Business Suite before the bot
replies to the public, or three voices will answer every message.

## 2026-10-20: One persona, three registers, not three personas

The user asked whether the bot needs a Carmen persona for tattoos, a Jess
persona for nails and a Lori-Dee persona for hair, since the history shows
three distinct voices. Decided against, for now:

- The Page already works as one front door. Jess answers first and the
  specialists step in by announcing themselves ("Hiya its Lori the
  hairdresser"). Clients read that as a human hand-over.
- What makes Lori and Carmen sound different is what the bot cannot do:
  quote colour from daylight photos, price a tattoo from a picture and a
  size. Those are hand-overs whichever name the bot uses.
- A bot saying "it's Lori" when Lori did not type it is a trust problem,
  and threads mix treatments, which would need intent routing and an owner
  rule for a mixed thread.

Instead Jess stays the single voice and her register shifts with the
treatment: Lori-Dee's shape on hair (Hiya, plain, one x, consultation and
photos first), Carmen's on tattoos (low key, size and placement, free
consultation), her own on everything else, then a hand-over naming the
person. Written into `persona/jess.md` and `persona/voice-guide.md`.

Revisit if Lori-Dee or Carmen want the bot to answer their threads in their
own words (built from their own replies, their decision), or if the bot
gets to quote and book hair and tattoos itself.

## 2026-10-20: Hand-overs go to a Telegram group, not Facebook, WhatsApp or SMS

The user wants hand-overs to reach Jess, Carmen or Lori-Dee where they will
see them, as a group. Checked in order:

- A Facebook group: no. Meta removed app posting into groups in 2024, and
  neither the Messenger nor the WhatsApp APIs can send into a group chat.
- A WhatsApp group: possible since June 2026 through the Groups API, but
  only with a WhatsApp Business Platform number (a second number; the
  salon's runs the app) and an Official Business Account, which Meta grants
  selectively. Weeks of waiting on two approvals.
- WhatsApp Channels: one-way broadcast, no API.
- SMS to the named person: works today (the Fresha watch sender), about 4p
  a text, but one-to-one and no replies.
- Telegram: groups fully supported by the Bot API, free, no approvals,
  fifteen minutes to set up, and later a button to claim a hand-over and a
  reply that unlocks the thread. The cost is a second app on three phones.

Telegram it is. Message format is the user's: `<Area>: <kind>: <client's
name>: <FB|Insta>`, then the Business Suite link, then the detail. The
model fills `area` and `escalation_kind` (complaint; booking; cancellation
or rebooking; can't assist anymore; spam) alongside `escalate_to`. Email
stays as the record; spam is email only. The group's chat id is discovered
by the Lambda from the bot's feed and cached in SSM so no one has to find
it by hand. If the team will not live with Telegram, SMS to the named
person is the fallback, same message, same routing.

## 2026-10-20: Availability comes from the public booking flow, not the dashboard session

The bot needs to see what is free before it can talk slots through with a
client. The dashboard's `availableTimeSlots` needs a logged-in session whose
auth has not been captured (the blocker on booking). The public booking
flow needs nothing: it is what a client sees on fresha.com, server-driven,
persisted queries only, and it returns five months of dates and 15-minute
start times for one service and one person. So availability is read from
there (`src/bot/availability.py`), and booking stays on the dashboard path
for later. Costs: three or four requests per person per lookup, and a hash
that Fresha could retire (old ones have stayed valid so far; the Fresha
watch covers the first step and the tool reports failures to the model).

The model gets a tool rather than pre-fetched data, because which service,
person and dates to check only emerge from the conversation. Three rounds
at most, and the reply pause is measured from message arrival so the lookup
does not push the reply past Meta's clock.

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
not a direct commit, so the change is recorded and the tests run against it.
Hand-written facts live in `salon.auto.tfvars` and are never regenerated.
Consequence: nobody edits the menu in git; they fix it in Fresha and the PR
follows within the hour (or on demand).

Amended 2026-10-19 (evening): the PR is merged automatically. The user's
call: this is a hands-off deployment, and a PR waiting for a person is not.
The deploy workflow runs the tests on the `menu-sync` PR and merges it with
the PAT when they pass; the merge triggers the deploy. Only that branch is
auto-merged, so any other PR still waits for a review. The ops email remains
the human's notice that the menu changed.

## 2026-10-19: One Meta app and one bot per channel

The user's call: Tlg-app1 for Messenger and Tlg-app2 for Instagram, each
with its own Lambda, rather than one app and one Lambda for both. Meta
registers a callback per webhook object anyway, so the cost is one more
secret and one more function from the same code. The gain: Instagram's
account linking, message-access toggle and app review are independent of
Messenger's, so Facebook can go live while Instagram is still being set up,
and a failure on one channel never touches the other. They share the
conversation table and the escalation topic.

Simple mode comes first: a plain acknowledgement with no Claude and no
persona, behind the trigger-word guardrail (`MESSAGE_TEST_MODE`), so the
event path and the reply path are proven before the framework exists.

## 2026-10-19: Fresha watch texts by SMS now, WhatsApp later

The user wants a text or WhatsApp when Fresha's public pages change shape.
SMS is one API call and needs only a verified number (through AWS End User
Messaging with a sender ID: SNS's SMS path turned out to drop texts from this
account without an error, End User Messaging delivered). WhatsApp
through AWS End User Messaging Social needs Meta Business verification, a
WhatsApp Business account and a registered sender number, which is days of
setup for the same message. So: SMS now, behind one function, WhatsApp when
the salon's WhatsApp number is set up for it. The watch is its own stack
(`terraform/fresha_watch`) rather than part of the parked monitor, because
the monitor also checks Meta and the bot, neither of which is deployed.

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

## 2026-10-19: GitHub immutable subject claims broke the OIDC trust

The first pipeline runs failed at the assume-role step with "Not authorized
to perform sts:AssumeRoleWithWebIdentity" although the role's trust policy
allowed `repo:Danny-Cooke/*`. Cause: this repo has GitHub's immutable
subject claims on (`use_immutable_subject: true`, the default for newer
repos), so its token's subject is
`repo:Danny-Cooke@50141838/tlg-automation@1422584660:environment:prod`.
The `@<user id>` after the owner name does not match the old wildcard. Fix:
a second trust entry, `repo:Danny-Cooke@50141838/*`, pinned to the user id
so a renamed or re-registered account can never match. The older repos keep
presenting the plain form and are unaffected. Applied by hand to the shared
`github-oidc` role 2026-10-19; the role is not under Terraform anywhere.

## 2026-10-20: the bot books through the owner's own Fresha login

Fresha's partner login has no password: a code by email, a second code by
SMS on an unknown device, reCAPTCHA on each request, a 30-day session that
is not extended by use (recorded in `knowledge/fresha-internal-api.md`).
An unattended keeper would have to read email and SMS and get a headless
browser past reCAPTCHA every month; not built, on fragility and on
principle. Instead a person logs in once a month through a laptop script
that keeps the trusted-device cookie and stores the session cookie in
Secrets Manager; the bot Lambda uses that cookie over plain HTTP.

The user's ruling: that login is their own Fresha account, not a separate
staff account for the bot. Consequences: bookings the bot makes show as
made by the owner; the monthly code goes to the owner's email; the owner
runs the script. If the owner logs in on another new device, that is a
separate session and does not affect the bot's.
