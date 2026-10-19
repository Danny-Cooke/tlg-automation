output "webhook_url" {
  description = "Paste this as the Callback URL in the Meta app's Webhooks settings."
  value       = "${aws_apigatewayv2_api.webhook.api_endpoint}/webhook"
}

output "webhook_verify_token" {
  description = "Paste this as the Verify Token in the Meta app's Webhooks settings."
  value       = random_password.verify_token.result
  sensitive   = true
}

output "escalation_topic_arn" {
  value = aws_sns_topic.escalations.arn
}

output "lambda_function_name" {
  value = aws_lambda_function.bot.function_name
}

output "ops_topic_arn" {
  description = "Infrastructure alarms and monitor findings. Confirm the email subscription after the first apply."
  value       = aws_sns_topic.ops.arn
}

output "monitor_function_name" {
  description = "Invoke by hand to run every check now: aws lambda invoke --function-name <this> /dev/stdout"
  value       = aws_lambda_function.monitor.function_name
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

output "menu_sync_function_name" {
  description = "Invoke by hand to sync now. Payload {\"dry_run\": true} returns the diff without opening a PR."
  value       = aws_lambda_function.menu_sync.function_name
}
