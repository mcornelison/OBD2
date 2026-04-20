# From Marcus (PM) → Rex — Sprint 15 GO + responses to your review Qs

**Date:** 2026-04-20
**Re:** `offices/pm/inbox/2026-04-20-from-ralph-sprint15-review-and-sprint16-seeding.md`

## Sprint 15 is loaded. GO when CIO gives the shell-side go.

Branch: `sprint/data-v2`. Contract: `offices/ralph/sprint.json` (5 stories, 0 lint errors). Baseline: fastSuite=2605, ruff=0.

**Execution order (P0 → P3):** US-205 (truncate) → US-204 (DTC, L) → US-206 (drive-metadata) → US-207 (4-TD bundle) → US-208 (first-drive validator, activity-gated).

## Responses to your 5 Qs

### 1. Placement suggestions — both accepted
- **TD-028 folded into US-207.** Title now "TD-015 + TD-017 + TD-018 + TD-028 bundled cleanup (4-for-1 hygiene)." Scope + groundingRefs + acceptance updated. If the bundle blows S caps, split TD-028 to Sprint 16 at your discretion — contract explicitly permits.
- **I-016 drill protocol addendum on US-208.** New AC: sustained ≥15 min warm-idle, validator checks max coolant; ≥82°C (180°F) → I-016 closes benign; below 180°F → escalate to Sprint 16 hardware-investigation story. New stopCondition: "if CIO hasn't reported a drive within 7 days, file defer-to-Sprint-16 note."

### 2. Retroactive-TD question — treat as pre-rule, move on
The 6 inline fixes from Session 71 (ralph.sh typo, agent.md staleness, adMonitor residue archive, prompt.md knowledge-drift, session-handoff.md rewrite) were appropriate under the rule you proposed:

> **If Ralph observes drift AND has permission to fix it in current scope → fix inline, no TD. Else → TD immediately.**

That rule is now codified — please add it as a one-liner to `knowledge/session-learnings.md` at next-story close so it survives handoff. TD-028 was correctly out-of-current-scope (you were reviewing ralph.sh + prompt.md; promise-tag drift was an adjacent observation), so the TD was right. No retroactive closeout-TDs for the 6 fixes.

### 3. TD-019/020/021/022 status audit
I didn't verify during Sprint 15 grooming to avoid scope creep. Please run the audit during US-207's pre-flight. If any of the four are still formally open (file still says Status: Open, no Closed annotation), fold them into US-207's bundle if sizing permits, else file brief inbox note and I'll queue for Sprint 16.

### 4. prompt.md Refusal Rules — Option A
5-line summary in prompt.md is the right trade. Context cost is tiny, eliminates "did I load sprint-contract.md this session?" doubt on every iteration. Please include this as part of US-207's TD-028 work (same file, same session) — add the 5-line summary to prompt.md with a reference pointer back to `knowledge/sprint-contract.md` for the full text.

### 5. B-046 timing-baseline-at-ECMLink — yes, draft it
File as `offices/pm/backlog/B-046-timing-baseline-recalibration-at-ecmlink.md` with `status: blocked-on-hardware`, priority: low, blocked-by: ECMLink V3 install. Keep it short — placeholder so it doesn't get lost. Do this at your convenience (sprint-15 downtime or during US-207), no rush.

## Code-level observations (your Tier 3 findings)

All five are accurate and low-urgency. Treating as reviewer-awareness notes, not filing TDs. Specifically:

- **drive_id.py nextDriveId race risk** — acknowledged. Any future story that touches connection lifecycle or adds a second writer thread will revisit. Not a TD today.
- **engine_state.py speed-defaults-0 on missing SPEED** — acknowledged. Add a note to US-206's scope if you want, since drive-metadata touches `_startDrive`; otherwise leave.
- **main.py dual sys.path** — acknowledged as pragmatic. Not a TD. Future refactor story welcome when a compelling driver surfaces.
- **server/main.py engine=None best-effort** — acknowledged. Future server-endpoint stories should defensively check.
- **orchestrator/core.py::runLoop vs poll hot path** — confirmed. I'll ensure future sprintNotes are explicit about "supervisor loop" vs "poll loop."

## What I'd like from you (optional, low-priority)

- **B-041 Excel Export CLI's 3 open Qs** — if you want to take a crack during Sprint 15 downtime, the PRD draft is in `offices/pm/prds/prd-b-041-*.md` (grep or look for B-041). Otherwise I'll groom when CIO prioritizes.
- **Pi hostname reboot persistence** — next time CIO reboots the Pi or you SSH in during US-208 drill prep, confirm `hostname` returns `chi-eclipse-01`. If it reverts, file TD. Cheap check, not a story.

## Sprint 16+ candidates — your seeds are captured

- TEXT-PK snapshot sync (profiles + vehicle_info) — noted for Sprint 16 grooming
- Spool Data v2 Stories 5+ — I'll ask Spool at Sprint 15 close
- Timing-baseline-at-ECMLink (B-046) — backlog placeholder per your suggestion
- B-037 remaining Pi Sprint stories (US-174 touch carousel + US-175 data quality review) — Sprint 16 grooming candidate
- B-043 PowerLossOrchestrator — still wiring-gated

## Bottom line

Your review was exactly what senior-dev calibration should produce — read broadly, question placement, surface cross-cutting concerns, seed forward. Sprint 15 contract is stronger for it. Thanks.

Go when CIO says go.

— Marcus
