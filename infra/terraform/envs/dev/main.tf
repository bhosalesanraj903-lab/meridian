terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    # bucket comes from -backend-config (bootstrap output), e.g.:
    #   terraform init -backend-config="bucket=meridian-tfstate-<account_id>"
    key = "envs/dev/terraform.tfstate"
    # The tfstate BUCKET lives in ap-south-1 (original bootstrap region);
    # state-bucket region is independent of where resources deploy.
    region       = "ap-south-1"
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { project = "meridian", env = "dev", managed_by = "terraform" }
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "alert_email" {
  type        = string
  description = "Email for pipeline alerts and budget notifications"
}

data "aws_caller_identity" "current" {}

module "lake" {
  source      = "../../modules/lake"
  account_id  = data.aws_caller_identity.current.account_id
  alert_email = var.alert_email
}

output "lake_bucket" { value = module.lake.lake_bucket }
output "artifacts_bucket" { value = module.lake.artifacts_bucket }
output "alerts_topic_arn" { value = module.lake.alerts_topic_arn }
output "state_table" { value = module.lake.state_table_name }
