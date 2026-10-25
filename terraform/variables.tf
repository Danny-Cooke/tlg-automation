variable "aws_region" {
  description = "AWS region for everything. London by default."
  type        = string
  default     = "eu-west-2"
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
  default     = "tlg"
}

variable "environment" {
  description = "dev or prod. Only affects names and tags."
  type        = string
  default     = "prod"
}

# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

variable "anthropic_aws_workspace_id" {
  description = "Claude Platform on AWS workspace id (ANTHROPIC_AWS_WORKSPACE_ID). Needed from shadow mode on; empty in simple mode."
  type        = string
  default     = ""
}

variable "claude_model" {
  description = "Model id passed to the API. Sonnet since 2026-10-25: the first Instagram reply took 20 s end to end, 14 s of it Opus drafting, on Meta's 20 s webhook deadline."
  type        = string
  default     = "claude-sonnet-5-5"
}

variable "claude_effort" {
  description = "Effort level for replies. low is right for chat."
  type        = string
  default     = "low"
}

# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

# One Meta app per channel: Tlg-app1 for Messenger, Tlg-app2 for Instagram.
# Each app's secret verifies that channel's webhook signatures.

variable "meta_page_id" {
  description = "Facebook Page id. Used for the Business Suite inbox link in alerts."
  type        = string
}

variable "meta_messenger_app_id" {
  description = "App ID of the Messenger app (Tlg-app1)."
  type        = string
}

variable "meta_messenger_app_secret" {
  description = "App Secret of the Messenger app (Tlg-app1)."
  type        = string
  sensitive   = true
}

variable "meta_instagram_app_id" {
  description = "App ID of the Instagram app (Tlg-app2). Empty until it is set up."
  type        = string
  default     = ""
}

variable "meta_instagram_app_secret" {
  description = "App Secret of the Instagram app (Tlg-app2). Empty until it is set up; the Instagram bot rejects every call until then."
  type        = string
  sensitive   = true
  default     = ""
}

variable "meta_page_token" {
  description = "Long-lived Page access token issued by the Messenger app (Tlg-app1) with pages_messaging. Needed from shadow mode on."
  type        = string
  sensitive   = true
  default     = ""
}

variable "meta_instagram_page_token" {
  description = "Page access token issued by the Instagram app (Tlg-app2) with instagram_manage_messages, instagram_basic and pages_manage_metadata. A token belongs to the app that issued it, so the Messenger one cannot serve Instagram (checked 2026-10-25). Empty: the Instagram bot falls back to meta_page_token, which can verify webhooks but not read or send Instagram messages."
  type        = string
  sensitive   = true
  default     = ""
}

# ---------------------------------------------------------------------------
# Bot behaviour
# ---------------------------------------------------------------------------

variable "bot_mode" {
  description = "simple: a plain acknowledgement, no Claude, no persona. shadow: draft replies with Claude and email them to Jess only. live: reply with Claude."
  type        = string
  default     = "simple"

  validation {
    condition     = contains(["simple", "shadow", "live"], var.bot_mode)
    error_message = "bot_mode must be simple, shadow or live."
  }

  validation {
    condition     = var.bot_mode == "simple" || (var.meta_page_token != "" && var.anthropic_aws_workspace_id != "")
    error_message = "shadow and live need meta_page_token and anthropic_aws_workspace_id."
  }
}

variable "message_test_mode" {
  description = "true: the bots answer only messages that start with the trigger word, so only the tester gets replies. false: they answer everyone."
  type        = bool
  default     = true
}

variable "reply_delay_seconds" {
  description = "Pause before each reply, with the typing indicator showing, so the bot does not answer faster than a person could. Under Meta's 20 second webhook deadline."
  type        = number
  default     = 10

  validation {
    condition     = var.reply_delay_seconds >= 0 && var.reply_delay_seconds <= 15
    error_message = "reply_delay_seconds must be between 0 and 15."
  }
}

variable "carmen_whatsapp" {
  description = "Carmen's WhatsApp number, given to tattoo clients who want more than a consultation (user, 2026-10-21). Empty: the bot uses the holding line instead."
  type        = string
  default     = ""
}

variable "patch_test_lead_hours" {
  description = "How long before a lash or brow treatment its patch test must be (plan job 12). The bot books the test at least this far ahead."
  type        = number
  default     = 24
}

variable "chaser_schedule" {
  description = "When the confirmation chaser runs (plan job 14), after the client mirror. EventBridge cron, in chaser_timezone."
  type        = string
  default     = "cron(0 6 * * ? *)"
}

variable "chaser_timezone" {
  type    = string
  default = "Europe/London"
}

variable "chaser_send_texts" {
  description = "false: the chaser only lists who it would text (the SMS account is still in the sandbox). true: it texts them."
  type        = bool
  default     = false
}

variable "chaser_fresha_reminder" {
  description = "true: the chaser also presses Fresha's own \"Send reminder\" for each appointment, so Fresha re-sends its confirmation email."
  type        = bool
  default     = false
}

variable "chaser_email_subject" {
  description = "The subject of the Fresha email the chase text tells the client to look for."
  type        = string
  default     = "Please confirm your appointment"
}

variable "sms_sender_id" {
  description = "End User Messaging sender ID the salon's texts come from (the Fresha watch uses the same one)."
  type        = string
  default     = "TLGWATCH"
}

variable "sms_sender_country" {
  type    = string
  default = "GB"
}

variable "sophie_whatsapp" {
  description = "Sophie's WhatsApp number, given to clients who want to book hair with her (user, 2026-10-24: no hair bookings in chat). Empty: the bot says Sophie will message them and hands over."
  type        = string
  default     = ""
}

variable "staff_senders" {
  description = "Comma-separated names of staff who message the Page as themselves (GitHub variable TLG_STAFF). A sender whose Facebook or Instagram name contains one is never answered (user, 2026-10-25)."
  type        = string
  default     = ""
}

variable "message_test_trigger" {
  description = "The word a message must start with to be answered while message_test_mode is true. Stripped before the bot reads the text."
  type        = string
  default     = "joshsmells"
}

variable "escalation_emails" {
  description = "Email addresses that receive escalations (Jess, and anyone covering)."
  type        = list(string)
  default     = []
}

# ---------------------------------------------------------------------------
# Operations: alarms and the scheduled monitor
# ---------------------------------------------------------------------------

variable "monitor_schedule" {
  description = "EventBridge schedule expression for the monitor Lambda."
  type        = string
  default     = "rate(1 hour)"
}

variable "owner_email" {
  description = "Owner tag on every resource."
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Menu file metadata (the menu sync itself is the terraform/menu_sync stack)
# ---------------------------------------------------------------------------

variable "menu_snapshot_date" {
  description = "Date the menu file was generated from Fresha. Written by menu sync; informational."
  type        = string
  default     = ""
}

variable "calendar_emails" {
  description = "Google account per staff slug for the calendar checklist. Hand-written; not in the generated menu file."
  type        = map(string)
  default     = {}
}

# ---------------------------------------------------------------------------
# Salon facts. These are rendered into the bot's system prompt.
# ---------------------------------------------------------------------------

variable "salon" {
  description = "Salon details the bot is allowed to quote."
  type = object({
    name                 = string
    address              = string
    phone                = string
    general_booking_link = string
    opening_hours        = map(string)
    extra_notes          = optional(string, "")
    venue_url            = optional(string, "")            # Fresha venue page; the monitor checks it loads
    not_bookable_staff   = optional(list(string), [])      # Fresha team members the bot must never offer or book
    not_bookable_for     = optional(map(list(string)), {}) # service name -> people the bot must not book for it
  })
}

variable "services" {
  description = <<-EOT
    Services grouped by Fresha category (category names exactly as Fresha shows them).
    staff lists the first names of the people bookable for that service on Fresha.
    Generated from Fresha by the menu sync into fresha-menu.auto.tfvars.json.
  EOT
  type = list(object({
    category     = string
    name         = string
    price        = string
    duration     = string
    staff        = optional(list(string), [])
    booking_link = optional(string, "")
    notes        = optional(string, "")
  }))
  default = []
}

variable "staff" {
  description = <<-EOT
    Team members. Keyed by a short slug. Generated from Fresha by the menu
    sync into fresha-menu.auto.tfvars.json; do not edit by hand. Google
    accounts for the calendar checklist go in var.calendar_emails.
  EOT
  type = map(object({
    name           = string
    role           = string
    employee_id    = optional(string, "")
    booking_link   = optional(string, "")
    services       = optional(list(string), [])
    calendar_email = optional(string, "")
  }))
  default = {}
}

# ---------------------------------------------------------------------------
# Client list mirror (plan job 10)
# ---------------------------------------------------------------------------

variable "client_sync_schedule" {
  description = "EventBridge Scheduler cron for the Fresha client list mirror, in client_sync_timezone."
  type        = string
  default     = "cron(30 5 * * ? *)" # daily, 05:30
}

variable "client_sync_timezone" {
  description = "IANA time zone the client sync schedule is written in."
  type        = string
  default     = "Europe/London"
}

# ---------------------------------------------------------------------------
# Telegram: the team's hand-over group (decision 2026-10-20)
# ---------------------------------------------------------------------------

variable "telegram_bot_token" {
  description = "BotFather token for the hand-over bot. Empty disables Telegram; hand-overs then go to email only."
  type        = string
  default     = ""
  sensitive   = true
}

variable "telegram_chat_id" {
  description = "The team group's chat id (a negative number). Leave empty: the bot discovers it from its update feed the first time someone has spoken in the group, and caches it in SSM."
  type        = string
  default     = ""
}
