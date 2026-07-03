# TD-061 — Pi has no `schema_migrations` version ledger (N-3)

| Field | Value |
|---|---|
| Source | Argus finding 2026-05-12 (N-3); re-verified live 2026-07-02 (US-437 triage) |
| Severity | Low (structural / hygiene — not a correctness bug) |
| Size | M–L |
| Raised by | Rex (US-437) |
| Related | F-082 (rollup), server `src/server/migrations/runner.py` (the symmetric server mechanism) |

## What

The server tracks schema evolution in a versioned `schema_migrations` table
(`src/server/migrations/runner.py` + `versions/v00XX_*.py`). The **Pi has no
migration-history table at all** — re-confirmed live 2026-07-02: the Pi obd.db
`sqlite_master` contains no `schema_migrations`/`migration*`/`alembic*` table.

The Pi instead evolves its schema via `CREATE TABLE IF NOT EXISTS`
(`database_schema.ALL_SCHEMAS`) plus ~12 idempotent `ensureX()` migrators run on
**every boot** in `src/pi/obdii/database.py:initialize()` (e.g.
`ensureAllDriveIdColumns`, `ensureBatteryHealthLogSocPctColumns`,
`ensurePowerLogDataQuality`, `ensureDriveStatisticsRetired`, and — new this
sprint — `ensureBatteryLogRetired`). None record a version row; each re-probes
schema and re-applies.

## Why it's only Low / deferred (not folded into US-437)

The idempotent "converge on every boot" pattern **already bounds the drift
harm** — every guard re-runs and self-heals on each boot, so a Pi can't silently
diverge from code-expected schema the way an un-tracked ad-hoc SQL fix could.
The missing ledger is a *visibility* gap (no way to ask "what version is this Pi
at / what's pending"), not a correctness gap. Building a proper Pi ledger touches
all ~12 existing migrators and needs a versioning convention → M–L, its own
story, not US-437 scope.

## Suggested approach (when scheduled)

New `src/pi/obdii/migration_ledger.py` (or extend `database.py:initialize`)
mirroring the server `runner.py` model: a `schema_migrations` table on the Pi,
each `ensureX` application recorded as a version row exactly once, re-init a
clean no-op with the ledger intact. Tests assert (a) table created on fresh
init, (b) each migrator writes its version row once, (c) idempotent re-init.
