# Plan

Running list of agreed jobs and the decisions behind them. Planning is still
open: nothing below is built until the user says so, except where marked.
Started 2026-10-19. Design reasoning lives in `docs/decisions.md`; Fresha
facts in `knowledge/`.

## Where things stand (2026-10-25, evening)

- **Both bots are live on both channels and both Meta apps are published.**
  Messenger and Instagram DMs reach `tlg-prod-messenger-bot` and
  `tlg-prod-instagram-bot`; `BOT_MODE=live`, model Opus 5.5. The only thing
  between the bot and real clients is the GitHub variable
  `MESSAGE_TEST_MODE` (still `true`: trigger word only). Flipping it to
  `false` and running the Deploy workflow is the user's switch (decision
  2026-10-25, "I want it talking to all customers").
- **Working rhythm:** nothing is committed until the user says "commit";
  the user pushes and runs the pipeline; after a deploy, verify by reading
  the Lambda configuration and CloudWatch logs (`gh` is not logged in).
- **In place:** staff quiet list (`TLG_STAFF`), Sophie's and Carmen's
  WhatsApp numbers, hair three-door rule, Telegram hand-overs with the chat
  id cached, the tool cap answering from what it found, Meta Business
  Agent off on the Page.
- **Instagram is not open to clients yet (found 2026-10-26).** Test mode is
  off and Messenger answers the public, but Meta only delivers Instagram DMs
  from app-role accounts until `instagram_manage_messages` has Advanced
  Access: Business Verification, then App Review on Tlg-app2
  (`docs/setup.md` step 6). A client's DM at 18:21 on 26 Oct was never sent
  to the webhook; the team answers Instagram by hand until approval.
  Checked 2026-10-27: Business Verification is **Verified** (TLG Beauty
  Limited, 26 Oct); the App Review submission on Tlg-app2 is still empty
  ("Not submitted") and every Instagram permission is "Ready for testing".
  Adding a permission to App Review now demands irreversible "Tech
  Provider" status; Meta's own guide says an app for a business you own
  needs no App Review on the Instagram Login route. Decision open: Tech
  Provider + App Review, or move Tlg-app2 to Instagram Login (see
  `docs/meta-app-review.md`, "Found 2026-10-27").
- **Next, in order:** 0) job 19, book first then confirm, plus jobs and
  competitions handed to Jess (built 2026-10-28, awaiting a push); 1) `MESSAGE_TEST_MODE` is off since 2026-10-26 16:04; 2) job 15,
  reply time under Meta's 20 s on a cold start; 3) narrow the wide staff
  entries ("Looking Glass", "Savvy" silence any client whose name
  contains them); 4) job 9 hand-back; 5) the rest of the backlog below
  (SMS sandbox, chaser texts, job 11 rulings, Fresha test client
  "TLG Bot Test" id 305395953 still to delete).

## Second strand: CPD course accreditation (started 2026-10-26)
- **Acrylic course rebuilt as v1.1 (2026-10-27):** `cpd-tlg/acrylic-course/`, manual v1.1 and A02–A06 pack from the v1 file that is with the assessor; nothing to upload until #20893 comes back, then Jess's checklist applies.
- **Gel Polish course rebuilt (2026-10-26):** `cpd-tlg/gel-polish-course/`, manual v2.0 and G02–G06 pack to the Builder Gel standard; waiting on Jess's checklist items (CV, forms, photographs, application text) before resubmitting #21252. Figures 14 to 22 redrawn realistically on 2026-10-27 after Jess's feedback, and the Builder Gel and Acrylic figures redrawn the same way the same day, so all three manuals share one drawing style.


Separate from the bot. Jess's nail courses are being accredited by The CPD
Group and keep being returned; everything they have published or sent us is
in `cpddocs/`, our course files are in `cpd-tlg/`, and the summary for the
knowledge server is `knowledge/cpd-accreditation.md`. State on 2026-10-26:
the Builder Gel course manual was critiqued and rebuilt as v1.1 with a full
assessment pack; Jess has a checklist of what to check and what only she
can supply (CV, photographs, the application form text). Gel Polish #21252
got it on 2026-10-26 and Acrylic #20893 on 2026-10-27 (while in review). Picking this
strand up: read `knowledge/cpd-accreditation.md`, then
`cpd-tlg/builder-gel-course/working-files/B01-fix-log-2026-10-26.md`.

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
conversation, an ops email per booking (no Telegram post: the group is for
hand-overs only, decision 2026-10-21 evening), dry run outside
live mode. Widened to hair the same afternoon (decision 2026-10-21), then **reversed
2026-10-24: hair is never booked in chat.** Sophie's clients are sent to her
WhatsApp (`SOPHIE_PHONE`), Lori-Dee's get her link or a hand-over (decision
2026-10-24). Tattoos: the free
consultation with Carmen only; prices and designs are quote hand-overs.
Beauty, lashes and aesthetics bookable too (evening ruling), so the only
menu item not booked in chat is a tattoo itself. The persona and prompt now read the slot back, ask "shall I pop
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
3. **Live.** `bot_mode = live` (since 2026-10-24 behind the trigger word).
   No app review was needed: the apps serve only the business's own Page
   and Instagram account, so Standard Access covers it. What Meta wanted
   before Publish was a privacy policy URL; both apps were published
   2026-10-25 (`docs/setup.md` step 6). Instagram got its own Page token
   the same day (System User on Tlg-app2, swapped for the Page's own
   token in code) and its first DM was answered at 17:05.

Only the user can do, in the Meta developer console: the two apps (done),
"Require app secret" on each, link the salon's Instagram account to the
Page, generate a page token, add testers, publish (all done by
2026-10-25). Steps in `docs/setup.md`. Secrets go on the GitHub `prod` environment and into
Secrets Manager by Terraform, one secret per channel, as the PAT does.

### 7. Live availability and interactive chat (BUILT 2026-10-20; bot stack)

The user's ask: leave booking alone for now; let the bot look at the nails
and hair calendars and talk slots through, interactively, with the user on
the live Page behind the trigger word. Built:

- `src/bot/availability.py`: real free start times from Fresha's public
  booking flow, no login (how in `knowledge/fresha.md`). One service, up to
  three named people, up to four dates. Read only.
- `brain.ask` runs a tool loop: Claude may call `check_availability`, the
  handler serves it, the final answer is still the JSON reply. Five tool
  rounds at most; at the cap one more call with the tools closed so the
  model answers from what it found (2026-10-25), and the holding line only
  if it still cannot. The prompt says one lookup answers the question. An
  API or tool failure is a safe escalation.
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

One Telegram bot, one group of Jess, Carmen and Lori-Dee (group
"TLG-Messages", id cached 2026-10-21). Every hand-over posts
`<Area>: <kind>: <client>: <FB|Insta>` plus the Business Suite link and the
detail; spam is email only, and so are bookings and cancellations the bot
completed: the group is where the bot stops, not a running commentary. Token in Secrets Manager via the
`TELEGRAM_BOT_TOKEN` secret; chat id discovered by the Lambda and cached in
SSM (`TELEGRAM_CHAT_ID` variable overrides). Steps in `docs/setup.md` 4c.
Next: job 9 gives the thread back.

### 9. Hand-back: Meta's handover protocol plus Telegram buttons (AGREED 2026-10-22, not built)

The problem (user, 2026-10-22): the bot hands a thread to Jess, Carmen or
Lori-Dee and goes quiet, but nothing ever gives it back except the owner
running a DynamoDB command. Two mechanisms, built together, either one
hands back:

**A. Meta's handover protocol.** The bot app is the Page's *primary
receiver*; Meta's own inbox (Business Suite) is the secondary. On a locking
hand-over (complaint, cancellation fee, quote, can't assist) the bot locks
the thread as now and also calls `POST /{page-id}/pass_thread_control` with
the inbox as `target_app_id` (Page Inbox `263902037430900`, Instagram Inbox
`1217981644879628`) and `metadata` naming the kind and who it is for. From
then on the client's messages reach the bot on Meta's `standby` channel,
which it ignores, so Meta itself keeps the bot quiet. The team reply from
the inbox as they do today. Moving the conversation to **Done** in the inbox
passes control back: Meta sends `pass_thread_control` on the
`messaging_handovers` webhook with our app as `new_owner_app_id`, and the
bot clears the lock. Verified from Meta's reference for the endpoint, app
ids and webhook payload; "Done gives it back" is documented by two vendors
built on the protocol, not on a Meta page I could reach, so the first live
test confirms it. Needs: `messaging_handovers` (and `standby`) added to the
fields `scripts/meta_setup.py` subscribes; a one-off operator step per
channel (Page settings: Advanced Messaging, set the app as primary
receiver; for Instagram, Page Setup > Instagram Conversation Routing, set
the app as default) in `docs/setup.md`; the inbound parser to read
`messaging_handovers` events; `meta.pass_thread_control` and
`meta.take_thread_control`.

**B. Buttons on the Telegram post.** Each locking hand-over's post carries
two inline buttons: "I've got it" and "Done, bot can take over".
"I've got it" edits the post to "<first name> has it, 18:42" (the tapper's
Telegram name) and stores `handled_by` on the conversation item; the Done
button stays. "Done" clears the lock, calls `take_thread_control` so the
inbox no longer owns the thread, and edits the post to "Back with the bot".
The Done-in-inbox route (A) edits the post the same way, so the group sees
the hand-back whichever way it happened. Button taps are callback queries,
delivered to the bot that owns the message regardless of privacy mode, so
privacy mode stays on. Needs: a `POST /telegram` route on the existing API
Gateway to the messenger bot Lambda (one route serves both channels; the
64-byte `callback_data` carries action, channel and sender id); the request
checked against `X-Telegram-Bot-Api-Secret-Token`, a Terraform-generated
secret stored next to the bot token; `setWebhook` asserted by the deploy
pipeline like the Meta registration, with `allowed_updates` of
`callback_query`, `message` and `my_chat_member`; `answerCallbackQuery` on
every tap so the spinner stops. Once a webhook is set `getUpdates` stops
working, so chat-id discovery moves from polling to the incoming update:
any update from a group caches the id in SSM, replacing
`discover_group_chat_id`. The cached id already covers the live group.

**Backstop.** A lock older than `HANDOVER_TTL_DAYS` (default 7) is treated as
cleared, and the bot takes control back on the next client message; Meta's
own control expires after 24 hours idle anyway. Logged when it happens.

**Rules kept.** Only live mode passes control or locks (shadow never has).
Non-locking hand-overs (booking, cancellation, spam) get no buttons and no
thread-control call. Email is unchanged. Telegram not configured: route A
alone. Assigning to a named person in Business Suite has no API, so the
Telegram post plus "I've got it" is the assignment; Page labels could add a
filter in the inbox later if wanted.

**Not in this job, worth doing after:** recording the team's own replies
(`message_echoes`) while the thread is with them, so the bot resumes
knowing what Lori or Carmen told the client.

### 10. SMS offers to the client list (AGREED 2026-10-23; steps 1 and 2 BUILT; steps 3 to 5 BACKLOG since 2026-10-24)

Parked by the user on 2026-10-24 ("a backlog item") so the messaging of
clients can be finished first (job 11). What is built keeps running: the
daily mirror and the stop link cost nothing to leave in place. The
AWS sandbox-exit case, the Fresha write-back recording and the send
Lambda wait.

The team asked for offers by text. Fresha's own blast campaigns cost £0.08
a text plus VAT; the sender the Fresha watch already uses costs about 2.5p,
so a blast to the 440 clients who accept SMS marketing is about £11 against
£42. Built in this order:

1. **Client mirror (built 2026-10-23).** `tlg-prod-client-sync`, in the bot
   stack, pages through Fresha's client search with the owner's session and
   fetches each client's full record, which is where the marketing ticks
   live (`accepts-sms-marketing-notifications`, email, WhatsApp). Mirrors
   name, mobile (E.164), email, blocked, labels, created/updated, referral
   source and the three ticks into DynamoDB `tlg-prod-clients`, keyed by
   Fresha's client id. Our own fields on the same row are never written by
   the sync: `sms_opt_out`, `lists` (our segments), `token` (the random code
   in the unsubscribe link), the send log. Clients that vanish from Fresha
   (merged, deleted) are marked `in_fresha=false`, not removed. Daily at
   05:30 London and on demand (`{"dry_run": true}` counts without writing).
   Who can be texted = in Fresha, has a mobile, Fresha tick yes, not opted
   out with us, not blocked.
   **Widened 2026-10-24 (user: "I want our DynamoDB to be a mirror of our
   client lists and everything we hold about the clients ... because of
   patch tests and automation"):** the sync now also fetches each client's
   profile page, in one composed GraphQL call (`clientRecord`) plus Fresha's
   statistics and consultation-forms calls: patch tests (title, status,
   performed, expiry, active), allergies, tags, segment badges, no-show and
   unpaid flags, staff alert, birthday, notes, files (names only), upcoming
   and the last 50 past appointments with services, person and add-ons,
   consultation forms, and Fresha's counters. Clients are refreshed stalest
   first within the Lambda's 15-minute budget; leftovers go first next run
   and the summary says how many (`remaining`). Not mirrored: product
   sales, wallet, loyalty, memberships, packages (all unused by the salon)
   and signed file links (they expire; the file names are kept).
2. **Unsubscribe (built 2026-10-23).** `GET /stop/<token>` on the existing
   webhook API shows a page with one "Stop texts" button; pressing it (a
   POST, so link previews and scanners cannot opt people out) flips
   `sms_opt_out`, and the page offers "Get offers again". The token is
   eight random characters tied to the row, no phone number in the link.
   The change is marked `fresha_pending` until the write-back below exists.
3. **Fresha write-back (needs one recording).** Nobody has yet toggled the
   SMS-marketing tick in a client profile with DevTools open, so the update
   call is not in `knowledge/fresha-internal-api.md`. Record it (same HAR
   method as the booking), then the sync pushes pending opt-outs to Fresha
   so the desk sees the same answer.
4. **Sending.** A send Lambda through the existing End User Messaging
   sender (needs the account out of the SMS sandbox: a support case), 160
   plain characters, booking link and stop link in every text, a log of
   who got what. The link in the text is `tlg-beauty.co.uk/stop/<token>`
   (user, 2026-10-23): one wildcard redirect on the website (Krystal)
   sends `/stop/*` to the API, so no second domain in AWS and the link
   is 30 characters instead of 60.
5. **/offer in Telegram**, after job 9's webhook: a few words in, a draft
   in Jess's voice out, count and cost, Send button.

### 11. Every service settled in chat or handed to Telegram (PROPOSED 2026-10-24, not agreed)

The user's ask: "I want to be sure every service we have in our catalogue
is dealt with by our chat bot in a way where it either solves the
conversation or escalates to Telegram." The audit is `docs/service-coverage.md`:
a matrix of the eight Fresha categories against what the bot answers, books,
quotes and hands over, and nine gaps. The code already guarantees that an
answered message ends in a reply or a hand-over; the gaps are about the
menu's edges and about proof. Proposed steps, in order:

1. **Rulings from the user** (no code): colour prices, quote or list price;
   add-ons, quote and "mention it on the day" or hand over; who may be booked
   for "Shampoo and blow dry long hair" and "Mini hatters pamper"; whether
   Bernadette, Amber and Sophie join the Telegram group and `escalate_to`;
   whether Tiny Tattoos become bookable; whether the free consultations
   (Bernadette, Lori-Dee, Sophie) are offered the way Carmen's is.
2. **Fixes in Fresha** (the user, in the dashboard): tick "patch test
   required" on every colour service; remove or rename the Beauty - TLG
   copies of "Classic lashes" and "Classic lash infill"; trim the staff on
   "Shampoo and blow dry long hair". The menu sync carries each change into
   the bot overnight.
3. **Code**: a colour keyword guard in `booking.py` that refuses and hands
   to Lori-Dee regardless of the Fresha flag; add-ons refused as standalone
   bookings; a never-book list ("Competition winner", "Two week Botox
   review") and the `not_bookable_for` additions in `salon.auto.tfvars`;
   prompt and persona changes for consultations and whatever step 1 decides.
4. **Evaluation run**: `scripts/eval_bot.py`, one scenario per service
   family and per hand-over rule (about forty: a price question, a booking
   ask, a picture, a complaint, an add-on, a colour, an aesthetics "what
   should I have", a tiny tattoo, each category), run against the real model
   with a scripted Fresha, asserting the outcome class and who it went to.
   Not part of `pytest` (it costs money and needs AWS); run by hand before a
   persona or prompt change, result recorded at the foot of
   `docs/service-coverage.md`.
5. **Switch**: `MESSAGE_TEST_MODE=false` on the GitHub `prod` environment,
   the user's call, after step 4 passes.

### 12. Patch tests before beauty and lash bookings (BUILT 2026-10-24; bot stack)

The user's ask: when a client asks for a service that needs a patch test,
check whether we have tested them before; if not, arrange a 10-minute
patch-test visit during working hours in Jess's, Carmen's or Amber's
diary, tell Jess on Telegram with the time, and book the real appointment
in the same conversation, leaving enough time between the two.

How it will work:

1. **Which services need one: Fresha's own tick.** The "patch test
   required" flag on a service already reaches the booking tool through
   the catalog (`Service.patch_test`); today it is off everywhere. Jess and
   Amber tick it on the tint and lash services (open question 8). The
   lead time between test and treatment is config
   (`salon.auto.tfvars`: `patch_test_lead_hours`, default 24, with a
   per-service override for the lash adhesive at 48 if Amber wants it).
2. **"Have we patch tested you before?" is answered from our column
   first** (`patch_tested` on the clients row, decision 2026-10-24: a
   Fresha record, or assumed from a past appointment for a flagged
   service). A new read-only tool, `patch_test_status`, looks the client
   up in the table (and Fresha live when the row is missing): tested means
   book straight away, nothing to ask. Not tested means the bot asks the
   client; "no" or "not sure" means a patch test is arranged. "Yes, you
   did it last month" with nothing on our side: the bot still books the
   test (the record is what covers the salon) and says so kindly, unless
   the user rules otherwise (decision needed).
3. **The patch test is a real Fresha appointment.** Fresha needs a service
   to book against, so the user adds one in Fresha: "Patch test", in
   Beauty - TLG, free, 10 minutes, Jess, Carmen and Amber, bookable online
   (the availability lookup reads the public booking flow, so a hidden
   service would have no free times). Then the existing
   `check_availability` and `book_appointment` tools do the rest: free
   10-minute slots in opening hours, the client gets Fresha's confirmation,
   and it sits in whichever diary was free. No new Fresha call to record.
4. **Two bookings, one read-back.** "To confirm then, patch test with Jess
   on Tuesday 28th at 11am, then classic lashes with Amber on Thursday 30th
   at 2pm, shall I pop you in? x". Two `book_appointment` calls on the yes.
   The tool refuses a patch-test service unless the client has an active
   test on record or a patch test booked in this conversation at least the
   lead time before the slot: the guard is in code, not just the prompt.
5. **Jess hears about it.** A new hand-over kind, `patch test`, posted to
   Telegram and emailed with both appointments, not locking: the client is
   mid-conversation and the bot carries on.
6. Hair is unaffected: hair is never booked in chat (decision 2026-10-24),
   so the Fresha tick on colour services only makes the refusal explicit.

Built 2026-10-24, the same afternoon the user added "lash patch test" in
Fresha (Beauty - TLG and Lashes by Amber; Amber, Carmen, Jess; free; 5
minutes): `src/bot/patch_tests.py` (which services need a test: the lash
or brow rule shared with the sync plus Fresha's tick; the client's row by
name; `patch_test_status` tool body; "booked earlier in this thread far
enough ahead"), the guard in `booking.book` (a lash or brow treatment, or a
flagged service, is refused unless the column says tested or a patch test
is booked in the conversation at least `PATCH_TEST_LEAD_HOURS` before,
default 24, Terraform `patch_test_lead_hours`), the Patch tests section of
the prompt (check first; tested, book; otherwise one question, then the
test and the treatment read back together and booked test first), the
`patch test` hand-over kind (Telegram and email to Jess, not locking), the
bot Lambdas' read access to the clients table. Decided by default: a client
who says they were tested but has no record still gets the test, kindly.
Not yet: a dry run against a test client on the live Page.

### 13. New clients: onboard in chat when Fresha does not know them (BUILT 2026-10-24; bot stack)

The user's ask: "onboard a new client if they message and they are not
already a customer." Today the booking tool matches the client by exact
name in Fresha and, when there is no match, hands over to Jess; the
create-client call was never recorded (job 4, "not yet").

How it will work:

1. **Find them properly first.** The Messenger name is a display name, not
   a record. Before creating anyone the bot asks for a mobile number (the
   team already does) and matches on that, using Fresha's own duplicate
   check (`customer-duplicates/existence-check`, seen in the profile
   capture) and the client search. A match by phone under another name is
   the same person: book them, no new record. Email is asked for as well,
   because Fresha's card-confirmation message goes to one or the other.
2. **Create them in Fresha** with a new tool, `create_client` (first name,
   last name, mobile, email): the dashboard's "Add client" mutation, to be
   recorded once from the profile page with the capture hook, then replayed
   with the real details. Marketing ticks are left off; Fresha's own
   booking message asks the client what they want. Referral source
   "Messenger" or "Instagram" so the desk can see where they came from.
3. **Then book as normal.** The new record is used straight away for the
   appointment (and the patch-test flow if it is lashes or brows: a new
   client has no test on record, so the test goes in first). The nightly
   sync mirrors the new client into the clients table with a stop-link
   token like everyone else.
4. **Wording.** In Jess's voice: "Lovely, you're new to us! Can I grab your
   mobile number and email so Fresha can send your confirmation through? x"
   Asked once, both in one message; a client who will not give a number is
   handed over to Jess (kind booking) with the slot, as now.
5. **Guard rails.** The bot never creates a second record for a number or
   email Fresha already has; it never edits an existing record; a failed
   create hands over as now. Numbers are stored as Fresha formats them;
   the bot never repeats a number back in chat beyond "the one ending 123".

Built 2026-10-24 after the user pasted the form ("we only need first name,
last name, phone number and email; drop the leading 0, it's +44 already")
and the Add client call was recorded (`knowledge/fresha-internal-api.md`,
"Adding a client"; test record "TLG Bot Test" for the user to delete).
`Fresha.create_client` and `find_client_by_phone`; the `create_client`
tool in `booking.py` (details checked, phone first, add only when nobody
has the number, the Fresha client id kept on the conversation so the
booking uses it by id from then on); the New clients section of the
prompt; nothing written outside live mode. The desk's own defaults are
kept for the rest of the form, so a client the bot adds is opted in to
marketing like a walk-in. Not yet: a dry run on the live Page.

### 14. Confirmation chaser: unconfirmed appointments 48 hours out get a text (BUILT 2026-10-24, texts off until the SMS sandbox is left; bot stack)

The user's ask: "we have an issue with customers not confirming their
appointments. I want another Lambda that looks at all appointments when
they are 48 hours away and if the customer hasn't confirmed we need to
send them an email and a text message." Size of it on 2026-10-24, from
the mirror: 73 upcoming appointments unconfirmed against 111 confirmed,
roughly two to ten a day; 8 of the 73 have no mobile on file, 11 no email.

How it will work:

1. **Who.** `tlg-prod-confirm-chaser`, daily at 06:00 London, half an hour
   after the client mirror: every upcoming appointment in the table that
   starts the day after tomorrow and is still UNCONFIRMED. Each candidate
   is re-read live (`viewAppointment`, recorded) so a client who confirmed
   overnight is skipped, and cancelled ones are skipped. One chase per
   appointment, remembered on the client row (`chased` by appointment id).
2. **What they get (user's final word the same evening: "we just send a
   simple reminder at 48 hours and ask them to look through their email").**
   One text through the existing sender, in Jess's voice: "Hi Sarah, still
   ok for gel polish with Jess on Fri 30 Oct at 2pm? Please tap Confirm in
   the email Fresha sent you, titled 'Please confirm your appointment'.
   Need to change it? Just message us x". The subject it names is config
   (`chaser_email_subject`): the confirmation-request email Fresha sent
   on the appointments looked at was titled "Please confirm your
   appointment on <day> at <time>"; set it to "New appointment" if that is
   the one the team sees clients get. Pressing Fresha's own "Send
   reminder" first is there behind a switch (`chaser_fresha_reminder`,
   off), recorded and tested, if a fresh email at the top of the inbox
   turns out to help.
3. **Confirming** is Fresha's: the client adds a card through Fresha's own
   link and the appointment turns Confirmed. The chaser re-reads the
   appointment next morning and reports who still has not.
4. **Jess sees the day's chases** in the ops email (count and names), not
   Telegram; a client who still has not confirmed by the day before is a
   line in the same email the next morning, for the desk to ring.

Looked at in Fresha the same evening (calendar, an appointment, its
activity log and the "View message" copy of a sent notification):

- Fresha already sends a "confirmation request" when an appointment is
  made, by email and by WhatsApp, and a "confirmation" once the client
  taps Confirm. For the appointment opened, both WhatsApp sends show
  "failed to send"; the dashboard also loads a
  `automatedMessages_messageAccountingZeroBalanceWarning` query, which
  points at Fresha's paid message balance being empty. So clients get the
  email only. Worth checking Marketing > Automated messages and the
  message balance before anything is built: a top-up may be the cheapest
  fix of all.
- There is no "resend" on an appointment: the quick actions are note,
  form, activity, repeat, group, rebook, reschedule, no-show, cancel.
- The dashboard's copy of the sent email has the Confirm and Manage links
  replaced with "#", so Fresha's real confirm link cannot be read back and
  reused in our text. Our message can only point at Fresha's email, or at
  our own confirm page (step 3).
- The notification history is readable per appointment
  (`GET customer-notifier-api.fresha.com/appointment-notifications-history/<appointment id>`:
  type confirmation_required / confirmation, transport email / whatsapp,
  status sent / error; `GET /messages/<uuid>` for the rendered copy), so
  the chaser can tell who was asked and how, and skip anyone Fresha
  reached by WhatsApp once that works.

Prerequisites, none of them code:

- **SMS sandbox exit** (the same AWS case as job 10 step 4; reminders are
  a transactional use and strengthen it). Until then texts only reach
  verified numbers, so the chaser can run email-only first.
- **No email of our own is needed now**: Fresha's reminder is the email.
  SES stays parked unless the salon wants a second email in Jess's voice.
- **No status recording needed**: the client confirms through Fresha.
- **Fresha's message balance.** Every WhatsApp confirmation request seen
  so far failed to send, and the dashboard shows a zero-balance warning.
  Topping up would make Fresha's own WhatsApp requests reach clients as
  well as the email; worth doing whatever we build.

Built 2026-10-24: `src/clients/chaser.py`, `tlg-prod-confirm-chaser`
daily at 06:00 London (`chaser_schedule`), half an hour after the mirror.
Reads the mirrored upcoming appointments for the day after tomorrow with
status UNCONFIRMED, skips rows not in Fresha or blocked, skips anyone
already chased for that appointment or with no mobile (listed for the
desk to ring), re-reads each one live (`viewAppointment`) and skips any
now confirmed or cancelled, then texts (End User Messaging, sender
TLGWATCH, transactional) and records `chased` on the row. The ops email
carries the morning's list. `chaser_send_texts` is false until the SMS
sandbox is left, so until then every run is a dry run and the email says
so; `{"dry_run": true}` and `{"date": "YYYY-MM-DD"}` work by hand. Cost
once on: about 2.5p a text, two to ten a day.

### 15. Reply time under Meta's 20 seconds on a cold start (PROPOSED 2026-10-25, not built)

Measured 2026-10-25 evening on the live Page: a cold Facebook reply took
22.1 s end to end (Meta re-sent the webhook at 20 s; the duplicate check
absorbed it, so the client got one reply), a warm one 15.5 s, a cold
Instagram one 17.6 s. The Claude call is about 12.4 s on Sonnet and 14 s
on Opus, so the model is not the lever (Sonnet was tried for a few hours
and reverted, decisions 2026-10-25). Where the rest goes: cold start plus
the Page token exchange about 3 s, the Fresha session check about 5 s
(`FRESHA SESSION ok` is logged before the Claude call), the reply pause
overlaps the call. Candidates, to measure before choosing: take the Fresha
session check off the reply path (cache it per container or check it
lazily when a tool needs it); keep a container warm (a scheduled ping or
provisioned concurrency, cost to weigh); acknowledge Meta's webhook first
and reply from a second invocation (the clean fix: the 20 s deadline then
only covers the acknowledgement); trim the prompt and the structured
reply. Not agreed yet; the user's call once the bot is talking to clients.

### 16. Add-ons on a nails booking: art, luxury manicure, a removal before a new set (BUILT 2026-10-25 evening; availability still checks the main service alone)

The user's question: "can you handle a client booking nails and then
extra nail art too?" Not yet: the booking tool takes one service, and
the availability check uses that one service's duration, so "BIAB and
some simple art" either becomes a quote hand-over (right when a picture
or a design is involved) or a BIAB booked alone in a slot too short.

Captured 2026-10-25 (`knowledge/fresha-internal-api.md`, "Two services in
one appointment"): Fresha's save is the same mutation with a second entry
in `bookings`, starting where the first ends, same person, its own
pricing level and duration. To build:

1. `Fresha.create` takes a list of services; one booking entry each,
   chained start times, catalog price each. `viewAppointment` already
   lists every booking.
2. The availability check takes the combined duration (the public flow
   accepts a basket; confirm it returns the same slots as the dashboard
   for two services, else check the main service and filter by the
   total).
3. `book_appointment` grows an optional `add_ons` list of exact service
   names from the same category; the read-back names them all ("BIAB
   with simple nail art, Jess, Thu 29th at 2pm"); the Telegram note too.
4. Rules: the bot may attach "Extra time for simple nail art", "Luxury
   manicure", and a removal before a new set (gel polish, Biab, acrylic
   soak off) when the client asks for them in words. Extreme art, a
   picture, or a design request stays a quote to Jess, as now. The
   per-nail art price is whatever the desk sets afterwards; the bot
   books it at catalog price and says the art is priced on the day.
5. Tests: two-service create body, chained times, read-back wording,
   quote rule unchanged.

Built the same evening after the user asked for the question itself ("when
booking appointments I want you to say things like, do you need any add-ons
like nail art?"): `book_appointment` takes `add_ons` (exact names, same
category, same person), `Fresha.create` chains them as further bookings,
the clash check covers the whole slot, the read-back and the Telegram note
name them, and the prompt asks once. Still open from step 2: the
availability lookup checks the main service alone, so a slot with no room
for the add-on is caught by the booking tool ("not free with the add-on
time") and the bot offers another time; a basket lookup would avoid that
round trip.

### 17. TLG Academy: student login, Jess's approval gate, course pages with placeholder videos (BUILT 2026-10-26, not yet deployed; design in `docs/academy.md`, operator steps in `docs/setup.md` section 7)

The user: "we want to create an online academy for our courses... a tlg
academy page with a student logon... placeholder youtube videos... a
redirection page from our website hosted in krystal which forwards us to
the aws infrastructure". Decisions the same day: a subdomain
`academy.tlg-beauty.co.uk` rather than a redirect page; students
self-register but see no course until Jess approves them for it from her
own login; every variable and secret prefixed `TLG_ACADEMY_`, including
`TLG_ACADEMY_ACCREDITATION_PENDING` for the CPD wording; desktop, Android
and iPhone; demo for the owners, no payments, no certificates.

Third Terraform stack (`terraform/academy/`): S3 + CloudFront + ACM for
the site, Cognito hosted UI for login with `students` and `admins`
groups, HTTP API + Python Lambdas + one DynamoDB table for profiles,
enrolment requests and lesson progress, a private bucket for the manual.
CPD brand rules are baked into the templates (provider logo on home and
about only, linked to the register; a per-course badge slot that stays
empty until accredited; no certificates). Krystal only needs two CNAME
records in cPanel's Zone Editor and a nav link.

Built the same day: `terraform/academy/` (validated), `src/academy/` with
six tests, `academy/web/` (hash-routed app, PKCE login against the hosted
UI, admin approvals page, responsive CSS), the Builder Gel course as eight
lessons in `academy/content/`, and `.github/workflows/academy.yml`, a
separate workflow (user's decision) gated by `TLG_ACADEMY_ENABLED`. Left
for deploy day: the GitHub variables, the first run, the two Krystal
records, the second run with `TLG_ACADEMY_DOMAIN_READY=true`, the manual
PDF into the files bucket, Jess registering, and testing on an Android
phone and an iPhone (the layout was checked in Chrome only). No video
ids yet: every lesson shows "video coming soon" until one is set.

### 18. Instagram on the Instagram Login route, no App Review (BUILT 2026-10-27, LIVE 2026-10-28; bot stack)

Why: Tlg-app2 talks to Instagram through the Facebook Page ("Instagram API
with Facebook Login"), and on that route Meta delivers DMs from the public
only at Advanced Access, which now means becoming a "Tech Provider"
(irreversible) and an App Review with a screencast. Meta's own App Review
guide says an app "only for a business I own or manage" on the Instagram
Login route needs no App Review: Standard Access covers accounts the
business owns and has added to the app. Messenger never had this problem
because `pages_messaging` at Standard Access already reaches the public.
The user chose this route on 2026-10-27 (`docs/meta-app-review.md`).

What changes, in order:

1. **Console (user, with the clicks prepared):** Tlg-app2 > Instagram API >
   "API setup with Instagram login". Note the Instagram app ID and
   Instagram app secret (a second pair, not the Facebook ones). App roles >
   Instagram testers > add @lookingglassbeautysalons, then accept the invite
   in the Instagram app (Settings > Website permissions > Tester invites).
   "Generate token" for that account: an Instagram sign-in, so the user or
   Jess does it; the token is long-lived (60 days). Webhooks under the same
   tab: callback `.../webhook/instagram`, our verify token, field
   `messages`.
2. **Terraform (`terraform/`):** two new GitHub secrets `TLG_IG_APP_ID`
   and `TLG_IG_APP_SECRET` into the Instagram channel's secret in place of
   the Facebook app pair; a separate secret `tlg-prod/meta/instagram-token`
   that the user creates once with `aws secretsmanager create-secret`
   (Terraform only points at the name, so a deploy never touches the
   token); Lambda env `META_GRAPH_HOST=graph.instagram.com` for
   the Instagram channel; a weekly EventBridge schedule (same pattern as the
   chaser) that invokes the bot package's `refresh_instagram_token` handler.
3. **Code (`src/bot/meta.py`, `handler.py`):** the Graph host per channel;
   signature check with the Instagram app secret; no Page token exchange
   on this channel; `/me/messages` and the profile read on
   graph.instagram.com with the Instagram token; `appsecret_proof` only
   where that host accepts it. The webhook body (`object: instagram`,
   `entry[].messaging[]`) is the same shape, so `parse_events` and the
   duplicate check by message id stay. The refresh handler calls
   `GET /refresh_access_token?grant_type=ig_refresh_token`, writes the new
   token and its expiry back to the token secret, and posts to the team's
   Telegram group and the ops topic if the refresh fails or the token has
   under ten days left. Weekly gives eight chances before a token dies.
   Tests for the host switch, the signature source and the refresh maths.
4. **Pipeline (`scripts/meta_setup.py`, `deploy.yml`):** the Instagram
   step subscribes the account with
   `POST graph.instagram.com/me/subscribed_apps?subscribed_fields=messages`
   using the stored token, instead of subscribing the Page to the app.
   The old Page subscription on Tlg-app2 is removed so a tester's DM is not
   delivered twice.
5. **Proof:** a DM from someone with no role on the app or the business
   portfolio (not the user, who is a tester) gets the bot's reply in the
   thread, and the Instagram Lambda log shows the invocation. Then the
   notes in `docs/setup.md` step 6 and `docs/meta-app-review.md` are
   rewritten for the new route.

Not a git pipeline job: the token never goes through GitHub. The deploy
pipeline ships code; the refresh runs in AWS on its own schedule and the
secret it rewrites is the one Terraform ignores.

Built 2026-10-27: `src/bot/ig_token.py` (the renewer, six tests),
`meta.py` host switch and fallback secret, `handler.py` token loading,
`terraform/instagram_token.tf` plus the variables, secret wiring and
outputs, `scripts/meta_setup.py --graph-host/--remove`, and the pipeline
step. Everything is gated on `TLG_IG_APP_SECRET`: until that GitHub secret
exists a deploy changes nothing on the Instagram side. Left for the user:
the console steps in `docs/setup.md` section 1 step 6 (the Instagram app
pair into GitHub, the tester invite, the token), then the proof DM.

Live 2026-10-28: deployed 09:45, token renewed to 27 December, account
subscribed. The first deploy had removed the app-level webhook
subscription (my pipeline step, wrong: that subscription belongs to the
Meta app whatever the login route) and a test DM was lost; restored by
hand 10:20 and the step fixed. Proof at 10:16 and 10:31: DMs from a
sender with no role on the app reached `tlg-prod-instagram-bot`; the
bot stayed quiet because the sender was on the staff list, and the
`staff` flag on a conversation record is sticky, so taking a name out of
`TLG_STAFF` does not free an existing thread (cleared by hand on that
record). Worth a rule later: re-check the staff list on every message
rather than trusting the saved flag.

### 19. Book first, confirm after; jobs and competitions straight to Jess (BUILT 2026-10-28; bot stack)

Two changes to how the bot talks, both from the user on 2026-10-28.

**Book first, confirm after.** Today the bot reads the slot back as a
question ("to confirm then, gel polish with Jess Thursday 29th at 10am,
shall I pop you in? x"), waits for a yes, then books. The user finds that
one confirmation too many. New flow: once the client has named the
service, the person, the day and the time, or said yes to a specific slot
the bot offered, the bot books it and then tells them, as a statement:
"All booked for you lovely, to confirm, gel polish with Jess on Thursday
29th at 10am, you'll get a message from Fresha to pop your card on x".
The read-back is now after the fact. Rules that follow:

1. No booking on a vague agreement ("yeah any time Thursday"): the bot
   still offers concrete slots from `check_availability` and books only a
   specific one the client picked or named.
2. The add-on question (job 16) is still asked once before booking when
   it applies, since it changes the appointment length.
3. A correction straight after ("actually can we do 11?") means cancel and
   rebook, then the same statement again; no question in between.
4. Patch tests (job 12): both appointments are booked, then both read
   back in one statement.
5. When the tool cannot book, the wording is unchanged: "I'll get the
   girls to pop that in for you" and a booking hand-over. Never "booked"
   unless the tool said so (that rule stays).
6. This supersedes the 2026-10-21 decision that put "to confirm then" at
   the start as a question; the phrase stays, as a statement.

Where: `src/bot/prompt.py` booking steps 3 to 5 and the patch-test
paragraph; `persona/jess.md` and `persona/voice-guide.md` matching rules;
`docs/decisions.md` entry; the prompt tests that assert the old wording.

**Jobs and competitions to Jess.** Messages asking for a job, about a
competition or giveaway, offering a collaboration, or selling something
get one warm line and go to the team group: "Hi lovely, I'll get this over
to Jess for you x", then a hand-over to jess with a new `escalation_kind`
`enquiry` (the reason says which: job, competition, collaboration,
selling), `area` general, and the thread locked so the bot stays quiet
while Jess answers. Jobs and collaborations are already on the hand-over
list in `persona/jess.md`; competitions are added. The Telegram post
names the kind so the team can see at a glance what it is.

Where: `src/bot/prompt.py` (hand-over kinds, a short rule), `persona/jess.md`,
`src/bot/handler.py` `LOCKING_KINDS`, a test for the lock.

Built 2026-10-28, prompt and persona only (no Terraform): booking steps 3,
5 and 8, the move and patch-test paragraphs, a "Jobs, competitions and
people selling things" section and the `enquiry` kind in `prompt.py`;
`persona/jess.md` and `persona/voice-guide.md` to match; `enquiry` added
to `LOCKING_KINDS`; the wording tests updated. Proof after the deploy: a
test client agrees a slot and gets "All booked ... to confirm ..." with no
question first; a "do you have any jobs going?" DM gets the one line and a
Telegram post marked enquiry, and the bot stays quiet after.

## Open questions for the user

1. Prod only, or a dev stack as well?
2. Pin Terraform 1.10+ for the S3 lockfile, or add a DynamoDB lock table for 1.7?
