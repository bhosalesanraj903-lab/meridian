"""End-to-end smoke test: generate -> resolve -> evaluate on a small book.

Slow-ish (~1 min: Splink EM training). Marked so PR CI excludes it; the
weekly scheduled CI job runs it to keep the quality floor asserted.
"""
import json

import pytest

from meridian.config import Settings
from meridian.generator.customers import generate
from meridian.matching.resolver import resolve


@pytest.mark.slow
def test_resolution_quality(tmp_path):
    lake = tmp_path / "data"
    generate(400, seed=11, out_dir=lake / "bronze" / "customers")

    settings = Settings(
        lake_uri=str(lake),
        user_agent="test",
        state_backend="local",
        state_table="",
        aws_region="us-east-1",
        alerts_topic_arn="",
    )
    _, report = resolve(settings, threshold=0.95)
    assert report["pairwise_precision"] > 0.95, report
    assert report["pairwise_recall"] > 0.90, report
    assert (lake / "silver/customers/golden_records.csv").exists()
    assert (lake / "silver/customers/eval_report.json").exists()
    print(json.dumps(report, indent=2))
