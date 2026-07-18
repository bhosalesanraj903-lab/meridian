# ADR-002: Explicit Glue Catalog tables, no crawler

**Status:** accepted · **Date:** 2026-07-18

## Context
The reference event-driven pattern ends with S3 → Lambda → Glue Crawler →
Catalog → Athena. Crawlers infer schemas by scanning data.

## Decision
Define `silver_golden_records` and `gold_screening_hits` as explicit
`aws_glue_catalog_table` resources in Terraform with **Athena partition
projection** on `run_date`.

Rationale: our schemas are fixed and owned by this repo — inference adds
crawl latency, per-crawl cost, schema-drift surprises, and an extra Lambda
whose only job is `start_crawler`. With partition projection, a new
`run_date=` prefix is queryable the moment Parquet lands: zero crawls, zero
`MSCK REPAIR`.

The tutorial's second event chain is kept, but its Lambda is the
*gold-notifier* (summarizes hits from the run manifest → alert email) — a
consumer that earns its place.

## Consequences
- Schema changes are code-reviewed Terraform diffs, not silent crawler edits.
- If a future source has genuinely unknown/drifting schemas, a crawler can be
  added for that source alone.
