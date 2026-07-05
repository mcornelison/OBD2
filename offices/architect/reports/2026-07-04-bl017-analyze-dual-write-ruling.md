# Atlas Ruling — BL-017: the `/analyze` `drive_statistics` dual-write (US-449 unblock)

**Date:** 2026-07-04
**Requested by:** Marcus (PM) — `inbox/2026-07-04-from-marcus-bl017-analyze-drive-statistics-dual-write.md`
**Refs:** BL-017, US-449, US-450, US-452, F-104 · **Blocking:** US-449 sole-writer AC2/VC2 → cascades 450/452
**Gate:** Rule-13 retired → this ruling IS the gate; Marcus folds into US-449 DoD + freezes, no re-sign.

## Verdict

**Option (A). The harness (`drive_statistics_compute.py`) is the SOLE writer of `drive_statistics`. `/analyze` becomes a pure CONSUMER — it does not persist. Reject (B).** The audit did exactly what the F-104 sole-writer AC exists to do. No BLOCK to the ruling; this is a clean unblock.

## Verified in code (not the narrative)

- `basic.py::computeDriveStatistics` **persists**: `delete(DriveStatistic).where(summary_id==driveId)` (`:87-89`) + `session.add(row)` (`:108`) + `session.commit()` (`:124`), grouping raw by **time-window + `source_device`** (`_collectReadings` via `drive_summary.start_time/end_time/device_id`). Confirmed second writer.
- Reached in production: `POST /api/v1/analyze` → `runAnalysis` → `_buildAnalyticsContext` (`analysis.py:269`) and a second call site (`analysis.py:1189`).
- The harness writer groups by `realtime_data.drive_id` — **different row-selection** → same drive, different rows, last-writer-wins. Confirmed divergence.
- The doc claim `analysis.py:72-75` ("US-351 retired the parallel drive_statistics writer") is **false** for this path — the trigger-seam was retired, `/analyze` was not.

## The ruling, precisely

1. **One writer.** `drive_statistics` is a server-authoritative fact → exactly one persister: the harness. Per the F-104 boundary rule, a second persister is a violation regardless of intent.
2. **`/analyze` is a consumer.** `_buildAnalyticsContext` **reads** the harness-written `drive_statistics` rows for the AI context; it must not `add`/`delete`/`commit` them.
3. **Preserve on-demand freshness via the authority, not a parallel writer.** If `/analyze` requests a drive the batch hasn't processed, it triggers the **harness** `compute_drive_statistics` (the single authority) and then reads — NOT `basic.py`'s divergent compute. This keeps today's "fresh on request" behavior with one writer. (Read-authoritative; compute-via-authority-on-miss.)
4. **Retire `basic.py::computeDriveStatistics` as a persister.** Remove its DB writes. Delete it if no caller needs a non-persisted view; if a display path genuinely needs an in-memory-only stat, keep a pure function that returns values and touches no table (thrown-away, per the boundary rule's "live UI may compute locally"). Both `/analyze` call sites switch to the authority.
5. **Fix the false claim** at `analysis.py:72-75` so it matches reality once the path is retired.

## Reject (B), and why the grouping question doesn't keep two writers

The row-selection difference (harness `drive_id` vs `basic.py` time-window+device) is **not** a reason to bless a second writer. Authority is settled by F-104 (the harness). If the time-window semantics were ever judged better, the **single authority adopts them** — you never keep a parallel persister to preserve a grouping. And note the hazard: `basic.py`'s pure time-window+device grouping **merges adjacent/overlapping drives** — the exact A-9 attribution failure. Do **not** fold that grouping into the authority without the server re-segmenter's boundary logic (US-450 re-keys the harness onto the canonical `drives.drive_id` from US-448 — that is where boundary semantics belong).

## Scope flag — this is not only `drive_statistics` (must reach the AC1 manifest)

The same `/analyze` flow also persists **`anomaly_log`** (`detectAnomalies`, `analysis.py:273`) and **`trend_snapshots`** (`computeTrends`, `:280` — "writes a snapshot each call"). By the identical boundary rule, those are the **same violation class**. Do not whack-a-mole `drive_statistics` alone. **US-449's owned-table manifest (AC1) must enumerate every persisted-analytics table with its ONE writer, and `/analyze` must be a consumer of all of them** (harness = sole writer of `drive_statistics`, `anomaly_log`, `trend_snapshots`, `drive_summary`, `statistics`, derived signals). The manifest is the SSOT that makes "sole writer" checkable.

## DoD for the follow-up (fold into US-449; its own story if sized heavy)

- `_buildAnalyticsContext` (+ the `:1189` site) read harness-authoritative `drive_statistics`; on-miss trigger the **harness** compute; no `add`/`delete`/`commit` of analytics from the `/analyze` path.
- `basic.py::computeDriveStatistics` de-persisted (deleted or pure-in-memory, no DB writes).
- `anomaly_log` + `trend_snapshots` writers in the `/analyze` flow resolved the same way (consumer, harness = sole writer) — captured in the AC1 manifest.
- `analysis.py:72-75` comment corrected.
- Test: the sole-writer/VC2 assertion (no dual-write path) now passes for `drive_statistics`, `anomaly_log`, `trend_snapshots`; `/analyze` regression covered (AI context still populated by reading authoritative rows / on-miss compute).
- `ruff` clean; mypy PM-integration.

**Disposition:** US-449 unblocked. Marcus folds this into US-449 DoD (manifest + sole-writer completion) + freezes. BL-018 (US-451) auto-unblocks when 449/450 land.

— Atlas
