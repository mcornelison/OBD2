# I-027: V0.27.6 US-323 backfill script for stranded battery_health_log rows 11-15 never executed

| Field | Value |
|---|---|
| Severity | Medium (P1 per Spool) |
| Status | Open (V0.27.7 candidate -- Spool Story Y) |
| Category | data recovery / deployment |
| Found In | `scripts/backfill_server_battery_health_log_stranded.py` (shipped V0.27.6 US-323) |
| Found By | Spool 2026-05-12 Drive 11 validation |
| Related | V0.27.6 US-323; V0.27.4 US-315 (forward-only sync UPDATE; doesn't replay history) |
| Created | 2026-05-12 |

## Description

V0.27.6 US-323 shipped `scripts/backfill_server_battery_health_log_stranded.py` to populate server-side rows 11-15 (stranded pre-V0.27.4 with `end_timestamp=NULL`). **Script exists in repo but rows 11-15 on server still show NULL.** Either:

- (a) Script written but never invoked with `--execute` flag (likely; Ralph's pattern is `--dry-run` default)
- (b) Script has a guard or bug preventing execution
- (c) Script was deployed but no auto-run mechanism (deploy-server.sh doesn't invoke it)

Per Spool 2026-05-12:
```sql
-- server-side battery_health_log:
id=14, source_id=14, end_timestamp=NULL
id=15, source_id=15, end_timestamp=NULL
id=16, source_id=16, end_timestamp=2026-05-10 20:00:46 ← pre-existing IRL evidence
id=18, source_id=17, end_timestamp=2026-05-12 00:34:32 ← Drain 17 US-315 worked
id=20, source_id=18, end_timestamp=NULL ← Drain 18 currently open
```

Rows 11-15 still NULL = US-323 script never ran.

## Resolution (V0.27.7 candidate)

Two paths:

**Path A (simplest)** — PM runs the script manually with `--execute` flag. ~5 min. No code change needed. Just validates the script works.

**Path B (durable)** — Make the script run as part of deploy-server.sh (idempotent guard so it only runs when stranded rows exist). OR systemd timer. OR documented runbook with explicit invocation.

Spool recommends Path B (mechanism is repeatable, not a one-off hand-edit). PM concurs — Path A leaves the same gap for future migrations.

## Acceptance Criteria

- [ ] Pre-flight: SSH chi-srv-01 + verify script exists at `/mnt/projects/O/OBD2v2/scripts/backfill_server_battery_health_log_stranded.py`; run with `--dry-run` to confirm it would update 5 rows
- [ ] Run with `--execute`; server rows 11-15 end_timestamp + end_soc + runtime_seconds populated matching Pi-side state
- [ ] Idempotent guard verified: re-run with `--execute` is no-op on populated rows
- [ ] Path B if Mike directs: wire into deploy-server.sh OR systemd timer

## Source

- Spool 2026-05-12 Drive 11 validation note (Story Y)
- V0.27.6 US-323 ship note (Ralph progress.txt) — script created but no execute mechanism
