# TD-081 — `test_prd_to_sprint.py` still asserts the RETIRED freeze fields (2 red tests on `dev`)

**Filed:** 2026-08-11 by Rex (Ralph) during US-554
**Area:** `tests/pm/test_prd_to_sprint.py` / `offices/pm/scripts/prd_to_sprint.py`
**Severity:** Medium — two permanently-red tests in `tests/pm`
**Status:** Open

## What

Two tests fail on a clean tree, and have since commit `22f65a8`:

```
FAILED tests/pm/test_prd_to_sprint.py::test_convertPrdToSprint_writesFreezeFields
FAILED tests/pm/test_prd_to_sprint.py::test_convertPrdToSprint_freezeHash_deterministic
    assert dataA["validation"]["bigDoDHash"] == dataB["validation"]["bigDoDHash"]
E   KeyError: 'bigDoDHash'
```

`22f65a8` ("process(pm): retire freeze mechanic (CIO 2026-07-13)") stopped
`prd_to_sprint` stamping `frozenAt` / `bigDoDHash`. The **producer** was retired;
these two **tests** were not, so they now pin a field the CIO deliberately
removed. The production code is correct — the tests are the stale half.

## Why it matters more than "two red tests"

A standing red in `tests/pm` **trains agents to read red as normal**. I hit it
running the US-554 fence and had to spend a step proving it was not mine (it is
not: my diff touches only `index_lock.py`, `ralph.sh`, `test_index_lock.py`, and
neither failing test nor its subject appears in it). Every future story that
fences over `tests/pm` pays that same tax, and the one time the red IS theirs,
the habit says otherwise.

## Fix (PM call — which way to resolve is not Ralph's to pick)

Either delete both tests with the mechanic they described, **or**, if any
consumer still reads the freeze fields, re-derive whether the retirement was
complete. `sprint_lint` already auto-skips the freeze checks, which points at
plain deletion.

**Not fixed here:** `offices/pm/` scripts + their tests are PM-owned, US-554 is
scope-fenced to the index-lock guard, and deleting a PM process test on my own
authority is the wrong call even when the git history is unambiguous.

## Refs

- Retirement commit: `22f65a8`
- MEMORY.md: "freeze RETIRED Session 54"
- Found during: US-554 (Sprint 74 / V0.29.29)
