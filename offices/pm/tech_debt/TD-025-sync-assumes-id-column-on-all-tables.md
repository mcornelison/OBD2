# TD-025: SyncClient assumes every in-scope table has an `id` column

| Field        | Value                                                |
|--------------|------------------------------------------------------|
| Severity     | High (blocks production Pi → server sync from a fresh-init DB) |
| Status       | Open                                                 |
| Filed By     | Marcus (PM), Session 23, 2026-04-19                  |
| Surfaced In  | Sprint 13 PM+CIO milestone drill — attempted to push 149 freshly-captured rows to chi-srv-01 after live drive |
| Blocking     | Any production Pi → server sync after a fresh `python src/pi/main.py` orchestrator init |

## Problem

`src/pi/data/sync_log.py:getDeltaRows()` runs:

```python
SELECT * FROM {tableName} WHERE id > ? ORDER BY id ASC LIMIT ?
```

This assumes **every table in `IN_SCOPE_TABLES`** has an `id` column. Two of them don't:

| Table                 | Actual PK         | Has `id` col? |
|-----------------------|-------------------|---------------|
| `realtime_data`       | id INTEGER PK     | ✅            |
| `statistics`          | id INTEGER PK     | ✅            |
| `profiles`            | id INTEGER PK     | ✅            |
| `ai_recommendations`  | id INTEGER PK     | ✅            |
| `connection_log`      | id INTEGER PK     | ✅            |
| `alert_log`           | id INTEGER PK     | ✅            |
| **`vehicle_info`**    | **vin TEXT PK**   | ❌            |
| **`calibration_sessions`** | **session_id INTEGER PK** | ❌      |

When `pushAllDeltas()` iterates the in-scope set, it crashes on the first table without `id`:

```
sqlite3.OperationalError: no such column: id
```

This stops the entire sync, including all the id-having tables it would otherwise push successfully.

## Why Sprint 11 didn't catch this

Sprint 11's e2e sync drill used a pre-existing fixture DB (`session17_multi.db`) that had been exported with `id` columns on every table — a property of the export format, not the production schema. The fresh-init schema produced by `src/pi/obdii/database.py:initialize()` correctly preserves the natural PKs on `vehicle_info` (vin) and `calibration_sessions` (session_id), which **is the right schema** but breaks the sync code's assumption.

## Workaround Attempted (Session 23)

PM tried to write `/tmp/push_safe.py` on the Pi calling `SyncClient.pushDelta('realtime_data')` directly to bypass the broken tables, but the project's import path quirks (`src.pi.sync.client` vs `pi.sync.client`) failed under `sys.path.insert(0, "src")`. Did not push the milestone data tonight. The 149 rows remain Pi-local at `~/Projects/Eclipse-01/data/obd.db`.

## Proper Fix (Ralph)

Two valid approaches:

### Option A — Per-table PK column registry

Replace the global `id` assumption with a per-table PK-column map:

```python
PK_COLUMN: dict[str, str] = {
    'realtime_data': 'id',
    'statistics': 'id',
    'profiles': 'id',
    'ai_recommendations': 'id',
    'connection_log': 'id',
    'alert_log': 'id',
    'vehicle_info': 'vin',                    # natural TEXT PK
    'calibration_sessions': 'session_id',     # INTEGER PK with non-standard name
}
```

Then `getDeltaRows`/`updateHighWaterMark` use `PK_COLUMN[tableName]`. Note that `lastId` may need to be string-typed for `vehicle_info` (or `vin`-based delta makes no sense for an upsert table — see Option B).

### Option B — Drop the upsert/static tables from the delta-sync set

`vehicle_info` and `calibration_sessions` are upsert/static tables, not append-only event streams. They don't fit the delta-by-id model. Move them to a separate "full sync" or "upsert sync" pathway, and remove from `IN_SCOPE_TABLES`.

This is probably the cleaner fix. The sync model is "stream new rows since last id" — that's only meaningful for append-only tables.

## Acceptance for Fix

- `python scripts/sync_now.py` against a fresh-init Pi DB completes successfully
- All append-only tables push their deltas
- `vehicle_info` either upserts via separate path or is excluded from delta sync
- New regression test in `tests/pi/sync/` covers the per-table PK or the exclusion (whichever path chosen)
- `scripts/sync_now.py --dry-run` reports counts correctly without crashing

## Related

- Sprint 13 closeout milestone drill: 149 rows captured but not pushed due to this bug
- Carryforward note: `offices/ralph/inbox/2026-04-19-from-marcus-sprint13-carryforward.md`
- Sibling Sprint 13 TDs: TD-023 (OBD connection MAC vs serial), TD-024 (status_display GL crash)
- BL-006 resolution: this TD is the third bug surfaced by the milestone drill
