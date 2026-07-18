# M2 — OFAC ingest: Lambda on a 6-hour EventBridge schedule landing bronze.

data "aws_iam_policy_document" "ofac_ingest" {
  statement {
    sid       = "BronzeWrite"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${module.lake.lake_bucket_arn}/bronze/ofac/*"]
  }
  statement {
    sid       = "BronzeList"
    actions   = ["s3:ListBucket"]
    resources = [module.lake.lake_bucket_arn]
  }
  statement {
    sid       = "StateReadWrite"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem"]
    resources = [module.lake.state_table_arn]
  }
}

module "ofac_ingest_lambda" {
  source           = "../../modules/lambda_zip"
  name             = "meridian-ofac-ingest"
  zip_path         = "${path.module}/../../../../build/lambda_bundle.zip"
  handler          = "ofac_ingest_handler.lambda_handler"
  policy_json      = data.aws_iam_policy_document.ofac_ingest.json
  alerts_topic_arn = module.lake.alerts_topic_arn
  timeout          = 120
  memory_mb        = 512
  environment = {
    MERIDIAN_LAKE_URI      = "s3://${module.lake.lake_bucket}"
    MERIDIAN_STATE_BACKEND = "dynamodb"
    MERIDIAN_STATE_TABLE   = module.lake.state_table_name
    MERIDIAN_USER_AGENT    = "MeridianDataPlatform ${var.alert_email}"
  }
}

# EventBridge Scheduler needs its own role to invoke the function.
resource "aws_iam_role" "scheduler" {
  name = "meridian-scheduler-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name = "invoke-ofac-ingest"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = module.ofac_ingest_lambda.function_arn
    }]
  })
}

resource "aws_scheduler_schedule" "ofac_ingest" {
  name                = "meridian-ofac-ingest-6h"
  schedule_expression = "rate(6 hours)"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = module.ofac_ingest_lambda.function_arn
    role_arn = aws_iam_role.scheduler.arn
    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}

# Freshness: if the ingest hasn't even been INVOKED in 12h the schedule is
# broken — missing data counts as breaching so a dead scheduler still pages.
resource "aws_cloudwatch_metric_alarm" "ingest_staleness" {
  alarm_name          = "meridian-ofac-ingest-staleness"
  alarm_description   = "OFAC ingest has not run in 12h (schedule broken?)"
  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  dimensions          = { FunctionName = module.ofac_ingest_lambda.function_name }
  statistic           = "Sum"
  period              = 43200
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [module.lake.alerts_topic_arn]
  ok_actions          = [module.lake.alerts_topic_arn]
}
