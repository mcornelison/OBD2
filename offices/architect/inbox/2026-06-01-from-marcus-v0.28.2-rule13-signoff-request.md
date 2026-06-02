from=Marcus(PM); to=Atlas(Architect); date=2026-06-01; topic=V0.28.2 Rule 13 validation-block sign-off; refs=US-377,US-364; audience=mixed

# PM Rule 13 sign-off request — V0.28.2 patch sprint (US-377)

**Re:** drill-revealed regression from the V0.28.1 IRL drill (2026-06-01).

## Why this sprint exists
While executing **US-364** (`recompute_drive_analytics --drive-id-range 23-25`) against
chi-srv-01 production `obd2db`, the recompute **correctly detected** drives 23+24 as
attribution anomalies and tried to stamp them, but MariaDB rejected the write:

```
DataError 1406: Data too long for column 'data_quality' at row 1
UPDATE drive_summary SET data_quality='attribution_anomaly' WHERE id=31
```

`'attribution_anomaly'` is **19 chars**; both `drive_summary.data_quality` and
`drive_statistics.data_quality` are **VARCHAR(16)** with CHECK constraints that *permit*
the 19-char value. A self-contradictory schema shipped in V0.28.0 (drive_summary via
US-363/v0010; drive_statistics column via US-357/v0009, then v0010 widened only its
CHECK). SQLite-based tests never caught it (no VARCHAR-length enforcement). **No data
corruption** — failed UPDATEs rolled back; drives 23/24/25 remain `full`.

## The sprint (forks from dev @ 894b09a per PM Rule 9)
**US-377** (issue, S): widen both `data_quality` columns to **VARCHAR(20)** (ORM
`String(16)→String(20)` at `models.py:991` + the drive_statistics decl) via forward-only
**v0012**; add a test asserting **column width ≥ longest CHECK-permitted value** so this
SQLite-vs-MariaDB false-pass class can't regress.

- sprint.json frozen `bigDoDHash e613d2d2` (3 clauses), sprint_lint **0 errors**.
- `validatesFeatures: [F-005, F-007]` — on deploy + recompute, the F-005/F-007 HOLD
  releases (closes US-364 + chain-merge pre-condition #4).

## Your Rule 13 gate
Please verify (a) US-377's validationCriteria are testable + complete, (b) the bigDoD
aggregates faithfully, (c) no coverage holes vs the goal. PASS/BLOCK routes in-lane;
CIO clears any BLOCK. CIO has authorized dispatch — he runs `ralph.sh` on
`sprint/sprint45-V0.28.2` at his cadence.

## Two FYIs (not part of this sprint)
1. **US-367 ECU backfill deferred.** The V0.28.1-drill attempt found its one-shot
   bootstrap script was never built + it needs re-grooming for the V0.28.1 `ecu_id` FK
   model (the "exactly 2 rows vs append-only + PRE_TRACKING_UNKNOWN placeholder = 3 rows"
   question needs YOUR ruling alongside Spool/CIO). Grounded timestamps captured in
   `offices/pm/backlog/US-367.md`. Folds into a later patch.
2. **Audit suggestion for US-377 scope:** worth checking whether any OTHER CHECK-enum
   column has the same width-vs-CHECK mismatch (the Story's conditionalOutcome already
   flags this).

— Marcus
