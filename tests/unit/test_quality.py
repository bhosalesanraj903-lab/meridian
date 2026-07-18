"""Data-quality gate tests: valid batch passes, broken batches quarantine."""
import json

from meridian.generator.customers import generate
from meridian.io import storage
from meridian.quality.checks import quarantine_batch, validate_batch


def _make_batch(tmp_path, batch_id="batch_001", count=200):
    batch_dir = tmp_path / "incoming" / batch_id
    summary = generate(count, seed=5, out_dir=batch_dir)
    manifest = {
        "batch_id": batch_id,
        "files": {
            "crm_customers.csv": summary["crm"],
            "loans_customers.csv": summary["loans"],
            "legacy_customers.csv": summary["legacy"],
        },
        "generator_seed": 5,
    }
    return str(batch_dir), manifest


def test_valid_batch_passes(tmp_path):
    batch_prefix, manifest = _make_batch(tmp_path)
    result = validate_batch(batch_prefix, manifest)
    assert result.ok, result.errors
    assert result.row_counts["crm_customers.csv"] == manifest["files"]["crm_customers.csv"]


def test_missing_file_fails(tmp_path):
    batch_prefix, manifest = _make_batch(tmp_path)
    (tmp_path / "incoming" / "batch_001" / "loans_customers.csv").unlink()
    result = validate_batch(batch_prefix, manifest)
    assert not result.ok
    assert any("loans_customers.csv: file missing" in e for e in result.errors)


def test_header_mismatch_fails(tmp_path):
    batch_prefix, manifest = _make_batch(tmp_path)
    crm = tmp_path / "incoming" / "batch_001" / "crm_customers.csv"
    lines = crm.read_text().splitlines()
    lines[0] = lines[0].replace("crm_id", "id")
    crm.write_text("\n".join(lines))
    result = validate_batch(batch_prefix, manifest)
    assert not result.ok
    assert any("header mismatch" in e for e in result.errors)


def test_row_count_below_expectation_fails(tmp_path):
    batch_prefix, manifest = _make_batch(tmp_path)
    manifest["files"]["crm_customers.csv"] += 50
    result = validate_batch(batch_prefix, manifest)
    assert not result.ok
    assert any("rows <" in e for e in result.errors)


def test_unknown_file_set_fails(tmp_path):
    batch_prefix, _ = _make_batch(tmp_path)
    result = validate_batch(batch_prefix, {"batch_id": "x", "files": {"other.csv": 1}})
    assert not result.ok


def test_quarantine_copies_batch_with_reason(tmp_path):
    batch_prefix, manifest = _make_batch(tmp_path)
    dest = quarantine_batch(
        batch_prefix, str(tmp_path / "quarantine"), reason=["header mismatch"]
    )
    files = storage.list_prefix(dest)
    names = {f.rsplit("/", 1)[-1] for f in files}
    assert "crm_customers.csv" in names
    assert "_quarantine_reason.json" in names
    reason = json.loads(storage.read_bytes(f"{dest}/_quarantine_reason.json"))
    assert reason["errors"] == ["header mismatch"]
