provider "aws" {
  region = var.aws_region
}

locals {
  service_name    = "metar-monitor"
  default_station = var.station_ids[0]
}

data "archive_file" "collector_zip" {
  type        = "zip"
  source_dir  = "${path.module}/src/collector"
  output_path = "${path.module}/build/collector.zip"
}

data "archive_file" "history_zip" {
  type        = "zip"
  source_dir  = "${path.module}/src/history"
  output_path = "${path.module}/build/history.zip"
}

data "archive_file" "admin_zip" {
  type        = "zip"
  source_dir  = "${path.module}/src/admin"
  output_path = "${path.module}/build/admin.zip"
}

resource "aws_dynamodb_table" "metars" {
  name         = "${local.service_name}-metars"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "station_id"
  range_key    = "observation_time"

  attribute {
    name = "station_id"
    type = "S"
  }

  attribute {
    name = "observation_time"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "runs" {
  name         = "${local.service_name}-runs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "checked_at_utc"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "checked_at_utc"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "stations" {
  name         = "${local.service_name}-stations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "station_id"

  attribute {
    name = "station_id"
    type = "S"
  }
}

resource "aws_sns_topic" "alerts" {
  name = "${local.service_name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_iam_role" "collector_lambda" {
  name = "${local.service_name}-collector-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "collector_policy" {
  name = "${local.service_name}-collector-policy"
  role = aws_iam_role.collector_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = ["dynamodb:BatchWriteItem", "dynamodb:PutItem", "dynamodb:Scan"]
        Resource = [
          aws_dynamodb_table.metars.arn,
          aws_dynamodb_table.runs.arn,
          aws_dynamodb_table.stations.arn
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = aws_sns_topic.alerts.arn
      }
    ]
  })
}

resource "aws_lambda_function" "collector" {
  function_name    = "${local.service_name}-collector"
  role             = aws_iam_role.collector_lambda.arn
  runtime          = "python3.12"
  handler          = "lambda_function.lambda_handler"
  filename         = data.archive_file.collector_zip.output_path
  source_code_hash = data.archive_file.collector_zip.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      STATION_IDS          = join(",", var.station_ids)
      LOOKBACK_HOURS       = tostring(var.lookback_hours)
      METARS_TABLE         = aws_dynamodb_table.metars.name
      RUNS_TABLE           = aws_dynamodb_table.runs.name
      STATIONS_TABLE       = aws_dynamodb_table.stations.name
      METAR_RETENTION_DAYS = tostring(var.metar_retention_days)
      RUN_RETENTION_DAYS   = tostring(var.run_retention_days)
      ALERT_TOPIC_ARN      = aws_sns_topic.alerts.arn
      ALERT_ON_EMPTY       = tostring(var.alert_on_empty)
    }
  }
}

resource "aws_cloudwatch_event_rule" "hourly" {
  name                = "${local.service_name}-hourly"
  description         = "Trigger METAR collector every hour"
  schedule_expression = "rate(1 hour)"
}

resource "aws_cloudwatch_event_target" "collector_target" {
  rule      = aws_cloudwatch_event_rule.hourly.name
  target_id = "collector-lambda"
  arn       = aws_lambda_function.collector.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.collector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.hourly.arn
}

resource "aws_iam_role" "history_lambda" {
  name = "${local.service_name}-history-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "history_policy" {
  name = "${local.service_name}-history-policy"
  role = aws_iam_role.history_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = ["dynamodb:Query", "dynamodb:Scan"]
        Resource = [
          aws_dynamodb_table.metars.arn,
          aws_dynamodb_table.runs.arn,
          aws_dynamodb_table.stations.arn
        ]
      }
    ]
  })
}

resource "aws_lambda_function" "history" {
  function_name    = "${local.service_name}-history"
  role             = aws_iam_role.history_lambda.arn
  runtime          = "python3.12"
  handler          = "lambda_function.lambda_handler"
  filename         = data.archive_file.history_zip.output_path
  source_code_hash = data.archive_file.history_zip.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      METARS_TABLE    = aws_dynamodb_table.metars.name
      RUNS_TABLE      = aws_dynamodb_table.runs.name
      STATIONS_TABLE  = aws_dynamodb_table.stations.name
      DEFAULT_STATION = local.default_station
    }
  }
}

resource "aws_apigatewayv2_api" "history" {
  name          = "${local.service_name}-history-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "OPTIONS"]
    allow_headers = ["content-type"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_integration" "history_lambda" {
  api_id                 = aws_apigatewayv2_api.history.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.history.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "history_get" {
  api_id    = aws_apigatewayv2_api.history.id
  route_key = "GET /"
  target    = "integrations/${aws_apigatewayv2_integration.history_lambda.id}"
}

resource "aws_apigatewayv2_stage" "history" {
  api_id      = aws_apigatewayv2_api.history.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_history_apigw" {
  statement_id  = "AllowExecutionFromApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.history.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.history.execution_arn}/*/*"
}

resource "aws_iam_role" "admin_lambda" {
  name = "${local.service_name}-admin-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "admin_policy" {
  name = "${local.service_name}-admin-policy"
  role = aws_iam_role.admin_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = ["dynamodb:Scan", "dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = [
          aws_dynamodb_table.stations.arn
        ]
      }
    ]
  })
}

resource "aws_lambda_function" "admin" {
  function_name    = "${local.service_name}-admin"
  role             = aws_iam_role.admin_lambda.arn
  runtime          = "python3.12"
  handler          = "lambda_function.lambda_handler"
  filename         = data.archive_file.admin_zip.output_path
  source_code_hash = data.archive_file.admin_zip.output_base64sha256
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      STATIONS_TABLE = aws_dynamodb_table.stations.name
      ADMIN_TOKEN    = var.admin_token
    }
  }
}

resource "aws_apigatewayv2_api" "admin" {
  name          = "${local.service_name}-admin-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "DELETE", "OPTIONS"]
    allow_headers = ["content-type", "x-admin-token"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_integration" "admin_lambda" {
  api_id                 = aws_apigatewayv2_api.admin.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.admin.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "admin_root_get" {
  api_id    = aws_apigatewayv2_api.admin.id
  route_key = "GET /"
  target    = "integrations/${aws_apigatewayv2_integration.admin_lambda.id}"
}

resource "aws_apigatewayv2_route" "admin_root_post" {
  api_id    = aws_apigatewayv2_api.admin.id
  route_key = "POST /"
  target    = "integrations/${aws_apigatewayv2_integration.admin_lambda.id}"
}

resource "aws_apigatewayv2_route" "admin_delete_station" {
  api_id    = aws_apigatewayv2_api.admin.id
  route_key = "DELETE /stations/{station_id}"
  target    = "integrations/${aws_apigatewayv2_integration.admin_lambda.id}"
}

resource "aws_apigatewayv2_stage" "admin" {
  api_id      = aws_apigatewayv2_api.admin.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_admin_apigw" {
  statement_id  = "AllowExecutionFromAdminApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.admin.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.admin.execution_arn}/*/*"
}

resource "aws_s3_bucket" "site" {
  bucket        = var.site_bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_website_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  index_document {
    suffix = "index.html"
  }
}

resource "aws_s3_bucket_policy" "site_public_read" {
  bucket = aws_s3_bucket.site.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicReadGetObject"
      Effect    = "Allow"
      Principal = "*"
      Action    = ["s3:GetObject"]
      Resource  = "${aws_s3_bucket.site.arn}/*"
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.site]
}

resource "aws_s3_object" "site_index" {
  bucket       = aws_s3_bucket.site.id
  key          = "index.html"
  content_type = "text/html"
  content = replace(
    replace(
      file("${path.module}/site/index.html.tmpl"),
      "__API_URL__",
      aws_apigatewayv2_stage.history.invoke_url
    ),
    "__DEFAULT_STATION__",
    local.default_station
  )
}

resource "aws_s3_object" "site_admin" {
  bucket       = aws_s3_bucket.site.id
  key          = "admin.html"
  content_type = "text/html"
  content = replace(
    file("${path.module}/site/admin.html.tmpl"),
    "__ADMIN_API_URL__",
    aws_apigatewayv2_stage.admin.invoke_url
  )
}
