---
name: PM Inline Patterns Graduate to Committed Tools
description: When PM writes the same `python -c "..."` inline pattern twice for sprint/backlog/counter operations, capture it as a committed script in `offices/pm/scripts/` rather than rewriting it next session.
type: feedback
originSessionId: 8097548c-53b0-4bc3-b07b-fa89f7118840
---
CIO directed (Session 24, 2026-04-19) when noticing inline `python -c "..."` invocations during Sprint 14 setup: "make sure that you save your code so that it becomes a reusable, repeatable tool that you can use in the future and have a repeatable utility that you can use over and over again."

**Why:** PM operations recur every session (status snapshot, backlog mutations, counter bumps). Writing them inline each time wastes context, introduces drift, and isn't reviewable. Committed tools become institutional memory the next session inherits.

**How to apply:**
- Live tools at `offices/pm/scripts/` with stdlib-only Python (Windows git-bash + Linux compatible).
- Each tool has CLI flags + `--help` + ideally `--dry-run`.
- README at `offices/pm/scripts/README.md` documents usage examples.
- The rule: if I write the same pattern twice as `python -c "..."`, it graduates to a committed script.
- Existing tools as of Session 24:
  - `pm_status.py` — session-start snapshot (sprint stories + backlog by status + counter state)
  - `backlog_set.py` — CLI for backlog.json mutations (flip status, add phase, record completion, bump lastUpdated)
- One-shot helpers (e.g. `_add_us202.py`) are fine if scoped to a single sprint operation, but should be deleted after use rather than kept around.
