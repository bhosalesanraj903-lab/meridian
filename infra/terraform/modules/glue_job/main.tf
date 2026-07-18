# Glue Python Shell job + scoped role + failure alerting via EventBridge
# rule on Glue Job State Change (FAILED/TIMEOUT/STOPPED -> alerts topic).

terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

variable "name" { type = string }
variable "script_s3_uri" { type = string }
variable "policy_json" { type = string }
variable "default_arguments" {
  type    = map(string)
  default = {}
}
variable "alerts_topic_arn" { type = string }
variable "timeout_minutes" {
  type    = number
  default = 30
}

resource "aws_iam_role" "this" {
  name = "${var.name}-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "this" {
  name   = "${var.name}-policy"
  role   = aws_iam_role.this.id
  policy = var.policy_json
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_glue_job" "this" {
  name         = var.name
  role_arn     = aws_iam_role.this.arn
  max_capacity = 1.0 # 4 vCPU / 16 GB — never 0.0625 (ADR-004 / INC-000)
  max_retries  = 0   # retries are the trigger's decision, not silent
  timeout      = var.timeout_minutes

  command {
    name            = "pythonshell"
    python_version  = "3.9"
    script_location = var.script_s3_uri
  }

  execution_property {
    max_concurrent_runs = 1
  }

  default_arguments = var.default_arguments
}

resource "aws_cloudwatch_event_rule" "job_failed" {
  name        = "${var.name}-failed"
  description = "Glue job ${var.name} FAILED/TIMEOUT/STOPPED"
  event_pattern = jsonencode({
    source      = ["aws.glue"]
    detail-type = ["Glue Job State Change"]
    detail = {
      jobName = [var.name]
      state   = ["FAILED", "TIMEOUT", "STOPPED"]
    }
  })
}

resource "aws_cloudwatch_event_target" "job_failed_sns" {
  rule = aws_cloudwatch_event_rule.job_failed.name
  arn  = var.alerts_topic_arn
}

output "job_name" { value = aws_glue_job.this.name }
output "job_arn" { value = aws_glue_job.this.arn }
output "role_name" { value = aws_iam_role.this.name }
