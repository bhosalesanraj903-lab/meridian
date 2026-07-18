# INC-000: Splink u-estimation crashes on single-CPU environments
Date: 2026-07-17 | Severity: SEV3 (dev-blocking, no data impact) | Detected by: first pipeline run | Time to detect: immediate | Time to resolve: ~15 min

## Impact
matching/resolve_customers.py failed during training; Pipeline 1 blocked in dev.

## Timeline (UTC)
- Run 1: `estimate_u_using_random_sampling(max_pairs=2e6)` raised
  "ValueError: Salting partitions must be specified and > 1".
- Guessed fix (lower max_pairs to 5e5): FAILED — same error. Lesson: stop guessing.
- Read library source (splink/internals/estimate_u.py): on duckdb with
  max_pairs > 1e4, splink sets `salting_partitions = multiprocessing.cpu_count()`.
- Environment had cpu_count()==1 -> 1 partition -> hard error.

## Root cause
splink 4.0.16 derives salting from CPU count with no floor; single-vCPU
machines (small VMs, CI runners, containers with cpu limits) always crash.

## Resolution
try/except in train(): retry with max_pairs=9_000 (below the salting code
path) only when this specific ValueError fires. Comment documents why.

## Action items
- [x] Fallback implemented with narrow exception matching
- [ ] Pin splink==4.0.16 in requirements; re-test on upgrade
- [ ] Note in runbook: CI runners may take the fallback path (slightly
      noisier u-estimates; acceptable, tests assert quality floor)
