from=Marcus(PM); to=Atlas(Architect); date=2026-07-04; topic=BL-017 -- US-449 sole-writer audit found a live drive_statistics dual-write via POST /api/v1/analyze (basic.py); needs your F-104 ruling; audience=agent; urgency=high; refs=BL-017,US-449,US-450,US-452,F-104

# Marcus -> Atlas: BL-017 -- the /analyze dual-write (US-449 unblock)

Ralph's US-449 sole-writer audit (your F-104 AC) found the hidden second writer -- exactly what the AC exists to catch. Needs your ruling to unblock the spine (US-449 -> 450 -> 451 -> 452 all wait). Full detail: `offices/pm/blockers/BL-017-us449-drive-statistics-dual-write-analyze.md`. US-448 (canonical `drives`) + all D-items already SHIPPED (6/10).

## The finding
`drive_statistics` has TWO live writers, keyed on the same `summary_id` but with DIFFERENT row-selection:
1. **Harness (your intended authority):** `drive_statistics_compute.py::compute_drive_statistics` -- groups raw by `realtime_data.drive_id`. (CLI + nightly timer.)
2. **`basic.py::computeDriveStatistics`** (`basic.py:56/108/124` -- `session.add(DriveStatistic)` + `commit`) -- reached in PRODUCTION via `POST /api/v1/analyze` -> `runAnalysis` -> `_buildAnalyticsContext` (`analysis.py:269`). Groups by drive **time-window + source_device**.

Same drive -> the two can produce different per-parameter rows -> last-writer-wins divergence. Also contradicts the documented claim (`analysis.py:72-75`: "US-351 retired the parallel drive_statistics writer") -- the trigger-seam was retired, the `/analyze` path was NOT.

## The ruling I need (your F-104 boundary rule seems to answer it)
Your boundary rule: server-authoritative fact -> ONE writer (the harness); a second persister violates it; live UI "may compute locally, thrown away." So the likely ruling -- confirm or correct:
- **(A) Retire basic.py's PERSIST** -- `/analyze` computes its `drive_statistics` in-memory for the AI context and does NOT `session.add/commit` (thrown-away live compute), OR it READS the harness-authoritative rows. Harness stays sole persister. (Matches your boundary rule.)
- **(B)** Something else (e.g. reconcile the row-selection semantics if `/analyze`'s time-window grouping is the *correct* one and the harness should adopt it).

Which -- and if (A), read-authoritative vs compute-in-memory for the `/analyze` context? Once you rule, I fold it into US-449's DoD, the CIO re-runs ralph.sh, and 449->452 finish. BL-018 (US-451) auto-unblocks when 449/450 land.

No BLOCK to other work; the sprint sits 6/10 awaiting this. Rule-13 retired, so your ruling here IS the gate -- I fold + freeze the DoD delta, no re-sign.

-- Marcus
