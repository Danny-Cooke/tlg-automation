# ---------------------------------------------------------------------------
# The bot stack: one Lambda per Meta channel, invoked by Meta the moment a
# message arrives.
#
#   messenger  the Facebook Page, Meta app Tlg-app1
#   instagram  the salon's Instagram account, Meta app Tlg-app2
#
# Same code, separate function, secret, logs and alarm per channel, so each
# can be switched on, reviewed by Meta and debugged on its own. One HTTP API
# with a route per channel, one conversation table, one escalation topic.
# What the bots do with a message is var.bot_mode: simple, shadow or live.
# While var.message_test_mode is true only messages starting with the
# trigger word are answered, so only the tester hears from them.
# ---------------------------------------------------------------------------

locals {
  name = "${var.name_prefix}-${var.environment}"

  channels = toset(["messenger", "instagram"])

  meta_app_ids = {
    messenger = var.meta_messenger_app_id
    instagram = var.meta_instagram_app_id
  }

  # Populated by `scripts/build_lambda.sh bot` before terraform apply. The
  # bundle carries bot/salon_config.json, rendered from salon.auto.tfvars and
  # fresha-menu.auto.tfvars.json by scripts/render_salon_config.py: the real
  # menu is 49KB, far over Lambda's 4KB limit for environment variables.
  lambda_build_dir = "${path.module}/../build/bot"
}

# Ops alerts (alarms, listen-mode notices) go to the topic owned by the menu
# sync stack, the first one deployed; read its ARN from that state.
data "terraform_remote_state" "menu_sync" {
  backend = "s3"
  config = {
    bucket = "tlg-automation-terraform-state"
    key    = "tlg-automation/${var.environment}/menu-sync.tfstate"
    region = var.aws_region
  }
}

locals {
  ops_topic_arn = data.terraform_remote_state.menu_sync.outputs.ops_topic_arn
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# Secrets: one per channel (its app's secret, the page token, the webhook
# verify token). Written by the deploy pipeline from GitHub environment
# secrets, read by the Lambda at run time.
# ---------------------------------------------------------------------------

resource "random_password" "verify_token" {
  for_each = local.channels
  length   = 32
  special  = false
}

resource "aws_secretsmanager_secret" "meta" {
  for_each                = local.channels
  name                    = "${local.name}/meta/${each.key}"
  description             = "Meta app ${local.meta_app_ids[each.key]} (${each.key}): app secret, page token, webhook verify token"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "meta" {
  for_each  = local.channels
  secret_id = aws_secretsmanager_secret.meta[each.key].id
  secret_string = jsonencode({
    app_id       = local.meta_app_ids[each.key]
    app_secret   = each.key == "messenger" ? var.meta_messenger_app_secret : var.meta_instagram_app_secret
    page_token   = var.meta_page_token
    verify_token = random_password.verify_token[each.key].result
  })
}

# ---------------------------------------------------------------------------
# State: one table for both channels, keyed by the sender's Meta id
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
# Escalation: Jess, in shadow and live modes
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

# The team's Telegram group gets the one-liner for every hand-over. The token
# sits in Secrets Manager; the group's chat id is discovered by the Lambda and
# cached here, so Terraform never needs to know it (ignore_changes on value).
locals {
  telegram_enabled = var.telegram_bot_token != ""
}

resource "aws_secretsmanager_secret" "telegram" {
  count                   = local.telegram_enabled ? 1 : 0
  name                    = "${local.name}/telegram"
  description             = "Telegram bot token for the team's hand-over group"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "telegram" {
  count         = local.telegram_enabled ? 1 : 0
  secret_id     = aws_secretsmanager_secret.telegram[0].id
  secret_string = jsonencode({ bot_token = var.telegram_bot_token })
}

resource "aws_ssm_parameter" "telegram_chat_id" {
  count = local.telegram_enabled ? 1 : 0
  name  = "/tlg/${var.environment}/telegram/chat_id"
  type  = "String"
  value = var.telegram_chat_id != "" ? var.telegram_chat_id : "unset"

  lifecycle {
    ignore_changes = [value]
  }
}

# The Fresha dashboard session the bot books with. Fresha's login is one-time
# codes, so no pipeline can produce this: a person runs
# scripts/fresha_session.py, which creates or updates the SecureString
# parameter below with {"cookie", "expires_at", ...}. The script owns the
# parameter (so it can run before or after any deploy); Terraform only names
# it and lets the bot read it. The bot reads it at run time, so a refresh
# never needs a deploy.
locals {
  fresha_session_param = "/tlg/${var.environment}/fresha/session"
  fresha_session_arn   = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.fresha_session_param}"
}

data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

# ---------------------------------------------------------------------------
# Lambdas
# ---------------------------------------------------------------------------

data "archive_file" "bot" {
  type        = "zip"
  source_dir  = local.lambda_build_dir
  output_path = "${path.module}/../build/bot.zip"
}

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
  for_each           = local.channels
  name               = "${local.name}-${each.key}-bot"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "bot" {
  for_each = local.channels

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.bot[each.key].arn}:*"]
  }

  statement {
    sid       = "State"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.conversations.arn]
  }

  statement {
    sid       = "Notify"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.escalations.arn, local.ops_topic_arn]
  }

  statement {
    sid       = "Secrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = concat([aws_secretsmanager_secret.meta[each.key].arn], aws_secretsmanager_secret.telegram[*].arn)
  }

  dynamic "statement" {
    for_each = local.telegram_enabled ? [1] : []
    content {
      sid       = "TelegramChatId"
      actions   = ["ssm:GetParameter", "ssm:PutParameter"]
      resources = [aws_ssm_parameter.telegram_chat_id[0].arn]
    }
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

  # Claude Platform on AWS: POST /v1/messages on this workspace only. Not
  # needed in simple mode, so only granted once the workspace id is known.
  # Reference: platform.claude.com/docs/en/api/claude-platform-on-aws-iam-actions
  dynamic "statement" {
    for_each = var.anthropic_aws_workspace_id == "" ? [] : [1]
    content {
      sid       = "Claude"
      actions   = ["aws-external-anthropic:CreateInference"]
      resources = ["arn:aws:aws-external-anthropic:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workspace/${var.anthropic_aws_workspace_id}"]
    }
  }

  # The SDK first swaps the role's credentials for a web identity token
  # tagged with the workspace (outbound web identity federation, enabled on
  # the account 2026-10-20). Without both actions the call fails 403 before
  # it reaches the workspace; the docs do not list them, the 403 messages do.
  dynamic "statement" {
    for_each = var.anthropic_aws_workspace_id == "" ? [] : [1]
    content {
      sid       = "ClaudeWebIdentityToken"
      actions   = ["sts:GetWebIdentityToken", "sts:TagGetWebIdentityToken"]
      resources = ["arn:aws:sts::${data.aws_caller_identity.current.account_id}:self"]
    }
  }
}

resource "aws_iam_role_policy" "bot" {
  for_each = local.channels
  name     = "bot"
  role     = aws_iam_role.bot[each.key].id
  policy   = data.aws_iam_policy_document.bot[each.key].json
}

resource "aws_cloudwatch_log_group" "bot" {
  for_each          = local.channels
  name              = "/aws/lambda/${local.name}-${each.key}-bot"
  retention_in_days = 30
}

resource "aws_lambda_function" "bot" {
  for_each         = local.channels
  function_name    = "${local.name}-${each.key}-bot"
  description      = "Answers ${each.key} DMs for the salon; invoked by Meta's webhook on every message (mode: ${var.bot_mode})"
  role             = aws_iam_role.bot[each.key].arn
  runtime          = "python3.12"
  handler          = "bot.handler.lambda_handler"
  filename         = data.archive_file.bot.output_path
  source_code_hash = data.archive_file.bot.output_base64sha256
  timeout          = 60
  memory_size      = 512
  architectures    = ["arm64"]

  environment {
    variables = {
      CHANNEL                    = each.key
      BOT_MODE                   = var.bot_mode
      MESSAGE_TEST_MODE          = tostring(var.message_test_mode)
      MESSAGE_TEST_TRIGGER       = var.message_test_trigger
      CARMEN_WHATSAPP            = var.carmen_whatsapp
      SOPHIE_WHATSAPP            = var.sophie_whatsapp
      REPLY_DELAY_SECONDS        = tostring(var.reply_delay_seconds)
      SALON_CONFIG_PATH          = "/var/task/bot/salon_config.json"
      PERSONA_PATH               = "/var/task/bot/persona"
      TELEGRAM_SECRET_ARN        = local.telegram_enabled ? aws_secretsmanager_secret.telegram[0].arn : ""
      TELEGRAM_CHAT_ID_PARAM     = local.telegram_enabled ? aws_ssm_parameter.telegram_chat_id[0].name : ""
      TELEGRAM_CHAT_ID           = var.telegram_chat_id
      FRESHA_SESSION_PARAM       = local.fresha_session_param
      CONVERSATIONS_TABLE        = aws_dynamodb_table.conversations.name
      ESCALATION_TOPIC_ARN       = aws_sns_topic.escalations.arn
      OPS_TOPIC_ARN              = local.ops_topic_arn
      META_SECRET_ARN            = aws_secretsmanager_secret.meta[each.key].arn
      META_PAGE_ID               = var.meta_page_id
      CLAUDE_MODEL               = var.claude_model
      CLAUDE_EFFORT              = var.claude_effort
      ANTHROPIC_AWS_WORKSPACE_ID = var.anthropic_aws_workspace_id
      LOG_LEVEL                  = "INFO"
    }
  }

  tags = {
    Component = "${each.key}-bot"
  }

  depends_on = [aws_cloudwatch_log_group.bot]
}

# ---------------------------------------------------------------------------
# Webhook endpoint: one API, one route per channel
#   GET  /webhook/<channel>  Meta's verification handshake
#   POST /webhook/<channel>  message events
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "webhook" {
  name          = "${local.name}-webhook"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "bot" {
  for_each               = local.channels
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.bot[each.key].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "verify" {
  for_each  = local.channels
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "GET /webhook/${each.key}"
  target    = "integrations/${aws_apigatewayv2_integration.bot[each.key].id}"
}

resource "aws_apigatewayv2_route" "events" {
  for_each  = local.channels
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook/${each.key}"
  target    = "integrations/${aws_apigatewayv2_integration.bot[each.key].id}"
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
  for_each      = local.channels
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.bot[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# Alarms: a handler error on either bot goes to the ops topic
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "bot_errors" {
  for_each            = local.channels
  alarm_name          = "${local.name}-${each.key}-bot-errors"
  alarm_description   = "The ${each.key} bot failed while handling a message."
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
    FunctionName = aws_lambda_function.bot[each.key].function_name
  }
}
