variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "domain_name" {
  description = "Base domain name"
  type        = string
  default     = "busyrain.com"
}

variable "subdomain" {
  description = "Subdomain for the application"
  type        = string
  default     = "garyeatsfloyd"
}

variable "youtube_channel_id" {
  description = "YouTube channel ID to monitor"
  type        = string
  default     = "@GaryEats"
}

variable "youtube_api_key" {
  description = "YouTube Data API key"
  type        = string
  sensitive   = true
}

variable "scan_schedule_hours" {
  description = "How often to scan for new videos (in hours)"
  type        = number
  default     = 24
}

variable "bedrock_model_id" {
  description = "Bedrock model ID for video processing"
  type        = string
  default     = "amazon.nova-reel-v1:0"
}

variable "keith_floyd_prompt" {
  description = "Prompt for video transformation"
  type        = string
  default     = <<-EOT
    Keith Floyd 1980s British TV chef style: always holding red wine, witty and tipsy, mentions wine often, pairs dishes with wine.
  EOT
}

locals {
  full_domain = "${var.subdomain}.${var.domain_name}"
  
  common_tags = {
    Project     = "GaryEatsFloyd"
    Environment = var.environment
  }
}
