# Runbook: force a whole-book sanctions rescan

Use when compliance wants re-screening without waiting for the next OFAC
list change (e.g., after a threshold tune or a missed alert investigation).

## Preferred: corrupt-the-hash drill (exercises the real path end to end)
```bash
aws dynamodb update-item --table-name meridian-state \
  --key '{"entity":{"S":"ofac_sdn"}}' \
  --update-expression "SET last_sha256 = :v" \
  --expression-attribute-values '{":v":{"S":"force-rescan"}}'
aws lambda invoke --function-name meridian-ofac-ingest /tmp/out.json && cat /tmp/out.json
```
The ingest re-lands the SDN file -> S3 event -> trigger starts a rescan run
against the latest batch (`batch_id=rescan-sdn_<ts>_<hash>`).

## Direct (skips the event chain — use only if the chain itself is broken)
```bash
aws glue start-job-run --job-name meridian-resolve-and-screen --arguments '{
  "--batch_id":"manual-rescan-$(date -u +%Y%m%dT%H%M%SZ)",
  "--batch_prefix":"s3://meridian-lake-use1-470945861699/bronze/customers/incoming/batch_id=<latest>",
  "--trigger_reason":"manual_rescan"}'
```

Verify: new `run_date=` partition appears and the notifier email lands.
