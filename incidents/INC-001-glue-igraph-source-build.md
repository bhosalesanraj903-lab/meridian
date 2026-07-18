# INC-001: Glue job stuck compiling igraph from source at startup
Date: 2026-07-18 | Severity: SEV2 (pipeline blocked, no data impact) | Detected by: watching first production Glue run | Time to detect: ~6 min | Time to resolve: ~10 min

## Impact
First `meridian-resolve-and-screen` run (jr_f4aa8700…) never reached job code:
pip spent 6+ minutes attempting to compile igraph's C core from source, failed
("finished with status 'error'"), and retried. Run was stopped manually at ~8
min. Batch 20260718T090918Z processing delayed; no data written, no data lost.

## Timeline (UTC)
- 09:09 Batch uploaded; trigger Lambda validated + started Glue run within 3s
  (event chain worked as designed).
- 09:10 `--additional-python-modules` pip install began; wheels resolved fine
  for splink/duckdb/pandas/pyarrow/rapidfuzz.
- 09:13 pip fell back to the igraph sdist (transitive dep of splink for
  clustering) and started a from-source C build.
- 09:14 Build failed; pip auto-retried a second build.
- 09:17 Run stopped manually (would have burned the 30-min job timeout).
- 09:18 Fix applied via Terraform; rerun started with the same batch args.

## Root cause
splink's dependency spec pulls the newest igraph. On the Glue Python Shell
py3.9 runtime, that release resolves to an sdist (no compatible prebuilt
wheel for Glue's platform/pip), and Glue workers lack the C toolchain pieces
to build igraph's C core. Unpinned transitive dependency + no-toolchain
runtime = startup failure. Same class of lesson as INC-000: the failure lives
in dependency resolution, not our code.

## Resolution
Pin `igraph==0.11.9` (ships a py3.9-compatible manylinux wheel) in the job's
`--additional-python-modules` (infra/terraform/envs/dev/pipeline.tf). Stopping
the doomed run also confirmed the Glue FAILED/STOPPED EventBridge rule ->
alerts email path fires.

## Action items
- [x] Pin igraph==0.11.9 alongside the other job deps
- [ ] Harden: mirror all job wheels into meridian-artifacts/wheels/ and point
      --additional-python-modules at s3 paths — removes PyPI resolution from
      the startup path entirely (also fixes the ~2 min per-run pip cost)
- [ ] Rule: every dependency in Glue job args must be an exact pin, including
      transitive deps that have ever resolved to an sdist
