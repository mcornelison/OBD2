---
sprint: <N>
version: V<X>.<Y>.<Z>
status: draft
createdAt: YYYY-MM-DD
createdBy: Marcus (PM)
selectedStories: [US-XXX, US-YYY]
argusReviewRequired: false
convertedAt: null
sprintJsonPath: null
---

# PRD — Sprint <N> (V<X>.<Y>.<Z>): <theme line>

## Sprint goal
<1–3 sentences. What this sprint delivers.>

## Selected stories
| Story | Title | Feature | Epic | Type | Size |
|---|---|---|---|---|---|
| US-XXX | <title> | F-XXX | E-XXX | normal | M |

## Open questions
| # | Question | Raised by | Resolution | Resolved by |
|---|---|---|---|---|

## Atlas architecture review
*Date: TBD*

## Argus QA review (only if required)
*Date: TBD*

## Sprint-level `validation.bigDefinitionOfDone`

## Before running `prd_to_sprint.py` (per spec 2026-05-28 / CIO directive #2)

1. Verify each selected Story carries non-empty `validationCriteria` + `definitionOfDone` in its Story.md (testable action + outcome pairs).
2. Route the draft to Atlas for validation-block review per PM Rule 13. Atlas verifies criteria are testable, bigDoD aggregates faithfully, no coverage holes vs Story `goal`.
3. Atlas PASS clears the freeze gate; PM then runs `prd_to_sprint.py` which pins the `bigDoDHash`. After that, late additions to bigDoD are ERRORs in `sprint_lint.py` — drill-discovered gaps require a patch sprint.

## Refinements made during grooming
| Story | Refinement | Made by | Date |
|---|---|---|---|

## Dependencies & sequencing

## Conversion record

## Audit trail
- YYYY-MM-DD draft created
