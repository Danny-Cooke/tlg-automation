output "site_bucket" {
  description = "Sync academy/web here after every apply."
  value       = aws_s3_bucket.site.bucket
}

output "files_bucket" {
  description = "Upload the manual and handouts here under <course_id>/; course.json names the keys."
  value       = aws_s3_bucket.files.bucket
}

output "cloudfront_distribution_id" {
  description = "For the cache invalidation after a sync."
  value       = aws_cloudfront_distribution.site.id
}

output "cloudfront_domain" {
  description = "The site's CloudFront host name. The Krystal CNAME for the academy host points here."
  value       = aws_cloudfront_distribution.site.domain_name
}

output "site_url" {
  description = "Where the academy is served right now (custom domain once academy_domain_ready is true)."
  value       = local.site_url
}

output "certificate_validation_record" {
  description = "Add this CNAME in Krystal's Zone Editor, then set TLG_ACADEMY_DOMAIN_READY=true and deploy again."
  value = local.has_domain ? {
    for o in aws_acm_certificate.site[0].domain_validation_options : o.domain_name => {
      name  = o.resource_record_name
      type  = o.resource_record_type
      value = o.resource_record_value
    }
  } : {}
}

output "domain_record" {
  description = "The second Krystal record: the academy host name as a CNAME to CloudFront."
  value = local.has_domain ? {
    name  = var.academy_domain
    type  = "CNAME"
    value = aws_cloudfront_distribution.site.domain_name
  } : {}
}

output "web_config" {
  description = "Written to academy/web/config.js by the deploy workflow; everything the browser app needs."
  value = {
    region               = var.aws_region
    userPoolId           = aws_cognito_user_pool.students.id
    clientId             = aws_cognito_user_pool_client.web.id
    authDomain           = "${aws_cognito_user_pool_domain.students.domain}.auth.${var.aws_region}.amazoncognito.com"
    apiBase              = aws_apigatewayv2_api.academy.api_endpoint
    siteUrl              = local.site_url
    accreditationPending = var.academy_accreditation_pending
    contactEmail         = var.academy_contact_email
    supportPhone         = var.academy_support_phone
  }
}
