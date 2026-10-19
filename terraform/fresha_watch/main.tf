# ---------------------------------------------------------------------------
# Fresha watch: text someone when Fresha's public pages change shape.
#
# Hourly at half past, 07:30 to 22:30 London time, between menu sync runs.
# Loads the venue page and the booking flow the way the menu sync does,
# records the shape of the parts the sync reads, and compares with the
# previous run in Parameter Store. A page that breaks, recovers or changes
# shape sends an SMS through SNS to alert_phone_numbers and a fuller email to
# the ops topic. Steady state is quiet. Invoke with {"dry_run": true} to see
# the result without saving or sending.
#
# The ops topic belongs to the menu sync stack; this one reads its ARN from
# that stack's state.
# ---------------------------------------------------------------------------

locals {
  name = "${var.name_prefix}-${var.environment}"

  # Populated by `scripts/build_lambda.sh fresha_watch menu_sync` before
  # terraform apply (the watch reuses the menu sync's Fresha reader).
  lambda_build_dir = "${path.module}/../../build/fresha_watch"
}

data "archive_file" "fresha_watch" {
  type        = "zip"
  source_dir  = local.lambda_build_dir
  output_path = "${path.module}/../../build/fresha_watch.zip"
}

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

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# Previous run's findings and shapes. Written by the Lambda, so Terraform
# only creates it and then leaves the value alone.
resource "aws_ssm_parameter" "state" {
  name        = "/${var.name_prefix}/${var.environment}/fresha-watch/state"
  description = "Fresha watch: last run's failing checks and page shapes. Owned by the Lambda."
  type        = "String"
  tier        = "Intelligent-Tiering"
  value       = "{}"

  lifecycle {
    ignore_changes = [value]
  }
}

# ---------------------------------------------------------------------------
# Lambda
# ---------------------------------------------------------------------------

resource "aws_iam_role" "fresha_watch" {
  name               = "${local.name}-fresha-watch"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "fresha_watch" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.fresha_watch.arn}:*"]
  }

  statement {
    sid       = "State"
    actions   = ["ssm:GetParameter", "ssm:PutParameter"]
    resources = [aws_ssm_parameter.state.arn]
  }

  statement {
    sid       = "Email"
    actions   = ["sns:Publish"]
    resources = [local.ops_topic_arn]
  }

  # Texting a phone number directly has no ARN to scope to, so SNS requires
  # "*" here (and there is no condition key that narrows Publish to SMS).
  # It means this role could publish to any topic in the account; the only
  # code it runs is in this repo.
  statement {
    sid       = "Text"
    actions   = ["sns:Publish"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "fresha_watch" {
  name   = "fresha-watch"
  role   = aws_iam_role.fresha_watch.id
  policy = data.aws_iam_policy_document.fresha_watch.json
}

resource "aws_cloudwatch_log_group" "fresha_watch" {
  name              = "/aws/lambda/${local.name}-fresha-watch"
  retention_in_days = 30
}

resource "aws_lambda_function" "fresha_watch" {
  function_name    = "${local.name}-fresha-watch"
  description      = "Checks Fresha's public pages and texts when one breaks, recovers or changes shape"
  role             = aws_iam_role.fresha_watch.arn
  runtime          = "python3.12"
  handler          = "fresha_watch.handler.lambda_handler"
  filename         = data.archive_file.fresha_watch.output_path
  source_code_hash = data.archive_file.fresha_watch.output_base64sha256
  timeout          = 120
  memory_size      = 256
  architectures    = ["arm64"]

  environment {
    variables = {
      FRESHA_VENUE_URL    = var.salon.venue_url
      FRESHA_GENERAL_LINK = var.salon.general_booking_link
      SALON_NAME          = var.salon.name
      STATE_PARAMETER     = aws_ssm_parameter.state.name
      OPS_TOPIC_ARN       = local.ops_topic_arn
      ALERT_PHONE_NUMBERS = join(",", var.alert_phone_numbers)
      LOG_LEVEL           = "INFO"
    }
  }

  tags = {
    Component = "fresha-watch"
  }

  depends_on = [aws_cloudwatch_log_group.fresha_watch]
}

# ---------------------------------------------------------------------------
# Schedule, in London time
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.name}-fresha-watch-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.fresha_watch.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "invoke-fresha-watch"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "fresha_watch" {
  name                         = "${local.name}-fresha-watch"
  description                  = "Fresha watch, hourly at half past, 07:30 to 22:30 London time"
  schedule_expression          = var.fresha_watch_schedule
  schedule_expression_timezone = var.fresha_watch_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.fresha_watch.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ source = "schedule" })

    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}

# The Lambda itself failing (not a Fresha finding) goes to the ops email.
resource "aws_cloudwatch_metric_alarm" "fresha_watch_errors" {
  alarm_name          = "${local.name}-fresha-watch-errors"
  alarm_description   = "The Fresha watch Lambda failed to run, so nobody is watching Fresha."
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
    FunctionName = aws_lambda_function.fresha_watch.function_name
  }
}
