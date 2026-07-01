# Atlas Ruling — US-416 startup_log sync (TEXT-PK natural-key snapshot path)

**By:** Atlas (Architect) · **Date:** 2026-07-01 · **Requested by:** Marcus (`2026-07-01-from-marcus-us416-startup-log-sync-design-gate`)
**Decision: build the GENERAL `SNAPSHOT_TABLES` natural-key sync path now** (CIO-directed 2026-07-01 — the F-115 EDR event-vault will reuse it). A-4 cross-tier-contract lane. Verified against the shipped code, not the note's narrative.

## Verified facts (grounding)
- `startup_log.boot_id TEXT PRIMARY KEY`, append-only `INSERT OR IGNORE` once per boot (`database_schema.py:600`, `boot_progress.py:324/337`) — immutable rows.
- No `INTEGER PRIMARY KEY` alias → the implicit `rowid` is **VACUUM-renumberable** (unsafe as a sync cursor).
- `sync_log`: `DELTA_SYNC_TABLES` = `PK_COLUMN.keys()` (integer-PK only); `SNAPSHOT_TABLES` exists solely to *reject* TEXT-PK tables from delta (`getDeltaRows` raises) — **no positive snapshot-push path exists**.
- Server: generic upsert keys `(source_device, source_id)` with `source_id` = Pi integer `id`; `dtc_freeze_frame` (`sync.py:194`) is a special-case for **cross-tier FK resolution** (US-369/F-109) — a *different* concern from natural-key dedup.

## Ruling

### Q1 — Pi push cursor: `recorded_at` time-cursor, NOT full-snapshot, NOT rowid
Append-only immutable rows → a monotonic cursor is correct; full-snapshot re-pushes all boot history every sync (O(n) waste). **Add an explicit `recorded_at` insertion-timestamp column** to `startup_log` (forward-only migration) and delta by it. **Do NOT cursor on `rowid`** — with a TEXT PK there's no INTEGER-PK alias, so `VACUUM` can renumber it and desync the cursor. Because the Q2 natural-key upsert is idempotent, **cursor precision is not safety-critical** — an over-reading cursor just harmlessly re-pushes; the cursor bounds volume, the natural key guarantees correctness.

### Q2 — Server resolver: natural-key `(source_device, boot_id)` upsert + `UNIQUE(source_device, boot_id)`
Correct shape, and the anchor that makes Q1 safe. `ON CONFLICT (source_device, boot_id) DO UPDATE` / `on_duplicate_key_update`. **Not** the integer-`source_id` registry path (there is no meaningful integer id to map). This is a **new pattern** — natural-key *dedup* — distinct from `dtc_freeze_frame`'s FK-resolution special-case; do not conflate them, and do not refactor `dtc_freeze_frame` onto this (its FK-resolution concern is orthogonal; leave shipped code alone).

### Q3 — build the GENERAL parameterized path (CIO-directed; F-115 reuse)
Not a one-off. Build a **reusable natural-key snapshot-sync mechanism parameterized per table**, so the F-115 event-vault + future TEXT-PK tables register instead of copy-pasting a branch:

- **Pi side:** a snapshot-push registry — `SNAPSHOT_SYNC: {table -> (naturalKeyCols, cursorCol)}` — plus a snapshot reader that pushes rows where `cursorCol > last_synced_cursor` (a per-table cursor stored in `sync_log`, parallel to the delta cursor). `startup_log` = first registrant: `naturalKeyCols=("boot_id",)`, `cursorCol="recorded_at"`.
- **Server side:** a natural-key upsert parameterized by the per-table `naturalKeyCols` → `UNIQUE(source_device, *naturalKeyCols)` + ON-CONFLICT upsert. One code path, table-driven.
- **A-4 anti-divergence (the reason to generalize cleanly):** the `naturalKeyCols` set for each table MUST be defined **once** and referenced by both tiers (Pi push registry ⇄ server upsert) — a single shared contract, not two hand-maintained lists that can drift. Same discipline as the EDR schema (`src/common/`). This is the whole point of generalizing: one contract, N tables, no per-table drift surface.

### Rule-10 / design-gate DoD
This changes the cross-tier **sync contract** (load-bearing) → `specs/architecture.md` sync section documents the general natural-key snapshot path + the `SNAPSHOT_SYNC` registry, in-sprint.

## Notes to Marcus
- **Sizing:** this is now larger than the one-off Ralph scoped — a general mechanism + `startup_log` as its first consumer + the `recorded_at` migration + server unique-constraint migration. Size US-416 accordingly (your lane); it's a Sprint 51 candidate, so there's room. A natural split: (a) the general path + registry + tests, (b) `startup_log` registered onto it.
- **F-115 hook:** when the EDR event-vault schema grooms, it registers into `SNAPSHOT_SYNC` rather than getting its own sync code — fold that into the F-115 design (I own that gate).
- Rule-13 on freeze as usual.

— Atlas
