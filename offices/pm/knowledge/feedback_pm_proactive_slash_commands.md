---
name: PM proactively suggests slash commands for repeated multi-step rituals
description: When PM (Marcus) catches himself running the same PM-office multi-step ritual 3+ times, he MUST proactively suggest codifying it as a slash command before running it again. PM-office scope ONLY -- do NOT propose codifying Ralph-office or other-agent rituals.
type: feedback
originSessionId: 3d385438-f986-4135-8838-82a0349c2f25
---
CIO 2026-05-05 standing rule: "as the Senior Project Manager, you are to be well organized. if you see yourself doing the same thing like the sprint closeout, you are to suggest to me that we save time and create a command."

**Scope**: PM office (`offices/pm/`) and PM-driven workflows ONLY. Do NOT propose codifying rituals in `offices/ralph/`, `offices/tuner/`, or other agent folders -- those are out of PM's lane; their owners decide their own automations.

**Threshold**: 3 occurrences before suggesting (not 2). CIO 2026-05-05: "no need to be aggressive, we can resolve things going forward organically." Wait for the pattern to land 3 times before raising the suggestion.

**Why**: Sprint-close ritual was executed manually 5 times (Sprints 14, 21, 22, 23, 24, V0.24.1 hotfix) before being skill-ified. The Session 26 next-actions list flagged the missing skill and it carried for 4 more sprint-closes. Each manual run cost ~10-15 min + had real risk of missed steps (the Sprint 22 hidden-bug pattern: server ran V0.21.0 in memory while V0.22.0 code on disk because deploy-server.sh halted at sudo without restart-service step ever firing — caught post-merge by accident). The skill would have prevented it.

**How to apply** when grooming, executing rituals, or at session-end review:

- After running ANY multi-step ritual that took 2+ tool calls + reused the same shape across 2+ prior sessions, pause and ask: "should this be a slash command?"
- Don't wait for CIO to notice the pattern. Surface it the moment you spot the repetition.
- Cite the past instances + the time-saved + the risk-avoided when proposing.
- If CIO approves, build the command in `.claude/commands/<name>.md` following the existing pattern (frontmatter + phased structure + stop conditions + "why this exists" + "related" sections).
- Reference the new command in `projectManager.md` next-actions or in the relevant `feedback_*.md` memory so future sessions discover it.

**Examples of what counts**:
- Sprint-close (codified 2026-05-05 as `/sprint-close-pm`)
- Backlog hygiene closure-in-fact audits (Sprint 23 US-273 + Sprint 25 Bucket A both used the same pattern; if it happens a 3rd time, codify)
- Mid-sprint contract amendments (BL-XXX unblock + scope.filesToTouch patch + status bump + lint + commit + push) — done 2-3 times, near skill threshold
- Rescue-commit pattern when Ralph's commit-but-not-stage bug recurs (096dade Sprint 22 + 6d8af99 Sprint 23 + Sprint 24 US-280 caught by US-282) — US-282 lint catches it now, but the rescue itself is a candidate

**Anti-patterns to avoid**:
- Running the same 5+ tool-call sequence "just one more time" before suggesting the command
- Building a command that's so customized to one sprint's specifics that it doesn't generalize — keep the skill flexible (parameterize sprint name, branch name, etc.)
- Skipping the "stop conditions" section — every multi-step ritual needs explicit halt criteria

**When NOT to suggest a slash command**:
- One-off operations (Spool's BL-009 unblock; the V0.24.1 hotfix were truly unique)
- Ritual that's still evolving (let it stabilize across 2-3 instances first)
- Ritual where each instance has substantially different shape (the codification effort exceeds the savings)
