# ---------------------------------------------------------------------------
# Menu sync: keep staff, services and who-does-what in step with Fresha.
#
# Every two hours in salon hours, and on demand. Reads Fresha's public booking data (no login),
# compares with terraform/fresha-menu.auto.tfvars.json on the base branch,
# and when they differ pushes the new file to a "menu-sync" branch and opens
# a pull request with the GitHub token from Parameter Store. The ops topic
# gets a summary. Invoke with {"dry_run": true} to see the diff only.
# ---------------------------------------------------------------------------

# Written by the deploy pipeline from the GitHub environment secret. The
# value is in Terraform state, which is why the state bucket is private.
resource "aws_ssm_parameter" "github_pat" {
  name        = "/${var.name_prefix}/${var.environment}/github/pat"
  description = "Fine-grained GitHub PAT: contents + pull requests on ${var.github_repo}"
  type        = "SecureString"
  value       = var.github_pat
}

data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

resource "aws_iam_role" "menu_sync" {
  name               = "${local.name}-menu-sync"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "menu_sync" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.menu_sync.arn}:*"]
  }

  statement {
    sid       = "Token"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.github_pat.arn]
  }

  statement {
    sid       = "Decrypt"
    actions   = ["kms:Decrypt"]
    resources = [data.aws_kms_alias.ssm.target_key_arn]
  }

  statement {
    sid       = "Alert"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.ops.arn]
  }
}

resource "aws_iam_role_policy" "menu_sync" {
  name   = "menu-sync"
  role   = aws_iam_role.menu_sync.id
  policy = data.aws_iam_policy_document.menu_sync.json
}

resource "aws_cloudwatch_log_group" "menu_sync" {
  name              = "/aws/lambda/${local.name}-menu-sync"
  retention_in_days = 30
}

resource "aws_lambda_function" "menu_sync" {
  function_name    = "${local.name}-menu-sync"
  description      = "Reads Fresha's staff and service menu and opens a PR when the Terraform menu file is out of date"
  role             = aws_iam_role.menu_sync.arn
  runtime          = "python3.12"
  handler          = "menu_sync.handler.lambda_handler"
  filename         = data.archive_file.bot.output_path
  source_code_hash = data.archive_file.bot.output_base64sha256
  timeout          = 300
  memory_size      = 256
  architectures    = ["arm64"]

  environment {
    variables = {
      FRESHA_VENUE_URL     = var.salon.venue_url
      GITHUB_REPO          = var.github_repo
      GITHUB_BASE_BRANCH   = var.github_base_branch
      GITHUB_PAT_PARAMETER = aws_ssm_parameter.github_pat.name
      MENU_FILE_PATH       = "terraform/fresha-menu.auto.tfvars.json"
      OPS_TOPIC_ARN        = aws_sns_topic.ops.arn
      LOG_LEVEL            = "INFO"
    }
  }

  tags = {
    Component = "menu-sync"
  }

  depends_on = [aws_cloudwatch_log_group.menu_sync]
}

# EventBridge Scheduler rather than a plain rule so the schedule can be in
# London time: every two hours from 07:00 to 22:00, whatever the clocks do.
resource "aws_iam_role" "menu_sync_scheduler" {
  name               = "${local.name}-menu-sync-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "menu_sync_scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.menu_sync.arn]
  }
}

resource "aws_iam_role_policy" "menu_sync_scheduler" {
  name   = "invoke-menu-sync"
  role   = aws_iam_role.menu_sync_scheduler.id
  policy = data.aws_iam_policy_document.menu_sync_scheduler.json
}

resource "aws_scheduler_schedule" "menu_sync" {
  name                         = "${local.name}-menu-sync"
  description                  = "Fresha menu sync, every two hours 07:00 to 22:00 London time"
  schedule_expression          = var.menu_sync_schedule
  schedule_expression_timezone = var.menu_sync_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.menu_sync.arn
    role_arn = aws_iam_role.menu_sync_scheduler.arn
    input    = jsonencode({ source = "schedule" })

    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "menu_sync_errors" {
  alarm_name          = "${local.name}-menu-sync-errors"
  alarm_description   = "The Fresha menu sync failed. Fresha may have changed its booking page or query."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.ops.arn]

  dimensions = {
    FunctionName = aws_lambda_function.menu_sync.function_name
  }
}
