# /resize_sprint pre-flight validation — recommended checks

**From:** Ralph
**To:** Marcus
**Date:** 2026-04-15
**Re:** Sprint contract design follow-up

## Context

The CIO and I spent a brainstorming session (2026-04-14 → 2026-04-15) designing a tightened sprint contract to make `sprint.json` stories crisp enough for efficient headless execution. The resulting spec is at `docs/superpowers/specs/2026-04-14-sprint-contract-design.md`.

The spec itself is narrow on purpose — it only defines what a well-written story looks like and the reviewer rules for keeping noise out. It deliberately does NOT cover the PM sprint process, directory layout, or implementation mechanics.

**However,** the CIO specifically asked me to send you a separate note with concrete pre-flight validation check suggestions. Having a lightweight validator that runs during `/resize_sprint` — before committing sprint.json — has real value for catching authoring mistakes before Ralph burns a headless iteration.

## Recommended pre-flight checks

These would run inside `/resize_sprint` right before committing `sprint.json`. If any check fails, the skill prints actionable errors to stderr and refuses to commit. You fix and re-run.

| # | Check | Catches |
|---|---|---|
| 1 | JSON schema valid; all required fields present with correct types | authoring typo, missing field |
| 2 | Story IDs unique and match pattern `US-\d+(-[a-z])?` | duplicate or malformed ID |
| 3 | Size caps enforced: declared `size` (S/M/L) vs. actual `filesToTouch.length`, `acceptance.length`, and reviewer-edit diff line count | story that will blow Ralph's context window mid-iteration |
| 4 | No acceptance criterion contains a banned phrase (see spec Banned Phrases section) | people-pleaser weasel words — the #1 failure mode for headless Ralph |
| 5 | Every numeric literal in acceptance criteria has a matching `groundingRefs` entry with valid `source` + `owner` | invented values / magic numbers |
| 6 | `verification` is a non-empty array of executable command strings | vague "tests pass" with no command |
| 7 | Dependency graph is acyclic and references only story IDs present in this sprint | typo or circular dependency |
| 8 | If any story has `size: "L"`, it must have a `pmSignOff` field non-empty | oversized story shipped without PM awareness |

## Why these specifically

- **#4 and #5** are the teeth for the two most important rules in the spec (Rule 1 "Refuse First" and Rule 2 "Ground Every Number"). They catch the exact fabrication patterns that ruin headless runs.
- **#3** prevents you from accidentally authoring an XL-sized story under an S label — the failure that burns Ralph's context window halfway through implementation.
- **#1, #2, #7** catch simple typos that would otherwise halt Ralph mid-iteration with a cryptic error and waste a whole run.

## Implementation is cheap

A Python script, approximately 200 lines, stdlib only (`json`, `re`, `sys`, `pathlib`). Runs in under a second on the full sprint file. Suggested location: `scripts/validate_sprint.py`. Invoked by `/resize_sprint` and again by `ralph.sh` at launch as a double-check (the committed file could have been hand-edited between `/resize_sprint` and ralph.sh launch).

Error output should be actionable — not "invalid JSON" but:

```
[CHECK 4] stories[0]='US-147' acceptance[2] contains banned phrase 'handle edge cases'
          → rewrite as an explicit condition, e.g.,
            'Input 220.0F produces CAUTION_HIGH, not DANGER'
```

## Not in this note (but worth flagging)

The original brainstorming session also covered post-story checks (scope fence, test-count preservation, ruff drift on touched files) and post-sprint checks (no orphaned incomplete stories, final test-count invariant). These belong to `ralph.sh` instrumentation rather than `/resize_sprint`, so they're a separate conversation. Happy to write a second note on those if you want them queued for a future sprint.

## Asks

1. Does the 8-check list feel right, or would you cut / add / reshape any?
2. If you want to move forward, file a backlog item to implement `scripts/validate_sprint.py` + wire it into `/resize_sprint` and `ralph.sh`. I can draft the user stories for that sprint whenever you're ready.

— Ralph, 2026-04-15
