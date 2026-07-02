# TD-059: Ralph headless-loop stalls on the first story running the FULL suite in background

| Field | Value |
|---|---|
| Status | open — needs a `offices/ralph/prompt.md` contract fix (Ralph's office / CIO call) |
| Priority | P1 (recurring; blocks the first story of EVERY fresh ralph.sh run; forces PM manual-landing) |
| Category | process / ralph headless contract |
| Size | S (a prompt.md rule) |
| Created | 2026-07-01 |
| Source | 2 occurrences: US-416 (Sprint 51), US-421 (Sprint 52) |

## Pattern (2x identical)

The **first story of a fresh `ralph.sh` run** — US-416, then US-421 — Ralph builds it completely + correctly, then runs the **full test suite in the background** and says *"I'll wait for the result before committing."* The headless loop is a fresh `claude -p` per iteration with **no cross-iteration monitor**, so the backgrounded result is dropped; the next iteration he "waits" again; `ralph.sh` stops after 2 no-progress iterations. PM verifies the story's **targeted** tests synchronously (fast: 64-66 tests, seconds) and lands it.

**Why the earlier coaching note didn't hold:** the note said "run tests synchronously." But the full suite is slow on the \\chi-nas-01 SMB share, so Ralph's instinct is to background it — "run synchronously" fights that instinct. The real rule must be: **run only the STORY's targeted tests in-loop; the full suite is a PM/integration gate.** (Ralph's own Sprint-49 learnings already say "mypy + full pytest = PM integration, slow SMB" — the prompt just doesn't forbid running it in-loop.)

## Proposed fix (needs CIO OK — `prompt.md` is Ralph's office)

Add to `offices/ralph/prompt.md` a hard rule:
> **In-loop testing:** run ONLY the current story's **targeted** tests, **synchronously** (foreground, block on exit, read the summary line), and **commit within the same iteration**. NEVER run the full suite in-loop and NEVER background a test to "wait for the result" — each iteration is a fresh process with no monitor; the async result is lost and you stall. The full suite + mypy are PM/integration-time gates.

Interim: PM lands the stalled first story manually (verify targeted tests + commit), then the rest of the run flows (coaching holds within a live session — Sprint 51 did US-417..425 fine after US-416 was landed).

## Cross-references

| Item | Relationship |
|---|---|
| TD-057 | Sibling recurring-Ralph-blocker (stale index.lock) |
| US-416 / US-421 | The two occurrences PM had to land |
