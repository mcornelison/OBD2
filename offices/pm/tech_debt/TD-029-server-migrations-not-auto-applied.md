# TD-029: Server schema migrations not auto-applied on deploy

| Field        | Value                                                 |
|--------------|-------------------------------------------------------|
| Severity     | Medium (CI false-green; silent prod divergence until next live-touching story) |
| Status       | **Open — recommend Sprint 16+ fix** (Alembic or explicit `deploy-server.sh` migration gate) |
| Filed By     | Agent3 (Ralph), Session 2026-04-20, during US-209 (server schema catch-up) |
| Surfaced In  | Ralph US-205 --dry-run 2026-04-20 — truncate script detected 9 schema divergences because US-195 (data_source) + US-200 (drive_id + drive_counter) SQLAlchemy model changes never ran as ALTER/CREATE on the live chi-srv-01 MariaDB |
| Blocking     | Unblocks itself for US-209 (resolved inline via `scripts/apply_server_migrations.py`). Leaves the underlying **deploy-flow gap** unresolved — the next schema change (US-204 `dtc_log`, US-206 `drive_summary` with drive_id FK) will hit the same pattern unless Sprint 16 addresses it. |
| Related      | US-195 (Session 65), US-200 (Session 66), US-205 (Session 72 halt), US-209 (this session), TD-028 (contract-drift lint pattern — precedent for set-equality tests that catch divergence before it ships) |

## Problem

When a Sprint story adds columns or tables on the Pi side AND mirrors them in SQLAlchemy server models, **nothing currently runs the DDL on the live chi-srv-01 MariaDB**. The assumption was `Base.metadata.create_all` handles schema, but `create_all` **only adds missing tables — it does not ALTER existing tables to add columns or indexes**. The SQLAlchemy model code was tested against ephemeral SQLite fixtures in CI, so the gap went unnoticed for two full sprints (Sessions 65 through 71).

Evidence from US-205 --dry-run (2026-04-20):

- Pi `realtime_data`: 352,508 rows tagged `data_source='real'` (expected after US-195).
- Server `realtime_data`: 26,765 rows with **no `data_source` column**. Query `SELECT COUNT(*) WHERE data_source='real'` fails with `ERROR 1054: Unknown column`.
- Server `drive_counter`: table does not exist. `nextDriveId()` against the server is currently schema-impossible.

Any analytics / sync / AI prompt code that assumes server tables have the Pi-aligned shape has been silently degrading on this divergence since mid-Sprint-14.

## Immediate fix (landed with US-209)

`scripts/apply_server_migrations.py` (US-209) closes the data_source + drive_id + drive_counter gap for 4 capture tables:

- `realtime_data`, `connection_log`, `statistics` — ADD COLUMN data_source + ADD COLUMN drive_id + ADD INDEX
- `alert_log` — ADD COLUMN drive_id + ADD INDEX (data_source intentionally excluded per Pi CAPTURE_TABLES carve-out)
- `profiles`, `calibration_sessions` — ADD COLUMN data_source (from CAPTURE_TABLES scope)
- `drive_counter` — CREATE TABLE + seed singleton (`id=1, last_drive_id=0`)

Script is idempotent: re-running emits zero DDL on an already-migrated DB. Safety posture: --dry-run probes INFORMATION_SCHEMA + prints the plan, --execute refuses without a prior --dry-run sentinel, backs up via `mysqldump --single-transaction` BEFORE any DDL, enforces per-statement timing guards (30s per ALTER, 60s for backup, 500 MB backup size ceiling).

**But the script is a one-shot — it does not prevent the next schema drift from happening the same way.**

## Root-cause fix (recommended for Sprint 16+)

Pick one. Ranked by effort vs robustness:

### Path A — Alembic (robust, industry-standard; ~2-3 day story)

Add Alembic to `requirements-server.txt`. Initialize `alembic/` directory with autogenerate against current SQLAlchemy models as the baseline. Every subsequent schema change generates a migration file checked into git. `deploy-server.sh --init` and the non-init path both run `alembic upgrade head` after the git pull step. Adds: migration history table, rollback support, deterministic schema under version control.

**Cost**: learning curve (moderate), one-time baseline migration needs manual review (autogenerate misses CHECK constraints sometimes), adds a dependency. **Benefit**: proper schema history; every future story's server-side DDL is self-applying.

### Path B — Explicit migration gate in deploy-server.sh (lightweight; ~1 day story)

Add a `deploy/migrations/` directory with timestamped SQL files (`2026-04-20-001-us195-data-source.sql`, etc.). `deploy-server.sh` adds a step between git pull and service restart: enumerate unapplied migrations (tracked via a `_schema_migrations` table), run each in a transaction, record the applied version. Same bookkeeping Alembic does but hand-rolled and MariaDB-specific.

**Cost**: bespoke tooling to maintain, reinvention-of-wheel. **Benefit**: zero dependencies, transparent, matches the "one deploy script, keep it simple" directive in `offices/ralph/CLAUDE.md`.

### Path C — Keep apply_server_migrations.py as the permanent pattern (cheap but brittle; zero new work)

Declare `scripts/apply_server_migrations.py` the canonical migration script; every future schema-adding story either extends it or adds a sibling script with a `--dry-run` / `--execute` gate. CIO runs the script manually after each deploy. No auto-apply.

**Cost**: relies on human memory at deploy time (exactly the failure mode this TD is documenting); migration scripts proliferate; no audit trail of what ran when. **Benefit**: zero engineering work until a human forgets.

### Ralph's recommendation

**Path B** — it matches CIO's "single deploy script, lockstep, keep it simple" directive (offices/ralph/CLAUDE.md), uses existing bash + SQL familiarity, and costs about a day. Path A is technically superior but adds a learning curve and one more moving piece in a project that's deliberately avoided framework bloat. Path C is the null option and would guarantee TD-030 for the next story that adds columns.

## Additional cleanup recommendations (low-priority)

1. **SQLAlchemy `Integer` → `BigInteger` for `drive_id` columns** (models.py lines 134, 174, 303, 333). The docstring in `src/pi/obdii/drive_id.py` explicitly says "play well with SQLAlchemy's BigInteger mapping on the server side" but the actual model code uses `Integer` (MariaDB INT 32-bit). US-209 migrates the live DB to BIGINT per the PM grounding gloss in sprint.json. If the SQLAlchemy model ever runs `create_all` against a fresh dev DB, it will recreate the columns as INT — a dev/prod divergence. Update the models to `BigInteger` so the two agree.
2. **Consider adding a CI job that spins up a real MariaDB container and runs the full server test suite against it** — this would have caught TD-029 at CR review time in Session 65 when US-195 shipped. SQLite ephemeral fixtures can't catch MariaDB-specific schema concerns (CHECK constraint enforcement, INFORMATION_SCHEMA semantics, VARCHAR length behavior).

## Not in scope for this TD

- US-204 `dtc_log` table creation — that's inside US-204's scope and will be written against whichever deploy-flow fix Sprint 16 picks.
- US-206 `drive_summary` server mirror — same, within US-206.
- Pi-side migrations — Pi's `ObdDatabase.initialize()` already handles idempotent ALTER on every boot (US-195 / US-200 pattern in `src/pi/obdii/data_source.py::ensureAllCaptureTables` + `drive_id.py::ensureAllDriveIdColumns`). Pi side is solid; the gap is server-only.

## Verification after Sprint 16 fix

Whichever path is chosen, the regression guard should be:

1. A CI job that drops + recreates a fresh MariaDB, runs the migration chain, and then runs the server test suite end-to-end.
2. A `sprint_lint`-style check that flags any SQLAlchemy model change without a corresponding migration file / autogenerate entry.
3. Deployment smoke test: after `deploy-server.sh`, run `python scripts/apply_server_migrations.py --dry-run` and assert the plan is empty.

## Filed with US-209 ship

- `scripts/apply_server_migrations.py` — the US-209 fix script (new, 500+ lines, stdlib-only)
- `tests/scripts/test_apply_server_migrations.py` — 39 tests green (Session 2026-04-20)
- This file — TD-029 documenting the underlying CI gap and recommending Sprint 16 fix
