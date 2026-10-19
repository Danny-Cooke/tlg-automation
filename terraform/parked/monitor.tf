# ---------------------------------------------------------------------------
# Scheduled monitor: is everything still working, has anything changed shape.
#
# A second Lambda from the same build zip, run by EventBridge on a schedule.
# It checks our webhook, the Meta page token and subscription, the Fresha
# booking links, and the Fresha partner dashboard code the booking integration
# depends on. Findings go to the ops topic (you), not to Jess.
# ---------------------------------------------------------------------------

locals {
  # Every public Fresha page the bot may hand out. The monitor expects each
  # one to load and to mention the salon by name.
  fresha_links = distinct(compact(concat(
    [var.salon.venue_url, var.salon.general_booking_link],
    [for m in var.staff : m.booking_link],
  )))
}

# PARKED 2026-10-19: not loaded by Terraform (this directory is not a root).
# To revive, move it back into terraform/, point it at
# aws_lambda_function.bot["messenger"] and the per-channel secret, and add
# "monitor" to the bot bundle. local.ops_topic_arn now lives in main.tf.

# Previous run's findings and fingerprints. Written by the Lambda, so
# Terraform only creates it and then leaves the value alone.
resource "aws_ssm_parameter" "monitor_state" {
  name  = "/${var.name_prefix}/${var.environment}/monitor/state"
  type  = "String"
  value = "{}"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_iam_role" "monitor" {
  name               = "${local.name}-monitor"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "monitor" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.monitor.arn}:*"]
  }

  statement {
    sid       = "State"
    actions   = ["ssm:GetParameter", "ssm:PutParameter"]
    resources = [aws_ssm_parameter.monitor_state.arn]
  }

  statement {
    sid       = "Alert"
    actions   = ["sns:Publish"]
    resources = [local.ops_topic_arn]
  }

  statement {
    sid       = "Secrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.meta["messenger"].arn]
  }

  statement {
    sid       = "BotMetrics"
    actions   = ["cloudwatch:GetMetricStatistics"]
    resources = ["*"] # GetMetricStatistics does not support resource-level permissions
  }
}

resource "aws_iam_role_policy" "monitor" {
  name   = "monitor"
  role   = aws_iam_role.monitor.id
  policy = data.aws_iam_policy_document.monitor.json
}

resource "aws_cloudwatch_log_group" "monitor" {
  name              = "/aws/lambda/${local.name}-monitor"
  retention_in_days = 30
}

resource "aws_lambda_function" "monitor" {
  function_name    = "${local.name}-monitor"
  role             = aws_iam_role.monitor.arn
  runtime          = "python3.12"
  handler          = "monitor.handler.lambda_handler"
  filename         = data.archive_file.bot.output_path
  source_code_hash = data.archive_file.bot.output_base64sha256
  timeout          = 120
  memory_size      = 256
  architectures    = ["arm64"]

  environment {
    variables = {
      WEBHOOK_URL             = "${aws_apigatewayv2_api.webhook.api_endpoint}/webhook/messenger"
      META_SECRET_ARN         = aws_secretsmanager_secret.meta["messenger"].arn
      META_PAGE_ID            = var.meta_page_id
      FRESHA_LINKS_JSON       = jsonencode(local.fresha_links)
      SALON_NAME              = var.salon.name
      BOT_FUNCTION_NAME       = aws_lambda_function.bot["messenger"].function_name
      MONITOR_STATE_PARAMETER = aws_ssm_parameter.monitor_state.name
      OPS_TOPIC_ARN           = local.ops_topic_arn
      LOG_LEVEL               = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.monitor]
}

resource "aws_cloudwatch_event_rule" "monitor" {
  name                = "${local.name}-monitor"
  description         = "Run the TLG monitor"
  schedule_expression = var.monitor_schedule
}

resource "aws_cloudwatch_event_target" "monitor" {
  rule = aws_cloudwatch_event_rule.monitor.name
  arn  = aws_lambda_function.monitor.arn
}

resource "aws_lambda_permission" "monitor_schedule" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.monitor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.monitor.arn
}

# The monitor watching itself: if it crashes, or stops being invoked, you hear
# about it from CloudWatch rather than from silence.

resource "aws_cloudwatch_metric_alarm" "monitor_errors" {
  alarm_name          = "${local.name}-monitor-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.ops_topic_arn]

  dimensions = {
    FunctionName = aws_lambda_function.monitor.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "monitor_silent" {
  alarm_name          = "${local.name}-monitor-silent"
  alarm_description   = "The monitor has not run for a while. Check the EventBridge rule and the Lambda."
  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [local.ops_topic_arn]
  ok_actions          = [local.ops_topic_arn]

  dimensions = {
    FunctionName = aws_lambda_function.monitor.function_name
  }
}
