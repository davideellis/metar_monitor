# metar_monitor

Serverless METAR monitor on AWS using Terraform.

## What this deploys
- Hourly collector Lambda (EventBridge schedule `rate(1 hour)`)
- DynamoDB table for METAR records
- DynamoDB table for collector run status (ok/empty/error)
- DynamoDB table for tracked station configuration
- DynamoDB table for notification owners
- DynamoDB table for alert cooldown state
- SNS topic for alerts (with optional email subscription)
- Public History API (API Gateway + Lambda)
- Admin API (API Gateway + Lambda) to add/remove tracked stations
- Alert Router Lambda (EventBridge -> Lambda -> per-owner SNS topic)
- Public S3 static site showing availability timeline + recent METAR history

## Repository layout
- `src/collector/lambda_function.py`: pulls METAR XML, stores data, alerts on failures
- `src/history/lambda_function.py`: serves historical runs and METAR entries
- `src/admin/lambda_function.py`: admin endpoints for managing tracked stations
- `src/router/lambda_function.py`: routes per-station failures to owner SNS topics with cooldown
- `site/index.html.tmpl`: static timeline UI template
- `site/admin.html.tmpl`: static admin UI template
- `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`: Terraform infra
- `terraform.tfvars.example`: example values

## Prerequisites
- Terraform >= 1.6
- AWS credentials configured (`aws configure` or environment variables)
- Python 3.12 (for local unit tests)

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

## Unit Tests
1. Install dev dependencies:
   ```bash
   py -m pip install -r requirements-dev.txt
   ```
2. Run tests:
   ```bash
   py -m pytest
   ```
3. Run tests with coverage:
   ```bash
   py -m pytest --cov=src --cov-report=term-missing
   ```

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
- Collector emits station-level alert events to EventBridge.
- Run history stores each hourly invocation and status for availability reporting.
- `ALERT_ON_EMPTY` controls whether zero-METAR responses generate alert events.
- `STALE_THRESHOLD_HOURS` controls stale detection (default `2`): if a station's newest METAR observation is older than this, station status is `error`.
- Detailed METAR observation records are retained for `metar_retention_days` (default: `30`).
- Availability/run records are retained for `run_retention_days` (default: `30`).
- Retention is implemented with DynamoDB TTL (`expires_at`) and may take up to 48 hours to fully purge expired items.
- Set `admin_token` in `terraform.tfvars`, then use it in the `x-admin-token` field on `admin.html`.
- Configure owner records with `owner_id` and `topic_arn`, then assign `owner_id` on each station.
