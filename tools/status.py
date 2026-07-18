"""Operator CLI: one-shot pipeline health check (`make status`).

Prints the same signals the daily triage ritual reads from the meridian-ops
dashboard: alarm states, ingest freshness, last screening run, DLQ depths,
and the newest gold partition. Requires AWS credentials (aws login).
"""
from __future__ import annotations

from datetime import datetime, timezone

import boto3

REGION = "us-east-1"
LAKE = "meridian-lake-use1-470945861699"
GLUE_JOB = "meridian-resolve-and-screen"
DLQS = [
    "meridian-sdn-updated-dlq",
    "meridian-customer-batch-dlq",
    "meridian-gold-published-dlq",
]


def _age(ts) -> str:
    delta = datetime.now(timezone.utc) - ts
    hours = delta.total_seconds() / 3600
    return f"{hours:.1f}h ago"


def main() -> None:
    session = boto3.session.Session(region_name=REGION)
    ok = True

    cw = session.client("cloudwatch")
    firing = cw.describe_alarms(StateValue="ALARM")["MetricAlarms"]
    if firing:
        ok = False
        print(f"✗ ALARMS FIRING: {', '.join(a['AlarmName'] for a in firing)}")
    else:
        print("✓ alarms: all green")

    logs = session.client("logs")
    streams = logs.describe_log_streams(
        logGroupName="/aws/lambda/meridian-ofac-ingest",
        orderBy="LastEventTime", descending=True, limit=1,
    )["logStreams"]
    if streams:
        last = datetime.fromtimestamp(
            streams[0]["lastEventTimestamp"] / 1000, tz=timezone.utc
        )
        stale = (datetime.now(timezone.utc) - last).total_seconds() > 12 * 3600
        ok = ok and not stale
        print(f"{'✗' if stale else '✓'} ofac ingest: last activity {_age(last)}"
              f"{' — STALE (>12h)' if stale else ''}")
    else:
        ok = False
        print("✗ ofac ingest: no log activity found")

    glue = session.client("glue")
    runs = glue.get_job_runs(JobName=GLUE_JOB, MaxResults=1)["JobRuns"]
    if runs:
        run = runs[0]
        good = run["JobRunState"] == "SUCCEEDED"
        ok = ok and good
        print(f"{'✓' if good else '✗'} screening: last run {run['JobRunState']} "
              f"({_age(run['StartedOn'])}, "
              f"batch {run.get('Arguments', {}).get('--batch_id', '?')})")
    else:
        print("• screening: no runs yet")

    sqs = session.client("sqs")
    depths = []
    for name in DLQS:
        url = sqs.get_queue_url(QueueName=name)["QueueUrl"]
        n = int(sqs.get_queue_attributes(
            QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"]
        )["Attributes"]["ApproximateNumberOfMessages"])
        depths.append(n)
        if n:
            ok = False
    if any(depths):
        print(f"✗ DLQ depths: {dict(zip(DLQS, depths))} — see runbooks/dlq-redrive.md")
    else:
        print("✓ DLQs: all empty")

    s3 = session.client("s3")
    resp = s3.list_objects_v2(
        Bucket=LAKE, Prefix="gold/screening_hits/", MaxKeys=1000
    )
    parts = sorted({o["Key"].split("/")[2] for o in resp.get("Contents", [])})
    print(f"✓ gold partitions: {parts[-3:] if parts else 'none yet'}")

    print("—" * 40)
    print("PIPELINE HEALTHY" if ok else "ATTENTION NEEDED — check items marked ✗")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
