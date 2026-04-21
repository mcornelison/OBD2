# From Rex (Ralph) → Marcus — TD-028 + I-016 filed, per CIO Q1/Q2 2026-04-20 rules

**Date:** 2026-04-20
**Priority:** Routine — FYI for Sprint 15 grooming + future prioritization
**Context:** CIO established two new rules today during my Tier 1 knowledge-read session:
- **Q1 rule (B)**: when Ralph spots drift outside a sprint, file a TD immediately rather than log-and-forget or document-only. Marcus wraps into a story at sprint boundaries.
- **Q2 rule**: track the Session 23 coolant-below-op-temp observation as an issue (not a backlog item), routed to PM for future prioritization and analysis.

Both rules applied below.

## Filed

### TD-028 — `offices/pm/tech_debt/TD-028-ralph-sh-promise-tag-contract-drift.md`

**Summary**: `ralph.sh` handles seven `<promise>` tags; `prompt.md` §Stop Condition documents three (plus implicit exit). Four tags in ralph.sh (HUMAN_INTERVENTION_REQUIRED, SPRINT_IN_PROGRESS, ALL_BLOCKED) are undocumented in prompt.md; SPRINT_BLOCKED has an exit-code distinction also missing from prompt.md.

**Severity**: Low. No observable production impact today (stories that shipped Sprint 14 only used documented tags). Risk surface: future story authors don't know which tags are actually live; dead branches in ralph.sh waste maintenance attention.

**My lean**: Option A — prune ralph.sh to match prompt.md. The undocumented branches look like adMonitor-precursor scaffolding. Documented in the TD along with Option B (expand prompt.md) for completeness.

**Sprint impact**: Not urgent. S-size story whenever there's sprint room for documentation hygiene (could naturally fold into US-207's TD bundle if you want a 4-for-1).

### I-016 — `offices/pm/issues/I-016-coolant-below-op-temp-session23.md`

**Summary**: Session 23 captured coolant temp flat at 73-74°C (163-165°F) across 14 samples, ~110 seconds. Full op temp for 4G63 is 88-93°C. `specs/grounded-knowledge.md` line 151 flagged the value with "⚠ Below full op temp (180°F+). If still below 180°F after sustained warmup, investigate thermostat."

**Three hypotheses** documented in the issue body: (1) capture-window artifact (most likely benign — short window, cold ambient, engine may not have warmed); (2) thermostat stuck open (real hardware concern, common 2G DSM failure mode); (3) thermostat missing entirely (less common, documented).

**Impact**: affects Spool's interpretation of Session 23 as "warm idle" baseline. Re-grade may be needed if hypothesis (2) or (3) is confirmed. Also relevant to summer 2026 E85 conversion prep (cooling-system audit is implicit there regardless).

**Suggested action**: US-208 (Sprint 15 first-drive + post-drive analytics, activity-gated on CIO driving) is the natural venue to collect confirmation/refutation data. I recommend adding a **drill-protocol addendum** to US-208 when you finalize the contract: "run engine at idle for at least 10-15 minutes sustained, log coolant trend; if plateaus ≥180°F, issue can close benign; if stays below, promote to hardware concern." No separate story needed today — attaching to US-208's acceptance would overshoot scope.

**Supersedes**: the "2G thermostat diagnostic" item in Spool's pending-research list (`project_spool_pending_research.md`). This issue is concretely tracked, that list entry can be closed.

## Ancillary — open question for your call

**Session-71 drift already fixed inline**: a cluster of drift fixes happened this session BEFORE CIO established the Q1 rule (B) — ralph.sh `passes`/`passed` typo, agent.md same typo, agent.md stale Pi hostname/path, adMonitor residue. Those were all applied live during CIO's direct review of ralph.sh + prompt.md + agent.md.

Retroactively these would have been TDs under rule B. I did NOT file them as TDs after the fact because:
1. The fixes already landed on branch.
2. Filing closed TDs creates noise without adding signal.

If you'd prefer a closeout-TD pattern (TD filed + immediately closed with fix reference, to keep the drift-log complete), say the word and I'll generate retroactive TDs. Otherwise treating these as pre-rule fixes seems right.

— Rex
