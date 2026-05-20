---
name: PM skips Ralph sprint-load handoff inbox notes — CIO tells Ralph directly
description: At sprint load, do not author offices/ralph/inbox/*from-marcus-sprint*-go.md handoff notes. CIO tells Ralph the sprint is loaded directly. The sprint.json contract itself is the spec.
type: feedback
originSessionId: c18b7094-bf20-456a-a0e5-9bcc3073010d
---
At Sprint 19 load (2026-04-29), I authored a multi-page Ralph handoff inbox note (`offices/ralph/inbox/2026-04-29-from-marcus-sprint19-go-runtime-fixes.md`) summarizing theme, story sequencing, action items, etc. CIO said: "next time, no need to send Ralph a note. I can tell him."

**Rule:** at sprint load, the deliverables are:
1. `offices/ralph/sprint.json` — the contract (Sprint Contract v1.0; this IS the spec)
2. `offices/pm/story_counter.json` — nextId bump
3. Any new backlog/inbox source material referenced in story groundingRefs (Spool's note, Ralph's audit, etc.) — already in place
4. Branch created, committed, pushed — PM owns this per `feedback_ralph_no_git_commands.md`

**Do NOT author:** `offices/ralph/inbox/YYYY-MM-DD-from-marcus-sprint*-go-*.md` handoff notes. Ralph reads `sprint.json` directly. CIO will message Ralph that the sprint is loaded.

**Why:** the sprint.json contract already contains intent, scope, groundingRefs, acceptance, verification, invariants, stopConditions per story. A separate handoff note duplicates the contract content and adds zero new information. Saves PM time at sprint-load.

**How to apply:** After running the sprint-build script + sprint_lint, skip writing the handoff note. Stop at: sprint.json + story_counter.json + commit + push. Done.

**Exception:** if there's information that genuinely doesn't fit in sprint.json (cross-sprint context, mid-sprint course corrections, post-mortem for a sister sprint) — write that as a regular targeted inbox note, not a sprint-load handoff template.
