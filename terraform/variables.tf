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
  default     = "dev"
}

# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

variable "anthropic_aws_workspace_id" {
  description = "Claude Platform on AWS workspace id (ANTHROPIC_AWS_WORKSPACE_ID)."
  type        = string
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

variable "meta_page_id" {
  description = "Facebook Page id. Used for the Business Suite inbox link in alerts."
  type        = string
}

variable "meta_app_secret" {
  description = "Meta app secret, used to verify webhook signatures."
  type        = string
  sensitive   = true
}

variable "meta_page_token" {
  description = "Long-lived Page access token with pages_messaging and instagram_manage_messages."
  type        = string
  sensitive   = true
}

# ---------------------------------------------------------------------------
# Bot behaviour
# ---------------------------------------------------------------------------

variable "shadow_mode" {
  description = "When true the bot drafts replies and sends them to Jess only. Nothing reaches clients."
  type        = bool
  default     = true
}

variable "escalation_emails" {
  description = "Email addresses that receive escalations (Jess, and anyone covering)."
  type        = list(string)
  default     = []
}

variable "escalation_sms_numbers" {
  description = "E.164 mobile numbers that receive escalations by SMS. Optional."
  type        = list(string)
  default     = []
}

# ---------------------------------------------------------------------------
# Operations: alarms and the scheduled monitor
# ---------------------------------------------------------------------------

variable "ops_alert_emails" {
  description = "Email addresses for infrastructure alarms and monitor findings. You, not Jess."
  type        = list(string)
  default     = []
}

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
# Menu sync: GitHub access for the Lambda that keeps the menu file current
# ---------------------------------------------------------------------------

variable "github_repo" {
  description = "owner/name of this repository on GitHub, where menu sync opens pull requests."
  type        = string
}

variable "github_environment" {
  description = "GitHub environment the deploy workflow runs under; the deploy role trusts only this."
  type        = string
  default     = "prod"
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub OIDC identity provider. Set false if the account already has one."
  type        = bool
  default     = true
}

variable "github_base_branch" {
  description = "Branch the menu sync compares with and targets."
  type        = string
  default     = "main"
}

variable "github_pat" {
  description = "Fine-grained PAT (contents + pull requests on github_repo). Supplied by the deploy pipeline from the GitHub environment secret."
  type        = string
  sensitive   = true
}

variable "menu_sync_schedule" {
  description = "EventBridge Scheduler cron for the Fresha menu sync, in menu_sync_timezone."
  type        = string
  default     = "cron(0 7-22/2 * * ? *)" # 07:00, 09:00, ... 21:00
}

variable "menu_sync_timezone" {
  description = "IANA time zone the menu sync schedule is written in."
  type        = string
  default     = "Europe/London"
}

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
