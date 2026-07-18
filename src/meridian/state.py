"""Pipeline state: OFAC hash compare-and-set + batch processing ledger.

Two backends behind one interface:
  * LocalJsonState  — a JSON file in the lake (local dev, unit tests).
  * DynamoDbState   — table `meridian-state`, pk `entity` (AWS).
    - item `ofac_sdn` holds last_sha256 etc.; swap is an atomic conditional
      UpdateItem so concurrent ingest runs can't double-land one version.
    - items `batch#<batch_id>` are the processing ledger: a conditional put
      dedupes S3's at-least-once event delivery (first writer wins).
"""
from __future__ import annotations

import json
from typing import Protocol

from meridian.io import storage


class StateStore(Protocol):
    def get_ofac_state(self) -> dict: ...

    def swap_ofac_hash(self, new_state: dict) -> bool:
        """Atomically record a new SDN version. Returns False if another
        writer already recorded the same sha256 (no-op)."""
        ...

    def claim_batch(self, batch_id: str, attrs: dict) -> bool:
        """Register a batch as being processed. Returns False if already
        claimed (duplicate event — skip)."""
        ...

    def release_batch(self, batch_id: str) -> None:
        """Remove a ledger claim so a batch can be reprocessed (runbook op)."""
        ...


class LocalJsonState:
    def __init__(self, path: str):
        self.path = path

    def _load(self) -> dict:
        if storage.exists(self.path):
            return json.loads(storage.read_bytes(self.path))
        return {}

    def _save(self, doc: dict) -> None:
        storage.write_bytes(self.path, json.dumps(doc, indent=2).encode())

    def get_ofac_state(self) -> dict:
        return self._load().get("ofac_sdn", {})

    def swap_ofac_hash(self, new_state: dict) -> bool:
        doc = self._load()
        if doc.get("ofac_sdn", {}).get("last_sha256") == new_state.get("last_sha256"):
            return False
        doc["ofac_sdn"] = new_state
        self._save(doc)
        return True

    def claim_batch(self, batch_id: str, attrs: dict) -> bool:
        doc = self._load()
        ledger = doc.setdefault("batches", {})
        if batch_id in ledger:
            return False
        ledger[batch_id] = attrs
        self._save(doc)
        return True

    def release_batch(self, batch_id: str) -> None:
        doc = self._load()
        if batch_id in doc.get("batches", {}):
            del doc["batches"][batch_id]
            self._save(doc)


class DynamoDbState:
    def __init__(self, table_name: str, region: str):
        import boto3

        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self._exc = boto3.client("dynamodb", region_name=region).exceptions

    def get_ofac_state(self) -> dict:
        resp = self._table.get_item(Key={"entity": "ofac_sdn"})
        return resp.get("Item", {})

    def swap_ofac_hash(self, new_state: dict) -> bool:
        try:
            self._table.put_item(
                Item={"entity": "ofac_sdn", **new_state},
                ConditionExpression=(
                    "attribute_not_exists(entity) OR last_sha256 <> :new"
                ),
                ExpressionAttributeValues={":new": new_state["last_sha256"]},
            )
            return True
        except self._exc.ConditionalCheckFailedException:
            return False

    def claim_batch(self, batch_id: str, attrs: dict) -> bool:
        try:
            self._table.put_item(
                Item={"entity": f"batch#{batch_id}", **attrs},
                ConditionExpression="attribute_not_exists(entity)",
            )
            return True
        except self._exc.ConditionalCheckFailedException:
            return False

    def release_batch(self, batch_id: str) -> None:
        self._table.delete_item(Key={"entity": f"batch#{batch_id}"})


def state_store(settings) -> StateStore:
    if settings.state_backend == "dynamodb":
        return DynamoDbState(settings.state_table, settings.aws_region)
    return LocalJsonState(settings.local_state_path)
