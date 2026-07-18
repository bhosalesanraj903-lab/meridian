"""Operator CLI: generate a synthetic customer batch and upload it to the
lake using the manifest-last protocol (CSVs first, manifest.json LAST so the
single S3 notification announces a complete batch).

Usage:
  python tools/upload_batch.py --count 5000 --seed 42 [--plant-sdn-hits 2]
  python tools/upload_batch.py ... --break-header   # game-day: force quarantine
"""
import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from meridian.config import Settings
from meridian.generator.customers import generate
from meridian.io import storage
from meridian.logs import get_logger, setup_logging

setup_logging()
log = get_logger("meridian.tools.upload_batch")

BATCH_FILES = ["crm_customers.csv", "loans_customers.csv", "legacy_customers.csv"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--plant-sdn-hits", type=int, default=0)
    ap.add_argument(
        "--break-header",
        action="store_true",
        help="corrupt the CRM header to exercise the quarantine path",
    )
    args = ap.parse_args()

    settings = Settings.from_env()
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch_prefix = f"{settings.bronze_customers_prefix}/batch_id={batch_id}"

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        summary = generate(
            args.count, args.seed, out_dir=out, plant_sdn_hits=args.plant_sdn_hits
        )
        if args.break_header:
            crm = out / "crm_customers.csv"
            crm.write_text(crm.read_text().replace("crm_id", "broken_id", 1))

        # CSVs first (includes _truth.csv for the quality gate), manifest LAST.
        for name in [*BATCH_FILES, "_truth.csv"]:
            storage.write_bytes(f"{batch_prefix}/{name}", (out / name).read_bytes())

        manifest = {
            "batch_id": batch_id,
            "files": {
                "crm_customers.csv": summary["crm"],
                "loans_customers.csv": summary["loans"],
                "legacy_customers.csv": summary["legacy"],
            },
            "generator_seed": args.seed,
            "planted_sdn_hits": args.plant_sdn_hits,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
        storage.write_bytes(
            f"{batch_prefix}/manifest.json", json.dumps(manifest, indent=2).encode()
        )

    log.info("Batch uploaded", extra={"batch_id": batch_id, "prefix": batch_prefix})
    print(json.dumps({"batch_id": batch_id, "batch_prefix": batch_prefix}, indent=2))


if __name__ == "__main__":
    main()
