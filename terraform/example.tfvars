# Copy to terraform.tfvars and fill in. terraform.tfvars is git-ignored.
# Salon facts (hours, services, team) live in salon.auto.tfvars and are committed.

aws_region  = "eu-west-2"
environment = "dev"

anthropic_aws_workspace_id = "wrkspc_xxxxxxxxxxxx"

meta_page_id    = "61577501519464"
meta_app_secret = "replace-me"
meta_page_token = "replace-me"

shadow_mode            = true
escalation_emails      = ["info@tlg-beauty.co.uk"]
escalation_sms_numbers = [] # e.g. ["+447512574127"]

# Infrastructure alarms and monitor findings go here, not to Jess.
ops_alert_emails = ["you@example.com"]
monitor_schedule = "rate(1 hour)"
# menu_sync_schedule = "cron(0 7-22/2 * * ? *)" # London time, see menu_sync_timezone

# Menu sync. The PAT comes from the GitHub environment secret in the pipeline;
# for a laptop apply, export TF_VAR_github_pat rather than writing it here.
github_repo = "Danny-Cooke-CK/tlg-automation"
owner_email = "you@example.com"
