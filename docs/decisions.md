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

## 2026-10-21: the bot's first bookings are nails only

The user's ruling: test the booking flow with nail services first. Hair
stays a link to Fresha and an escalation to Lori-Dee (colour needs a patch
test and a consultation; cuts come later once nails are proven), tattoos
stay with Carmen. Consequence for the build: the booking tool refuses any
service outside the two Fresha nail categories ("Senior Nail Services -
TLG" and "Nails by TLG", 25 services between them), and the bot says so in Jess's
voice and offers the Fresha link instead. Widening the list is a one-line
change once the first week of nail bookings has been watched.

## 2026-10-21: hair is booked too, with Lori-Dee or Sophie, in Lori-Dee's register

The user's ruling, the same afternoon, after the nails flow booked and
cancelled cleanly through Messenger: make it work for hair with Lori-Dee or
Sophie. Consequences:

- The booking tool accepts the two hair categories as Fresha spells them,
  "Hair by Lori-dee" (Lori-Dee only) and "Sophie cooper" (Sophie or
  Lori-Dee, a few extension services list the whole team). Who does what
  still comes from Fresha's catalog, so Sophie is only booked for services
  Fresha lists her on.
- Colour stays out of chat for now: Fresha flags the services that need a
  patch test and the tool refuses those, handing over to Lori-Dee rather
  than Jess. Colour quotes from pictures were already a hand-over.
- No Sophie persona. The user's words: "when booking in Sophie, it's Lori's
  persona". The hair register in `persona/jess.md` (Hiya, calmer, one x) is
  used whether the appointment is with Lori-Dee or Sophie, and the bot still
  never says who it is. This keeps the 2026-10-20 one-persona decision.
- The Telegram line and ops email carry the area the booking belongs to
  ("Hair: booked by the bot: ..."), worked out from the service's Fresha
  category; cancellations look the service up the same way.

Tattoos, beauty and aesthetics remain link-out and escalation.

## 2026-10-21: the bot cancels free cancellations itself; fees stay with the team

The user's ruling, after the first live booking: the bot should handle
cancellations too. It cancels one of the client's upcoming appointments
when Fresha's own enforcement check says there is nothing to charge, with
the cancellation notification on. When Fresha reports a fee the bot does
not cancel, does not discuss the fee, and hands over, because the humans
decide whether to waive it. Refined the same afternoon: inside the window
the bot warns of the fee and asks "are you sure?". A client who is unsure
or asks not to pay gets "bear with me a moment" and a locking hand-over to
Jess (kind "cancellation fee"); the bot does not continue on that thread.
A client who says cancel anyway is sent to the link in their Fresha
confirmation to cancel it themselves, with a warm sign-off: a cancellation
that costs money is theirs to make, not the bot's. Moving a booking outside
the window is the bot's to do (user, same afternoon): it checks the old one
is free to cancel, agrees the new slot, books it, and only then cancels the
old one, so a failed booking never leaves the client with nothing. A move
inside the window is handled like a cancellation with a fee.

## 2026-10-21: the booking read-back opens with "to confirm then"

The user's ruling after the first hair move through Messenger: the message
that reads an agreed slot back must open "Hi <name>, to confirm then, ..."
rather than "so that's ...", with "shall I pop you in? x" still at the end.
Why: people skim and miss a question at the end of a message; the opening
tells them a yes is wanted before they read the details. Applies to new
bookings and to moves. Written into the prompt's booking and moving rules
and `persona/jess.md`.

## 2026-10-21: a price the bot cannot give is one holding line, then a quiet hand-over

The user's ruling after sending a picture of a nail set with "how much
would a set of these cost with extra nail art": the bot replied that it
could not see the picture, gave guide prices for BIAB, acrylics and art per
nail, and said it would pass the picture to Jess. The user does not want
that. Any price enquiry the bot cannot answer straight from the salon
details, including anything priced from a picture, gets one short line,
"Hi lovely, give me a little time to have a think and I'll get back to you
x" (wording settled the same evening), and a hand-over of a new kind "quote"
to the right person; the thread
then goes quiet so the team sends the price without the bot talking over
them. No guide prices, no mention of not seeing the picture, no asking for
more photos: the team does that. Consequences: `quote` is a locking kind
like complaint; a picture that comes with text is flagged to the model as
"[1 picture(s) attached]" (the handler used to drop that fact, which is why
the bot guessed about the picture); a picture with no text gets the same
holding line and a quote hand-over; and the bot's fallback line when Claude
fails is now that same sentence in Jess's voice. The old register notes
that asked for daylight photos (hair) or placement and size (tattoos) are
gone: Lori-Dee and Carmen ask for those themselves.

## 2026-10-21: tattoos in chat are the free consultation only, everything else is a quote

The user's ruling: the only tattoo appointment the bot may book is Carmen's
free 15-minute "consultation" (Fresha category "Tattoos by Skin deep
canvas"). Tiny Tattoo and Tiny Tattoo Tuesdays are not booked in chat;
Carmen books the tattoo itself, usually at the consultation. "How much
would this cost" and "can you design me something similar to this" are
quotes: the holding line and a quote hand-over to Carmen on Telegram, the
thread quiet. Consequence: the booking tool has a per-category allow list
(`ONLY_THESE` in `src/bot/booking.py`), the tattoo category now carries the
area word "tattoos" for the Telegram line, and the persona and prompt say
so.

## 2026-10-21: Telegram is for hand-overs only, never a running commentary

The user's ruling after watching the day's bookings land in the group:
"I do not want successful conversations going to Telegram. It's an
escalation point where you cannot continue." So a booking or cancellation
the bot completed is emailed to the ops topic for the record and is not
posted; Fresha's diary and its own notifications tell the team. The group
gets exactly the hand-overs: complaint, booking the tool could not make,
cancellation or rebooking it could not do, cancellation fee, quote, can't
assist anymore. Spam and shadow-mode drafts stay email only. The
three-days-to-expiry session warning, when built, still belongs there: it
is a point where the bot is about to stop working.

## 2026-10-21: beauty, lashes and aesthetics are bookable in chat too

The user's ruling, the same evening: "I want beauty, lashes and
Bernadette's aesthetics bookable via you." So the booking tool now takes
every Fresha category: the two nail ones, the two hair ones, "Beauty -
TLG", "Lashes by Amber" and "Bernadettes ReFresh aethetics", plus the
tattoo consultation. The only thing on the menu it refuses is a tattoo
itself. Who does what still comes from Fresha. The bot books aesthetics
but never advises on them: suitability and anything medical stay a
hand-over, as before. Area words for the Telegram line and ops email:
beauty (beauty and lashes), aesthetics. New clients are the next item.

## 2026-10-21: some Fresha team members are never bookable through the bot

The user's ruling while tidying staff in Fresha: "SJP Accountants",
"Danny Cooke" and "Rebekah Cooke" are not bookable for any service, even
if Fresha lists them somewhere. They are Fresha team-member records that
are not people clients book. The list is hand-written in
`terraform/salon.auto.tfvars` as `not_bookable_staff`, rendered into the
bundle, and applied when the config loads: those names are dropped from the
team the bot knows and from every service's staff list, so the prompt never
mentions them and the booking tool answers "not on the team list" if a
client asks for one. The menu sync keeps writing whatever Fresha says, so
the generated file may still carry them; the filter is the bot's, not the
sync's. Matching is on the name, case-insensitive, either way round.

## 2026-10-21: hand-written "not for this service" overrides beat Fresha's staff lists

The user's ruling: Carmen does not do makeup, only Amber, and "don't book
people in with Carmen" for it, even though Fresha lists her on "Make up by
the lash goblin". Rather than wait for Fresha to be tidied, the salon file
`terraform/salon.auto.tfvars` carries `not_bookable_for`, a map of service
name to first names the bot must never offer or book for it. Applied when
the config loads, so the prompt lists the right people, and enforced in
the booking tool: the person must be on the service's staff list as the
bot knows it, not merely in Fresha's catalog (that check was missing; the
tool used to trust Fresha alone, which would have bypassed any override).
The sync still writes what Fresha says; the override is the bot's.

## 2026-10-21: tattoo questions go to Carmen's WhatsApp, in her words

The user's ruling: a tattoo message that does not say what it wants ("I
want to book a tattoo with Carmen") gets one question first, "how can we
help? Do you want to discuss it, or book a free consultation?" (refined
the same evening after the first test). A client who wants the
consultation is offered Carmen's free times straight away and booked in.
Anyone who wants to discuss it, or more than that, "how much is a half sleeve", a full sleeve, a picture,
a design, is answered once in Carmen's persona and first person: "Hey
lovely, to discuss this further you can talk to me directly on WhatsApp, I
can respond much quicker on there if that's ok? <number> x", then a quote
hand-over to Carmen and the thread goes quiet. Her number is the GitHub prod
variable `CARMEN_PHONE`, passed through Terraform into the bot's
environment as `CARMEN_WHATSAPP` (never in the repo); without it the holding line is used. This
is the one deliberate exception to the 2026-10-20 one-persona rule: the
message sends the client to Carmen's own phone, so it is hers.

## 2026-10-23: offers by text go through our own sender, with the client list mirrored from Fresha

The team asked for SMS offers to the client list. Fresha's blast campaigns
do it at £0.08 a text plus VAT; the End User Messaging sender the Fresha
watch already uses costs about 2.5p (this account's October bill: three UK
texts, $0.10). The user's ruling: build it. The client list is mirrored
from Fresha into DynamoDB `tlg-prod-clients` by a daily Lambda using the
owner's session, because Fresha's client export shows it already holds the
answer that matters: 440 of 593 clients accept SMS marketing, 152 do not.
Fresha stays the source of truth for who the client is and for that tick;
our row adds an opt-out with us, our own segments ("lists"), and the token
behind the stop link. The sync writes only Fresha's fields, so the two
sides can never overwrite each other.

The stop link is a page with a button, not a bare GET that opts out: phones
preview links and carriers scan them, and either would unsubscribe people
who never tapped. The token is eight random characters tied to the row; no
phone number travels in the link. An opt-out is marked `fresha_pending`
because the call that updates a client's marketing tick in Fresha has not
been recorded yet; once it is, the sync carries the answer back so the desk
sees the same thing. The link in the text is `tlg-beauty.co.uk/stop/<token>`
(user, 2026-10-23: "can the domain be better?"): the website on Krystal
redirects `/stop/*` to the API, which keeps the link to 30 characters with
no certificate or custom domain in AWS. Sending itself, leaving the SMS
sandbox and the /offer command in Telegram are the next steps of plan job 10.

## 2026-10-24: the clients table mirrors the whole Fresha profile, not just the marketing ticks

The user's ruling, while reviewing how the bot should treat hair colour:
"I want our DynamoDB to be a mirror of our client lists and everything we
hold about the clients. It's important we know this because of patch tests
and automation." Fresha keeps patch tests, allergies, notes, files, tags,
badges, a staff alert and the appointment history on each client, and the
dashboard reads them with six GraphQL queries and three REST calls when a
profile is opened (recorded 2026-10-24 from the profile drawer). The
client sync now fetches all of it: one composed GraphQL operation
(`clientRecord`, the same fields under one name) plus the statistics and
consultation-forms calls, four requests a client, into the same row.

Why a mirror rather than live reads: automations (offers, reminders, the
colour rule, anything the team asks for next) need to ask "who" across all
clients, which Fresha's APIs cannot do without a call per client; a daily
copy in DynamoDB can. Where freshness matters at the moment of a booking
(a patch test, a fee) the booking tool still asks Fresha live.

Consequences: the Lambda runs up to 15 minutes and refreshes the stalest
clients first, so a slow day leaves the rest for the next run and says so;
file links are not stored (they expire), only names; products, wallet,
loyalty and memberships are left out because the salon does not use them.

## 2026-10-24: hair is never booked in chat; Sophie's clients go to her WhatsApp

The user's ruling, reversing the 2026-10-21 hair decision: "No hair
bookings automatic at all. Any messages we answer for Sophie we do a very
similar thing to Carmen": one message in Jess's own voice, "Ok lovely, if
you want to book in with Sophie it's best to message her directly on
WhatsApp, here's her number", the number from a GitHub prod variable
(`SOPHIE_PHONE`, like `CARMEN_PHONE`), then a hand-over.

How it is built:

- The booking tool refuses both hair categories before touching Fresha and
  tells the model the two routes (`booking.NOT_IN_CHAT`). The area word
  "hair" still exists for Telegram lines and cancellations.
- The prompt has a Hair section: plain questions answered in Lori-Dee's
  shape; if the client has not said which stylist, one question ("is that
  with Lori-Dee or Sophie lovely?"); Sophie's clients get the WhatsApp line
  and a hand-over to lori-dee (kind booking, "Sent to Sophie's WhatsApp"
  in the reason, bot keeps answering); Lori-Dee's clients get her own
  booking link, and a hand-over to Lori-Dee with the details if they would
  rather be booked in. No hair availability checks. Colour stays a quote.
- Without `SOPHIE_PHONE` the bot says Sophie will message them and hands
  over, so nothing breaks before the variable is set.

Refined the same afternoon by the user: "any hair complaints get escalated
though to Jess and Telegram. Hair for Lori gets moved to Lori in the FB
messages for Lori to deal with completely. Amber / nails / beauty all get
dealt with by you." So:

- A hair thread that is not a plain listed-price question ends the bot's
  part: Sophie named, the WhatsApp line; otherwise "Hiya, that's one for
  Lori our hairdresser, she'll pick this up with you here x". Both hand over
  to lori-dee (kind booking, area hair) and the thread locks: `handler.locks`
  treats area "hair" like a locking kind, so Lori-Dee has the inbox thread
  to herself. No "which stylist?" question: anyone who does not name Sophie
  is Lori-Dee's.
- A hair complaint is a complaint: escalate_to jess, kind complaint, locked,
  posted to Telegram like every complaint.
- Nails, beauty, lashes and aesthetics stay the bot's: booked in chat, and
  their hand-overs go to Jess. Cancelling a hair appointment through the
  cancel tool is unchanged (Fresha's own free cancellation, which the
  client could do themselves).

## 2026-10-24: a thread with Lori-Dee or Carmen is still read; the bot answers what is its own

The user's ruling, after the hair hand-over was built: "you should however
monitor all the messages even after they have been allocated to Lori. For
example if it's a hair client and lives with Lori but then wants to ask
about nails then you take over for nails, beauty."

So a hand-over now records who has the thread and for what
(`Conversation.handed_to`, `handed_area`). With Lori-Dee or Carmen the bot
keeps reading every message (`Conversation.watching()`): the context block
tells the model whose thread it is, that their replies are not shown to
it, and that a short message is almost certainly for them. The model sends
nothing (an empty `reply`, the only time that is allowed) for anything in
their area or anything that could be a reply to them, and answers in Jess's
voice when the client clearly turns to nails, beauty, lashes, aesthetics or
the salon, booking as usual. The thread stays theirs throughout: a nails
answer does not unlock the hair, and a further hair message is left alone
rather than handed over a second time. With Jess (complaints, fees,
anything she took) the bot stays silent as before: she answers the whole
thread herself.

Why not unlock after the nails answer: Lori-Dee would then get a second
Telegram post and a second "that's one for Lori" the next time the client
mentioned hair. Why silent with Jess: her hand-overs are the ones where a
bot reply could cut across a complaint or a money decision.

## 2026-10-24: Telegram stays, and only Jess is in it

The user asked whether hand-overs could go to Jess's personal Facebook
profile instead of Telegram, because Lori-Dee does not want much
intervention. No: a Page can only reply to someone who has messaged it,
and only for 24 hours after their last message; it cannot start a
conversation and cannot reach a profile URL (same wall as the 2026-10-20
decision). Ruling: "leave it as Telegram then and it will be just Jess."
So the group keeps its one bot and one member, Jess; Lori-Dee and Carmen
leave it (or never look). Nothing changes in code: every hand-over still
posts the same line, and the `escalate_to` name on the line tells Jess
who it concerns. Lori-Dee's hair threads are already hers in the inbox
without a post needing to reach her.

## 2026-10-24: our own patch-test column, assumed from history until Fresha has the record

The first full client mirror found one patch test logged in Fresha across
604 clients, so the team has not been recording them there. The user's
ruling: "for clients in our list who have had services that require patch
tests, I want you to indicate that the patch test has been done. This
should be an additional patch test column. In future, any new clients that
have patch tests done will need the Fresha patch test column and my column
updating."

So the clients row carries our own fields, never written by Fresha's side
of the sync: `patch_tested`, `patch_test_basis`, `patch_test_date`,
`patch_test_service`, `patch_test_set_at`. The sync fills them in order of
trust: an active patch test on the Fresha record ("fresha record"), else
the most recent past appointment, not cancelled and not a no-show, for
any lash or brow service ("assumed from Brow Tint on 2026-09-01
(completed)") or any service Fresha flags as needing a patch test. The
user's words: "if someone has had some sort of lash or brow appointment
then I want my column updating as a one off, done now, and if a future
Lambda sync finds someone new and they have had a lash or brow service
and/or the patch test in Fresha has been ticked then I want mine updating
too." So: a lash or brow word in the service name counts (makeup and
removals do not), plus Fresha's own "patch test required" tick read from
the catalog each run. The one-off was run from the laptop against the
mirrored history on 2026-10-24; the sync applies the same rule daily. The
sync never clears the column, and an assumption never overwrites a record.

Going forward, both columns update from one action at the desk: log the
test on the client's profile in Fresha (Records, Patch tests). The next
sync copies it and the basis becomes "fresha record". A patch-test
appointment the bot books (job 12) also counts once it has happened,
because the patch-test services are ticked as requiring one.

## 2026-10-24: lash and brow bookings check the patch-test column, and book the test first when there is none

The user's ask: "when a customer books in for a lash or brow I want the
bot to check their patch status and then book the appointment or, a patch
test plus appointment." Built as plan job 12. The bot has a fourth tool,
`patch_test_status`, which reads the salon's own patch-test column on the
client list (a Fresha record, or assumed from a past lash or brow
appointment). Tested: book as normal. Not tested: one question, then a
10-minute "lash patch test" with Amber, Carmen or Jess at least 24 hours
before the treatment, both read back in one message and booked test
first. The booking tool enforces it in code: a lash or brow treatment (or
anything Fresha flags) is refused unless the column says tested or a
patch test is booked in the same conversation far enough ahead. Jess is
told on Telegram with both appointments (kind "patch test"); the bot keeps
talking. A client who says they were tested but has no record still gets
the test, said kindly, because the record is what covers the salon. The
sync marks them tested once the patch-test appointment has happened, so
the question is asked once.

## 2026-10-24: new clients are added in chat, phone first, with the desk's defaults

The user's ask: "onboard a new client if they message and they are not
already a customer", then the form fields: "we only need first name, last
name, phone number and email; when we create the new client we drop the
leading 0 from the phone number, it's +44 in the menu already." Built as
plan job 13.

- When a booking finds no Fresha client with the thread's name, the bot
  no longer hands over. It asks once for mobile and email, then
  `create_client` looks the number up first: a match under another name is
  the same person and no record is added. Only a number nobody has gets a
  new record, through the dashboard's own Add client call.
- The rest of the form keeps the desk's defaults, including the three
  marketing ticks on, so a client the bot adds is treated exactly like a
  walk-in added at the desk. Flip in `Fresha.create_client` if the user
  wants bot-added clients opted out until they say otherwise.
- The referral source is the salon's default ("Walk-In", the only one).
  Adding "Messenger" and "Instagram" sources in Fresha would let the desk
  see where bot clients came from; the code picks the default source, so
  that is a Fresha change plus one line.
- The matched or created Fresha client id is kept on the conversation and
  every later booking in that thread uses it, so a Messenger display name
  that differs from the Fresha name stops mattering once the number is
  known.

## 2026-10-24: the confirmation chaser is one text pointing at Fresha's email, not a link of our own

The user's ask, then the shape it settled into over an evening: a Lambda
that looks at appointments 48 hours away and chases the ones the client
has not confirmed. Looked at in Fresha: "unconfirmed" here means the card
confirmation Fresha asked for when the appointment was made has not been
given; Fresha already emailed a request with a Confirm button (its
WhatsApp copy fails, message balance); there is a "Send reminder" on the
appointment (recorded, `sendAppointmentProtectionReminder`) but no way to
read the client's confirm link back. Three designs were on the table: our
own confirm page (a new link, a status recording, a website redirect),
pressing Fresha's reminder plus a text, or a text alone. The user's
ruling: "we just send a simple reminder at 48 hours before if the
appointment is not confirmed and ask them to look through the email".

So the chaser sends one text in Jess's voice naming the Fresha email to
look for, and nothing else. Fresha's reminder press stays available
behind a switch. Texts wait for the SMS sandbox exit; until then the
chaser runs daily as a dry run and emails the list to the ops topic, so
the desk can ring the ones with no mobile either way.

## 2026-10-25: the Instagram bot gets its own Page token, issued by Tlg-app2

The user asked whether the bot's rules cover the Instagram DMs that land in
the Business Suite inbox alongside Messenger. The code does (one handler,
two Lambdas), but the logs for the last two weeks showed 25 client
messages on the Messenger bot and none on the Instagram one. Asked Meta
directly with the stored credentials: the single Page token both bots
share was issued by Tlg-app1 and carries only `pages_messaging`; Tlg-app2's
webhook is registered and active for Instagram messages, but the Page was
never subscribed to Tlg-app2 because that token cannot do it (wrong app,
no `pages_manage_metadata`). The Instagram profile is linked to the Page
and both apps sit in the business portfolio, so nothing else was missing.

A token belongs to the app that issued it: every Graph call carries an
`appsecret_proof` made with that app's secret, so one token cannot serve
both apps. Hence `meta_instagram_page_token` (`TLG_IG_PAGE_TOKEN`), written
into the Instagram channel's secret and used by its registration step,
falling back to the Messenger token when unset so the deploy is safe
before it exists. The token comes from a System User ("TLG bots") so it
never expires. The Instagram app's own "allow access to messages" switch
(Settings > Messages > Connected tools) is still the owner's to check on
the phone; Meta exposes it through no API.

Same evening, after the token was made: Tlg-app2's permission list offers
only `instagram_basic`, `instagram_manage_messages`, `pages_read_engagement`
and `pages_show_list` (its use case is Instagram only), and a System User
token is not the Page, so the bot and the registration script now swap it
for the Page's own token on first use (`meta.page_token_for`). Doing that
showed the Page id the repo had carried since the start, 61577501519464,
is not a Page at all; the Page is 625244944014434, fixed everywhere. For
the Page subscription Tlg-app2 gained the use case "Manage everything on
your Page", which carries `pages_manage_metadata`; the token was made
again with it, so the pipeline subscribes the Page itself. Subscribing
with the `messages` field still failed ("needs pages_messaging"), so the
Instagram channel subscribes the Page with `name`: the Page link is what
Meta needs, the messages field is on the app's own subscription. Done by
hand once the same afternoon and the Page now lists Tlg-app2.

## 2026-10-25: Instagram reached the bot; the bot moves to Sonnet for speed

The first Instagram DM to reach the bot (a tester, trigger word, Tlg-app2
still unpublished) was answered correctly, a hair request handed to
Lori-Dee and escalated to Jess, but the run took 20 s: 2 s token swap
and profile, 3 s Fresha session check (once per warm container), 14 s
the Opus call, 2 s escalation and send. Meta's webhook deadline is 20 s.
The user's call: move to Sonnet 5.5 (`claude_model`) and re-test; Opus
is one variable away if the voice suffers. Still to do for Instagram:
switch Tlg-app2 to Live (Publish) before real clients' DMs are delivered.

## 2026-10-25: a hair request with no stylist named gets asked which, never pushed to Lori-Dee

The first Instagram test ("I want a haircut", nobody named) was answered
"that's one for Lori our hairdresser" and handed to Lori-Dee. The user:
"if someone asks for a hairdresser, you need to ask which one first
because you can't just push them to Lori first, that's wrong." So the hair
rule has three doors now: Sophie named, her WhatsApp line; Lori-Dee named,
hers in the inbox; nobody named, one question in Lori-Dee's shape, "Hiya,
which of our hairdressers is it for, Sophie or Lori? x", no hand-over
until they answer. Assumed, not ruled: "don't mind" goes to Lori-Dee.

## 2026-10-25: staff who message the Page are never answered

The user had assigned the team's own threads to Jess in Business Suite
and asked whether the bot would leave them alone. Assignment in the inbox
tells the bot nothing: Meta delivers every message to the webhook, and
until now only test mode kept the bot off those threads. The user's
ruling: a GitHub variable `TLG_STAFF`, a comma-separated list of names,
"and if the message sender contains those strings, then don't bother
replying". So the bot fetches the sender's name (it already did, once per
thread), folds case and decoration, and if it contains an entry the
message is stored and nothing else happens: no reply, no Telegram, no
onboarding. A `staff` flag on the conversation row covers anyone the
list misses, set by hand. Both channels.

## 2026-10-25: "I'll pass you on to Lori", and no second "Hiya" when the client has just answered

Instagram test the same evening: the bot asked "which of our hairdressers
is it for, Sophie or Lori?", the user answered "Lori", and the bot came
back with the fixed line "Hiya, that's one for Lori our hairdresser,
she'll pick this up with you here x". The user: "that looks so wrong ...
it should be something like I'll pass you on to Lori". Two faults in one
line: a fresh greeting mid-conversation, and explaining who Lori is to
someone who just named her. So the Lori hand-over has two forms. Named in
the opening message: "Hiya, that's one for Lori our hairdresser, I'll pass
you on to her and she'll pick this up with you here x". Named in answer to
the bot's question: "Lovely, I'll pass you on to Lori and she'll pick this
up with you here x", no greeting. The same no-fresh-Hiya rule is spelled
out for Sophie's line when it follows the question.

## 2026-10-25: back to Opus; the tool cap answers from what it found; one lookup per question

Evening test on Sonnet: "hi i want to book nails next week", "BIAB please
with Sav?". The first lookup found Sav free on Thursday 29th (2pm, 6.30,
6.45). The model then checked Saturday, the whole of the following week,
Jess and Carmen, and Tuesday again: six lookups, past the five-round cap,
so the code threw the results away, sent the holding line "give me a
little time to have a think" and pinged the team. The user: "I don't like
this model change ... why is it asking for time to come back to me".

Three changes. The cap no longer ends in the holding line: one more call
with `tool_choice` none and a note that the looking is over, so the model
answers from the lookups it already ran; the escalation only if it still
asks for a tool. The availability rule now says one lookup answers the
question: check the days and person asked for, offer what is free, and if
nothing is, say so and ask what other day suits; never another week or
other people unasked. And the model is Opus again (`claude_model`):
Sonnet's call took 12.4 s against 14 s, not worth a voice and judgement
the user dislikes. The 20 s problem is the rest of the reply path (cold
start, the Fresha session check, a retry from Meta at 20 s that the
duplicate check absorbed) and is tomorrow's job.

## 2026-10-25: both Meta apps published; the bot goes to all clients when MESSAGE_TEST_MODE is false

The user: "I want to put in live and remove joshsmells. I want it talking
to all customers." Both apps were still In development, which is the real
gate: Meta only delivers messages from people with a role on the app, so
flipping the test-mode variable alone would have reached nobody new. Each
app's Publish page wanted only a privacy policy URL; the salon's website
already has one (https://tlg-beauty.co.uk/privacy-policy/), so it was set
on both apps and both were published the same evening. No App Review: the
apps serve only the business's own Page and Instagram account, which
Standard Access covers. Test mode stayed on through the publish, so the
order is Meta first, then the GitHub variable `MESSAGE_TEST_MODE=false`
and a pipeline run, which is the user's switch.

## 2026-10-25: the bot asks about add-ons while booking nails, and books them into the same appointment

The user, after pushing the evening's docs: "when booking appointments I
want you to say things like, do you need any add-ons like nail art?" A
question with no way to act on it would have left the client at a dead
end, so plan job 16 was built the same evening on the back of the capture
made an hour earlier (`knowledge/fresha-internal-api.md`, "Two services in
one appointment"): Fresha takes a second entry in `bookings`, starting
where the first ends. The rules: once service, person and day are settled,
ask once, in Jess's words, whether they want anything adding; the bot may
add "Extra time for simple nail art", "Luxury manicure", or a removal
before a new set, by exact name from the same category, with the same
person; simple art is 50p a nail and priced on the day (the team's own
quotes, `knowledge/from-messages.md`), so the bot gives no total; extreme
art, gems, chrome, a picture or a design request stays a quote to Jess.
The read-back and the team note name the add-ons. The clash check covers
the whole slot; the availability lookup still checks the main service
alone, which is noted on the job.

