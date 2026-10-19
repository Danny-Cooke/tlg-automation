locals {
  name = "${var.name_prefix}-${var.environment}"

  # Everything the bot may quote, rendered once into one env var.
  salon_config = {
    salon_name           = var.salon.name
    address              = var.salon.address
    phone                = var.salon.phone
    opening_hours        = var.salon.opening_hours
    general_booking_link = var.salon.general_booking_link
    extra_notes          = var.salon.extra_notes
    services             = var.services
    staff = [
      for slug, m in var.staff : {
        name         = m.name
        role         = m.role
        booking_link = m.booking_link
        services     = m.services
      }
    ]
  }

  # Build directory populated by scripts/build_lambda.sh before `terraform apply`.
  lambda_build_dir = "${path.module}/../build/lambda"
}

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

resource "random_password" "verify_token" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "meta" {
  name                    = "${local.name}/meta"
  description             = "Meta app secret, page token and webhook verify token"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "meta" {
  secret_id = aws_secretsmanager_secret.meta.id
  secret_string = jsonencode({
    app_secret   = var.meta_app_secret
    page_token   = var.meta_page_token
    verify_token = random_password.verify_token.result
  })
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "conversations" {
  name         = "${local.name}-conversations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "sender_id"

  attribute {
    name = "sender_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.environment == "prod"
  }
}

# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "escalations" {
  name = "${local.name}-escalations"
}

resource "aws_sns_topic_subscription" "email" {
  for_each  = toset(var.escalation_emails)
  topic_arn = aws_sns_topic.escalations.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_sns_topic_subscription" "sms" {
  for_each  = toset(var.escalation_sms_numbers)
  topic_arn = aws_sns_topic.escalations.arn
  protocol  = "sms"
  endpoint  = each.value
}

# ---------------------------------------------------------------------------
# Lambda
# ---------------------------------------------------------------------------

data "archive_file" "bot" {
  type        = "zip"
  source_dir  = local.lambda_build_dir
  output_path = "${path.module}/../build/lambda.zip"
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "bot" {
  name               = "${local.name}-bot"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "bot" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.bot.arn}:*"]
  }

  statement {
    sid       = "State"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.conversations.arn]
  }

  statement {
    sid       = "Escalate"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.escalations.arn]
  }

  statement {
    sid       = "Secrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.meta.arn]
  }

  # Claude Platform on AWS: POST /v1/messages on this workspace only.
  # Reference: platform.claude.com/docs/en/api/claude-platform-on-aws-iam-actions
  statement {
    sid       = "Claude"
    actions   = ["aws-external-anthropic:CreateInference"]
    resources = ["arn:aws:aws-external-anthropic:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workspace/${var.anthropic_aws_workspace_id}"]
  }
}

resource "aws_iam_role_policy" "bot" {
  name   = "bot"
  role   = aws_iam_role.bot.id
  policy = data.aws_iam_policy_document.bot.json
}

resource "aws_cloudwatch_log_group" "bot" {
  name              = "/aws/lambda/${local.name}-bot"
  retention_in_days = 30
}

resource "aws_lambda_function" "bot" {
  function_name    = "${local.name}-bot"
  role             = aws_iam_role.bot.arn
  runtime          = "python3.12"
  handler          = "bot.handler.lambda_handler"
  filename         = data.archive_file.bot.output_path
  source_code_hash = data.archive_file.bot.output_base64sha256
  timeout          = 60
  memory_size      = 512
  architectures    = ["arm64"]

  environment {
    variables = {
      SALON_CONFIG_JSON          = jsonencode(local.salon_config)
      PERSONA_PATH               = "/var/task/bot/jess.md"
      CONVERSATIONS_TABLE        = aws_dynamodb_table.conversations.name
      ESCALATION_TOPIC_ARN       = aws_sns_topic.escalations.arn
      META_SECRET_ARN            = aws_secretsmanager_secret.meta.arn
      META_PAGE_ID               = var.meta_page_id
      SHADOW_MODE                = tostring(var.shadow_mode)
      CLAUDE_MODEL               = var.claude_model
      CLAUDE_EFFORT              = var.claude_effort
      ANTHROPIC_AWS_WORKSPACE_ID = var.anthropic_aws_workspace_id
      LOG_LEVEL                  = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.bot]
}

# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "webhook" {
  name          = "${local.name}-webhook"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "bot" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.bot.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "verify" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "GET /webhook"
  target    = "integrations/${aws_apigatewayv2_integration.bot.id}"
}

resource "aws_apigatewayv2_route" "events" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook"
  target    = "integrations/${aws_apigatewayv2_integration.bot.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.webhook.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 20
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.bot.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# Alarm: any handler error goes to the ops topic (see monitor.tf)
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "bot_errors" {
  alarm_name          = "${local.name}-bot-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops.arn]

  dimensions = {
    FunctionName = aws_lambda_function.bot.function_name
  }
}
