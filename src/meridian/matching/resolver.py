"""Meridian customer entity resolution (Pipeline 1, silver layer).

Takes the three raw source extracts (CRM, loans, legacy — each with its own
corruption profile), normalizes them to a common schema, runs Splink
(link_and_dedupe, DuckDB backend) to cluster records belonging to the same
real person, and writes:

  <lake>/silver/customers/golden_records.csv   cluster_id -> member records
  <lake>/silver/customers/eval_report.json     pairwise precision/recall vs truth

Design notes (these are interview answers — keep them true):
  * Normalization is deliberately separate from matching: fix formats
    (name order, date formats, casing) deterministically BEFORE the
    probabilistic model, so Splink spends its power on genuine ambiguity
    (typos, nicknames, missing DOBs), not on solvable format noise.
  * Nickname canonicalization uses a dictionary (Bob->Robert). Real
    compliance teams do exactly this; it is not cheating, it is domain
    knowledge encoded as a rule.
  * Blocking on last_name OR zip OR dob keeps candidate pairs tractable
    while keeping recall: a pair only needs to survive ONE blocking rule.
  * Evaluation against generator ground truth reports pairwise precision
    and recall — the honest metric. Tune thresholds with eyes open.
"""
from __future__ import annotations

import io
import json
import re
from itertools import combinations

import pandas as pd
import splink.comparison_library as cl
from splink import DuckDBAPI, Linker, SettingsCreator, block_on

from meridian.config import Settings
from meridian.io import storage

# Reverse nickname map: nickname -> canonical
NICK_TO_CANONICAL = {
    "jim": "james", "jon": "john", "bob": "robert", "mike": "michael",
    "bill": "william", "liz": "elizabeth", "rick": "richard", "joe": "joseph",
    "tom": "thomas", "chuck": "charles", "chris": "christopher",
    "dan": "daniel", "matt": "matthew", "peggy": "margaret", "jen": "jennifer",
}


def _canon_first(name: str) -> str:
    n = (name or "").strip().lower()
    return NICK_TO_CANONICAL.get(n, n)


def _norm_street(s: str) -> str:
    """Lowercase, expand/strip street-type words, sort tokens.

    Token-sorting makes '2287 Main St' and 'main st 2287' compare equal —
    the legacy system stores number-last.
    """
    s = (s or "").lower()
    s = re.sub(r"\b(street|st)\b", "st", s)
    s = re.sub(r"\b(avenue|ave)\b", "ave", s)
    s = re.sub(r"\b(road|rd)\b", "rd", s)
    s = re.sub(r"\b(lane|ln)\b", "ln", s)
    s = re.sub(r"\b(drive|dr)\b", "dr", s)
    s = re.sub(r"\b(boulevard|blvd)\b", "blvd", s)
    s = re.sub(r"\b(court|ct)\b", "ct", s)
    tokens = sorted(re.findall(r"[a-z0-9]+", s))
    return " ".join(tokens)


def _read_csv(uri: str) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(storage.read_bytes(uri)), dtype=str).fillna("")


def load_and_normalize(raw_prefix: str) -> dict[str, pd.DataFrame]:
    """Return {alias: normalized frame} with the common matching schema."""
    frames: dict[str, pd.DataFrame] = {}

    crm = _read_csv(f"{raw_prefix}/crm_customers.csv")
    parts = crm["full_name"].str.strip().str.split(" ", n=1, expand=True)
    frames["crm"] = pd.DataFrame(
        {
            "unique_id": crm["crm_id"],
            "first_name": parts[0].map(_canon_first),
            "last_name": parts[1].str.lower().str.strip(),
            "dob": crm["dob"],
            "street": crm["address"].map(_norm_street),
            "city": crm["city"].str.lower().str.strip(),
            "zip": crm["zip"],
        }
    )

    loans = _read_csv(f"{raw_prefix}/loans_customers.csv")
    nm = loans["name"].str.split(",", n=1, expand=True)
    dob_iso = pd.to_datetime(
        loans["date_of_birth"], format="%m/%d/%Y", errors="coerce"
    ).dt.strftime("%Y-%m-%d").fillna("")
    frames["loans"] = pd.DataFrame(
        {
            "unique_id": loans["loan_cust_id"],
            "first_name": nm[1].fillna("").map(_canon_first),
            "last_name": nm[0].str.lower().str.strip(),
            "dob": dob_iso,
            "street": loans["addr_line1"].map(_norm_street),
            "city": loans["addr_city"].str.lower().str.strip(),
            "zip": loans["addr_zip"],
        }
    )

    legacy = _read_csv(f"{raw_prefix}/legacy_customers.csv")
    dob = legacy["birth_dt"].replace("1900-01-01", "")  # sentinel -> missing
    frames["legacy"] = pd.DataFrame(
        {
            "unique_id": "LG-" + legacy["cust_no"],
            "first_name": legacy["fname"].map(_canon_first),
            "last_name": legacy["lname"].str.lower().str.strip(),
            "dob": dob,
            "street": legacy["street"].map(_norm_street),
            "city": legacy["city"].str.lower().str.strip(),
            "zip": legacy["zip5"].replace("00000", ""),
        }
    )

    for alias, df in frames.items():
        frames[alias] = df.replace("", None)
    return frames


def build_linker(frames: dict[str, pd.DataFrame]) -> Linker:
    settings = SettingsCreator(
        link_type="link_and_dedupe",
        blocking_rules_to_generate_predictions=[
            block_on("last_name"),
            block_on("zip"),
            block_on("dob"),
        ],
        comparisons=[
            cl.NameComparison("first_name"),
            cl.NameComparison("last_name"),
            cl.DateOfBirthComparison("dob", input_is_string=True),
            cl.LevenshteinAtThresholds("street", 2),
            cl.ExactMatch("city").configure(term_frequency_adjustments=True),
            cl.ExactMatch("zip"),
        ],
        retain_intermediate_calculation_columns=False,
    )
    return Linker(
        list(frames.values()),
        settings,
        db_api=DuckDBAPI(),
        input_table_aliases=list(frames.keys()),
    )


def train(linker: Linker) -> None:
    deterministic = [
        "l.last_name = r.last_name and l.dob = r.dob and l.zip = r.zip",
        "l.first_name = r.first_name and l.last_name = r.last_name and l.dob = r.dob",
    ]
    linker.training.estimate_probability_two_random_records_match(
        deterministic, recall=0.7
    )
    # INC-000: splink 4.0.16 sets salting_partitions = cpu_count() when
    # max_pairs>1e4 on duckdb; on a single-CPU machine that yields 1 partition
    # and raises "Salting partitions must be > 1". Fall back below the salting
    # threshold. Production Glue runs at 1 DPU (4 vCPU) never hit this; CI
    # runners and small VMs do.
    try:
        linker.training.estimate_u_using_random_sampling(max_pairs=5e5)
    except ValueError as err:
        if "Salting partitions" not in str(err):
            raise
        linker.training.estimate_u_using_random_sampling(max_pairs=9_000)
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("last_name", "zip")
    )
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("dob")
    )


def resolve(
    settings: Settings | None = None, threshold: float = 0.95
) -> tuple[pd.DataFrame, dict]:
    """Run resolution; write silver outputs; return (clusters, eval_report)."""
    settings = settings or Settings.from_env()
    raw_prefix = f"{settings.lake_uri}/bronze/customers"
    frames = load_and_normalize(raw_prefix)
    linker = build_linker(frames)
    train(linker)
    predictions = linker.inference.predict(threshold_match_probability=0.5)
    clusters = linker.clustering.cluster_pairwise_predictions_at_threshold(
        predictions, threshold_match_probability=threshold
    ).as_pandas_dataframe()

    report = evaluate(clusters, raw_prefix)
    report["threshold"] = threshold
    report["n_clusters"] = int(clusters["cluster_id"].nunique())
    report["n_records"] = int(len(clusters))

    out_prefix = settings.silver_customers_prefix
    storage.write_bytes(
        f"{out_prefix}/golden_records.csv", clusters.to_csv(index=False).encode()
    )
    storage.write_bytes(
        f"{out_prefix}/eval_report.json", json.dumps(report, indent=2).encode()
    )
    return clusters, report


def evaluate(clusters: pd.DataFrame, raw_prefix: str) -> dict:
    """Pairwise precision/recall against generator ground truth."""
    truth = _read_csv(f"{raw_prefix}/_truth.csv")

    true_pairs: set[frozenset] = set()
    for _, row in truth.iterrows():
        ids = [
            i
            for i in [
                row["crm_id"],
                row["loan_cust_id"],
                ("LG-" + row["cust_no"]) if row["cust_no"] else "",
            ]
            if i
        ]
        for a, b in combinations(ids, 2):
            true_pairs.add(frozenset((a, b)))

    pred_pairs: set[frozenset] = set()
    for _, grp in clusters.groupby("cluster_id"):
        ids = grp["unique_id"].tolist()
        for a, b in combinations(ids, 2):
            pred_pairs.add(frozenset((a, b)))

    tp = len(true_pairs & pred_pairs)
    precision = tp / len(pred_pairs) if pred_pairs else 0.0
    recall = tp / len(true_pairs) if true_pairs else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "true_pairs": len(true_pairs),
        "predicted_pairs": len(pred_pairs),
        "true_positives": tp,
        "pairwise_precision": round(precision, 4),
        "pairwise_recall": round(recall, 4),
        "pairwise_f1": round(f1, 4),
    }


if __name__ == "__main__":
    from meridian.logs import setup_logging

    setup_logging()
    _, _report = resolve()
    print(json.dumps(_report, indent=2))
