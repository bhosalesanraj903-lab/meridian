"""Glue Python Shell job: entity resolution + sanctions screening.

Started by the resolution-trigger Lambda with:
  --batch_id <id> --batch_prefix s3://.../bronze/customers/incoming/batch_id=<id>
  --trigger_reason customer_batch|sanctions_list_updated

Runs at 1 DPU (4 vCPU) — see ADR-004; the INC-000 fallback in the resolver
stays as defense in depth. Steps:
  1. Splink resolution over the batch's three source extracts.
  2. Quality gate: generator batches carry _truth.csv; precision/recall below
     floor fails the job (visible FAILED state -> alert) and writes no gold.
  3. Screening vs latest SDN bronze -> gold Parquet (run_date partition).
  4. Silver golden records Parquet + run manifest for the gold-notifier.
"""
import argparse
import io
import json
import os
import sys
import uuid
from datetime import datetime, timezone

PRECISION_FLOOR = 0.95
RECALL_FLOOR = 0.90


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch_id", required=True)
    parser.add_argument("--batch_prefix", required=True)
    parser.add_argument("--trigger_reason", default="unknown")
    parser.add_argument("--MERIDIAN_LAKE_URI", dest="lake_uri", default="")
    parser.add_argument("--MERIDIAN_STATE_BACKEND", dest="state_backend", default="")
    parser.add_argument("--MERIDIAN_STATE_TABLE", dest="state_table", default="")
    args, _ = parser.parse_known_args()

    for key, value in [
        ("MERIDIAN_LAKE_URI", args.lake_uri),
        ("MERIDIAN_STATE_BACKEND", args.state_backend),
        ("MERIDIAN_STATE_TABLE", args.state_table),
    ]:
        if value:
            os.environ[key] = value

    from meridian.config import Settings
    from meridian.io import storage
    from meridian.logs import get_logger, setup_logging
    from meridian.manifest import write_run_manifest
    from meridian.matching.resolver import resolve
    from meridian.screening.screen import screen

    setup_logging()
    log = get_logger("meridian.glue.resolve_and_screen")
    settings = Settings.from_env()
    run_id = uuid.uuid4().hex[:12]
    started = datetime.now(timezone.utc)

    log.info(
        "Job start",
        extra={
            "run_id": run_id,
            "batch_id": args.batch_id,
            "batch_prefix": args.batch_prefix,
            "trigger_reason": args.trigger_reason,
        },
    )

    clusters, report = resolve(settings, raw_prefix=args.batch_prefix)
    if report.get("evaluated"):
        precision = report["pairwise_precision"]
        recall = report["pairwise_recall"]
        if precision < PRECISION_FLOOR or recall < RECALL_FLOOR:
            log.error("Quality gate FAILED", extra={"run_id": run_id, **report})
            sys.exit(
                f"Quality gate failed: precision={precision} recall={recall} "
                f"(floors {PRECISION_FLOOR}/{RECALL_FLOOR}) — no gold written"
            )

    run_date = started.strftime("%Y-%m-%d")
    silver_uri = (
        f"{settings.silver_customers_prefix}/golden/run_date={run_date}/"
        f"golden_{run_id}.parquet"
    )
    buf = io.BytesIO()
    clusters.to_parquet(buf, index=False)
    storage.write_bytes(silver_uri, buf.getvalue())

    screen_summary = screen(
        settings, clusters=clusters, run_id=run_id, batch_id=args.batch_id
    )

    manifest_uri = write_run_manifest(
        settings,
        run_id,
        {
            "batch_id": args.batch_id,
            "batch_prefix": args.batch_prefix,
            "trigger_reason": args.trigger_reason,
            "started_at": started.isoformat(),
            "resolution": report,
            "silver_uri": silver_uri,
            "screening": screen_summary,
        },
    )
    log.info(
        "Job complete",
        extra={"run_id": run_id, "manifest_uri": manifest_uri, **screen_summary},
    )
    print(json.dumps({"run_id": run_id, "manifest_uri": manifest_uri}))


if __name__ == "__main__":
    main()
