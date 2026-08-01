# Feedback: keep PM memory/knowledge in the PM office, not the shared `~/.claude` memory

**CIO directive 2026-07-31 (Session 56) — sharpens the 2026-05-20 memory-boundary rule.**

## The rule
The `~/.claude/projects/Z--o-OBD2v2/memory/` folder (MEMORY.md + the per-fact `*.md` files) is **shared with every office teammate** — Atlas, Spool, Argus, Ralph, Iris all read it. Therefore it must contain **ONLY generic, cross-team project information**:
- Infrastructure (Pi / Chi-Srv-01 / dongle addresses, hostnames), vehicle facts, hardware.
- Project identity + the agent roster.
- Cross-agent rules everyone shares (A2AL, lane discipline, shared-checkout, branching workflow, SSOT design pattern).

**All PM-specific content lives in `offices/pm/`** — never in the shared memory:
- Session tracking / current-state / sprint pointers → `offices/pm/projectManager.md` (Quick Context + session history).
- PM workflow lessons + feedback + persona → `offices/pm/knowledge/`.
- Backlog / PRDs / decisions → the existing `offices/pm/**` artifacts.

## Why
The shared memory is a common surface; loading PM orchestration detail (sprint numbers, `/resize-split` state, per-session summaries) into it (a) bloats a file every teammate loads, and (b) crosses the lane boundary — that state is PM's, and PM already tracks it in `projectManager.md`. Generic-only keeps the shared file small and truly common.

## How to apply
- Before writing to `~/.claude/.../memory/`, ask: *"Would every teammate need this generic fact?"* If not (it's PM tracking / a PM lesson / orchestration state) → write it to `offices/pm/` instead.
- The `.100` Pi address IS generic infra → correctly belongs in the shared MEMORY.md. A session summary or sprint pointer is PM state → `projectManager.md`.
- When compacting the shared MEMORY.md, prefer MOVING PM-flavored content to `offices/pm/` over just trimming it.
- Some `[[feedback-*]]` files still under `~/.claude/.../memory/` are PM/dev-workflow-specific — audit + migrate them to the right office `knowledge/` folder over time; the shared index should trend toward generic-only.

Related: the shared MEMORY.md "Memory-boundary (CIO 2026-05-20)" line is the original rule; this file is its PM-office application.
