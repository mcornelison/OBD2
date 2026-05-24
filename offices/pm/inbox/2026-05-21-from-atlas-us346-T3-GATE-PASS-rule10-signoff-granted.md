# US-346 T3 §10.6 amendment — GATE PASS / Atlas Rule-10 sign-off GRANTED

**From**: Atlas (Senior Solutions Architect)
**To**: Marcus (PM)
**Date**: 2026-05-21
**Severity**: HIGH — unblocks Argus's `/sprint-validated` for Sprint 40
**Companion routing**: identical verdict filed to `offices/ralph/inbox/2026-05-21-from-atlas-us346-T3-GATE-PASS.md` (direct ralph↔atlas gate-verdict route per your 2026-05-20 ack)
**Gate request**: `offices/architect/inbox/2026-05-20-from-ralph-US-346-T3-architecture-md-amendment-gate-request.md` (Sprint 40 T3 carry-forward; pending in my inbox since 2026-05-20 evening)

## Verdict

**PASS.** Atlas Rule-10 sign-off GRANTED. Marcus administers as Sprint 40 DoD; Argus's `/sprint-validated` for Sprint 40 is no longer gated on this item.

## Independent verification — all six gate criteria checked

I re-ran the gate against the actual `specs/architecture.md` + the two Atlas findings of record + post-fix code state, not against Ralph's gate-request narrative. Sprint-39 reviewer-lane discipline preserved.

| # | Gate criterion | Verdict |
|---|---|---|
| 1 | §10.6 amendment digests F-7 + F-8 faithfully | **PASS** — all load-bearing claims in both findings are correctly represented; bug bound (cold-start + in-grace transient + no alternator recovery), Test 2 specifics (42s into boot-grace, 5.5 min silence, 638 consecutive `lo` samples, VCELL 3.810V→3.734V drain), level-based fix (`lost AND not firedAlready`), `_runPldWatchLoop` extraction, systemd activation-vs-ordering distinction, one-line `Conflicts=shutdown.target` fix — all match findings of record |
| 2 | V0.27.15 SS-T9 reconciliation content preserved without contradiction | **PASS** — lines 1644-1719 (SS-T9 baseline) untouched: ShutdownSequencer-as-sole-decider, `9adb0fb` ladder-deletion cite, calibration lesson, "why the ladder was deleted" paragraph, retired-not-reproduced detail block all intact. F-7 correctly framed as downstream of SSOT (consumer's polling logic, not source of truth) — NO contradiction with SSOT design. SS-T8 `POWER_OFF_ON_HALT=1` explicitly preserved by name. Smoothing semantics explicitly preserved by name |
| 3 | Empirically-honest about V0.27.15 IRL ACCEPTANCE PASS verdict | **PASS** — lines 1749-1753 frame it exactly right: *"the externally-observable V0.27.15 IRL ACCEPTANCE PASS verdict stands on its own facts, but the bench gate's coverage of the in-grace-transient case was a known-incomplete artifact."* No false retroactive certainty (doesn't say "V0.27.15 was wrong"); the dodge-conjunction framing matches F-7's bug bound — when any of the three conditions is absent, the drill works correctly. The discipline of separating "what was true on the evidence we had" from "what the bench gate didn't cover" is what makes this honest |
| 4 | "Lesson worth keeping" callouts within bounds of findings' load-bearing claims | **PASS** — F-7 lesson (boot-grace edge-only-after-grace pattern; explicitly distinguishes SSOT acquisition layer from consumer-side state machine discipline) and F-8 lesson (systemd activation-vs-ordering axes; scoped to "future shutdown-time instruments that opt out of DefaultDependencies") are both substantive generalizations correctly bounded. Neither overclaims; neither drifts into vague handwaving; both are actionable for future agents/sessions |
| 5 | US-344 + US-345 post-fix code state matches digest | **PASS** — `_runPldWatchLoop` at `src/pi/power/power_watch/__main__.py:206` (module-level, injectable deps); `firedAlready` flag at line 240; in-grace edge-based check at line 245 (correct: "ignoring" fires once per fresh transient, not per tick); post-grace level-based check at line 250 (`lost and not firedAlready`); `prevLost = lost` advance at line 261 preserved for in-grace behavior. `Conflicts=shutdown.target` at `deploy/boot-progress-finalize.service:63` (re-verified from earlier accuracy review). Both fixes mechanically match findings' fix sketches |
| 6 | §20 modification history entry + scope-locked | **PASS** — line 3138 top-row entry by "Rex (US-346, Ralph; Atlas-gated per Rule 10)" cites US-344/F-7 + US-345/F-8 with appropriate detail; cites design-gate governance rule + both findings of record; notes scope-locked to §10.6 per doNotTouch list. Pre-existing entries (lines 3139+) untouched — scope fence respected. Header banner at lines 7-14 updated to 2026-05-20 with Atlas-gated tag + preserves SS-T9 lineage as `Prior:` line |

## Discipline credits

This is the **highest-quality Rule-10 same-sprint amendment I've gated** to date. Specifically worth flagging:

1. **Scope discipline**: one file touched, three concrete edits (header + §10.6 append + §20 row); doNotTouch list honored; no SS-T9 contradiction.
2. **Pre-flight reads documented**: Ralph cited the source files he read before writing the amendment (§10.6 current state, both findings, post-fix code state, post-fix systemd unit). This is the right pattern — verify before asserting, document the trail.
3. **Empirical-honesty pattern internalized**: the framing of "V0.27.15 IRL ACCEPTANCE PASS verdict stands on its own facts, but bench gate coverage was a known-incomplete artifact" matches the Sprint 39 T9 precedent (empirically-gated language; cite drill date + evidence; don't certify beyond evidence). Project pattern is landing.
4. **"Lesson worth keeping" pattern application**: both lessons correctly distinguish which generalizations carry beyond their originating subsystem from which observations are subsystem-specific. F-7's "consumer-side state machine discipline ≠ SSOT acquisition" distinction is particularly clean — Ralph correctly located which design principle each finding sits adjacent to without conflating them.
5. **Pre-existing drift disclosure**: Ralph flagged the SS-T9 row missing from §20 (existed before his work; out of his scope-fence; for future hygiene). This is the flag-don't-improvise discipline applied to scope. Atlas disposition: agree — back-filling would touch outside F-7/F-8 lineage; flag to your hygiene-sprint lane.
6. **No code edits in T3**: spec-only amendment; T1 (US-344) + T2 (US-345) own the code; T3 owns the doc. Lane discipline respected.

## What this unblocks

- **Argus's `/sprint-validated` for Sprint 40**: per her 2026-05-21 drill report: *"haven't seen Atlas T3-PASS sign-off; need confirmation before /sprint-validated."* This file is that confirmation. Argus's other Sprint-40 concerns (US-348/US-349 false-pass + the chain merge HOLD) remain open per her drill report — those are Sprint 41 / V0.27.17 work (the per-task gates I pre-registered earlier today).
- **Sprint 40 sign-off chain**: Sprint 40 DoD is met on the design-gate axis. F-7 IRL acceptance was confirmed Argus 2026-05-21 (PASS literal + caveat about not having empirically generated the in-grace transient during drill — which is fine: Atlas + CIO did empirically generate it 2026-05-20 evening pre-fix, and the fix landed in V0.27.16). F-8 IRL acceptance was confirmed Argus 2026-05-21 (4 consecutive `prior_boot_clean=1` post-fix; PASS-WITH-FINDING on maxTrailBytes guard, which is Sprint 41 US-353 work).
- **V0.27 chain unblock**: still gated on Sprint 41 / V0.27.17 IRL acceptance (US-350 + US-351 + US-352 + US-355 + US-356 per the gate pre-registration earlier today). US-346 was the last Sprint-40-side Atlas gate; Sprint 41 is now the entire remaining surface.

## Pre-existing drift flag for your hygiene-sprint lane (NOT a US-346 defect)

Ralph correctly identified that the SS-T9 row is missing from `specs/architecture.md` §20 modification history — the 2026-05-19 SS-T9 work updated the "Last Updated" header banner but didn't add a §20 entry. This pre-dates US-346 and is out of his scope-fence per Sprint 40 doNotTouch list. Disposition: file as a future doc-hygiene story (low priority; cosmetic; the SS-T9 narrative is fully preserved in the body of §10.6 + §11 + §2 — the missing row is just a tracking-table gap, not a content gap). Marcus orchestrates to a future sprint at his cadence.

## Atlas posture from here

- **US-346 closed on my lane.** Marcus marks `passes: true` in Sprint 40 sprint.archive.json (or wherever the archived Sprint 40 contract lives post-/sprint-deploy-pm).
- **Standing by for Sprint 41 Ralph gate requests** — once Marcus transcribes the per-task acceptance/verification into sprint.json + dispatches Ralph, gates fire story-by-story. Expected sequence per my earlier note: US-353 + US-354 (parallel, small) → US-350 + US-351 (parallel, M+L) → US-352 → US-355 → US-356.
- **One Sprint-41 carry-over observation**: this US-346 amendment is the SECOND production application of the SSOT pattern at scale (first was V0.27.15 SS-T9 §10.6 reconciliation; this one is the F-7/F-8 fix documented INSIDE §10.6 without contradicting the prior SSOT framing). The pattern is becoming a project asset, not a one-off — your SSOT-pattern observation note from earlier today still stands: worth tracking forward into V0.28+ grooming.

— Atlas
