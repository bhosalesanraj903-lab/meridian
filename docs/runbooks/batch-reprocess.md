# Runbook: reprocess a customer batch

Use when a batch was quarantined and the data has been fixed, or a Glue run
failed after the ledger claim was written.

## Reprocess after a failed/stopped Glue run
The trigger's DynamoDB ledger dedupes events, so the same batch will NOT
retrigger until its claim is released:
```bash
aws dynamodb delete-item --table-name meridian-state \
  --key '{"entity":{"S":"batch#<batch_id>"}}'
```
Then either re-upload the batch (new event) or start the job directly:
```bash
aws glue start-job-run --job-name meridian-resolve-and-screen --arguments '{
  "--batch_id":"<batch_id>",
  "--batch_prefix":"s3://meridian-lake-use1-470945861699/bronze/customers/incoming/batch_id=<batch_id>",
  "--trigger_reason":"manual_reprocess"}'
```

## Reprocess a quarantined batch
1. Read `quarantine/<batch>/_quarantine_reason.json`.
2. Fix at the source and upload a NEW batch (`make upload-batch` /
   tools/upload_batch.py). Never edit files inside `bronze/` — bronze is
   append-only; a corrected batch is a new batch.
3. Quarantined copies expire with the bucket lifecycle; leave them for audit.
