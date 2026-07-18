# Bootstrap root — applied ONCE, manually, with local state:
#   terraform init && terraform apply -var github_repo=<owner>/meridian
# Creates the tfstate bucket and the GitHub OIDC deploy role that everything
# else depends on. Never imported into the main state.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { project = "meridian", managed_by = "terraform-bootstrap" }
  }
}

variable "region" {
  # Bootstrap stays in ap-south-1: the tfstate bucket was created there and
  # IAM/OIDC resources are global. Workload resources deploy to us-east-1.
  type    = string
  default = "ap-south-1"
}

variable "github_repo" {
  type        = string
  description = "GitHub repo (owner/name) trusted to assume the deploy role"
}

# GitHub OIDC sub claims embed numeric owner/repo IDs:
#   repo:<owner>@<owner_id>/<repo>@<repo_id>:<context>
# Pinning the IDs is stricter than names alone (immune to rename/re-create
# attacks). Get them from: gh api repos/<owner>/<repo> --jq '.id,.owner.id'
variable "github_owner_id" {
  type = string
}

variable "github_repo_id" {
  type = string
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "tfstate" {
  bucket = "meridian-tfstate-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

resource "aws_iam_role" "github_deploy" {
  name = "meridian-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${split("/", var.github_repo)[0]}@${var.github_owner_id}/${split("/", var.github_repo)[1]}@${var.github_repo_id}:*"
        }
      }
    }]
  })
}

# Personal single-purpose account: admin on the deploy role keeps Terraform
# unblocked while the platform grows. Scope down (S3/Glue/Lambda/IAM-scoped)
# once the resource set stabilizes.
resource "aws_iam_role_policy_attachment" "github_deploy_admin" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

output "tfstate_bucket" {
  value = aws_s3_bucket.tfstate.bucket
}

output "deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}
