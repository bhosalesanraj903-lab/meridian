# ADR-003: DynamoDB for ingest state + processing ledger

**Status:** accepted · **Date:** 2026-07-18

## Context
The OFAC ingester needs a compare-and-set on the last-seen SDN hash. Phase 0
used a JSON file with atomic rename — correct on POSIX, but S3 has no atomic
read-modify-write, so porting the file to S3 would race two concurrent runs.
Separately, S3 event delivery is at-least-once: the resolution trigger must
dedupe batch events or one upload can start two Glue runs.

## Decision
One on-demand DynamoDB table `meridian-state`, pk `entity`:
- `ofac_sdn` — last_sha256 etc.; updated with a conditional put
  (`last_sha256 <> :new`), an atomic compare-and-set.
- `batch#<batch_id>` — processing ledger; claimed with
  `attribute_not_exists(entity)` so the first event wins and duplicates
  no-op. Deleting the item is the documented "reprocess this batch" runbook
  operation.

Local dev keeps a JSON-file backend behind the same `StateStore` interface
(`MERIDIAN_STATE_BACKEND=local|dynamodb`).

## Consequences
- Effectively $0 (free tier; KB-scale items).
- Exactly-once *effects* from at-least-once delivery — standard idempotency
  pattern, unit-tested with moto.
