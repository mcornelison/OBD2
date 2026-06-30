# Design Spec — PRD→Sprint Workflow Simplification

**Date:** 2026-06-29
**Author:** Marcus (PM)
**Status:** CIO-DECIDED 2026-06-29 (all open questions resolved — see §8; ready to scope implementation)
**Supersedes/amends:** PM Rule 5 (validation-criteria stage), PM Rule 13 (freeze sign-off), the `2026-05-28-validation-criteria-upfront-contract-design.md` freeze mechanics, `/resize-sprint` + `/groom-product-requirements` skills, `prd_to_sprint.py`.

---

## 1. Why this exists

The path from "an idea" to "a `sprint.json` Ralph can execute" has **accreted layers**, each added to fix a real past pain, but several now duplicate each other or duplicate git. Friction observed in a single session (2026-06-28/29, Sprints 47+48):

- The **same story detail authored 3×** — `backlog.json` + Story.md mirrors + `sprint.json`.
- `prd_to_sprint.py` emits only the hash subset → the PM **hand-adds 5 validation fields** (`validationMethod` / `validatesFeatures` / `currentVersion` / `validatedAt` / `validatedBy`) **every freeze** (done twice this session).
- `validatesFeatures` must be **manually pre-registered** in `regression_manifest.json` each freeze.
- `/resize-sprint` is a **stale DataWarehouse-template skill** (`prd.json`, `signOffs`, "Ledger/Kunai" personas) — its sizing judgment is already emitted by `sprint_lint` warnings.
- Recurring **Windows papercuts**: `prd_to_sprint.py` needs UNC-resolved paths; every script needs `PYTHONIOENCODING=utf-8`.

The **core discipline is sound and stays** (see §3). The **ceremony around it** is what we cut.

## 2. The intended model (CIO, 2026-06-29)

| Artifact | Role | Detail level |
|---|---|---|
| **Backlog** | The broad idea ledger — *everything*: ideas, bugs, issues, enhancements + notes, dependencies, examples, general thinking. | **Light.** Roughed-in. Not every item fully specified. |
| **PRD** (`prd-V0.X.Y.md`) | The **selected scope, fully detailed**: clarifying questions answered, research performed, examples included. **Peer-reviewed** (Architect + QA) for accuracy. | **Full.** The single detailed source for in-scope items. |
| **Resize** | Make each story concise + well-defined; **split big stories** into sub-stories so Ralph maximizes success. Operates on the PRD. | — |
| **`sprint.json`** | Ralph's executable contract, **reshaped** from the PRD by a robust parser. | Generated, not hand-authored. |

**The pivotal change:** the **full detail lives in the PRD, not the backlog.** This eliminates the triple-authoring. The backlog gets lighter; the PRD is the one place a scoped item is fully specified; Story.md mirrors disappear.

## 3. What we KEEP (the parts that earned their place)

- **Validation-criteria-upfront** — every in-scope story carries **testable outcome** criteria (action → observable result), authored at PRD time (after the clarifying Qs + research that make them crystal-clear). *This* is the actual fix for the V0.27 false-pass cluster (stories passing on "code compiles" instead of "outcome observed"). Non-negotiable.
- **A reviewed, frozen contract before Ralph builds** — Ralph builds to a fixed target; the criteria don't move mid-sprint.
- **Risk-appropriate sign-off** — a load-bearing schema/boot change gets Architect + QA review; see §4.7.

## 4. The changes

### 4.1 Backlog becomes a light idea-ledger (amends PM Rule 5)
Backlog items carry: `id`, `type`, `title`, short `description`/notes, `dependencies`, `examples`/links, `status`, parent Feature/Epic. They **may** carry a rough goal, but **full `goal`/`definitionOfDone`/`validationCriteria`/`conditionalOutcomes` are NOT required at backlog stage** — those are authored at PRD time. Rule 5 changes from "defined in backlog, crystal-clear at PRD" to **"roughed-in at backlog (optional), authored-in-full at PRD (required)."**

**Backlog archival (CIO 2026-06-29):** the backlog is a list of things *to do* — when an item ships, it is **archived out** (to `archive/completed-work-products/`), not retained as a backlog row. The active backlog stays a true to-do list, never a graveyard of done work. (Formalizes + tightens Rule 12 graduation: archive on completion, promptly.)

### 4.2 The PRD is the single detailed source (markdown)
Per CIO decision (2026-06-29): the PRD stays **human-readable markdown** (`offices/pm/prds/prd-V0.X.Y.md`). It carries the full per-story detail in a **defined, parseable convention** (§5). Peer review happens on the markdown (readable). No separate full-detail authoring into `backlog.json`.

### 4.3 Drop Story.md mirrors
`offices/pm/backlog/US-*.md` mirrors duplicate the PRD/`backlog.json` content. **Retire them** for sprint-bound stories. The PRD is the detailed source; the backlog entry is the light ledger row. (Completed-work archival keeps the PRD + the frozen `sprint.json`, which together preserve the full record.)

### 4.4 Harden the reshape parser (`prd_to_sprint.py` v2)
The parser reads the PRD markdown's structured story sections (§5) and emits a **COMPLETE** `sprint.json` in one shot:
- Per-story `goal` / `acceptance` (DoD) / `validationCriteria` / `conditionalOutcomes` / `deps` / `size` / `parent` / `type` — parsed from the PRD, not pulled from `backlog.json`.
- The **full `validation` block**: `validationMethod`, `validatesFeatures`, `currentVersion` read from PRD frontmatter; `validatedAt`/`validatedBy` = null; plus `bigDefinitionOfDone` + `frozenAt` (+ `bigDoDHash` if kept, §4.6).
- **Auto-register `validatesFeatures`** in `regression_manifest.json` (stub entry if absent) instead of the manual side-step.
- **Robustness:** fail loudly with the offending heading/line if a story section doesn't match the convention (no silent partial parse). Resolve its own paths (no UNC/Z: caller burden) and set UTF-8 I/O internally (kills the two recurring papercuts).

### 4.5 Resize operates on the PRD; retire `/resize-sprint`
Sizing is the PM splitting oversized stories **in the PRD** before reshape. The 5-dimension sizing signal is **already produced by `sprint_lint`** (the title/acceptance-count warnings) — so the stale `/resize-sprint` skill is redundant. **Retire it**; replace with: (a) `sprint_lint` warnings as the objective signal, (b) PM judgment to split in the PRD, (c) optionally a tiny `size_check.py` that prints the matrix per story. No `prd.json`/`signOffs`/persona machinery.

### 4.6 DECISION (CIO 2026-06-29): DROP the `bigDoDHash`
**What it did:** SHA-256 of the aggregated `validationCriteria`; `sprint_lint` re-hashed to detect post-freeze edits to the acceptance bar. **Verdict:** it guarded against *silent goalpost-moving after sign-off* — a risk **git already records** (authored, timestamped diffs) and that we have **no evidence ever occurred**. **Dropped.** Replacement controls:
- **git** is the tamper-evident log of any criteria change (who, when, what).
- **`sprint_lint`** keeps the check that each story *has* non-empty, testable `validationCriteria` (action → observable outcome) — the part that actually prevents the false-pass class — and **drops** the freeze-drift hash comparison.
- Net: **no freeze/re-freeze ceremony.** The reshape simply regenerates `sprint.json` from the PRD whenever the PRD changes; `prd_to_sprint.py` v2 stops emitting `bigDoDHash` (+ `frozenAt` becomes a plain `generatedAt`).

### 4.7 Tier the gates by risk
Not every sprint needs the full PM→Architect→QA→resize gauntlet.
- **Load-bearing** (schema/migration, power/shutdown, boot path, tier contracts, vehicle-write): full Architect design-gate + QA + PM sizing. (Unchanged.)
- **Light** (bench-only UI, isolated bug fixes, docs/tooling): PM authors + sizes; Architect/QA review **async / opt-in** (a heads-up, not a blocking round-trip). The PM self-verifies reshape integrity (§4.4 loud-fail parser) rather than gating dispatch on a redundant pass.
- The PM declares the tier in the PRD frontmatter (`reviewTier: load-bearing | light`).

### 4.8 The PM owns fork + freeze (clarify, not change)
Forking the sprint branch and running the reshape are **the PM's job** — not gated on an Architect "permission." The Architect's value is the **PRD review** (substance) and a **design-gate BLOCK** when architecture is at stake; once that's given, freeze/fork/dispatch are PM mechanics.

## 5. PRD markdown convention (what the parser keys on)

Frontmatter (required): `sprint`, `version`, `theme`, `reviewTier`, `validationMethod`, `validatesFeatures` (list), `forksFrom`, `selectedStories` (list of US-ids in build order).

Per-story section (one per story), stable headings the parser anchors on:
```
### US-NNN — <title>   [parent: F-XXX | type: normal|issue|... | size: S|M|L | deps: US-AAA,US-BBB]
- **Goal:** <connextra or gherkin>
- **DoD:** <bullet> / <bullet> / ...
- **ValidationCriteria:**
  - (<testable action>) -> (<observable outcome>)
  - ...
- **ConditionalOutcomes:** <bullet> / ...
```
(This is close to what `prd-V0.29.2.md` already uses — the convention is mostly formalizing current practice so the parser is reliable.)

## 6. End-to-end flow (after this lands)

1. **Capture** → backlog row (light): idea/bug/enhancement + notes/deps/examples.
2. **Scope a sprint** → `/groom-product-requirements` writes the PRD markdown: pull selected backlog rows, ask clarifying Qs, do research, write full per-story detail (§5), set `reviewTier`.
3. **Review** → Architect (+ QA) review the markdown; annotate; design-gate BLOCK only if architecture is at stake.
4. **Resize** → PM splits oversized stories in the PRD (signal = `sprint_lint` sizing warnings).
5. **Reshape** → `prd_to_sprint.py v2` → complete `sprint.json` (+ auto-manifest, + hash if kept). One command.
6. **Dispatch** → PM forks `sprint/sprintN-V0.X.Y`, CIO runs `ralph.sh`.
7. **Close** → `/sprint-deploy-pm` merges to dev; backlog rows graduate; the PRD + frozen sprint.json are the archived record.

**Net deletions vs today:** the separate full-authoring into `backlog.json`, the Story.md mirrors, the manual validation-block hand-adds, the manual manifest registration, the stale `/resize-sprint`, and the UNC/encoding papercuts.

## 7. Implementation slices (proposed E-OPS stories)

- **S1 — `prd_to_sprint.py` v2** (parser reads full PRD detail → complete `sprint.json` + validation block + auto-manifest + self-resolving paths + UTF-8). *Highest ROI; bit me twice this session.*
- **S2 — Retire `/resize-sprint`**; add `size_check.py` (or just lean on `sprint_lint` warnings); update the workflow docs.
- **S3 — Lighten the backlog convention** (amend Rule 5 + `backlog_schema.py`: full per-story fields optional at backlog stage) + stop generating Story.md mirrors.
- **S4 (optional)** — `reviewTier` gating + the one-command re-freeze ergonomics for the hash.

These are PM-tooling stories (tests + the scripts); they can ride a future hygiene sprint, not a sprint that needs Ralph's product focus.

## 8. Decisions (CIO 2026-06-29)

1. **Hash:** **DROP** (§4.6). git + the criteria-present lint check replace it; no freeze/re-freeze ceremony.
2. **Mirrors:** **RETIRE** entirely (§4.3). The PRD is the detailed source; backlog rows are light.
3. **Review tiers:** **CONFIRMED** (§4.7). Load-bearing → full Arch + QA; light (bench UI, isolated bugs, tooling/docs) → Arch/QA **async / opt-in**, not a blocking round-trip.
4. **Backlog archival:** **CONFIRMED** (§4.1). The backlog is a to-do list; completed items archive out promptly (not a graveyard).
5. **Backlog detail floor:** light row = `title + type + notes + deps + examples` (+ optional rough goal); full detail authored at PRD. (Refine during implementation S3.)

## 9. Implementation order (post-decision)
S1 (`prd_to_sprint.py` v2: full-PRD parse → complete `sprint.json`, no hash, auto-manifest, self-resolving paths/UTF-8) → S2 (retire `/resize-sprint`; lean on `sprint_lint` sizing warnings) → S3 (lighten backlog convention + stop Story.md mirrors + prompt-archive-on-complete) → S4 (`reviewTier` gating). All E-OPS hygiene; ride a future tooling sprint, not a Ralph-product sprint.
