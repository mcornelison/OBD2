# Sweep 1 Complete — Facade Cleanup Merged to Main

**From**: Ralph
**To**: Marcus (PM)
**Date**: 2026-04-13
**Subject**: Structural reorg (B-040) Sweep 1 of 6 — Checkpoint A passed, merged
**Status**: Informational — architecture change summary for PM awareness

---

## TL;DR

Sweep 1 of the 6-sweep structural reorganization is **complete and merged to main** (merge commit `21029e8`). 18 facade files are gone from `src/obd/`, the shutdown subpackage is populated with real logic, and `src/obd/__init__.py` imports from canonical package locations. Zero behavior change — 1517 tests pass, simulator smoke test clean. You don't need to do anything except read this for situational awareness; future sweeps will continue from here.

---

## What changed in Sweep 1

### 1. Shutdown subpackage consolidation
Two 442+1158-line flat files moved into a proper subpackage:
- `src/obd/shutdown_manager.py` → `src/obd/shutdown/manager.py`
- `src/obd/shutdown_command.py` → `src/obd/shutdown/command.py`
- `src/obd/shutdown/__init__.py` — previously an empty placeholder — now re-exports the full public API (22 symbols across both files).

**Implication**: code that needs shutdown symbols now imports from `src.obd.shutdown` (the package), not the flat files. This is behaviorally equivalent; only the import path changes.

### 2. 18 facade files deleted
These were pure re-export shims under `src/obd/` that existed only to forward symbols to canonical locations elsewhere. Sweep 1 rewired every consumer to import from the canonical path, then deleted the shims:

| Deleted flat file | Canonical location (now import from) |
|---|---|
| `src/obd/data_logger.py` | `obd.data` (package) |
| `src/obd/drive_detector.py` | `obd.drive` (package) |
| `src/obd/vin_decoder.py` | `obd.vehicle` (package) |
| `src/obd/static_data_collector.py` | `obd.vehicle` (package) |
| `src/obd/profile_manager.py` | `profile` (top-level package) |
| `src/obd/profile_switcher.py` | `profile` (top-level package) |
| `src/obd/profile_statistics.py` | `analysis` (top-level package) |
| `src/obd/display_manager.py` | `display` (top-level package) |
| `src/obd/adafruit_display.py` | `display.adapters.adafruit` (submodule) |
| `src/obd/alert_manager.py` | `alert` (top-level package) |
| `src/obd/obd_config_loader.py` | `obd.config` (package) — see Option A note below |
| `src/obd/battery_monitor.py` | `power.battery` (submodule) — was orphan |
| `src/obd/power_monitor.py` | `power.power` (submodule) — was orphan |
| `src/obd/calibration_manager.py` | `calibration.manager` (submodule) — was orphan |
| `src/obd/calibration_comparator.py` | `calibration.comparator` (submodule) — was orphan |
| `src/obd/recommendation_ranker.py` | `ai.ranker` (submodule) — was orphan |
| `src/obd/ai_analyzer.py` | `ai.analyzer` (submodule) — was orphan |
| `src/obd/ai_prompt_template.py` | `ai.prompt_template` (submodule) — was orphan |

**2,465 lines deleted.** Eight of the facades were orphans (zero external consumers) and could be deleted outright; the other ten had real consumers that had to be rewired first.

### 3. `src/obd/__init__.py` rewritten
The package's public API (215 symbols in `__all__`) is **unchanged byte-for-byte**. What changed is where those symbols are sourced from — previously they were forwarded through the facade files above; now they are imported directly from canonical packages.

Alphabetized and grouped: relative imports (`.data`, `.database`, `.config`, `.drive`, `.shutdown`, `.vehicle`, etc.) first, then top-level absolute imports (`display`, `alert`, `analysis`) grouped separately. The try/except wrapper for the Adafruit display adapter (non-Pi fallback) is preserved.

### 4. Orchestrator lazy imports rewired
`src/obd/orchestrator.py` has 8 lazy (inside-function) imports that reference facade paths. All 8 were rewritten in Task 6:

| Old lazy import | New lazy import |
|---|---|
| `from .profile_manager import createProfileManagerFromConfig` | `from profile import createProfileManagerFromConfig` |
| `from .profile_manager import createProfileSwitcherFromConfig` | `from profile import createProfileSwitcherFromConfig` |
| `from .vin_decoder import createVinDecoderFromConfig` | `from .vehicle import createVinDecoderFromConfig` |
| `from .display_manager import createDisplayManagerFromConfig` (×2) | `from display import createDisplayManagerFromConfig` |
| `from .drive_detector import createDriveDetectorFromConfig` | `from .drive import createDriveDetectorFromConfig` |
| `from .alert_manager import createAlertManagerFromConfig` | `from alert import createAlertManagerFromConfig` |
| `from .data_logger import createRealtimeLoggerFromConfig` | `from .data import createRealtimeLoggerFromConfig` |

### 5. Seven test files updated
Tests that mocked these lazy imports via `@patch('obd.<facade>.X')` or `sys.modules` dict injections had to retarget to the new canonical paths. Files touched: `test_orchestrator_alerts.py`, `test_orchestrator_data_logging.py`, `test_orchestrator_display.py`, `test_orchestrator_drive_detection.py`, `test_orchestrator_profiles.py`, `test_orchestrator_statistics.py`, `test_orchestrator_vin_decode.py`. `test_obd_config_loader.py` import source updated to use `obd.config` + `obd.config.loader` split.

---

## Option A — `obd_config_loader.py` resolution (CIO-approved)

The Task 2 audit flagged `src/obd/obd_config_loader.py` as **AMBIGUOUS**: it was 871 lines of real implementation (not a facade), and its nominated canonical replacement (`src/obd/config/loader.py`) was only a 584-line subset missing 14 getter functions.

**Mitigating discovery**: all 14 missing symbols **already exist** in other files inside the `obd.config` package:
- 7 in `src/obd/config/helpers.py`
- 7 in `src/obd/config/simulator.py`

And `src/obd/config/__init__.py` re-exports all of them at the package level.

**Resolution (CIO approved 2026-04-13)**: The canonical location is the `obd.config` **package** (not the `loader.py` submodule). Rewire consumers to `from obd.config import (...)` and the existing package `__init__.py` serves the full public API. Zero symbol porting needed — just a plan correction.

Tech debt note at `offices/pm/tech_debt/TD-reorg-sweep1-config-loader-divergence.md` with full detail and the CIO resolution stamp.

---

## Path convention correction

The original plan prescribed `from src.display import ...` / `from src.alert import ...` etc. for top-level packages. **This is wrong for this project** because `tests/conftest.py` puts `src/` itself on `sys.path` (not the project root). The correct form is `from display import ...` without the `src.` prefix.

I discovered this when my initial Task 5 rewrite (using `from src.display`) broke subprocess-spawning tests in `scripts/verify_database.py` — those tests inherit only `src/` on path, so `from src.display` raises `ModuleNotFoundError: No module named 'src'`. The final sweep uses bare-package imports consistently.

**Going forward**: any code in `src/obd/` that needs to reach `display`, `alert`, `analysis`, `profile`, `power`, `calibration`, `ai`, `backup`, `hardware`, or `common` should import without the `src.` prefix. Relative imports within `src/obd/` still use `.config`, `.data`, `.drive`, `.shutdown`, `.vehicle`, etc.

---

## New architecture map (post-sweep-1 canonical import table)

For anyone writing new code or updating PRDs, here's where to find things:

### Top-level packages (imports as `from <package> import ...`)
| Package | Contents |
|---|---|
| `common` | config_validator, secrets_loader, logging_config, error_handler |
| `display` | manager, drivers/, adapters/ (Adafruit etc.) |
| `alert` | manager, thresholds, tiered_thresholds |
| `analysis` | profile_statistics (the statistical analysis for profiles) |
| `profile` | manager, switcher, types |
| `power` | battery, power, monitor |
| `calibration` | manager, comparator, session |
| `ai` | analyzer, ollama/, prompt_template, ranker |
| `backup` | backup_manager, google_drive uploader |
| `hardware` | HardwareManager, UpsMonitor, ShutdownHandler, GpioButton, StatusDisplay |

### `obd` subpackages (imports as `from obd.<subpkg> import ...` OR within obd code as `from .<subpkg> import ...`)
| Subpackage | Contents |
|---|---|
| `obd.config` | loader (with private `_loadConfigFile`, `_validateDisplayMode`, etc.), helpers, simulator |
| `obd.data` | logger, realtime, helpers |
| `obd.drive` | detector, session types |
| `obd.vehicle` | vin_decoder, static_collector, helpers |
| `obd.shutdown` | manager, command (newly consolidated in sweep 1) |
| `obd.service` | service manager, install scripts |
| `obd.simulator` | SimulatedObdConnection, scenario runner |

### `src/obd/` top-level files (still flat, NOT touched by sweep 1)
| File | Purpose |
|---|---|
| `__init__.py` | Package public API (215 symbols) |
| `database.py` | OBD database operations |
| `obd_connection.py` | Real Bluetooth OBD connection |
| `obd_parameters.py` | Parameter definitions and category lookups |
| `orchestrator.py` | Application lifecycle orchestrator (Sweep 5 will split this) |
| `simulator_integration.py` | Glue between real connection and simulator |
| `statistics_engine.py` | Drive statistics calculation |

These were NOT facade files — they contain real logic and stay put. Sweep 5 will address orchestrator.py's size (TD-003).

---

## Test count baseline (do not let this regress)

- **Full suite**: **1517 passed, 1 skipped** (same as pre-sweep baseline `df40ca2`)
- **Fast suite** (`pytest -m "not slow"`): **1499 passed, 19 deselected**

Future sweeps should preserve these counts.

---

## What's still ahead (the other 5 sweeps)

Per the reorg handoff doc at `docs/superpowers/plans/REORG-HANDOFF.md`:

| Sweep | Plan file | Summary |
|---|---|---|
| 2 | `2026-04-12-reorg-sweep2-thresholds.md` | Merge legacy threshold system into tiered |
| 3 | `2026-04-12-reorg-sweep3-tier-split.md` | **Highest risk** — physical tier split (pi/ server/ common/) |
| 4 | `2026-04-12-reorg-sweep4-config.md` | Config restructure (pi/server sections in single config.json) |
| 5 | `2026-04-12-reorg-sweep5-file-sizes.md` | Orchestrator split (TD-003) + 10 other oversized files |
| 6 | `2026-04-12-reorg-sweep6-casing.md` | camelCase + READMEs |

Sweep 2 starts next (no cooling period required for sweep 1 → 2; sweep 3 and 5 have the 24-hour cooling gates).

---

## Parallel-session complication (just informational)

During Sweep 1 execution, you (Marcus) were running a parallel PM session and committed two documents to both `main` and `sprint/reorg-sweep1-facades`:
- `d794048` / `1bfcb86` — "Draft PRD for infrastructure pipeline MVP"
- `0bac58b` / `99320c9` — "Session 14 closeout"

These commits touched only docs/PM files and did not conflict with the sweep work. However, your session did `git checkout main` between commits, which caused my Ralph session to briefly end up on `main` with sweep-branch-style edits as uncommitted changes. I recovered via `git stash` + `git checkout sprint/...` + `git stash pop`, and all work is intact.

**For future parallel PM↔Ralph work**: when Ralph is on a sprint branch, please avoid `git checkout main` within that shell — it flips Ralph's working tree too. If you need to work on main while Ralph is sprinting, open a second shell or use a worktree. No data loss happened this time, but the save-and-recover dance cost ~5 minutes.

---

## Tech debt filed during Sweep 1

1. `TD-reorg-sweep1-config-loader-divergence.md` — RESOLVED via Option A approval. No further action needed.

## Tech debt NOT yet filed (recommendations for post-sweep cleanup)

1. **`src/obd/__init__.py` import ordering** — ruff auto-fixed the I001 errors during Task 8, but the overall grouping could be cleaner (relatives before absolutes, alphabetized). Low priority.
2. **`src/obd/display_manager.py` line 46** used to contain `from display.drivers import ...` (unqualified) — that file is now deleted, so the issue is moot.
3. **Pre-existing ruff warnings** in `src/ai/ollama.py` (UP041 — `socket.timeout` should be `TimeoutError`) and `tests/test_remote_ollama.py` (UP041, F841, I001) — out of sweep 1 scope, predate the reorg.

---

## What you need to do

**Nothing right now.** This note is for situational awareness only. If you update PRDs, backlog items, or docs that reference old facade paths (e.g., `from obd.data_logger import ObdDataLogger`), update them to canonical paths per the table above. Any such references would be stale but not breaking — the public API via `from obd import ObdDataLogger` still works.

For the PRD draft you already queued (`prd-infrastructure-pipeline-mvp.md` with 12 TBD markers pending reorg completion), you can now fill in the sweep-1-related TBDs using the canonical paths from the architecture map section above. Sweeps 2-6 will move things further, so some TBDs should wait until the full reorg lands (roughly after Sweep 3, when the Pi/Server tier split is complete).

---

## Commits on main from this sweep

Baseline: `df40ca2`
Sweep 1 merge commit: `21029e8`

Sweep-specific commits (now part of main history):
- `7be6de5` chore: sweep 1 audit notes _(scratch, later deleted)_
- `2c64380` docs: TD-reorg-sweep1-config-loader — Option A approved
- `0718427` refactor: consolidate shutdown into subpackage (task 3)
- `f931424` refactor: rewire obd_config_loader consumers (task 4)
- `670bae4` refactor: rewrite src/obd/__init__.py canonical imports (task 5)
- `0bf2836` refactor: rewire orchestrator lazy imports + test patches (task 6)
- `2ef3d99` refactor: delete 18 facade files (task 7)
- `e7d95ca` refactor: ruff I001 autofix + scratch cleanup (task 8)
- `95977d3` docs: sweep 1 status update — Checkpoint A passed (task 9)
- `21029e8` Merge sprint/reorg-sweep1-facades

---

End of Sweep 1 report. Ready to continue with Sweep 2 whenever the CIO greenlights.
