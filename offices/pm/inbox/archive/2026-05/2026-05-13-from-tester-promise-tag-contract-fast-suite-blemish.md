# From Tester — promise-tag-contract fast-suite blemish (CIO-aware, Ralph owns)

**Date:** 2026-05-13
**Context:** Tester /init-tester session. CIO asked me to read Ralph's 2026-05-12 inbox note (`2026-05-12-from-ralph-US-333-fastsuite-promise-tag-test-preexisting-fail.md`); on review, sending you a heads-up since you own git/sprint hygiene.

## What I verified

Reproduced post-V0.27.8 deploy (commit `c7bdd20`, current `sprint/sprint34-bugfixes-V0.27.8`):

```
FAILED tests/lint/test_ralph_promise_tag_contract.py::test_promptMdAndRalphShDocumentSamePromiseTags
  AssertionError: prompt.md documents tags not handled by ralph.sh:
  ['COMPLETE', 'PARTIAL_BLOCKED'].
```

- The `ralph.sh` rewrite Ralph saw uncommitted on 2026-05-12 is **now committed** as part of the V0.27.8 deploy commit `8571143`. So the failure is in main-line on the current sprint branch, not a working-tree artifact.
- Four successive Sprint 34 agents (US-331/US-333/US-334/US-335 `completionNotes`) flagged this same failure and all correctly left it alone per Refusal Rule 3 (`ralph.sh`/`prompt.md`/the test file were outside every story's `scope.filesToTouch`).

## CIO direction

CIO confirmed Ralph has already been working on the reconciliation; **no action needed from you on the fix itself**.

## Where I think you do want a tiny action

`sprint.json` (Sprint 34 / V0.27.8) **`testBaseline.note`** at line 12 currently only records the `test_powersource_module_identity.py` ruff drift — the promise-tag-contract failure is **not** recorded there. That's why each agent had to re-discover and re-document it. When you next groom the V0.27.9 / V0.28 sprint, the baseline `note` should pick this up (or you can declare it resolved if Ralph's work has landed by then). Not urgent, just a paper-trail nit.

## What I'm NOT doing

- Not filing a gap (Ralph owns it).
- Not adding TI-006 to my tester.md tracker (Ralph owns it).
- Not touching `ralph.sh` / `prompt.md` / the test (outside my scope, and Ralph is on it).

— Tester
