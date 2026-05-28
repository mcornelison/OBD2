# Validation-Criteria-Upfront Contract (V0.28+) — Design Spec

**Date**: 2026-05-28
**Author**: Marcus (PM) under CIO 2026-05-23 directive #2
**Status**: Design complete — awaiting CIO review before implementation plan
**Scope**: `backlog_schema.py` non-empty enforcement (validationCriteria + definitionOfDone); `prd_to_sprint.py` freeze (frozenAt + bigDoDHash); `sprint_lint.py` freeze-drift + per-story empty-list ERRORs; new PM Rule 13 (validation-block sign-off, Atlas-owned); sprint contract spec update; PRD template note.
**Non-scope**: Unfreeze ritual or command (handled by directive #1's patch-sprint pattern). DoD shape enforcement beyond non-empty. Atlas review automation. Backfill of legacy V0.27 sprint.json files (V0.27 chain is closed; freeze applies V0.28+ only).

---

## 1. Motivation

The V0.27 chain shipped clauses being added to `sprint.json validation.bigDefinitionOfDone` *at deploy time*, after the sprint was already dispatched and Ralph had already worked the scope. This was the recurring failure pattern around US-326/US-328/US-348/US-349 (three cycles of "false-pass" recurrence): validation criteria were not pinned upfront, so drill-time discovery of gaps got back-grafted into the contract instead of forcing a structural patch sprint.

**CIO direction (verbal 2026-05-23, captured in `offices/pm/knowledge/v0.28.0-grooming-agenda-cio-2026-05-23-directives.md` §2)**:

> "before the beginning of a dev we need to define the validation criteria too before work has begun. it should be defined as testable actions with outcomes. these will be based on what is in the user story that define that feature release."

Backlog v2 (shipped 2026-05-27) already put most of the mechanics in place: every Story carries `validationCriteria` as a `[{action, outcome}]` list; `prd_to_sprint.py` snapshots each Story's pairs into a `bigDefinitionOfDone` aggregate. This spec closes the remaining gaps:

1. The schema permits `validationCriteria: []` (field required, content not). Need non-empty enforcement.
2. The aggregated `bigDefinitionOfDone` can be modified after dispatch. Need a freeze.
3. Atlas's review of the validation block at sprint-spin time is informal cadence. Need a PM Rule.

---

## 2. Architecture overview

Three lanes of enforcement, each with a specific failure mode:

```
[Backlog grooming]            [PRD → sprint conversion]         [Sprint dispatch + execution]
        │                              │                                  │
        ▼                              ▼                                  ▼
backlog_schema.py             prd_to_sprint.py                    sprint_lint.py
─ requires Story.             ─ snapshots Story.                  ─ checks bigDoDHash matches
  validationCriteria            validationCriteria into             current bigDoD content;
  + definitionOfDone            sprint.json per-story               ERROR on drift
  NON-EMPTY                   ─ writes frozenAt timestamp         ─ checks each story has
                              ─ writes bigDoDHash (SHA-256          NON-EMPTY validationCriteria
                                of canonical bigDoD)                + definitionOfDone
                                                                  ERROR on either empty
```

**Property:** validation criteria are pinned at backlog grooming; aggregated + frozen at PRD→sprint conversion; structurally immutable until the next patch sprint forks from `dev` (per directive #1's dev/main workflow).

---

## 3. Backlog-side enforcement (Story content)

### 3.1 `validateBacklog()` non-empty checks

Current `_validateValidationCriteria` checks shape only. Extend:

```python
def _validateValidationCriteria(story: dict[str, Any]) -> None:
    vc = story.get("validationCriteria")
    if not isinstance(vc, list):
        raise BacklogValidationError(
            f"Story {story['id']}: validationCriteria must be a list"
        )
    if len(vc) == 0:
        raise BacklogValidationError(
            f"Story {story['id']}: validationCriteria must be non-empty "
            f"(at least 1 (action, outcome) pair) per directive 2026-05-23 #2"
        )
    for i, item in enumerate(vc):
        if not isinstance(item, dict) or set(item.keys()) != {"action", "outcome"}:
            raise BacklogValidationError(
                f"Story {story['id']}: validationCriteria[{i}] must have keys "
                f"{{action, outcome}}, got {item!r}"
            )
        if not item["action"] or not item["outcome"]:
            raise BacklogValidationError(
                f"Story {story['id']}: validationCriteria[{i}] action and outcome "
                f"must both be non-empty strings"
            )
```

Add a parallel `_validateDefinitionOfDone(story)` that errors on empty list or empty-string items.

### 3.2 Scope: all 7 story types

Per CIO direction (2026-05-28 brainstorming, ratified): every Story regardless of `type` requires non-empty `validationCriteria` and `definitionOfDone`. Even `housekeeping` ("all callers updated; ruff/mypy clean") and `research` ("note exists at `offices/<role>/knowledge/<file>.md`; <specific claim> documented") get testable pairs. Rationale: without testable criteria, Ralph has no completion signal.

### 3.3 Backfill of existing backlog content

Existing Stories in `offices/pm/backlog.json` (Tasks added during backlog v2) have `validationCriteria: []` placeholders. Per non-goals: no bulk backfill. The enforcement applies starting V0.28+ at story-grooming time — when a Story enters a PRD, its content must satisfy the schema. Stories that haven't been groomed for a sprint don't trigger the check (validateBacklog runs on demand via `sprint_lint --backlog`, which is the gate for PRD-grooming Stories).

**Migration aid:** `validateBacklog` errors point to the specific Story id + field, so PM can fix one Story at a time as they're pulled into PRDs. No flag-day rollout.

---

## 4. Sprint-side enforcement (the freeze)

### 4.1 `prd_to_sprint.py` writes freeze fields

`convertPrdToSprint()` adds two fields to the generated sprint.json `validation` block:

```python
import hashlib
from datetime import datetime, timezone

# After building bigDoD:
canonicalBigDoD = "\n".join(sorted(line.strip() for line in bigDoD))
bigDoDHash = hashlib.sha256(canonicalBigDoD.encode("utf-8")).hexdigest()
frozenAt = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

sprintJson["validation"] = {
    "bigDefinitionOfDone": bigDoD,
    "frozenAt": frozenAt,
    "bigDoDHash": bigDoDHash,
    # ... existing fields (validationMethod, validatesFeatures, currentVersion, etc.
    # populated by PM at sprint-spin time)
}
```

**Canonicalization:** sort lines + strip whitespace + join with `\n`. Deterministic regardless of ordering or stray whitespace. UTF-8 encoded for cross-platform stability.

**SHA-256 choice:** matches git's hashing primitive; collision-resistant well beyond what's needed here; standard library; no new dependency.

### 4.2 `sprint_lint.py` freeze-drift detection

Extend `lintSprintValidation()`:

```python
if v.get("frozenAt"):
    stored = v.get("bigDoDHash")
    if not stored:
        errs.append("validation.frozenAt set but validation.bigDoDHash missing -- contract corrupt")
    else:
        bdod = v.get("bigDefinitionOfDone", [])
        canonical = "\n".join(sorted(line.strip() for line in bdod))
        computed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if computed != stored:
            errs.append(
                f"validation.bigDefinitionOfDone modified after freeze at "
                f"{v['frozenAt']}; computed={computed[:8]}, stored={stored[:8]}. "
                f"Late additions are forbidden per directive 2026-05-23 #2 -- "
                f"create a patch sprint instead."
            )
```

### 4.3 Per-story empty-list ERROR

Extend the existing sprint-story iteration in `sprint_lint`:

```python
for story in sprintData.get("stories", []):
    vc = story.get("validationCriteria", [])
    if not vc:
        errs.append(
            f"Story {story['id']}: validationCriteria empty in sprint.json -- "
            f"every story must have at least 1 (action, outcome) pair "
            f"per directive 2026-05-23 #2"
        )
    dod = story.get("acceptance", []) or story.get("definitionOfDone", [])
    if not dod:
        errs.append(
            f"Story {story['id']}: definitionOfDone empty in sprint.json -- "
            f"every story must have a non-empty DoD so Ralph knows when complete"
        )
```

(Note: `prd_to_sprint.py` currently sets `acceptance = story.get("definitionOfDone", [])` in the sprint.json. The check accommodates either field name.)

### 4.4 What changes after freeze is OK?

The freeze hash covers `validation.bigDefinitionOfDone` only. These validation-block fields legitimately change after freeze:

- `validatedAt` — set by `/sprint-validated`
- `validatedBy` — set by `/sprint-validated`
- `currentVersion` — bumped by `/sprint-deploy-pm` on RELEASE_VERSION bump

These record the validation *event*, not the contract. They are not part of the hash input.

### 4.5 Natural unfreeze path (no command needed)

When drill reveals a real gap, the path is:

1. Drill fails. Argus + CIO identify missing/wrong validation criterion.
2. New patch sprint forks from `dev` (per directive #1 workflow).
3. Patch sprint includes a Story whose validationCriteria captures the new criterion (could be a new Story or an amendment to an existing Story's validationCriteria — the Story.md is the source of truth).
4. `prd_to_sprint.py` generates new sprint.json for the patch sprint with new `frozenAt` + `bigDoDHash`.

No "unfreeze" command exists; no PM ritual to remember. The patch-sprint pattern (already validated for V0.27 chain) is the structural unfreeze.

---

## 5. PM Rule 13 — Validation-block sign-off

### 5.1 Why a new rule (not Rule 10 amendment)

Rule 10 (design-gate DoD) governs Atlas review of *load-bearing subsystem* changes — narrow scope tied to `specs/architecture.md` updates. Validation-block review applies to **every** sprint regardless of architectural scope (a pure housekeeping sprint still needs validation criteria reviewed for Ralph-completeness). Conceptually distinct lanes; cleaner to evolve independently.

### 5.2 Rule 13 text

> 13. **Validation-block sign-off (CIO directive 2026-05-23 #2 + spec 2026-05-28; Atlas owns the gate).** Every sprint's `validation.bigDefinitionOfDone` + per-story `validationCriteria` get Atlas reviewer-lane sign-off before Ralph dispatch. Atlas verifies: (a) each Story's validationCriteria is testable + complete; (b) bigDoD aggregates faithfully; (c) no holes in coverage relative to the Story's stated `goal`. Atlas may raise a formal validation-block BLOCK; PM/CIO clears it explicitly (same shape as Rule 10's design-gate BLOCK). The freeze hash gets cut by `prd_to_sprint.py` at PRD→sprint conversion; Atlas review happens between PRD draft and `prd_to_sprint.py` run.

### 5.3 Interaction with Rule 10

Rule 13 is independent of Rule 10. A sprint can trigger BOTH (load-bearing architectural change + every-sprint validation review) or only Rule 13 (housekeeping sprint with no architectural touch). The two reviews can be combined into a single Atlas brief at sprint-spin time, or sequenced — PM's call.

### 5.4 Review artifact

Atlas's sign-off lands in PM inbox as a single note: `offices/pm/inbox/YYYY-MM-DD-from-atlas-sprint-N-validation-block-review.md`. PM treats Atlas's PASS as the gate-cleared signal; runs `prd_to_sprint.py` to freeze; then dispatches Ralph. PM treats Atlas's BLOCK as a request for PRD revision; PM addresses + reroutes.

---

## 6. Sprint contract spec update

`docs/superpowers/specs/2026-04-14-sprint-contract-design.md` is the canonical sprint-contract reference. It uses unnumbered addendum sections (the most recent is `## Sprint-Level DoD Addendum — Design Gate (added 2026-05-18, CIO directive)`). Append a new addendum following the same pattern:

> ## Validation-Criteria-Upfront Addendum (added 2026-05-28, CIO directive #2)
>
> Every sprint.json `validation` block includes:
> - `frozenAt`: ISO timestamp set by `prd_to_sprint.py`
> - `bigDoDHash`: SHA-256 of canonicalized `bigDefinitionOfDone` content
>
> `sprint_lint.py` ERRORs on:
> - Hash drift (bigDoD modified after freeze)
> - Any story with empty `validationCriteria`
> - Any story with empty `definitionOfDone` / `acceptance`
>
> Atlas reviews the validation block before freeze per PM Rule 13. Late additions to bigDoD after freeze require a patch sprint (per dev/main workflow spec 2026-05-28).

---

## 7. PRD template note

`offices/pm/prds/_template-prd.md` gets a one-paragraph note in the grooming-checklist section:

> Before running `prd_to_sprint.py`, verify each selected Story carries non-empty `validationCriteria` + `definitionOfDone` in its Story.md. Route the draft to Atlas for validation-block review per PM Rule 13. Atlas's PASS clears the freeze gate; PM then runs `prd_to_sprint.py` which pins the hash.

---

## 8. Script impacts (summary)

| Script | Change |
|---|---|
| `backlog_schema.py` | `_validateValidationCriteria` errors on empty list; new `_validateDefinitionOfDone` errors on empty list |
| `prd_to_sprint.py` | Adds `frozenAt` + `bigDoDHash` to generated sprint.json's `validation` block |
| `sprint_lint.py` | `lintSprintValidation` recomputes bigDoDHash + errors on drift; per-story empty-list errors |
| `pm_status.py` | No change (branches display from directive #1 stands) |
| `verify_release_version.py` | No change |
| `bump_passed_statuses.py` | No change |
| `archive_sprint_artifacts.py` | No change (archived sprint.json carries the freeze fields naturally) |
| `chain_validate_aggregate.py` | No change |
| `chain_validate_manifest_bump.py` | No change |
| `repair_ralph_agents.py` | No change |
| `pm_regression_status.py` | No change |
| `graduate_story.py` | No change |

---

## 9. TDD scope

| Test | Asserts |
|---|---|
| `test_backlog_schema_validationCriteria_empty_raises` | Empty list raises BacklogValidationError |
| `test_backlog_schema_definitionOfDone_empty_raises` | Empty list raises BacklogValidationError |
| `test_backlog_schema_validationCriteria_emptyStrings_raises` | `{"action": "", "outcome": "x"}` raises |
| `test_prd_to_sprint_writesFreezeFields` | Generated sprint.json has frozenAt (ISO format) + bigDoDHash (64-char hex) |
| `test_prd_to_sprint_freezeHash_deterministic` | Same input PRD yields same hash on two runs |
| `test_sprint_lint_freezeDrift_detected` | Modifying bigDoD after writing freeze fields → ERROR |
| `test_sprint_lint_freezeNoDrift_passes` | Unchanged bigDoD → no error |
| `test_sprint_lint_storyValidationCriteria_empty_errors` | Sprint story with empty validationCriteria → ERROR |
| `test_sprint_lint_storyDefinitionOfDone_empty_errors` | Sprint story with empty acceptance/definitionOfDone → ERROR |

Total new tests: ~9. Pattern matches existing `tests/pm/test_backlog_schema.py` + `test_pm_status_v2.py` + `test_sprint_lint_*.py` style.

---

## 10. Bootstrap + rollout

No git operation needed (unlike directive #1's `dev` branch creation). Schema + lint changes apply prospectively starting V0.28.0 Sprint 1. Existing legacy V0.27 sprint.json files in `offices/ralph/archive/` are not retroactively validated (V0.27 chain is closed; freeze fields would be missing on archived sprints and sprint_lint's freeze check is skipped when `frozenAt` is absent — graceful degradation for pre-V0.28 contracts).

**Rollout sequence:**

1. Land backlog_schema empty-list errors first (TDD).
2. Land prd_to_sprint freeze fields (TDD).
3. Land sprint_lint freeze + per-story errors (TDD).
4. Add PM Rule 13 to projectManager.md.
5. Update sprint contract spec + PRD template.
6. Update MEMORY.md standing directives + Current State pointer.
7. Mark agenda directive #2 as DONE.

V0.28.0 Sprint 1 PRD is the first downstream consumer; it must produce a sprint.json that passes the new checks.

---

## 11. Cross-references

- CIO directive 2026-05-23 #2 captured in `offices/pm/knowledge/v0.28.0-grooming-agenda-cio-2026-05-23-directives.md` §2
- Existing PM Rules 5 (Story contract) + 8 + 9 (rewritten 2026-05-28 for dev/main workflow) + 10 (design-gate DoD) + 11 + 12 in `offices/pm/projectManager.md`
- Existing scripts in `offices/pm/scripts/`:
  - `backlog_schema.py` (touches `_validateValidationCriteria`)
  - `prd_to_sprint.py` (touches `convertPrdToSprint`)
  - `sprint_lint.py` (touches `lintSprintValidation`)
- Sprint contract spec: `docs/superpowers/specs/2026-04-14-sprint-contract-design.md` (gets new §N)
- Backlog v2 spec (predecessor for Story schema): `docs/superpowers/specs/2026-05-27-backlog-hierarchy-v2-design.md`
- Directive #1 spec (companion landing 2026-05-28): `docs/superpowers/specs/2026-05-28-dev-main-branching-workflow-design.md`
- Atlas design-gate authority (Rule 10 lineage): `offices/architect/knowledge/atlas-charter-and-authority.md`

---

## 12. Open questions deferred to implementation plan

- Whether to update `_template-story.md` wording to reinforce "at least one row required" — PM lean: yes, one-line clarification in the table caption is enough. Defer to plan task.
- Whether `sprint_lint` should also report a *warning* (not error) when an existing sprint.json predates the freeze fields, to make the V0.27 archived-sprint backward-compatibility intentional rather than silent. PM lean: yes; small warning text. Defer to plan task.
- Exact hash field name: `bigDoDHash` chosen over `bigDoDChecksum` or `contractHash` for readability. Defer to plan task only if user pushes back.
