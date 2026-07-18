# Reusable zip-based Lambda: function + scoped role + retained log group +
# errors alarm wired to the alerts topic.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

variable "name" { type = string }
variable "zip_path" { type = string }
variable "handler" { type = string }
variable "policy_json" {
  type        = string
  description = "Scoped inline policy for this function's role"
}
variable "environment" {
  type    = map(string)
  default = {}
}
variable "timeout" {
  type    = number
  default = 120
}
variable "memory_mb" {
  type    = number
  default = 512
}
variable "alerts_topic_arn" { type = string }
variable "runtime" {
  type    = string
  default = "python3.12"
}

resource "aws_iam_role" "this" {
  name = "${var.name}-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "this" {
  name   = "${var.name}-policy"
  role   = aws_iam_role.this.id
  policy = var.policy_json
}

resource "aws_iam_role_policy_attachment" "basic_logs" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = 14
}

resource "aws_lambda_function" "this" {
  function_name    = var.name
  role             = aws_iam_role.this.arn
  runtime          = var.runtime
  handler          = var.handler
  filename         = var.zip_path
  source_code_hash = filebase64sha256(var.zip_path)
  timeout          = var.timeout
  memory_size      = var.memory_mb

  environment {
    variables = var.environment
  }

  depends_on = [aws_cloudwatch_log_group.this]
}

resource "aws_cloudwatch_metric_alarm" "errors" {
  alarm_name          = "${var.name}-errors"
  alarm_description   = "Any invocation error in ${var.name}"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.this.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]
}

output "function_name" { value = aws_lambda_function.this.function_name }
output "function_arn" { value = aws_lambda_function.this.arn }
output "role_arn" { value = aws_iam_role.this.arn }
output "role_name" { value = aws_iam_role.this.name }
