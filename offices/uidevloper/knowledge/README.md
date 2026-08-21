# Iris — knowledge index

**Read on demand.** Load the file a situation calls for; do not read the folder.
The charter (`../claude.md`) is the only thing that loads every session.

**Scope boundary (CIO 2026-08-20):** this folder holds **how I work** — the CIO's
preferences toward me, my design-process lessons, my traps. **Project-shared facts live
in shared locations with one version of the truth** and are indexed at the bottom.
Consolidated 2026-08-20: 33 files → 22, with five overlapping verify-patterns merged into
one and all 3D-printing material moved to `docs/3d-printing/`.

---

## Start here — the two that fire most often

| File | Load when |
|---|---|
| `pattern-the-artifact-is-not-the-fact.md` | **Before believing any document, check, template, draft, or earlier measurement.** Five cases, one rule. This is the single most-repeated failure on this project — three data errors in Aug 2026, mine and Spool's alike |
| `feedback-cio-prefers-visual-brainstorming.md` | Any UI work. The CIO reviews **visually** — build a mockup and publish it, don't describe it in prose |

## Working with the CIO

| File | Load when |
|---|---|
| `feedback-cio-prefers-visual-brainstorming.md` | Standing default for UI work (ratified: "100% proceed with using a browser") |
| `feedback-cio-clarifying-questions-always-welcome.md` | Unsure whether to ask — the answer is ask |
| `feedback-cio-architectural-paths-belong-to-atlas.md` | Tempted to specify a path, schema or service name — propose the shape, let Atlas name it |
| `feedback-cio-measures-clearance-from-glass-edge.md` | Any clearance figure he gives — his datum is the **glass**, not the PCB (2.3 mm apart) |
| `feedback-cio-auto-maintains-settings.md` | `settings.local.json` looks reverted — it's deliberate |
| `feedback-tool-upgrades-cio-directs-then-suggest.md` | Considering a tooling change — he directs, I suggest |
| `feedback-brainstorming-stall-nudge-pattern.md` | A brainstorm session stalls |

## Design judgement

| File | Load when |
|---|---|
| `pattern-ui-as-ssot-consumer.md` | Any surface showing a value — I render the SSOT, never invent or re-derive it |
| `feedback-honest-approximate-vs-hide.md` | A value is uncertain — show it honestly-approximate rather than hiding it |
| `pattern-threshold-plus-dwell-for-cycling-signals.md` | Putting an alert band on a live signal — **if it cycles, a bare threshold always nuisance-fires** |
| `pattern-defects-first-existing-artifact-review.md` | Reviewing an existing artifact — surface defects before proposing a redesign |
| `pattern-ground-in-existing-implementation.md` | Starting "new" work — check what's already built first |
| `pattern-destructive-action-defense-in-depth.md` | Designing a destructive control — deliberate gesture + confirm + structural lock |
| `pattern-honor-louder-choice-fold-safety-as-subtreatment.md` | The CIO picks the louder option — honour it, fold the safety in as a sub-treatment |
| `pattern-argus-ui-acceptance-criteria.md` | Writing acceptance criteria — Argus's single-boolean, evidence-survival shape |
| `pattern-css-svg-reverse-animation-fillmode.md` | Reversing a CSS/SVG animation — fill-mode gotcha (a live defect in `splash-shutdown.svg`) |
| `pattern-brand-font-subset-woff2-inline.md` | Producing a brand face — VF → pin weight → subset → woff2 → base64 |

## Hardware + enclosure craft (mine; the printer itself is shared — see below)

| File | Load when |
|---|---|
| `pattern-hardware-measurement-frame-and-datasheet-authority.md` | **Any physical measurement conversation.** Front/back mirroring, Y-symmetric flips, parallax, datasheet-over-shorthand. Cost several review rounds before it was written |
| `project-display-case-design-decisions.md` | Touching enclosure #1 — the decision log behind the current geometry |

## Environment

| File | Load when |
|---|---|
| `pattern-stale-git-index-lock-shared-checkout.md` | `index.lock` blocks a commit — **prove staleness, never `rm`**; use `offices/pm/scripts/index_lock.py` |

---

## Project-shared truth — NOT here, and deliberately so

| Need | Single source |
|---|---|
| 3D printer, materials, slicer profile, print recipes, CLI, printable-geometry rules | **`docs/3d-printing/`** (start at its `README.md`) |
| Pi / UPS / sensor / display hardware specs | `docs/hardware-reference.md` |
| OSOYOO display **mechanical** dimensions (PCB, glass, mount rectangle) | `enclosure1/datasheets/2024009100-extracted-facts.md` — beside the vendor PDF and the scripts that derived them |
| UI tokens (colour, type scale) | `specs/UI/tokens.css` |
| Cross-agent project state | `MEMORY.md` + `offices/pm/projectManager.md` |
| A2AL protocol | `offices/handbook.md` §9 |
