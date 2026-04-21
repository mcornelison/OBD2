# US-205 truncate complete — Pi + server at clean slate, fixture intact

**Date**: 2026-04-20
**From**: Rex (Ralph / Agent 3)
**To**: Spool (Tuner SME)
**Priority**: Routine confirmation
**Re**: `offices/pm/inbox/2026-04-20-from-spool-session23-truncate-request.md` +
`offices/pm/inbox/2026-04-20-from-spool-us205-amendment.md`

## Result

Clean slate achieved. `drive_counter.last_drive_id = 0` on both Pi and server.
Next real Eclipse drive mints `drive_id = 1`.

## Pre-truncate state (at the final `--dry-run`, after US-209 shipped)

| Host | Table | data_source='real' rows | drive_counter | notes |
|------|-------|------------------------|---------------|-------|
| Pi (chi-eclipse-01) | `realtime_data` | 491,653 | `last_drive_id=2` | timestamp span 2026-04-19 07:18:50 → 2026-04-20 21:28:54Z |
| Pi | `connection_log` | 20 | — | |
| Pi | `statistics` | 11 | — | |
| Pi | `alert_log` | 0 (total, no `data_source` column — per `data_source.py::CAPTURE_TABLES` carve-out) | — | |
| Server (chi-srv-01) | `realtime_data` | 26,765 | `last_drive_id=0` (seeded by US-209) | |
| Server | `connection_log` | 34 | — | |
| Server | `statistics` | 75 | — | |
| Server | `alert_log` | 0 (total, no `data_source` — server mirror honors the Pi carve-out per US-209) | — | |
| Fixture | `eclipse_idle.db` | 149 rows / 188,416 bytes / SHA `0b90b188fa31f628…` | — | frozen, untouched |
| Orphan scan | `ai_recommendations` + `calibration_sessions` | 0 / 0 in Session 23 window | — | clean |

The Pi count (491,653) is larger than the 352,508 Rex scanned in Session 72
because benchtest activity continued between sprint sessions. Per your
Amendment 1, the full scope is the intended truncate target — wipe semantics
are correct regardless of size.

## Post-truncate state (verified)

| Host | Table | data_source='real' rows | drive_counter |
|------|-------|------------------------|---------------|
| Pi | `realtime_data` | 0 | `last_drive_id=0` |
| Pi | `connection_log` | 0 | — |
| Pi | `statistics` | 0 | — |
| Pi | `alert_log` | 0 (total) | — |
| Server | `realtime_data` | 0 | `last_drive_id=0` |
| Server | `connection_log` | 0 | — |
| Server | `statistics` | 0 | — |
| Server | `alert_log` | 0 (total) | — |
| Fixture | `eclipse_idle.db` | 188,416 bytes / SHA `0b90b188fa31f628…` | — | hash match ✓ |

## Backups

| Host | Path | Size / timestamp |
|------|------|------------------|
| Pi | `/home/mcornelison/Projects/Eclipse-01/data/obd.db.bak-truncate-20260420-213809Z` | per last `--execute` run (the 2 prior runs produced `.bak-truncate-20260420-213248Z` and `.bak-truncate-20260420-213518Z`, all intact) |
| Server | `/tmp/obd2-truncate-backup-20260420-213809Z.sql` | `mysqldump --single-transaction` of all four capture tables plus `ai_recommendations` + `calibration_sessions` |

## Two things I fixed in the script while closing this

Both are in-scope (`filesToTouch: [scripts/truncate_session23.py]`) and both
directly follow your Amendment 2 / Amendment 3 guidance:

1. **Server `alert_log` data_source carve-out** (amendment 2): the
   `divergenceDetected` function only had the carve-out on the Pi loop. I
   added the same carve-out to the server loop so `--execute` stops
   refusing over a column that was deliberately omitted from both sides.
   The `drive_id` check on `alert_log` still runs (US-209 added it).
2. **Service state preservation** (amendment 3 hygiene bug): `_runExecute`
   captured whether the Pi service was active before stopping it, and the
   `finally` block now only restarts if it was active at entry. The prior
   force-start meant every `--execute` race-repopulated with benchtest-
   tagged-as-real rows within seconds. Two new tests pin both branches.

## Pi service left stopped

Per the hygiene bug, the `eclipse-obd.service` auto-collects data and the
DEFAULT `'real'` tag contaminates the clean slate. I stopped the service
and left it stopped. Before the first real drive, operator must:

```bash
ssh mcornelison@10.27.27.28 'sudo systemctl start eclipse-obd.service'
```

This is documented in `specs/architecture.md` §5 Invariant #4. A proper
fix comes via the separate benchtest-hygiene story you filed (`offices/pm/
inbox/2026-04-20-from-spool-benchtest-data-source-hygiene.md`).

## Amendment 1 (352K → actual 491K) — intent preserved

The row count doesn't matter; the clean slate does. Session 23's 149
captures live forever in `data/regression/pi-inputs/eclipse_idle.db` with
a hash pin in the script constants (`FIXTURE_EXPECTED_SHA256`). Nothing
about Session 23's empirical fingerprint in `grounded-knowledge.md`,
`obd2-research.md`, or your `knowledge.md` was touched.

## Amendment 2 (alert_log carve-out) — handled via script fix above

`alert_log` skipped on both sides because both sides lack `data_source`.
Currently 0 rows on both. Script future-proofed: if a future US-X adds
`data_source` to `alert_log`, the `ts.hasDataSourceColumn`-gated
`DELETE FROM alert_log WHERE data_source='real'` branch will activate
automatically.

## Amendment 3 (benchtest hygiene bug) — out of scope, filed

Your standalone story note
(`offices/pm/inbox/2026-04-20-from-spool-benchtest-data-source-hygiene.md`)
is in Marcus's queue. I did NOT audit benchtest writers this session —
that's the separate hygiene story's scope.

— Rex
