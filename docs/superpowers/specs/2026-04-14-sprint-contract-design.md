# Sprint Contract — Eclipse OBD-II

**Project:** Eclipse OBD-II Monitor
**Author:** Ralph (autonomous dev agent), with CIO direction
**Created:** 2026-04-14
**Revised:** 2026-04-15 (scope tightened per CIO feedback)
**Status:** Draft — pending CIO approval
**Supersedes:** none

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-04-14 | Ralph + CIO | Initial draft (over-scoped — included pipeline, validator tables, directory layout) |
| 2026-04-15 | Ralph + CIO | Rewritten to narrow scope: story schema + content quality rules + reviewer discipline |
| 2026-05-18 | Marcus (PM) | Added Sprint-Level DoD Addendum (design-gate rule) + Atlas reviewer lane, per CIO role-boundary directive 2026-05-18 |

---

## Purpose

Define what a well-written user story in `offices/ralph/sprint.json` looks like so Ralph can execute it efficiently in headless mode. This spec covers three things:

1. **The story schema** — what fields exist and what each one means
2. **Content quality rules** — what "well-defined" actually means in practice
3. **Reviewer discipline** — how reviewers contribute to story quality without adding noise

This spec does NOT describe the PM sprint process, validator implementation, directory layout, or the full pipeline from backlog to Ralph. Those are implementation details handled separately.

## Why this matters

In headless mode (`offices/ralph/ralph.sh`), there is no human in the loop. A context-starved LLM that hits ambiguity will ship a plausible guess rather than stop and ask — the "people-pleaser failure mode." The contract's job is to make every story self-contained enough that Ralph never has to guess.

---

## The 5 Rules for a Well-Defined Story

These define what PM (Marcus) and reviewers aim for when writing and refining a story. They go into `offices/ralph/agent.md` as Ralph's runtime discipline, but they are equally rules for how the story itself is authored.

### Rule 1 — Refuse First

When in doubt, Ralph STOPS and files a blocker in `offices/pm/blockers/BL-<date>-<story-id>-<slug>.md`. Ambiguity is a blocker, not an invitation. A valid refusal is more valuable than a plausible wrong answer.

**What this means for story authoring:** the story must be unambiguous. If a reviewer spots ambiguity during review, they fix it in place so Ralph never sees it.

### Rule 2 — Ground Every Number

Every threshold, interval, ratio, or constant in the story must trace to an authoritative source via a `groundingRefs` entry. No rounding, no "reasonable defaults," no common sense.

**What this means for story authoring:** every numeric value that appears in `intent`, `acceptance`, `invariants`, or `stopConditions` must have a matching `groundingRefs` entry with `source` and `owner`.

### Rule 3 — Scope Fence

The story declares exactly which files Ralph may touch (`scope.filesToTouch`) and exactly which files Ralph may read (`scope.filesToRead`). Ralph touches nothing outside `filesToTouch` and reads nothing outside `filesToRead`.

**What this means for story authoring:** the file manifest must be complete. If the list is wrong or missing a file, Ralph files a blocker — he does NOT scavenge for context.

### Rule 4 — Verifiable Criteria Only

Every acceptance criterion must be executable or observable. No weasel phrases (see banned list). The story provides explicit `verification` commands — not "tests pass."

**What this means for story authoring:** every criterion must be something Ralph can check with a specific command or file inspection. Vague criteria get rewritten or the story gets split.

### Rule 5 — Silence is the Default for Feedback

Ralph populates `feedback.filesActuallyTouched` and `feedback.grounding` because they are verifiable facts. Ralph does NOT populate journal-style commentary. If something surprising happened, it becomes a BL- / TD- / I- file or an inbox note to the relevant teammate — never accumulated inside sprint.json.

**What this means for story authoring:** sprint.json has no commentary or journal fields. It has story content + proof of execution. Nothing narrative lives inside it.

---

## Story Schema (sprint.json)

### Field Reference

| Field | Required | Purpose |
|---|---|---|
| `id` | ✅ | Pattern `US-\d+` (split sub-stories use `US-\d+-[a-z]`); unique within sprint |
| `title` | ✅ | ≤70 chars, imperative verb + object (e.g. "Update coolantTempCritical to 220F") |
| `size` | ✅ | `S` / `M` / `L` — drives cap enforcement |
| `intent` | ✅ | 1–2 sentences explaining WHY this story exists |
| `priority` | ✅ | `high` / `medium` / `low` — ordering among unblocked stories |
| `dependencies` | ✅ | Array of story IDs that must complete first |
| `scope.filesToTouch` | ✅ | Explicit file manifest; size cap enforced |
| `scope.filesToRead` | ✅ | The ONLY files Ralph may read during this story |
| `scope.doNotTouch` | optional | Explicit forbidden neighbors (belt-and-suspenders) |
| `groundingRefs` | ✅ | `[{value, unit, source, owner}]` for every numeric value |
| `acceptance` | ✅ | Verifiable conditions; first entry is always the pre-flight audit |
| `verification` | ✅ | Explicit command strings Ralph runs to verify (NOT "tests pass") |
| `invariants` | ✅ | Things that must not change (e.g., test-count preservation) |
| `stopConditions` | optional | Per-story STOP triggers |
| `feedback` | ✅ | Scaffold: `{ "filesActuallyTouched": null, "grounding": null }` |
| `passes` | ✅ | `false` until story complete and all checks pass |

### Sizing Caps

| Size | filesToTouch | acceptance (excl. pre-flight) | diff | PM sign-off |
|---|---|---|---|---|
| **S** | ≤2 | ≤3 | ≤200 lines | no |
| **M** | ≤5 | ≤5 | ≤500 lines | no |
| **L** | ≤10 | ≤8 | ≤1000 lines | **required** (`pmSignOff` field) |

No XL. Stories larger than L split into dependency-chained sub-stories.

### Annotated Example

```json
{
  "id": "US-147",
  "title": "Update coolantTempCritical to 220F in pi/obd/thresholds.py",
  "size": "S",
  "intent": "Align coolant threshold with Spool spec (220F). Single file, single constant.",
  "priority": "high",
  "dependencies": [],
  "scope": {
    "filesToTouch": ["src/pi/obd/thresholds.py"],
    "filesToRead": [
      "specs/grounded-knowledge.md",
      "src/pi/alert/tiered_thresholds.py",
      "tests/test_thresholds.py"
    ],
    "doNotTouch": ["src/pi/alert/tiered_thresholds.py"]
  },
  "groundingRefs": [
    {
      "value": "220",
      "unit": "F",
      "source": "specs/grounded-knowledge.md#coolant-critical",
      "owner": "Spool"
    }
  ],
  "acceptance": [
    "Produce pre-flight audit listing files to touch, unknowns, and assumptions before any code change",
    "src/pi/obd/thresholds.py coolantTempCritical constant = 220",
    "tests/test_thresholds.py::test_coolantCritical_at220F_raisesAlert passes"
  ],
  "verification": [
    "pytest tests/test_thresholds.py -v",
    "ruff check src/pi/obd/thresholds.py"
  ],
  "invariants": ["Fast-suite count stays at 1469"],
  "stopConditions": [
    "If 220F is not in grounded-knowledge.md, STOP and file BL-"
  ],
  "feedback": {
    "filesActuallyTouched": null,
    "grounding": null
  },
  "passes": false
}
```

---

## Reviewer Contribution Rules

Reviewers are: **Marcus** (PM — always), **Atlas** (Senior Solutions Architect — auto-flagged when any load-bearing subsystem is touched; owns the design gate), **Spool** (Tuner SME — auto-flagged when any Spool-owned value is touched), **Tester** (Marcus's call based on regression risk), **Ralph** (rare — invited by Marcus for dev-heavy stories). Reviewer set is selected per sprint based on complexity.

### Two paths, no third option

**Path 1 — Direct high-quality edit to a story field.**
If the reviewer can make the story clearer, more specific, or more correct — *within their expertise* — they edit the story directly. Acceptable edits: `intent`, `scope.filesToTouch`, `scope.filesToRead`, `groundingRefs`, `acceptance`, `verification`, `invariants`, `stopConditions`. The goal: Ralph reads the refined story and finds it unambiguous, fully grounded, and executable.

Examples of valuable in-lane edits:
- **Spool** tightens a `groundingRefs.value` from a rounded number to the exact spec value
- **Spool** adds a `stopConditions` entry reflecting a tuning-physics edge case
- **Tester** adds a specific pytest command to `verification` that catches a known regression surface
- **Tester** extends an `acceptance` criterion with a specific observable (e.g., "at exactly 220.0F, result is CAUTION_HIGH, not DANGER")
- **Ralph** (pre-execution) adds a missing file to `scope.filesToRead` so he won't have to file a blocker at runtime
- **Marcus** clarifies an ambiguous `intent` statement, rewrites a weasel-phrased criterion, or splits an oversized story

**Path 2 — Inbox note to PM for suggestions, ideas, and general improvements.**
If the reviewer has a genuine suggestion or idea that is NOT a story-clarity edit — e.g., *"we should also build feature X,"* *"this whole area needs rethinking,"* *"there's a broader pattern problem here"* — they write a note to `offices/pm/inbox/<date>-from-<reviewer>-<topic>.md`. Marcus reads the inbox and decides whether the idea becomes a backlog item, which later becomes a future sprint.

### Silence is the default

If nothing needs an in-lane edit AND nothing needs PM-level attention, the reviewer says nothing. There is no `comments[]` field. There is no review journal. There is no "I reviewed this and have no concerns" sign-off text. Review discipline means: contribute value or stay silent.

### Reviewer lanes (what each role may edit in-line)

| Role | In-lane edits (during PRD/story review) | Goes to PM inbox instead |
|---|---|---|
| **Marcus (PM)** | Any story field — PM owns sprint shape | — (their lane) |
| **Atlas (Architect)** | Architecture-related `acceptance`/`invariants`, the `specs/architecture.md`-update DoD clause for load-bearing stories; may raise a design-gate **BLOCK** | Non-architectural refactor ideas, broader roadmap suggestions |
| **Spool (Tuner SME)** | `groundingRefs` values, tuning-related `acceptance`, tuning-related `invariants`, tuning-related `stopConditions` | Code-structure ideas, test-pattern ideas, non-tuning observations |
| **Tester** | `verification` commands, regression-related `acceptance` entries | Code-refactor ideas, broader test-strategy suggestions |
| **Ralph (pre-exec review)** | `scope.filesToTouch`, `scope.filesToRead`, implementation-detail `acceptance` | Tuning concerns, PRD scope concerns |

A reviewer may never modify a value owned by a different lane. Spool never touches `scope.filesToTouch`. Ralph never touches a Spool-owned `groundingRefs.value`. Cross-lane concerns go to Marcus's inbox and (maybe) become backlog items.

---

## Banned Phrases

These phrases are rejected in acceptance criteria. Each one lets a people-pleaser LLM ship without doing the actual work.

- `handle edge cases`
- `works correctly`
- `good UX`
- `as appropriate`
- `if needed`
- `etc.` / `and so on`
- `make sure that`
- `verify` *without a specific command*
- `tests pass` *without a specific pytest command*

Append-only list. Reviewers may propose additions via Marcus's inbox.

---

## Example: Bad Story Rewritten as Good

### Before — what a bad story looks like

```json
{
  "id": "US-147",
  "title": "Fix coolant thresholds",
  "description": "The coolant temperature thresholds need to be updated based on Spool's recent spec. Make sure that the values are handled correctly and that edge cases are covered. Tests should pass.",
  "acceptanceCriteria": [
    "Coolant thresholds work correctly",
    "Handle edge cases appropriately",
    "Tests pass"
  ],
  "priority": "medium"
}
```

**What's wrong with this story** (and what Ralph will fabricate if headless):

- Title is vague ("Fix coolant thresholds" — which thresholds? in which file?)
- No `size` declared → Ralph cannot predict context cost
- No `scope` → Ralph will explore the codebase to find relevant files, burning tokens
- No `groundingRefs` → Ralph will invent a value or pick one from the nearest plausible file
- Every acceptance criterion contains a banned phrase ("work correctly," "handle edge cases," "tests pass")
- No `verification` commands → Ralph decides which tests to run (probably wrong ones)
- No `invariants` → test-count drift and scope escape will go unnoticed
- No `stopConditions` → Ralph has no explicit permission to refuse

**In a headless run, Ralph would:**
1. Explore `src/pi/` looking for coolant-related files (20K tokens)
2. Pick a file that looks relevant but may be wrong
3. Invent a reasonable-looking threshold value from context (e.g., 212 or 230)
4. Write a change, run the full test suite, mark `passes: true`
5. Ship a subtly wrong value that won't get caught until real drive data arrives

### After — what a well-defined story looks like

See the annotated example in the Story Schema section above. Every field is explicit; every value is grounded; every criterion is executable; the file manifest is complete; the invariants are declared; the stop conditions give Ralph an obvious refusal path.

**Ralph reads this story once and knows exactly what to do.** No exploration. No guessing. No fabrication. If anything in the story is wrong, Ralph files a blocker rather than improvising — because the story gives him explicit permission to refuse.

---

## Sprint-Level DoD Addendum — Design Gate (added 2026-05-18, CIO directive)

This spec governs story-level quality. One sprint-level Definition-of-Done rule is added here because it is administered through the sprint contract:

**Design-gate DoD rule.** Any sprint that touches a *load-bearing subsystem* — power/shutdown, sync, the data-capture pipeline, `src/common/` contracts, tier boundaries, or any subsystem with a `specs/architecture.md` section — MUST update that subsystem's `specs/architecture.md` section **within the same sprint**. The architecture-spec update is part of the sprint's Definition of Done (carry it in `validation.bigDefinitionOfDone` and in the relevant story's `acceptance`), never a deferred follow-up.

- **Who owns the gate:** Atlas (Senior Solutions Architect). Atlas may raise a formal design-gate **BLOCK** on any load-bearing change shipped without its spec update; PM/CIO clears the block explicitly.
- **Who administers it:** Marcus (PM) bakes the clause into the sprint contract and the `bigDefinitionOfDone`, routes the architectural call to Atlas, and lands Atlas's corrected-architecture decision into the sprint or a TD.
- **Why:** `specs/architecture.md` went ~17 sprints stale on power/shutdown, producing a false EEPROM-wake guarantee (Atlas finding F-6) that became the documentation root of the V0.27 chain blocker. The gate exists so a confident-but-stale spec can never again mask a real subsystem failure.

---

## Validation-Criteria-Upfront Addendum (added 2026-05-28, CIO directive #2)

Per spec `docs/superpowers/specs/2026-05-28-validation-criteria-upfront-contract-design.md`:

Every sprint.json `validation` block includes:
- `frozenAt`: ISO timestamp set by `prd_to_sprint.py` at PRD→sprint conversion
- `bigDoDHash`: SHA-256 of canonicalized `bigDefinitionOfDone` content (canonicalization helper at `offices/pm/scripts/_freeze.py`)

`sprint_lint.py` ERRORs on:
- Hash drift (`bigDefinitionOfDone` modified after freeze)
- Any story with empty `validationCriteria`
- Any story with empty `acceptance` (the sprint.json field name for the Story's `definitionOfDone`)

Atlas reviews the validation block before freeze per PM Rule 13. Late additions to `bigDoD` after freeze require a patch sprint (per dev/main workflow spec 2026-05-28). The natural unfreeze path is forking a new patch sprint from `dev`; no explicit unfreeze command exists.

`backlog_schema.py` enforces non-empty `validationCriteria` + `definitionOfDone` on every Story at backlog grooming time. Stories cannot enter a PRD without populated content.

---

*End of spec.*
