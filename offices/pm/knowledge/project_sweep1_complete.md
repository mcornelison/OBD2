---
name: Sweep 1 Complete — Facade Cleanup
description: B-040 structural reorg Sweep 1 of 6 merged to main 2026-04-13. 18 facades deleted, shutdown consolidated, __init__.py rewritten, baseline preserved at 1517 tests.
type: project
originSessionId: 38c42a69-5943-4b0e-a31a-94918ffa988b
---
# Sweep 1 — COMPLETE, merged to main 2026-04-13

## State
- **Merge commit**: `21029e8` on main
- **Baseline preserved**: 1517 full-suite passing, 1499 fast-suite (exact df40ca2 match)
- **Branch retained**: `sprint/reorg-sweep1-facades` — do NOT delete until after Sweep 2 merges (plan rule)
- **Not pushed** to origin (main is 8 commits ahead; CIO has not requested push)

**Why:** CIO approved Sweep 1 execution and merge. Completed in one session with parallel PM activity on the same repo. Architecture is now cleaner but still in the flat pre-tier-split layout.

**How to apply:** When a new session asks about the reorg status, Sweep 1 is DONE. The next sweep is Sweep 2 (legacy threshold merge). Start Sweep 2 from `docs/superpowers/plans/2026-04-12-reorg-sweep2-thresholds.md` after CIO greenlight. Do not re-do any Sweep 1 work.

## What Sweep 1 delivered
1. Deleted 18 flat facade files under `src/obd/` (2,465 lines removed)
2. Moved `shutdown_manager.py` + `shutdown_command.py` into `src/obd/shutdown/` subpackage
3. Rewrote `src/obd/__init__.py` to import from canonical packages (no facade references)
4. Rewired 8 lazy imports in `src/obd/orchestrator.py` + 7 test files' @patch targets
5. Rewired 3 other consumers of `obd_config_loader` (simulator_integration, obd_connection, test_obd_config_loader) via Option A

## Option A decision (CIO-approved)
The plan nominated `src/obd/config/loader.py` as the canonical for `obd_config_loader.py`, but `loader.py` was missing 14 getter functions that actually live in `config/helpers.py` and `config/simulator.py`. **Resolution**: canonical is the `obd.config` **package**, not the `loader.py` submodule. Import consumers as `from obd.config import ...` and the package `__init__.py` serves the full public API. Zero symbol porting needed — it was a plan correction, not a code migration.

Tech debt note at `offices/pm/tech_debt/TD-reorg-sweep1-config-loader-divergence.md` documents the resolution.

## Remaining 5 sweeps
| Sweep | Plan file | Risk |
|---|---|---|
| 2 | `docs/superpowers/plans/2026-04-12-reorg-sweep2-thresholds.md` | Low — legacy threshold merge |
| 3 | `docs/superpowers/plans/2026-04-12-reorg-sweep3-tier-split.md` | **HIGH** — physical Pi/server/common tier split + 24h cooling |
| 4 | `docs/superpowers/plans/2026-04-12-reorg-sweep4-config.md` | Medium — config restructure |
| 5 | `docs/superpowers/plans/2026-04-12-reorg-sweep5-file-sizes.md` | **HIGH** — orchestrator split + 24h cooling |
| 6 | `docs/superpowers/plans/2026-04-12-reorg-sweep6-casing.md` | Low — casing + READMEs |

## PM inbox note
Full architecture change summary for Marcus at `offices/pm/inbox/2026-04-13-from-ralph-sweep1-complete.md` (committed as `f97afa3`).
