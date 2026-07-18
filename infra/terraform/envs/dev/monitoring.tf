# M5 — meridian-ops dashboard: the daily-triage landing page.
# Ritual: alarms strip first; anything red -> function/queue panels -> logs.

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
        type = "alarm"
        x    = 0, y = 0, width = 24, height = 3
        properties = {
          title  = "Alarm status — anything not green is today's work"
          alarms = local.alarm_arns
        }
      },
      {
        type = "metric"
        x    = 0, y = 3, width = 12, height = 6
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
        x    = 12, y = 3, width = 12, height = 6
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
        x    = 0, y = 9, width = 12, height = 6
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
        x    = 12, y = 9, width = 12, height = 6
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
