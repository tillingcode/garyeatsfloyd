# Secrets Manager for YouTube API Key
resource "aws_secretsmanager_secret" "youtube_api_key" {
  name        = "garyeatsfloyd/youtube-api-key"
  description = "YouTube Data API key for GaryEatsFloyd"

  recovery_window_in_days = 7

  tags = {
    Name = "GaryEatsFloyd YouTube API Key"
  }
}

resource "aws_secretsmanager_secret_version" "youtube_api_key" {
  secret_id     = aws_secretsmanager_secret.youtube_api_key.id
  secret_string = var.youtube_api_key
}
