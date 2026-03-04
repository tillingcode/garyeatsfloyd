output "website_url" {
  description = "URL of the GaryEatsFloyd website"
  value       = "https://${local.full_domain}"
}

output "api_url" {
  description = "URL of the API endpoint"
  value       = "https://api.${local.full_domain}"
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID"
  value       = aws_cloudfront_distribution.website.id
}

output "raw_videos_bucket" {
  description = "S3 bucket for raw video downloads"
  value       = aws_s3_bucket.raw_videos.id
}

output "processed_videos_bucket" {
  description = "S3 bucket for processed videos"
  value       = aws_s3_bucket.processed_videos.id
}

output "website_bucket" {
  description = "S3 bucket for website static files"
  value       = aws_s3_bucket.website.id
}

output "videos_table" {
  description = "DynamoDB table for video tracking"
  value       = aws_dynamodb_table.videos.name
}

output "processing_jobs_table" {
  description = "DynamoDB table for processing jobs"
  value       = aws_dynamodb_table.processing_jobs.name
}

output "youtube_scanner_function" {
  description = "YouTube scanner Lambda function name"
  value       = aws_lambda_function.youtube_scanner.function_name
}

output "video_processor_function" {
  description = "Video processor Lambda function name"
  value       = aws_lambda_function.video_processor.function_name
}
