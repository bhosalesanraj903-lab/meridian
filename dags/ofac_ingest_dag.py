"""OFAC SDN ingestion DAG — runs every 30 minutes.

Change detection lives in the ingest script; a no-change run is a cheap no-op
that still refreshes the freshness signal. When the list changes, the script
emits a `sanctions_list_updated` event; the rescan DAG (Phase 1b) senses it.
"""
from __future__ import annotations
import sys
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

sys.path.insert(0, "/opt/meridian/ingestion/ofac")

def _run_ingest(**_):
    from ofac_ingest import run
    summary = run()
    if summary["changed"]:
        print(f"SDN CHANGED — landed {summary['landed_path']}")
    return summary

with DAG(
    dag_id="ofac_sdn_ingest",
    schedule="*/30 * * * *",
    start_date=datetime(2026, 7, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["meridian", "sanctions", "pipeline-1"],
) as dag:
    PythonOperator(task_id="ingest_sdn", python_callable=_run_ingest)
