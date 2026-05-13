# From Ralph (Agent2, Session 197) — pre-existing fast-suite failure surfaced during US-333

**Date:** 2026-05-12
**Context:** While running the Sprint 34 / US-333 verification gate (`pytest tests/ -m 'not slow' -q`), the fast suite came back with **exactly one failure** — and it is **not introduced by US-333** (US-333 touched only `src/server/api/sync.py` + the new `tests/server/test_sync_history_timestamps_utc.py`).

## The failure

```
FAILED tests/lint/test_ralph_promise_tag_contract.py::test_promptMdAndRalphShDocumentSamePromiseTags
  AssertionError: prompt.md documents tags not handled by ralph.sh:
  ['COMPLETE', 'PARTIAL_BLOCKED']. Either add branches to ralph.sh or remove the documentation entries.
```

## Why it's pre-existing (not US-333)

- `git status` at session start (and now) shows `M offices/ralph/ralph.sh` — a large **uncommitted** working-tree edit (`git diff --stat`: `offices/ralph/ralph.sh | 290 +++++…`). `offices/ralph/prompt.md` is **not** modified (still HEAD).
- The lint test reads `prompt.md` ⇄ `ralph.sh` and asserts the documented `<promise>` tag set matches the shell's handled set. The uncommitted `ralph.sh` rewrite dropped (or restructured past the test's parser) the `COMPLETE` and `PARTIAL_BLOCKED` branches that `prompt.md` still documents.
- US-333's diff is entirely under `src/server/` + `tests/server/` — it cannot affect `prompt.md`/`ralph.sh`.

## What I did NOT do (scope fence — Refusal Rule 3)

Did not touch `offices/ralph/ralph.sh`, `offices/ralph/prompt.md`, or `tests/lint/test_ralph_promise_tag_contract.py` — all far outside US-333's `scope.filesToTouch`.

## Suggested PM/CIO action

Reconcile `ralph.sh` ⇄ `prompt.md` once the in-flight `ralph.sh` rewrite is finalized: either re-add `COMPLETE`/`PARTIAL_BLOCKED` handling branches in `ralph.sh`, or trim those entries from `prompt.md`'s Stop-Condition table — whichever matches the rewrite's intent. The other pre-existing fast-suite blemish (ruff drift in `tests/pi/regression/test_powersource_module_identity.py`, 8 UP037/F401) is already noted in `sprint.json testBaseline`; this promise-tag one is **not** yet noted there.

— Ralph (Agent2)
