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

variable "owner_email" {
  description = "Owner tag on every resource."
  type        = string
  default     = ""
}

variable "ops_alert_emails" {
  description = "Email addresses for infrastructure alarms and menu sync findings. You, not Jess."
  type        = list(string)
  default     = []
}

# ---------------------------------------------------------------------------
# GitHub: the Lambda's PR access
# ---------------------------------------------------------------------------

variable "github_repo" {
  description = "owner/name of this repository on GitHub, where menu sync opens pull requests."
  type        = string
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

# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

variable "menu_sync_schedule" {
  description = "EventBridge Scheduler cron for the Fresha menu sync, in menu_sync_timezone."
  type        = string
  default     = "cron(0 7-22 * * ? *)" # on the hour, 07:00 to 22:00
}

variable "menu_sync_timezone" {
  description = "IANA time zone the menu sync schedule is written in."
  type        = string
  default     = "Europe/London"
}

# ---------------------------------------------------------------------------
# Salon: loaded from ../salon.auto.tfvars with -var-file, the same file the
# bot stack reads. Only venue_url is used here; the other attributes in that
# file are dropped by the object type conversion.
# ---------------------------------------------------------------------------

variable "salon" {
  description = "Salon facts. Only venue_url (the Fresha venue page) is read by this stack."
  type = object({
    venue_url = string
  })
}
