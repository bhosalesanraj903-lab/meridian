# Runbook: Glue run FAILED / TIMEOUT / STOPPED

The failure alert email comes from the EventBridge rule on Glue Job State
Change. `max_retries` is deliberately 0 — nothing retries silently.

## 1. Get the error
```bash
aws glue get-job-runs --job-name meridian-resolve-and-screen --max-results 3 \
  --query 'JobRuns[].{id:Id,state:JobRunState,error:ErrorMessage,secs:ExecutionTime}'
aws logs tail /aws-glue/python-jobs/error --since 2h | tail -50
aws logs tail /aws-glue/python-jobs/output --since 2h | tail -50
```

## 2. Classify
- **pip/startup failure** (never reached job code): dependency resolution —
  see INC-001; every dep must be an exact pin with a real wheel.
- **Quality gate failure** (`Quality gate failed: precision=...`): the batch
  resolved badly. Inspect the eval report in
  `silver/customers/eval_report.json`; likely generator/source drift or a
  threshold problem. Data was deliberately NOT written to gold.
- **INC-000 signature** (`Salting partitions must be > 1`): job ran on a
  1-vCPU environment — check the job's max_capacity is still 1.0, never 0.0625.
- **S3 AccessDenied**: IAM drift — `terraform plan` will show it.

## 3. Rerun
After fixing, release the ledger claim and rerun — batch-reprocess.md.

## Game-day drill (midweek)
Break something on purpose, follow this runbook, file the postmortem:
- `terraform apply` with the Glue role's LakeWriteCurated statement commented
  out -> AccessDenied at write time, or
- upload a batch with `--break-header` -> quarantine path + alert instead.
