# Copy to terraform.tfvars and fill in. terraform.tfvars is git-ignored.
# Salon facts (hours, services, team) live in salon.auto.tfvars and the
# generated fresha-menu.auto.tfvars.json, both committed. In the pipeline
# every value below comes from the GitHub prod environment, not a file.

aws_region  = "eu-west-2"
environment = "prod"
owner_email = "you@example.com"

# Meta: one app per channel. Tlg-app1 is Messenger, Tlg-app2 is Instagram.
meta_page_id              = "61577501519464"
meta_messenger_app_id     = "replace-me"
meta_messenger_app_secret = "replace-me"
meta_instagram_app_id     = "" # Tlg-app2, when ready
meta_instagram_app_secret = ""
meta_page_token           = "" # needed from shadow mode on

# simple: a plain acknowledgement, no Claude. shadow: draft replies to Jess
# only. live: reply with Claude.
bot_mode = "simple"
# true: answer only messages that start with the trigger word (the tester).
message_test_mode = true
escalation_emails = [] # Jess, from shadow mode on, e.g. ["info@tlg-beauty.co.uk"]

# Claude Platform on AWS, needed from shadow mode on.
anthropic_aws_workspace_id = ""

# Infrastructure alarms and listen-mode notices go to the ops topic, which
# belongs to the menu sync stack (terraform/menu_sync).
