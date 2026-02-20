variable "aws_region" {
  type        = string
  description = "AWS region to deploy into"
  default     = "us-east-1"
}

variable "station_ids" {
  type        = list(string)
  description = "METAR station IDs to monitor"
  default     = ["KJWY"]
}

variable "lookback_hours" {
  type        = number
  description = "Hours of METAR history requested from API"
  default     = 2.5
}

variable "metar_retention_days" {
  type        = number
  description = "How many days to retain detailed METAR observation records"
  default     = 30
}

variable "run_retention_days" {
  type        = number
  description = "How many days to retain hourly availability/run status records"
  default     = 30
}

variable "stale_threshold_hours" {
  type        = number
  description = "Treat station as error when newest METAR observation is older than this many hours"
  default     = 2
}

variable "alert_on_empty" {
  type        = bool
  description = "Whether to send SNS alert when API returns no METARs"
  default     = true
}

variable "alert_email" {
  type        = string
  description = "Optional email for SNS alerts (must confirm subscription)"
  default     = ""
}

variable "admin_token" {
  type        = string
  description = "Legacy admin auth secret (kept for backwards compatibility)"
  default     = ""
  sensitive   = true
}

variable "admin_session_secret" {
  type        = string
  description = "HMAC secret used to sign admin session tokens"
  default     = ""
  sensitive   = true
}

variable "site_bucket_name" {
  type        = string
  description = "Unique S3 bucket name for the static timeline site"
}
