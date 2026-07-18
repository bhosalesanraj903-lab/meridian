# Runbook: DLQ depth alarm

A message reached a dead-letter queue after 3 failed consumer attempts.

## 1. Look at the message (do NOT delete it)
```bash
aws sqs receive-message \
  --queue-url "$(aws sqs get-queue-url --queue-name meridian-<chain>-dlq --query QueueUrl --output text)" \
  --visibility-timeout 30 --max-number-of-messages 1
```
The body is an S3 event — note bucket/key. Check the consumer Lambda's logs
around the message's SentTimestamp:
```bash
aws logs tail /aws/lambda/meridian-resolution-trigger --since 2h | grep -i error
```

## 2. Fix the cause first
Typical causes: consumer bug (fix code, `make build-lambdas`, terraform apply),
IAM change, malformed S3 event from a manual console upload.

## 3. Redrive back to the source queue
```bash
aws sqs start-message-move-task \
  --source-arn arn:aws:sqs:ap-south-1:470945861699:meridian-<chain>-dlq
```
Watch the consumer process it, confirm DLQ depth returns to 0 and the alarm
goes OK (email arrives).

## 4. If the message is garbage (not reprocessable)
Delete it with `aws sqs purge-queue` ONLY after saving the body into the
incident note.
