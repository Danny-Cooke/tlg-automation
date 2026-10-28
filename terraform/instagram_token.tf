# ---------------------------------------------------------------------------
# Instagram on the Instagram Login route (plan job 18, 2026-10-27).
#
# The Instagram bot sends and reads with the salon account's own token
# rather than a Page token, so Standard Access reaches the public and no
# App Review is needed. Meta issues that token for 60 days; this Lambda
# renews it weekly, re-asserts the account's webhook subscription, and
# warns ops and the team group when a renewal fails. The token lives in its
# own secret, which Terraform does not manage: the user creates it once
# with the CLI from the token the Meta console issues (docs/setup.md
# section 1 step 6), and the Lambda rewrites it on every renewal, so a
# deploy can never put a stale token back. Everything here exists only
# once the Instagram app pair (var.meta_instagram_login_*) is set.
# ---------------------------------------------------------------------------

locals {
  # Keyed on the id, not the secret: a sensitive value in the switch would
  # make every output that mentions it sensitive too.
  instagram_login = var.meta_instagram_login_app_id != ""

  # Created by hand, so only the name is known here; Secrets Manager adds a
  # random suffix to the ARN, hence the wildcard in the IAM resources.
  instagram_token_secret_name = "${local.name}/meta/instagram-token"
  instagram_token_secret_arn  = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${local.name}/meta/instagram-token-*"
}

resource "aws_iam_role" "instagram_token" {
  count              = local.instagram_login ? 1 : 0
  name               = "${local.name}-instagram-token"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "instagram_token" {
  count = local.instagram_login ? 1 : 0

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.instagram_token[0].arn}:*"]
  }

  statement {
    sid       = "Token"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
    resources = [local.instagram_token_secret_arn]
  }

  statement {
    sid       = "Ops"
    actions   = ["sns:Publish"]
    resources = [local.ops_topic_arn]
  }

  dynamic "statement" {
    for_each = local.telegram_enabled ? [1] : []
    content {
      sid       = "Telegram"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [aws_secretsmanager_secret.telegram[0].arn]
    }
  }

  dynamic "statement" {
    for_each = local.telegram_enabled ? [1] : []
    content {
      sid       = "TelegramChatId"
      actions   = ["ssm:GetParameter", "ssm:PutParameter"]
      resources = [aws_ssm_parameter.telegram_chat_id[0].arn]
    }
  }
}

resource "aws_iam_role_policy" "instagram_token" {
  count  = local.instagram_login ? 1 : 0
  name   = "instagram-token"
  role   = aws_iam_role.instagram_token[0].id
  policy = data.aws_iam_policy_document.instagram_token[0].json
}

resource "aws_cloudwatch_log_group" "instagram_token" {
  count             = local.instagram_login ? 1 : 0
  name              = "/aws/lambda/${local.name}-instagram-token"
  retention_in_days = 30
}

resource "aws_lambda_function" "instagram_token" {
  count            = local.instagram_login ? 1 : 0
  function_name    = "${local.name}-instagram-token"
  description      = "Renews the salon Instagram account's token (60-day) and re-asserts its webhook subscription; weekly and after every deploy"
  role             = aws_iam_role.instagram_token[0].arn
  runtime          = "python3.12"
  handler          = "bot.ig_token.lambda_handler"
  filename         = data.archive_file.bot.output_path
  source_code_hash = data.archive_file.bot.output_base64sha256
  timeout          = 60
  memory_size      = 256
  architectures    = ["arm64"]

  environment {
    variables = {
      META_TOKEN_SECRET_ARN  = local.instagram_token_secret_name
      OPS_TOPIC_ARN          = local.ops_topic_arn
      TELEGRAM_SECRET_ARN    = local.telegram_enabled ? aws_secretsmanager_secret.telegram[0].arn : ""
      TELEGRAM_CHAT_ID_PARAM = local.telegram_enabled ? aws_ssm_parameter.telegram_chat_id[0].name : ""
      TELEGRAM_CHAT_ID       = var.telegram_chat_id
      IG_TOKEN_WARN_DAYS     = tostring(var.instagram_token_warn_days)
      LOG_LEVEL              = "INFO"
    }
  }

  tags = {
    Component = "instagram-bot"
  }

  depends_on = [aws_cloudwatch_log_group.instagram_token]
}

resource "aws_cloudwatch_metric_alarm" "instagram_token_errors" {
  count               = local.instagram_login ? 1 : 0
  alarm_name          = "${local.name}-instagram-token-errors"
  alarm_description   = "The Instagram token renewal crashed; the token dies 60 days after its last renewal"
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
    FunctionName = aws_lambda_function.instagram_token[0].function_name
  }
}

resource "aws_iam_role" "instagram_token_scheduler" {
  count              = local.instagram_login ? 1 : 0
  name               = "${local.name}-instagram-token-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "instagram_token_scheduler" {
  count = local.instagram_login ? 1 : 0

  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.instagram_token[0].arn]
  }
}

resource "aws_iam_role_policy" "instagram_token_scheduler" {
  count  = local.instagram_login ? 1 : 0
  name   = "invoke-instagram-token"
  role   = aws_iam_role.instagram_token_scheduler[0].id
  policy = data.aws_iam_policy_document.instagram_token_scheduler[0].json
}

resource "aws_scheduler_schedule" "instagram_token" {
  count                        = local.instagram_login ? 1 : 0
  name                         = "${local.name}-instagram-token"
  description                  = "Weekly renewal of the salon Instagram account's token"
  schedule_expression          = var.instagram_token_schedule
  schedule_expression_timezone = var.instagram_token_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.instagram_token[0].arn
    role_arn = aws_iam_role.instagram_token_scheduler[0].arn
    input    = jsonencode({ source = "schedule" })
  }
}
