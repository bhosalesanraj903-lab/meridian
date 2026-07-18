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
import subprocess
import sys
import uuid
from datetime import datetime, timezone

PRECISION_FLOOR = 0.95
RECALL_FLOOR = 0.90


def bootstrap_deps(artifacts_bucket: str) -> None:
    """Install the vendored wheelhouse in ONE pip call with --no-index.

    INC-001: Glue's own extra-py-files installer runs pip once per wheel and
    re-resolves dependencies from PyPI each time, where pyarrow/igraph resolve
    to sdists that fail to compile. Downloading the wheelhouse ourselves and
    installing with --no-index makes PyPI physically unreachable: every
    requirement resolves inside the wheelhouse or the job fails loudly.
    """
    import boto3  # preinstalled on Glue Python Shell

    wheel_dir = "/tmp/wheelhouse"
    os.makedirs(wheel_dir, exist_ok=True)
    s3 = boto3.client("s3")
    wheels = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=artifacts_bucket, Prefix="wheels/"):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".whl"):
                dest = os.path.join(wheel_dir, os.path.basename(obj["Key"]))
                s3.download_file(artifacts_bucket, obj["Key"], dest)
                wheels.append(dest)
    if not wheels:
        sys.exit(f"No wheels found under s3://{artifacts_bucket}/wheels/")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", "--no-index",
         "--find-links", wheel_dir] + wheels
    )
    print(f"bootstrap: installed {len(wheels)} wheels from s3://{artifacts_bucket}/wheels/")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch_id", required=True)
    parser.add_argument("--batch_prefix", required=True)
    parser.add_argument("--trigger_reason", default="unknown")
    parser.add_argument("--MERIDIAN_ARTIFACTS_BUCKET", dest="artifacts_bucket", default="")
    parser.add_argument("--MERIDIAN_LAKE_URI", dest="lake_uri", default="")
    parser.add_argument("--MERIDIAN_STATE_BACKEND", dest="state_backend", default="")
    parser.add_argument("--MERIDIAN_STATE_TABLE", dest="state_table", default="")
    args, _ = parser.parse_known_args()

    if args.artifacts_bucket:
        bootstrap_deps(args.artifacts_bucket)

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
