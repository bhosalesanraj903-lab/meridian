"""Run manifests — one JSON document per pipeline run, the audit trail.

Written by the Glue job at the end of a successful run; read by the
gold-notifier Lambda to compose the alert summary, and by humans during
triage. Manifests are immutable: one per run_id, never overwritten.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from meridian.config import Settings
from meridian.io import storage


def write_run_manifest(settings: Settings, run_id: str, payload: dict) -> str:
    doc = {
        "run_id": run_id,
        "written_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    uri = f"{settings.manifests_prefix}/run_id={run_id}/manifest.json"
    storage.write_bytes(uri, json.dumps(doc, indent=2).encode())
    return uri


def read_run_manifest(settings: Settings, run_id: str) -> dict:
    uri = f"{settings.manifests_prefix}/run_id={run_id}/manifest.json"
    return json.loads(storage.read_bytes(uri))
