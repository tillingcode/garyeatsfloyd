# Lambda Layer for common dependencies
resource "aws_lambda_layer_version" "dependencies" {
  filename            = data.archive_file.lambda_layer.output_path
  layer_name          = "garyeatsfloyd-dependencies"
  compatible_runtimes = ["python3.11"]
  source_code_hash    = data.archive_file.lambda_layer.output_base64sha256
  description         = "Common dependencies for GaryEatsFloyd lambdas"
}

# YouTube Scanner Lambda
resource "aws_lambda_function" "youtube_scanner" {
  filename         = data.archive_file.youtube_scanner.output_path
  function_name    = "garyeatsfloyd-youtube-scanner"
  role             = aws_iam_role.youtube_scanner.arn
  handler          = "handler.lambda_handler"
  source_code_hash = data.archive_file.youtube_scanner.output_base64sha256
  runtime          = "python3.11"
  timeout          = 300
  memory_size      = 512

  layers = [aws_lambda_layer_version.dependencies.arn]

  environment {
    variables = {
      VIDEOS_TABLE_NAME        = aws_dynamodb_table.videos.name
      YOUTUBE_API_KEY_SECRET   = aws_secretsmanager_secret.youtube_api_key.name
      YOUTUBE_CHANNEL_ID       = var.youtube_channel_id
      VIDEO_DOWNLOADER_FUNCTION = aws_lambda_function.video_downloader.function_name
    }
  }

  depends_on = [aws_iam_role_policy.youtube_scanner]
}

# Video Downloader Lambda
resource "aws_lambda_function" "video_downloader" {
  filename         = data.archive_file.video_downloader.output_path
  function_name    = "garyeatsfloyd-video-downloader"
  role             = aws_iam_role.video_downloader.arn
  handler          = "handler.lambda_handler"
  source_code_hash = data.archive_file.video_downloader.output_base64sha256
  runtime          = "python3.11"
  timeout          = 900  # 15 minutes for video downloads
  memory_size      = 1024

  layers = [aws_lambda_layer_version.dependencies.arn]

  environment {
    variables = {
      RAW_VIDEOS_BUCKET       = aws_s3_bucket.raw_videos.id
      VIDEOS_TABLE_NAME       = aws_dynamodb_table.videos.name
      JOBS_TABLE_NAME         = aws_dynamodb_table.processing_jobs.name
      VIDEO_PROCESSOR_FUNCTION = aws_lambda_function.video_processor.function_name
    }
  }

  depends_on = [aws_iam_role_policy.video_downloader]
}

# Video Processor Lambda (Bedrock)
resource "aws_lambda_function" "video_processor" {
  filename         = data.archive_file.video_processor.output_path
  function_name    = "garyeatsfloyd-video-processor"
  role             = aws_iam_role.video_processor.arn
  handler          = "handler.lambda_handler"
  source_code_hash = data.archive_file.video_processor.output_base64sha256
  runtime          = "python3.11"
  timeout          = 900  # 15 minutes for processing
  memory_size      = 3008

  layers = [aws_lambda_layer_version.dependencies.arn]

  environment {
    variables = {
      RAW_VIDEOS_BUCKET       = aws_s3_bucket.raw_videos.id
      PROCESSED_VIDEOS_BUCKET = aws_s3_bucket.processed_videos.id
      VIDEOS_TABLE_NAME       = aws_dynamodb_table.videos.name
      JOBS_TABLE_NAME         = aws_dynamodb_table.processing_jobs.name
      CONTENT_TABLE_NAME      = aws_dynamodb_table.website_content.name
      BEDROCK_MODEL_ID        = var.bedrock_model_id
      KEITH_FLOYD_PROMPT      = var.keith_floyd_prompt
      WEBSITE_PUBLISHER_FUNCTION = aws_lambda_function.website_publisher.function_name
    }
  }

  depends_on = [aws_iam_role_policy.video_processor]
}

# API Handler Lambda
resource "aws_lambda_function" "api_handler" {
  filename         = data.archive_file.api_handler.output_path
  function_name    = "garyeatsfloyd-api-handler"
  role             = aws_iam_role.api_handler.arn
  handler          = "handler.lambda_handler"
  source_code_hash = data.archive_file.api_handler.output_base64sha256
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 256

  layers = [aws_lambda_layer_version.dependencies.arn]

  environment {
    variables = {
      VIDEOS_TABLE_NAME       = aws_dynamodb_table.videos.name
      CONTENT_TABLE_NAME      = aws_dynamodb_table.website_content.name
      PROCESSED_VIDEOS_BUCKET = aws_s3_bucket.processed_videos.id
      CLOUDFRONT_DOMAIN       = local.full_domain
    }
  }

  depends_on = [aws_iam_role_policy.api_handler]
}

# Website Publisher Lambda
resource "aws_lambda_function" "website_publisher" {
  filename         = data.archive_file.website_publisher.output_path
  function_name    = "garyeatsfloyd-website-publisher"
  role             = aws_iam_role.website_publisher.arn
  handler          = "handler.lambda_handler"
  source_code_hash = data.archive_file.website_publisher.output_base64sha256
  runtime          = "python3.11"
  timeout          = 300
  memory_size      = 512

  layers = [aws_lambda_layer_version.dependencies.arn]

  environment {
    variables = {
      WEBSITE_BUCKET          = aws_s3_bucket.website.id
      PROCESSED_VIDEOS_BUCKET = aws_s3_bucket.processed_videos.id
      VIDEOS_TABLE_NAME       = aws_dynamodb_table.videos.name
      CONTENT_TABLE_NAME      = aws_dynamodb_table.website_content.name
      CLOUDFRONT_DISTRIBUTION_ID = aws_cloudfront_distribution.website.id
      WEBSITE_DOMAIN          = local.full_domain
    }
  }

  depends_on = [aws_iam_role_policy.website_publisher]
}

# CloudWatch Event Rule for scheduled scanning
resource "aws_cloudwatch_event_rule" "youtube_scan_schedule" {
  name                = "garyeatsfloyd-youtube-scan"
  description         = "Trigger YouTube scanner every ${var.scan_schedule_hours} hours"
  schedule_expression = "rate(${var.scan_schedule_hours} hours)"
}

resource "aws_cloudwatch_event_target" "youtube_scanner" {
  rule      = aws_cloudwatch_event_rule.youtube_scan_schedule.name
  target_id = "YouTubeScanner"
  arn       = aws_lambda_function.youtube_scanner.arn
}

resource "aws_lambda_permission" "youtube_scanner_cloudwatch" {
  statement_id  = "AllowCloudWatchInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.youtube_scanner.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.youtube_scan_schedule.arn
}

# Lambda permission for API Gateway
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

# Archive files for Lambda functions
data "archive_file" "lambda_layer" {
  type        = "zip"
  source_dir  = "${path.module}/../src/layer"
  output_path = "${path.module}/../dist/layer.zip"
}

data "archive_file" "youtube_scanner" {
  type        = "zip"
  source_dir  = "${path.module}/../src/youtube_scanner"
  output_path = "${path.module}/../dist/youtube_scanner.zip"
}

data "archive_file" "video_downloader" {
  type        = "zip"
  source_dir  = "${path.module}/../src/video_downloader"
  output_path = "${path.module}/../dist/video_downloader.zip"
}

data "archive_file" "video_processor" {
  type        = "zip"
  source_dir  = "${path.module}/../src/video_processor"
  output_path = "${path.module}/../dist/video_processor.zip"
}

data "archive_file" "api_handler" {
  type        = "zip"
  source_dir  = "${path.module}/../src/api_handler"
  output_path = "${path.module}/../dist/api_handler.zip"
}

data "archive_file" "website_publisher" {
  type        = "zip"
  source_dir  = "${path.module}/../src/website_publisher"
  output_path = "${path.module}/../dist/website_publisher.zip"
}

# CloudWatch Log Groups
resource "aws_cloudwatch_log_group" "youtube_scanner" {
  name              = "/aws/lambda/${aws_lambda_function.youtube_scanner.function_name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "video_downloader" {
  name              = "/aws/lambda/${aws_lambda_function.video_downloader.function_name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "video_processor" {
  name              = "/aws/lambda/${aws_lambda_function.video_processor.function_name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "api_handler" {
  name              = "/aws/lambda/${aws_lambda_function.api_handler.function_name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "website_publisher" {
  name              = "/aws/lambda/${aws_lambda_function.website_publisher.function_name}"
  retention_in_days = 30
}
