"""Lambda handler: resolution trigger.

Consumes S3 ObjectCreated events (via SNS->SQS, raw delivery, batch size 1)
from two prefixes:
  bronze/customers/incoming/.../manifest.json  -> validate batch, start Glue
  bronze/ofac/sdn/                             -> whole-book rescan on latest batch

Validation failures quarantine the batch and alert — they do NOT raise, so
bad data never poisons the queue into the DLQ. Infrastructure errors DO
raise -> SQS retry x3 -> DLQ -> alarm.
"""
import json
import os
from datetime import datetime, timezone
from urllib.parse import unquote_plus

import boto3

from meridian.config import Settings
from meridian.io import storage
from meridian.logs import get_logger, setup_logging
from meridian.quality.checks import quarantine_batch, validate_batch
from meridian.state import state_store

setup_logging()
log = get_logger("meridian.trigger")

GLUE_JOB_NAME = os.environ.get("MERIDIAN_GLUE_JOB", "meridian-resolve-and-screen")


def _start_job(settings: Settings, batch_id: str, batch_prefix: str, reason: str):
    glue = boto3.client("glue", region_name=settings.aws_region)
    run = glue.start_job_run(
        JobName=GLUE_JOB_NAME,
        Arguments={
            "--batch_id": batch_id,
            "--batch_prefix": batch_prefix,
            "--trigger_reason": reason,
        },
    )
    log.info(
        "Started Glue run",
        extra={"batch_id": batch_id, "reason": reason, "glue_run_id": run["JobRunId"]},
    )


def _alert(settings: Settings, subject: str, body: dict) -> None:
    if settings.alerts_topic_arn:
        boto3.client("sns", region_name=settings.aws_region).publish(
            TopicArn=settings.alerts_topic_arn,
            Subject=subject[:100],
            Message=json.dumps(body, indent=2),
        )


def _latest_batch_prefix(settings: Settings) -> str:
    """Newest batch under incoming/ (batch ids are timestamped => sorted)."""
    uris = storage.list_prefix(settings.bronze_customers_prefix)
    manifests = [u for u in uris if u.endswith("/manifest.json")]
    return manifests[-1].rsplit("/", 1)[0] if manifests else ""


def _handle_customer_batch(settings: Settings, store, bucket: str, key: str) -> None:
    batch_prefix = f"s3://{bucket}/{key.rsplit('/', 1)[0]}"
    manifest = json.loads(storage.read_bytes(f"s3://{bucket}/{key}"))
    batch_id = manifest.get("batch_id", "unknown")

    result = validate_batch(batch_prefix, manifest)
    if not result.ok:
        dest = quarantine_batch(
            batch_prefix, settings.quarantine_prefix, result.errors
        )
        log.error(
            "Batch failed validation -> quarantined",
            extra={"batch_id": batch_id, "errors": result.errors, "dest": dest},
        )
        _alert(
            settings,
            f"[meridian] batch {batch_id} QUARANTINED",
            {"batch_id": batch_id, "errors": result.errors, "quarantine": dest},
        )
        return

    if not store.claim_batch(
        batch_id,
        {"claimed_at": datetime.now(timezone.utc).isoformat(), "prefix": batch_prefix},
    ):
        log.info("Batch already claimed — duplicate event", extra={"batch_id": batch_id})
        return

    _start_job(settings, batch_id, batch_prefix, "customer_batch")


def _handle_sdn_update(settings: Settings, store, key: str) -> None:
    batch_prefix = _latest_batch_prefix(settings)
    if not batch_prefix:
        log.info("SDN updated but no customer batches exist yet — nothing to rescan")
        return
    sdn_tag = key.rsplit("/", 1)[-1].removesuffix(".csv")
    rescan_id = f"rescan-{sdn_tag}"
    if not store.claim_batch(
        rescan_id,
        {"claimed_at": datetime.now(timezone.utc).isoformat(), "prefix": batch_prefix},
    ):
        log.info("Rescan already claimed", extra={"batch_id": rescan_id})
        return
    _start_job(settings, rescan_id, batch_prefix, "sanctions_list_updated")


def lambda_handler(event, context):
    settings = Settings.from_env()
    store = state_store(settings)

    for record in event.get("Records", []):
        s3_event = json.loads(record["body"])
        for s3_record in s3_event.get("Records", []):
            bucket = s3_record["s3"]["bucket"]["name"]
            # S3 event keys are URL-encoded ('batch_id=' arrives as 'batch_id%3D')
            key = unquote_plus(s3_record["s3"]["object"]["key"])
            log.info("Processing S3 event", extra={"bucket": bucket, "key": key})
            if key.endswith("manifest.json"):
                _handle_customer_batch(settings, store, bucket, key)
            elif "/ofac/sdn/" in key:
                _handle_sdn_update(settings, store, key)
            else:
                log.warning("Unrecognized key — ignoring", extra={"key": key})
    return {"ok": True}
