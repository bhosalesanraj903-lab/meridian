"""Screening engine tests with a planted-hit SDN fixture."""
import io

import pandas as pd

from meridian.io import storage
from meridian.screening.screen import (
    canonical_customers,
    dob_corroboration,
    extract_sdn_dob_years,
    load_latest_sdn,
    normalize_name,
    screen,
)


def _sdn_row(ent_num, name, sdn_type, program, remarks="-0- "):
    # sdn.csv is headerless with 12 columns; "-0- " marks missing values
    return (
        f'{ent_num},"{name}","{sdn_type}","{program}",'
        f'-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,"{remarks}"'
    )


SDN_FIXTURE = "\n".join(
    [
        _sdn_row(
            306,
            "BOUT, Viktor Anatolijevitch",
            "individual",
            "SDNT",
            remarks="DOB 13 Jan 1967; POB Dushanbe, Tajikistan",
        ),
        _sdn_row(4106, "ZAMBADA GARCIA, Ismael", "individual", "SDNTK"),
        _sdn_row(7000, "AEROCOM", "-0- ", "SDNT"),  # entity — must be excluded
        _sdn_row(8000, "SMITH SHIPPING LTD", "vessel", "SDGT"),
    ]
)


def _land_sdn(settings):
    storage.write_bytes(
        f"{settings.bronze_ofac_prefix}/sdn_20260718T000000Z_abc123.csv",
        SDN_FIXTURE.encode(),
    )


def _clusters(rows):
    return pd.DataFrame(
        rows, columns=["cluster_id", "unique_id", "first_name", "last_name", "dob"]
    )


def test_normalize_name_orders_tokens():
    assert normalize_name("BOUT, Viktor") == "bout viktor"
    assert normalize_name("viktor  BOUT") == "bout viktor"
    assert normalize_name("") == ""


def test_load_latest_sdn_filters_individuals(settings):
    _land_sdn(settings)
    sdn = load_latest_sdn(settings)
    assert set(sdn["sdn_name"]) == {
        "BOUT, Viktor Anatolijevitch",
        "ZAMBADA GARCIA, Ismael",
    }


def test_canonical_customers_prefers_longest_variant():
    clusters = _clusters(
        [
            ["c1", "CRM-1", "viktor", "bout", "1967-01-13"],
            ["c1", "LG-1", "v", "bout", None],
        ]
    )
    canon = canonical_customers(clusters)
    assert len(canon) == 1
    assert canon.iloc[0]["first_name"] == "viktor"
    assert canon.iloc[0]["dob"] == "1967-01-13"


def test_screen_finds_planted_hit_and_ignores_clean_customer(settings):
    _land_sdn(settings)
    clusters = _clusters(
        [
            ["c1", "CRM-1", "viktor", "bout", "1967-01-13"],
            ["c2", "CRM-2", "maria", "hernandez", "1980-05-05"],
        ]
    )
    summary = screen(settings, clusters=clusters, run_id="testrun", batch_id="b1")

    assert summary["hits_total"] >= 1
    assert summary["customers_screened"] == 2

    hits = pd.read_parquet(io.BytesIO(storage.read_bytes(summary["hits_uri"])))
    assert (hits["run_id"] == "testrun").all()
    bout_hits = hits[hits["cluster_id"] == "c1"]
    assert len(bout_hits) >= 1
    assert (hits["cluster_id"] != "c2").all(), hits.to_string()


def test_extract_sdn_dob_years():
    assert extract_sdn_dob_years("DOB 13 Jan 1967; POB Dushanbe") == [1967]
    assert extract_sdn_dob_years("DOB 1955; alt. DOB 12 May 1958") == [1955, 1958]
    assert extract_sdn_dob_years("no dates here") == []
    assert extract_sdn_dob_years("") == []


def test_dob_corroboration_bands():
    assert dob_corroboration("1967-01-13", [1967]) == "match"
    assert dob_corroboration("1966-01-01", [1967]) == "match"  # +/-2y tolerance
    assert dob_corroboration("1980-01-01", [1967]) == "mismatch"
    assert dob_corroboration("", [1967]) == "unknown"
    assert dob_corroboration("1967-01-13", []) == "unknown"


def test_dob_mismatch_demotes_strong_hit(settings):
    _land_sdn(settings)
    # Same name as the SDN entry but born decades later
    clusters = _clusters([["c1", "CRM-1", "viktor", "bout", "1999-06-01"]])
    summary = screen(settings, clusters=clusters, run_id="demote")
    hits = pd.read_parquet(io.BytesIO(storage.read_bytes(summary["hits_uri"])))
    bout = hits[hits["cluster_id"] == "c1"]
    assert len(bout) >= 1
    assert (bout["severity"] == "POSSIBLE").all(), bout.to_string()
    assert (bout["dob_corroboration"] == "mismatch").all()


def test_dob_match_keeps_strong_hit(settings):
    _land_sdn(settings)
    clusters = _clusters([["c1", "CRM-1", "viktor", "bout", "1967-01-13"]])
    summary = screen(settings, clusters=clusters, run_id="keep")
    hits = pd.read_parquet(io.BytesIO(storage.read_bytes(summary["hits_uri"])))
    bout = hits[hits["cluster_id"] == "c1"]
    assert (bout["severity"] == "STRONG").all(), bout.to_string()
    assert (bout["dob_corroboration"] == "match").all()


def test_screen_no_sdn_files_raises(settings):
    try:
        screen(settings, clusters=_clusters([["c1", "CRM-1", "a", "b", None]]))
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError:
        pass
