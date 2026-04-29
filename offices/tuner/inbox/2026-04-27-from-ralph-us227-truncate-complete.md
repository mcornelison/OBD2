# US-227 truncate complete -- Pi + server, Drive 3 preserved

**From:** Rex (Ralph Agent 1)
**To:** Spool (Tuner SME)
**Date:** 2026-04-27
**Re:** Sprint 18 / US-227 closure

## TL;DR

drive_id=1 / data_source='real' pollution wiped on both Pi and server.
Drive 3 (6,089 rows on `drive_id=3`) preserved on both sides.
drive_counter advanced to 3 idempotently.
Regression fixture hash unchanged.
Sync gate enforced before --execute (would have refused if Drive 3 still stranded).
BL-007 closed by Marcus pre-flight; this story executes against the post-deploy
state Marcus left.

## Before / after

### Pi (chi-eclipse-01:~/Projects/Eclipse-01/data/obd.db)

| Metric                                          | Before | After |
|-------------------------------------------------|--------|-------|
| realtime_data drive_id=1 / real                 | 2,939,090 | 0 |
| connection_log drive_id=1 / real                | 2 | 0 |
| dtc_log drive_id=1 / real                       | 0 | 0 |
| statistics drive_id=1 / real                    | 0 | 0 |
| drive_summary drive_id=1                        | 0 | 0 |
| **realtime_data drive_id=3 / real (Drive 3)**   | 6,089 | **6,089 (preserved)** |
| realtime_data drive_id=2 / physics_sim          | 1,853 | 1,853 (preserved) |
| realtime_data NULL drive_id / real (US-233)     | 413 | 413 (preserved) |
| realtime_data NULL drive_id / physics_sim       | 171 | 171 (preserved) |
| drive_counter.last_drive_id                     | 3 | 3 (idempotent no-op) |

### Server (chi-srv-01:obd2db MariaDB)

| Metric                                          | Before | After |
|-------------------------------------------------|--------|-------|
| realtime_data drive_id=1 / real                 | 812 | 0 |
| connection_log drive_id=1 / real                | 2 | 0 |
| statistics drive_id=1 / real                    | 0 | 0 |
| **realtime_data drive_id=3 / real (Drive 3)**   | 6,089 | **6,089 (preserved)** |
| realtime_data NULL drive_id / real              | 188 | 188 (server-side US-233 territory) |
| drive_counter.last_drive_id                     | 0 | 3 (advanced) |

### Regression fixture (must not drift)

```
sha256 = 0b90b188fa31f6285d8440ba1a251678a2ac652dd589314a50062fa06c5d38db
bytes  = 188416
```

Hash matches `truncate_session23.FIXTURE_EXPECTED_SHA256` exactly, pre and
post the --execute. Same fixture state as US-205 close.

## Backup paths (kept for rollback)

- Pi:     `chi-eclipse-01:~/Projects/Eclipse-01/data/obd.db.bak-truncate-20260427-135844Z` (509 MB SQLite snapshot)
- Server: `chi-srv-01:/tmp/obd2-truncate-backup-20260427-135844Z.sql` (1.9 MB mysqldump)

Both retained per US-205 precedent (operator deletes when comfortable; no
auto-rotation).

## How the script differs from US-205 (operational notes)

| Concern | US-205 | US-227 |
|---------|--------|--------|
| WHERE clause | `data_source='real'` (everything) | `drive_id=1 AND data_source='real'` (scoped) |
| drive_counter target | reset to 0 | advance to 3 (idempotent; never regress) |
| Sync gate | none | refuses --execute unless `sync_log.realtime_data.last_synced_id ≥ 3,439,960` |
| Sentinel filename | `.us205-dry-run-ok` | `.us227-dry-run-ok` (no collision) |
| Orphan-scan window | 2026-04-19 07:18..07:20 | 2026-04-21 02:27..2026-04-23 03:12 (Spool's pollution window) |
| Tables targeted | hardcoded list (4) | data-driven enumeration: any table with both `drive_id` + `data_source` columns (excludes `drive_summary` per doNotTouch) |
| Helpers | self-contained | imports SSH/backup/fixture helpers from `scripts/truncate_session23.py` -- one file per snapshot, plumbing reused |

## What this enables for you

- Drive 3 is now the cleanly-identifiable real warm-idle / drive baseline on
  both Pi and server (drive_id=3, all rows tagged `real`, no pollution
  drowning it out in the per-drive_id row counts).
- `realtime_data` per-drive distribution is now legible: NULL/3/(future).
- US-219 review ritual against Drive 3 is unblocked by the server-side row
  landing (Marcus's bridge sync).
- Spool's "Real Vehicle Data" knowledge.md update against Drive 3 (your
  Sprint 18 parallel deliverable) can reference the post-truncate state as
  the authoritative baseline.

## Out-of-scope follow-ups (NOT done by US-227)

- **Server-side NULL drive_id / real (188 rows)**: pre-mint orphans that
  landed via Marcus's bridge sync. US-233's backfill script ran on Pi only;
  the server-side equivalent needs either a separate Sprint 19 story or a
  re-run of `scripts/backfill_premint_orphans.py` adapted for the server's
  cursor-based sync semantics. Flagged in Session 103 close note already.
- **Pi NULL drive_id rows (413 real + 171 sim)**: out of US-227 scope per
  story doNotTouch. US-233 territory (already shipped on Pi).

## Verification commands the operator can re-run

```
# Pi
ssh mcornelison@10.27.27.28 "sqlite3 ~/Projects/Eclipse-01/data/obd.db \
  'SELECT drive_id, data_source, COUNT(*) FROM realtime_data \
   GROUP BY drive_id, data_source ORDER BY drive_id, data_source'"

# Server (via the script's helper to avoid DSN parsing pitfalls)
python -c "
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('us227', 'scripts/truncate_drive_id_1_pollution.py')
mod = importlib.util.module_from_spec(spec); sys.modules['us227'] = mod
spec.loader.exec_module(mod)
addrs = mod.loadAddresses(Path('deploy/addresses.sh'))
creds = mod.loadServerCreds(addrs)
print(mod._runServerSql(addrs, creds,
    'SELECT drive_id, data_source, COUNT(*) FROM realtime_data \
     GROUP BY drive_id, data_source ORDER BY drive_id, data_source;',
    mod._defaultRunner).stdout)
"

# Fixture hash
python -c "import hashlib; print(hashlib.sha256(open('data/regression/pi-inputs/eclipse_idle.db','rb').read()).hexdigest())"
```

— Rex
