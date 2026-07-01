# BL-013: startup_log sync needs a design decision — TEXT boot_id PK doesn't fit the delta pattern

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium                    |
| Status       | Active                    |
| Blocking     | US-412 (the startup_log half only — power_log half is DONE) |
| Waiting On   | PM/Atlas decision: which sync mechanism for a TEXT-PK, insert-once table (recommend split into its own story) |
| Created      | 2026-07-01                |

## Description

US-412 asks to sync both `power_log` AND `startup_log` Pi→server "following the
battery_health_log pattern." The battery_health_log pattern is the
**delta-by-integer-PK** path (`sync_log.PK_COLUMN` → `getDeltaRows` cursor →
server `runSyncUpsert` mapping Pi `id` → `source_id`, upsert on
`(source_device, source_id)`).

**`power_log` fits that pattern perfectly** — integer `id` AUTOINCREMENT PK,
append-only — and is fully implemented + tested in this story (see completion
notes on US-412).

**`startup_log` does NOT fit it.** Its PK is `boot_id` (TEXT — a 32-char hex
boot UUID), and it is written INSERT-OR-IGNORE once per boot. Three hard walls:

1. **Pi delta cursor forbids TEXT PKs.** `sync_log.PK_COLUMN`'s contract is
   explicit: *"Every value MUST be an INTEGER PK column (the delta cursor is
   monotonic, which only holds for AUTOINCREMENT rowids)."* `getDeltaRows` does
   `WHERE {pk} > ?` with an integer high-water mark and `int(lastId)`; a TEXT
   `boot_id` (random hex) is not monotonic and cannot be a delta cursor. This is
   the exact class of bug US-194 fixed (the `int('daily')` explosion for
   `profiles`); TEXT-PK tables are deliberately routed to `SNAPSHOT_TABLES`,
   which return `SKIPPED` from `pushDelta` because **the snapshot/upsert sync
   path does not exist yet** ("A future story (post-US-194) will add an upsert
   path").

2. **Server ingest requires an integer `source_id`.** `runSyncUpsert`
   (`src/server/api/sync.py`) maps Pi `id` → `source_id` and appends it to
   `sourceIds` unconditionally (KeyError without an `id`); the upsert conflict
   key is `(source_device, source_id)`. `startup_log` has no integer id — it
   would need a **dedicated natural-key `(source_device, boot_id)` upsert
   resolver** (like the special-cased `_syncDtcFreezeFrameRows` cross-tier path),
   not the generic registry path.

3. **Therefore startup_log needs a genuinely different mechanism on BOTH tiers**
   — a bespoke Pi push (full-snapshot or a `recorded_at` TEXT cursor) + a
   dedicated server resolver + a natural-key unique constraint. That is a design
   decision (which cursor/idempotency model) and roughly doubles a size-M story.
   It is above Ralph's scope-fence and warrants an SSOT/architecture gate.

## Impact

- **US-412 stays `passes: false`** because it is atomic and the startup_log
  acceptance criteria (rows #1/#2 for startup_log) are unmet.
- **power_log is fully DONE and committed** (Pi registry + server model +
  v0013 migration + tests), so the story's primary value is delivered and
  de-risked — only the startup_log half is blocked.
- Does **NOT** block US-413 / US-414 / US-415 (all independent). Single-agent:
  ralph.sh continues to US-413.

## Attempted Solutions

- Confirmed power_log fits the delta path and shipped it (13 server tests + Pi
  delta coverage, all green).
- Traced startup_log through the whole pipeline (Pi `getDeltaRows` → client
  `_renamePkToId`/`_postBatchWithRetry` → server `runSyncUpsert`/`_upsertBatch`)
  — it cannot flow the generic path without either (a) a base-module change to
  the shared delta query (blast radius across all 11 delta tables — rejected on
  risk) or (b) a whole new snapshot/natural-key mechanism.

## Proposed Resolution

**Recommend: split US-412.** Mark the power_log half complete; carve startup_log
into its own story (e.g. US-4xx "startup_log Pi→server via natural-key upsert")
so it gets proper sizing + a design gate. When PM/Atlas pick the mechanism,
Ralph builds it cleanly. Options for that story to choose from:

- **A. Full-snapshot upsert (recommended, simplest & correct).** Pi pushes ALL
  `startup_log` rows each sync (volume is tiny — one row per boot); server
  upserts on `(source_device, boot_id)`. Idempotent + catch-up for free; no
  cursor needed. Requires: a Pi snapshot-push path (or generalize the dormant
  `SNAPSHOT_TABLES` handling) + a dedicated server resolver + a
  `UNIQUE(source_device, boot_id)` constraint (no `source_id`).
- **B. `recorded_at` TEXT cursor.** Delta by lexicographic `recorded_at`
  (fixed-width ISO-8601 is monotonic), server upsert on `(source_device,
  boot_id)`. More moving parts than A for no real gain at this volume.
- **C. Give startup_log an integer surrogate on the Pi.** Table rebuild
  (SQLite can't add an AUTOINCREMENT PK via ALTER) — highest risk, rejected.

## Resolution

[Fill in when resolved.]
