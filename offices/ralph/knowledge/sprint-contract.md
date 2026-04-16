# Sprint Contract Knowledge

Spec location: `docs/superpowers/specs/2026-04-14-sprint-contract-design.md`

## 5 Refusal Rules
1. **Refuse First** — ambiguity = blocker, not invitation. File BL- and stop.
2. **Ground Every Number** — every value needs `groundingRefs` entry with source + owner. No rounding.
3. **Scope Fence** — touch only `scope.filesToTouch`. Tangential fixes → TD- file.
4. **Verifiable Criteria Only** — no weasel phrases. Explicit commands in `verification[]`.
5. **Silence is Default** — populate `filesActuallyTouched` + `grounding` only. No journal entries.

## Story Schema Key Fields
`id`, `title` (≤70 chars), `size` (S/M/L), `intent` (1-2 sentences), `scope` (filesToTouch/filesToRead/doNotTouch), `groundingRefs` [{value, unit, source, owner}], `acceptance` (verifiable), `verification` (commands), `invariants`, `stopConditions`, `feedback` {filesActuallyTouched, grounding}, `passes`

## Sizing Caps
- **S**: ≤2 files, ≤3 criteria, ≤200 lines diff
- **M**: ≤5 files, ≤5 criteria, ≤500 lines diff
- **L**: ≤10 files, ≤8 criteria, ≤1000 lines diff + PM sign-off. No XL — split.

## Reviewer Two-Path Rule
1. In-lane edit → directly improve story fields (clarity, specificity, accuracy)
2. Out-of-lane idea → PM inbox note → becomes backlog seed

No `comments[]` field. Silence is the default.

## Banned Phrases in Acceptance Criteria
`handle edge cases`, `works correctly`, `good UX`, `as appropriate`, `if needed`, `etc.`, `and so on`, `make sure that`, `verify` without command, `tests pass` without pytest command.

## One Source of Truth Rule
During story execution, read ONLY `scope.filesToRead`. No exploration. The sprint contract IS the context.
