# TD-079 — `schema_diff.loadPiSchema` is blind to `dtc_freeze_frame` (and to every future ensureX-only table)

**Filed by:** Rex (Ralph / Dev)
**Date:** 2026-08-10
**Found during:** US-543 (A-4 Pi↔server contract parity guard)
**Severity:** medium — a drift-detection script with a silent coverage hole
**Scope:** OUT of US-543's scope (Rule 3 scope fence) — filed, not fixed

## The defect

`scripts/schema_diff.py::loadPiSchema()` builds the Pi schema by executing a
**hand-listed registry** of `CREATE TABLE` string constants:

```python
registry: list[tuple[str, str]] = list(ALL_SCHEMAS) + [
    ('drive_summary', SCHEMA_DRIVE_SUMMARY),
    ('dtc_log', SCHEMA_DTC_LOG),
    ('battery_health_log', SCHEMA_BATTERY_HEALTH_LOG),
    ('pi_state', SCHEMA_PI_STATE),
    ('sync_log', SYNC_LOG_SCHEMA),
    ('calibration_data', SCHEMA_CALIBRATION_DATA),
]
```

`dtc_freeze_frame` is **not in that list**. It was created in US-368 via
`ensureDtcFreezeFrameTable()` and registered for sync in US-369
(`sync_log.PK_COLUMN`). So the TD-039 drift gate has been reporting "shared
tables clean" over a **synced table it cannot see at all** — 7 columns,
including the cross-tier `vehicle_info_vin` resolution.

Measured during US-543 (applied Pi schema vs `loadPiSchema()`, synced tables
only):

```
dtc_freeze_frame  appliedOnly=['captured_at_timestamp_utc','data_source',
  'dtc_log_id','id','notes','pid_responses_json','vehicle_info_vin']  ddlOnly=[]
```

## Why it is a class, not a one-off

The registry is a **hand-kept list**, so it is stale by default: every table
that arrives through an `ensureXSchema` helper is invisible until someone
remembers to add it. On the Pi, `ensureXSchema` **is** the migration system —
that is the normal way a table lands, not the exception. The same hole will
open for the next one (F-115 EDR event vault is the obvious candidate).

## Suggested fix

Replace the constants registry with the **applied** schema, which is now
available and covers every table by construction:

```python
from scripts.audit_sync_contract_parity import loadPiAppliedSchema
```

It runs `ObdDatabase.initialize()` (every ensureX helper) against a throwaway
SQLite file and reads back `PRAGMA table_info`. US-543 pins the difference in
`tests/lint/test_pi_server_contract_parity.py::TestPiLoaderReadsTheAppliedSchema`.

Caveat for whoever takes this: `loadPiSchema()` returns `dict[str, set[str]]`
and `loadPiAppliedSchema()` returns `dict[str, dict[str, ColumnSpec]]` —
`computeDiff` and `tests/scripts/test_schema_diff.py` both assume the set
shape, so this is an adapter + test-update job, not a one-line swap.

## Interim mitigation (already in place)

US-543's guard (`tests/lint/test_pi_server_contract_parity.py`) covers
`dtc_freeze_frame` today via the applied loader, so the *synced-table* surface
is no longer unguarded. This TD is about `schema_diff` — the broader Pi↔server
report — still carrying the blind spot.

## Grounding

- `scripts/schema_diff.py::loadPiSchema` — the hand-listed registry
- `src/pi/obdii/dtc_freeze_frame_schema.py::ensureDtcFreezeFrameTable` (US-368)
- `src/pi/data/sync_log.py::PK_COLUMN['dtc_freeze_frame']` (US-369)
- `scripts/audit_sync_contract_parity.py::loadPiAppliedSchema` (US-543)
