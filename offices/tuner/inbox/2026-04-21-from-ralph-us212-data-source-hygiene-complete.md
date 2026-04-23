# US-212 -- Benchtest data_source hygiene: complete

**From**: Rex (Ralph)
**To**: Spool
**Date**: 2026-04-21
**Sprint**: 16 (Wiring)
**Story**: US-212 (S, high) -- `passes: true`
**Prior**: closes the root cause of the 352K 'real' rows that surfaced in US-205.

## What shipped

Every non-live-OBD INSERT into a capture table now tags `data_source`
explicitly. The live-OBD writer still inherits the schema DEFAULT
`'real'`, but it now auto-derives the tag from `connection.isSimulated`
so the simulator path (which shares the live-OBD writer) no longer
accidentally stamps rows as `'real'`. Closes the US-195 DEFAULT-catchall
hygiene bug you filed.

### Call-site classification (acceptance #1)

Grep `INSERT INTO (realtime_data|connection_log|statistics|calibration_sessions|profiles|dtc_log|drive_summary)` across `src/` + `scripts/`:

| File:Line | Table | Class | Disposition |
|-----------|-------|-------|-------------|
| `src/pi/obdii/data/logger.py:307` | `realtime_data` | live-OBD + simulator (shared) | **Auto-derives** from `connection.isSimulated` (real or physics_sim); explicit override accepted |
| `src/pi/obdii/data/helpers.py:104` | `realtime_data` | live-OBD helper | Same: `dataSource` kwarg, defaults to `'real'` |
| `src/pi/analysis/engine.py:693` | `statistics` | live analytics | Unchanged (post-drive computation on real rows; DEFAULT `'real'` correct) |
| `src/pi/calibration/session.py:57` | `calibration_sessions` | live user action | Unchanged (manual calibration = real) |
| `src/pi/profile/manager.py:137` | `profiles` | DDL seed | Unchanged (profiles are DDL-level, not capture data) |
| `src/pi/profile/switcher.py:615` | `connection_log` | live profile change | Unchanged |
| `src/pi/obdii/obd_connection.py:550` | `connection_log` | live BT connect | Unchanged |
| `src/pi/obdii/shutdown/manager.py:285` + `command_core.py:361` | `connection_log` | live shutdown | Unchanged |
| `src/pi/data/connection_logger.py:180` | `connection_log` | live US-211 helper | Unchanged |
| `src/pi/obdii/drive/detector.py:762` | `connection_log` | live drive_start/end | Unchanged |
| `src/pi/obdii/data_retention.py:465` | `connection_log` | live cleanup | Unchanged |
| `src/pi/obdii/dtc_logger.py:254` | `dtc_log` | live Mode 03/07 | Unchanged (DEFAULT 'real' correct for live ECU read) |
| `src/pi/obdii/drive_summary.py:429` | `drive_summary` | live summary | Already tagged explicitly (US-206) |
| **`scripts/seed_scenarios.py:154,174,221`** | 3 tables | **physics sim seeder** | **Tagged `'physics_sim'`** |
| **`scripts/seed_pi_fixture.py:310,369,374,404`** | 4 tables | **regression fixture seeder** | **Tagged `'fixture'`** |

Test-harness INSERTs (under `tests/`) are intentionally out of scope --
they write to isolated per-test SQLite files, never the operational DB.

## Enforcement (acceptance #4)

`tests/pi/data/test_data_source_hygiene.py` (13 tests, all green):

1. **AST audit** (`TestSeedScriptHygiene`, 2 parametrized tests) parses
   `scripts/seed_scenarios.py` + `scripts/seed_pi_fixture.py`, pulls
   every `INSERT INTO` string literal (handles triple-quoted +
   concatenation + f-strings), and asserts the capture-table ones all
   name `data_source`. A regression -- say someone adds a new seed
   script that forgets to tag -- fails this test immediately.
2. **Runtime derivation** (`TestObdDataLoggerDataSourceDerivation`, 6
   tests) exercises the new `ObdDataLogger.dataSource` parameter:
   - Live connection (no `isSimulated`) -> `'real'`.
   - Simulated connection (`isSimulated=True` on
     `SimulatedObdConnection`) -> `'physics_sim'`.
   - Explicit override wins.
   - Invalid value (e.g. `'bogus'`) raises `ValueError` at construction.
   - `logReading()` actually writes the derived tag to the DB.
3. **Helper override** (`TestHelpersLogReadingDataSource`, 4 tests):
   `helpers.logReading` accepts a `dataSource` kwarg, defaults to
   `'real'`, rejects unknown values, and persists the value to the row.
4. **Enum stability** (`test_enumValues_unchanged`): pins the 4-value
   tuple so no one silently adds a 5th without updating downstream.

## Invariants honored

- Schema DEFAULT stays `'real'`. No column default change (acceptance
  stopCondition respected).
- CHECK constraint enum unchanged (`real`/`replay`/`physics_sim`/`fixture`).
- No data migration -- US-205 already truncated; new writes land
  correctly going forward.
- Server-side `data_source` column stays untouched (Pi-side writers
  only, per scope).
- Existing test_data_source_column.py (US-195 schema tests) continues
  to pass -- no backward-incompatible changes to the column DDL.

## Changes summary

**New file**
- `tests/pi/data/test_data_source_hygiene.py` -- 13 tests

**Source modified**
- `src/pi/obdii/simulator/simulated_connection.py` -- added
  class-level `isSimulated = True` sentinel
- `src/pi/obdii/data/logger.py` -- `ObdDataLogger.__init__(..., dataSource=None)`
  + `_resolveDataSource()` helper + `INSERT INTO realtime_data` now
  names `data_source` column
- `src/pi/obdii/data/helpers.py` -- `logReading(db, reading, dataSource='real')`
  + `createDataLoggerFromConfig` + `createRealtimeLoggerFromConfig`
  thread the kwarg
- `src/pi/obdii/data/realtime.py` -- `RealtimeDataLogger.__init__`
  forwards `dataSource` to the inner `ObdDataLogger`

**Seed scripts tagged**
- `scripts/seed_scenarios.py` -- all 3 capture INSERTs tag
  `'physics_sim'`
- `scripts/seed_pi_fixture.py` -- all 4 capture INSERTs tag
  `'fixture'`

**Docs**
- `src/pi/obdii/database_schema.py` -- module docstring now names the
  DEFAULT 'real' as a narrow safety net for the live-OBD path ONLY
- `specs/architecture.md` §5 -- "Data Source Tagging" section
  tightened per your Spool note (Default paragraph + `physics_sim` +
  `fixture` ownership table rewritten). Points to the AST audit as
  the enforcing test.

## Verification (acceptance #5-7)

```bash
pytest tests/pi/data/test_data_source_hygiene.py -v     # 13 passed
pytest tests/pi/data/ tests/pi/simulator/ -m "not slow" # 213 passed, 0 regressions
ruff check src/ scripts/ tests/                          # All checks passed!
python validate_config.py                                # 4/4 OK
python offices/pm/scripts/sprint_lint.py                 # 0 errors (pre-existing sizing warnings unchanged)
```

## What this unblocks

- Future benchtest runs on the Pi no longer accumulate 'real'-tagged
  synthetic rows. The simulator + any script that writes capture rows
  tags explicitly, and the AST audit test catches regressions at PR
  time.
- Server-side `WHERE data_source = 'real'` filter regains its meaning
  -- baseline calibrations, AI prompts, and analytics now see genuine
  live-vehicle rows only (once any new runs happen; US-205 already
  truncated prior pollution).
- The US-208 first-drive validator can now assert
  `data_source='real'` as a genuine signal of real-vehicle capture.

## Not in scope (filed separately if needed)

- connection_log writers (drive detector, shutdown, BT connect) still
  rely on DEFAULT 'real'. If the simulator ever fires one of these
  paths (e.g., by running `--simulate` with a real BT adapter attached
  -- unlikely), it would mis-tag. Mitigated by:
  - simulator path uses `SimulatedObdConnection`, which does not reach
    these real-hardware paths today;
  - eclipse-obd.service no longer runs with `--simulate` (US-210).
  If you want these hardened anyway (full defense-in-depth), file a
  follow-up.
- Server-side mirror columns were out of scope per the sprint
  contract (`doNotTouch` explicit).

-- Rex
