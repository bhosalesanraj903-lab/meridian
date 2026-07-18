"""Generator determinism + pathology presence checks."""
import csv
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generator.generate_customers import generate


def test_deterministic(tmp_path):
    s1 = generate(500, seed=7, out_dir=tmp_path / "a")
    s2 = generate(500, seed=7, out_dir=tmp_path / "b")
    for name in ["crm_customers.csv", "loans_customers.csv", "legacy_customers.csv"]:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    assert s1["crm"] == s2["crm"]


def test_pathologies_present(tmp_path):
    generate(2000, seed=42, out_dir=tmp_path)
    legacy = list(csv.DictReader((tmp_path / "legacy_customers.csv").open()))
    dobs = [r["birth_dt"] for r in legacy]
    assert "" in dobs, "expected missing DOBs in legacy"
    assert "1900-01-01" in dobs, "expected sentinel DOBs in legacy"
    ids = [r["cust_no"] for r in legacy]
    assert len(ids) > len(set(ids)), "expected duplicate rows in legacy"


def test_truth_mapping_written(tmp_path):
    generate(300, seed=1, out_dir=tmp_path)
    truth = list(csv.DictReader((tmp_path / "_truth.csv").open()))
    assert len(truth) == 300
