"""Sanctions screening — Meridian pipeline #1, gold layer.

Matches resolved customer golden records against the latest OFAC SDN list and
writes screening hits as Parquet, partitioned by run_date.

Method:
  1. Collapse each resolution cluster to one canonical record (longest name
     variant wins — truncated legacy names lose; first non-null DOB).
  2. Keep SDN rows where sdn_type = 'individual' (vessels/entities need a
     different comparison model and are out of scope for pipeline 1).
  3. Block on a shared name token (DuckDB join) to keep pairs tractable, then
     score each candidate pair token-wise: for every customer name token, the
     best Jaro-Winkler match among SDN name tokens, averaged. Token-wise
     scoring is deliberate — SDN names carry extra middle names/patronymics
     ("BOUT, Viktor Anatolijevitch") that must not dilute a match on
     "viktor bout".
  4. Severity bands: STRONG >= 0.95, POSSIBLE 0.88-0.95, below discarded.
  5. DOB corroboration: OFAC embeds DOBs in remarks ("DOB 13 Jan 1967",
     sometimes several alternates). When the customer DOB year contradicts
     every SDN DOB year by more than 2 years, a STRONG hit demotes to
     POSSIBLE — name-only screening floods analysts with same-name/different-
     person hits, and DOB is the cheapest discriminator we hold on both sides.
     Hits are never dropped by DOB (list DOBs can be wrong/aliases).
  6. DOB promotion (audit finding, 2026-07-18): a near-miss name score
     (>= 0.90) WITH a corroborating DOB is stronger evidence than a perfect
     name with no DOB — promote to STRONG. `severity_basis` records whether
     severity came from the name score alone or a DOB promotion/demotion.
  7. Fan-out cap (audit finding, 2026-07-18): a customer whose name matches
     hundreds of SDN entries ("khan" problem) carries little signal per
     match. Keep only the top FANOUT_CAP matches per customer by score;
     `cluster_match_count` preserves the original fan-out for analysts.

The OFAC sdn.csv has no header row. Columns (per OFAC file spec):
  ent_num, sdn_name, sdn_type, program, title, call_sign, vess_type,
  tonnage, grt, vess_flag, vess_owner, remarks
Missing values are the literal string "-0- ". Names are "LAST, First".
"""
from __future__ import annotations

import io
import json
import re
import uuid
from datetime import datetime, timezone

import duckdb
import pandas as pd

from meridian.config import Settings
from meridian.io import storage
from meridian.logs import get_logger

log = get_logger("meridian.screening")

SDN_COLUMNS = [
    "ent_num", "sdn_name", "sdn_type", "program", "title", "call_sign",
    "vess_type", "tonnage", "grt", "vess_flag", "vess_owner", "remarks",
]

STRONG_THRESHOLD = 0.95
POSSIBLE_THRESHOLD = 0.88
# Near-miss name score that a corroborating DOB promotes to STRONG.
PROMOTE_THRESHOLD = 0.90
# Max SDN matches kept per customer cluster (top-N by score).
FANOUT_CAP = 25


def normalize_name(name: str) -> str:
    """'BOUT, Viktor' / 'viktor  bout' -> 'bout viktor' (sorted tokens)."""
    tokens = re.findall(r"[a-z]+", (name or "").lower())
    return " ".join(sorted(tokens))


def _name_score(customer_norm: str, sdn_norm: str) -> float:
    """Token-wise similarity: mean over customer tokens of the best
    Jaro-Winkler match among SDN tokens. Extra SDN middle names don't dilute
    the score; a customer token with no good SDN counterpart drags it down.
    """
    from rapidfuzz.distance import JaroWinkler

    cust_tokens = customer_norm.split()
    sdn_tokens = sdn_norm.split()
    if not cust_tokens or not sdn_tokens:
        return 0.0
    best = [
        max(JaroWinkler.similarity(ct, st) for st in sdn_tokens)
        for ct in cust_tokens
    ]
    return sum(best) / len(best)


_DOB_YEAR_RE = re.compile(r"DOB[^;]*?(\d{4})", re.IGNORECASE)


def extract_sdn_dob_years(remarks: str) -> list[int]:
    """Pull every DOB year out of an SDN remarks field ('' if none)."""
    return [int(y) for y in _DOB_YEAR_RE.findall(remarks or "")]


def dob_corroboration(customer_dob: str, sdn_dob_years: list[int]) -> str:
    """'match' | 'mismatch' | 'unknown' — +/-2 years tolerates list noise."""
    if not customer_dob or not sdn_dob_years:
        return "unknown"
    try:
        year = int(str(customer_dob)[:4])
    except ValueError:
        return "unknown"
    return (
        "match"
        if min(abs(year - y) for y in sdn_dob_years) <= 2
        else "mismatch"
    )


def load_latest_sdn(settings: Settings) -> pd.DataFrame:
    """Read the newest landed SDN file from bronze; individuals only."""
    landed = storage.list_prefix(settings.bronze_ofac_prefix)
    if not landed:
        raise FileNotFoundError(
            f"No SDN files under {settings.bronze_ofac_prefix} — run ingestion first"
        )
    latest = landed[-1]
    sdn = pd.read_csv(
        io.BytesIO(storage.read_bytes(latest)),
        names=SDN_COLUMNS,
        dtype=str,
        header=None,
    )
    sdn = sdn.replace(re.compile(r"^-0-\s*$"), "").fillna("")
    individuals = sdn[sdn["sdn_type"].str.strip().str.lower() == "individual"].copy()
    individuals["name_norm"] = individuals["sdn_name"].map(normalize_name)
    individuals = individuals[individuals["name_norm"] != ""]
    individuals["sdn_dob_years"] = individuals["remarks"].map(
        lambda r: ",".join(str(y) for y in extract_sdn_dob_years(r))
    )
    log.info(
        "Loaded SDN list",
        extra={
            "sdn_uri": latest,
            "rows_total": len(sdn),
            "rows_individuals": len(individuals),
        },
    )
    return individuals[
        ["ent_num", "sdn_name", "program", "name_norm", "sdn_dob_years"]
    ]


def canonical_customers(clusters: pd.DataFrame) -> pd.DataFrame:
    """One row per cluster: longest first/last name variant, first non-null DOB."""
    df = clusters.fillna("")

    def longest(series: pd.Series) -> str:
        vals = [v for v in series if v]
        return max(vals, key=len) if vals else ""

    def first_nonnull(series: pd.Series) -> str:
        for v in series:
            if v:
                return v
        return ""

    canon = df.groupby("cluster_id").agg(
        first_name=("first_name", longest),
        last_name=("last_name", longest),
        dob=("dob", first_nonnull),
        n_members=("unique_id", "size"),
        member_ids=("unique_id", lambda s: ";".join(sorted(s))),
    ).reset_index()
    canon["name_norm"] = (canon["first_name"] + " " + canon["last_name"]).map(
        normalize_name
    )
    return canon[canon["name_norm"] != ""]


def screen(
    settings: Settings | None = None,
    clusters: pd.DataFrame | None = None,
    run_id: str | None = None,
    batch_id: str = "",
) -> dict:
    """Screen golden records against the latest SDN list; write gold Parquet.

    Returns a summary dict (counts by severity, output URI) for the manifest.
    """
    settings = settings or Settings.from_env()
    run_id = run_id or uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc)

    if clusters is None:
        clusters = pd.read_csv(
            io.BytesIO(
                storage.read_bytes(
                    f"{settings.silver_customers_prefix}/golden_records.csv"
                )
            ),
            dtype=str,
        )
    customers = canonical_customers(clusters)
    sdn = load_latest_sdn(settings)

    con = duckdb.connect()
    con.register("customers", customers)
    con.register("sdn", sdn)
    candidates = con.execute(
        """
        WITH cust_tokens AS (
            SELECT *, unnest(string_split(name_norm, ' ')) AS token FROM customers
        ),
        sdn_tokens AS (
            SELECT *, unnest(string_split(name_norm, ' ')) AS token FROM sdn
        )
        SELECT DISTINCT
            c.cluster_id, c.first_name, c.last_name, c.dob,
            c.n_members, c.member_ids, c.name_norm AS customer_name_norm,
            s.ent_num, s.sdn_name, s.program, s.name_norm AS sdn_name_norm,
            s.sdn_dob_years
        FROM cust_tokens c
        JOIN sdn_tokens s USING (token)
        WHERE length(token) >= 3
        """
    ).df()
    con.close()

    candidates["score"] = [
        _name_score(c, s)
        for c, s in zip(
            candidates["customer_name_norm"], candidates["sdn_name_norm"]
        )
    ]
    hits = (
        candidates[candidates["score"] >= POSSIBLE_THRESHOLD]
        .sort_values("score", ascending=False)
        .reset_index(drop=True)
    )

    hits["severity"] = "POSSIBLE"
    hits.loc[hits["score"] >= STRONG_THRESHOLD, "severity"] = "STRONG"
    hits["severity_basis"] = "name_score"
    hits["dob_corroboration"] = [
        dob_corroboration(
            dob, [int(y) for y in years.split(",") if y]
        )
        for dob, years in zip(hits["dob"].fillna(""), hits["sdn_dob_years"])
    ]
    demote = (hits["severity"] == "STRONG") & (hits["dob_corroboration"] == "mismatch")
    hits.loc[demote, ["severity", "severity_basis"]] = ["POSSIBLE", "dob_demoted"]
    promote = (
        (hits["severity"] == "POSSIBLE")
        & (hits["score"] >= PROMOTE_THRESHOLD)
        & (hits["dob_corroboration"] == "match")
    )
    hits.loc[promote, ["severity", "severity_basis"]] = ["STRONG", "dob_promoted"]

    # Fan-out cap: common names ("khan") match hundreds of SDN entries with
    # little signal each. Keep the top FANOUT_CAP per customer by score
    # (deterministic tie-break on ent_num); record the original fan-out.
    hits["cluster_match_count"] = (
        hits.groupby("cluster_id")["ent_num"].transform("size").astype("int64")
    )
    n_before = len(hits)
    hits = (
        hits.sort_values(
            ["cluster_id", "score", "ent_num"], ascending=[True, False, True]
        )
        .groupby("cluster_id", group_keys=False)
        .head(FANOUT_CAP)
        .sort_values("score", ascending=False)
        .reset_index(drop=True)
    )
    n_capped = n_before - len(hits)

    hits.insert(0, "hit_id", [uuid.uuid4().hex for _ in range(len(hits))])
    hits.insert(1, "run_id", run_id)
    hits.insert(2, "batch_id", batch_id)
    hits["screened_at"] = now.isoformat()

    run_date = now.strftime("%Y-%m-%d")
    out_uri = (
        f"{settings.gold_hits_prefix}/run_date={run_date}/hits_{run_id}.parquet"
    )
    buf = io.BytesIO()
    hits.to_parquet(buf, index=False)
    storage.write_bytes(out_uri, buf.getvalue())

    summary = {
        "run_id": run_id,
        "batch_id": batch_id,
        "run_date": run_date,
        "customers_screened": int(len(customers)),
        "sdn_individuals": int(len(sdn)),
        "hits_total": int(len(hits)),
        "hits_strong": int((hits["severity"] == "STRONG").sum()),
        "hits_possible": int((hits["severity"] == "POSSIBLE").sum()),
        "hits_promoted": int((hits["severity_basis"] == "dob_promoted").sum()),
        "hits_demoted": int((hits["severity_basis"] == "dob_demoted").sum()),
        "hits_capped": int(n_capped),
        "hits_uri": out_uri,
    }
    log.info("Screening complete", extra=summary)
    return summary


if __name__ == "__main__":
    from meridian.logs import setup_logging

    setup_logging()
    print(json.dumps(screen(), indent=2))
