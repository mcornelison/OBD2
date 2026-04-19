# src/pi/obdii/ — OBD-II Subsystem

The largest subpackage in the Pi tier. Houses everything that reads, models,
exports, and lifecycles OBD-II data — from the Bluetooth ELM327 connection
layer up through the application orchestrator. If a module touches OBD data
or coordinates components that do, it lives here.

## Subpackages

| Subpackage | Role |
|---|---|
| `orchestrator/` | 9-module mixin package composing `ApplicationOrchestrator` (Sweep 5 / TD-003). See `orchestrator/README.md`. |
| `config/` | OBD config loading, parameter definitions, helpers (`loader.py`, `parameters.py`, `helpers.py`). |
| `data/` | Realtime PID reader + data logger (`realtime.py`, `logger.py`). |
| `drive/` | Drive detection state machine (`detector.py`). |
| `export/` | Data exporter split (Sweep 5): `exporter.py`, `realtime.py`, `summary.py`, `summary_fetchers.py`, `types.py`, `helpers.py`. |
| `service/` | Pi service manager support (script helpers extracted in Sweep 5). |
| `shutdown/` | Shutdown lifecycle: `manager.py`, `command_core.py`, `command_scripts.py`, `command_types.py`, `command_gpio.py`. |
| `simulator/` | SensorSimulator + scenario runner + simulated connection + failure injector (Sweep 5 splits). Data dirs: `profiles/`, `scenarios/`. |
| `vehicle/` | VIN decoder (NHTSA) + static vehicle data collector. |

## Top-level files (not yet in a subpackage)

| File | Role |
|---|---|
| `__init__.py` | Top-level re-exports. Structural; could be split in a future cleanup. |
| `obd_connection.py` | ELM327/Bluetooth connection wrapper. |
| `obd_parameters.py` | **PID data tables** — `STATIC_PARAMETERS`, `REALTIME_PARAMETERS`, lookup helpers. Exempted from the 300-line guideline because the bulk is data, not code (see `src/README.md` exemption block). |
| `database.py` | SQLite database class (schema extracted in Sweep 5 to `database_schema.py`). |
| `database_schema.py` | Database schema constants and table definitions (extracted in Sweep 5). |
| `data_retention.py` | Retention policy engine. |
| `statistics_engine.py` | Backwards-compat facade re-exporting `pi.analysis.engine`. |
| `data_exporter.py` | Backwards-compat facade for `obd.export` subpackage (Sweep 5 split). |
| `simulator_integration.py` | `SimulatorIntegration` orchestrator-style class; types, factory, and operation helpers extracted in Sweep 5. |
| `integration_factory.py`, `integration_operations.py`, `integration_types.py` | Extracted helpers for `simulator_integration.py` (Sweep 5). |
| `service.py` | Pi service manager; script helpers extracted in Sweep 5. |

## Facade files

`data_exporter.py` and `statistics_engine.py` are thin re-export shims kept for
backwards compatibility after the Sweep 5 splits. They are intentional — they
let existing imports like `from src.pi.obdii.data_exporter import DataExporter`
continue working without forcing every call site to update immediately. Unlike
the facades removed in Sweep 1 (which were empty re-exports from deleted
legacy modules), these facades guard an active migration.

## Dependencies

- Imports from `src.common.*` allowed
- Imports from `src.pi.*` (same-tier) allowed
- Imports from `src.server.*` **forbidden**
