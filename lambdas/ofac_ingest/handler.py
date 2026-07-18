"""Lambda handler: OFAC SDN ingest. Thin wrapper — all logic in meridian.*.

Triggered by EventBridge Scheduler every 6 hours. Configuration via env vars
(MERIDIAN_LAKE_URI, MERIDIAN_STATE_BACKEND=dynamodb, ...). A changed SDN list
lands in bronze; the S3 ObjectCreated notification carries the event onward.
"""
from meridian.ingestion.ofac import run
from meridian.logs import setup_logging

setup_logging()


def lambda_handler(event, context):
    return run()
