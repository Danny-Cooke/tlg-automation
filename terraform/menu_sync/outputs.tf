output "menu_sync_function_name" {
  description = "Invoke by hand to sync now. Payload {\"dry_run\": true} returns the diff without opening a PR."
  value       = aws_lambda_function.menu_sync.function_name
}

output "ops_topic_arn" {
  description = "Infrastructure alarms and sync findings. Confirm the email subscription after the first apply. Read by the bot stack."
  value       = aws_sns_topic.ops.arn
}
