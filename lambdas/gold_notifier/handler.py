"""Lambda handler: gold notifier.

Consumes S3 ObjectCreated events for gold/screening_hits/*.parquet (via
SNS->SQS). Reads the run manifest matching the landed file's run_id and
publishes a human-readable hit summary to the alerts topic. STRONG hits get
an URGENT-prefixed subject.

This is the tutorial pattern's second event chain, repurposed: with explicit
catalog tables + partition projection (ADR-002) there is no crawler to
trigger — the gold partition is already queryable — so the consumer's job is
telling a human what just landed.
"""
import json
import os
import re
from urllib.parse import unquote_plus

import boto3

from meridian.config import Settings
from meridian.logs import get_logger, setup_logging
from meridian.manifest import read_run_manifest

setup_logging()
log = get_logger("meridian.gold_notifier")

RUN_ID_RE = re.compile(r"hits_([0-9a-f]+)\.parquet$")


def lambda_handler(event, context):
    settings = Settings.from_env()
    sns = boto3.client("sns", region_name=settings.aws_region)

    for record in event.get("Records", []):
        s3_event = json.loads(record["body"])
        for s3_record in s3_event.get("Records", []):
            key = unquote_plus(s3_record["s3"]["object"]["key"])
            match = RUN_ID_RE.search(key)
            if not match:
                log.warning("No run_id in key — ignoring", extra={"key": key})
                continue
            run_id = match.group(1)
            manifest = read_run_manifest(settings, run_id)
            screening = manifest.get("screening", {})
            strong = screening.get("hits_strong", 0)
            subject = (
                f"[meridian]{' URGENT:' if strong else ''} run {run_id} — "
                f"{strong} STRONG / {screening.get('hits_possible', 0)} POSSIBLE hits"
            )
            body = {
                "run_id": run_id,
                "batch_id": manifest.get("batch_id"),
                "trigger_reason": manifest.get("trigger_reason"),
                "customers_screened": screening.get("customers_screened"),
                "hits_strong": strong,
                "hits_possible": screening.get("hits_possible"),
                "hits_uri": screening.get("hits_uri"),
                "athena_hint": (
                    "SELECT * FROM meridian.gold_screening_hits WHERE run_id = "
                    f"'{run_id}' AND severity = 'STRONG' ORDER BY score DESC"
                ),
            }
            sns.publish(
                TopicArn=os.environ["MERIDIAN_ALERTS_TOPIC_ARN"],
                Subject=subject[:100],
                Message=json.dumps(body, indent=2),
            )
            log.info("Published run summary", extra=body)
    return {"ok": True}
