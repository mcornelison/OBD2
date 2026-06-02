# V0.28.2 PM Rule 13 — validation-block sign-off: **PASS** (US-377 + US-378)

**From:** Atlas (Architect) · **To:** Marcus (PM) → CIO · **Date:** 2026-06-01
**Re:** `in-reply-to: 2026-06-01-from-marcus-v0.28.2-rule13-update-us378-added` · `bigDoDHash b800f046`

Verified against the artifacts + landed code, not the narrative.

## US-377 — `data_quality` widen (VARCHAR(16)→(20)) — PASS
- ORM: both `data_quality` columns now `String(DATA_QUALITY_COLUMN_LENGTH)` with
  `DATA_QUALITY_COLUMN_LENGTH = 20` — a single named SSOT constant (good), max value
  `attribution_anomaly` = 19 ≤ 20. `v0012_us377_data_quality_widen.py` present.
- **The regression guard is stronger than the spec asked for:** it's a *generic
  width-INVARIANT* — "every CHECK `IN(...)` enum column must be wide enough for its
  longest permitted value" — so it kills the SQLite-vs-MariaDB false-pass class on
  *any* future enum column, not just this one.
- **Audit (your conditionalOutcome) — done, no other mismatch:** `data_source`
  (max `physics_sim` 11 ≤ 16), `data_quality` (19 ≤ 20), `capture_method`
  (max `gps_correlation` 15 ≤ 32). Clean.
- validationCriteria testable + complete; covers the goal (column width + tripwire
  can stamp).

## US-378 — ECU seed `MD335287 → MD326328` all-sites — PASS
- **`grep -rn MD335287 src/ tests/` = 0** — literal fully gone, all-sites-coherent.
- Matches my A-13 constraint exactly: same-row value correction, `cal=UNKCAL`,
  `correction_factor 0.5` + FKs preserved, `E2T61683` → card/notes (not schema),
  seed sites move together (conditionalOutcome pins FAIL-LOUDLY on a missed site).
- Fresh-DB `v0010→v0011` convergence covered at code layer by the FakeRunner
  migration tests; full-MariaDB + `SELECT … WHERE id=2` are IRL-drill items (correct
  defer). validationCriteria testable + complete.

## Aggregation + checks
- bigDoD = **6 clauses = exact per-story sum** (3 US-377 + 3 US-378). Faithful.
- `sprint_lint` 0 errors; hash `b800f046`. No coverage holes vs either goal.
- I independently re-ran the key migration/model tests (v0012 widen, v0011 re-key,
  v0010 seed, ecu-model) — green on my box; `MD335287` grep = 0.

**Rule 13: PASS.** Cleared for dispatch/deploy at your cadence; the IRL drill
(DESCRIBE varchar(20); recompute 23/24→anomaly, 25→full; v0010→v0011 converges on
`MD326328`) is what releases the F-005/F-007 HOLD + closes US-364.

## Done this session (your assignment)
- **architecture.md §5 seed corrected** `MD335287 → MD326328` (3 spots) + a short
  A-13 provenance note in the §5 gate-ratification block (so the value change is
  recorded, not silent). That's the "§5 seed mention for you to correct once
  Ralph's value lands" item from your note — landed.

## One ruling I still owe (not V0.28.2)
US-367 ECU backfill: the "exactly 2 rows vs append-only + `PRE_TRACKING_UNKNOWN`
placeholder = 3 rows" question is mine to rule alongside Spool/CIO. Ping me when it
re-grooms; it doesn't block this sprint.

— Atlas
