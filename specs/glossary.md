# Glossary

## Overview

This document defines terms, acronyms, and domain-specific language used in this project. Keep definitions concise and practical.

**Last Updated**: 2026-01-31

---

## Terms

### A

**Acceptance Criteria**
: Specific, verifiable conditions that must be met for a user story to be considered complete. Each criterion should be testable with a YES/NO answer.

**Anti-pattern**
: A common solution to a problem that is ineffective or counterproductive. Documented to help developers avoid known pitfalls.

### B

**Backlog**
: A prioritized list of tasks and features to be implemented. Stored in `specs/backlog.json`.

**BCM (Broadcom)**
: Pin numbering scheme for Raspberry Pi GPIO that uses the Broadcom SoC channel numbers. Example: GPIO17 refers to BCM pin 17, not physical pin 17. Used by gpiozero by default.

### C

**camelCase**
: Naming convention where words are joined without spaces, first word lowercase, subsequent words capitalized. Example: `getUserData`, `recordCount`. Used for Python functions and variables in this project.

**Configuration-driven**
: Design pattern where behavior is controlled by external configuration files rather than hardcoded values. Enables flexibility without code changes.

### D

**DSM (Diamond Star Motors)**
: Joint venture between Mitsubishi and Chrysler that produced the Eclipse, Talon, and Laser (1990-1999). The 2G DSM refers to the 1995-1999 models. The project vehicle is a 1998 Eclipse GST (2G DSM, 4G63 turbo).

**Dependency Injection**
: Design pattern where dependencies are passed to a component rather than created internally. In this project, configuration is injected as a dictionary parameter.

**Drive Detector**
: Component that monitors RPM and vehicle speed to detect engine running state. Uses state machine pattern (STOPPED → STARTING → RUNNING → STOPPING → STOPPED) with duration-based transitions.

**Drive Phase**
: A single segment of a drive scenario with target values for RPM, speed, throttle, and gear. Phases have configurable duration and support smooth transitions between states.

**Drive Scenario**
: A predefined sequence of drive phases for repeatable test cycles. Scenarios support looping (0=none, -1=infinite, N times) and include built-in scenarios like cold_start, city_driving, highway_cruise.

### E

**ECMLink V3**
: Next-generation tuning and datalogging tool from [ECMTuning](https://www.ecmtuning.com/) for 1990-1999 DSM and EVO 1-3 vehicles. Provides direct access to fuel maps, timing maps, airflow tables, and boost control via a drop-in flash device that replaces the factory EPROM. Logs at 1000+ samples/sec. The project's ultimate goal is to feed OBD-II analysis data into ECMLink tuning decisions. Not yet installed in the vehicle.

**ECU (Engine Control Unit)**
: The vehicle's onboard computer that controls engine operation -- fuel injection, ignition timing, idle speed, boost control. The stock ECU can be replaced with a programmable ECU running ECMLink for custom tuning.

**ELM327**
: A microcontroller chip that translates OBD-II protocols to serial communication. Used in most Bluetooth OBD-II dongles to interface between the vehicle's diagnostic port and external devices.

**Exponential Backoff**
: Retry strategy where wait time increases exponentially with each attempt. Example: 1s, 2s, 4s, 8s, 16s. Used for handling transient failures.

### G

**GpioButton**
: Component in `src/hardware/` that monitors physical buttons via Raspberry Pi GPIO. Supports debounce (bounce_time), long press detection (hold_time), and callbacks for button events.

### F

**Fail Fast**
: Design principle where errors are detected and reported as early as possible, typically at startup. Configuration errors should fail fast with clear messages.

**Failure Injection**
: Testing technique where faults are deliberately introduced to verify error handling. The simulator supports five failure types: CONNECTION_DROP, SENSOR_FAILURE, INTERMITTENT_SENSOR, OUT_OF_RANGE, and DTC_CODES.

### H

**HardwareManager**
: Central component in `src/hardware/` that coordinates all Raspberry Pi hardware modules: UpsMonitor, ShutdownHandler, GpioButton, StatusDisplay, and TelemetryLogger. Handles initialization order, component wiring, and lifecycle management.

### I

**Idempotent**
: An operation that produces the same result regardless of how many times it is executed. Critical for reliable ETL pipelines and retry logic.

### J

**Jaccard Similarity**
: A measure of text similarity calculated as the size of the intersection divided by the size of the union of two word sets. Used for AI recommendation deduplication with a 70% threshold.

### N

**NHTSA API**
: National Highway Traffic Safety Administration Vehicle Product Information Catalog API. Used to decode VINs and retrieve vehicle specifications. Returns JSON data including make, model, year, engine, and fuel type.

### O

**OBD-II (On-Board Diagnostics II)**
: A standardized vehicle diagnostic system that provides access to various vehicle subsystems. All vehicles sold in the US since 1996 are required to support OBD-II.

**ollama**
: A local LLM (Large Language Model) inference server. This project uses ollama with small models like Gemma2 (2b) or Qwen2.5 (3b) for AI-powered performance recommendations.

### P

**PascalCase**
: Naming convention where words are joined without spaces, each word capitalized. Example: `ConfigValidator`, `DataProcessor`. Used for Python classes in this project.

**PII (Personally Identifiable Information)**
: Data that can identify an individual, such as names, email addresses, SSNs. Must be masked in logs and protected in storage.

**PID (Parameter ID)**
: A code used to request data from a vehicle via OBD-II. Examples: RPM (0x0C), Vehicle Speed (0x0D), Coolant Temperature (0x05). Static PIDs are queried once; realtime PIDs are polled continuously.

**PRD (Product Requirements Document)**
: A document that describes what a feature should do, including goals, user stories, and acceptance criteria. Stored in `specs/tasks/`.

### R

**Ralph**
: The autonomous agent system used for executing user stories. Spawns fresh Claude instances per iteration with no memory between runs.

**Re-Export Module**
: A Python module that imports symbols from another location and exposes them through its own namespace. Used for backward compatibility when code moves to subpackages. Example: `data_logger.py` re-exports from `obd.data/`.

**Retryable Error**
: An error caused by transient conditions (network timeout, rate limit) that may succeed if attempted again. Should use exponential backoff.

### S

**Sensor Simulator**
: Component that generates realistic OBD-II sensor values using physics-based modeling. Simulates throttle response, gear ratios, coolant warmup, and sensor noise.

**Simulator Mode**
: Application mode where SimulatedObdConnection replaces real hardware. Enabled via `--simulate` CLI flag or `simulator.enabled` config. Uses VehicleProfile for vehicle characteristics.

**ShutdownHandler**
: Component in `src/hardware/` that manages graceful shutdown on power loss. Monitors UPS power source changes, schedules delayed shutdown when switching to battery, and handles low battery immediate shutdown.

**snake_case**
: Naming convention where words are joined with underscores, all lowercase. Example: `user_accounts`, `created_at`. Used for SQL tables and columns in this project.

**Skill**
: A documented procedure for accomplishing a specific task. Skills define inputs, process steps, and expected outputs. Stored as `*_skill.md` files.

**StatusDisplay**
: Component in `src/hardware/` that renders system status on the OSOYOO 3.5" HDMI touch display (480x320). Shows battery status, power source, OBD connection, error counts, uptime, and IP address.

### T

**TDD (Test-Driven Development)**
: Development methodology where tests are written before implementation code. The cycle is: write failing test → write code to pass → refactor.

**TelemetryLogger**
: Component in `src/hardware/` that logs system telemetry (battery, CPU temp, disk space) to rotating JSON files. Uses RotatingFileHandler with configurable size limits and retention.

**Token Budget**
: The maximum number of tokens available for a task in an LLM context window. User stories must fit within the token budget (typically 150K-175K tokens).

**TYPE_CHECKING**
: A Python `typing` module constant that is `False` at runtime but `True` during static type checking. Used to import types that would cause circular imports at runtime: `if TYPE_CHECKING: from module import Type`.

### U

**UpsMonitor**
: Component in `src/hardware/` that monitors the Geekworm X1209 UPS HAT via I2C. Reads battery voltage, current, percentage, and power source. Supports polling with callbacks for power source changes.

**User Story**
: A description of a feature from the user's perspective, following the format: "As a [user], I want [feature] so that [benefit]."

### V

**Vehicle Profile**
: Dataclass defining vehicle characteristics for simulation: VIN, make, model, year, engine specs, RPM limits, speed limits, and temperature thresholds. Stored as JSON files in `src/obd/simulator/profiles/`.

**VIN (Vehicle Identification Number)**
: A unique 17-character identifier assigned to every vehicle. Contains encoded information about manufacturer, model, year, and production sequence. Excludes letters I, O, Q to avoid confusion with 1 and 0.

### W

**WAL (Write-Ahead Logging)**
: A SQLite journaling mode that improves concurrent read/write performance. Enabled via `PRAGMA journal_mode = WAL`. Recommended for this project's database.

---

## Acronyms

| Acronym | Meaning |
|---------|---------|
| ADC | Analog-to-Digital Converter |
| API | Application Programming Interface |
| CLI | Command Line Interface |
| CI/CD | Continuous Integration / Continuous Deployment |
| DDL | Data Definition Language (SQL schema statements) |
| DRY | Don't Repeat Yourself |
| DSM | Diamond Star Motors |
| ECU | Engine Control Unit |
| EGR | Exhaust Gas Recirculation |
| ETL | Extract, Transform, Load |
| FK | Foreign Key |
| GPIO | General Purpose Input/Output |
| I2C | Inter-Integrated Circuit (serial protocol) |
| JSON | JavaScript Object Notation |
| LLM | Large Language Model |
| MAP | Manifold Absolute Pressure (sensor) |
| MAF | Mass Air Flow (sensor) |
| NHTSA | National Highway Traffic Safety Administration |
| OAuth | Open Authorization |
| OBD | On-Board Diagnostics |
| PID | Parameter Identifier |
| PII | Personally Identifiable Information |
| PRD | Product Requirements Document |
| REST | Representational State Transfer |
| RPM | Revolutions Per Minute |
| SCD | Slowly Changing Dimension |
| SIM | Simulation Mode |
| SQL | Structured Query Language |
| TDD | Test-Driven Development |
| UTC | Coordinated Universal Time |
| VIN | Vehicle Identification Number |
| WAL | Write-Ahead Logging |

---

## Adding New Terms

When adding a new term:
1. Place it alphabetically within the appropriate section
2. Use the definition list format (term on one line, definition with `: ` prefix on next)
3. Keep definitions concise (1-2 sentences)
4. Include an example if it helps clarify
5. Update the "Last Updated" date

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-26 | Knowledge Update | Added Raspberry Pi hardware terms: BCM, GpioButton, HardwareManager, ShutdownHandler, StatusDisplay, TelemetryLogger, UpsMonitor |
| 2026-01-22 | Knowledge Update | Added refactoring terms (Re-Export Module, TYPE_CHECKING) |
| 2026-01-22 | Knowledge Update | Added simulator terms (DrivePhase, DriveScenario, FailureInjection, SensorSimulator, VehicleProfile) |
| 2026-01-22 | Knowledge Update | Added OBD-II domain terms (VIN, PID, OBD-II, NHTSA, ollama, ELM327, WAL) and expanded acronyms |
| 2026-01-31 | Marcus (PM) | Added ECMLink V3, ECU, DSM terms and acronyms. Project vision: data collection → AI analysis → ECU tuning |
| 2026-01-21 | M. Cornelison | Initial glossary |
