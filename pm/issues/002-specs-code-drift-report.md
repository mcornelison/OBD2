# Code Drift Report: Specs vs Codebase

**Reported by**: Ralph (Agent 1)
**Date**: 2026-01-29
**Priority**: Medium
**Type**: Documentation Drift

---

## Summary

9 items audited between `specs/` documentation and the actual codebase. **7 drift issues found**, 2 items confirmed correct.

---

## Drift Items

### DRIFT-001: architecture.md - Adafruit in Output Targets Diagram (Line 48)
**File**: `specs/architecture.md`, line 48
**Issue**: The ASCII diagram in Section 1 still shows `Adafruit Display` in the Output Targets box. The hardware was updated to OSOYOO 3.5" HDMI Touch display (as correctly documented on line 92).
**Fix**: Change `Adafruit` to `OSOYOO` in the diagram.

### DRIFT-002: architecture.md - Technology Stack References Adafruit/CircuitPython (Line 75)
**File**: `specs/architecture.md`, line 75
**Issue**: Technology Stack table still lists `Display | CircuitPython | 8.x | Adafruit ST7789 driver`. This contradicts the Hardware table (line 92) which correctly says OSOYOO 3.5" HDMI Touch.
**Fix**: Update the Display row to reference pygame and OSOYOO driver instead of CircuitPython/Adafruit ST7789.

### DRIFT-003: architecture.md - Display Layout Shows Wrong Dimensions (Line 432)
**File**: `specs/architecture.md`, line 432
**Issue**: Display Layout section is titled "Display Layout (240x240)" and the mockup uses 240x240 proportions. The OSOYOO display is 480x320. The StatusDisplay component in `src/hardware/` also references 480x320.
**Fix**: Update dimensions to 480x320 and adjust the layout mockup accordingly.

### DRIFT-004: methodology.md - References Deleted Manual Test Runners (Lines 132-133)
**File**: `specs/methodology.md`, lines 132-134
**Issue**: The "Running Tests" section includes:
```
# Manual test runners (when pytest unavailable)
python run_tests_config_validator.py
python run_all_tests.py
```
`run_tests_config_validator.py` was deleted in US-TD-007 along with 40 other manual test runners. `run_all_tests.py` still exists in `tests/` but the individual `run_tests_*.py` files are gone.
**Fix**: Remove the manual test runner references, or update to only reference `run_all_tests.py` if it's still intended to be used.

### DRIFT-005: architecture.md - Backup Missing from Configuration Sections Table (Lines 329-340)
**File**: `specs/architecture.md`, lines 329-340
**Issue**: The Configuration Sections table lists: application, database, api, logging, profiles, alerts, calibration. The `backup` section is missing even though backup configuration was added in US-TD-008 with 7 config keys (enabled, provider, folderPath, scheduleTime, maxBackups, compressBackups, catchupDays).
**Fix**: Add `backup` row: "Backup cloud storage, scheduling, retention settings".

### DRIFT-006: architecture.md - Domain Subpackages Table Incomplete (Lines 139-154)
**File**: `specs/architecture.md`, Section 3.2
**Issue**: The "Implemented Domain Subpackages" table lists 11 domains under `src/obd/`. However, the actual codebase also includes:
- `src/backup/` (backup_manager.py, google_drive.py, types.py, exceptions.py)
- `src/hardware/` (HardwareManager, UpsMonitor, ShutdownHandler, etc.)

These are documented in later sections (12, 13) but not reflected in the main component table. The `src/backup/` package is not mentioned in the architecture at all beyond Section 13.
**Fix**: Add `backup/` and note `hardware/` in the component overview, or add a cross-reference to Sections 12/13.

### DRIFT-007: methodology.md - References Non-Existent Test Directories (Lines 99-100)
**File**: `specs/methodology.md`, lines 96-100
**Issue**: Test Categories table lists:
- `Integration | Component interaction | tests/integration/`
- `End-to-End | Full workflow | tests/e2e/`

Neither `tests/integration/` nor `tests/e2e/` directories exist. All tests are in the flat `tests/` directory as `test_*.py` files.
**Fix**: Either create these directories and organize tests, or update the table to reflect the actual flat structure.

---

## Items Confirmed Correct (No Drift)

| Item | Status |
|------|--------|
| `backlog.json` statistics (8 total, 8 completed) | Accurate |
| `specs/plan.md` reference in methodology.md | File exists (Plan.md) |

---

## Recommendation

Drift items 001-003 are related (Adafruit/OSOYOO display update was incomplete). These could be fixed together in a single update pass.

Drift item 007 represents a structural decision: should tests be reorganized into subdirectories, or should the docs be updated to match the current flat layout?

---

*Submitted by Ralph via pm/issues/ per read-only specs/ protocol.*
