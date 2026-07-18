# M4 — gold event chain + notifier + explicit catalog tables (ADR-002:
# partition projection on run_date, no crawler, no MSCK).

# ---------- gold-published chain + notifier ----------

data "aws_iam_policy_document" "gold_notifier" {
  statement {
    sid       = "ManifestRead"
    actions   = ["s3:GetObject"]
    resources = ["${module.lake.lake_bucket_arn}/manifests/*"]
  }
  statement {
    sid       = "Alert"
    actions   = ["sns:Publish"]
    resources = [module.lake.alerts_topic_arn]
  }
}

module "gold_notifier_lambda" {
  source           = "../../modules/lambda_zip"
  name             = "meridian-gold-notifier"
  zip_path         = "${local.build_dir}/lambda_bundle.zip"
  handler          = "gold_notifier_handler.lambda_handler"
  policy_json      = data.aws_iam_policy_document.gold_notifier.json
  alerts_topic_arn = module.lake.alerts_topic_arn
  timeout          = 60
  memory_mb        = 256
  environment = {
    MERIDIAN_LAKE_URI         = "s3://${module.lake.lake_bucket}"
    MERIDIAN_ALERTS_TOPIC_ARN = module.lake.alerts_topic_arn
  }
}

module "chain_gold_published" {
  source              = "../../modules/event_chain"
  name                = "gold-published"
  bucket_arn          = module.lake.lake_bucket_arn
  attach_consumer     = true
  consumer_lambda_arn = module.gold_notifier_lambda.function_arn
  consumer_role_name  = module.gold_notifier_lambda.role_name
  alerts_topic_arn    = module.lake.alerts_topic_arn
}

# ---------- catalog tables (schemas owned here, in code) ----------

locals {
  hits_columns = [
    { name = "hit_id", type = "string" },
    { name = "run_id", type = "string" },
    { name = "batch_id", type = "string" },
    { name = "cluster_id", type = "string" },
    { name = "first_name", type = "string" },
    { name = "last_name", type = "string" },
    { name = "dob", type = "string" },
    { name = "n_members", type = "bigint" },
    { name = "member_ids", type = "string" },
    { name = "customer_name_norm", type = "string" },
    { name = "ent_num", type = "string" },
    { name = "sdn_name", type = "string" },
    { name = "program", type = "string" },
    { name = "sdn_name_norm", type = "string" },
    { name = "sdn_dob_years", type = "string" },
    { name = "score", type = "double" },
    { name = "severity", type = "string" },
    { name = "dob_corroboration", type = "string" },
    { name = "screened_at", type = "string" },
  ]
}

resource "aws_glue_catalog_table" "gold_screening_hits" {
  database_name = module.lake.glue_database
  name          = "gold_screening_hits"
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"                    = "parquet"
    "projection.enabled"                = "true"
    "projection.run_date.type"          = "date"
    "projection.run_date.format"        = "yyyy-MM-dd"
    "projection.run_date.range"         = "2026-07-01,NOW"
    "projection.run_date.interval"      = "1"
    "projection.run_date.interval.unit" = "DAYS"
    "storage.location.template"         = "s3://${module.lake.lake_bucket}/gold/screening_hits/run_date=$${run_date}/"
  }

  partition_keys {
    name = "run_date"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${module.lake.lake_bucket}/gold/screening_hits/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = local.hits_columns
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}
