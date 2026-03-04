# Get existing Route 53 hosted zone
data "aws_route53_zone" "main" {
  name         = var.domain_name
  private_zone = false
}

# ACM Certificate for the subdomain
resource "aws_acm_certificate" "main" {
  provider          = aws.us_east_1  # Must be in us-east-1 for CloudFront
  domain_name       = local.full_domain
  validation_method = "DNS"

  subject_alternative_names = [
    "api.${local.full_domain}",
    "*.${local.full_domain}"
  ]

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = "GaryEatsFloyd Certificate"
  }
}

# DNS validation records
resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.main.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.main.zone_id
}

# Certificate validation
resource "aws_acm_certificate_validation" "main" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}

# A record for the main website (CloudFront)
resource "aws_route53_record" "website" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.full_domain
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.website.domain_name
    zone_id                = aws_cloudfront_distribution.website.hosted_zone_id
    evaluate_target_health = false
  }
}

# AAAA record for IPv6
resource "aws_route53_record" "website_ipv6" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.full_domain
  type    = "AAAA"

  alias {
    name                   = aws_cloudfront_distribution.website.domain_name
    zone_id                = aws_cloudfront_distribution.website.hosted_zone_id
    evaluate_target_health = false
  }
}

# A record for API subdomain
resource "aws_route53_record" "api" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "api.${local.full_domain}"
  type    = "A"

  alias {
    name                   = aws_apigatewayv2_domain_name.api.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.api.domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}
