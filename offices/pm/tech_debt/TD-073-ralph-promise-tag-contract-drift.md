# TD-073 — `prompt.md` documents promise tags `ralph.sh` does not handle

- **Filed**: 2026-08-02 by Ralph (Rex), during US-517 (Sprint 69 / V0.29.24)
- **Severity**: Medium — fails the FAST lint suite, so it will trip the PM
  integration gate at sprint close
- **Status**: Open
- **Scope**: NOT fixed in US-517 (scope fence — both files unmodified by that
  story)

## Symptom

```
tests/lint/test_ralph_promise_tag_contract.py::test_promptMdAndRalphShDocumentSamePromiseTags
AssertionError: prompt.md documents tags not handled by ralph.sh:
  ['COMPLETE', 'PARTIAL_BLOCKED'].
  Either add branches to ralph.sh or remove the documentation entries.
```

Reproduce: `pytest tests/lint/ -q`

## Why it matters more than a doc nit

`COMPLETE` is the tag that **ends a sprint**. The contract test asserts
`ralph.sh` has no branch for it. Either:

- **(a)** the test's parser has drifted (it may be scanning for a branch shape
  `ralph.sh` no longer uses), in which case the gate is crying wolf and should
  be re-grounded; or
- **(b)** `ralph.sh` genuinely lost the branch, in which case a sprint-ending
  `<promise>COMPLETE</promise>` is not being acted on and the loop's stop
  condition is broken.

Those have opposite fixes, so this needs a look rather than a rubber stamp.

Note the shape: this is the **same class as the US-513 finding** — a test
asserting a contract against a second artifact that *describes* the behaviour
rather than the one that *enforces* it. Worth checking which side is wrong
before editing either.

## Not a US-517 regression

`git status` shows `offices/ralph/prompt.md` and `offices/ralph/ralph.sh` both
unmodified on `sprint/sprint69-V0.29.24`. US-517 touched `config.json`,
`src/common/config/validator.py`, `src/pi/location/**`,
`specs/architecture.md` and its own tests only.

## Suggested owner

PM (Marcus) — `ralph.sh` and `prompt.md` are the harness contract, outside
Ralph's lane to change unilaterally.
