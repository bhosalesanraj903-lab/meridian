"""OFAC SDN list ingestion — Meridian pipeline #1, stage 1.

Behavior (idempotent, safe to run on any schedule):
  1. Download the SDN CSV from Treasury (User-Agent set, timeout, retries).
  2. Compute sha256; compare against last-known hash in the state store.
  3. If unchanged -> log and exit (no-op run; invocation metric still updates
     the freshness alarm).
  4. If changed  -> land an immutable, timestamped raw copy in bronze and
     atomically swap the state hash. On AWS, the bronze S3 ObjectCreated
     notification IS the `sanctions_list_updated` event — no separate emit.

Bronze is append-only: we never overwrite a landed file. Every landed file
name embeds the UTC timestamp and content hash for auditability.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

import requests

from meridian.config import Settings
from meridian.io import storage
from meridian.logs import get_logger
from meridian.state import state_store

SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"

log = get_logger("meridian.ingestion.ofac")


def _download(url: str, user_agent: str, retries: int = 3, backoff: float = 2.0) -> bytes:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=60)
            resp.raise_for_status()
            if len(resp.content) < 1024:
                raise ValueError(
                    f"Suspiciously small response ({len(resp.content)} bytes) "
                    "— refusing to treat as a valid SDN file"
                )
            return resp.content
        except Exception as err:  # noqa: BLE001 — we re-raise after retries
            last_err = err
            log.warning(
                "Download attempt failed", extra={"attempt": attempt, "error": str(err)}
            )
            time.sleep(backoff * attempt)
    raise RuntimeError(f"OFAC download failed after {retries} attempts") from last_err


def run(settings: Settings | None = None) -> dict:
    """Execute one ingestion cycle. Returns a summary dict (for tests/handlers)."""
    settings = settings or Settings.from_env()
    store = state_store(settings)

    started = datetime.now(timezone.utc)
    content = _download(SDN_URL, settings.user_agent)
    digest = hashlib.sha256(content).hexdigest()
    previous = store.get_ofac_state()

    summary = {
        "run_time": started.isoformat(),
        "sha256": digest,
        "bytes": len(content),
        "changed": False,
        "landed_uri": None,
    }

    if previous.get("last_sha256") == digest:
        log.info("SDN unchanged — no-op", extra={"sha256_prefix": digest[:12]})
        return summary

    ts = started.strftime("%Y%m%dT%H%M%SZ")
    landed_uri = f"{settings.bronze_ofac_prefix}/sdn_{ts}_{digest[:12]}.csv"
    # Land first, swap state second: a failed swap only means a harmless
    # duplicate bronze file, while the reverse order could record a version
    # that never landed (silent staleness until the next list change).
    storage.write_bytes(landed_uri, content)
    log.info(
        "Landed new SDN version",
        extra={"landed_uri": landed_uri, "bytes": len(content)},
    )
    swapped = store.swap_ofac_hash(
        {
            "last_sha256": digest,
            "last_landed_uri": landed_uri,
            "last_change_time": started.isoformat(),
            "previous_sha256": previous.get("last_sha256", ""),
        }
    )
    if not swapped:
        log.info(
            "Concurrent run already recorded this version",
            extra={"sha256_prefix": digest[:12]},
        )
    summary.update({"changed": True, "landed_uri": landed_uri})
    return summary


if __name__ == "__main__":
    import json

    from meridian.logs import setup_logging

    setup_logging()
    print(json.dumps(run(), indent=2))
