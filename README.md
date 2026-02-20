# metar_monitor

Serverless METAR monitor on AWS using Terraform.

## What this deploys
- Hourly collector Lambda (EventBridge schedule `rate(1 hour)`)
- DynamoDB table for METAR records
- DynamoDB table for collector run status (ok/empty/error)
- SNS topic for alerts (with optional email subscription)
- History API Lambda with Function URL (`GET`) for timeline data
- Public S3 static site showing availability timeline + recent METAR history

## Repository layout
- `src/collector/lambda_function.py`: pulls METAR XML, stores data, alerts on failures
- `src/history/lambda_function.py`: serves historical runs and METAR entries
- `site/index.html.tmpl`: static timeline UI template
- `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`: Terraform infra
- `terraform.tfvars.example`: example values

## Prerequisites
- Terraform >= 1.6
- AWS credentials configured (`aws configure` or environment variables)

## Deploy
1. Copy and edit variables:
   ```bash
   copy terraform.tfvars.example terraform.tfvars
   ```
2. Set a globally unique `site_bucket_name` in `terraform.tfvars`.
3. Initialize/apply:
   ```bash
   terraform init
   terraform apply
   ```
4. If `alert_email` is set, confirm SNS subscription from your email inbox.

## Useful outputs
- `site_url`: static website endpoint
- `history_api_url`: Lambda function URL used by the site
- `collector_lambda_name`
- `alerts_topic_arn`

## API usage examples
- Runs timeline:
  - `${history_api_url}?type=runs&limit=168`
- METAR history for station:
  - `${history_api_url}?type=metars&station=KJWY&limit=168`

## Notes
- Collector stores each METAR by `station_id + observation_time`.
- Run history stores each hourly invocation and status for availability reporting.
- `ALERT_ON_EMPTY` controls whether zero-METAR responses send alerts.
