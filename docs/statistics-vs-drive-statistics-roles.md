# `statistics` vs `drive_statistics` — authoritative roles (US-452 / F-104 D-1)

**Decision record.** Sprint 55 / V0.29.9. Owner: F-104 server-analytics authority spine.

## The question (D-1)

The server carries two per-parameter statistics tables. The D-1 concern: do they
hold the *same fact*, written by two independent paths (a **dual-write**)? If so,
they must be reconciled into clear, non-overlapping roles.

## The two tables

| | `drive_statistics` | `statistics` |
|---|---|---|
| **Grain** | per **drive** × parameter | per **profile** × parameter (multi-drive rollup) |
| **Scope key** | `(summary_id, parameter_name)` | `(profile_id, analysis_date, parameter_name)`; `drive_id` nullable |
| **Columns** | min/max/avg/std_dev/outliers/sample_count/**data_quality** | min/max/avg/**mode**/**std_1**/**std_2**/outliers/sample_count |
| **Computed by** | **server harness** (`drive_statistics_compute.compute_drive_statistics`) from raw `realtime_data` | **Pi** `StatisticsEngine` (`src/pi/analysis/`) |
| **Reaches the server via** | server-side derivation (never synced) | raw Pi→server **sync mirror** (`api.sync._TABLE_REGISTRY['statistics']`) |
| **F-104 status** | compliant (server-authoritative, reproducible from raw) | legacy Pi-transmitted derived table (see debt below) |

## Ruling — which is authoritative for which fact

- **`drive_statistics` is the authoritative granular per-drive per-parameter
  SSOT** (US-450: server-harness-derived, keyed on the canonical `drives.drive_id`).
  It is the single source for "what were the stats of parameter *P* on drive *D*".
- **`statistics` is the source of the distinct per-profile rollup fact** — a
  multi-drive aggregate (with `mode`, `std_1`, `std_2`) that `drive_statistics`
  does **not** hold. It is **not** authoritative for per-drive facts.

The roles are **non-overlapping at the intended grain**: per-drive → `drive_statistics`;
per-profile rollup → `statistics`.

## No independent dual-write

- **Server side:** only `drive_statistics` is *derived* on the server (by the
  harness). `statistics` is written **only** by the generic raw sync mirror,
  which passes the Pi-computed row through verbatim — it is never re-computed
  server-side. No server code constructs a `statistics` rollup row. This is
  grep-guarded by `tests/server/analytics/test_statistics_vs_drive_statistics_no_dual_write.py`
  (a source-scan) and recorded in the owned-table manifest
  (`src/server/analytics/owned_tables.py`: `statistics` → `WRITER_SYNC_MIRROR`,
  not harness-owned).
- **Pi side:** the Pi computes `statistics` (per-profile) but no longer computes
  `drive_statistics` (the Pi-side writer was retired — `detector.py`). So no
  single fact is derived into both tables by any path.

## Residual F-104 debt (flagged, not resolved here)

`statistics` is a **Pi-transmitted derived table**, which is in tension with the
F-104 boundary rule *"no derived state the Pi transmits"* (a per-parameter
aggregate is reproducible from synced raw, so under F-104 the server should own
it). Its historical per-drive-scoped rows (`drive_id` set) also overlap
`drive_statistics`'s fact-space.

Fully resolving this — **retire** the Pi `statistics` compute + sync, or
**re-derive** the profile rollup server-side as a harness rollup — is an
architectural decision (Atlas / sync-scope) beyond US-452's document-and-guard
scope. `drive_statistics` is already the authoritative per-drive path; `statistics`
remains as the profile-rollup mirror until that follow-up lands.

**Re-evaluate trigger:** when the analysis/AI tier (Sprint 56+) needs
profile-level rollups server-authoritative, fold the rollup under the harness
(deriving it from `drive_statistics`) and drop `statistics` from the raw-sync
scope in the same pass.
