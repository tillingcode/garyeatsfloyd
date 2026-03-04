# S3 Bucket for raw video downloads from YouTube
resource "aws_s3_bucket" "raw_videos" {
  bucket = "garyeatsfloyd-raw-videos-${random_id.bucket_suffix.hex}"
}

resource "aws_s3_bucket_versioning" "raw_videos" {
  bucket = aws_s3_bucket.raw_videos.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "raw_videos" {
  bucket = aws_s3_bucket.raw_videos.id

  rule {
    id     = "cleanup-old-videos"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw_videos" {
  bucket = aws_s3_bucket.raw_videos.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# S3 Bucket for processed (Floyd-style) videos
resource "aws_s3_bucket" "processed_videos" {
  bucket = "garyeatsfloyd-processed-videos-${random_id.bucket_suffix.hex}"
}

resource "aws_s3_bucket_versioning" "processed_videos" {
  bucket = aws_s3_bucket.processed_videos.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "processed_videos" {
  bucket = aws_s3_bucket.processed_videos.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# S3 Bucket for static website hosting
resource "aws_s3_bucket" "website" {
  bucket = "garyeatsfloyd-website-${random_id.bucket_suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "website" {
  bucket = aws_s3_bucket.website.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_website_configuration" "website" {
  bucket = aws_s3_bucket.website.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "error.html"
  }
}

resource "aws_s3_bucket_cors_configuration" "website" {
  bucket = aws_s3_bucket.website.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["https://${local.full_domain}"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

# CORS for processed videos bucket (for video playback)
resource "aws_s3_bucket_cors_configuration" "processed_videos" {
  bucket = aws_s3_bucket.processed_videos.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["https://${local.full_domain}"]
    expose_headers  = ["ETag", "Content-Length"]
    max_age_seconds = 3600
  }
}

# Random suffix for globally unique bucket names
resource "random_id" "bucket_suffix" {
  byte_length = 4
}

# S3 bucket policy for CloudFront access to website bucket
resource "aws_s3_bucket_policy" "website" {
  bucket = aws_s3_bucket.website.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontAccess"
        Effect    = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.website.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.website.arn
          }
        }
      }
    ]
  })
}

# S3 bucket policy for CloudFront access to processed videos
resource "aws_s3_bucket_policy" "processed_videos" {
  bucket = aws_s3_bucket.processed_videos.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontAccess"
        Effect    = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.processed_videos.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.website.arn
          }
        }
      }
    ]
  })
}

# S3 bucket policy for CloudFront access to raw videos (thumbnails)
resource "aws_s3_bucket_policy" "raw_videos" {
  bucket = aws_s3_bucket.raw_videos.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontAccess"
        Effect    = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.raw_videos.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.website.arn
          }
        }
      }
    ]
  })
}
