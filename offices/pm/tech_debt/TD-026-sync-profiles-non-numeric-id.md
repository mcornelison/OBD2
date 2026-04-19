# TD-026: SyncClient `getDeltaRows` casts `lastId` to int — fails on non-numeric PKs

| Field        | Value                                                |
|--------------|------------------------------------------------------|
| Severity     | Low (workaround: skip profiles in delta sync)        |
| Status       | Open                                                 |
| Filed By     | Marcus (PM), Session 23, 2026-04-19                  |
| Surfaced In  | Sprint 13 milestone push — `profiles` table push errored |
| Blocking     | Profile records (currently 'daily', 'performance') don't sync to server |

## Problem

`src/pi/data/sync_log.py:getDeltaRows()` (line 188) does `int(lastId)`
unconditionally. The `profiles` table uses `id TEXT PRIMARY KEY` with
values like `'daily'` and `'performance'`. When the sync attempts to
push profiles, the int cast fails:

```
ValueError: invalid literal for int() with base 10: 'daily'
```

This is the same family of bug as TD-025 — sync code assumes integer
auto-increment PKs everywhere. Profiles use a semantic string ID
(intentional — profiles are a small finite set, named for the use case).

## Workaround Used (Session 23)

Profiles skipped from the manual milestone push. realtime_data,
statistics, and connection_log all pushed successfully (176 rows total).

## Proper Fix

Coupled with TD-025's fix:

- **If TD-025 → Option A (per-table PK registry)**: `profiles` PK column is `id` (TEXT). Need to also drop the `int()` cast or make it type-aware per the registry.
- **If TD-025 → Option B (move upsert tables out)**: `profiles` is upsert-style too. Move it out of delta sync. Use a separate "snapshot upsert" path for the small set of profile rows.

Option B remains the cleaner path.

## Acceptance for Fix

- Profile rows reach the server via whichever sync path
- `python scripts/sync_now.py` against a fresh-init Pi DB succeeds end-to-end (closes TD-025 + TD-026 together)
- Regression test for TEXT PKs added

## Related

- TD-025 (sibling): SyncClient assumes every in-scope table has an `id` column (numeric)
- Sprint 13 milestone push log: 'profiles ERROR: ValueError: invalid literal for int() with base 10: daily'
- Carryforward note: `offices/ralph/inbox/2026-04-19-from-marcus-sprint13-carryforward.md`
