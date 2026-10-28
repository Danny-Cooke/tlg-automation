# Setup

## 0. First deploy: the menu sync stack

Nothing is bootstrapped by hand. The deploy workflow assumes the account's
existing `github-oidc` role (it trusts every Danny-Cooke repo) and applies
`terraform/menu_sync` on every push to `main`. The `prod` environment holds
`AWS_ROLE_ARN` (that role), `GH_PAT` (fine-grained PAT: contents + pull
requests on this repo) and optionally `OPS_ALERT_EMAILS` (JSON list).

After the first apply, confirm the SNS subscription email if one was set,
then run the sync by hand once:

```bash
aws lambda invoke --region eu-west-2 --function-name tlg-prod-menu-sync --cli-binary-format raw-in-base64-out --payload '{"dry_run": true}' out.json && cat out.json
```

The bots run without a browser. Messages come in over Meta's webhook and go
out over the Graph API. The browser is needed only for the one-time steps
below that Meta does not expose through any API.

There are two Meta apps and two bots, one per channel: Tlg-app1 for
Messenger (the Facebook Page) and Tlg-app2 for Instagram. Same code, separate
Lambda, secret, logs and alarm, so each goes live on its own.

## 1. Meta: things only the console can do (once)

At https://developers.facebook.com, logged in as an admin of the salon's
Facebook Page. Done 2026-10-19: both apps exist.

1. **Tlg-app1 (Messenger).** App of type Business with the Messenger
   product. Note the App ID and App Secret from Settings > Basic.
2. **Tlg-app2 (Instagram).** Same, with the Instagram product. The salon's
   Instagram must be a professional account linked to the Page (Business
   Settings > Instagram accounts), and in the Instagram app, Settings >
   Messages > Connected tools must allow message access.
3. **Settings > Advanced on each app:** turn on "Require app secret". Every
   Graph call the bots make carries an appsecret_proof, so a leaked page
   token is useless without the secret. Leave the server IP allowlist empty;
   Lambda has no fixed address. The client token is not used.
4. **Page access tokens, one per app.** A token belongs to the app that
   issued it (the `appsecret_proof` on every call is made with that app's
   secret), so each channel needs its own. Messenger > API setup >
   Generate token gives one quickly; a System User token never expires and
   is the better one. For Instagram (done 2026-10-25): Business Settings >
   Users > System users > Add ("TLG bots", Employee); Assign assets: the
   Page with Full access "Everything" (the Instagram profile shares it),
   the app Tlg-app2 with Develop app; Generate token for Tlg-app2, expiry
   Never, with `instagram_basic`, `instagram_manage_messages`,
   `pages_read_engagement`, `pages_show_list` and `pages_manage_metadata`.
   The last one is what lets the pipeline subscribe the Page to the app;
   the Instagram use case does not offer it, so Tlg-app2 also has the use
   case "Manage everything on your Page" (Dashboard > Add use cases),
   where `pages_manage_metadata` was added under Permissions and features
   (2026-10-25). A System User token is not the Page: Meta's "me" is the
   system user, so the bot and the registration script swap it for the
   Page's own token on first use (`meta.page_token_for`, GET
   `/{page_id}?fields=access_token`; same permissions, never expires).
   That needs the real Page id, 625244944014434. Needed before the bots
   can reply; until then they store, log and email what arrives.
5. **Testers.** Until app review, Meta delivers messages only from people
   with a role on the app. Add your own Facebook and Instagram accounts as
   testers (App roles > Roles) so you can message the Page and see the bots
   react.
6. **Instagram: the Instagram Login route, no App Review (plan job 18,
   2026-10-27).** Standard Access covers Messenger but, on the route that
   goes through the Facebook Page, not Instagram: on 2026-10-26 a client's
   Instagram DM never left Meta while the tester's did, and Business
   Verification (TLG Beauty Limited, verified 2026-10-26) changed nothing.
   App Review on that route now demands irreversible "Tech Provider"
   status. Meta's own guide says an app "only for a business I own or
   manage" on the **Instagram Login** route needs no App Review, so the
   Instagram bot now uses that route: graph.instagram.com with the salon
   account's own token, no Page in the path. Once, in the console:
   1. Tlg-app2 > Use cases > Instagram API > Customize > **API setup with
      Instagram login** (the console calls it legacy and pushes "Unified
      login"; that one is the Facebook route under another name, see
      `docs/decisions.md` 2026-10-27). Copy the *Instagram app ID*
      (1959298412099447, app name Tlg-app2-IG) and the *Instagram app
      secret* (Show, next to it; a second pair, not the ones from Settings
      > Basic) into the GitHub prod secrets `TLG_IG_APP_ID` and
      `TLG_IG_APP_SECRET`. Setting the pair is what switches the pipeline
      and the bot to this route.
   2. Same tab, "Generate access tokens" > Add account: add
      @lookingglassbeautysalons as an Instagram tester, then accept the
      invite from the salon's Instagram app (Settings > Website
      permissions > Apps and websites > Tester invites). The account must
      be a professional account.
   3. "Generate token" next to the account: an Instagram sign-in as the
      salon, so whoever holds that login does it. Store the token with the
      AWS CLI; Terraform does not manage this secret, it only points at
      the name, so create it before the first deploy with the pair set:
      `aws secretsmanager create-secret --name tlg-prod/meta/instagram-token --description "Salon Instagram token, renewed weekly by tlg-prod-instagram-token" --secret-string '{"access_token":"<token>"}'`.
      A later token (after the old one died) goes in with
      `aws secretsmanager put-secret-value --secret-id tlg-prod/meta/instagram-token --secret-string '{"access_token":"<token>"}'`.
      Then check it straight away rather than waiting for Monday:
      `aws lambda invoke --function-name tlg-prod-instagram-token --cli-binary-format raw-in-base64-out --payload '{"source":"deploy"}' out.json && cat out.json`
      should show the salon's username, an expiry about 60 days out and
      an empty `problems` list. (In Git Bash on Windows prefix both with
      `MSYS_NO_PATHCONV=1` and the usual `--profile default --region
      eu-west-2`.) Terraform never touches that secret;
      `tlg-prod-instagram-token` renews it every Monday and after every
      deploy, re-subscribes the account to `messages`, and emails ops and
      posts to the team group if a renewal fails or under ten days are
      left. A token that has died needs step 3 again. If the Meta console's
      "Generate token" popup says the page cannot be loaded, step 4 of
      that console tab ("Set up Instagram business login") needs a
      redirect URL first; the salon website is in there (2026-10-28).
      Removing the app under Instagram > Apps and websites puts the
      invite back to Pending on Meta's side; accept it again on the Tester
      invitations tab and the token can be generated again.
   4. Webhooks: the pipeline subscribes the app's `instagram` object on
      graph.instagram.com with the Instagram pair and removes the old
      Facebook Login subscription; if that step warns, set the callback
      (`terraform output webhook_urls`, instagram) and verify token under
      the same tab > Configure webhooks > `messages`. The callback and the
      Lambda are unchanged; the signature is checked against the Instagram
      app secret first and the Facebook one as a fallback.
   5. Proof: a DM from someone with no role on the app or the business
      portfolio (not the user, who is a tester) gets the bot's reply and
      shows in the `tlg-prod-instagram-bot` log. Sender ids on this route
      are new Instagram-scoped ids, so old Instagram threads in the
      conversation table start again.
   The original publish step: no App Review was needed to publish: Meta's Publish page asked for one thing, a privacy
   policy URL (App settings > Basic), set to the salon's
   https://tlg-beauty.co.uk/privacy-policy/ on both apps, and the Publish
   button then worked. Both apps were published 2026-10-25. Until an app is
   published, Meta delivers messages only from people with a role on it;
   once published it delivers everyone's, and `MESSAGE_TEST_MODE` is the
   only thing left between the bot and the clients. To take the bot off the
   air at the Meta end: the app > Publish > Unpublish.

## 2. GitHub prod environment

Secrets (set 2026-10-19): `TLG_APP1_ID`, `TLG_APP1_SECRET` (Messenger),
`TLG_APP2_ID`, `TLG_APP2_SECRET` (Instagram). Then `TLG_PAGE_TOKEN` so the
Messenger bot can reply (without it they store, log and email but cannot
send), and later `ANTHROPIC_AWS_WORKSPACE_ID` for shadow mode. Since plan
job 18 (2026-10-27) the Instagram bot runs on the Instagram Login route:
`TLG_IG_APP_ID` and `TLG_IG_APP_SECRET` (the Instagram app pair, section 1
step 6) switch it on, and the account's token is seeded into Secrets
Manager by hand, not into GitHub. `TLG_IG_PAGE_TOKEN` (the Page token
issued by Tlg-app2, used on the old route) is ignored once the Instagram
pair is set and can be deleted. The Page ID is in `salon.auto.tfvars`; it
is not secret.

Variable `TLG_STAFF` (set 2026-10-25): a comma-separated list of staff
names as they appear on Facebook and Instagram. A sender whose profile
name contains one of them (case and decoration folded, so "Sophie's
𝐻𝐴𝐼𝑅" matches "sophie's hair") is never answered, escalated or
onboarded; the message is stored and the log says "STAFF: ... staying
quiet". For a staff thread the list misses, flag it by hand:

```bash
aws dynamodb update-item --table-name tlg-prod-conversations   --key '{"sender_id": {"S": "<psid>"}}' --update-expression "SET staff = :t"   --expression-attribute-values '{":t": {"BOOL": true}}'
```

Variables: `MESSAGE_TEST_MODE` (`true`: only messages starting with the
trigger word are answered, so only the tester hears from the bots; `false`:
everyone is answered), `BOT_MODE` (`simple`, the default, then `shadow`,
then `live`), `ESCALATION_EMAILS` (JSON list, Jess, from shadow mode on) and
`CARMEN_PHONE` (her WhatsApp number as clients should dial it; tattoo questions
beyond a consultation are sent there in her words; empty means the bot uses
the holding line instead) and `SOPHIE_PHONE` (her WhatsApp number; clients
who want to book hair with Sophie are sent there in Jess's voice, because
hair is never booked in chat; empty means the bot says Sophie will message
them and hands over).

`PATCH_TEST_LEAD_HOURS` is a Terraform variable (`patch_test_lead_hours`,
default 24): how far before a lash or brow treatment the bot books the
patch test.

The bot stack applies once `TLG_APP1_SECRET` exists. The deploy then
registers the webhooks with Meta itself (section 3) and prints the URLs.

## 3. Meta: the webhooks (done by the pipeline)

After each apply the workflow runs `scripts/meta_setup.py` once per channel
with the app's id and secret: it points the app's webhook at that channel's
URL and, when that channel's token is set (`TLG_PAGE_TOKEN` for Messenger,
`TLG_IG_PAGE_TOKEN` for Instagram), subscribes the Page to the app. For
Instagram the Page is subscribed with the `name` field: Meta only needs
the Page tied to the app (the `messages` field is on the app's Instagram
subscription), and `messages` on the Page would need `pages_messaging`,
which Tlg-app2 cannot have (checked 2026-10-25). The Instagram channel is
registered once `TLG_APP2_SECRET` exists; the run log then shows the
linked Instagram username. Registration
is idempotent, so every deploy re-asserts it.

Without a page token, or with one that lacks `pages_manage_metadata` (the
Instagram one, 2026-10-25), Meta will not deliver Page messages until the
Page is subscribed to the app, which the console can do: the app >
Messenger > Instagram settings (or Messenger API settings) > Webhooks >
Add subscriptions next to the Page, tick messages. To run the script
by hand instead, see its docstring.

Test: from a tester account, DM the Page starting with the trigger word.
Within seconds the bot replies "Hi, this is the TLG messenger test bot. I
received ...", the ops topic emails you the message and the reply, and the
thread is in the `tlg-prod-conversations` table. A message without the
trigger word is stored and logged, never answered.

## 4. Shadow mode

Set the `BOT_MODE` variable to `shadow`, add `TLG_PAGE_TOKEN`,
`ANTHROPIC_AWS_WORKSPACE_ID` and `ESCALATION_EMAILS`, push. The bot drafts a
reply for every message and emails it to Jess instead of sending it. Nothing
reaches clients. Run this for a week, tune the files in `persona/` and the salon
variables, then set `BOT_MODE` to `live`. `MESSAGE_TEST_MODE` keeps gating
replies in every mode until it is set to `false`.

## 4b. Live chat with the owner, before anyone else hears it

Set the `BOT_MODE` variable to `live`, add the `ANTHROPIC_AWS_WORKSPACE_ID`
secret (Claude Platform on AWS workspace in this account, eu-west-2), keep
`MESSAGE_TEST_MODE` at `true`, push. Only messages starting with the trigger
word are answered, so only the owner hears from the bot. First switch off
Meta's Business AI and the instant reply in Meta Business Suite (Inbox >
Automations), or two voices answer every test message.

What to try, one message each, starting with the trigger word: a nails
price, "can you do these" with a picture, "what's Jess got Friday", a hair
colour question, a tattoo quote, parking, moving an appointment, a
complaint, a sales pitch. The last three hand over and lock the thread;
clear it with the command in the next section. Watch the Lambda log for
`TOOL check_availability` lines to see what the bot looked up.

## 4c. The team's Telegram group for hand-overs

Every hand-over posts one message to a Telegram group, in the team's format.
Only hand-overs: a booking or cancellation the bot completed is emailed to
the ops topic and never posted, the group is not a running commentary.

```
Nails: complaint: Danny Cooke: FB
https://business.facebook.com/latest/inbox/all?asset_id=<page id>
<the detail the team needs, when there is any, e.g. the slot a client agreed>
```

Spam hand-overs go to email only. Setup, once, on a phone:

1. In Telegram, message **BotFather**: `/newbot`, a display name, a username
   ending in `bot`. Copy the token into the GitHub `prod` environment as the
   secret `TELEGRAM_BOT_TOKEN`. Never paste it anywhere else; if it has been
   seen, `/revoke` and use the new one.
2. BotFather again: `/setprivacy`, pick the bot, **Disable**, so the bot can
   read the group (needed to find the group, and later for replies).
3. Create a group, add Jess, Carmen and Lori-Dee, add the bot, make the bot
   an admin. Send any message in it.
4. Push. Terraform stores the token in Secrets Manager and creates the SSM
   parameter `/tlg/prod/telegram/chat_id` as `unset`. On the first hand-over
   the Lambda reads the bot's update feed, finds the group, and caches its
   id in that parameter. Telegram keeps updates for about a day, so if the
   first hand-over is later than that, say something in the group first, or
   set the `TELEGRAM_CHAT_ID` variable by hand (a negative number).

Each team member only needs Telegram installed and notifications on for the
group. Email stays as the record of every hand-over.

## 4d. The Fresha session the bot books with

Fresha's partner login has no password: a code by email and, on a browser it
has not seen, a second code by text, each behind a reCAPTCHA. The session it
sets lasts 30 days from login and is not extended by use. So a person logs
in, weekly, and a script stores the session for the bot. The bot uses the
owner's own Fresha account (decision 2026-10-20).

Once, on the laptop:

```bash
python -m pip install -r requirements-ops.txt
```

The script creates or updates the SSM parameter `/tlg/prod/fresha/session`
itself (SecureString, default key), using the laptop's AWS credentials.
Terraform does not manage the parameter; it only gives the bot Lambdas
permission to read it, so the order of the first run and the first deploy
does not matter.

Every week (set a calendar reminder; from three days out the bot also
posts to the Telegram group once a day, and again if the login has run
out or Fresha rejects it; `FRESHA_SESSION_NAG_DAYS` moves the threshold):

```bash
python scripts/fresha_session.py
```

It opens Chrome on the Fresha login in its own browser profile under
`.local/fresha-profile`. Log in: email, then the code Fresha emails you. The
first time it also texts a code to the account's phone; tick "trust this
device" and that step does not come back for a year, because the profile
keeps the trusted-device cookie. The window closes by itself once the new
session cookie exists. The script then checks the cookie works from plain
HTTP, the way the Lambda uses it, writes it to the parameter and prints the
expiry date. It never prints the cookie. `--dry-run` logs in and verifies
without writing.

The bot reads the parameter at run time and caches it for five minutes, so
no deploy follows a refresh. On each cold start in shadow or live mode the
bot also runs the same harmless probe query from inside AWS and logs
`FRESHA SESSION ok (...)` or `FRESHA SESSION rejected`, which is how you
know the cookie works from Lambda's address and not just the laptop. Each login starts a fresh 30 days, so a missed
week costs nothing; a missed month means the bot stops booking and goes
back to the Fresha link and a hand-over until the next run.

## 4e. Booking from chat (nails only)

With the session parameter in place the bot has a `book_appointment` tool
(`src/bot/booking.py`). In `shadow` mode it runs every check and writes
nothing, answering "Would have booked ..." so the drafts read right. In
`live` mode it writes to Fresha. Scope, by decision 2026-10-21: the two nail
categories only; the client must already be on Fresha under the name the
bot has; anything else is a hand-over with the details, as before.

Cancelling works the same way through a `cancel_appointment` tool: the bot
confirms which appointment, asks Fresha whether cancelling now carries a fee,
cancels with Fresha's notification when it is free, and hands over to the
team when a fee applies, so nobody but the team ever decides about money.
`python scripts/fresha_book.py upcoming <client id> --fee` shows what the
tool sees for a client.

Every booking or cancellation the bot makes is emailed to the ops topic for
the record, and nothing else: the Telegram group is only for hand-overs,
the point where the bot cannot continue (user, 2026-10-21). Fresha itself
sends the client the confirmation with the card step, exactly as for a
dashboard booking (proved 2026-10-21), and the team sees it in the diary.

To try it by hand without Messenger, the same code is driven from the
laptop:

```bash
python scripts/fresha_book.py clients cooke
python scripts/fresha_book.py services --nails --staff 3440861
python scripts/fresha_book.py slots --level 25845686 --staff 3440861 --date 2026-10-29 --minutes 60
python scripts/fresha_book.py book --client <id> --level 25845686 --staff 3440861 --date 2026-10-29 --time 10:00 --minutes 60 --price 34
python scripts/fresha_book.py cancel <appointment id> --notify
```

First live run: `BOT_MODE=live`, `MESSAGE_TEST_MODE=true`, message the Page
with the trigger word and ask for nails with Jess on a day she works; say
yes when the bot reads the slot back. Check the Fresha calendar and the
confirmation email, then cancel from the dashboard or with the script.

## 5. Clearing a hand-over

When the bot hands over a complaint or something it cannot handle, it stays
quiet on that thread (booking and cancellation hand-overs do not lock it).
To hand it back:

```bash
aws dynamodb update-item \
  --table-name tlg-prod-conversations \
  --key '{"sender_id": {"S": "<PSID>"}}' \
  --update-expression "SET handed_to_jess = :f" \
  --expression-attribute-values '{":f": {"BOOL": false}}'
```

A small admin endpoint for Jess can replace this later.

## 6. The client list and the stop link (plan job 10)

The bot stack also deploys `tlg-prod-client-sync` and `tlg-prod-unsubscribe`.
Nothing to set up: the sync uses the same Fresha session as the bot (4d) and
runs daily at 05:30 London. To run it now, or to see what it would do:

```bash
aws lambda invoke --function-name tlg-prod-client-sync --payload '{"dry_run": true}'   --cli-binary-format raw-in-base64-out /dev/stdout
aws lambda invoke --function-name tlg-prod-client-sync --payload '{"limit": 5}'       --cli-binary-format raw-in-base64-out /dev/stdout   # the five stalest clients only, written
```

The team's one habit that keeps the mirror right: when a patch test is
done, log it on the client's profile in Fresha (Records, Patch tests).
The next sync copies it into the row and our `patch_tested` column.

The same stack deploys `tlg-prod-confirm-chaser` (plan job 14), daily at
06:00 London. It texts clients whose appointment the day after tomorrow
is still unconfirmed, pointing them at Fresha's confirmation email. Texts
are off until the SMS account is out of the sandbox: set the Terraform
variable `chaser_send_texts = true` then. To see who it would chase:

```bash
aws lambda invoke --function-name tlg-prod-confirm-chaser --payload '{"dry_run": true}'   --cli-binary-format raw-in-base64-out /dev/stdout
```

The reply is a summary: clients in Fresha, rows, how many have a mobile,
how many accept SMS marketing in Fresha, how many opted out with us, and
`textable`, the number a blast would reach. Rows are in the DynamoDB table
`tlg-prod-clients`; a client's stop link lands at the `unsubscribe_url`
output with their row's `token` in place of `{token}`.

**The short link on the website (done 2026-10-23).** Texts carry
`tlg-beauty.co.uk/stop/<token>`. The website is WordPress on Krystal's
Onyx managed platform (not the cPanel account on hera, which the domain
does not point at: a redirect added there does nothing). The rule lives
at the top of the site's `.htaccess`, above the Patchstack block, edited
through the Onyx dashboard: Sites, The looking Glass, File Manager, `html`,
Actions next to `.htaccess`, Edit:

```
# TLG stop link for offer texts: tlg-beauty.co.uk/stop/<token> goes to the salon's AWS page
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteRule ^stop/(.*)$ https://qzn1xllzdj.execute-api.eu-west-2.amazonaws.com/stop/$1 [R=301,L]
</IfModule>
```

The API address is the `unsubscribe_url` output without `/{token}`; it only
changes if the API is ever recreated. Check: `https://tlg-beauty.co.uk/stop/test`
redirects (301) to the API, and after the deploy lands on our "This link
isn't valid" page. Patchstack and WordPress rewrite their own blocks of the
file and leave lines above "# BEGIN Patchstack" alone.

Still to do before the first blast, in order:

1. **Record Fresha's consent update.** Open a client's profile in the Fresha
   dashboard with DevTools recording (same method as 4d's booking capture),
   untick "SMS marketing", save, tick it back, save, export the HAR with
   sensitive data. The request that saves the tick goes into
   `knowledge/fresha-internal-api.md`, and the sync can then push rows
   flagged `fresha_pending` back to Fresha.
2. **Leave the SMS sandbox.** AWS Support case under End User Messaging:
   production access and a monthly spend limit (£30 covers a blast to
   everyone). Until then only verified numbers can receive texts.
3. ~~The redirect on the website~~ done.

## Local checks

```bash
pip install -r src/requirements.txt -r requirements-dev.txt
pytest
cd terraform && terraform fmt -check && terraform validate
```

## Fresha watch text messages

The Fresha watch Lambda texts you through SNS when a Fresha page breaks,
recovers or changes shape. Done once on 2026-10-19 for the first number;
repeat steps 3 and 4 for each extra number.

1. **London needs an origination identity.** A new account has none, so SNS
   accepts a text and drops it, and even the sandbox cannot send a
   verification code ("No origination entities available to send"). A UK
   alphanumeric sender ID needs no registration and costs nothing. The AWS
   CLI on the laptop is too old for the call, so use boto3:

   ```
   python -c "import boto3; print(boto3.client('pinpoint-sms-voice-v2', region_name='eu-west-2').request_sender_id(SenderId='TLGWatch', IsoCountryCode='GB', MessageTypes=['TRANSACTIONAL']))"
   ```

2. **The Lambda sends through End User Messaging, not SNS.** With the sender
   ID in place SNS still accepted texts and dropped them without an error;
   `pinpoint-sms-voice-v2` SendTextMessage from TLGWATCH delivered. The
   sender ID name is `sms_sender_id` in the Fresha watch stack. (The SNS
   default sender was also set to TLGWATCH; harmless, not relied on.)

3. **Verify the number.** The account is in the SMS sandbox, which only
   delivers to verified numbers. The SNS sandbox call registers the number
   but cannot always send the code; End User Messaging can, from the sender
   ID. Register, send the code, then confirm it:

   ```
   aws sns create-sms-sandbox-phone-number --region eu-west-2 --phone-number +44... --language-code en-GB
   python -c "import boto3; c=boto3.client('pinpoint-sms-voice-v2', region_name='eu-west-2'); v=c.describe_verified_destination_numbers()['VerifiedDestinationNumbers'][0]; print(c.send_destination_number_verification_code(VerifiedDestinationNumberId=v['VerifiedDestinationNumberId'], VerificationChannel='TEXT', LanguageCode='EN_GB', OriginationIdentity='TLGWATCH'))"
   python -c "import boto3; c=boto3.client('pinpoint-sms-voice-v2', region_name='eu-west-2'); v=c.describe_verified_destination_numbers()['VerifiedDestinationNumbers'][0]; print(c.verify_destination_number(VerifiedDestinationNumberId=v['VerifiedDestinationNumberId'], VerificationCode='123456'))"
   ```

   `aws sns list-sms-sandbox-phone-numbers --region eu-west-2` should then
   show the number as Verified. Ten numbers fit in the sandbox; to text
   anyone, request production access under SNS, Text messaging (SMS).

4. **Tell the pipeline the numbers.** On the GitHub `prod` environment add a
   secret `ALERT_PHONE_NUMBERS` holding a JSON list in E.164 form, for
   example `["+447700900123"]`. Watch for a stray space in the name field.
   The deploy passes it to Terraform as `alert_phone_numbers`. With no secret
   the watch still emails the ops topic and sends no texts.

The SNS monthly SMS spend limit is the default one dollar; a UK text costs a
few pence, so that is dozens of alerts a month. Raise it under SNS, Text
messaging (SMS), Account spend limit if it ever trips.

Send yourself a test text through the real path (number, sandbox, IAM):

```
aws lambda invoke --region eu-west-2 --function-name tlg-prod-fresha-watch --cli-binary-format raw-in-base64-out --payload '{"test_sms": true}' out.json && cat out.json
```

Check the Fresha checks are wired up without waiting for Fresha to change:

```
aws lambda invoke --region eu-west-2 --function-name tlg-prod-fresha-watch --cli-binary-format raw-in-base64-out --payload '{"dry_run": true}' out.json && cat out.json
```

## Meta Business Agent (Meta's own inbox AI): keep it off

The Page has Meta's "Business Agent" set up (Business Suite > Inbox >
Meta Business Agent). Checked 2026-10-25: **AI is off**. The "Meta Business
Agent" thread in the inbox is Meta's agent talking to the business during
its own setup (Oct 13 to 17), not a client, and the "AI responding" label
dates from then. It must stay off: switched on it would answer clients
about prices and products from Meta's guesses, over the top of our bot.
If a thread ever shows "AI responding" again, check this page first.

## 7. TLG Academy (plan job 17, `docs/academy.md`)

Its own workflow, `.github/workflows/academy.yml`, its own stack,
`terraform/academy/`. Nothing here touches the bots.

1. **GitHub prod environment**, all prefixed `TLG_ACADEMY_`:
   `TLG_ACADEMY_ENABLED=true` (anything else plans only),
   `TLG_ACADEMY_DOMAIN=academy.tlg-beauty.co.uk`,
   `TLG_ACADEMY_DOMAIN_READY=false` (for now),
   `TLG_ACADEMY_ACCREDITATION_PENDING=true`,
   `TLG_ACADEMY_ADMIN_EMAILS=<Jess's email>`,
   `TLG_ACADEMY_CONTACT_EMAIL`, `TLG_ACADEMY_SUPPORT_PHONE`. No secrets.
2. **First deploy** (push, or run the Academy workflow by hand). It creates
   everything, publishes the site on CloudFront's own domain, and prints two
   DNS records at the end of the job: the certificate validation CNAME and
   the `academy` CNAME to CloudFront. The site works at the
   `cloudfront.net` address straight away; the login works there too.
3. **Krystal**: client area, the hosting package, cPanel, Domains, Zone
   Editor, Manage next to tlg-beauty.co.uk, Add Record, CNAME, twice. Not
   the Subdomains tool (that would create a folder and an A record on
   Krystal that fights the CNAME). Nothing else on the zone changes.
4. **Second deploy**: set `TLG_ACADEMY_DOMAIN_READY=true`, run the workflow.
   The certificate validates (it waits up to 20 minutes for the record to
   resolve) and CloudFront answers on `academy.tlg-beauty.co.uk`.
5. **WordPress**: a menu item "Academy" to the subdomain and a one-paragraph
   `/academy/` page with the same link.
6. **Jess**: she registers on the site like any student (hosted UI, email
   code). Because her email is in `TLG_ACADEMY_ADMIN_EMAILS`, the
   post-confirmation trigger puts her in the `admins` group and the
   Approvals page appears in her menu. Students request access on a course
   page; she approves or rejects on Approvals.
7. **The manual**: `academy/files/` is synced to the private files bucket on
   every deploy; `courses.json` names the key (`builder-gel/B01 Builder Gel
   Learner Manual.pdf`). Approved learners get a five-minute signed link
   from the course page. Placeholder courses (`"placeholder": true`) show
   "coming soon" and cannot be requested.
8. **Placeholder videos**: put a YouTube id in `youtube_id` for a lesson in
   `academy/content/courses.json` and push. Empty means "video coming soon".
9. **CPD marks**: The CPD Group rosette, the Approved Provider logo and the
   Register badge are on the home page, the about page, every course page
   and the footer; the Accredited Activity badge (the example from their
   brand guidelines until the real one is issued) sits on each course with
   the "pending" label. When a course is accredited, replace
   `assets/cpd-accredited-activity.png` with the badge they issue, fill the
   course's `cpd` block in `courses.json` and set
   `TLG_ACADEMY_ACCREDITATION_PENDING=false`. The site is for the owners
   while in development; the brand rules on where their logos may appear
   apply when it goes public.

Local check: `python -m http.server 8080 -d academy/web` after copying
`academy/content` to `academy/web/content`; public pages work without
config, login needs the values from `terraform output -json web_config`
pasted into `academy/web/config.js`. Tests: `python -m pytest -q
tests/test_academy.py`.

