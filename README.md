# metar_monitor

Serverless METAR monitor on AWS using Terraform.

## What this deploys
- Hourly collector Lambda (EventBridge schedule `rate(1 hour)`)
- DynamoDB table for METAR records
- DynamoDB table for collector run status (ok/empty/error)
- DynamoDB table for tracked station configuration
- SNS topic for alerts (with optional email subscription)
- Public History API (API Gateway + Lambda)
- Admin API (API Gateway + Lambda) to add/remove tracked stations
- Public S3 static site showing availability timeline + recent METAR history

## Repository layout
- `src/collector/lambda_function.py`: pulls METAR XML, stores data, alerts on failures
- `src/history/lambda_function.py`: serves historical runs and METAR entries
- `src/admin/lambda_function.py`: admin endpoints for managing tracked stations
- `site/index.html.tmpl`: static timeline UI template
- `site/admin.html.tmpl`: static admin UI template
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
- `history_api_url`: history API URL used by the timeline site
- `admin_api_url`: admin API URL
- `admin_ui_url`: admin page URL
- `collector_lambda_name`
- `alerts_topic_arn`

## API usage examples
- Runs timeline:
  - `${history_api_url}?type=runs&limit=168`
- METAR history for station:
  - `${history_api_url}?type=metars&station=KJWY&limit=168`

## Notes
- Collector stores each METAR by `station_id + observation_time`.
- Collector reads tracked stations from `metar-monitor-stations`; if empty, it falls back to `station_ids` variable.
- Run history stores each hourly invocation and status for availability reporting.
- `ALERT_ON_EMPTY` controls whether zero-METAR responses send alerts.
- Detailed METAR observation records are retained for `metar_retention_days` (default: `30`).
- Availability/run records are retained for `run_retention_days` (default: `365`).
- Retention is implemented with DynamoDB TTL (`expires_at`) and may take up to 48 hours to fully purge expired items.
- Set `admin_token` in `terraform.tfvars`, then use it in the `x-admin-token` field on `admin.html`.
