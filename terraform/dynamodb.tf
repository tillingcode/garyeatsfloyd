# DynamoDB table to track videos
resource "aws_dynamodb_table" "videos" {
  name           = "garyeatsfloyd-videos"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "video_id"

  attribute {
    name = "video_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "published_at"
    type = "S"
  }

  global_secondary_index {
    name            = "status-published-index"
    hash_key        = "status"
    range_key       = "published_at"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name = "GaryEatsFloyd Videos Table"
  }
}

# DynamoDB table for processing jobs
resource "aws_dynamodb_table" "processing_jobs" {
  name           = "garyeatsfloyd-processing-jobs"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  attribute {
    name = "video_id"
    type = "S"
  }

  attribute {
    name = "job_status"
    type = "S"
  }

  global_secondary_index {
    name            = "video-id-index"
    hash_key        = "video_id"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "job-status-index"
    hash_key        = "job_status"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name = "GaryEatsFloyd Processing Jobs Table"
  }
}

# DynamoDB table for website content/metadata
resource "aws_dynamodb_table" "website_content" {
  name           = "garyeatsfloyd-website-content"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "content_id"
  range_key      = "content_type"

  attribute {
    name = "content_id"
    type = "S"
  }

  attribute {
    name = "content_type"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "content-type-created-index"
    hash_key        = "content_type"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  tags = {
    Name = "GaryEatsFloyd Website Content Table"
  }
}
