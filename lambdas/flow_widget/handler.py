"""CloudWatch custom widget: live pipeline flow diagram.

Rendered inside the meridian-ops dashboard on every refresh. Queries each
component's real state and draws the connected node flow with status colors —
the architecture map and the health check in one glance.
"""
import os
from datetime import datetime, timezone

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
GLUE_JOB = "meridian-resolve-and-screen"
DLQS = [
    "meridian-sdn-updated-dlq",
    "meridian-customer-batch-dlq",
    "meridian-gold-published-dlq",
]

OK, WARN, CRIT = "#2E7D46", "#B07A18", "#C4453C"


def _node(svc: str, name: str, status: str, color: str) -> str:
    return (
        f'<td style="border:1.5px solid {color};border-radius:8px;padding:6px 10px;'
        f'background:rgba(127,127,127,0.06);min-width:105px">'
        f'<div style="font-size:9px;letter-spacing:1px;color:#888;text-transform:uppercase">{svc}</div>'
        f'<div style="font-size:12px;font-weight:600">{name}</div>'
        f'<div style="font-size:11px;color:{color};font-weight:600">{status}</div></td>'
    )


def _arrow() -> str:
    return '<td style="padding:0 4px;color:#2E8C96;font-weight:700;font-size:15px">&#8594;</td>'


def lambda_handler(event, context):
    session = boto3.session.Session(region_name=REGION)

    cw = session.client("cloudwatch")
    firing = {
        a["AlarmName"] for a in cw.describe_alarms(StateValue="ALARM")["MetricAlarms"]
    }

    logs = session.client("logs")
    streams = logs.describe_log_streams(
        logGroupName="/aws/lambda/meridian-ofac-ingest",
        orderBy="LastEventTime", descending=True, limit=1,
    )["logStreams"]
    ingest_age_h = 999.0
    if streams:
        last = datetime.fromtimestamp(
            streams[0]["lastEventTimestamp"] / 1000, tz=timezone.utc
        )
        ingest_age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600

    glue = session.client("glue")
    runs = glue.get_job_runs(JobName=GLUE_JOB, MaxResults=1)["JobRuns"]
    run_state = runs[0]["JobRunState"] if runs else "NONE"
    run_batch = runs[0].get("Arguments", {}).get("--batch_id", "?")[-8:] if runs else "-"

    sqs = session.client("sqs")
    dlq_total = 0
    for name in DLQS:
        url = sqs.get_queue_url(QueueName=name)["QueueUrl"]
        dlq_total += int(
            sqs.get_queue_attributes(
                QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"]
            )["Attributes"]["ApproximateNumberOfMessages"]
        )

    sns = session.client("sns")
    subs = sns.list_subscriptions_by_topic(
        TopicArn=f"arn:aws:sns:{REGION}:470945861699:meridian-alerts"
    )["Subscriptions"]
    email_ok = any(s["SubscriptionArn"].startswith("arn:") for s in subs)

    ingest_color = OK if ingest_age_h < 12 else CRIT
    ingest_stat = f"ran {ingest_age_h:.1f}h ago" if ingest_age_h < 24 else "STALE"
    glue_ok = run_state in ("SUCCEEDED", "RUNNING", "STARTING")
    glue_color = OK if run_state == "SUCCEEDED" else (WARN if glue_ok else CRIT)
    chain_color = OK if dlq_total == 0 else CRIT
    chain_stat = "queues clear" if dlq_total == 0 else f"{dlq_total} in DLQ!"
    email_color = OK if email_ok else WARN
    email_stat = "delivering" if email_ok else "confirm pending"
    trigger_color = CRIT if "meridian-resolution-trigger-errors" in firing else OK

    healthy = (
        not firing and dlq_total == 0 and ingest_age_h < 12 and glue_ok and email_ok
    )
    banner_color = OK if healthy else CRIT
    banner = "PIPELINE HEALTHY" if healthy else "ATTENTION NEEDED"

    nodes = [
        _node("EventBridge", "6h schedule", "on schedule", OK),
        _arrow(),
        _node("Lambda", "ofac-ingest", ingest_stat, ingest_color),
        _arrow(),
        _node("S3 bronze", "raw, append-only", "immutable", OK),
        _arrow(),
        _node("SNS&#8594;SQS &#215;3", "event chains + DLQ", chain_stat, chain_color),
        _arrow(),
        _node("Lambda", "resolution-trigger", "validating", trigger_color),
        _arrow(),
        _node("Glue 1 DPU", "resolve-and-screen", f"{run_state} &#183; {run_batch}", glue_color),
        _arrow(),
        _node("S3 gold", "hits parquet + Athena", "queryable", OK),
        _arrow(),
        _node("Notifier", "&#128231; alert email", email_stat, email_color),
    ]

    return (
        '<div style="font-family:-apple-system,sans-serif">'
        f'<div style="display:inline-block;border-radius:999px;padding:3px 14px;'
        f'background:{banner_color};color:#fff;font-size:12px;font-weight:700;'
        f'margin-bottom:8px">&#9679; {banner}</div>'
        '<div style="overflow-x:auto"><table style="border-collapse:collapse">'
        f'<tr>{"".join(nodes)}</tr></table></div>'
        '<div style="font-size:10px;color:#888;margin-top:6px">'
        "Live component states &#183; refreshes with the dashboard &#183; "
        "red node &#8594; runbooks in docs/runbooks/</div></div>"
    )
