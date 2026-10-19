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

# ---------------------------------------------------------------------------
# Who gets the text
# ---------------------------------------------------------------------------

variable "alert_phone_numbers" {
  description = "E.164 numbers texted by SNS when a Fresha page breaks, recovers or changes shape. Supplied by the deploy pipeline from the GitHub environment secret. Empty means email only."
  type        = list(string)
  default     = []
  sensitive   = true

  validation {
    condition     = alltrue([for n in var.alert_phone_numbers : can(regex("^\\+[1-9][0-9]{6,14}$", n))])
    error_message = "Each number must be E.164, for example +447700900123."
  }
}

# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

variable "fresha_watch_schedule" {
  description = "EventBridge Scheduler cron for the Fresha watch, in fresha_watch_timezone. Half past the hour, between menu sync runs."
  type        = string
  default     = "cron(30 7-22 * * ? *)"
}

variable "fresha_watch_timezone" {
  description = "IANA time zone the schedule is written in."
  type        = string
  default     = "Europe/London"
}

# ---------------------------------------------------------------------------
# Salon: loaded from ../salon.auto.tfvars with -var-file, the same file the
# other stacks read. Only these three attributes are used; the rest of that
# file is dropped by the object type conversion.
# ---------------------------------------------------------------------------

variable "salon" {
  description = "Salon facts. The watch reads the venue page, the general booking link and the name it must mention."
  type = object({
    name                 = string
    venue_url            = string
    general_booking_link = string
  })
}
