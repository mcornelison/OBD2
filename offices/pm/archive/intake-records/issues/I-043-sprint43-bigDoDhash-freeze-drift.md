# I-043: Sprint 43 (V0.28.0) bigDoDHash drifted from frozen bigDefinitionOfDone

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | High |
| Status       | Open |
| Category     | testing / infrastructure (sprint freeze integrity) |
| Found In     | `offices/ralph/sprint.json` (`validation.bigDoDHash` vs `validation.bigDefinitionOfDone`) |
| Found By     | Rex (Ralph agent), US-359 iteration 2026-05-28 |
| Related B-   | F-107 / PM Rule 13 / validation-criteria-upfront contract (spec 2026-05-28; CIO directive 2026-05-23 #2) |
| Created      | 2026-05-28                |

## Description

The Sprint 43 `validation.bigDoDHash` does **not** match the SHA-256 of the
canonicalized `validation.bigDefinitionOfDone` currently in `sprint.json`. This
is exactly the freeze-drift tripwire that `sprint_lint.lintSprintValidation`
exists to catch — and it fires:

```
validation.bigDefinitionOfDone modified after freeze at 2026-05-28T19:26:59Z;
computed=5557ae5c, stored=251bad94. Late additions are forbidden per directive
2026-05-23 #2 -- create a patch sprint instead.
```

- **Stored** `bigDoDHash`: `251bad9423a5b627f6cd7d9c2b51f2db004c6f830153d77365205607012c5dcf`
- **Recomputed** from the file's `bigDefinitionOfDone`: `5557ae5c696e7bf73454604175739e4a74b5f82e0e81a7965bed03f21f3f0878`
- Recipe (identical in `prd_to_sprint.py:121-122` and `sprint_lint.py:417-418`):
  `hashlib.sha256(_freeze.canonicalizeBigDoD(bdod).encode("utf-8")).hexdigest()`

**This pre-dates the US-359 commit.** `git show HEAD:offices/ralph/sprint.json`
recomputes to the same `5557ae5c…` and still stores `251bad94…`, so the drift
was present in the committed tree before this iteration. The US-359 diff touches
**only** the US-359 story object (`passes`, `completionNotes`, `feedback`) and
does not alter `bigDefinitionOfDone` (verified via `git diff`).

## Steps to Reproduce

1. `python offices/pm/scripts/sprint_lint.py --path offices/ralph/sprint.json`
   reports `0 error(s)` in the printed **Summary** line — but that summary only
   tallies the per-story `validateStory` errors. The sprint-level
   `validation`-block error is computed separately and is **not** rolled into
   that count (a reporting gap worth a follow-up).
2. Call the check directly to see the real verdict:
   ```python
   from offices.pm.scripts.sprint_lint import lintSprintValidation
   import json; from pathlib import Path
   print(lintSprintValidation(json.load(open('offices/ralph/sprint.json')), Path('.')))
   ```
3. Observe: one error — bigDefinitionOfDone modified after freeze (hash drift).

## Expected Behavior

`bigDoDHash` should equal the SHA-256 of the canonicalized `bigDefinitionOfDone`
that is actually present in `sprint.json`, so `/sprint-deploy-pm` and
`/sprint-validated` (which run `sprint_lint`) pass their freeze-integrity gate.

## Actual Behavior

Stored hash and file content disagree. Most likely cause (per MEMORY.md
current-state pointer): the Spool Q2/Q4 + Atlas structural-pin deltas were
applied to per-story `validationCriteria` (which aggregate into
`bigDefinitionOfDone`) after the `frozenAt=2026-05-28T19:26:59Z` freeze, OR a
manual edit landed after the documented `prd_to_sprint.py` re-freeze, so the
stored hash was never re-stamped to match the final ratified content.

## Impact

- **Blocks PM deploy/validate rituals**: `/sprint-deploy-pm` Phase 0 and
  `/sprint-validated` invoke `sprint_lint`; this error will halt them.
- **Does NOT block Ralph dev**: US-360..US-373 are fully specified and
  implementable; the drift only bites at sprint-close lint/deploy. US-359
  landed green and is unaffected.
- The per-story criteria appear to be the CIO+Atlas+Spool-ratified versions
  (per MEMORY.md), so the **content is believed legitimate** — the hash just
  needs reconciling.

## Recommended Resolution (PM-owned — freeze authority)

1. Confirm the current `bigDefinitionOfDone` is the intended, ratified content
   (Spool Q2/Q4 + Atlas pin applied). If yes → re-run `prd_to_sprint.py` (or the
   re-freeze path) so `bigDoDHash` is re-stamped to `5557ae5c…` and `frozenAt`
   is refreshed. If the drift reflects an **unintended** post-freeze edit →
   reconcile content first, then re-freeze.
2. Consider rolling the sprint-level `validation`-block error into
   `sprint_lint`'s printed **Summary** count so `EXIT=0` can't mask a freeze
   drift (see Step 1 above — the error is real but the summary said `0 error(s)`).

## Resolution

[Fill in when resolved]
