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

The bot runs without a browser. Messages come in over Meta's webhook and go
out over the Graph API. The browser is needed only for the one-time steps
below that Meta does not expose through any API.

## 1. Meta: things only the console can do (once)

At https://developers.facebook.com, logged in as an admin of the salon's
Facebook Page:

1. Create an app of type **Business**. Note the **App ID** and **App Secret**
   from App settings > Basic.
2. Add the **Messenger** product and the **Instagram** product.
3. Make sure the salon's Instagram professional account is linked to the
   Facebook Page (Business Settings > Instagram accounts).
4. Get a **Page access token**. Either Messenger > API setup > Generate token,
   or create a System User in Business Settings with the
   `pages_messaging`, `pages_manage_metadata`, `instagram_basic` and
   `instagram_manage_messages` permissions and generate a never-expiring token
   for it. The System User route is better for a bot.
5. App review: before the app can message people who are not app admins or
   testers, submit `pages_messaging` and `instagram_manage_messages` for
   review. Shadow mode can run on test accounts before that lands.

Everything after this is scripted.

## 2. AWS

```bash
# build the Lambda bundle (needs Python 3.12-compatible wheels, pulled for arm64)
bash scripts/build_lambda.sh

cd terraform
cp example.tfvars terraform.tfvars   # fill in Meta values, workspace id, salon facts, Jess's email
terraform init
terraform apply
terraform output webhook_url
terraform output -raw webhook_verify_token
```

Jess will get an SNS confirmation email. She has to click it once.

The `anthropic_aws_workspace_id` comes from the Claude Platform on AWS
onboarding (Claude Console > Workspaces, after linking the AWS account).

## 3. Meta: wire the webhook (scripted)

```bash
python scripts/meta_setup.py \
  --app-id <APP_ID> --app-secret <APP_SECRET> \
  --page-id <PAGE_ID> --page-token <PAGE_TOKEN> \
  --callback-url "$(cd terraform && terraform output -raw webhook_url)" \
  --verify-token "$(cd terraform && terraform output -raw webhook_verify_token)"
```

This registers the callback for both the `page` and `instagram` objects and
subscribes the Page to the app. Meta hits `GET /webhook` during this call, so
the Lambda must be deployed first.

## 4. Shadow mode

`shadow_mode = true` (the default). The bot drafts a reply for every message
and emails it to Jess instead of sending it. Nothing reaches clients. Run this
for a week, tune `persona/jess.md` and the salon variables, then set
`shadow_mode = false` and apply.

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
