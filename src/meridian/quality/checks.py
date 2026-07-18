"""Data-quality gate for incoming customer batches.

Runs in the resolution-trigger Lambda BEFORE any expensive compute: a batch
that fails validation is moved to quarantine and alerted on, never processed.

Contract (manifest-last upload protocol): a batch prefix contains the three
source CSVs plus a manifest.json uploaded LAST:
  { "batch_id": "...", "files": {"crm_customers.csv": <expected_rows>, ...},
    "generator_seed": 42 }
The S3 notification fires on manifest.json only, so one event == one complete
batch and the expected row counts arrive with the trigger.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field

from meridian.io import storage

EXPECTED_HEADERS = {
    "crm_customers.csv": [
        "crm_id", "full_name", "dob", "address", "city", "state", "zip", "email",
    ],
    "loans_customers.csv": [
        "loan_cust_id", "name", "date_of_birth", "addr_line1", "addr_city",
        "addr_state", "addr_zip", "ssn_last4",
    ],
    "legacy_customers.csv": [
        "cust_no", "fname", "lname", "birth_dt", "street", "city", "st", "zip5",
    ],
}

# Legacy duplicates rows on purpose, so allow landed counts to exceed the
# manifest's expectation slightly; anything below is silent data loss.
ROW_COUNT_TOLERANCE = 0.05


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    row_counts: dict = field(default_factory=dict)


def validate_batch(batch_prefix: str, manifest: dict) -> ValidationResult:
    """Validate one landed batch against its manifest. Never raises."""
    errors: list[str] = []
    row_counts: dict = {}

    expected_files = manifest.get("files", {})
    if not manifest.get("batch_id"):
        errors.append("manifest missing batch_id")
    if set(expected_files) != set(EXPECTED_HEADERS):
        errors.append(
            f"manifest files {sorted(expected_files)} != "
            f"expected {sorted(EXPECTED_HEADERS)}"
        )
        return ValidationResult(ok=False, errors=errors)

    for name, expected_rows in expected_files.items():
        uri = f"{batch_prefix}/{name}"
        if not storage.exists(uri):
            errors.append(f"{name}: file missing")
            continue
        try:
            reader = csv.reader(io.StringIO(storage.read_bytes(uri).decode()))
            header = next(reader, None)
            n_rows = sum(1 for _ in reader)
        except Exception as err:  # noqa: BLE001 — any parse failure quarantines
            errors.append(f"{name}: unreadable ({err})")
            continue
        row_counts[name] = n_rows
        if header != EXPECTED_HEADERS[name]:
            errors.append(
                f"{name}: header mismatch — got {header}, "
                f"expected {EXPECTED_HEADERS[name]}"
            )
        if n_rows == 0:
            errors.append(f"{name}: zero data rows")
        elif n_rows < expected_rows:
            errors.append(
                f"{name}: {n_rows} rows < manifest expectation {expected_rows}"
            )
        elif n_rows > expected_rows * (1 + ROW_COUNT_TOLERANCE):
            errors.append(
                f"{name}: {n_rows} rows exceeds manifest expectation "
                f"{expected_rows} by more than {ROW_COUNT_TOLERANCE:.0%}"
            )

    return ValidationResult(ok=not errors, errors=errors, row_counts=row_counts)


def quarantine_batch(batch_prefix: str, quarantine_prefix: str, reason: list[str]) -> str:
    """Copy a failed batch to quarantine with a reason file; return its URI."""
    batch_name = batch_prefix.rstrip("/").rsplit("/", 1)[-1]
    dest_prefix = f"{quarantine_prefix}/{batch_name}"
    for uri in storage.list_prefix(batch_prefix):
        name = uri.rsplit("/", 1)[-1]
        storage.write_bytes(f"{dest_prefix}/{name}", storage.read_bytes(uri))
    storage.write_bytes(
        f"{dest_prefix}/_quarantine_reason.json",
        json.dumps({"errors": reason}, indent=2).encode(),
    )
    return dest_prefix
