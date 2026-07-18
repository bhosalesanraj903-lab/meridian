# Event chain: SNS <- S3 (policy only) -> SQS (+DLQ, depth alarm)
# -> optional Lambda event source mapping. Used three times (sdn-updated,
# customer-batch, gold-published) — the policies between S3/SNS/SQS are easy
# to get subtly wrong, so they live here once.
#
# NOTE: aws_s3_bucket_notification is bucket-GLOBAL (one resource per bucket,
# last writer wins), so the notification itself is defined once in the env
# root with all prefix rules — this module only provides the topic + queue
# chain and the policy allowing the bucket to publish.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

variable "name" { type = string }
variable "bucket_arn" { type = string }
variable "attach_consumer" {
  type        = bool
  description = "Wire a consumer Lambda (must be known at plan time)"
  default     = false
}
variable "consumer_lambda_arn" {
  type        = string
  description = "Lambda to wire as SQS consumer"
  default     = ""
}
variable "consumer_role_name" {
  type        = string
  description = "Role name of the consumer Lambda (granted SQS consume)"
  default     = ""
}
variable "alerts_topic_arn" { type = string }

resource "aws_sns_topic" "this" {
  name = "meridian-${var.name}"
}

resource "aws_sns_topic_policy" "allow_s3" {
  arn = aws_sns_topic.this.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = aws_sns_topic.this.arn
      Condition = { ArnEquals = { "aws:SourceArn" = var.bucket_arn } }
    }]
  })
}

resource "aws_sqs_queue" "dlq" {
  name                      = "meridian-${var.name}-dlq"
  message_retention_seconds = 1209600 # 14 days to investigate
}

resource "aws_sqs_queue" "this" {
  name                       = "meridian-${var.name}-q"
  visibility_timeout_seconds = 300 # > consumer Lambda timeout
  message_retention_seconds  = 345600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue_policy" "allow_sns" {
  queue_url = aws_sqs_queue.this.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.this.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.this.arn } }
    }]
  })
}

resource "aws_sns_topic_subscription" "queue" {
  topic_arn            = aws_sns_topic.this.arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.this.arn
  raw_message_delivery = true
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "meridian-${var.name}-dlq-depth"
  alarm_description   = "Messages in ${var.name} DLQ — something is failing repeatedly"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]
}

resource "aws_lambda_event_source_mapping" "consumer" {
  count            = var.attach_consumer ? 1 : 0
  event_source_arn = aws_sqs_queue.this.arn
  function_name    = var.consumer_lambda_arn
  batch_size       = 1
}

resource "aws_iam_role_policy" "consumer_sqs" {
  count = var.attach_consumer ? 1 : 0
  name  = "consume-${var.name}"
  role  = var.consumer_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
      ]
      Resource = aws_sqs_queue.this.arn
    }]
  })
}

output "topic_arn" { value = aws_sns_topic.this.arn }
output "queue_arn" { value = aws_sqs_queue.this.arn }
output "queue_url" { value = aws_sqs_queue.this.id }
output "dlq_url" { value = aws_sqs_queue.dlq.id }
output "dlq_arn" { value = aws_sqs_queue.dlq.arn }
