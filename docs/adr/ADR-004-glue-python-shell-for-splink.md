# ADR-004: Glue Python Shell (1 DPU) runs Splink resolution + screening

**Status:** accepted · **Date:** 2026-07-18

## Context
Splink+DuckDB+pandas exceed Lambda's 250 MB zip limit, and INC-000 showed
splink 4.0.16 crashes during u-estimation on 1-vCPU machines ("Salting
partitions must be > 1") — the fallback path (max_pairs=9000) produces
noisier u-estimates.

## Decision
Run resolution + screening as a **Glue Python Shell job at 1 DPU**
(4 vCPU / 16 GB):
- 4 vCPU → the INC-000 crash path is never entered at full max_pairs=5e5;
  the code fallback stays as defense in depth (CI runners are 1-vCPU-class).
- **Never** use the 0.0625 (1/16) DPU size — it is 1-vCPU-class and would
  live permanently on the degraded fallback path.
- Dependencies via `--additional-python-modules` (all pinned); the `meridian`
  wheel via `--extra-py-files` from the artifacts bucket.
- Cost ≈ $1.80/mo at ~30 runs × 8 min ($0.44/DPU-hr).

Rejected: Lambda container image (10 GB / 6 vCPU, ~free). Close call — but it
adds ECR + image builds, hits a hard 15-min wall as the book grows, and loses
Glue's native run history + Job State Change failure events.

## Consequences
- Job failures alarm via an EventBridge rule on Glue Job State Change.
- Re-test INC-000 before any splink upgrade (pinned at 4.0.16).
