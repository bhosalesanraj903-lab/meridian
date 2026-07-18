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

## Resolution (three attempts — each taught something)
1. **Pin igraph==0.11.9 in --additional-python-modules**: run 2 still pulled
   igraph-1.0.0.tar.gz — job-config change hadn't propagated when the run
   started (Glue eventual consistency). Lesson: verify `aws glue get-job`
   shows the new args before rerunning.
2. **Vendored wheelhouse via --extra-py-files** (make build-wheelhouse: full
   dependency tree as cp39/manylinux wheels in S3): run 3 STILL built pyarrow
   and igraph from source. Logs revealed the real mechanism: Glue pip-installs
   extra-py-files ONE AT A TIME, IN LIST ORDER, resolving any unsatisfied
   requirement from PyPI. meridian's wheel was first in the list, so pip
   resolved `pyarrow>=17` -> 21.0 (sdist on py3.9) from PyPI before any
   vendor wheel installed.
3. **Ordered wheelhouse**: leaf/compiled wheels first, pandas/altair, then
   splink, meridian LAST — every requirement is already satisfied locally by
   the time its dependent installs, so pip never consults PyPI. requests
   vendored too. This is the durable fix.

Stopping the doomed runs confirmed the Glue STOPPED EventBridge rule ->
alerts email path fires.

## Action items
- [x] Vendored, ORDERED wheelhouse in --extra-py-files (PyPI out of the
      startup path; also removes most of the per-run pip latency)
- [x] Rule: verify get-job args after terraform apply, before start-job-run
- [x] Rule: every Glue dependency is an exact pinned wheel in the wheelhouse;
      rebuild with `make build-wheelhouse` on any dep change
