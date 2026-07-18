"""OFAC SDN list ingestion — Meridian pipeline #1, stage 1.

Behavior (idempotent, safe to run every 30 min):
  1. Download the SDN CSV from Treasury (User-Agent set, timeout, retries).
  2. Compute sha256; compare against last-known hash in the state file.
  3. If unchanged -> log and exit 0 (no-op run; freshness metric still updates).
  4. If changed  -> land an immutable, timestamped raw copy in bronze,
                   update state, and emit a `sanctions_list_updated` event
                   (Phase 1: JSON file in events dir; Phase 2: Kafka topic).

Bronze is append-only: we never overwrite a landed file. Every landed file
name embeds the UTC timestamp and content hash for auditability.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
USER_AGENT = os.environ.get(
    "MERIDIAN_USER_AGENT", "MeridianDataPlatform contact@example.com"
)
DATA_DIR = Path(os.environ.get("MERIDIAN_DATA_DIR", "./data"))
BRONZE_DIR = DATA_DIR / "bronze" / "ofac" / "sdn"
STATE_FILE = DATA_DIR / "bronze" / "ofac" / "_state.json"
EVENTS_DIR = DATA_DIR / "bronze" / "_events"

log = logging.getLogger("ofac_ingest")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)


def _download(url: str, retries: int = 3, backoff: float = 2.0) -> bytes:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=60
            )
            resp.raise_for_status()
            if len(resp.content) < 1024:
                raise ValueError(
                    f"Suspiciously small response ({len(resp.content)} bytes) "
                    "— refusing to treat as a valid SDN file"
                )
            return resp.content
        except Exception as err:  # noqa: BLE001 — we re-raise after retries
            last_err = err
            log.warning("Download attempt %d/%d failed: %s", attempt, retries, err)
            time.sleep(backoff * attempt)
    raise RuntimeError(f"OFAC download failed after {retries} attempts") from last_err


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)  # atomic on POSIX


def _emit_event(event: dict) -> None:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{event['event_time'].replace(':', '')}_{event['event_type']}.json"
    (EVENTS_DIR / name).write_text(json.dumps(event, indent=2))
    log.info("Emitted event %s", event["event_type"])


def run() -> dict:
    """Execute one ingestion cycle. Returns a summary dict (for tests/Airflow)."""
    started = datetime.now(timezone.utc)
    content = _download(SDN_URL)
    digest = hashlib.sha256(content).hexdigest()
    state = _load_state()

    summary = {
        "run_time": started.isoformat(),
        "sha256": digest,
        "bytes": len(content),
        "changed": False,
        "landed_path": None,
    }

    if state.get("last_sha256") == digest:
        log.info("SDN unchanged (sha256=%s…) — no-op", digest[:12])
        return summary

    ts = started.strftime("%Y%m%dT%H%M%SZ")
    BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    landed = BRONZE_DIR / f"sdn_{ts}_{digest[:12]}.csv"
    landed.write_bytes(content)
    log.info("Landed new SDN version: %s (%d bytes)", landed.name, len(content))

    _save_state(
        {
            "last_sha256": digest,
            "last_landed": str(landed),
            "last_change_time": started.isoformat(),
            "previous_sha256": state.get("last_sha256"),
        }
    )
    _emit_event(
        {
            "event_type": "sanctions_list_updated",
            "event_time": started.isoformat(),
            "source": "ofac_sdn",
            "sha256": digest,
            "previous_sha256": state.get("last_sha256"),
            "landed_path": str(landed),
        }
    )
    summary.update({"changed": True, "landed_path": str(landed)})
    return summary


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
