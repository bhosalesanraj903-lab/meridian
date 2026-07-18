"""Generator determinism + pathology presence checks."""
import csv

from meridian.generator.customers import PLANTED_SDN_IDENTITIES, generate


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


def test_planted_sdn_hits(tmp_path):
    generate(200, seed=3, out_dir=tmp_path, plant_sdn_hits=2)
    crm = list(csv.DictReader((tmp_path / "crm_customers.csv").open()))
    names = " | ".join(r["full_name"].lower() for r in crm)
    planted = [f"{f} {last}".lower() for f, last in PLANTED_SDN_IDENTITIES[:2]]
    # ~90% CRM coverage per person; with 2 plants at least one should surface
    assert any(p in names for p in planted), names[:500]
