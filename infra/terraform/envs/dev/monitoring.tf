# M5 — meridian-ops dashboard: the daily-triage landing page.
# Ritual: flow map + alarms strip first; anything red -> panels -> logs.

# Custom-widget Lambda: renders the live pipeline flow diagram inside the
# dashboard (CloudWatch invokes it with the viewer's credentials on refresh).
data "aws_iam_policy_document" "flow_widget" {
  statement {
    sid = "ReadPipelineState"
    actions = [
      "cloudwatch:DescribeAlarms",
      "glue:GetJobRuns",
      "logs:DescribeLogStreams",
      "sqs:GetQueueUrl",
      "sqs:GetQueueAttributes",
      "sns:ListSubscriptionsByTopic",
    ]
    resources = ["*"]
  }
}

module "flow_widget_lambda" {
  source           = "../../modules/lambda_zip"
  name             = "meridian-flow-widget"
  zip_path         = "${path.module}/../../../../build/lambda_bundle.zip"
  handler          = "flow_widget_handler.lambda_handler"
  policy_json      = data.aws_iam_policy_document.flow_widget.json
  alerts_topic_arn = module.lake.alerts_topic_arn
  timeout          = 30
  memory_mb        = 128
}

locals {
  alarm_names = [
    "meridian-ofac-ingest-errors",
    "meridian-ofac-ingest-staleness",
    "meridian-resolution-trigger-errors",
    "meridian-gold-notifier-errors",
    "meridian-sdn-updated-dlq-depth",
    "meridian-customer-batch-dlq-depth",
    "meridian-gold-published-dlq-depth",
  ]
  alarm_arns = [
    for name in local.alarm_names :
    "arn:aws:cloudwatch:${var.region}:${data.aws_caller_identity.current.account_id}:alarm:${name}"
  ]
  lambda_names = [
    "meridian-ofac-ingest",
    "meridian-resolution-trigger",
    "meridian-gold-notifier",
  ]
  queue_names = [
    "meridian-sdn-updated-q",
    "meridian-customer-batch-q",
    "meridian-gold-published-q",
    "meridian-sdn-updated-dlq",
    "meridian-customer-batch-dlq",
    "meridian-gold-published-dlq",
  ]
}

resource "aws_cloudwatch_dashboard" "ops" {
  dashboard_name = "meridian-ops"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "custom"
        x    = 0, y = 0, width = 24, height = 4
        properties = {
          endpoint = module.flow_widget_lambda.function_arn
          title    = "Pipeline flow — live component status"
          updateOn = { refresh = true, resize = true, timeRange = false }
        }
      },
      {
        type = "text"
        x    = 0, y = 4, width = 24, height = 4
        properties = {
          markdown = <<-EOT
            ## Meridian — sanctions-screening pipeline (us-east-1)
            **Flow:** EventBridge 6h cron → `ofac-ingest` λ → S3 bronze → SNS→SQS (+DLQ) → `resolution-trigger` λ (validate/quarantine/dedupe) → Glue `resolve-and-screen` (1 DPU) → S3 silver+gold Parquet → SNS→SQS → `gold-notifier` λ → **alert email** · gold queryable in [Athena](https://console.aws.amazon.com/athena/home?region=us-east-1) (workgroup `meridian`)

            **Triage ritual:** alarm strip below must be green → DLQ depths 0 → ingest invocations present every 6h. Anything red: [Glue runs](https://console.aws.amazon.com/gluestudio/home?region=us-east-1#/jobs) → runbooks in [repo](https://github.com/bhosalesanraj903-lab/meridian) `docs/runbooks/`. Budget alarm $5/mo.
          EOT
        }
      },
      {
        type = "alarm"
        x    = 0, y = 8, width = 24, height = 3
        properties = {
          title  = "Alarm status — anything not green is today's work"
          alarms = local.alarm_arns
        }
      },
      {
        type = "metric"
        x    = 0, y = 11, width = 12, height = 6
        properties = {
          title  = "Lambda invocations (ingest freshness = leftmost bars present)"
          region = var.region
          stat   = "Sum"
          period = 3600
          metrics = [
            for fn in local.lambda_names :
            ["AWS/Lambda", "Invocations", "FunctionName", fn]
          ]
          view = "timeSeries"
        }
      },
      {
        type = "metric"
        x    = 12, y = 11, width = 12, height = 6
        properties = {
          title  = "Lambda errors (must be zero)"
          region = var.region
          stat   = "Sum"
          period = 3600
          metrics = [
            for fn in local.lambda_names :
            ["AWS/Lambda", "Errors", "FunctionName", fn]
          ]
          view = "timeSeries"
        }
      },
      {
        type = "metric"
        x    = 0, y = 17, width = 12, height = 6
        properties = {
          title  = "Queue depth (DLQs must be zero)"
          region = var.region
          stat   = "Maximum"
          period = 300
          metrics = [
            for q in local.queue_names :
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", q]
          ]
          view = "timeSeries"
        }
      },
      {
        type = "log"
        x    = 12, y = 17, width = 12, height = 6
        properties = {
          title  = "Screening runs — hits by severity (from run summaries)"
          region = var.region
          query  = <<-EOT
            SOURCE '/aws/lambda/meridian-gold-notifier'
            | filter message = "Published run summary"
            | sort @timestamp desc
            | display @timestamp, run_id, batch_id, hits_strong, hits_possible, customers_screened
            | limit 20
          EOT
          view   = "table"
        }
      },
    ]
  })
}
