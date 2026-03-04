# API Gateway HTTP API
resource "aws_apigatewayv2_api" "main" {
  name          = "garyeatsfloyd-api"
  protocol_type = "HTTP"
  description   = "API for GaryEatsFloyd website"

  cors_configuration {
    allow_origins = ["https://${local.full_domain}"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["Content-Type", "Authorization"]
    max_age       = 3600
  }
}

# API Gateway Stage
resource "aws_apigatewayv2_stage" "main" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId         = "$context.requestId"
      ip                = "$context.identity.sourceIp"
      requestTime       = "$context.requestTime"
      httpMethod        = "$context.httpMethod"
      routeKey          = "$context.routeKey"
      status            = "$context.status"
      protocol          = "$context.protocol"
      responseLength    = "$context.responseLength"
      integrationError  = "$context.integrationErrorMessage"
    })
  }
}

# Lambda Integration
resource "aws_apigatewayv2_integration" "lambda" {
  api_id             = aws_apigatewayv2_api.main.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.api_handler.invoke_arn
  integration_method = "POST"
  payload_format_version = "2.0"
}

# Routes
resource "aws_apigatewayv2_route" "get_videos" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /api/videos"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "get_video" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /api/videos/{videoId}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "get_latest" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /api/latest"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "health" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /api/health"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# CloudWatch Log Group for API Gateway
resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${aws_apigatewayv2_api.main.name}"
  retention_in_days = 30
}

# Custom domain for API Gateway
resource "aws_apigatewayv2_domain_name" "api" {
  domain_name = "api.${local.full_domain}"

  domain_name_configuration {
    certificate_arn = aws_acm_certificate.main.arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }

  depends_on = [aws_acm_certificate_validation.main]
}

resource "aws_apigatewayv2_api_mapping" "api" {
  api_id      = aws_apigatewayv2_api.main.id
  domain_name = aws_apigatewayv2_domain_name.api.id
  stage       = aws_apigatewayv2_stage.main.id
}
