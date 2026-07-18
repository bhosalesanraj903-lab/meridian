# Meridian — regulated banking & compliance data platform

A live-operated data platform simulating a mid-size lender: sanctions
screening with entity resolution, regulatory ingestion with restatement
handling, credit-risk marts, and market data with daily reconciliation.
Operated daily with published SLOs and a full incident history.

## Quickstart (day 1)
```bash
pip install -r requirements.txt
make test          # generator + ingestion unit tests
make gen           # synthetic customer book -> data/bronze/customers/
make ingest        # OFAC SDN -> data/bronze/ofac/ (change-detecting)
make up            # full local stack (Airflow :8080, Grafana :3000, MinIO :9001)
```

## Repo map
- `ingestion/` source ingestion jobs (OFAC first; EDGAR, FFIEC follow)
- `generator/` deterministic synthetic data (customers, later core-banking)
- `dags/` Airflow orchestration
- `dbt/` silver->gold transformations, star schema (see docs/design)
- `docs/` design docs, ADRs, source catalog, runbooks, weekly log
- `incidents/` postmortems (INC-NNN)
- `infra/` prometheus/grafana config; terraform arrives with cloud deploy

## Operating rhythm
Daily: 15-min triage (Grafana -> Airflow -> ops note) + build block.
Weekly: Mon planning, midweek game-day, Fri retro+demo note.
See docs/operating-handbook.md.

## Status
Phase 0 — skeleton. Roadmap: docs/roadmap.md
