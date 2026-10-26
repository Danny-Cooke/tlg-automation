# ---------------------------------------------------------------------------
# TLG Academy: the school's online home (plan job 17, docs/academy.md).
#
# A static site on S3 behind CloudFront, Cognito's hosted UI for student
# login, an HTTP API with one Lambda for profiles, enrolment requests,
# Jess's approvals and lesson progress, one DynamoDB table, and a private
# bucket for the manual. Independent of the bot stacks.
#
# The custom domain comes up in two deploys: the first (academy_domain_ready
# = false) creates the certificate and outputs the CNAME records for
# Krystal's DNS; the second, after those records exist, validates the
# certificate and attaches the domain to CloudFront.
# ---------------------------------------------------------------------------

locals {
  name        = "${var.name_prefix}-${var.environment}"
  admin_group = "admins"
  has_domain  = var.academy_domain != ""
  use_domain  = local.has_domain && var.academy_domain_ready
  site_url    = local.use_domain ? "https://${var.academy_domain}" : "https://${aws_cloudfront_distribution.site.domain_name}"

  # Populated by `scripts/build_lambda.sh academy` before terraform apply.
  lambda_build_dir = "${path.module}/../../build/academy"

  callback_urls = compact([
    "https://${aws_cloudfront_distribution.site.domain_name}/",
    local.has_domain ? "https://${var.academy_domain}/" : "",
    var.academy_local_dev_url != "" ? "${var.academy_local_dev_url}/" : "",
  ])
  cors_origins = compact([
    "https://${aws_cloudfront_distribution.site.domain_name}",
    local.has_domain ? "https://${var.academy_domain}" : "",
    var.academy_local_dev_url,
  ])
}

data "aws_caller_identity" "current" {}

data "archive_file" "academy" {
  type        = "zip"
  source_dir  = local.lambda_build_dir
  output_path = "${path.module}/../../build/academy.zip"
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

# ---------------------------------------------------------------------------
# The site: private bucket, CloudFront with origin access control
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "site" {
  bucket = "${local.name}-academy-site-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${local.name}-academy-site"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_iam_policy_document" "site_bucket" {
  statement {
    sid       = "CloudFrontRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site_bucket.json
}

# Certificate in us-east-1, validated by a CNAME the owner adds in Krystal.
resource "aws_acm_certificate" "site" {
  count             = local.has_domain ? 1 : 0
  provider          = aws.us_east_1
  domain_name       = var.academy_domain
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "site" {
  count                   = local.use_domain ? 1 : 0
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.site[0].arn
  validation_record_fqdns = [for o in aws_acm_certificate.site[0].domain_validation_options : o.resource_record_name]

  timeouts {
    create = "20m"
  }
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "${local.name} academy"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  http_version        = "http2and3"
  is_ipv6_enabled     = true
  aliases             = local.use_domain ? [var.academy_domain] : []

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "site"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "site"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    # Managed policies: CachingOptimized, and a response-headers policy with
    # HSTS, nosniff, frame denial and a referrer policy.
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6"
    response_headers_policy_id = aws_cloudfront_response_headers_policy.site.id
  }

  # Missing keys come back from S3 as 403; serve the app so hash routes work.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }
  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 10
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = local.use_domain ? false : true
    acm_certificate_arn            = local.use_domain ? aws_acm_certificate_validation.site[0].certificate_arn : null
    ssl_support_method             = local.use_domain ? "sni-only" : null
    minimum_protocol_version       = local.use_domain ? "TLSv1.2_2021" : "TLSv1"
  }
}

resource "aws_cloudfront_response_headers_policy" "site" {
  name = "${local.name}-academy-headers"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = false
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
}

# ---------------------------------------------------------------------------
# Private files: the manual and handouts, served by presigned URL to
# approved learners only.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "files" {
  bucket = "${local.name}-academy-files-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "files" {
  bucket                  = aws_s3_bucket.files.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "files" {
  bucket = aws_s3_bucket.files.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ---------------------------------------------------------------------------
# Students: Cognito user pool with the hosted UI
# ---------------------------------------------------------------------------

resource "aws_cognito_user_pool" "students" {
  name                     = "${local.name}-academy"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  deletion_protection      = "ACTIVE"

  password_policy {
    minimum_length                   = 10
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "name"
    attribute_data_type = "String"
    required            = true
    mutable             = true
    string_attribute_constraints {
      min_length = 1
      max_length = 100
    }
  }

  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "Your TLG Academy verification code"
    email_message        = "Welcome to The Looking Glass Beauty School academy. Your verification code is {####}."
  }

  user_pool_add_ons {
    advanced_security_mode = "OFF"
  }

  lambda_config {
    post_confirmation = aws_lambda_function.triggers.arn
  }
}

resource "aws_cognito_user_pool_domain" "students" {
  domain       = "${local.name}-academy"
  user_pool_id = aws_cognito_user_pool.students.id
}

resource "aws_cognito_user_group" "admins" {
  name         = local.admin_group
  user_pool_id = aws_cognito_user_pool.students.id
  description  = "Can approve and reject course access. Jess."
}

resource "aws_cognito_user_pool_client" "web" {
  name                                 = "${local.name}-academy-web"
  user_pool_id                         = aws_cognito_user_pool.students.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = local.callback_urls
  logout_urls                          = local.callback_urls
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  access_token_validity                = 60
  id_token_validity                    = 60
  refresh_token_validity               = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

# ---------------------------------------------------------------------------
# Data: one table. PK/SK plus an index for the admin's pending list.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "academy" {
  name         = "${local.name}-academy"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
  attribute {
    name = "GSI1PK"
    type = "S"
  }
  attribute {
    name = "GSI1SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ---------------------------------------------------------------------------
# Lambdas: the API, and the Cognito post-confirmation trigger that puts the
# admin emails into the admins group.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name}-academy-api"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "triggers" {
  name              = "/aws/lambda/${local.name}-academy-triggers"
  retention_in_days = 30
}

resource "aws_iam_role" "api" {
  name               = "${local.name}-academy-api"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }
  statement {
    sid       = "Table"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.academy.arn, "${aws_dynamodb_table.academy.arn}/index/*"]
  }
  statement {
    sid       = "Files"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.files.arn}/*"]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "academy-api"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_lambda_function" "api" {
  function_name    = "${local.name}-academy-api"
  description      = "TLG Academy API: profiles, course access requests, approvals, lesson progress, file links"
  role             = aws_iam_role.api.arn
  runtime          = "python3.12"
  handler          = "academy.handler.lambda_handler"
  filename         = data.archive_file.academy.output_path
  source_code_hash = data.archive_file.academy.output_base64sha256
  timeout          = 15
  memory_size      = 256
  architectures    = ["arm64"]

  environment {
    variables = {
      TABLE_NAME   = aws_dynamodb_table.academy.name
      FILES_BUCKET = aws_s3_bucket.files.bucket
      ADMIN_EMAILS = var.academy_admin_emails
      LOG_LEVEL    = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.api]
}

resource "aws_iam_role" "triggers" {
  name               = "${local.name}-academy-triggers"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "triggers" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.triggers.arn}:*"]
  }
  statement {
    sid       = "Groups"
    actions   = ["cognito-idp:AdminAddUserToGroup"]
    resources = ["arn:aws:cognito-idp:${var.aws_region}:${data.aws_caller_identity.current.account_id}:userpool/*"]
  }
}

resource "aws_iam_role_policy" "triggers" {
  name   = "academy-triggers"
  role   = aws_iam_role.triggers.id
  policy = data.aws_iam_policy_document.triggers.json
}

resource "aws_lambda_function" "triggers" {
  function_name    = "${local.name}-academy-triggers"
  description      = "TLG Academy Cognito trigger: admin emails join the admins group on sign-up"
  role             = aws_iam_role.triggers.arn
  runtime          = "python3.12"
  handler          = "academy.triggers.post_confirmation"
  filename         = data.archive_file.academy.output_path
  source_code_hash = data.archive_file.academy.output_base64sha256
  timeout          = 10
  memory_size      = 128
  architectures    = ["arm64"]

  environment {
    variables = {
      ADMIN_EMAILS = var.academy_admin_emails
      ADMIN_GROUP  = local.admin_group # not the group resource: that would be a cycle through the pool
      LOG_LEVEL    = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.triggers]
}

resource "aws_lambda_permission" "triggers_cognito" {
  statement_id  = "AllowCognito"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.triggers.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.students.arn
}

# ---------------------------------------------------------------------------
# API: HTTP API, every route behind the Cognito JWT authoriser
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "academy" {
  name          = "${local.name}-academy"
  protocol_type = "HTTP"
  description   = "TLG Academy API"

  cors_configuration {
    allow_origins = local.cors_origins
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.academy.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 25
  }
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.academy.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "cognito"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.students.id}"
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.academy.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "api" {
  for_each = toset([
    "GET /me",
    "POST /courses/{course_id}/request",
    "POST /courses/{course_id}/lessons/{lesson_id}/complete",
    "GET /courses/{course_id}/files/{file_id}",
    "GET /admin/requests",
    "POST /admin/requests/{user_id}/{course_id}",
  ])
  api_id             = aws_apigatewayv2_api.academy.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.api.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_lambda_permission" "api_apigw" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.academy.execution_arn}/*/*"
}
