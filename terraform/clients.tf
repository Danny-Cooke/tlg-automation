# ---------------------------------------------------------------------------
# The client list (plan job 10): a DynamoDB mirror of Fresha's clients and
# the opt-out link that goes in every marketing text.
#
#   tlg-prod-clients            one row per Fresha client; Fresha's fields
#                               plus ours (opt-out, segments, link token)
#   tlg-prod-client-sync        daily, pages Fresha with the owner's session
#   tlg-prod-unsubscribe        GET/POST /stop/{token} on the webhook API
#
# Same bundle as the bot (build/bot), different handlers.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "clients" {
  name         = "${local.name}-clients"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "client_id"

  attribute {
    name = "client_id"
    type = "S"
  }

  attribute {
    name = "token"
    type = "S"
  }

  # The unsubscribe link carries the token, never the phone number.
  global_secondary_index {
    name            = "by_token"
    hash_key        = "token"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.environment == "prod"
  }

  tags = {
    Component = "clients"
  }
}

# ---------------------------------------------------------------------------
# Client sync Lambda
# ---------------------------------------------------------------------------

resource "aws_iam_role" "client_sync" {
  name               = "${local.name}-client-sync"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "client_sync" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.client_sync.arn}:*"]
  }

  statement {
    sid       = "Clients"
    actions   = ["dynamodb:UpdateItem", "dynamodb:Scan", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.clients.arn]
  }

  statement {
    sid       = "FreshaSession"
    actions   = ["ssm:GetParameter"]
    resources = [local.fresha_session_arn]
  }

  statement {
    sid       = "FreshaSessionDecrypt"
    actions   = ["kms:Decrypt"]
    resources = [data.aws_kms_alias.ssm.target_key_arn]
  }

  statement {
    sid       = "Ops"
    actions   = ["sns:Publish"]
    resources = [local.ops_topic_arn]
  }
}

resource "aws_iam_role_policy" "client_sync" {
  name   = "client-sync"
  role   = aws_iam_role.client_sync.id
  policy = data.aws_iam_policy_document.client_sync.json
}

resource "aws_cloudwatch_log_group" "client_sync" {
  name              = "/aws/lambda/${local.name}-client-sync"
  retention_in_days = 30
}

resource "aws_lambda_function" "client_sync" {
  function_name    = "${local.name}-client-sync"
  description      = "Mirrors Fresha's client list and each client's profile page (patch tests, notes, appointments) into the clients table"
  role             = aws_iam_role.client_sync.arn
  runtime          = "python3.12"
  handler          = "clients.sync.lambda_handler"
  filename         = data.archive_file.bot.output_path
  source_code_hash = data.archive_file.bot.output_base64sha256
  timeout          = 900 # ~600 clients, four calls each; the sync stops 45s early and carries on next run
  memory_size      = 256
  architectures    = ["arm64"]

  environment {
    variables = {
      CLIENTS_TABLE        = aws_dynamodb_table.clients.name
      FRESHA_SESSION_PARAM = local.fresha_session_param
      OPS_TOPIC_ARN        = local.ops_topic_arn
      LOG_LEVEL            = "INFO"
    }
  }

  tags = {
    Component = "clients"
  }

  depends_on = [aws_cloudwatch_log_group.client_sync]
}

# Daily, in London time, before the salon opens.
data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "client_sync_scheduler" {
  name               = "${local.name}-client-sync-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "client_sync_scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.client_sync.arn]
  }
}

resource "aws_iam_role_policy" "client_sync_scheduler" {
  name   = "invoke-client-sync"
  role   = aws_iam_role.client_sync_scheduler.id
  policy = data.aws_iam_policy_document.client_sync_scheduler.json
}

resource "aws_scheduler_schedule" "client_sync" {
  name                         = "${local.name}-client-sync"
  description                  = "Fresha client list mirror, daily"
  schedule_expression          = var.client_sync_schedule
  schedule_expression_timezone = var.client_sync_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.client_sync.arn
    role_arn = aws_iam_role.client_sync_scheduler.arn
    input    = jsonencode({ source = "schedule" })

    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "client_sync_errors" {
  alarm_name          = "${local.name}-client-sync-errors"
  alarm_description   = "The Fresha client list mirror failed."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.ops_topic_arn]

  dimensions = {
    FunctionName = aws_lambda_function.client_sync.function_name
  }
}

# ---------------------------------------------------------------------------
# Unsubscribe Lambda, on the webhook API: ANY /stop/{token}
# The texts carry tlg-beauty.co.uk/stop/<token>; the website redirects
# /stop/* here (docs/setup.md 6), so the path is the same on both.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "unsubscribe" {
  name               = "${local.name}-unsubscribe"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "unsubscribe" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.unsubscribe.arn}:*"]
  }

  statement {
    sid       = "Clients"
    actions   = ["dynamodb:Query", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.clients.arn, "${aws_dynamodb_table.clients.arn}/index/by_token"]
  }
}

resource "aws_iam_role_policy" "unsubscribe" {
  name   = "unsubscribe"
  role   = aws_iam_role.unsubscribe.id
  policy = data.aws_iam_policy_document.unsubscribe.json
}

resource "aws_cloudwatch_log_group" "unsubscribe" {
  name              = "/aws/lambda/${local.name}-unsubscribe"
  retention_in_days = 30
}

resource "aws_lambda_function" "unsubscribe" {
  function_name    = "${local.name}-unsubscribe"
  description      = "The stop link in marketing texts: /stop/{token}"
  role             = aws_iam_role.unsubscribe.arn
  runtime          = "python3.12"
  handler          = "clients.unsubscribe.lambda_handler"
  filename         = data.archive_file.bot.output_path
  source_code_hash = data.archive_file.bot.output_base64sha256
  timeout          = 10
  memory_size      = 256
  architectures    = ["arm64"]

  environment {
    variables = {
      CLIENTS_TABLE = aws_dynamodb_table.clients.name
      SALON_NAME    = var.salon.name
      LOG_LEVEL     = "INFO"
    }
  }

  tags = {
    Component = "clients"
  }

  depends_on = [aws_cloudwatch_log_group.unsubscribe]
}

resource "aws_apigatewayv2_integration" "unsubscribe" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.unsubscribe.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "unsubscribe" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "ANY /stop/{token}"
  target    = "integrations/${aws_apigatewayv2_integration.unsubscribe.id}"
}

resource "aws_lambda_permission" "unsubscribe_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.unsubscribe.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}

resource "aws_cloudwatch_metric_alarm" "unsubscribe_errors" {
  alarm_name          = "${local.name}-unsubscribe-errors"
  alarm_description   = "The unsubscribe page failed for a client."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.ops_topic_arn]

  dimensions = {
    FunctionName = aws_lambda_function.unsubscribe.function_name
  }
}
