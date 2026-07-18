# M3 — event chains + resolution trigger + Glue resolve-and-screen job.

locals {
  wheel_file  = "meridian-0.1.0-py3-none-any.whl"
  build_dir   = "${path.module}/../../../../build"
  glue_script = "${path.module}/../../../../glue_jobs/resolve_and_screen.py"
}

# ---------- artifacts: glue script + meridian wheel ----------

resource "aws_s3_object" "glue_script" {
  bucket = module.lake.artifacts_bucket
  key    = "glue-scripts/resolve_and_screen.py"
  source = local.glue_script
  etag   = filemd5(local.glue_script)
}

resource "aws_s3_object" "meridian_wheel" {
  bucket = module.lake.artifacts_bucket
  key    = "wheels/${local.wheel_file}"
  source = "${local.build_dir}/${local.wheel_file}"
  etag   = filemd5("${local.build_dir}/${local.wheel_file}")
}

# INC-001: full vendored wheelhouse (make build-wheelhouse) — the job installs
# ONLY these prebuilt cp39/manylinux wheels; PyPI never enters the startup path.
resource "aws_s3_object" "vendor_wheels" {
  for_each = fileset("${local.build_dir}/wheelhouse", "*.whl")
  bucket   = module.lake.artifacts_bucket
  key      = "wheels/vendor/${each.value}"
  source   = "${local.build_dir}/wheelhouse/${each.value}"
  etag     = filemd5("${local.build_dir}/wheelhouse/${each.value}")
}

# Glue pip-installs extra-py-files IN LIST ORDER, one at a time, resolving
# any unsatisfied requirement from PyPI (where pyarrow/igraph resolve to
# sdists that fail to compile — INC-001). Order is therefore load-bearing:
# leaf/compiled wheels first, splink after its deps, meridian last so every
# one of its requirements is already satisfied locally.
locals {
  vendor_wheels  = sort(tolist(fileset("${local.build_dir}/wheelhouse", "*.whl")))
  wheels_leaf    = [for w in local.vendor_wheels : w if !can(regex("^(splink|pandas|altair)", w))]
  wheels_mid     = [for w in local.vendor_wheels : w if can(regex("^(pandas|altair)", w))]
  wheels_splink  = [for w in local.vendor_wheels : w if can(regex("^splink", w))]
  wheels_ordered = concat(local.wheels_leaf, local.wheels_mid, local.wheels_splink)

  extra_py_files = join(",", concat(
    [
      for w in local.wheels_ordered :
      "s3://${module.lake.artifacts_bucket}/wheels/vendor/${w}"
    ],
    ["s3://${module.lake.artifacts_bucket}/wheels/${local.wheel_file}"],
  ))
}

# ---------- resolution trigger Lambda ----------

data "aws_iam_policy_document" "resolution_trigger" {
  statement {
    sid     = "LakeRead"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      module.lake.lake_bucket_arn,
      "${module.lake.lake_bucket_arn}/*",
    ]
  }
  statement {
    sid       = "QuarantineWrite"
    actions   = ["s3:PutObject"]
    resources = ["${module.lake.lake_bucket_arn}/quarantine/*"]
  }
  statement {
    sid       = "Ledger"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = [module.lake.state_table_arn]
  }
  statement {
    sid       = "StartGlue"
    actions   = ["glue:StartJobRun", "glue:GetJobRun"]
    resources = [module.resolve_and_screen_job.job_arn]
  }
  statement {
    sid       = "Alert"
    actions   = ["sns:Publish"]
    resources = [module.lake.alerts_topic_arn]
  }
}

module "resolution_trigger_lambda" {
  source           = "../../modules/lambda_zip"
  name             = "meridian-resolution-trigger"
  zip_path         = "${local.build_dir}/lambda_bundle.zip"
  handler          = "resolution_trigger_handler.lambda_handler"
  policy_json      = data.aws_iam_policy_document.resolution_trigger.json
  alerts_topic_arn = module.lake.alerts_topic_arn
  timeout          = 120
  memory_mb        = 256
  environment = {
    MERIDIAN_LAKE_URI         = "s3://${module.lake.lake_bucket}"
    MERIDIAN_STATE_BACKEND    = "dynamodb"
    MERIDIAN_STATE_TABLE      = module.lake.state_table_name
    MERIDIAN_ALERTS_TOPIC_ARN = module.lake.alerts_topic_arn
    MERIDIAN_GLUE_JOB         = module.resolve_and_screen_job.job_name
  }
}

# ---------- event chains (topic+queue+dlq per prefix) ----------

module "chain_sdn_updated" {
  source              = "../../modules/event_chain"
  name                = "sdn-updated"
  bucket_arn          = module.lake.lake_bucket_arn
  attach_consumer     = true
  consumer_lambda_arn = module.resolution_trigger_lambda.function_arn
  consumer_role_name  = module.resolution_trigger_lambda.role_name
  alerts_topic_arn    = module.lake.alerts_topic_arn
}

module "chain_customer_batch" {
  source              = "../../modules/event_chain"
  name                = "customer-batch"
  bucket_arn          = module.lake.lake_bucket_arn
  attach_consumer     = true
  consumer_lambda_arn = module.resolution_trigger_lambda.function_arn
  consumer_role_name  = module.resolution_trigger_lambda.role_name
  alerts_topic_arn    = module.lake.alerts_topic_arn
}

# aws_s3_bucket_notification is bucket-global: ALL prefix rules live here.
resource "aws_s3_bucket_notification" "lake" {
  bucket = module.lake.lake_bucket

  topic {
    id            = "sdn-updated"
    topic_arn     = module.chain_sdn_updated.topic_arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "bronze/ofac/sdn/"
  }

  topic {
    id            = "customer-batch"
    topic_arn     = module.chain_customer_batch.topic_arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "bronze/customers/incoming/"
    filter_suffix = "manifest.json"
  }

  topic {
    id            = "gold-published"
    topic_arn     = module.chain_gold_published.topic_arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "gold/screening_hits/"
    filter_suffix = ".parquet"
  }
}

# ---------- Glue job ----------

data "aws_iam_policy_document" "glue_job" {
  statement {
    sid     = "LakeReadWrite"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      module.lake.lake_bucket_arn,
      "${module.lake.lake_bucket_arn}/*",
    ]
  }
  statement {
    sid     = "LakeWriteCurated"
    actions = ["s3:PutObject"]
    resources = [
      "${module.lake.lake_bucket_arn}/silver/*",
      "${module.lake.lake_bucket_arn}/gold/*",
      "${module.lake.lake_bucket_arn}/manifests/*",
    ]
  }
  statement {
    sid     = "ArtifactsRead"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      module.lake.artifacts_bucket_arn,
      "${module.lake.artifacts_bucket_arn}/*",
    ]
  }
}

module "resolve_and_screen_job" {
  source           = "../../modules/glue_job"
  name             = "meridian-resolve-and-screen"
  script_s3_uri    = "s3://${module.lake.artifacts_bucket}/${aws_s3_object.glue_script.key}"
  policy_json      = data.aws_iam_policy_document.glue_job.json
  alerts_topic_arn = module.lake.alerts_topic_arn
  timeout_minutes  = 30

  default_arguments = {
    # meridian wheel + fully vendored dependency wheelhouse (INC-001):
    # Glue pip-installs these exact S3 wheels, nothing else.
    "--extra-py-files"         = local.extra_py_files
    "--MERIDIAN_LAKE_URI"      = "s3://${module.lake.lake_bucket}"
    "--MERIDIAN_STATE_BACKEND" = "dynamodb"
    "--MERIDIAN_STATE_TABLE"   = module.lake.state_table_name
  }
}
