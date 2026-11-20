variable "aws_region" {
  description = "AWS region for everything except the CloudFront certificate. London by default."
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
# Academy. Every GitHub variable for this stack is prefixed TLG_ACADEMY_ and
# arrives here as TF_VAR_academy_*.
# ---------------------------------------------------------------------------

variable "academy_domain" {
  description = "The academy's own host name, e.g. academy.tlg-beauty.co.uk (GitHub variable TLG_ACADEMY_DOMAIN). Empty: CloudFront's own domain only."
  type        = string
  default     = ""
}

variable "academy_domain_ready" {
  description = "true once the two CNAME records (certificate validation, and the host name to CloudFront) exist in Krystal's DNS (TLG_ACADEMY_DOMAIN_READY). Until then CloudFront serves on its own domain and the certificate waits."
  type        = bool
  default     = false
}

variable "academy_admin_emails" {
  description = "Email addresses placed in the admins group when they register (TLG_ACADEMY_ADMIN_EMAILS, comma-separated). Jess."
  type        = string
  default     = ""
}

variable "academy_contact_email" {
  description = "Shown in the academy footer and privacy notice (TLG_ACADEMY_CONTACT_EMAIL)."
  type        = string
  default     = ""
}

variable "academy_sender_email" {
  description = "The address the shop's receipts and booking confirmations are sent from (TLG_ACADEMY_SENDER_EMAIL). Empty: no emails are sent. The mailbox gets a verification link from AWS on the first apply."
  type        = string
  default     = ""
}

variable "academy_shop_origins" {
  description = "Websites whose pages may call the shop API from the browser: the main site, where the buy buttons, the booking page and the course-dates page live."
  type        = list(string)
  default     = ["https://tlg-beauty.co.uk", "https://www.tlg-beauty.co.uk"]
}

variable "academy_shop_booking_url" {
  description = "The page a buyer lands on after paying, to choose a date. The order token is added as ?order=."
  type        = string
  default     = "https://tlg-beauty.co.uk/academy/booking/"
}

variable "academy_shop_courses_url" {
  description = "Where Stripe's back link goes if the buyer does not pay: the academy page with the courses."
  type        = string
  default     = "https://tlg-beauty.co.uk/academy/"
}

variable "academy_support_phone" {
  description = "Shown in the academy footer (TLG_ACADEMY_SUPPORT_PHONE)."
  type        = string
  default     = ""
}

variable "academy_accreditation_pending" {
  description = "true: every course shows 'CPD accreditation pending' and no badge; false: each course shows its own badge if it has one (TLG_ACADEMY_ACCREDITATION_PENDING). Read by the site build, carried here so the config output is complete."
  type        = bool
  default     = true
}

variable "academy_local_dev_url" {
  description = "A localhost origin allowed as a login callback for development, e.g. http://localhost:8080. Empty to disable."
  type        = string
  default     = "http://localhost:8080"
}
