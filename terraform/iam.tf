# IAM Role for YouTube Scanner Lambda
resource "aws_iam_role" "youtube_scanner" {
  name = "garyeatsfloyd-youtube-scanner-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "youtube_scanner" {
  name = "garyeatsfloyd-youtube-scanner-policy"
  role = aws_iam_role.youtube_scanner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.videos.arn,
          "${aws_dynamodb_table.videos.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.youtube_api_key.arn
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = aws_lambda_function.video_downloader.arn
      }
    ]
  })
}

# IAM Role for Video Downloader Lambda
resource "aws_iam_role" "video_downloader" {
  name = "garyeatsfloyd-video-downloader-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "video_downloader" {
  name = "garyeatsfloyd-video-downloader-policy"
  role = aws_iam_role.video_downloader.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.raw_videos.arn,
          "${aws_s3_bucket.raw_videos.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem"
        ]
        Resource = [
          aws_dynamodb_table.videos.arn,
          aws_dynamodb_table.processing_jobs.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = aws_lambda_function.video_processor.arn
      }
    ]
  })
}

# IAM Role for Video Processor Lambda (Bedrock)
resource "aws_iam_role" "video_processor" {
  name = "garyeatsfloyd-video-processor-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "video_processor" {
  name = "garyeatsfloyd-video-processor-policy"
  role = aws_iam_role.video_processor.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.raw_videos.arn,
          "${aws_s3_bucket.raw_videos.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:CopyObject"
        ]
        Resource = [
          aws_s3_bucket.processed_videos.arn,
          "${aws_s3_bucket.processed_videos.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query"
        ]
        Resource = [
          aws_dynamodb_table.videos.arn,
          aws_dynamodb_table.processing_jobs.arn,
          "${aws_dynamodb_table.processing_jobs.arn}/index/*",
          aws_dynamodb_table.website_content.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:StartAsyncInvoke",
          "bedrock:GetAsyncInvoke",
          "bedrock:ListAsyncInvokes"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = aws_lambda_function.website_publisher.arn
      }
    ]
  })
}

# IAM Role for API Lambda
resource "aws_iam_role" "api_handler" {
  name = "garyeatsfloyd-api-handler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "api_handler" {
  name = "garyeatsfloyd-api-handler-policy"
  role = aws_iam_role.api_handler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.videos.arn,
          "${aws_dynamodb_table.videos.arn}/index/*",
          aws_dynamodb_table.website_content.arn,
          "${aws_dynamodb_table.website_content.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.processed_videos.arn,
          "${aws_s3_bucket.processed_videos.arn}/*"
        ]
      }
    ]
  })
}

# IAM Role for Website Publisher Lambda
resource "aws_iam_role" "website_publisher" {
  name = "garyeatsfloyd-website-publisher-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "website_publisher" {
  name = "garyeatsfloyd-website-publisher-policy"
  role = aws_iam_role.website_publisher.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.website.arn,
          "${aws_s3_bucket.website.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = [
          aws_s3_bucket.processed_videos.arn,
          "${aws_s3_bucket.processed_videos.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.videos.arn,
          "${aws_dynamodb_table.videos.arn}/index/*",
          aws_dynamodb_table.website_content.arn,
          "${aws_dynamodb_table.website_content.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "cloudfront:CreateInvalidation"
        ]
        Resource = aws_cloudfront_distribution.website.arn
      }
    ]
  })
}
