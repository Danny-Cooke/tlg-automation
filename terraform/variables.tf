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
  description = "Model id passed to the API."
  type        = string
  default     = "claude-opus-5-5"
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
  description = "Long-lived Page access token with pages_messaging and instagram_manage_messages. Needed from shadow mode on."
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

variable "message_test_trigger" {
  description = "The word a message must start with to be answered while message_test_mode is true. Stripped before the bot reads the text."
  type        = string
  default     = "bootycall"
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
    venue_url            = optional(string, "") # Fresha venue page; the monitor checks it loads
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
