# Meridian roadmap (40-day build)

D1-2   Phase 0: skeleton, compose stack, CI, budget alarms          [now]
D3-8   Pipeline 1: OFAC + generator + Splink + rescan trigger; D8 = deploy to VM, CLOCK STARTS
D9-14  Pipeline 4: Binance ws -> Kafka -> bars; gap repair; nightly recon; Grafana SLOs live
D15-21 Pipeline 2: EDGAR watchlist + Saturday restatement re-diff; FFIEC + dim_institution SCD2; dbt gates
D22-24 CDC mini-demo (Debezium, 1 table); first game-day + postmortem
D25-26 GSE credit-risk benchmark sprint (local Spark + one EMR spot run)
D27-40 Operate & harden: 2 game-days/wk, incidents, docs, publish write-up, apply from ~D28

Backlog (scoped, not scheduled): Companies House stream, k3s migration,
Snowflake port, Databricks port, GCP leg, Power BI, NL-query capstone.
