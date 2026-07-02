# Issue — `sync_history` failed-row backlog is not pruned (N-1)

| Field | Value |
|---|---|
| Source | Argus finding 2026-05-12 (N-1); re-verified live 2026-07-02 (US-437 triage) |
| Severity | Low (log accumulation / observability noise — not a data-integrity bug) |
| Raised by | Rex (US-437) |
| Disposition | Flagged for PM — this is a live-DB ops decision, not a dev code fix |

## Finding (verify-first, US-437)

The 2026-05-12 finding reported 8,505 of 20,283 `sync_history` rows `status='failed'`
from two modes, both since **resolved structurally**:
- (a) `drive_summary ... doesn't have a default value` — fixed by migration `v0006` (newest such failure 2026-05-01, historical).
- (b) `Record has changed since last read` optimistic-lock race — historical (not in current top modes).

## Current live state (server obd2db @ chi-srv-01, 2026-07-02)

```
status     count   MAX(started_at)
completed  35925   2026-07-02 22:31:42
failed     48962   2026-06-30 00:10:42
```
The failed backlog has **grown to 48,962** — dominated by a *newer* mode not in the
original finding:
- `dtc_freeze_frame sync: no vehicle_info row for vin '4A3AK54F8WE122916' ... cross-tier FK resolution failed` — **40,457 rows, surged 2026-06-20 → 06-30, now cleared** (0 failed the last two days). This is **fail-loudly-by-design** (`src/server/api/sync.py:667-672`, US-369 — an unresolvable VIN raises rather than silently re-resolving); it drained once the `vehicle_info` lineage row for that VIN existed. NOT a code regression.

Sync is currently healthy (2026-07-01: 9,353 completed / 0 failed; 2026-07-02: 799 / 0).

## The actual gap

A prune mechanism **exists** — `src/server/migrations/versions/v0007_sync_history_retention.py`
(`DELETE FROM sync_history WHERE started_at < NOW() - INTERVAL N DAY`, default 90d,
`SYNC_HISTORY_RETENTION_DAYS`-overridable) — but it is:
1. **age-based only, not status-scoped** — it never targets `status='failed'`, so the
   failed backlog is not shrunk; failed rows only age out at 90 days.
2. a **deploy-time one-shot** run by `MigrationRunner`; the migration's own docstring
   says ongoing pruning "is a separate concern (cron / scheduled task)" — and no such
   scheduler exists in `src/` (only the migration calls `buildDeleteSql`).

## Recommended action (PM / ops call — no dev fix shipped in US-437)

- Ops: a one-time `DELETE FROM sync_history WHERE status='failed'` (with a
  `mysqldump --single-transaction` backup first per the DB-access rule) to clear the
  ~48.9k historical failed rows, OR extend `v0007` to status-scope the prune.
- Keep an eye on the `dtc_freeze_frame` VIN-FK condition — it's a data-lineage
  dependency (freeze-frame arriving before its `vehicle_info` parent), not a defect,
  but it's the current top failure generator when it fires.
