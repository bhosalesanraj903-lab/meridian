# ADR-001: EventBridge + S3 events replace Airflow

**Status:** accepted · **Date:** 2026-07-18

## Context
Phase 0 ran Airflow standalone (SQLite, single container) with one DAG
polling OFAC every 30 min. The docker-compose stack also carried Kafka,
Debezium, Prometheus, and Grafana that nothing used. The target is a real,
long-running deployment on a personal AWS account at near-zero cost.

## Decision
Orchestrate with AWS-native eventing instead of Airflow:
- EventBridge Scheduler cron (6h) drives the OFAC ingest Lambda — polling a
  list that changes ~weekly every 30 min bought nothing.
- S3 ObjectCreated notifications → SNS → SQS (+DLQ) → Lambda chain the
  pipeline stages; the bronze landing event IS the "sanctions list updated"
  signal, replacing the JSON event files.
- The docker-compose stack, DAG, and Prometheus config are deleted (git
  history keeps them). Local dev is plain filesystem + `make` targets.

## Consequences
- No always-on orchestrator to run, patch, or pay for ($0 vs an
  always-on VM/MWAA); retries and backpressure come from SQS semantics.
- Run history lives in Glue job runs + run manifests in S3, not an Airflow UI.
- If DAG-shaped multi-step dependencies return (dbt, backfills), revisit with
  Step Functions before reaching for managed Airflow.
