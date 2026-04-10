# PRD: Module Refactoring and End-to-End Testing

**Parent Backlog Item**: N/A (architectural improvement)
**Status**: Complete

## Introduction

The Eclipse OBD-II codebase has grown significantly, with many files exceeding 800-1400 lines. This makes it difficult for AI programming agents to work on focused chunks and increases cognitive load for developers. This PRD defines a refactoring effort to split large files into single-responsibility modules organized by domain, followed by end-to-end verification in both simulation and non-simulation modes.

## Goals

- Split all Python files into single-responsibility modules
- Organize modules into domain-specific subpackages
- Ensure all existing tests pass after refactoring
- Create test files for each new module
- Document the new module structure
- Verify full end-to-end functionality in simulation mode
- Verify application startup in non-simulation mode (hardware optional)

## Current State Analysis

**Files over 800 lines requiring refactoring:**

| File | Lines | Proposed Domain |
|------|-------|-----------------|
| display_manager.py | 1412 | display/ |
| data_exporter.py | 1309 | export/ |
| calibration_manager.py | 1250 | calibration/ |
| ai_analyzer.py | 1242 | ai/ |
| drive_scenario.py | 1234 | simulator/scenario/ |
| power_monitor.py | 1205 | power/ |
| statistics_engine.py | 1177 | analysis/ |
| shutdown_command.py | 1159 | shutdown/ |
| simulator_integration.py | 1078 | simulator/ |
| data_logger.py | 1072 | data/ |
| alert_manager.py | 1030 | alert/ |
| simulator_cli.py | 991 | simulator/cli/ |
| failure_injector.py | 984 | simulator/failure/ |
| drive_detector.py | 963 | drive/ |
| battery_monitor.py | 960 | power/ |
| ai_prompt_template.py | 892 | ai/ |
| vin_decoder.py | 891 | vehicle/ |
| obd_config_loader.py | 871 | config/ |
| calibration_comparator.py | 859 | calibration/ |
| obd_parameters.py | 844 | config/ |

## User Stories

---

### US-001: Create domain subpackage structure
**Description:** As a developer, I want a clear subpackage structure so that related modules are grouped together.

**Acceptance Criteria:**
- [ ] Create `src/obd/ai/` subpackage with `__init__.py`
- [ ] Create `src/obd/alert/` subpackage with `__init__.py`
- [ ] Create `src/obd/analysis/` subpackage with `__init__.py`
- [ ] Create `src/obd/calibration/` subpackage with `__init__.py`
- [ ] Create `src/obd/config/` subpackage with `__init__.py`
- [ ] Create `src/obd/data/` subpackage with `__init__.py`
- [ ] Create `src/obd/display/` subpackage with `__init__.py`
- [ ] Create `src/obd/drive/` subpackage with `__init__.py`
- [ ] Create `src/obd/export/` subpackage with `__init__.py`
- [ ] Create `src/obd/power/` subpackage with `__init__.py`
- [ ] Create `src/obd/profile/` subpackage with `__init__.py`
- [ ] Create `src/obd/service/` subpackage with `__init__.py`
- [ ] Create `src/obd/shutdown/` subpackage with `__init__.py`
- [ ] Create `src/obd/vehicle/` subpackage with `__init__.py`
- [ ] Update `src/obd/__init__.py` to re-export from subpackages (backward compatibility)
- [ ] Typecheck/lint passes

---

### US-002: Refactor display_manager.py (1412 lines)
**Description:** As a developer, I want display_manager split into focused modules so each has a single responsibility.

**Acceptance Criteria:**
- [ ] Create `src/obd/display/types.py` - DisplayMode enum, StatusInfo, AlertInfo dataclasses
- [ ] Create `src/obd/display/exceptions.py` - DisplayError, DisplayInitializationError, DisplayOutputError
- [ ] Create `src/obd/display/drivers/base.py` - BaseDisplayDriver abstract class
- [ ] Create `src/obd/display/drivers/headless.py` - HeadlessDisplayDriver
- [ ] Create `src/obd/display/drivers/minimal.py` - MinimalDisplayDriver
- [ ] Create `src/obd/display/drivers/developer.py` - DeveloperDisplayDriver
- [ ] Create `src/obd/display/manager.py` - DisplayManager class
- [ ] Create `src/obd/display/helpers.py` - createDisplayManagerFromConfig, getDisplayModeFromConfig, isDisplayAvailable
- [ ] Move adafruit_display.py to `src/obd/display/adapters/adafruit.py`
- [ ] Update `src/obd/display/__init__.py` with all exports
- [ ] All existing display tests pass
- [ ] Create `tests/test_display_types.py` for new types module
- [ ] Typecheck/lint passes

---

### US-003: Refactor data_exporter.py (1309 lines)
**Description:** As a developer, I want data_exporter split so CSV, JSON, and summary exports are separate.

**Acceptance Criteria:**
- [ ] Create `src/obd/export/types.py` - ExportFormat enum, ExportResult, SummaryExportResult dataclasses
- [ ] Create `src/obd/export/exceptions.py` - ExportError, InvalidDateRangeError, ExportDirectoryError
- [ ] Create `src/obd/export/csv_exporter.py` - CSV export logic
- [ ] Create `src/obd/export/json_exporter.py` - JSON export logic
- [ ] Create `src/obd/export/summary_exporter.py` - Summary export logic (statistics, recommendations, alerts)
- [ ] Create `src/obd/export/base.py` - BaseExporter with shared query building
- [ ] Create `src/obd/export/helpers.py` - Factory functions and convenience helpers
- [ ] Update `src/obd/export/__init__.py` with all exports
- [ ] All existing export tests pass
- [ ] Create test file for each new module
- [ ] Typecheck/lint passes

---

### US-004: Refactor calibration_manager.py (1250 lines)
**Description:** As a developer, I want calibration split into session management, data collection, and export.

**Acceptance Criteria:**
- [ ] Create `src/obd/calibration/types.py` - CalibrationState enum, CalibrationSession, CalibrationReading, CalibrationStats dataclasses
- [ ] Create `src/obd/calibration/exceptions.py` - CalibrationError, CalibrationSessionError
- [ ] Create `src/obd/calibration/session.py` - Session lifecycle management (start, end, list)
- [ ] Create `src/obd/calibration/collector.py` - Reading collection and storage
- [ ] Create `src/obd/calibration/export.py` - Session export to CSV/JSON
- [ ] Create `src/obd/calibration/manager.py` - CalibrationManager orchestration
- [ ] Move calibration_comparator.py to `src/obd/calibration/comparator.py`
- [ ] Update `src/obd/calibration/__init__.py` with all exports
- [ ] All existing calibration tests pass
- [ ] Typecheck/lint passes

---

### US-005: Refactor ai_analyzer.py (1242 lines)
**Description:** As a developer, I want AI components split by responsibility.

**Acceptance Criteria:**
- [ ] Create `src/obd/ai/types.py` - AnalyzerState enum, AiRecommendation, AnalysisResult, AnalyzerStats dataclasses
- [ ] Create `src/obd/ai/exceptions.py` - AiAnalyzerError and subclasses
- [ ] Create `src/obd/ai/data_preparation.py` - Data window preparation logic
- [ ] Create `src/obd/ai/analyzer.py` - Core AiAnalyzer class
- [ ] Move ai_prompt_template.py to `src/obd/ai/prompt_template.py`
- [ ] Move ollama_manager.py to `src/obd/ai/ollama.py`
- [ ] Move recommendation_ranker.py to `src/obd/ai/ranker.py`
- [ ] Create `src/obd/ai/helpers.py` - Factory and convenience functions
- [ ] Update `src/obd/ai/__init__.py` with all exports
- [ ] All existing AI tests pass
- [ ] Typecheck/lint passes

---

### US-006: Refactor power_monitor.py and battery_monitor.py (2165 lines combined)
**Description:** As a developer, I want power monitoring components organized together.

**Acceptance Criteria:**
- [ ] Create `src/obd/power/types.py` - PowerSource, PowerMonitorState, BatteryState enums, VoltageReading, PowerReading dataclasses
- [ ] Create `src/obd/power/exceptions.py` - PowerMonitorError, BatteryMonitorError
- [ ] Create `src/obd/power/battery.py` - BatteryMonitor class
- [ ] Create `src/obd/power/power.py` - PowerMonitor class
- [ ] Create `src/obd/power/readers.py` - Voltage reader factory functions (ADC, I2C)
- [ ] Create `src/obd/power/helpers.py` - Config helpers
- [ ] Update `src/obd/power/__init__.py` with all exports
- [ ] All existing power/battery tests pass
- [ ] Typecheck/lint passes

---

### US-007: Refactor statistics_engine.py (1177 lines)
**Description:** As a developer, I want statistics calculation separated from storage.

**Acceptance Criteria:**
- [ ] Create `src/obd/analysis/types.py` - AnalysisState enum, ParameterStatistics, AnalysisResult, EngineStats dataclasses
- [ ] Create `src/obd/analysis/exceptions.py` - StatisticsError and subclasses
- [ ] Create `src/obd/analysis/calculations.py` - Pure calculation functions (mean, mode, std, outliers)
- [ ] Create `src/obd/analysis/engine.py` - StatisticsEngine class
- [ ] Move profile_statistics.py to `src/obd/analysis/profile_statistics.py`
- [ ] Create `src/obd/analysis/helpers.py` - Factory functions
- [ ] Update `src/obd/analysis/__init__.py` with all exports
- [ ] All existing statistics tests pass
- [ ] Typecheck/lint passes

---

### US-008: Refactor data_logger.py (1072 lines)
**Description:** As a developer, I want data logging split into single readings and realtime polling.

**Acceptance Criteria:**
- [ ] Create `src/obd/data/types.py` - LoggingState enum, LoggedReading, LoggingStats dataclasses
- [ ] Create `src/obd/data/exceptions.py` - DataLoggerError and subclasses
- [ ] Create `src/obd/data/logger.py` - ObdDataLogger for single readings
- [ ] Create `src/obd/data/realtime.py` - RealtimeDataLogger for continuous polling
- [ ] Create `src/obd/data/helpers.py` - Factory and verification functions
- [ ] Update `src/obd/data/__init__.py` with all exports
- [ ] All existing data logger tests pass
- [ ] Typecheck/lint passes

---

### US-009: Refactor alert_manager.py (1030 lines)
**Description:** As a developer, I want alert types, thresholds, and manager separated.

**Acceptance Criteria:**
- [ ] Create `src/obd/alert/types.py` - AlertDirection, AlertState enums, AlertThreshold, AlertEvent, AlertStats dataclasses
- [ ] Create `src/obd/alert/exceptions.py` - AlertError and subclasses
- [ ] Create `src/obd/alert/thresholds.py` - Threshold checking logic
- [ ] Create `src/obd/alert/manager.py` - AlertManager class
- [ ] Create `src/obd/alert/helpers.py` - Factory and config helpers
- [ ] Update `src/obd/alert/__init__.py` with all exports
- [ ] All existing alert tests pass
- [ ] Typecheck/lint passes

---

### US-010: Refactor shutdown modules (1600 lines combined)
**Description:** As a developer, I want shutdown components logically organized.

**Acceptance Criteria:**
- [ ] Create `src/obd/shutdown/types.py` - ShutdownState enum, ShutdownConfig, ShutdownResult dataclasses
- [ ] Create `src/obd/shutdown/exceptions.py` - ShutdownError and subclasses
- [ ] Create `src/obd/shutdown/manager.py` - ShutdownManager (signal handling)
- [ ] Create `src/obd/shutdown/command.py` - ShutdownCommand (process termination)
- [ ] Create `src/obd/shutdown/gpio.py` - GpioButtonTrigger
- [ ] Create `src/obd/shutdown/scripts.py` - Script generation functions
- [ ] Update `src/obd/shutdown/__init__.py` with all exports
- [ ] All existing shutdown tests pass
- [ ] Typecheck/lint passes

---

### US-011: Refactor config modules (1715 lines combined)
**Description:** As a developer, I want config loading and parameter definitions separated.

**Acceptance Criteria:**
- [ ] Create `src/obd/config/types.py` - ParameterInfo dataclass, category constants
- [ ] Create `src/obd/config/exceptions.py` - ObdConfigError
- [ ] Create `src/obd/config/loader.py` - Config loading and validation
- [ ] Create `src/obd/config/parameters.py` - STATIC_PARAMETERS, REALTIME_PARAMETERS definitions
- [ ] Create `src/obd/config/helpers.py` - Parameter lookup and config access functions
- [ ] Create `src/obd/config/simulator.py` - Simulator config helpers
- [ ] Update `src/obd/config/__init__.py` with all exports
- [ ] All existing config tests pass
- [ ] Typecheck/lint passes

---

### US-012: Refactor profile modules (1642 lines combined)
**Description:** As a developer, I want profile management components organized together.

**Acceptance Criteria:**
- [ ] Create `src/obd/profile/types.py` - Profile dataclass, ProfileChangeEvent
- [ ] Create `src/obd/profile/exceptions.py` - ProfileError and subclasses
- [ ] Create `src/obd/profile/manager.py` - ProfileManager CRUD operations
- [ ] Create `src/obd/profile/switcher.py` - ProfileSwitcher drive-aware switching
- [ ] Create `src/obd/profile/helpers.py` - Factory and config functions
- [ ] Update `src/obd/profile/__init__.py` with all exports
- [ ] All existing profile tests pass
- [ ] Typecheck/lint passes

---

### US-013: Refactor vehicle modules (1665 lines combined)
**Description:** As a developer, I want VIN decoding and static data collection grouped.

**Acceptance Criteria:**
- [ ] Create `src/obd/vehicle/types.py` - VinDecodeResult, StaticReading, CollectionResult dataclasses
- [ ] Create `src/obd/vehicle/exceptions.py` - VinDecoderError, StaticDataError and subclasses
- [ ] Create `src/obd/vehicle/vin_decoder.py` - VinDecoder class
- [ ] Create `src/obd/vehicle/static_collector.py` - StaticDataCollector class
- [ ] Create `src/obd/vehicle/helpers.py` - Factory and convenience functions
- [ ] Update `src/obd/vehicle/__init__.py` with all exports
- [ ] All existing VIN/static tests pass
- [ ] Typecheck/lint passes

---

### US-014: Refactor drive_detector.py (963 lines)
**Description:** As a developer, I want drive detection types and logic separated.

**Acceptance Criteria:**
- [ ] Create `src/obd/drive/types.py` - DriveState, DetectorState enums, DriveSession, DetectorConfig, DetectorStats dataclasses
- [ ] Create `src/obd/drive/exceptions.py` - DriveDetectorError and subclasses
- [ ] Create `src/obd/drive/detector.py` - DriveDetector class
- [ ] Create `src/obd/drive/helpers.py` - Factory and config functions
- [ ] Update `src/obd/drive/__init__.py` with all exports
- [ ] All existing drive detector tests pass
- [ ] Typecheck/lint passes

---

### US-015: Refactor service.py (804 lines)
**Description:** As a developer, I want systemd service generation modularized.

**Acceptance Criteria:**
- [ ] Create `src/obd/service/types.py` - ServiceConfig, ServiceStatus dataclasses
- [ ] Create `src/obd/service/exceptions.py` - ServiceError and subclasses
- [ ] Create `src/obd/service/systemd.py` - Systemd service file generation
- [ ] Create `src/obd/service/manager.py` - ServiceManager class
- [ ] Create `src/obd/service/scripts.py` - Install/uninstall script generation
- [ ] Update `src/obd/service/__init__.py` with all exports
- [ ] All existing service tests pass
- [ ] Typecheck/lint passes

---

### US-016: Refactor simulator drive_scenario.py (1234 lines)
**Description:** As a developer, I want scenario phases, runner, and loading separated.

**Acceptance Criteria:**
- [ ] Create `src/obd/simulator/scenario/types.py` - ScenarioState enum, DrivePhase, DriveScenario dataclasses
- [ ] Create `src/obd/simulator/scenario/exceptions.py` - ScenarioError and subclasses
- [ ] Create `src/obd/simulator/scenario/runner.py` - DriveScenarioRunner class
- [ ] Create `src/obd/simulator/scenario/loader.py` - Load/save/list functions
- [ ] Create `src/obd/simulator/scenario/builtin.py` - Built-in scenario definitions
- [ ] Update `src/obd/simulator/scenario/__init__.py` with all exports
- [ ] All existing scenario tests pass
- [ ] Typecheck/lint passes

---

### US-017: Refactor simulator failure_injector.py (984 lines)
**Description:** As a developer, I want failure types and injection logic separated.

**Acceptance Criteria:**
- [ ] Create `src/obd/simulator/failure/types.py` - FailureType enum, FailureConfig, ScheduledFailure dataclasses
- [ ] Create `src/obd/simulator/failure/injector.py` - FailureInjector class
- [ ] Create `src/obd/simulator/failure/scheduler.py` - Scheduled failure handling
- [ ] Update `src/obd/simulator/failure/__init__.py` with all exports
- [ ] All existing failure injector tests pass
- [ ] Typecheck/lint passes

---

### US-018: Refactor simulator_cli.py (991 lines)
**Description:** As a developer, I want CLI commands and input handling separated.

**Acceptance Criteria:**
- [ ] Create `src/obd/simulator/cli/types.py` - CliState, CommandType enums, CommandResult dataclass
- [ ] Create `src/obd/simulator/cli/commands.py` - Command execution logic
- [ ] Create `src/obd/simulator/cli/input.py` - Platform-specific input handling
- [ ] Create `src/obd/simulator/cli/cli.py` - SimulatorCli class
- [ ] Update `src/obd/simulator/cli/__init__.py` with all exports
- [ ] All existing CLI tests pass
- [ ] Typecheck/lint passes

---

### US-019: Update backward compatibility exports
**Description:** As a developer, I want existing imports to continue working after refactoring.

**Acceptance Criteria:**
- [ ] Update `src/obd/__init__.py` to re-export all public classes/functions from subpackages
- [ ] All imports like `from src.obd import DisplayManager` continue to work
- [ ] All imports like `from src.obd.display_manager import DisplayManager` emit deprecation warning
- [ ] Document migration path in docstrings
- [ ] All existing tests pass without modification
- [ ] Typecheck/lint passes

---

### US-020: Create module structure documentation
**Description:** As a developer, I want clear documentation of the new module structure.

**Acceptance Criteria:**
- [ ] Create `docs/module-structure.md` with:
  - Directory tree of new structure
  - Purpose of each subpackage
  - Migration guide from old imports to new
  - Diagram showing module dependencies
- [ ] Update `CLAUDE.md` with new module organization
- [ ] Update `specs/architecture.md` with new package structure
- [ ] Typecheck/lint passes

---

### US-021: End-to-end test in simulation mode
**Description:** As a developer, I want to verify all features work in simulation mode.

**Acceptance Criteria:**
- [ ] Create `tests/e2e/test_simulation_mode.py` integration test
- [ ] Test application startup with `--simulate` flag
- [ ] Test OBD connection simulation (connect, query, disconnect)
- [ ] Test VIN decoding via SimulatedVinDecoder
- [ ] Test static data collection in simulation
- [ ] Test realtime data logging for 10 seconds
- [ ] Test drive detection (start → running → stop)
- [ ] Test statistics calculation after simulated drive
- [ ] Test AI analysis triggering (mock ollama if unavailable)
- [ ] Test alert threshold checking
- [ ] Test display updates in developer mode
- [ ] Test data export (CSV and JSON)
- [ ] Test graceful shutdown
- [ ] All tests pass
- [ ] Document test results in `docs/e2e-test-results.md`

---

### US-022: End-to-end verification without simulation
**Description:** As a developer, I want to verify the app starts correctly in normal mode.

**Acceptance Criteria:**
- [ ] Create `tests/e2e/test_normal_mode.py` integration test
- [ ] Test application startup without `--simulate` flag
- [ ] Test configuration loading and validation
- [ ] Test database initialization
- [ ] Test display manager initialization (headless mode)
- [ ] Test graceful handling when OBD hardware unavailable
- [ ] Test service file generation
- [ ] Test shutdown script generation
- [ ] All tests pass (or skip with clear reason if hardware required)
- [ ] Document any hardware-dependent tests

---

### US-029: Rename main.py to eclipse.py
**Description:** As a developer, I want the entry point named after the project so it's more memorable and fun.

**Acceptance Criteria:**
- [ ] Rename src/main.py to src/eclipse.py
- [ ] Update all references in documentation (CLAUDE.md, README if exists)
- [ ] Update any shell scripts or service files that reference main.py
- [ ] Add a fun ASCII art banner or project tagline to startup output
- [ ] Update test imports in tests/test_main.py (rename to tests/test_eclipse.py)
- [ ] Application runs successfully: `python src/eclipse.py --help`
- [ ] Application runs in sim mode: `python src/eclipse.py --simulate`
- [ ] Typecheck passes

---

## Functional Requirements

- FR-1: Each Python module must have a single, clear responsibility
- FR-2: All dataclasses and enums must be in `*_types.py` or `types.py` files
- FR-3: All custom exceptions must be in `*_exceptions.py` or `exceptions.py` files
- FR-4: All helper/factory functions must be in `*_helpers.py` or `helpers.py` files
- FR-5: Each subpackage must have an `__init__.py` that exports all public members
- FR-6: Backward compatibility must be maintained via `src/obd/__init__.py` re-exports
- FR-7: Each new module must have a corresponding test file
- FR-8: All existing tests must pass after refactoring
- FR-9: Module dependencies must flow downward (no circular imports)
- FR-10: End-to-end tests must cover all major features

## Non-Goals

- No new features during refactoring (pure restructuring)
- No changes to business logic or algorithms
- No database schema changes
- No configuration format changes
- No API changes to public functions/classes
- No performance optimization (focus on organization)

## Technical Considerations

- Use relative imports within subpackages (e.g., `from .types import ...`)
- Use absolute imports across subpackages (e.g., `from src.obd.data.types import ...`)
- Avoid circular imports by careful dependency ordering
- Types modules should have no dependencies on other project modules
- Consider using `TYPE_CHECKING` for type hints to avoid runtime circular imports
- Preserve all docstrings and type hints during moves

## Success Metrics

- All 22 user stories completed with passing tests
- Zero regression in existing functionality
- Each module under 400 lines (target)
- Clear single responsibility for each module
- Documentation complete and accurate
- Full end-to-end test suite passes in simulation mode

## Open Questions

- Should we create a `src/obd/connection/` subpackage for OBD connection, or keep it at top level since it's the core interface?
- Should simulator subpackages mirror main package structure (e.g., `simulator/ai/` for SimulatedVinDecoder)?
- What's the deprecation timeline for old import paths?

---

## Implementation Order

Recommended order to minimize conflicts:

1. **US-001**: Create subpackage structure (foundation)
2. **US-011**: Config modules (no dependencies)
3. **US-002**: Display modules (UI foundation)
4. **US-008**: Data modules (core data flow)
5. **US-013**: Vehicle modules (VIN, static data)
6. **US-014**: Drive detector
7. **US-007**: Analysis/statistics
8. **US-009**: Alert manager
9. **US-006**: Power modules
10. **US-012**: Profile modules
11. **US-004**: Calibration modules
12. **US-005**: AI modules
13. **US-003**: Export modules
14. **US-010**: Shutdown modules
15. **US-015**: Service modules
16. **US-016-018**: Simulator submodules
17. **US-019**: Backward compatibility
18. **US-020**: Documentation
19. **US-021**: E2E simulation test
20. **US-022**: E2E normal mode test
21. **US-029**: Rename main.py to eclipse.py (fun finale!)
