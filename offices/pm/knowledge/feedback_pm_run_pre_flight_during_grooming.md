---
name: PM runs pre-flight audit DURING grooming, not just as story acceptance
description: Sprint 28 had 3 of 6 stories blocked by pre-flight audits contradicting groomed scope (BL-011, BL-012, BL-013). Each story's acceptance criterion #1 was "rg X src/" -- if PM had run that during grooming, the contradiction would have been caught before sprint start. Standing rule: when story acceptance starts with `rg X src/`, PM runs that `rg` during grooming and bakes the findings into scope.filesToTouch.
type: feedback
originSessionId: 3d385438-f986-4135-8838-82a0349c2f25
---
When a sprint story's first acceptance criterion is "Pre-flight audit: rg X src/", the PM grooming process MUST include running that `rg` and verifying the assumed scope matches reality. Three Sprint 28 stories had pre-flight contradictions; that's a 50% grooming defect rate.

**Why**: Sprint 28 / V0.27.2 (2026-05-09):

| Story | Groomed premise | Pre-flight reality | Blocker |
|---|---|---|---|
| US-305 (sync_history v0007 migration) | "v0007 should apply on Pi" | v0007 is a server-side DELETE pruner; never designed for Pi; BL-010 closure had already established sync_log + sync_history are separate tables on separate hosts | **BL-011** |
| US-307 (drain_event close-on-TRIGGER) | "close not wired into _enterStage(TRIGGER); needs adding" | _enterTrigger ALREADY calls _closeDrainEvent BEFORE systemctl poweroff since US-216 ship; existing test GREEN; bug is a different class | **BL-012** |
| US-309 (battery_health_log start_soc cleanup) | "fix is local to battery_health.py per Option 1 (NULL) or Option 2 (populate SOC%)" | Option 1 blocked by NOT NULL constraint; Option 2 requires touching orchestrator + lifecycle + ~10 lock-down test files; cold-start MAX17048 calibration drift hazard | **BL-013** |

All three stories' acceptance criterion #1 was a verbatim `rg` command. Running each `rg` during grooming would have caught the contradictions before sprint started:

- US-305: `rg v0007 src/server/migrations/versions/` shows DELETE-only retention pruner; not a rename.
- US-307: `rg _closeDrainEvent src/pi/power/` shows wiring already in `_enterTrigger`.
- US-309: `rg start_soc src/` shows NOT NULL constraint + 10 lock-down tests + 4 production callers passing VCELL.

Each `rg` takes <30 seconds.

**Rule (apply at every story grooming session)**:

1. **For every story whose acceptance criterion #1 is "Pre-flight audit: rg X src/", PM runs that exact `rg` during grooming.**
2. **If the `rg` results contradict the story's groomed premise**, narrow the scope, repoint at the actual failure site, OR file as a clarifying question before grooming proceeds. DO NOT enter sprint with the wrong premise.
3. **If the `rg` results confirm the premise**, bake the findings into `scope.filesToTouch` so Ralph's pre-flight audit at story-start is verifying-already-known facts, not discovering surprises.
4. **If the `rg` reveals scope expansion needed** (e.g., 10 lock-down tests must update), update the story's `scope.filesToTouch` BEFORE sprint starts -- or split the story into multiple smaller ones with explicit dependencies.

**The deeper rule**: a sprint contract is a hypothesis about how to fix a bug. PM's job at grooming time is to test that hypothesis with cheap verifications (`rg`, `ls`, `grep`, `cat`) before committing Ralph to it. Ralph's job is to refine the hypothesis at pre-flight + report contradictions; PM's job is to NOT NEED Ralph to do that work.

**Three stories blocked in one sprint** is a PM workflow failure, not a Ralph workflow failure. Ralph caught all three via pre-flight discipline; PM grooming should have caught them earlier.

**Cheap pre-flight commands** (under 30 sec each):
- File existence: `ls <path>` or `find . -name "<name>"`
- Symbol grep: `grep -rn "<symbol>" src/`
- Schema constraints: `grep -n "NOT NULL\|NULLABLE" src/server/db/models.py src/pi/obdii/database_schema.py`
- Migration contents: `cat src/server/migrations/versions/v<N>_*.py | head -80`
- Existing test green-state: `pytest <test_path> -v`

**Anti-patterns this rule prevents**:
- BL-011 / BL-012 / BL-013 class: PM grooms wrong premise; Ralph caught at pre-flight; sprint slot at risk
- Sprint scope-blast: story groomed assuming 1-file fix; pre-flight reveals 10-file scope expansion needed
- "Phantom premise" class: PM groomed against a hypothesis; the hypothesis was wrong; the fix was wrong target

**When to skip the verification**:
- Story has NO `rg X src/` in acceptance (no investigation hint -- the story's scope is mechanically obvious like "rename file X to Y")
- The story is a follow-up to a JUST-shipped sprint where the codebase is fresh in PM memory
- Scope is purely documentation / config / non-code

**Cross-references**:
- `feedback_pm_verify_table_names_against_code.md` -- narrower rule about table/symbol names; this rule is the broader scope-verification companion
- `feedback_pm_verify_diagnostic_premises.md` -- companion rule about verifying hypothesized causes from inbox notes
- BL-011 + BL-012 + BL-013 -- canonical examples of grooming-defect failures
- US-274 lint (file-existence check) -- catches phantom paths in `filesToTouch` but NOT phantom premises about WHERE the bug lives
