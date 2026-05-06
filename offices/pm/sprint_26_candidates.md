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

### Backlog hygiene closure-in-fact audit (S, P3)
**Goal**: 11 backlog items are closed-in-fact under different IDs but never marked Resolved in records. Mirrors Sprint 23 US-273 pattern. Records-only edit story; no production code changes.

**Files to touch** (all Status field updates only):
- `offices/pm/backlog/B-001.md` — superseded by Sprint 14+ test refactors
- `offices/pm/backlog/B-005.md` — superseded by various sprint commits
- `offices/pm/backlog/B-008.md` — TD-004 covers same scope (verify TD-004 coverage)
- `offices/pm/backlog/B-009.md` — superseded by Sprint 14+ specs work (verify)
- `offices/pm/backlog/B-010.md` — superseded by hostname / chi-eclipse-01 doc updates (verify)
- `offices/pm/backlog/B-014.md` — SUPERSEDED by B-037 (Pi pipeline complete)
- `offices/pm/backlog/B-022.md` — SUPERSEDED by B-036 (Companion service complete)
- `offices/pm/backlog/B-023.md` — SUPERSEDED by US-188 DeathStarWiFi detection (Sprint 13)
- `offices/pm/backlog/B-027.md` — SUPERSEDED by US-149 + US-226 sync (Sprint 18)
- `offices/pm/backlog/B-031.md` — SUPERSEDED by B-036 (Server pipeline complete)
- `offices/pm/backlog/B-038.md` — SHIPPED via `sprint_lint.py` (Sprint 14 onward) + extended Sprint 23 US-274 + Sprint 24 US-282
- `offices/pm/backlog.json` — reconcile each item's `status` field from `pending` -> `complete` (or `groomed` -> `complete` for B-014 / B-022 / B-031)

**Acceptance**:
- Pre-flight audit: per item, verify the cited supersession by reading the closing US- record OR git log of the relevant code path. Document in completionNotes.
- Per Sprint 23 US-273 pattern: any item that does NOT cleanly verify as closed-in-fact stays `pending` with explanation; story still ships (8/11 closes is fine).
- backlog.json reconciliation: status field updated; lastUpdated bumped; updatedBy set to "Marcus (PM, Sprint 26 hygiene close)"
- sprint_lint clean (this is records-only; no source/test changes).

**Stop conditions**:
- If any item's supersession can't be verified (the cited closing US- doesn't actually cover the scope) -- STOP, leave pending + propose a real grooming follow-up
- If the audit finds a 12th+ stale item not on this list -- STOP, document + add to next-sprint hygiene list

## Sprint 26 size summary

| Bucket | Stories | Size points |
|---|---|---|
| B-047 production validation | 4 | 6 (2M + 2S) |
| B-053 sync cadence | 3 | 5 (1M + 2S) |
| Backlog hygiene audit | 1 | 2 (1S; conservative) |
| **Total queued** | **8** | **~13** |

Plus whatever Spool retros from Sprint 25 close + any new TDs surfaced.

## Notes

- **Numbering caveat**: per memory `feedback_pm_sprint_close_version_bump.md`, Sprint 25 → Sprint 26 means a MINOR version bump (V0.24.1 → V0.25.0 at Sprint 25 close, then V0.26.0 at Sprint 26 close).
- **Anti-blocker discipline** to apply at Sprint 26 grooming time:
  - Verify ALL UPDATE paths exist on disk before grooming (US-274 lint will catch but pre-flight is faster)
  - Mandate architectural choices upfront (BL-009 lesson)
  - Preserve `--check-feedback` verifier for sprint-close (US-282)
  - Runtime-validation gate on every fix story
