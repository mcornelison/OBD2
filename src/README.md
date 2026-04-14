# src/ — OBD2v2 Source Tree

This tree is organized by deployment tier. See
`docs/superpowers/specs/2026-04-12-reorg-design.md` for the architectural
rationale.

## Top-level structure

- **`common/`** — Deployed to both tiers. Utilities, shared contracts, config schema, errors, logging.
- **`pi/`** — Deployed to Raspberry Pi only. Hardware, display, OBD data collection, orchestrator, simulator.
- **`server/`** — Deployed to Chi-Srv-01 only. FastAPI app, AI analysis, ingest, recommendation staging, MariaDB models.

## Deployment rule

The deploy script copies `src/common/ + src/<tier>/` to the appropriate host.
`src/pi/` never reaches the server. `src/server/` never reaches the Pi.

## Import rules

- Within a tier: use package-local relative imports (`from .X import Y`)
- Cross-package within a tier: use absolute imports (`from src.pi.obd.X import Y`)
- From tier to common: use absolute imports (`from src.common.config.validator import X`)
- **Tier-to-tier imports are FORBIDDEN.** `src/pi/` cannot import from `src/server/` and vice versa.

## Finding things

- Shared types (DriveLog, Recommendation, etc.): `src/common/contracts/`
- Config validation: `src/common/config/`
- Pi entry point: `src/pi/main.py`
- Pi orchestrator: `src/pi/obd/orchestrator/` (post-sweep 5)
- Server entry point: `src/server/main.py`
- Server AI: `src/server/ai/`

## File size guidance

Source files should target **≤300 lines**. This is a guideline, not a hard cap —
the list below documents files that exceed it for specific reasons. All files
not listed here are within the guideline (or have been split in Sweep 5 into
focused modules below it).

### Orchestrator subpackage (split per TD-003, Sweep 5 Task 2)

The orchestrator was decomposed into 7 mixin modules composed by a single
`ApplicationOrchestrator` class. Five of the modules exceed the 300-line cap
because splitting them further would scatter cohesive units (init/shutdown
pairs, callback chains, etc.) across files and obscure the 12-component
lifecycle contract.

- `pi/obd/orchestrator/lifecycle.py` (767) — 12 `_initialize*` + 12 `_shutdown*` methods in dependency order. Each init has a paired shutdown; splitting would scatter pairs across files and make it harder to audit that every component has matching setup/teardown.
- `pi/obd/orchestrator/core.py` (607) — `ApplicationOrchestrator` class, `__init__`, `runLoop`, `getStatus`, `createOrchestratorFromConfig` factory. The composition root; further splitting would fragment the main class definition.
- `pi/obd/orchestrator/event_router.py` (433) — 5 callback chains (reading / drive / alert / analysis / profile). Each chain is short but the set of 5 is a natural unit.
- `pi/obd/orchestrator/backup_coordinator.py` (348) — backup init, catchup, schedule, upload, cleanup. Cohesive backup lifecycle.
- `pi/obd/orchestrator/connection_recovery.py` (307) — reconnect with exponential backoff, pause/resume. Only 7 lines over; a further split would fragment the recovery protocol.

### OBD data tables

- `pi/obd/obd_parameters.py` (843) — OBD-II PID constant tables (`STATIC_PARAMETERS`, `REALTIME_PARAMETERS`) plus lookup helpers. The bulk is data, not code. Splitting PID groups into separate files would obscure the single-source-of-truth for PID metadata.

### Pi-tier single-responsibility classes

Each of these is a single cohesive class or module whose responsibilities don't
factor cleanly. Most approach but don't greatly exceed the ~700 target used by
the orchestrator split. Future refactors may revisit.

- `pi/power/power.py` (783) — `PowerMonitor` threaded class; DB and display I/O helpers were extracted in Sweep 5, class body is the remaining coherent lifecycle.
- `pi/obd/simulator_integration.py` (770) — `SimulatorIntegration` orchestrator-style class; types, factory, and operation helpers extracted in Sweep 5.
- `pi/hardware/status_display.py` (724) — hardware status rendering.
- `pi/obd/drive/detector.py` (706) — drive detection state machine.
- `pi/analysis/engine.py` (704) — statistics engine main class.
- `pi/hardware/hardware_manager.py` (692) — hardware lifecycle manager.
- `pi/obd/simulator/sensor_simulator.py` (691) — sensor data simulator.
- `pi/power/battery.py` (681) — battery state monitor.
- `pi/obd/data_retention.py` (680) — retention policy engine.
- `pi/obd/simulator/simulator_cli.py` (675) — simulator CLI dispatcher; command helpers extracted in Sweep 5.
- `pi/analysis/profile_statistics.py` (670) — per-profile statistics.
- `pi/obd/config/parameters.py` (660) — config parameter definitions.
- `pi/alert/manager.py` (652) — alert manager class.
- `pi/obd/simulator/failure_injector.py` (631) — failure injection dispatcher; failure types/factory extracted in Sweep 5.
- `pi/calibration/comparator.py` (629) — calibration comparator.
- `pi/profile/switcher.py` (624) — profile switcher state machine.
- `pi/obd/vehicle/vin_decoder.py` (620) — VIN decoder with NHTSA lookups.
- `pi/obd/simulator/simulated_vin_decoder.py` (597) — simulator VIN decoder.
- `pi/display/adapters/adafruit.py` (588) — Adafruit display driver adapter.
- `pi/obd/vehicle/static_collector.py` (570) — static vehicle data collector.
- `pi/obd/service.py` (559) — Pi service manager; script helpers extracted in Sweep 5.
- `pi/obd/config/loader.py` (542) — config file loader.
- `pi/obd/obd_connection.py` (533) — ELM327 connection wrapper.
- `pi/calibration/manager.py` (529) — calibration manager.
- `pi/hardware/ups_monitor.py` (528) — UPS hat monitor.
- `pi/obd/__init__.py` (525) — top-level package re-exports (structural; future cleanup could split re-exports by subsystem).
- `pi/display/drivers/minimal.py` (525) — minimal display driver.
- `pi/display/manager.py` (523) — display manager dispatcher.
- `pi/obd/data/realtime.py` (511) — realtime PID reader.
- `pi/profile/manager.py` (510) — profile manager.
- `pi/obd/simulator/vehicle_profile.py` (506) — vehicle simulator profile.
- `pi/hardware/telemetry_logger.py` (506) — telemetry logger.
- `pi/backup/backup_manager.py` (497) — backup manager (just under 500 but above 300).
- `pi/obd/simulator/scenario_runner.py` (473) — scenario runner (from Sweep 5 drive_scenario split).
- `pi/obd/simulator/simulated_connection.py` (461) — simulated OBD connection.
- `pi/hardware/i2c_client.py` (447) — I2C client wrapper.
- `pi/obd/shutdown/manager.py` (442) — shutdown manager.
- `pi/obd/database.py` (422) — database class (trimmed in Sweep 5; schema extracted to `database_schema.py`).
- `pi/backup/google_drive.py` (422) — Google Drive upload client.
- `pi/obd/database_schema.py` (418) — database schema definitions (extracted in Sweep 5).
- `pi/display/screens/fuel_detail.py` (408) — fuel detail screen.
- `pi/obd/export/realtime.py` (403) — realtime exporter (from Sweep 5 data_exporter split).
- `pi/obd/shutdown/command_core.py` (393) — shutdown command core (from Sweep 5 command split).
- `pi/obd/shutdown/command_scripts.py` (382) — shutdown command scripts (from Sweep 5 command split).
- `pi/calibration/types.py` (378) — calibration type definitions.
- `pi/hardware/shutdown_handler.py` (373) — shutdown signal handler.
- `pi/display/screens/parked_mode.py` (367) — parked-mode screen.
- `pi/power/readers.py` (357) — power reader adapters.
- `pi/hardware/gpio_button.py` (356) — GPIO button handler.
- `pi/profile/helpers.py` (354) — profile helper functions.
- `pi/calibration/session.py` (351) — calibration session.
- `pi/obd/simulator/simulator_status.py` (348) — simulator status reporter.
- `pi/display/screens/system_detail.py` (348) — system detail screen.
- `pi/obd/config/helpers.py` (346) — config helper functions.
- `pi/alert/timing_thresholds.py` (346) — timing thresholds.
- `pi/obd/export/exporter.py` (343) — export dispatcher (from Sweep 5 data_exporter split).
- `pi/obd/export/summary.py` (341) — summary exporter (from Sweep 5 data_exporter split).
- `pi/obd/simulator/scenario_builtins.py` (338) — builtin scenarios (from Sweep 5 drive_scenario split).
- `pi/power/types.py` (334) — power type definitions.
- `pi/analysis/helpers.py` (333) — analysis helper functions.
- `pi/obd/data/logger.py` (322) — data logger.
- `pi/power/helpers.py` (320) — power helper functions.
- `pi/display/screens/primary_screen.py` (318) — primary display screen.
- `pi/display/screens/touch_interactions.py` (314) — touch interaction handlers.
- `pi/obd/simulator/failure_types.py` (306) — failure type definitions (from Sweep 5 failure_injector split).
- `pi/display/drivers/developer.py` (306) — developer display driver.

### Server-tier modules

- `server/ai/analyzer.py` (666) — `AiAnalyzer` class; DB and Ollama helpers extracted in Sweep 5.
- `server/ai/ollama.py` (643) — Ollama client wrapper.
- `server/ai/ranker.py` (625) — recommendation ranker.
- `server/ai/prompt_template.py` (616) — prompt template assembly.
- `server/ai/types.py` (530) — AI type definitions.
- `server/ai/helpers.py` (473) — AI helper functions.

### Common-tier modules

- `common/errors/handler.py` (340) — error classifier (5-tier error handling system).
