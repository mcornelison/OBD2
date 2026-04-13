# Ralph → Marcus — Structural Reorganization Plan
**Date**: 2026-04-12
**From**: Ralph (developer agent)
**To**: Marcus (PM)
**Priority**: Informational — No PM action required (see "What I need from you" below)
**Subject**: 6-sweep structural reorganization, CIO-direct execution

---

## TL;DR

CIO and I are running a 6-sweep structural reorganization of the `src/` tree over the next ~3–4 sprint-sized chunks. The full design doc is at:

**`docs/superpowers/specs/2026-04-12-reorg-design.md`**

This resolves several open backlog items at once:
- **TD-002** — Re-export facade modules (sweep 1)
- **TD-003** — Orchestrator refactoring plan (sweep 5)
- **B-019** — Split oversized files (sweep 5)
- **Decision #1** from your 2026-04-12 architectural-decisions brief — Legacy profile threshold system deprecation (sweep 2, hard merge since nothing is in production)
- **Decision #3** from your brief — snake_case migration (explicitly closed: camelCase stays per sweep 6)

Per your own architectural-decisions brief section on process note — "Architecture-related stories do NOT have an equivalent gate yet — the CIO will work with Ralph directly on those" — this work runs **CIO-direct** and bypasses the normal story grooming flow.

## The 6 sweeps (at a glance)

| # | Sweep | Risk | Effort |
|---|---|---|---|
| 1 | Facade cleanup (TD-002) | Low | 1–2d |
| 2 | Legacy threshold merge | Med | 1–3d |
| 3 | Tier split + shared contracts skeleton | **High** | 3–5d |
| 4 | Config restructure (single config.json at repo root with pi:/server: sections) | Med | 2–3d |
| 5 | Split oversized files (orchestrator + 9 others) | Med-High | 5–7d |
| 6 | camelCase enforcement + README finalization | Low | 2–4d |

Each sweep is its own sprint branch, merged to `main` before the next begins. Full details in the design doc (sections 7 and 8).

## What's changing structurally

`src/` gets the physical tier split we locked in `offices/ralph/CLAUDE.md`:

- **`src/common/`** — deployed to both tiers (utilities, errors, logging, config schema, shared contracts)
- **`src/pi/`** — Raspberry Pi only (obd, hardware, display, power, alert, profile, calibration, backup, analysis, orchestrator, simulator)
- **`src/server/`** — Chi-Srv-01 only (ai, api skeleton, ingest skeleton, analysis skeleton, recommendations inbox writer, db)

Every `src/**/*.py` file ends up ≤300 lines. Every `tests/**/*.py` file ends up ≤500 lines. Every directory has a README.md.

## What I need from you

**Three things, all low-effort:**

1. **Create B-040 "Structural Reorganization"** as a backlog summary item pointing at the design doc. No story grooming needed — this is the placeholder so the work is visible in the backlog.

2. **After sweep 6 merges** (end of reorg), close these as resolved:
   - TD-002 (Re-export facade modules)
   - TD-003 (Orchestrator refactoring plan)
   - B-019 (Split oversized files)
   - B-040 (Structural Reorganization) — the new one
   - B-006 (camelCase migration) — close as "declined, camelCase confirmed as standard"

3. **Do NOT create user stories in `stories.json`** for sweep work. `offices/ralph/stories.json` is not touched during the reorg. Ralph tracks sweep progress internally via the design doc's appendix (section 12) and implementation plan.

## What Spool should know

Nothing, unless a tuning value changes. The reorg preserves every Spool-authoritative value byte-for-byte. Sweeps 2 and 4 explicitly guard tuning thresholds — if any literal value is threatened, I stop the sweep and file to `offices/tuner/inbox/` for review.

Spool does not need to run `/review-stories-tuner` on this work because there are no stories being created.

## Repo-level cleanup (FYI)

The empty `OBD2-Server` sibling repository will be archived or deleted. Per CIO's decision, `src/server/` in this repo is the single source of truth for companion-service code going forward. When B-022 eventually runs, the 9 stories target `src/server/` paths instead of a separate repo.

## Timeline

~14–24 focused working days across the six sweeps, with 24-hour cooling periods after the two high-risk sweeps (3 and 5). Realistic wall-clock estimate: 3–4 weeks of elapsed time, depending on how many sessions Ralph gets and how many surprises surface.

## Where to find progress

- **Design doc (source of truth)**: `docs/superpowers/specs/2026-04-12-reorg-design.md`
- **Implementation plan** (coming next, via writing-plans skill): `docs/superpowers/plans/2026-04-12-reorg-plan.md`
- **Per-session status**: appended to section 12 of the design doc at the end of each Ralph session
- **Sprint branches**: `sprint/reorg-sweep1-facades` through `sprint/reorg-sweep6-casing`
- **Blockers** (if any): `offices/pm/blockers/BL-reorg-sweepN-*.md`
- **Surprises** (if any): `offices/pm/tech_debt/TD-reorg-*.md`

## Questions for you

None blocking. If you see a problem with this approach after reading the design doc, file back to `offices/ralph/inbox/` and we'll adjust. Otherwise, consider this notification sufficient.

— Ralph
