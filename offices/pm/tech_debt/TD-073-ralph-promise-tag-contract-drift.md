# TD-073 — `prompt.md` documents promise tags `ralph.sh` does not handle

- **Filed**: 2026-08-02 by Ralph (Rex), during US-517 (Sprint 69 / V0.29.24)
- **Severity**: Medium — fails the FAST lint suite, so it will trip the PM
  integration gate at sprint close
- **Status**: RESOLVED 2026-08-03 by US-529 (Sprint 70 / V0.29.25) — **cause (a),
  the gate was crying wolf.** See "Resolution" at the bottom; the fix was NOT to
  add the branch.
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
Ralph's lane to change unilaterally. (Sanctioned via US-529: PM sprint-wrapped
the TD, which is the standing path for Ralph to touch harness files.)

## Resolution (US-529, 2026-08-03)

**Cause (a): the test's parser had drifted. Adding the branch would have been a
regression, so it was refused.**

Evidence, all held as tests rather than asserted:

- **A sprint-ending branch DOES exist** — `ralph.sh:243` compares the
  `sprint.json` tally (`after_complete -ge total`), announces `PRD COMPLETE`
  and `exit 0`. So a sprint-ending `COMPLETE` **is** acted on, via the
  authoritative artifact rather than the model's claim.
- **It is deliberately not tag-driven** — the loop-control contract rewritten
  2026-05-12 states the tag is advisory and names
  `<promise>COMPLETE</promise> when the count disagrees ... CONTINUE`.
- **`PARTIAL_BLOCKED`'s documented behaviour ("continue") IS the loop's
  default**, so a branch would be a no-op.
- **The literal drift**: `ralph.sh` documented `COMPLETE` in the *abbreviated*
  `<promise>COMPLETE</>` form (header line ~16), invisible to the test's
  `</promise>` regex.

Adding `grep -q '<promise>COMPLETE</promise>' -> exit 0` would let a model end a
sprint by **asserting** completion while stories are still `passes:false` — the
exact failure the 2026-05-12 rewrite removed. That regression is now pinned as a
test (`test_completeTagIsNotAGrepBranch_soAModelCannotEndASprintByAssertingIt`).

The gate was **re-grounded rather than loosened**: it now parses real `grep`
branches vs explicit `# NOT_TAG_DRIVEN: <promise>X</promise> -- <why>`
declarations, and separately pins the tally-derived completion mechanism so the
declaration cannot silently become a lie. Deleting entries from `prompt.md` — the
other way to make the old assertion pass — is now itself a failure.
