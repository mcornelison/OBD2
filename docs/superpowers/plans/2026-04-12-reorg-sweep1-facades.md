# Sweep 1 — Facade Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete every file-level facade shim in `src/obd/`, consolidate the shutdown trio into a proper subpackage, and rewrite `src/obd/__init__.py` to import directly from canonical locations. Zero behavior change. All tests green.

**Architecture:** The current codebase has ~19 flat `.py` files under `src/obd/` that exist only to re-export symbols from proper subpackages (e.g., `src/obd/data_logger.py` re-exports from `src/obd/data/logger.py`). Some of them are pure facades; two (`shutdown_manager.py`, `shutdown_command.py`) contain real logic that was never moved into its empty `shutdown/` subpackage; one (`obd_config_loader.py`) may be the original implementation with a parallel `config/loader.py`. This plan audits each, resolves the ambiguous cases, rewrites the single upstream consumer (`src/obd/__init__.py`), and deletes the flat files.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy, git on Windows (MINGW64_NT). No new dependencies.

**Design doc**: `docs/superpowers/specs/2026-04-12-reorg-design.md` — read section 7 (sweep 1) before starting.

**Estimated effort:** 1–2 days of focused work.

**Exit criteria:**
1. `src/obd/__init__.py` imports directly from canonical subpackage locations (no facade files referenced)
2. Every facade file listed in section 6 of the design doc is deleted
3. `src/obd/shutdown/` is a proper subpackage containing the real shutdown logic
4. All tests green (`pytest tests/` passes, including slow tests)
5. `grep -rn "from obd\.data_logger\|from obd\.drive_detector\|..." src tests` returns zero non-docstring hits
6. PR merged to `main`
7. Design doc session log appendix updated with Checkpoint A status

---

## Task 1: Setup — Create sweep branch, tag baseline, verify starting state

**Files:**
- No file changes in this task

- [ ] **Step 1: Confirm you are on a clean main**

Run:
```bash
cd Z:/o/OBD2v2
git status
git branch --show-current
```
Expected: branch is `main`, working tree is clean (or only has unrelated `.claude/settings.local.json` noise that won't interfere).

If the tree has real uncommitted changes, stop and surface to CIO.

- [ ] **Step 2: Tag the pre-reorg baseline for nuclear rollback**

Run:
```bash
cd Z:/o/OBD2v2
git tag reorg-baseline
git tag --list reorg-baseline
```
Expected: `reorg-baseline` printed. This tag is the safety net referenced in design doc section 8.4.

- [ ] **Step 3: Create and check out the sweep 1 branch**

Run:
```bash
cd Z:/o/OBD2v2
git checkout -b sprint/reorg-sweep1-facades main
git branch --show-current
```
Expected: output is `sprint/reorg-sweep1-facades`.

- [ ] **Step 4: Verify starting test suite is green**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x --tb=short -q 2>&1 | tail -20
```
Expected: final line shows `passed` (some number like `408 passed`). If any test fails on the clean main, stop and surface to CIO — the sweep cannot start on a red baseline.

- [ ] **Step 5: Record the baseline test count**

Read the output of step 4 and note the exact number of passing tests. Write it down in this plan (replace `NNN` below):

```
Baseline: NNN tests passing on main at commit <short-sha>
```

This number must not drop by the end of sweep 1.

---

## Task 2: Audit phase — Classify every facade file

**Goal of this task:** For each of the 19 files the design doc marks for deletion, read it and classify it into one of three buckets:
- **Pure facade**: contains only `from .X import Y` statements and docstrings. Safe to delete after rewriting `__init__.py`.
- **Has real logic**: contains actual implementation. Cannot be deleted without moving the logic first.
- **Ambiguous / drifted**: has extra logic on top of re-exports, or exports something the canonical file doesn't. Needs case-by-case resolution.

**Files to audit** (19 flat files + 3 shutdown files + 2 for obd_config_loader comparison):

- Create: `docs/superpowers/plans/sweep1-audit-notes.md` (scratch file; will be deleted at sweep end)
- Read: `src/obd/data_logger.py`, `src/obd/drive_detector.py`, `src/obd/vin_decoder.py`, `src/obd/static_data_collector.py`, `src/obd/profile_statistics.py`, `src/obd/profile_manager.py`, `src/obd/profile_switcher.py`, `src/obd/alert_manager.py`, `src/obd/battery_monitor.py`, `src/obd/power_monitor.py`, `src/obd/calibration_manager.py`, `src/obd/calibration_comparator.py`, `src/obd/recommendation_ranker.py`, `src/obd/ai_analyzer.py`, `src/obd/ai_prompt_template.py`, `src/obd/display_manager.py`, `src/obd/adafruit_display.py`, `src/obd/obd_config_loader.py`, `src/obd/shutdown_manager.py`, `src/obd/shutdown_command.py`
- Read: `src/obd/shutdown/__init__.py`, `src/obd/config/loader.py` (for comparison)

- [ ] **Step 1: Create audit notes scratch file**

Create `docs/superpowers/plans/sweep1-audit-notes.md`:

```markdown
# Sweep 1 Audit Notes (scratch — deleted before merge)

Classification per file: PURE / LOGIC / AMBIGUOUS
Symbols exported, and canonical location if applicable.
```

- [ ] **Step 2: Audit `src/obd/data_logger.py`**

Read the entire file. For each symbol in its `__all__` list (or top-level names), verify the symbol is importable from `src/obd/data/logger.py` or `src/obd/data/realtime.py`.

Run this to see both files' top-level symbols:
```bash
cd Z:/o/OBD2v2
python -c "import src.obd.data_logger as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.obd.data.logger as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.obd.data.realtime as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
```

Expected outcome: every symbol visible via `data_logger` is also visible via `data.logger` or `data.realtime`. If anything is missing from the canonical, classify as AMBIGUOUS and note the missing symbol.

Write classification and symbol list in `sweep1-audit-notes.md`:
```
## src/obd/data_logger.py
- Classification: PURE (or AMBIGUOUS — missing symbol X)
- Canonical: src/obd/data/logger.py + src/obd/data/realtime.py
- Symbols: [ObdDataLogger, LoggedReading, ...]
```

- [ ] **Step 3: Audit `src/obd/drive_detector.py`**

Same procedure as step 2. Canonical location: `src/obd/drive/detector.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.drive_detector as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.obd.drive.detector as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
```

Write classification to `sweep1-audit-notes.md` under a `## src/obd/drive_detector.py` heading.

- [ ] **Step 4: Audit `src/obd/vin_decoder.py`**

Canonical: `src/obd/vehicle/vin_decoder.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.vin_decoder as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.obd.vehicle.vin_decoder as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
```

Write classification.

- [ ] **Step 5: Audit `src/obd/static_data_collector.py`**

Canonical: `src/obd/vehicle/static_collector.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.static_data_collector as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.obd.vehicle.static_collector as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
```

Write classification.

- [ ] **Step 6: Audit `src/obd/profile_statistics.py`**

Canonical: `src/analysis/profile_statistics.py` (note: different top-level package).

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.profile_statistics as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.analysis.profile_statistics as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
```

Write classification.

- [ ] **Step 7: Audit `src/obd/profile_manager.py`**

Canonical: `src/profile/manager.py`. Note: this facade is NOT imported by `src/obd/__init__.py`, so it may be an orphan.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.profile_manager as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.profile.manager as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
```

Also check who imports it:
```bash
cd Z:/o/OBD2v2
grep -rn "from src\.obd\.profile_manager\|from obd\.profile_manager\|import.*obd\.profile_manager" src tests 2>/dev/null
```

Write classification and whether it's an orphan (zero external references) to `sweep1-audit-notes.md`.

- [ ] **Step 8: Audit `src/obd/profile_switcher.py`**

Canonical: `src/profile/switcher.py`. Same procedure as step 7 (may be orphan).

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.profile_switcher as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.profile.switcher as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
grep -rn "from src\.obd\.profile_switcher\|from obd\.profile_switcher\|import.*obd\.profile_switcher" src tests 2>/dev/null
```

Write classification.

- [ ] **Step 9: Audit `src/obd/alert_manager.py`**

Canonical: `src/alert/manager.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.alert_manager as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.alert.manager as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
```

Write classification.

- [ ] **Step 10: Audit `src/obd/battery_monitor.py`**

Canonical: `src/power/battery.py`. Likely orphan — not in `src/obd/__init__.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.battery_monitor as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.power.battery as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
grep -rn "from src\.obd\.battery_monitor\|from obd\.battery_monitor" src tests 2>/dev/null
```

Write classification.

- [ ] **Step 11: Audit `src/obd/power_monitor.py`**

Canonical: `src/power/power.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.power_monitor as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.power.power as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
grep -rn "from src\.obd\.power_monitor\|from obd\.power_monitor" src tests 2>/dev/null
```

Write classification.

- [ ] **Step 12: Audit `src/obd/calibration_manager.py`**

Canonical: `src/calibration/manager.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.calibration_manager as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.calibration.manager as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
grep -rn "from src\.obd\.calibration_manager\|from obd\.calibration_manager" src tests 2>/dev/null
```

Write classification.

- [ ] **Step 13: Audit `src/obd/calibration_comparator.py`**

Canonical: `src/calibration/comparator.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.calibration_comparator as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.calibration.comparator as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
grep -rn "from src\.obd\.calibration_comparator\|from obd\.calibration_comparator" src tests 2>/dev/null
```

Write classification.

- [ ] **Step 14: Audit `src/obd/recommendation_ranker.py`**

Canonical: `src/ai/ranker.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.recommendation_ranker as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.ai.ranker as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
grep -rn "from src\.obd\.recommendation_ranker\|from obd\.recommendation_ranker" src tests 2>/dev/null
```

Write classification.

- [ ] **Step 15: Audit `src/obd/ai_analyzer.py`**

Canonical: `src/ai/analyzer.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.ai_analyzer as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.ai.analyzer as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
grep -rn "from src\.obd\.ai_analyzer\|from obd\.ai_analyzer" src tests 2>/dev/null
```

Write classification.

- [ ] **Step 16: Audit `src/obd/ai_prompt_template.py`**

Canonical: `src/ai/prompt_template.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.ai_prompt_template as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.ai.prompt_template as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
grep -rn "from src\.obd\.ai_prompt_template\|from obd\.ai_prompt_template" src tests 2>/dev/null
```

Write classification.

- [ ] **Step 17: Audit `src/obd/display_manager.py`**

Canonical: `src/display/manager.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.display_manager as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.display.manager as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
```

Write classification.

- [ ] **Step 18: Audit `src/obd/adafruit_display.py`**

Canonical: `src/display/adapters/adafruit.py`.

```bash
cd Z:/o/OBD2v2
python -c "import src.obd.adafruit_display as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.display.adapters.adafruit as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
```

Note: this module uses a try/except ImportError wrapper for non-Pi platforms. The canonical must preserve that behavior. Write classification, and flag if the canonical does not have the try/except wrapper.

- [ ] **Step 19: Audit `src/obd/obd_config_loader.py` vs `src/obd/config/loader.py`**

This is the most important audit because both files appear to be real implementations with overlapping but not-identical exports.

Read both files fully. Compare their public symbols:
```bash
cd Z:/o/OBD2v2
python -c "import src.obd.obd_config_loader as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
python -c "import src.obd.config.loader as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
```

Compare line counts:
```bash
cd Z:/o/OBD2v2
wc -l src/obd/obd_config_loader.py src/obd/config/loader.py
```

**Decision tree:**
- If both files are byte-identical (check with `diff src/obd/obd_config_loader.py src/obd/config/loader.py`): canonical is `config/loader.py`, flat file is a duplicate. Classify PURE-DUPLICATE.
- If `config/loader.py` contains everything `obd_config_loader.py` contains (and more): canonical is `config/loader.py`. Classify `obd_config_loader.py` as SUPERSEDED.
- If `obd_config_loader.py` has symbols missing from `config/loader.py`: classify AMBIGUOUS and stop. File a tech-debt note, surface to CIO, do not delete.

Write the classification and the decision in `sweep1-audit-notes.md`. If classification is AMBIGUOUS, also create:

File: `offices/pm/tech_debt/TD-reorg-sweep1-config-loader-divergence.md`
```markdown
# TD: obd_config_loader.py diverges from config/loader.py

**Discovered during sweep 1 audit (2026-04-12)**

Symbols in `src/obd/obd_config_loader.py` but NOT in `src/obd/config/loader.py`:
- [list the symbols]

**Status**: Sweep 1 blocked. The canonical replacement must be reconciled before the flat file can be deleted.

**Suggested resolution**: [describe — e.g., port missing symbols into `config/loader.py`]
```

- [ ] **Step 20: Audit shutdown trio**

Read all three files:
- `src/obd/shutdown_manager.py` (442 lines, real logic)
- `src/obd/shutdown_command.py` (1158 lines, real logic)
- `src/obd/shutdown/__init__.py` (26 lines — currently an empty subpackage placeholder)

Confirm that `src/obd/shutdown/__init__.py` does NOT define `ShutdownManager`, `ShutdownCommand`, or any of the symbols currently in the two flat files. Run:
```bash
cd Z:/o/OBD2v2
python -c "import src.obd.shutdown as m; print(sorted([n for n in dir(m) if not n.startswith('_')]))"
```

Expected: output is minimal (just module-level dunders). This confirms the shutdown subpackage is an empty placeholder that needs to receive the two flat files' contents.

Classification:
- `src/obd/shutdown_manager.py`: LOGIC (needs to move into `shutdown/manager.py`)
- `src/obd/shutdown_command.py`: LOGIC (needs to move into `shutdown/command.py`)
- `src/obd/shutdown/__init__.py`: PLACEHOLDER (needs to be rewritten as a re-exporter)

Write this to `sweep1-audit-notes.md`.

- [ ] **Step 21: Summarize audit — how many files of each classification**

Review `sweep1-audit-notes.md` and summarize at the top:
```
## Audit summary
- PURE facades (safe to delete after __init__.py rewrite): N files
- LOGIC (need migration before delete): 2 files (shutdown_manager, shutdown_command)
- SUPERSEDED/DUPLICATE: N files
- AMBIGUOUS (blockers): N files
- ORPHANS (not imported anywhere): N files
```

If AMBIGUOUS count > 0, stop here and surface to CIO. Do not proceed to task 3 until each AMBIGUOUS is resolved (typically by porting missing symbols to the canonical file, which may be out of scope for sweep 1 — in which case, the facade stays for now and gets addressed in a follow-up).

- [ ] **Step 22: Commit audit notes**

Run:
```bash
cd Z:/o/OBD2v2
git add docs/superpowers/plans/sweep1-audit-notes.md
git status
git commit -m "chore: sweep 1 audit notes"
```

Expected: one commit on `sprint/reorg-sweep1-facades`.

---

## Task 3: Shutdown consolidation — Move real logic into subpackage

**Goal:** Move the contents of `src/obd/shutdown_manager.py` and `src/obd/shutdown_command.py` into the previously-empty `src/obd/shutdown/` subpackage, so later tasks can delete the flat files.

**Files:**
- Create: `src/obd/shutdown/manager.py`
- Create: `src/obd/shutdown/command.py`
- Modify: `src/obd/shutdown/__init__.py`
- Delete (later in task 7): `src/obd/shutdown_manager.py`, `src/obd/shutdown_command.py`

**Important:** These files contain real logic (442 + 1158 lines), not re-export shims. Treat this like a move, not a delete.

- [ ] **Step 1: Move shutdown_manager.py into the subpackage via git mv**

Run:
```bash
cd Z:/o/OBD2v2
git mv src/obd/shutdown_manager.py src/obd/shutdown/manager.py
git status
```

Expected: git shows a rename from `src/obd/shutdown_manager.py` to `src/obd/shutdown/manager.py`.

- [ ] **Step 2: Update file header in manager.py**

Read: `src/obd/shutdown/manager.py`
Change the `# File Name:` line in the header block from `shutdown_manager.py` to `manager.py`.

Find:
```python
# File Name: shutdown_manager.py
```
Replace with:
```python
# File Name: manager.py
```

- [ ] **Step 3: Check for internal relative imports that broke**

The file may contain imports like `from .some_other_obd_module import X`. Those are one directory deeper now.

Run:
```bash
cd Z:/o/OBD2v2
grep -n "^from \." src/obd/shutdown/manager.py
grep -n "^from src\." src/obd/shutdown/manager.py
```

If you see any `from .X import ...` where `X` is a sibling of the OLD location (a module in `src/obd/`), rewrite it as `from ..X import ...` (go up one directory) in the NEW location.

Example: if the old file had `from .database import ObdDatabase`, rewrite to `from ..database import ObdDatabase` because `src/obd/database.py` is now one directory up from `src/obd/shutdown/manager.py`.

Leave `from .types` or similar references to sibling files within `src/obd/shutdown/` unchanged (if any).

- [ ] **Step 4: Verify shutdown_manager imports still resolve**

Run:
```bash
cd Z:/o/OBD2v2
python -c "from src.obd.shutdown.manager import ShutdownManager, createShutdownManager, installGlobalShutdownHandler; print('OK')"
```

Expected: prints `OK`. If `ImportError`, fix the imports in `manager.py` and retry.

- [ ] **Step 5: Move shutdown_command.py into the subpackage**

Run:
```bash
cd Z:/o/OBD2v2
git mv src/obd/shutdown_command.py src/obd/shutdown/command.py
git status
```

Expected: git shows a rename.

- [ ] **Step 6: Update file header in command.py**

Read: `src/obd/shutdown/command.py`
Find:
```python
# File Name: shutdown_command.py
```
Replace with:
```python
# File Name: command.py
```

- [ ] **Step 7: Fix relative imports in command.py**

Same procedure as step 3. Run:
```bash
cd Z:/o/OBD2v2
grep -n "^from \." src/obd/shutdown/command.py
grep -n "^from src\." src/obd/shutdown/command.py
```

Rewrite any `from .X` referencing siblings that are now one level up to `from ..X`.

- [ ] **Step 8: Verify shutdown_command imports still resolve**

Run:
```bash
cd Z:/o/OBD2v2
python -c "from src.obd.shutdown.command import ShutdownCommand, ShutdownState, GpioButtonTrigger; print('OK')"
```

Expected: prints `OK`.

- [ ] **Step 9: Rewrite `src/obd/shutdown/__init__.py` as a re-exporter**

Read: `src/obd/shutdown/__init__.py`

Replace the entire file content with:

```python
################################################################################
# File Name: __init__.py
# Purpose/Description: Shutdown subpackage for graceful shutdown handling
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-04-12    | Ralph Agent  | Sweep 1: consolidate shutdown_manager and shutdown_command
# ================================================================================
################################################################################
"""
Shutdown Subpackage.

Contains shutdown handling components:
- Shutdown manager (manager.py)
- Shutdown command execution (command.py)
"""

from .command import (
    SHUTDOWN_REASON_GPIO_BUTTON,
    SHUTDOWN_REASON_LOW_BATTERY,
    SHUTDOWN_REASON_MAINTENANCE,
    SHUTDOWN_REASON_SYSTEM,
    SHUTDOWN_REASON_USER_REQUEST,
    GpioButtonTrigger,
    GpioNotAvailableError,
    ProcessNotFoundError,
    ShutdownCommand,
    ShutdownCommandError,
    ShutdownConfig,
    ShutdownResult,
    ShutdownState,
    ShutdownTimeoutError,
    createShutdownCommandFromConfig,
    generateGpioTriggerScript,
    generateShutdownScript,
    isGpioAvailable,
    sendShutdownSignal,
)
from .manager import (
    ShutdownManager,
    createShutdownManager,
    installGlobalShutdownHandler,
)

__all__ = [
    # Shutdown Manager
    "ShutdownManager",
    "createShutdownManager",
    "installGlobalShutdownHandler",
    # Shutdown Command
    "ShutdownCommand",
    "ShutdownConfig",
    "ShutdownResult",
    "ShutdownState",
    "ShutdownCommandError",
    "ProcessNotFoundError",
    "ShutdownTimeoutError",
    "GpioNotAvailableError",
    "GpioButtonTrigger",
    "generateShutdownScript",
    "generateGpioTriggerScript",
    "createShutdownCommandFromConfig",
    "isGpioAvailable",
    "sendShutdownSignal",
    "SHUTDOWN_REASON_USER_REQUEST",
    "SHUTDOWN_REASON_GPIO_BUTTON",
    "SHUTDOWN_REASON_LOW_BATTERY",
    "SHUTDOWN_REASON_MAINTENANCE",
    "SHUTDOWN_REASON_SYSTEM",
]
```

**Important**: verify the exact symbol list matches what `src/obd/__init__.py` currently imports from `.shutdown_manager` and `.shutdown_command` (lines 116-120 and 228-248 in `src/obd/__init__.py`). If any symbol is missing from the list above, add it. If any symbol in the list is missing from the source files, remove it.

- [ ] **Step 10: Verify the subpackage public API is complete**

Run:
```bash
cd Z:/o/OBD2v2
python -c "from src.obd.shutdown import ShutdownManager, ShutdownCommand, ShutdownState, createShutdownManager, createShutdownCommandFromConfig; print('OK')"
```

Expected: `OK`. If any symbol fails to import, fix `__init__.py` re-exports.

- [ ] **Step 11: Run the fast test suite**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -20
```

Expected: same number of tests passing as the baseline. If red, fix before committing.

**Note**: Tests at this point may still import from `src.obd.shutdown_manager` and `src.obd.shutdown_command` paths (the OLD flat files). But those old files are gone now, which means the tests would break unless they import via `src.obd` (package) or the new `src.obd.shutdown` subpackage. If any tests are red with `ModuleNotFoundError` for the flat shutdown modules, they need their imports updated — do that now as part of this task:

```bash
cd Z:/o/OBD2v2
grep -rln "from src\.obd\.shutdown_manager\|from src\.obd\.shutdown_command\|from obd\.shutdown_manager\|from obd\.shutdown_command" tests src 2>/dev/null
```

For each file returned, replace:
- `from src.obd.shutdown_manager import X` → `from src.obd.shutdown import X`
- `from src.obd.shutdown_command import X` → `from src.obd.shutdown import X`
- `from obd.shutdown_manager import X` → `from obd.shutdown import X`
- `from obd.shutdown_command import X` → `from obd.shutdown import X`

Then rerun the test command above until green.

- [ ] **Step 12: Commit the shutdown consolidation**

Run:
```bash
cd Z:/o/OBD2v2
git add -A
git status
git commit -m "refactor: consolidate shutdown into subpackage (sweep 1, task 3)

Move shutdown_manager.py into shutdown/manager.py
Move shutdown_command.py into shutdown/command.py
Populate shutdown/__init__.py with re-exports
Update any tests importing old flat paths"
```

Expected: commit succeeds, git status is clean.

---

## Task 4: Resolve obd_config_loader.py vs config/loader.py

**Goal:** Determine which of the two config-loader files is canonical, migrate any missing symbols, and prepare to delete the flat file.

**Files:**
- Audit-dependent: `src/obd/obd_config_loader.py`, `src/obd/config/loader.py`
- Potentially modify: `src/obd/config/loader.py`, `tests/test_obd_config_loader.py`

- [ ] **Step 1: Re-read the audit note for obd_config_loader**

Open `docs/superpowers/plans/sweep1-audit-notes.md` and find the entry for `src/obd/obd_config_loader.py`. Confirm the classification.

- [ ] **Step 2: If classification is PURE-DUPLICATE or SUPERSEDED, proceed to step 6**

If the files are byte-identical or `config/loader.py` is a superset, no migration needed. Skip to step 6.

- [ ] **Step 3: If classification is AMBIGUOUS, stop and surface to CIO**

Per the audit task (Task 2, Step 19), an AMBIGUOUS classification should already have produced `offices/pm/tech_debt/TD-reorg-sweep1-config-loader-divergence.md`. Verify that file exists:

```bash
cd Z:/o/OBD2v2
ls offices/pm/tech_debt/TD-reorg-sweep1-config-loader-divergence.md
```

Expected: file exists. Do not proceed until CIO decides the resolution.

- [ ] **Step 4: If CIO approves migration, port missing symbols to config/loader.py**

For each symbol listed as "missing from config/loader.py" in the tech-debt file:
1. Read the symbol's definition in `src/obd/obd_config_loader.py`
2. Copy the definition (function, class, or constant) into `src/obd/config/loader.py`, placed logically (e.g., near similar helpers)
3. If the symbol depends on another symbol in `obd_config_loader.py` that isn't in `config/loader.py` yet, port that too (recursively)
4. Do NOT change the symbol's behavior — this is a pure copy

- [ ] **Step 5: Verify the port is symmetric**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import src.obd.obd_config_loader as a; import src.obd.config.loader as b; missing = set(dir(a)) - set(dir(b)) - {'__' + n + '__' for n in ['name','file','loader','spec','path','doc','package','builtins']}; print('Missing from config/loader.py:', [n for n in missing if not n.startswith('_')])"
```

Expected: output is `Missing from config/loader.py: []`.

If the list is non-empty, repeat step 4 for the remaining symbols.

- [ ] **Step 6: Check `tests/test_obd_config_loader.py` imports**

Read: `tests/test_obd_config_loader.py` (just the top-of-file import block).

Run:
```bash
cd Z:/o/OBD2v2
head -40 tests/test_obd_config_loader.py | grep -E "^(from|import)"
```

If it imports via `from src.obd.obd_config_loader import ...` or `from obd.obd_config_loader import ...`, those imports will break when we delete the flat file in task 7. Update them now.

- [ ] **Step 7: Rewrite test imports to use canonical path**

Find in `tests/test_obd_config_loader.py`:
```python
from src.obd.obd_config_loader import ...
```
Replace with:
```python
from src.obd.config.loader import ...
```

(Adjust for whatever form the import takes — `from obd.obd_config_loader import X` becomes `from obd.config.loader import X`, etc.)

- [ ] **Step 8: Run the config loader tests**

```bash
cd Z:/o/OBD2v2
pytest tests/test_obd_config_loader.py -v --tb=short 2>&1 | tail -30
```

Expected: all tests in this file pass. If any fail due to a missing symbol, it means step 4 missed something — port it and retry.

- [ ] **Step 9: Commit the config-loader resolution**

Run:
```bash
cd Z:/o/OBD2v2
git add -A
git status
git commit -m "refactor: migrate obd_config_loader symbols to config/loader (sweep 1, task 4)

Port missing symbols (if any) to canonical config/loader.py
Update tests/test_obd_config_loader.py imports to canonical path
Prepare obd_config_loader.py for deletion in task 7"
```

---

## Task 5: Rewrite `src/obd/__init__.py` to import from canonical locations

**Goal:** Rewrite the package's `__init__.py` so it imports directly from canonical subpackage locations instead of via facade files. After this task, the facade files are orphans (no one imports them), and task 7 can delete them safely.

**Files:**
- Modify: `src/obd/__init__.py` (currently 534 lines)

**Reference:** Read `src/obd/__init__.py` fully before starting this task. The file has 17 `from .X import (...)` blocks and one big `__all__` list at the bottom. We are changing the import sources, not the `__all__` list.

- [ ] **Step 1: Read current `src/obd/__init__.py` completely**

Read the full file. Note each `from .X import (...)` block and its line range.

- [ ] **Step 2: Rewrite the `from .data_logger` block**

Find (around line 26):
```python
from .data_logger import (
    DataLoggerError,
    LoggedReading,
    LoggingState,
    LoggingStats,
    ObdDataLogger,
    ParameterNotSupportedError,
    ParameterReadError,
    RealtimeDataLogger,
    createDataLoggerFromConfig,
    createRealtimeLoggerFromConfig,
    logReading,
    queryParameter,
    verifyDataPersistence,
)
```

This needs to become imports from canonical subpackage modules. Based on the audit, `data_logger` re-exports from `data/logger.py` and `data/realtime.py`. Replace the single block with two:

```python
from .data.logger import (
    DataLoggerError,
    LoggedReading,
    LoggingState,
    LoggingStats,
    ObdDataLogger,
    ParameterNotSupportedError,
    ParameterReadError,
    createDataLoggerFromConfig,
    logReading,
    queryParameter,
    verifyDataPersistence,
)
from .data.realtime import (
    RealtimeDataLogger,
    createRealtimeLoggerFromConfig,
)
```

**Important**: The split above assumes which symbols come from `logger.py` vs `realtime.py`. Verify by running:
```bash
cd Z:/o/OBD2v2
python -c "import src.obd.data.logger as m; print([n for n in dir(m) if not n.startswith('_')])"
python -c "import src.obd.data.realtime as m; print([n for n in dir(m) if not n.startswith('_')])"
```

Adjust the split if symbols live in different modules than assumed. Run a quick sanity check after the edit:
```bash
cd Z:/o/OBD2v2
python -c "from src.obd.data.logger import ObdDataLogger; from src.obd.data.realtime import RealtimeDataLogger; print('OK')"
```

- [ ] **Step 3: Rewrite the `from .display_manager` block**

Find (around line 49):
```python
from .display_manager import (
    AlertInfo,
    ...
    isDisplayAvailable,
)
```

Replace with:
```python
from src.display.manager import (
    AlertInfo,
    BaseDisplayDriver,
    DeveloperDisplayDriver,
    DisplayError,
    DisplayInitializationError,
    DisplayManager,
    DisplayMode,
    DisplayOutputError,
    HeadlessDisplayDriver,
    MinimalDisplayDriver,
    StatusInfo,
    createDisplayManagerFromConfig,
    getDisplayModeFromConfig,
    isDisplayAvailable,
)
```

**Note the path change**: `src.display.manager` not `src.obd.display.manager` — display is its own top-level package, not a subpackage of `obd`. Verify:
```bash
cd Z:/o/OBD2v2
python -c "from src.display.manager import DisplayManager; print('OK')"
```

- [ ] **Step 4: Rewrite the `from .obd_config_loader` block**

Find (around line 65):
```python
from .obd_config_loader import (
    ObdConfigError,
    getActiveProfile,
    getConfigSection,
    getLoggedParameters,
    getPollingInterval,
    getRealtimeParameters,
    getStaticParameters,
    loadObdConfig,
    shouldQueryStaticOnFirstConnection,
)
```

Replace with:
```python
from .config.loader import (
    ObdConfigError,
    getActiveProfile,
    getConfigSection,
    getLoggedParameters,
    getPollingInterval,
    getRealtimeParameters,
    getStaticParameters,
    loadObdConfig,
    shouldQueryStaticOnFirstConnection,
)
```

Verify:
```bash
cd Z:/o/OBD2v2
python -c "from src.obd.config.loader import loadObdConfig; print('OK')"
```

- [ ] **Step 5: Rewrite the `from .shutdown_manager` block**

Find (around line 116):
```python
from .shutdown_manager import (
    ShutdownManager,
    createShutdownManager,
    installGlobalShutdownHandler,
)
```

Replace with:
```python
from .shutdown.manager import (
    ShutdownManager,
    createShutdownManager,
    installGlobalShutdownHandler,
)
```

Or equivalently (cleaner since task 3 populated the subpackage's `__init__.py`):
```python
from .shutdown import (
    ShutdownManager,
    createShutdownManager,
    installGlobalShutdownHandler,
)
```

Use the second form — it lets the subpackage own its public API.

- [ ] **Step 6: Rewrite the `from .static_data_collector` block**

Find (around line 121):
```python
from .static_data_collector import (
    CollectionResult,
    ...
    verifyStaticDataExists,
)
```

Replace with:
```python
from .vehicle.static_collector import (
    CollectionResult,
    StaticDataCollector,
    StaticDataError,
    StaticDataStorageError,
    StaticReading,
    VinNotAvailableError,
    collectStaticDataOnFirstConnection,
    createStaticDataCollectorFromConfig,
    getStaticDataCount,
    verifyStaticDataExists,
)
```

Verify:
```bash
cd Z:/o/OBD2v2
python -c "from src.obd.vehicle.static_collector import StaticDataCollector; print('OK')"
```

- [ ] **Step 7: Rewrite the `try: from .adafruit_display` block**

Find (around line 134-164 — note the try/except wrapper for non-Pi platforms):
```python
try:
    from .adafruit_display import (
        ...
    )
    from .adafruit_display import (
        DisplayInitializationError as AdafruitDisplayInitializationError,
    )
except (ImportError, NotImplementedError, RuntimeError):
    # ... fallback implementations
```

Replace both `.adafruit_display` references with `src.display.adapters.adafruit`:
```python
try:
    from src.display.adapters.adafruit import (
        DISPLAY_HEIGHT,
        DISPLAY_WIDTH,
        AdafruitDisplayAdapter,
        Colors,
        DisplayAdapterError,
        DisplayRenderError,
        createAdafruitAdapter,
        isDisplayHardwareAvailable,
    )
    from src.display.adapters.adafruit import (
        DisplayInitializationError as AdafruitDisplayInitializationError,
    )
except (ImportError, NotImplementedError, RuntimeError):
    # ... fallback implementations (UNCHANGED)
```

Leave the except block unchanged. Verify on non-Pi:
```bash
cd Z:/o/OBD2v2
python -c "import src.obd as m; print('DISPLAY_WIDTH' in dir(m))"
```

Expected: `True` (either from real import or fallback).

- [ ] **Step 8: Rewrite the `from .alert_manager` block**

Find (around line 165):
```python
from .alert_manager import (
    ALERT_TYPE_BOOST_PRESSURE_MAX,
    ...
    isAlertingEnabled,
)
```

Replace with:
```python
from src.alert.manager import (
    ALERT_TYPE_BOOST_PRESSURE_MAX,
    ALERT_TYPE_COOLANT_TEMP_CRITICAL,
    ALERT_TYPE_OIL_PRESSURE_LOW,
    ALERT_TYPE_RPM_REDLINE,
    DEFAULT_COOLDOWN_SECONDS,
    AlertConfigurationError,
    AlertDatabaseError,
    AlertDirection,
    AlertError,
    AlertEvent,
    AlertManager,
    AlertState,
    AlertStats,
    AlertThreshold,
    checkThresholdValue,
    createAlertManagerFromConfig,
    getAlertThresholdsForProfile,
    getDefaultThresholds,
    isAlertingEnabled,
)
```

Verify:
```bash
cd Z:/o/OBD2v2
python -c "from src.alert.manager import AlertManager; print('OK')"
```

- [ ] **Step 9: Rewrite the `from .drive_detector` block**

Find (around line 186):
```python
from .drive_detector import (
    DEFAULT_DRIVE_END_DURATION_SECONDS,
    ...
    isDriveDetectionEnabled,
)
```

Replace with:
```python
from .drive.detector import (
    DEFAULT_DRIVE_END_DURATION_SECONDS,
    DEFAULT_DRIVE_END_RPM_THRESHOLD,
    DEFAULT_DRIVE_START_DURATION_SECONDS,
    DEFAULT_DRIVE_START_RPM_THRESHOLD,
    DRIVE_DETECTION_PARAMETERS,
    DetectorConfig,
    DetectorState,
    DetectorStats,
    DriveDetector,
    DriveDetectorConfigError,
    DriveDetectorError,
    DriveDetectorStateError,
    DriveSession,
    DriveState,
    createDriveDetectorFromConfig,
    getDefaultDriveDetectionConfig,
    getDriveDetectionConfig,
    isDriveDetectionEnabled,
)
```

Verify:
```bash
cd Z:/o/OBD2v2
python -c "from src.obd.drive.detector import DriveDetector; print('OK')"
```

- [ ] **Step 10: Rewrite the `from .profile_statistics` block**

Find (around line 214):
```python
from .profile_statistics import (
    SIGNIFICANCE_THRESHOLD,
    ...
    getProfileStatisticsSummary,
)
```

Replace with:
```python
from src.analysis.profile_statistics import (
    SIGNIFICANCE_THRESHOLD,
    ParameterComparison,
    ProfileComparison,
    ProfileComparisonResult,
    ProfileStatisticsError,
    ProfileStatisticsManager,
    ProfileStatisticsReport,
    compareProfiles,
    createProfileStatisticsManager,
    generateProfileReport,
    getAllProfilesStatistics,
    getProfileStatisticsSummary,
)
```

**Note the top-level package change**: `src.analysis` not `src.obd.analysis`. Verify:
```bash
cd Z:/o/OBD2v2
python -c "from src.analysis.profile_statistics import ProfileStatisticsManager; print('OK')"
```

- [ ] **Step 11: Rewrite the `from .shutdown_command` block**

Find (around line 228):
```python
from .shutdown_command import (
    SHUTDOWN_REASON_GPIO_BUTTON,
    ...
    sendShutdownSignal,
)
```

Since task 3 already populated `src/obd/shutdown/__init__.py` with all these symbols, replace with:
```python
from .shutdown import (
    SHUTDOWN_REASON_GPIO_BUTTON,
    SHUTDOWN_REASON_LOW_BATTERY,
    SHUTDOWN_REASON_MAINTENANCE,
    SHUTDOWN_REASON_SYSTEM,
    SHUTDOWN_REASON_USER_REQUEST,
    GpioButtonTrigger,
    GpioNotAvailableError,
    ProcessNotFoundError,
    ShutdownCommand,
    ShutdownCommandError,
    ShutdownConfig,
    ShutdownResult,
    ShutdownState,
    ShutdownTimeoutError,
    createShutdownCommandFromConfig,
    generateGpioTriggerScript,
    generateShutdownScript,
    isGpioAvailable,
    sendShutdownSignal,
)
```

**But** this duplicates the imports from step 5 (`.shutdown` already gave us `ShutdownManager` etc.). Merge the two `.shutdown` import blocks into one, combining symbols from both step 5 and step 11. Place the merged block where step 5's block was, and delete step 11's.

Merged block:
```python
from .shutdown import (
    SHUTDOWN_REASON_GPIO_BUTTON,
    SHUTDOWN_REASON_LOW_BATTERY,
    SHUTDOWN_REASON_MAINTENANCE,
    SHUTDOWN_REASON_SYSTEM,
    SHUTDOWN_REASON_USER_REQUEST,
    GpioButtonTrigger,
    GpioNotAvailableError,
    ProcessNotFoundError,
    ShutdownCommand,
    ShutdownCommandError,
    ShutdownConfig,
    ShutdownManager,
    ShutdownResult,
    ShutdownState,
    ShutdownTimeoutError,
    createShutdownCommandFromConfig,
    createShutdownManager,
    generateGpioTriggerScript,
    generateShutdownScript,
    installGlobalShutdownHandler,
    isGpioAvailable,
    sendShutdownSignal,
)
```

- [ ] **Step 12: Rewrite the `from .vin_decoder` block**

Find (around line 280):
```python
from .vin_decoder import (
    DEFAULT_API_TIMEOUT,
    ...
    validateVinFormat,
)
```

Replace with:
```python
from .vehicle.vin_decoder import (
    DEFAULT_API_TIMEOUT,
    NHTSA_API_BASE_URL,
    NHTSA_FIELD_MAPPING,
    ApiCallResult,
    VinApiError,
    VinApiTimeoutError,
    VinDecoder,
    VinDecoderError,
    VinDecodeResult,
    VinStorageError,
    VinValidationError,
    createVinDecoderFromConfig,
    decodeVinOnFirstConnection,
    getVehicleInfo,
    isVinDecoderEnabled,
    validateVinFormat,
)
```

Verify:
```bash
cd Z:/o/OBD2v2
python -c "from src.obd.vehicle.vin_decoder import VinDecoder; print('OK')"
```

- [ ] **Step 13: Verify the rewritten `__init__.py` has no references to facade files**

Run:
```bash
cd Z:/o/OBD2v2
grep -n "from \.\(data_logger\|drive_detector\|vin_decoder\|static_data_collector\|profile_statistics\|profile_manager\|profile_switcher\|alert_manager\|battery_monitor\|power_monitor\|calibration_manager\|calibration_comparator\|recommendation_ranker\|ai_analyzer\|ai_prompt_template\|display_manager\|adafruit_display\|obd_config_loader\|shutdown_manager\|shutdown_command\) import" src/obd/__init__.py
```

Expected: zero hits. If any hit appears, you missed a rewrite — go back and fix.

- [ ] **Step 14: Import the package and verify all symbols resolve**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import src.obd as m; symbols = [s for s in m.__all__]; missing = [s for s in symbols if not hasattr(m, s)]; print('Missing:', missing)"
```

Expected: `Missing: []`. If any symbols are missing, trace them back — they're probably in one of the blocks you haven't rewritten yet (check for any remaining `from .X` facade imports).

- [ ] **Step 15: Run fast test suite**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -30
```

Expected: same baseline test count passing. If red, check `--tb=short` output for the specific failure and fix.

- [ ] **Step 16: Commit the __init__.py rewrite**

Run:
```bash
cd Z:/o/OBD2v2
git add src/obd/__init__.py
git status
git commit -m "refactor: rewrite src/obd/__init__.py to import from canonical locations (sweep 1, task 5)

Replace 11 facade-file imports with direct imports from their canonical
subpackage or top-level package locations. Facade files are now orphans
and can be deleted in task 7."
```

---

## Task 6: Verify no remaining consumers of the facade paths

**Goal:** Before deleting the facade files, double-check that no code still imports from them.

**Files:**
- Read-only: all of `src/` and `tests/`

- [ ] **Step 1: Broad search for any remaining flat-file imports**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn -E "from (src\.)?obd\.(data_logger|drive_detector|vin_decoder|static_data_collector|profile_statistics|profile_manager|profile_switcher|alert_manager|battery_monitor|power_monitor|calibration_manager|calibration_comparator|recommendation_ranker|ai_analyzer|ai_prompt_template|display_manager|adafruit_display|obd_config_loader|shutdown_manager|shutdown_command) import" src tests 2>/dev/null
```

Expected: zero hits (or only hits inside the facade files themselves, which we're about to delete).

If hits remain outside the facade files:
- For each hit, update the import to use the canonical path
- Re-run the grep until empty

- [ ] **Step 2: Check for `import` style (less common)**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn -E "import (src\.)?obd\.(data_logger|drive_detector|vin_decoder|static_data_collector|profile_statistics|profile_manager|profile_switcher|alert_manager|battery_monitor|power_monitor|calibration_manager|calibration_comparator|recommendation_ranker|ai_analyzer|ai_prompt_template|display_manager|adafruit_display|obd_config_loader|shutdown_manager|shutdown_command)" src tests 2>/dev/null
```

Expected: zero hits outside the facade files themselves.

- [ ] **Step 3: Check facade files' own docstring examples — these are fine**

The facade files contain docstring blocks with usage examples like `from obd.data_logger import X`. Those are text comments, not real imports — they'll disappear when we delete the files. No action needed.

Run (informational only):
```bash
cd Z:/o/OBD2v2
grep -c "from obd\." src/obd/data_logger.py src/obd/drive_detector.py 2>/dev/null
```

Expected: some non-zero hits (in docstring comments). These are the docstring references mentioned.

---

## Task 7: Delete the facade files

**Goal:** Now that no code imports from the facades, delete them.

**Files:**
- Delete: `src/obd/data_logger.py`, `src/obd/drive_detector.py`, `src/obd/vin_decoder.py`, `src/obd/static_data_collector.py`, `src/obd/profile_statistics.py`, `src/obd/profile_manager.py`, `src/obd/profile_switcher.py`, `src/obd/alert_manager.py`, `src/obd/battery_monitor.py`, `src/obd/power_monitor.py`, `src/obd/calibration_manager.py`, `src/obd/calibration_comparator.py`, `src/obd/recommendation_ranker.py`, `src/obd/ai_analyzer.py`, `src/obd/ai_prompt_template.py`, `src/obd/display_manager.py`, `src/obd/adafruit_display.py`, `src/obd/obd_config_loader.py`

Note: `src/obd/shutdown_manager.py` and `src/obd/shutdown_command.py` were already moved in task 3 via `git mv`, so they're not in this delete list.

- [ ] **Step 1: Delete all pure-facade files with git rm**

Run:
```bash
cd Z:/o/OBD2v2
git rm src/obd/data_logger.py src/obd/drive_detector.py src/obd/vin_decoder.py src/obd/static_data_collector.py src/obd/profile_statistics.py src/obd/profile_manager.py src/obd/profile_switcher.py src/obd/alert_manager.py src/obd/battery_monitor.py src/obd/power_monitor.py src/obd/calibration_manager.py src/obd/calibration_comparator.py src/obd/recommendation_ranker.py src/obd/ai_analyzer.py src/obd/ai_prompt_template.py src/obd/display_manager.py src/obd/adafruit_display.py src/obd/obd_config_loader.py
git status
```

Expected: git status shows 18 deleted files.

- [ ] **Step 2: Run fast test suite**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -30
```

Expected: same baseline test count passing.

If any test fails with `ModuleNotFoundError` for a deleted facade: go back to task 6 and fix the missed import. Then re-run this step.

- [ ] **Step 3: Commit the deletions**

Run:
```bash
cd Z:/o/OBD2v2
git commit -m "refactor: delete 18 facade files from src/obd/ (sweep 1, task 7)

All facades now orphan after __init__.py rewrite in task 5.
Canonical locations remain in their respective subpackages and
top-level packages (data/, drive/, vehicle/, config/, alert/,
analysis/, display/, power/, calibration/, ai/, profile/)."
```

---

## Task 8: Full test suite run (including slow tests) — Checkpoint A gate

**Goal:** Final sweep-1 verification. The fast suite has been run multiple times during the sweep; now run the full suite one time to catch anything only the slow path exercises.

**Files:**
- No changes — this is a verification task

- [ ] **Step 1: Run the full test suite**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ --tb=short 2>&1 | tail -40
```

Expected: same baseline test count passing (no drop). If any test fails, fix before proceeding.

- [ ] **Step 2: Run ruff lint**

Run:
```bash
cd Z:/o/OBD2v2
ruff check src/ tests/ 2>&1 | tail -20
```

Expected: clean or only pre-existing warnings from files sweep 1 didn't touch. No new lint errors introduced by the rewrite.

- [ ] **Step 3: Run mypy type checking**

Run:
```bash
cd Z:/o/OBD2v2
mypy src/ 2>&1 | tail -20
```

Expected: same as the pre-sweep baseline. If mypy finds new errors that only appear after sweep 1, investigate — the import rewrite may have broken a type annotation somewhere.

- [ ] **Step 4: Sanity check — orphan facade imports truly gone**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn -E "from (src\.)?obd\.(data_logger|drive_detector|vin_decoder|static_data_collector|profile_statistics|profile_manager|profile_switcher|alert_manager|battery_monitor|power_monitor|calibration_manager|calibration_comparator|recommendation_ranker|ai_analyzer|ai_prompt_template|display_manager|adafruit_display|obd_config_loader)" src tests 2>/dev/null
```

Expected: zero hits.

Also verify the facade files are gone:
```bash
cd Z:/o/OBD2v2
ls src/obd/data_logger.py 2>&1
```

Expected: `ls: cannot access 'src/obd/data_logger.py': No such file or directory`.

- [ ] **Step 5: Delete the audit notes scratch file**

The `sweep1-audit-notes.md` was scratch — delete it before the PR merge.

Run:
```bash
cd Z:/o/OBD2v2
git rm docs/superpowers/plans/sweep1-audit-notes.md
git commit -m "chore: remove sweep 1 audit notes scratch file"
```

- [ ] **Step 6: Run the OBD simulator end-to-end smoke test**

Per the design doc's Checkpoint A requirement: the simulator path exercises a broad slice of the codebase and catches integration regressions that unit tests miss.

Run:
```bash
cd Z:/o/OBD2v2
timeout 30 python src/main.py --simulate --dry-run 2>&1 | tail -30
```

Expected: the simulator starts, runs for a few seconds, and exits cleanly. No unhandled exceptions, no `ModuleNotFoundError`, no missing-import errors.

If the simulator can't complete in dry-run mode, run without `--dry-run` and interrupt with Ctrl+C after confirming it starts cleanly:
```bash
cd Z:/o/OBD2v2
python src/main.py --simulate 2>&1 | head -40
# Ctrl+C after 5 seconds
```

Expected: clean startup logs, component init order matches expectations, no import errors.

If the simulator crashes, fix before proceeding to task 9.

---

## Task 9: Update design doc session log

**Goal:** Append the sweep 1 completion entry to the design doc's appendix.

**Files:**
- Modify: `docs/superpowers/specs/2026-04-12-reorg-design.md` (section 12)

- [ ] **Step 1: Append sweep 1 status to section 12**

Read: `docs/superpowers/specs/2026-04-12-reorg-design.md`, find section 12 "Appendix — Session log" (at the very bottom).

Find the existing table:
```markdown
| Date | Sweep | Session notes |
|---|---|---|
| 2026-04-12 | — | Design doc drafted during brainstorming session. Pending CIO approval. |
```

Append a new row (update the date to the actual completion date):
```markdown
| YYYY-MM-DD | 1 | Sweep 1 complete. Deleted 18 facade files, consolidated shutdown trio into src/obd/shutdown/ subpackage, rewrote src/obd/__init__.py to import from canonical locations. Full test suite passes (NNN tests). Simulator smoke test green. Checkpoint A gate passed. |
```

Replace `YYYY-MM-DD` with today's date (absolute date, not relative) and `NNN` with the actual test count.

- [ ] **Step 2: Commit the design doc update**

Run:
```bash
cd Z:/o/OBD2v2
git add docs/superpowers/specs/2026-04-12-reorg-design.md
git commit -m "docs: sweep 1 status update — Checkpoint A passed"
```

---

## Task 10: Merge sweep 1 to main

**Goal:** Merge the sweep 1 branch into `main`, enabling sweep 2 to begin.

**Files:**
- No code changes

**⚠️ Prerequisite:** Get explicit CIO approval before running any merge commands. The design doc's Checkpoint A requires sign-off. Do NOT merge autonomously.

- [ ] **Step 1: Surface to CIO that sweep 1 is ready for Checkpoint A review**

Tell the CIO (via normal session output):
> "Sweep 1 is complete and all checkpoints pass. Full test suite green, simulator smoke test green, no facade imports remain. Ready for Checkpoint A sign-off. Approve merge to main?"

Wait for explicit approval.

- [ ] **Step 2: After CIO approval, fast-forward main to the sweep branch**

Run:
```bash
cd Z:/o/OBD2v2
git checkout main
git merge --no-ff sprint/reorg-sweep1-facades -m "Merge sprint/reorg-sweep1-facades: Sweep 1 complete — facade cleanup

Sweep 1 of 6 for the structural reorganization (B-040).
- Deleted 18 facade files from src/obd/
- Consolidated shutdown_manager.py and shutdown_command.py into src/obd/shutdown/ subpackage
- Rewrote src/obd/__init__.py to import from canonical subpackage locations
- Zero behavior change, full test suite passing
- Design doc: docs/superpowers/specs/2026-04-12-reorg-design.md
- Checkpoint A gate passed"
git log --oneline -5
```

Expected: main now shows the sweep 1 commits + merge commit at the top.

- [ ] **Step 3: Confirm main is green**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q --tb=short 2>&1 | tail -5
```

Expected: same baseline test count passing.

- [ ] **Step 4: Do NOT delete the sweep branch yet**

Per design doc section 8.4, keep the sweep 3 and sweep 5 branches alive for 24 hours as a cooling period. Sweep 1 is low-risk so no cooling period is required, but keeping the branch costs nothing. Delete after sweep 2 merges.

- [ ] **Step 5: Announce Checkpoint A complete**

Tell the CIO:
> "Sweep 1 merged to main. Checkpoint A complete. Sweep 2 (legacy threshold merge) is ready to start whenever you're ready."

Wait for CIO direction before starting sweep 2.

---

## End of Sweep 1 Plan

**Success criteria (from design doc section 10):**
- ✅ All facade files deleted (18 files)
- ✅ Shutdown subpackage populated with real logic
- ✅ `src/obd/__init__.py` imports from canonical locations only
- ✅ Full test suite green, same baseline count
- ✅ Simulator smoke test passes
- ✅ Design doc session log updated
- ✅ Checkpoint A approved by CIO
- ✅ Merged to main

**On to sweep 2**: `docs/superpowers/plans/2026-04-12-reorg-sweep2-thresholds.md`
