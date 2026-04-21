# TD-028: ralph.sh ↔ prompt.md promise-tag contract drift

| Field        | Value                                                 |
|--------------|-------------------------------------------------------|
| Severity     | Low (cosmetic / behavioral-gap; no current production impact) |
| Status       | **Closed 2026-04-20 via US-207 (Sprint 15)** — Option B (prompt.md expanded to canonical) |
| Filed By     | Ralph (Rex), Session 71, 2026-04-20                   |
| Surfaced In  | Tier 1 ralph/ knowledge read — CIO-directed audit of `ralph.sh` + `prompt.md` after live observation of `"0 / 12" + "PRD COMPLETE"` contradiction (that primary bug was a separate typo, fixed inline Session 71) |
| Blocking     | Nothing today. Could bite when a story emits one of the undocumented tags — the autonomous loop will respond but the story author couldn't have known which tags are live. |
| Closed       | 2026-04-20 (US-207)                                   |

## Closed 2026-04-20 — prompt.md promoted to canonical

**Chosen path:** Option B from the original TD — keep every tag ralph.sh branches on, document them in prompt.md so story authors have complete visibility, and add a contract-sync guard test.

**Reasoning for B over A:** PM's Sprint 15 go-signal specifically asked for a 5-line Refusal Rules summary in prompt.md — promoting prompt.md as the canonical reference for Ralph's workflow was the shipping decision. Pruning ralph.sh branches would have reduced flexibility and was not the preferred direction.

**What changed:**

1. **`offices/ralph/prompt.md` §Stop Condition** rewritten as a table documenting all 6 emittable tags + the no-tag case, with explicit exit codes and "ralph.sh behavior" columns. Key distinction highlighted: `SPRINT_BLOCKED` exits 1 (PM-attention signal), all other stop tags exit 0.
2. **`offices/ralph/prompt.md`** gained a new **5 Refusal Rules (quick reference)** section after the Before-You-Start block, with one-line summaries of each rule and a pointer back to `ralph/knowledge/sprint-contract.md` for the full text. This closes the "did I load sprint-contract.md this iteration?" doubt that motivated PM's sign-off.
3. **`offices/ralph/ralph.sh`** gained a 5-line header comment (no behavior change) naming `prompt.md §Stop Condition` as the authoritative tag list + exit-code distinctions.
4. **`offices/ralph/knowledge/session-learnings.md`** gained the CIO drift-observation rule (PM Q2 response): "If Ralph observes drift AND has permission to fix it within the current story's `scope.filesToTouch` → fix inline, no TD required. Otherwise → file a TD immediately."
5. **`tests/lint/test_ralph_promise_tag_contract.py`** (new, 2 tests, green) — extracts `<promise>TAG</promise>` tokens from both files via regex and asserts set-equality. If either file drifts, the test fails with a pointer to the canonical location. Placeholder "TAG" filtered via `_PLACEHOLDERS` so docs/examples don't false-positive.

**Verification:**
- `pytest tests/lint/test_ralph_promise_tag_contract.py -v` → 2/2 green
- `grep -Eo '<promise>[A-Z_]+</promise>' offices/ralph/prompt.md` set == `grep -Eo '<promise>[A-Z_]+</promise>' offices/ralph/ralph.sh` set (minus the placeholder `TAG` in both docs).

No behavior change in ralph.sh; no test regressions; no new runtime dependencies.

## Original analysis (preserved for reference)

## Problem

`offices/ralph/ralph.sh` branches on **seven** promise tags in the iteration-complete handler (lines ~94-131). `offices/ralph/prompt.md` §Stop Condition documents **three**. The two sets diverge.

### ralph.sh handles (live, in the script)
1. `<promise>COMPLETE</promise>` — "PRD COMPLETE - All stories passed!"
2. `<promise>HUMAN_INTERVENTION_REQUIRED</promise>` — "HUMAN INTERVENTION REQUIRED - Check pm/blockers/"
3. `<promise>SPRINT_IN_PROGRESS</promise>` — "Agent done - other agents still working"
4. `<promise>ALL_BLOCKED</promise>` — "No work available - tasks blocked by other agents"
5. `<promise>PARTIAL_BLOCKED</promise>` — "Some stories blocked, but work remains" *(continues loop)*
6. `<promise>SPRINT_BLOCKED</promise>` — "SPRINT BLOCKED - All remaining tasks are blocked/unresolvable"
7. (implicit: no promise tag = exit normally, ralph.sh starts next iteration)

### prompt.md §Stop Condition documents
1. `<promise>COMPLETE</promise>` — "all stories have passes: true"
2. `<promise>SPRINT_BLOCKED</promise>` — "a blocker prevents ALL remaining stories"
3. `<promise>PARTIAL_BLOCKED</promise>` — "SOME stories are blocked but others are available"
4. (implicit: no promise tag = exit normally)

### Drift

Four tags in ralph.sh are **undocumented in prompt.md**:
- `HUMAN_INTERVENTION_REQUIRED` (appears in root `CLAUDE.md`'s Ralph section as a legitimate promise tag but not in prompt.md; ralph.sh treats it as a valid exit)
- `SPRINT_IN_PROGRESS` (no documentation anywhere in `offices/ralph/` that I found)
- `ALL_BLOCKED` (no documentation anywhere)
- `SPRINT_BLOCKED` returns exit 1 in ralph.sh but prompt.md doesn't specify an exit code distinction

## Impact

- **Today**: none observable. Ralph autonomous runs don't emit the undocumented tags today (the stories that shipped Sprint 14 used only documented ones: `COMPLETE` implicit, sometimes `PARTIAL_BLOCKED`).
- **Risk surface**: a future story could reasonably emit a tag named in ralph.sh (e.g., `HUMAN_INTERVENTION_REQUIRED` — which the root `CLAUDE.md` suggests is valid) and ralph.sh would handle it correctly, but the story author (and anyone reading prompt.md) can't know that tag is available. Conversely, if ralph.sh branches are legacy scaffolds from a different project, Ralph emitting them wastes a branch.

## Proposed fix (two options)

**Option A — prompt.md is canonical; prune ralph.sh**

Delete the three undocumented branches from ralph.sh:
- `HUMAN_INTERVENTION_REQUIRED`, `SPRINT_IN_PROGRESS`, `ALL_BLOCKED`

Keep only the tags prompt.md lists. Fewest lines of change, smallest attack surface.

**Option B — ralph.sh is canonical; expand prompt.md**

Add a §Stop Condition table to prompt.md that lists all seven tags (including "no tag") with semantics and exit codes:

| Tag | Meaning | ralph.sh behavior |
|-----|---------|-------------------|
| `COMPLETE` | All stories `passes: true` | Stop iterations, exit 0 |
| `HUMAN_INTERVENTION_REQUIRED` | Blocker needs CIO judgment | Stop, exit 0, log pointer to pm/blockers/ |
| etc. | | |

Most information-preserving; costs more documentation upkeep.

**My lean**: Option A. The undocumented branches look like legacy scaffolding from a prior project (ralph.sh was lifted into this repo from the adMonitor codebase per agent.md's modification history). If you don't see a Ralph story needing these exits, delete them. Cleanup + consistency win.

## Acceptance for fix

If Option A:
- `ralph.sh` has exactly the branches prompt.md §Stop Condition documents, no more.
- `grep -E '<promise>' ralph.sh` and `grep -E '<promise>' prompt.md` enumerate the same tag names.
- A test (new) runs ralph.sh in a dry-run harness and asserts no dead-branch for tags prompt.md omits.

If Option B:
- prompt.md §Stop Condition has a table listing every tag ralph.sh handles.
- Each listed tag has a sample `<promise>TAG</promise>` emission pattern and the ralph.sh behavior.

## Related

- Session 71 ralph.sh `passes`/`passed` typo fix — sibling drift issue (different class, already closed inline).
- Root `CLAUDE.md` §"How Ralph Works" mentions `HUMAN_INTERVENTION_REQUIRED` — update or remove depending on option chosen.
- CIO feedback pattern rule (Q1 2026-04-20): TDs are how Ralph surfaces drift outside a sprint. Marcus wraps this into a story when sprint room allows.
