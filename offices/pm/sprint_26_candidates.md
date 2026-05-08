# Sprint 26 Candidates (queued for grooming after Sprint 25 close)

Aggregated list of pre-groomed stories ready for Sprint 26 contract. Pulled from B-047 + B-053 PRDs + standalone candidates. No US- IDs assigned until grooming.

## From B-047 (Pi self-update production validation)

| Title | Size | P | Source |
|---|---|---|---|
| Pi self-update production e2e drill | M | 1 | B-047 PRD Sprint 26 candidate |
| Pi auto-rollback drill | M | 1 | B-047 PRD Sprint 26 candidate |
| Cooldown timestamp persistence across reboots | S | 2 | B-047 PRD Sprint 26 candidate (D7) |
| Server release-registry retention enforcement | S | 2 | B-047 PRD Sprint 26 candidate (D4) |

## From B-053 (engine-aware sync-poll cadence)

| Title | Size | P | Source |
|---|---|---|---|
| `SyncCadenceController` state machine (IDLE / ACTIVE / DRAINING) | M | 2 | B-053 Story 1 |
| Wire `SyncCadenceController` into existing sync loop | S | 2 | B-053 Story 2 |
| `sync_log` retention cleanup migration | S | 2 | B-053 Story 3 |

## Standalone candidates

(none currently — backlog hygiene audit was completed by PM directly 2026-05-05; 11 items moved to `offices/pm/backlog/archive/` + backlog.json reconciled in same session. PM-organizational work, not Sprint 26 scope.)

## Sprint 27+ candidates (post Sprint 26)

### B-041 Analytics Excel Export CLI -- GROOMED 2026-05-05
PRD complete at `offices/pm/prds/prd-analytics-excel-export-cli.md`. 4 design decisions resolved (D1 Phase 1 Core 5 default; D2 shared `.env` API key; D3 openpyxl; D4 batched + paginated for big sets). Decomposes into ~4 stories, ~7 size-points (1M server endpoint + pagination + 1S client scaffold + 1M pagination walking + workbook assembly + 1S regression snapshot). Single-sprint fit.

## Sprint 26 size summary

| Bucket | Stories | Size points |
|---|---|---|
| B-047 production validation | 4 | 6 (2M + 2S) |
| B-053 sync cadence | 3 | 5 (1M + 2S) |
| **Total queued for Sprint 26** | **7** | **~11** |

Plus whatever Spool retros from Sprint 25 close + any new TDs surfaced.

## Notes

- **Numbering caveat**: per memory `feedback_pm_sprint_close_version_bump.md`, Sprint 25 → Sprint 26 means a MINOR version bump (V0.24.1 → V0.25.0 at Sprint 25 close, then V0.26.0 at Sprint 26 close).
- **Anti-blocker discipline** to apply at Sprint 26 grooming time:
  - Verify ALL UPDATE paths exist on disk before grooming (US-274 lint will catch but pre-flight is faster)
  - Mandate architectural choices upfront (BL-009 lesson)
  - Preserve `--check-feedback` verifier for sprint-close (US-282)
  - Runtime-validation gate on every fix story
