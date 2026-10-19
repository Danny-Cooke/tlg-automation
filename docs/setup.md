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
4. **Page access token.** Messenger > API setup > Generate token gives one
   quickly; a System User token (Business Settings, with `pages_messaging`,
   `pages_manage_metadata`, `instagram_basic`, `instagram_manage_messages`)
   never expires and is the better one for the bots. Needed before the bots
   can reply; until then they store, log and email what arrives.
5. **Testers.** Until app review, Meta delivers messages only from people
   with a role on the app. Add your own Facebook and Instagram accounts as
   testers (App roles > Roles) so you can message the Page and see the bots
   react.
6. **App review.** Before the bots can message anyone else, submit
   `pages_messaging` (Tlg-app1) and `instagram_manage_messages` (Tlg-app2)
   for review. Shadow mode runs on testers before that lands.

## 2. GitHub prod environment

Secrets (set 2026-10-19): `TLG_APP1_ID`, `TLG_APP1_SECRET` (Messenger),
`TLG_APP2_ID`, `TLG_APP2_SECRET` (Instagram). Then `TLG_PAGE_TOKEN` so the
bots can reply (without it they store, log and email but cannot send), and
later `ANTHROPIC_AWS_WORKSPACE_ID` for shadow mode. The Page ID is in
`salon.auto.tfvars`; it is not secret.

Variables: `MESSAGE_TEST_MODE` (`true`: only messages starting with the
trigger word are answered, so only the tester hears from the bots; `false`:
everyone is answered), `BOT_MODE` (`simple`, the default, then `shadow`,
then `live`) and `ESCALATION_EMAILS` (JSON list, Jess, from shadow mode on).

The bot stack applies once `TLG_APP1_SECRET` exists. The deploy then
registers the webhooks with Meta itself (section 3) and prints the URLs.

## 3. Meta: the webhooks (done by the pipeline)

After each apply the workflow runs `scripts/meta_setup.py` once per channel
with the app's id and secret: it points the app's webhook at that channel's
URL and, when `TLG_PAGE_TOKEN` is set, subscribes the Page to the app. The
Instagram channel is registered once `TLG_APP2_SECRET` exists. Registration
is idempotent, so every deploy re-asserts it.

Without a page token Meta will not deliver Page messages until the Page is
subscribed to the app, which the console can do: Messenger (or Instagram) >
Settings > Webhooks > Add subscriptions, tick messages. To run the script
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
reaches clients. Run this for a week, tune `persona/jess.md` and the salon
variables, then set `BOT_MODE` to `live`. `MESSAGE_TEST_MODE` keeps gating
replies in every mode until it is set to `false`.

## 5. Clearing a hand-over

When the bot escalates, it stays quiet on that thread. To hand it back:

```bash
aws dynamodb update-item \
  --table-name tlg-prod-conversations \
  --key '{"sender_id": {"S": "<PSID>"}}' \
  --update-expression "SET handed_to_jess = :f" \
  --expression-attribute-values '{":f": {"BOOL": false}}'
```

A small admin endpoint for Jess can replace this later.

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
