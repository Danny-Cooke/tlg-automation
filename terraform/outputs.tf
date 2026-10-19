output "webhook_urls" {
  description = "Callback URL per channel. Register each with its Meta app (scripts/meta_setup.py) once the Lambdas are deployed."
  value       = { for c in local.channels : c => "${aws_apigatewayv2_api.webhook.api_endpoint}/webhook/${c}" }
}

output "webhook_verify_tokens" {
  description = "Verify token per channel, for the same registration."
  value       = { for c in local.channels : c => random_password.verify_token[c].result }
  sensitive   = true
}

output "bot_function_names" {
  value = { for c in local.channels : c => aws_lambda_function.bot[c].function_name }
}

output "meta_page_id" {
  description = "The Facebook Page the bots answer for; the pipeline uses it to subscribe the Page to each app."
  value       = var.meta_page_id
}

output "escalation_topic_arn" {
  value = aws_sns_topic.escalations.arn
}

output "ops_topic_arn" {
  description = "Infrastructure alarms and listen-mode notices. Owned by the menu sync stack."
  value       = local.ops_topic_arn
}

output "staff_onboarding" {
  description = "Per-person checklist for the Fresha to Google Calendar sync, which only they can switch on."
  value = {
    for slug, m in var.staff : slug => join("\n", [
      "${m.name} (${m.role})",
      "  Owner does it:  Fresha web > Team > Team members > ${m.name} > Actions > Edit > Settings > Linked calendars > Link a calendar.",
      "  Or they do it:  Fresha web > profile picture > My profile > Workspaces > Manage > Linked calendars > Link a calendar.",
      "  1. Choose Google calendar, sign in as: ${lookup(var.calendar_emails, slug, m.calendar_email) != "" ? lookup(var.calendar_emails, slug, m.calendar_email) : "(their Google account; not stored in Terraform)"}.",
      "  2. Sync mode: 'Export events to calendar' to mirror Fresha into Google. Pick 'Two-way sync' only if their personal Google events should block their Fresha diary.",
      "  3. Export options: include appointments (and blocked time if wanted), location: The Looking Glass Beauty. Complete. Status shows 'Synced' within about 15 minutes.",
      "  4. Their booking link for the bot: ${m.booking_link != "" ? m.booking_link : "(general salon link; add a per-person Fresha link to staff.${slug}.booking_link)"}",
    ])
  }
}
