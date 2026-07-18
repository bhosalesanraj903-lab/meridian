# Operating handbook

## Daily
1. Triage (15-20 min, fixed time): Grafana scorecard -> alert channel ->
   Airflow runs -> classify anything red: INCIDENT / DEGRADATION / NOISE.
   Write one-line status in docs/weekly/ current file, even when green.
2. Written standup: shipped yesterday / ships today / blocked.
3. Build block: top ticket only; PR + self-review + green CI; no direct pushes.
4. Close: tickets moved, tomorrow's first step written down.

## Weekly
Mon: sprint planning (acceptance criteria on every ticket).
Midweek: game-day -> incident process -> same-day postmortem (template in docs/templates).
Fri: retro (2 paragraphs, about process) + demo note.

## Incidents
SEV1 wrong data in gold / SLA breach -> fix now, full postmortem.
SEV2 degraded/at-risk -> fix in a day, short postmortem.
SEV3 annoyance -> ticket. All SEV1/2 -> incidents/INC-NNN.md.

## Changes to operating pipelines
State rollback before merge. Deploy after triage, never before bed.
Watch one full cycle before calling it done.
