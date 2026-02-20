output "collector_lambda_name" {
  value = aws_lambda_function.collector.function_name
}

output "history_api_url" {
  value = aws_apigatewayv2_stage.history.invoke_url
}

output "admin_api_url" {
  value = aws_apigatewayv2_stage.admin.invoke_url
}

output "site_url" {
  value = "http://${aws_s3_bucket_website_configuration.site.website_endpoint}"
}

output "admin_ui_url" {
  value = "http://${aws_s3_bucket_website_configuration.site.website_endpoint}/admin.html"
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
