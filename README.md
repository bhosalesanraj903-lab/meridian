# Meridian — event-driven sanctions-screening data platform

A live-operated compliance data pipeline simulating a mid-size lender:
OFAC sanctions-list ingestion, customer entity resolution (Splink), and
sanctions screening — deployed on AWS as an event-driven serverless pipeline
(S3 → SNS → SQS → Lambda → Glue → Athena) with DLQs, CloudWatch alarms, and
Terraform-managed infrastructure. Operated daily with published SLOs and a
full incident history.

## Architecture

```
EventBridge cron ─▶ ingest Lambda ─▶ bronze S3 (OFAC SDN, hash change-detect)
                                          │ S3 event
customer batches ─▶ bronze S3 ─▶ SNS ─▶ SQS(+DLQ) ─▶ trigger Lambda
                                          (validate / quarantine / dedupe)
                                          ▼
                              Glue Python Shell job (1 DPU)
                       Splink resolution ─▶ quality gate ─▶ screening
                                          ▼
                        silver + gold Parquet (run_date partitions)
                                          │ S3 event
                       SNS ─▶ SQS ─▶ notifier Lambda ─▶ alert email
                                          ▼
                       Glue Catalog (explicit tables) ─▶ Athena
```

Local dev needs no AWS and no Docker: the lake is a plain directory
(`MERIDIAN_LAKE_URI=./data`, the default).

## Quickstart (local)
```bash
make install       # venv + editable install with dev extras
make test          # fast unit tests
make gen           # synthetic customer book -> data/bronze/customers/
make ingest        # OFAC SDN -> data/bronze/ofac/ (change-detecting)
make resolve       # Splink entity resolution -> data/silver/customers/
make screen        # sanctions screening -> data/gold/screening_hits/
```

## Repo map
- `src/meridian/` — the pipeline package (ingestion, generator, matching,
  screening, quality, config/state/storage platform code)
- `lambdas/` — thin AWS Lambda handlers (logic stays in `src/`)
- `glue_jobs/` — Glue Python Shell entrypoints
- `infra/terraform/` — all AWS infrastructure (modules + envs/dev)
- `tools/` — operator CLIs (batch upload, drills)
- `docs/` — operating handbook, ADRs, runbooks, source catalog, roadmap
- `incidents/` — postmortems (INC-NNN)

## Operating rhythm
Daily: 15-min triage (alerts inbox → CloudWatch dashboard → Glue run history)
+ build block. Weekly: Mon planning, midweek game-day, Fri retro.
See docs/operating-handbook.md.

## Status
Phase 1 — pipeline 1 (OFAC screening) local build complete; AWS deploy in
progress. History: the Phase-0 skeleton (docker-compose/Airflow stack) is in
git history; orchestration moved to EventBridge + S3 events (docs/adr/ADR-001).
