# Sweep 5 — Split Oversized Files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split every source file exceeding 300 lines and every test file exceeding 500 lines into smaller, focused modules. The largest file is `src/pi/obd/orchestrator.py` (2,504 lines) which gets the full TD-003 7-module split treatment. Another ~9 files need splitting. Zero behavior change.

**Architecture:** This sweep is pure refactoring — no new features, no behavior changes. The splits preserve public APIs via package `__init__.py` re-exports. The orchestrator split is the highest-risk sub-task because it touches 12 load-bearing component dependencies. Init/shutdown order is a critical invariant that must survive the split.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy, git.

**Design doc**: `docs/superpowers/specs/2026-04-12-reorg-design.md` — read section 7 (sweep 5).

**Canonical orchestrator split plan**: `offices/pm/tech_debt/TD-003-orchestrator-refactoring-plan.md` — **read this fully before starting Task 2.** It has the 7-module split structure, init/shutdown order, and key architectural details to preserve.

**Estimated effort:** 5–7 days. Orchestrator alone is 2–3 days.

**Prerequisites:**
- Sweeps 1, 2, 3, 4 merged to `main`
- 24-hour cooling period after sweep 3 complete (sweep 4 may have already satisfied this)
- Clean checkout of `main`, tests green

**Exit criteria:**
1. Every `src/**/*.py` file is ≤300 lines (or documented exemption in `src/README.md`)
2. Every `tests/**/*.py` file is ≤500 lines
3. Orchestrator split into 7 modules per TD-003
4. Init order preserved (verified via simulator startup logs)
5. Shutdown order preserved (verified via simulator shutdown logs)
6. Backward compatibility: `from src.pi.obd.orchestrator import ApplicationOrchestrator` still works
7. All tests green
8. Simulator smoke test passes
9. PR merged to `main`
10. 24-hour cooling period before sweep 6 begins

**Risk**: Medium-High. The orchestrator refactor is the load-bearing sub-task. Pure refactors of this size can introduce timing/lifecycle bugs that unit tests don't catch. The simulator smoke test is the primary integration safety net.

---

## Task 1: Setup

- [ ] **Step 1: Start from clean main**

```bash
cd Z:/o/OBD2v2
git checkout main
git log --oneline -3
```
Expected: last commit is sweep 4 merge.

- [ ] **Step 2: Confirm cooling period elapsed (24 hours after sweep 3 merge)**

Check when sweep 3 merged:
```bash
cd Z:/o/OBD2v2
git log --oneline --grep="Sweep 3 complete" -1
git show --format="%ai" --no-patch $(git log --oneline --grep="Sweep 3 complete" -1 --pretty=%H)
```

If less than 24 hours ago, stop and wait. If sweep 4 already completed after the cooling period, proceed.

- [ ] **Step 3: Create sweep 5 branch**

```bash
cd Z:/o/OBD2v2
git checkout -b sprint/reorg-sweep5-file-sizes main
```

- [ ] **Step 4: Verify baseline green**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q --tb=short 2>&1 | tail -5
```

- [ ] **Step 5: Snapshot the current top-10 oversized file list**

```bash
cd Z:/o/OBD2v2
find src -name "*.py" -not -path "*/__pycache__/*" -exec wc -l {} + 2>/dev/null | sort -rn | head -15 > /tmp/sweep5-before.txt
cat /tmp/sweep5-before.txt
```

This is the list of files that need splitting. The orchestrator should be at the top at ~2,504 lines. Record the file paths — paths changed in sweep 3 (e.g., `src/obd/orchestrator.py` is now `src/pi/obd/orchestrator.py`).

- [ ] **Step 6: Read TD-003 in full**

**Required reading before Task 2**: `offices/pm/tech_debt/TD-003-orchestrator-refactoring-plan.md`

Key things you must internalize:
- The 7-module split structure
- Init order (Database → ... → BackupManager)
- Shutdown order (reverse: BackupManager → ... → Database)
- 5 callback chains (Reading, Drive, Alert, Analysis, Profile)
- Backward compatibility requirement: `ApplicationOrchestrator` importable from package top

---

## Task 2: Split `src/pi/obd/orchestrator.py` into 7-module package

**Goal:** Convert the single 2,504-line file into a package matching the TD-003 plan structure. Preserve backward compatibility via `__init__.py` re-export.

**Files:**
- Delete: `src/pi/obd/orchestrator.py` (after split)
- Create: `src/pi/obd/orchestrator/__init__.py`
- Create: `src/pi/obd/orchestrator/types.py`
- Create: `src/pi/obd/orchestrator/core.py`
- Create: `src/pi/obd/orchestrator/lifecycle.py`
- Create: `src/pi/obd/orchestrator/connection_recovery.py`
- Create: `src/pi/obd/orchestrator/event_router.py`
- Create: `src/pi/obd/orchestrator/backup_coordinator.py`
- Create: `src/pi/obd/orchestrator/health_monitor.py`
- Create: `src/pi/obd/orchestrator/signal_handler.py`

**Strategy**: Create the new package directory, create `types.py` first with extracted type definitions (exceptions, enums, dataclasses), then progressively move methods out of the monolithic `orchestrator.py` into the new modules. The core `ApplicationOrchestrator` class stays in `core.py` but delegates most work to mixin classes or helper functions in the other modules. Run the test suite after every method move to catch regressions immediately.

- [ ] **Step 1: Read the current orchestrator.py to understand its structure**

Read: `src/pi/obd/orchestrator.py` (2,504 lines — read in chunks of 500 lines)

As you read, note:
- Top-level imports
- Top-level constants / type aliases
- Exception classes defined in the file
- Dataclasses / enums defined in the file
- The `ApplicationOrchestrator` class structure: init, runLoop, getStatus, and all private methods grouped by purpose

- [ ] **Step 2: Build a mapping of methods → target module**

Create `docs/superpowers/plans/sweep5-orchestrator-method-map.md`:
```markdown
# Orchestrator method map — which method goes where

## types.py (~100 lines target)
- Exceptions: OrchestratorError, ComponentInitializationError, ComponentStartError, ComponentStopError
- Enums: ShutdownState (if not in shutdown subpackage already)
- Dataclasses: HealthCheckStats, (any others from current orchestrator.py top)

## core.py (~750 lines target)
- ApplicationOrchestrator class
- __init__ (stays here, delegates to mixins/helpers)
- runLoop
- getStatus
- Properties (isRunning, isStopping, etc.)
- Simple accessors

## lifecycle.py (~400 lines target)
- _initializeDatabase, _initializeProfileManager, ..._initializeBackupManager (12 methods)
- _shutdownDatabase, ..._shutdownBackupManager (13 methods)
- The init/shutdown order constants

## connection_recovery.py (~350 lines target)
- _reconnectWithBackoff
- _handleConnectionLost
- _pauseOperations
- _resumeOperations
- (other connection-recovery helpers)

## event_router.py (~400 lines target)
- _handleReading (from DataLogger)
- _handleDriveStart / _handleDriveEnd (from DriveDetector)
- _handleAlert (from AlertManager)
- _handleAnalysis (from StatisticsEngine)
- _handleProfileSwitch (from ProfileSwitcher)
- Callback registration helpers

## backup_coordinator.py (~300 lines target)
- _initializeBackupSchedule
- _runCatchupBackup
- _uploadBackup
- _cleanupOldBackups
- (any backup-related orchestrator methods)

## health_monitor.py (~200 lines target)
- _runHealthChecks
- _trackDataRate
- _buildStatusDict
- HealthCheckStats tracking

## signal_handler.py (~100 lines target)
- _installSignalHandlers
- _handleSignal (SIGINT/SIGTERM)
- Double-Ctrl+C pattern
```

Read the current `orchestrator.py` and assign each method to a target module. Write the assignments in the file above.

- [ ] **Step 3: Create the orchestrator package directory and __init__.py**

The current `src/pi/obd/orchestrator.py` will be replaced by a package. Python can't have both `orchestrator.py` and `orchestrator/` — we need to do this carefully.

Strategy: create a temporary directory, build the package inside, then atomically replace.

First create the package directory as `orchestrator_new`:
```bash
cd Z:/o/OBD2v2
mkdir src/pi/obd/orchestrator_new
```

- [ ] **Step 4: Create `orchestrator_new/types.py`**

Create `src/pi/obd/orchestrator_new/types.py`.

Extract from `src/pi/obd/orchestrator.py` only the exception classes, enums, and dataclasses defined at the top of the file. Do not include the main `ApplicationOrchestrator` class or any of its methods.

Example (actual content depends on what's in orchestrator.py):
```python
################################################################################
# File Name: types.py
# Purpose/Description: Type definitions for the orchestrator package
# Author: Ralph Agent
# Creation Date: 2026-04-12
# ...
################################################################################
"""Type definitions: exceptions, enums, dataclasses for orchestrator."""

from dataclasses import dataclass, field
from datetime import datetime


class OrchestratorError(Exception):
    """Base exception for orchestrator errors."""


class ComponentInitializationError(OrchestratorError):
    """Raised when a component fails to initialize."""


class ComponentStartError(OrchestratorError):
    """Raised when a component fails to start."""


class ComponentStopError(OrchestratorError):
    """Raised when a component fails to stop cleanly."""


@dataclass
class HealthCheckStats:
    """Health check statistics tracked by the orchestrator."""
    lastCheckTime: datetime | None = None
    checksRun: int = 0
    checksFailed: int = 0
    # ...add other fields as they appear in orchestrator.py
```

**Important**: Copy the actual exception class definitions and any dataclass fields from the real `orchestrator.py` — don't make up fields that don't exist.

- [ ] **Step 5: Create `orchestrator_new/signal_handler.py`**

This is the simplest module to extract. Find the signal-handling code in `orchestrator.py` (look for `_handleSignal`, `_installSignalHandlers`, `SIGINT`, `SIGTERM`, `_shutdownRequested`).

Create `src/pi/obd/orchestrator_new/signal_handler.py` with the signal-handling functions as free functions or as a mixin class. Mixin approach:

```python
"""Signal handling for the orchestrator (SIGINT, SIGTERM, double-Ctrl+C)."""

import logging
import signal
from typing import Any

logger = logging.getLogger(__name__)


class SignalHandlerMixin:
    """Mixin providing signal handling for ApplicationOrchestrator.

    Assumes self has attributes:
    - _shutdownRequested: bool
    - _originalSigintHandler
    - _originalSigtermHandler
    """

    def _installSignalHandlers(self) -> None:
        """Install SIGINT and SIGTERM handlers."""
        self._originalSigintHandler = signal.signal(signal.SIGINT, self._handleSignal)
        self._originalSigtermHandler = signal.signal(signal.SIGTERM, self._handleSignal)

    def _handleSignal(self, signum: int, frame: Any) -> None:
        """Handle shutdown signal. Second Ctrl+C forces exit."""
        if self._shutdownRequested:
            logger.warning("Second signal received — forcing exit")
            raise SystemExit(1)
        logger.info(f"Signal {signum} received — beginning graceful shutdown")
        self._shutdownRequested = True

    def _restoreSignalHandlers(self) -> None:
        """Restore the original signal handlers at shutdown."""
        if self._originalSigintHandler is not None:
            signal.signal(signal.SIGINT, self._originalSigintHandler)
        if self._originalSigtermHandler is not None:
            signal.signal(signal.SIGTERM, self._originalSigtermHandler)
```

Extract the actual implementations from `orchestrator.py` — do not invent method bodies.

- [ ] **Step 6: Create `orchestrator_new/health_monitor.py`**

Extract health-check and data-rate-tracking methods from `orchestrator.py`. Use the same mixin pattern.

- [ ] **Step 7: Create `orchestrator_new/backup_coordinator.py`**

Extract backup-related methods. These touch `BackupManager` component — the mixin must assume `self._backupManager` is present.

- [ ] **Step 8: Create `orchestrator_new/connection_recovery.py`**

Extract reconnect-with-backoff methods. These touch `Connection` component. Preserve exponential backoff logic byte-for-byte — do not optimize or "improve" it.

- [ ] **Step 9: Create `orchestrator_new/event_router.py`**

Extract all `_handle*` methods that route callbacks from components to the display and other components. This is the largest extracted module — may approach 400 lines.

Preserve the 5 callback chains exactly:
1. Reading: DataLogger → Orchestrator → DisplayManager + DriveDetector + AlertManager
2. Drive: DriveDetector → Orchestrator → DisplayManager + external callback
3. Alert: AlertManager → Orchestrator → DisplayManager + HardwareManager + external
4. Analysis: StatisticsEngine → Orchestrator → DisplayManager + external
5. Profile: ProfileSwitcher → Orchestrator → AlertManager + DataLogger

- [ ] **Step 10: Create `orchestrator_new/lifecycle.py`**

Extract all `_initializeX` (12 methods) and `_shutdownX` (13 methods) into a mixin.

**Critical invariants**:
- Init order: Database → ProfileManager → Connection → VinDecoder → DisplayManager → HardwareManager → StatisticsEngine → DriveDetector → AlertManager → DataLogger → ProfileSwitcher → BackupManager
- Shutdown order: BackupManager → DataLogger → AlertManager → DriveDetector → StatisticsEngine → HardwareManager → DisplayManager → VinDecoder → Connection → ProfileSwitcher → ProfileManager → Database

Encode these as explicit ordered lists at the top of lifecycle.py:
```python
COMPONENT_INIT_ORDER = [
    "Database",
    "ProfileManager",
    "Connection",
    "VinDecoder",
    "DisplayManager",
    "HardwareManager",
    "StatisticsEngine",
    "DriveDetector",
    "AlertManager",
    "DataLogger",
    "ProfileSwitcher",
    "BackupManager",
]

COMPONENT_SHUTDOWN_ORDER = list(reversed(COMPONENT_INIT_ORDER))
```

Then the `initializeAllComponents()` and `shutdownAllComponents()` methods iterate over these lists, calling the matching `_initializeX` / `_shutdownX` method for each.

- [ ] **Step 11: Create `orchestrator_new/core.py`**

The main `ApplicationOrchestrator` class. It inherits from all the mixin classes:

```python
"""Main orchestrator class. All heavy lifting is delegated to mixins."""

from .types import OrchestratorError
from .lifecycle import LifecycleMixin
from .signal_handler import SignalHandlerMixin
from .health_monitor import HealthMonitorMixin
from .backup_coordinator import BackupCoordinatorMixin
from .connection_recovery import ConnectionRecoveryMixin
from .event_router import EventRouterMixin


class ApplicationOrchestrator(
    LifecycleMixin,
    SignalHandlerMixin,
    HealthMonitorMixin,
    BackupCoordinatorMixin,
    ConnectionRecoveryMixin,
    EventRouterMixin,
):
    """Main application orchestrator.

    Composes all component lifecycles, event routing, recovery, and health
    monitoring via mixin classes. See TD-003 for the rationale behind the
    split.
    """

    def __init__(self, config: dict) -> None:
        """..."""
        # Move the actual __init__ body here from the original file
        ...

    def runLoop(self) -> None:
        """Main application loop."""
        ...

    def getStatus(self) -> dict:
        """Return current status dict."""
        ...
```

Copy the actual `__init__`, `runLoop`, `getStatus`, and any other methods that stayed in core (not moved to mixins) from the original file.

- [ ] **Step 12: Create `orchestrator_new/__init__.py`**

```python
"""
Orchestrator subpackage — split per TD-003.

Public API: ApplicationOrchestrator, exceptions, and helpers are re-exported
here so existing callers can do:
    from src.pi.obd.orchestrator import ApplicationOrchestrator
"""

from .core import ApplicationOrchestrator
from .types import (
    ComponentInitializationError,
    ComponentStartError,
    ComponentStopError,
    OrchestratorError,
    HealthCheckStats,
)

# Also re-export the factory function if one existed in the original
# from .core import createOrchestratorFromConfig  # if applicable

__all__ = [
    "ApplicationOrchestrator",
    "OrchestratorError",
    "ComponentInitializationError",
    "ComponentStartError",
    "ComponentStopError",
    "HealthCheckStats",
    # "createOrchestratorFromConfig",  # if applicable
]
```

- [ ] **Step 13: Test the new package in isolation**

Run:
```bash
cd Z:/o/OBD2v2
python -c "
import importlib.util
spec = importlib.util.spec_from_file_location('orchestrator_new', 'src/pi/obd/orchestrator_new/__init__.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print('OK — ApplicationOrchestrator:', m.ApplicationOrchestrator)
"
```

Expected: `OK — ApplicationOrchestrator: <class ...>`. If any error, fix the split before proceeding.

- [ ] **Step 14: Atomic swap — replace orchestrator.py with orchestrator/ package**

Now do the atomic swap. Python's import system can't have both `orchestrator.py` and `orchestrator/` — we need to delete the file and rename the new directory in the same commit.

```bash
cd Z:/o/OBD2v2
git rm src/pi/obd/orchestrator.py
git mv src/pi/obd/orchestrator_new src/pi/obd/orchestrator
git status
```

Expected: `orchestrator.py` deleted, `orchestrator_new/*` renamed to `orchestrator/*`.

- [ ] **Step 15: Run fast test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -30
```

Expected: same baseline count. If red, investigate failures — most common issue is a method that wasn't moved into the mixin (still living in the deleted `orchestrator.py`).

If red with "AttributeError: 'ApplicationOrchestrator' object has no attribute 'X'": you missed a method. Find it in the pre-split version (via `git show HEAD:src/pi/obd/orchestrator.py`) and add it to the appropriate mixin.

- [ ] **Step 16: Run simulator smoke test**

```bash
cd Z:/o/OBD2v2
timeout 30 python src/pi/main.py --simulate --dry-run 2>&1 | tail -40
```

Expected: clean startup, components init in correct order (watch the logs), shutdown in reverse order. No component-ordering errors.

**Critical check**: the log output should show the 12 components initializing in this exact order:
1. Database
2. ProfileManager
3. Connection
4. VinDecoder
5. DisplayManager
6. HardwareManager
7. StatisticsEngine
8. DriveDetector
9. AlertManager
10. DataLogger
11. ProfileSwitcher
12. BackupManager

If the order is wrong, fix `lifecycle.py` — the `COMPONENT_INIT_ORDER` list may be wrong, or the iteration may be backward.

- [ ] **Step 17: Verify file sizes**

```bash
cd Z:/o/OBD2v2
wc -l src/pi/obd/orchestrator/*.py
```

Each file should be ≤300 lines (or very close). If any file is over, split it further or move functionality.

- [ ] **Step 18: Commit the orchestrator split**

```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "refactor: split src/pi/obd/orchestrator.py into 7-module package per TD-003 (sweep 5, task 2)

Converted 2,504-line monolithic file into a package with:
- types.py: exceptions, dataclasses
- core.py: ApplicationOrchestrator class, __init__, runLoop
- lifecycle.py: 12 _initialize* + 13 _shutdown* methods, order lists
- connection_recovery.py: reconnect with backoff
- event_router.py: 5 callback chains from components to display
- backup_coordinator.py: backup schedule, catchup, upload, cleanup
- health_monitor.py: health checks, data rate tracking
- signal_handler.py: SIGINT/SIGTERM, double-Ctrl+C
- __init__.py: re-exports ApplicationOrchestrator for backward compat

Init order and shutdown order preserved per TD-003. Simulator smoke
test confirms correct component ordering. All tests green.

Resolves TD-003, B-019 (partially — other oversized files handled in
sweep 5 task 4)."
```

---

## Task 3: Split oversized orchestrator test files

**Goal:** If any `tests/test_orchestrator_*.py` file exceeds 500 lines, split it by concern.

**Files:**
- Modify: `tests/test_orchestrator_*.py` files that exceed 500 lines

- [ ] **Step 1: Check current sizes**

```bash
cd Z:/o/OBD2v2
wc -l tests/test_orchestrator_*.py | sort -rn
```

Expected: most files well under 500, some may be near the limit.

- [ ] **Step 2: For each file over 500 lines, identify logical split points**

Read the oversized test file. Group tests by what they test:
- Tests for initialization → keep in one file
- Tests for a specific callback (e.g., drive events) → split to new file
- Tests for a specific component interaction → split to new file

The file names already suggest the splits (e.g., `test_orchestrator_startup.py`, `test_orchestrator_drive_detection.py`). If a file mixes concerns, extract the secondary concern into a new file with a descriptive name.

- [ ] **Step 3: Perform the splits**

For each split:
1. Read the source file
2. Create the new file with copied test functions + necessary imports
3. Delete the moved tests from the original file
4. Run both files:
   ```bash
   pytest tests/test_orchestrator_X.py tests/test_orchestrator_Y.py -v
   ```
5. Verify both green
6. Commit:
   ```bash
   git add tests/test_orchestrator_X.py tests/test_orchestrator_Y.py
   git commit -m "test: split test_orchestrator_X into focused files (sweep 5, task 3)"
   ```

- [ ] **Step 4: Verify all test files are ≤500 lines**

```bash
cd Z:/o/OBD2v2
find tests -name "*.py" -not -path "*/__pycache__/*" -exec wc -l {} + 2>/dev/null | awk '$1 > 500 {print}'
```
Expected: zero output.

---

## Task 4: Split the remaining oversized source files

**Goal:** Every other source file over 300 lines gets split.

**Files to split** (from the pre-sweep snapshot):
- `src/pi/obd/data_exporter.py` (1,309 lines)
- `src/pi/obd/simulator/drive_scenario.py` (1,234 lines)
- `src/pi/obd/shutdown/command.py` (1,158 lines — from sweep 1 consolidation)
- `src/pi/obd/simulator_integration.py` (1,048 lines)
- `src/pi/obd/simulator/simulator_cli.py` (992 lines)
- `src/pi/obd/simulator/failure_injector.py` (985 lines)
- `src/pi/power/power.py` (903 lines)
- `src/server/ai/analyzer.py` (882 lines)
- `src/pi/alert/tiered_thresholds.py` (737 lines)
- Any others that are over 300 lines

**Pattern for each file:**
1. Read the file to identify logical sub-concerns
2. Create submodules in the same directory (or a new subpackage)
3. Move related functions/classes to each submodule
4. Keep the original file as a re-export facade IF other code imports from it, OR delete it and update imports
5. Run fast suite
6. Commit

- [ ] **Step 1: Verify the current oversized list after sweep 3/4**

```bash
cd Z:/o/OBD2v2
find src -name "*.py" -not -path "*/__pycache__/*" -exec wc -l {} + 2>/dev/null | awk '$1 > 300' | sort -rn
```

Record the current list of oversized files. Note that paths are now tier-aware (`src/pi/...` or `src/server/...`).

- [ ] **Step 2: Split `src/pi/obd/data_exporter.py`**

Read: `src/pi/obd/data_exporter.py`.

Identify split points. Likely patterns:
- One function/class per export format (CSV, JSON, SQL, etc.)
- Convert to a subpackage `src/pi/obd/export/` with one file per format

Check if `src/pi/obd/export/` already exists (from earlier refactoring). If yes, move the format-specific code into it. If no, create it.

Apply the pattern:
1. `mkdir src/pi/obd/export_new` (or use existing `export/` if it's in good shape)
2. Create format-specific files: `csv_exporter.py`, `json_exporter.py`, etc.
3. Update `src/pi/obd/data_exporter.py` to import and delegate to the new files, OR delete and update callers

Ensure file count and sizes:
```bash
cd Z:/o/OBD2v2
wc -l src/pi/obd/data_exporter.py src/pi/obd/export/*.py 2>/dev/null
```
Each file ≤300.

Run tests, commit:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -10
git add -A
git commit -m "refactor: split data_exporter.py by export format (sweep 5, task 4)"
```

- [ ] **Step 3: Split `src/pi/obd/simulator/drive_scenario.py`**

Read the file. Identify the scenario types (likely: city, highway, cold_start, full_cycle).

Split by scenario type into separate files in the same `src/pi/obd/simulator/` directory:
- `scenario_city.py`
- `scenario_highway.py`
- `scenario_cold_start.py`
- `scenario_full_cycle.py`
- `scenario_base.py` (shared base class / interface)

Or, if the file has other organization (e.g., scenario building blocks + scenario definitions), split by layer instead.

Keep `drive_scenario.py` as a facade that re-exports the scenarios, OR delete and update callers — same decision process as task 2.

Run tests, commit.

- [ ] **Step 4: Split `src/pi/obd/shutdown/command.py`**

This is the file that came from sweep 1's `shutdown_command.py` consolidation. At 1,158 lines it's still oversized.

Likely split points:
- `command_base.py` — ShutdownCommand class, ShutdownConfig
- `command_gpio.py` — GpioButtonTrigger and GPIO-related code
- `command_script.py` — generateShutdownScript, generateGpioTriggerScript
- Keep `command.py` (or rename to `__init__.py` if converting to nested package)

Apply the split. Update `src/pi/obd/shutdown/__init__.py` re-exports to pull from the new files.

Run tests, commit.

- [ ] **Step 5: Split `src/pi/obd/simulator_integration.py`**

Read the file to identify concerns. Likely split:
- One class per integration type (real connection vs. simulated connection vs. mixed)
- Or by lifecycle (setup, teardown, request handling)

Apply split, test, commit.

- [ ] **Step 6: Split `src/pi/obd/simulator/simulator_cli.py`**

Split by CLI command group — one file per logical command set (start, stop, status, replay, etc.).

Test, commit.

- [ ] **Step 7: Split `src/pi/obd/simulator/failure_injector.py`**

Split by failure type — connection failures, data corruption, timeouts, etc.

Test, commit.

- [ ] **Step 8: Split `src/pi/power/power.py`**

At 903 lines — may be a single PowerMonitor class with many methods. Split by concern:
- `power.py` — main class (kept, but trimmed)
- `power_metrics.py` — metric calculation helpers
- `power_events.py` — event classification
- (or whatever logical groups emerge)

Test, commit.

- [ ] **Step 9: Split `src/server/ai/analyzer.py`**

At 882 lines — likely the main `AiAnalyzer` class with multiple responsibilities. Split:
- `analyzer.py` — main class (trimmed)
- `analyzer_prompts.py` — prompt construction (if not already in `prompt_template.py`)
- `analyzer_parsing.py` — response parsing
- `analyzer_scoring.py` — confidence scoring

Test, commit.

- [ ] **Step 10: Split `src/pi/alert/tiered_thresholds.py`**

At 737 lines — likely one class/helper per parameter type. Split by parameter:
- `tiered_core.py` — TieredThreshold base class, enum
- `tiered_rpm.py` — RPM-specific logic
- `tiered_temp.py` — temperature (coolant, IAT)
- `tiered_pressure.py` — boost, oil pressure
- `tiered_voltage.py` — battery voltage (bidirectional)
- `tiered_timing.py` — timing advance (already in `timing_thresholds.py`?)

Keep `tiered_thresholds.py` as a facade/package entry if callers import from it.

**CRITICAL**: Spool-authoritative values must not change. After the split, diff the thresholds config:
```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('config.json')); print(json.dumps(c['pi']['tieredThresholds'], indent=2, sort_keys=True))" > /tmp/tiered-task10-after.json
diff /tmp/sweep4-tiered-before.json /tmp/tiered-task10-after.json && echo "UNCHANGED"
```
Expected: `UNCHANGED`.

Test, commit.

- [ ] **Step 11: Any other files still over 300**

```bash
cd Z:/o/OBD2v2
find src -name "*.py" -not -path "*/__pycache__/*" -exec wc -l {} + 2>/dev/null | awk '$1 > 300'
```

For each remaining file: split by concern following the same pattern. Test, commit each.

- [ ] **Step 12: Document any exemptions in src/README.md**

If any file is **unavoidably** over 300 lines (e.g., a single generated file, a data-heavy constants file), document the exemption:

Add a section to `src/README.md`:
```markdown
## Size exemptions

Files that exceed the 300-line guideline for documented reasons:

- `src/pi/obd/obd_parameters.py` — NNN lines — constant definitions for OBD-II PIDs, not splittable into smaller logical units
- (etc.)
```

Commit:
```bash
cd Z:/o/OBD2v2
git add src/README.md
git commit -m "docs: document size exemptions in src/README.md (sweep 5)"
```

---

## Task 5: Full verification

- [ ] **Step 1: File size final check**

```bash
cd Z:/o/OBD2v2
echo "=== Source files over 300 lines ==="
find src -name "*.py" -not -path "*/__pycache__/*" -exec wc -l {} + 2>/dev/null | awk '$1 > 300 && $1 != "total" {print}'
echo "=== Test files over 500 lines ==="
find tests -name "*.py" -not -path "*/__pycache__/*" -exec wc -l {} + 2>/dev/null | awk '$1 > 500 && $1 != "total" {print}'
```

Expected: either empty output, or only documented exemptions from task 4 step 12.

- [ ] **Step 2: Full test suite (including slow tests)**

```bash
cd Z:/o/OBD2v2
pytest tests/ --tb=short 2>&1 | tail -15
```
Expected: same baseline count passing.

- [ ] **Step 3: Ruff, mypy**

```bash
cd Z:/o/OBD2v2
ruff check src/ tests/ 2>&1 | tail -10
mypy src/ 2>&1 | tail -10
```

- [ ] **Step 4: Simulator smoke test with explicit ordering verification**

```bash
cd Z:/o/OBD2v2
timeout 60 python src/pi/main.py --simulate --dry-run 2>&1 | tee /tmp/sweep5-simulator.log | tail -40
```

Read `/tmp/sweep5-simulator.log` to verify:
1. Component init order matches the 12-step sequence (Database → ... → BackupManager)
2. Component shutdown order matches the reverse sequence
3. No errors during callback routing
4. Clean exit

If ordering is wrong, fix `src/pi/obd/orchestrator/lifecycle.py`.

- [ ] **Step 5: Spool value final check**

```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('config.json')); print(json.dumps(c['pi']['tieredThresholds'], indent=2, sort_keys=True))" > /tmp/sweep5-tiered-final.json
diff /tmp/sweep4-tiered-before.json /tmp/sweep5-tiered-final.json && echo "TIERED VALUES UNCHANGED ACROSS SWEEP 5"
```

---

## Task 6: Cleanup, design doc update, merge

- [ ] **Step 1: Delete the orchestrator method map scratch file**

```bash
cd Z:/o/OBD2v2
git rm docs/superpowers/plans/sweep5-orchestrator-method-map.md 2>/dev/null || true
git commit -m "chore: remove sweep 5 orchestrator method map scratch" 2>/dev/null || true
```

- [ ] **Step 2: Append sweep 5 status to design doc section 12**

```markdown
| YYYY-MM-DD | 5 | Sweep 5 complete. Orchestrator split into 7-module package per TD-003. Split 10+ other oversized files. All files ≤300 lines (src) / ≤500 lines (tests) or documented exemption. Init/shutdown order preserved (verified via simulator). All tests green. **Checkpoint C passed.** |
```

- [ ] **Step 3: Commit and surface for merge**

```bash
cd Z:/o/OBD2v2
git add docs/superpowers/specs/2026-04-12-reorg-design.md
git commit -m "docs: sweep 5 status update — Checkpoint C passed"
```

Tell CIO:
> "Sweep 5 complete. Orchestrator split done, 10+ other files split, all sizes within guidelines. Init/shutdown order verified via simulator. All tests green. Ready for Checkpoint C approval. 24-hour cooling period required before sweep 6."

Wait for approval.

- [ ] **Step 4: Merge to main**

```bash
cd Z:/o/OBD2v2
git checkout main
git merge --no-ff sprint/reorg-sweep5-file-sizes -m "Merge sprint/reorg-sweep5-file-sizes: Sweep 5 complete — split oversized files

Sweep 5 of 6 for the structural reorganization (B-040).

- Split src/pi/obd/orchestrator.py (2,504 lines) into 7-module package per TD-003
  - types.py, core.py, lifecycle.py, connection_recovery.py, event_router.py,
    backup_coordinator.py, health_monitor.py, signal_handler.py
- Split 10+ other oversized files (data_exporter, simulator modules, power,
  analyzer, tiered_thresholds, etc.)
- All src files ≤300 lines, test files ≤500 lines (or documented exemption)
- Init/shutdown order preserved per TD-003 (verified via simulator)
- Spool-authoritative values unchanged
- All tests green, simulator green
- Checkpoint C passed
- Resolves B-019 fully, TD-003 fully
- Design doc: docs/superpowers/specs/2026-04-12-reorg-design.md"
```

- [ ] **Step 5: Start 24-hour cooling period**

Per design doc section 8.5. Record the merge time. Do not start sweep 6 until 24 hours elapse.

Tell CIO:
> "Sweep 5 merged. Checkpoint C complete. 24-hour cooling period begins now. Sweep 6 (camelCase + READMEs) can start after [merge time + 24h]."

---

## End of Sweep 5 Plan

**Success criteria:**
- ✅ Orchestrator split into 7 modules per TD-003
- ✅ All source files ≤300 lines (or documented exemption)
- ✅ All test files ≤500 lines
- ✅ Init/shutdown order preserved
- ✅ Spool values unchanged
- ✅ All tests green, simulator green
- ✅ Merged to main, cooling period started

**On to sweep 6**: `docs/superpowers/plans/2026-04-12-reorg-sweep6-casing.md`
