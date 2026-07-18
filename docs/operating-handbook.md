# Operating handbook

Console entry points (region ap-south-1):
- Dashboard: CloudWatch -> Dashboards -> `meridian-ops`
- Runs: Glue -> Jobs -> `meridian-resolve-and-screen` -> Runs
- Alerts arrive by email (SNS `meridian-alerts`); budget mails at $2.50/$4/$5

## Daily
1. Triage (15-20 min, fixed time): alerts inbox -> `meridian-ops` dashboard
   (alarm strip first; then DLQ depths, Lambda errors, ingest freshness) ->
   Glue run history. Classify anything red: INCIDENT / DEGRADATION / NOISE.
   Write one-line status in docs/weekly/ current file, even when green.
2. Written standup: shipped yesterday / ships today / blocked.
3. Build block: top ticket only; PR + self-review + green CI; no direct pushes.
4. Close: tickets moved, tomorrow's first step written down.

## Weekly
Mon: sprint planning (acceptance criteria on every ticket).
Midweek: game-day (see docs/runbooks/game-day.md) -> incident process ->
same-day postmortem (template in docs/templates).
Fri: retro (2 paragraphs, about process) + demo note.

## Incidents
SEV1 wrong data in gold / SLA breach -> fix now, full postmortem.
SEV2 degraded/at-risk (pipeline blocked, DLQ filling) -> fix in a day,
short postmortem.
SEV3 annoyance -> ticket. All SEV1/2 -> incidents/INC-NNN.md.

## Standard responses (runbooks in docs/runbooks/)
- DLQ alarm -> dlq-redrive.md
- Batch quarantined -> batch-reprocess.md
- Glue run FAILED -> glue-failure-triage.md
- Need whole-book rescan -> forced-rescan.md

## Changes to operating pipelines
State rollback before merge. Deploy after triage, never before bed.
Watch one full cycle before calling it done. Every Glue dependency is an
exact pin (INC-001); splink stays at 4.0.16 until INC-000 is re-tested.
