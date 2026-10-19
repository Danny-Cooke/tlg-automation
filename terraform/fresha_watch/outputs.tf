output "fresha_watch_function_name" {
  description = "Invoke by hand to check now. Payload {\"dry_run\": true} runs the checks without saving state or sending anything."
  value       = aws_lambda_function.fresha_watch.function_name
}

output "fresha_watch_state_parameter" {
  description = "SSM parameter holding the last run. Reset it to {} to re-baseline the shapes after an expected Fresha change."
  value       = aws_ssm_parameter.state.name
}
