---
sprint: 45
version: V0.28.2
status: converted
createdAt: 2026-06-01
createdBy: Marcus (PM)
selectedStories: [US-377, US-378]
argusReviewRequired: false
convertedAt: 2026-06-01T22:48:07Z
sprintJsonPath: offices/ralph/sprint.json
forksFrom: dev @ 894b09a
---

# PRD — Sprint 45 (V0.28.2): `data_quality` column-width hotfix (drill-revealed regression)

## Sprint goal

Fix the chain-blocking schema defect surfaced by the **V0.28.1 IRL drill** (2026-06-01): the `data_quality` columns on `drive_summary` and `drive_statistics` are `VARCHAR(16)`, but their own CHECK constraints permit `'attribution_anomaly'` (**19 chars**) — so `recompute_drive_analytics` on the dual-attribution drives 23+24 fails with MariaDB `DataError 1406 ("Data too long")`. Widen both columns to `VARCHAR(20)` via a forward-only `v0012` migration, and add a test that enforces "column width ≥ longest CHECK-permitted value" so this SQLite-vs-MariaDB false-pass class can't regress.

**Drill-revealed regression → patch sprint per PM Rule 9.** This forks from `dev` (carrying deployed-but-unvalidated V0.28.1) and re-merges to `dev` via `/sprint-deploy-pm` with a V0.28.2 patch bump. On deploy, US-364 (recompute drives 23/24/25) re-runs cleanly and releases the F-005/F-007 `regression_manifest` HOLD — the precondition `/chain-validated` needs.

**No data corruption from the drill.** The failed UPDATEs rolled back transactionally; drives 23/24/25 remain `data_quality='full'` with intact rows on production `obd2db`.

## Selected stories (DEV-doable)
| Story | Title | Feature | Epic | Type | Size |
|---|---|---|---|---|---|
| US-377 | `data_quality` column too narrow for `'attribution_anomaly'` (VARCHAR(16)<19) — widen both columns + v0012 + width-enforcing test | F-107 | E-002 | issue | S |
| US-378 | Correct ECU seed `MD335287 → MD326328` across all code sites (A-13, all-sites-coherent) | F-076 | E-002 | issue | S |

**US-378 added 2026-06-01 (A-13).** The CIO corrected the donor ECU's P/N: real value is `MD326328` (mfr `E2T61683`), not `MD335287` (a Session-19 mis-ID of the same box). Atlas already corrected the **prod** `ecu` row directly (`UPDATE ecu …WHERE id=2`); US-378 makes the **code** coherent (the `ecu` seed + v0010 `speed_pid_calibration` seed + v0011 backfill references must move **together** or the migration JOIN FAILs LOUDLY). Same-row value correction — `cal` stays `UNKCAL`, factor `0.5` + all FKs preserved, `E2T61683` → notes/card not schema. **SPEED calibration value is unchanged** (0.5 stays as seed; the GPS empirical method is a future post-drive-27 procedure, no rush). Governance: `MD335287` is in the **frozen** US-376/US-374 `validationCriteria` (Sprint 44, shipped) — a US-370/A-11 freeze-conflict; the value is Spool-signed, handled as a fast-follow data-correctness fix, not a re-scope.

## Out of scope / fast-follow
- **US-364 recompute execution + F-005/F-007 HOLD release** = IRL `validation.bigDefinitionOfDone`, NOT a story (runs against production on deploy; CIO-driven per `feedback-pm-sprint-scope-no-human-irl-tasks`).
- **US-367 ECU backfill** = deferred. The V0.28.1-drill attempt (2026-06-01) found its one-shot bootstrap script was never built and it needs re-grooming for the V0.28.1 `ecu_id` FK model (the "2 vs 3 rows / overwrite-the-placeholder" design question needs an Atlas/Spool/CIO ruling). Grounded timestamps captured in `offices/pm/backlog/US-367.md`. Folds into a later patch once its design is ruled — NOT this sprint (keeps V0.28.2 dispatch-ready immediately).

## IRL validation (rides the V0.28.2 deploy drill, folded into bigDefinitionOfDone)
- `SELECT column_type ... WHERE column_name='data_quality'` on chi-srv-01 post-v0012 → both `varchar(20)`.
- `recompute_drive_analytics --drive-id 23` + `--drive-id 24` → `data_quality='attribution_anomaly'`, no DataError.
- `recompute_drive_analytics --drive-id 25` → `data_quality='full'`.
- Re-run → idempotent zero-diff.
- On pass: release F-005 + F-007 `regression_manifest` HOLD (closes US-364 + chain-merge pre-condition #4).

## Open questions
None. US-377 root cause is fully characterized (ORM `models.py:991` `String(16)`; v0009 set `drive_statistics.data_quality` width, v0010 widened its CHECK without widening the column; v0010 created `drive_summary.data_quality` VARCHAR(16) with the over-wide CHECK from the start).
