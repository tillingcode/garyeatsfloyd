# CloudFront Origin Access Control for website bucket
resource "aws_cloudfront_origin_access_control" "website" {
  name                              = "garyeatsfloyd-website-oac"
  description                       = "OAC for GaryEatsFloyd website"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# CloudFront Origin Access Control for processed videos bucket
resource "aws_cloudfront_origin_access_control" "videos" {
  name                              = "garyeatsfloyd-videos-oac"
  description                       = "OAC for GaryEatsFloyd processed videos"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# CloudFront Distribution
resource "aws_cloudfront_distribution" "website" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = [local.full_domain]
  price_class         = "PriceClass_100"
  comment             = "GaryEatsFloyd Website Distribution"

  # Website bucket origin
  origin {
    domain_name              = aws_s3_bucket.website.bucket_regional_domain_name
    origin_id                = "S3-Website"
    origin_access_control_id = aws_cloudfront_origin_access_control.website.id
  }

  # Processed videos bucket origin
  origin {
    domain_name              = aws_s3_bucket.processed_videos.bucket_regional_domain_name
    origin_id                = "S3-Videos"
    origin_access_control_id = aws_cloudfront_origin_access_control.videos.id
  }

  # API Gateway origin
  origin {
    domain_name = replace(aws_apigatewayv2_api.main.api_endpoint, "https://", "")
    origin_id   = "API-Gateway"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Default behavior - static website
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "S3-Website"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 3600
    max_ttl     = 86400
  }

  # Videos behavior
  ordered_cache_behavior {
    path_pattern           = "/videos/*"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "S3-Videos"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 86400
    max_ttl     = 604800
  }

  # API behavior
  ordered_cache_behavior {
    path_pattern           = "/api/*"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "API-Gateway"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = true
      headers      = ["Authorization", "Origin", "Accept"]
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
  }

  # Custom error responses for SPA
  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate.main.arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  depends_on = [aws_acm_certificate_validation.main]

  tags = {
    Name = "GaryEatsFloyd Website"
  }
}
