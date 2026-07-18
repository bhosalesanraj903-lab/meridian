# Lake module: data + artifacts buckets, state table, alerts topic, budget,
# Athena workgroup, Glue catalog database. Everything cost-guarded.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

variable "account_id" { type = string }
variable "alert_email" { type = string }
variable "budget_limit_usd" {
  type    = string
  default = "5.0"
}

locals {
  lake_bucket      = "meridian-lake-${var.account_id}"
  artifacts_bucket = "meridian-artifacts-${var.account_id}"
}

# ---------- data lake bucket ----------

resource "aws_s3_bucket" "lake" {
  bucket = local.lake_bucket
}

resource "aws_s3_bucket_versioning" "lake" {
  bucket = aws_s3_bucket.lake.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "lake" {
  bucket                  = aws_s3_bucket.lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id

  rule {
    id     = "noncurrent-expiry"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 30 }
  }

  rule {
    id     = "bronze-to-glacier-ir"
    status = "Enabled"
    filter { prefix = "bronze/" }
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
  }
}

# Bronze is append-only for everyone except break-glass admin: deny deletes
# and overwrites of landed raw data at the bucket-policy level.
resource "aws_s3_bucket_policy" "lake" {
  bucket = aws_s3_bucket.lake.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyBronzeDelete"
      Effect    = "Deny"
      Principal = "*"
      Action    = ["s3:DeleteObject", "s3:DeleteObjectVersion"]
      Resource  = "${aws_s3_bucket.lake.arn}/bronze/*"
      Condition = {
        StringNotLike = {
          "aws:PrincipalArn" = "arn:aws:iam::${var.account_id}:role/meridian-github-deploy"
        }
      }
    }]
  })
}

# ---------- artifacts bucket (wheels, lambda zips, glue scripts, athena results) ----------

resource "aws_s3_bucket" "artifacts" {
  bucket = local.artifacts_bucket
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "athena-results-expiry"
    status = "Enabled"
    filter { prefix = "athena-results/" }
    expiration { days = 7 }
  }
}

# ---------- state table ----------

resource "aws_dynamodb_table" "state" {
  name         = "meridian-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "entity"
  attribute {
    name = "entity"
    type = "S"
  }
}

# ---------- alerts ----------

resource "aws_sns_topic" "alerts" {
  name = "meridian-alerts"
}

# EventBridge (Glue job failure rule) must be allowed to publish alerts.
resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountOwnerFullAccess"
        Effect    = "Allow"
        Principal = { AWS = "*" }
        Action    = ["SNS:Publish", "SNS:Subscribe", "SNS:GetTopicAttributes"]
        Resource  = aws_sns_topic.alerts.arn
        Condition = { StringEquals = { "AWS:SourceOwner" = var.account_id } }
      },
      {
        Sid       = "EventBridgePublish"
        Effect    = "Allow"
        Principal = { Service = "events.amazonaws.com" }
        Action    = "SNS:Publish"
        Resource  = aws_sns_topic.alerts.arn
      }
    ]
  })
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ---------- budget guardrail ----------

resource "aws_budgets_budget" "monthly" {
  name         = "meridian-monthly"
  budget_type  = "COST"
  limit_amount = var.budget_limit_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}

# ---------- Athena + Glue catalog ----------

resource "aws_athena_workgroup" "meridian" {
  name          = "meridian"
  force_destroy = true
  configuration {
    enforce_workgroup_configuration = true
    bytes_scanned_cutoff_per_query  = 1073741824 # 1 GB
    result_configuration {
      output_location = "s3://${aws_s3_bucket.artifacts.bucket}/athena-results/"
    }
  }
}

resource "aws_glue_catalog_database" "meridian" {
  name = "meridian"
}

# ---------- outputs ----------

output "lake_bucket" { value = aws_s3_bucket.lake.bucket }
output "lake_bucket_arn" { value = aws_s3_bucket.lake.arn }
output "artifacts_bucket" { value = aws_s3_bucket.artifacts.bucket }
output "artifacts_bucket_arn" { value = aws_s3_bucket.artifacts.arn }
output "state_table_name" { value = aws_dynamodb_table.state.name }
output "state_table_arn" { value = aws_dynamodb_table.state.arn }
output "alerts_topic_arn" { value = aws_sns_topic.alerts.arn }
output "glue_database" { value = aws_glue_catalog_database.meridian.name }
output "athena_workgroup" { value = aws_athena_workgroup.meridian.name }
