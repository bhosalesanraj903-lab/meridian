"""End-to-end smoke test: generate -> resolve -> evaluate on a small book.

Slow-ish (~1 min: Splink EM training). Marked so CI can include it explicitly.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.mark.slow
def test_resolution_quality(tmp_path, monkeypatch):
    from generator.generate_customers import generate

    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/bronze/customers").mkdir(parents=True)
    generate(400, seed=11, out_dir=tmp_path / "data/bronze/customers")

    from matching.resolve_customers import resolve

    report = resolve(threshold=0.95)
    assert report["pairwise_precision"] > 0.95, report
    assert report["pairwise_recall"] > 0.90, report
    assert (tmp_path / "data/silver/customers/golden_records.csv").exists()
    assert (tmp_path / "data/silver/customers/eval_report.json").exists()
    print(json.dumps(report, indent=2))
