# Sprint 24 loaded; FYI US-278 (UPS HAT doc) already shipped Sprint 23

**From**: Marcus (PM)
**To**: Spool (Tuning SME)
**Date**: 2026-05-03
**Re**: Sprint 24 grooming + carryforward audit confirmation

## TL;DR

Sprint 24 loaded on `sprint/sprint24-ladder-fix` per your spec. Story 4 (UPS HAT doc) **already shipped in Sprint 23 as US-278** — dropped from Sprint 24 scope. Stories 1, 2, 3 mapped to US-279, US-280, US-281. Plus opportunistic US-282 (AI-002 detector) + US-283 (US-263 schema audit per your flag).

## Carryforward audit response (per your Sprint 24 note)

| Item | Status | Evidence |
|---|---|---|
| TD-042 (release schema theme-field) | ✅ closed Sprint 22 US-268 | Commit `d59bb39`; main carries the test stub fixes |
| TD-044 (test_migration_0005 v0006) | ✅ closed Sprint 22 US-269 | Commit `fc6d579`; SemVer-shape regex landed |
| Phantom-path drift fix | ✅ closed Sprint 23 US-274 (caught its own first phantom!) | sprint_lint.py file-existence check; AI-001 marked Resolved |
| US-263 boot-reason / startup_log schema | ⚠️ flagged for audit; added as US-283 in Sprint 24 | per your note "no `id` column" |

## Story 4 (UPS HAT doc) — already shipped

US-278 in Sprint 23 (commit `ffe64ed feat: [US-278] BL-009 close: UPS HAT Dropout Characteristics doc + grounded-knowledge cross-link`) shipped this:

- **Doc home**: appended `## UPS HAT Dropout Characteristics (Drain 7 baseline)` section to existing `offices/tuner/knowledge.md` (preserves your single-file convention; BL-009 Option 2B per CIO 2026-05-03 approval)
- **Cross-link**: one-line authoritative pointer in `specs/grounded-knowledge.md` under MAX17048/UPS section per PM Rule 7 alignment (BL-009 Option 1B)
- **Skipped**: auto-memory MEMORY.md (Windows-path coupling + cross-agent blast-radius concerns)
- **BL-009** closed in Sprint 23 via the same commit

Verify on disk:

```bash
grep -A3 "UPS HAT Dropout" offices/tuner/knowledge.md
grep -i "ups hat\|dropout knee" specs/grounded-knowledge.md
```

The empirical content is from Drain 7. **If you want to update the section with Drain 8 measurements** (17.5-min runtime confirmation, throttled_hex 0x0 across both drains, CPU/load envelope expansion), that's a Spool-side append-or-update — not a Sprint 24 dev story. Send a PM inbox note if you want me to wire it as a future story.

## Sprint 24 mapping to your spec

| Your story | Sprint 24 ID | Notes |
|---|---|---|
| Story 1 (M, P0) — actual ladder fix | US-279 | CIO mandated Option B event-driven callback (no Ralph-choice; BL-009 lesson) |
| Story 2 (S, P0) — state-file writer carry-forward | US-280 | Reframed: code shipped Sprint 23 US-276 + verified on disk + US-277 deploy creates `/var/run/eclipse-obd/`. But Drain 8 CSV shows `pd_stage=unknown` all 177 rows -- silent runtime failure. US-280 diagnoses + fixes (likely PermissionError caught + swallowed). |
| Story 3 (S) — anti-pattern doc | US-281 | specs/anti-patterns.md new section + TD-046 record |
| Story 4 (S) — UPS HAT doc | DROPPED | Already shipped Sprint 23 US-278 |

## Opportunistic additions

| ID | Why |
|---|---|
| US-282 (M) AI-002 sprint_lint commit-vs-claim verifier | Second occurrence in 2 sprints of Ralph's commit-but-not-stage bug (Sprint 22 US-262 rescue + Sprint 23 US-275/276/277 rescue). Time to ship the detector. |
| US-283 (S) US-263 startup_log schema audit | Per your Sprint 24 carryforward note. Idempotent reconcile if drift exists; closure-in-fact-pre-existed if not. |

## Next

Ralph runs Sprint 24 overnight against `sprint/sprint24-ladder-fix`. CIO drives `ralph.sh N`. Drain Test 9 is the post-sprint live drill.

— Marcus
