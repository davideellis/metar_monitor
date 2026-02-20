output "collector_lambda_name" {
  value = aws_lambda_function.collector.function_name
}

output "history_api_url" {
  value = aws_lambda_function_url.history.function_url
}

output "site_url" {
  value = "http://${aws_s3_bucket_website_configuration.site.website_endpoint}"
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
