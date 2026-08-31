# System Architecture

## Overview

This document describes the system architecture, technology decisions, and design patterns for the Eclipse OBD-II Performance Monitoring System.

> **Structure (reorganized 2026-06-01):** to keep this spec focused on the
> implemented system, four non-current bodies of content were extracted to
> `specs/arch/` reference files (preserved verbatim, pointers left in place):
> **Phase-2 ECMLink + data-volume design** → `phase2-data-architecture.md`
> (§17–§18 stubs); the full **modification history** → `architecture-changelog.md`
> (append new change entries there); the **per-version migration history +
> Rule-10 records** → `schema-migration-history.md` (§5 keeps the current schema
> + migration-system contract); the **Shutdown-Sequencer + Data-Pipeline evolution
> history** (superseded designs, F-7/F-8 fix narratives, retired-writer cross-links,
> Rule-10 records) → `subsystem-evolution-history.md` (§10.6/§10.7 keep current
> behavior + invariants). −35% file size; no current-system content removed. (§11
> Deployment was reviewed — it's all current reference, nothing extracted.)

**Last Updated**: 2026-07-04 (Sprint 55 / V0.29.9 — F-104 Server-Side Analytics
Authority spine doc-sync (US-457, Rule-10). New **§10.7.3 "Server-Side Analytics
Authority (F-104)"** formalizes §10.7's B-104 Step-1 principle into the F-104
**boundary rule** (a fact is server-authoritative iff the server can reproduce it
from synced raw → server sole-writer, Pi does not transmit it; irreproducible →
raw, Pi emits first-class; "no derived state the Pi transmits"; B-076 = schema,
F-104 = authority + writers). Documents the LANDED identity spine (US-448): the
canonical `drives` table + server-minted `drive_id` (AUTOINCREMENT anchored by
`UNIQUE(source_device, source_drive_id)` + upsert-by-natural-key mint, never
renumbers) **subsuming** `drive_summary.id` (not a 5th orthogonal id; `v0018`
explicit-id insert keeps `drive_statistics.summary_id` FKs numerically valid),
Pi ids demoted to advisory `source_drive_id`, and the `attribution_anomaly`
tripwire re-point (keeps DETECTING on raw `realtime_data.drive_id` — backstop not
blinded — anomaly OUTPUT maps to canonical identity). The **sole-writer harness +
owned-table registry** (the EXISTING harness, not a parallel one) is documented as
the **target** with an honest **Implementation-status** note: US-449 sole-writer
formalization is BLOCKED (BL-017 — live `/analyze` → `basic.py::computeDriveStatistics`
dual-write of `drive_statistics`, last-writer-wins), and US-450/451/452 sit
downstream of that Atlas ruling (idempotency proof landed). LANDED schema
normalization enumerated: D-7 `power_log`+`pi_state` raw-sync (US-453/`v0019`),
D-3 O2 name canonicalization (US-454/`v0020`), D-4 unit-string canonicalization to
python-obd native (US-455/`v0021`), D-5 `static_data` honest-empty (US-456).
Stale-ref audit: no now-false "Pi transmits derived X" prose (§10.7 already states
the boundary rule; §5's Pi-`drive_id`→`source_id` is CURRENT — US-451 collapse not
landed — deliberately left). Also added `[[ssot-design-pattern]]` worked example #4
(server-analytics authority as the derived-data boundary) +
`regression_manifest.json` F-082 gains Sprint 55 (US-452/454/455/456 changed its
data-profile items; F-104/F-075 already registered by Marcus). BENCH-ONLY,
Rule-10 per Atlas A-11. Docs-only; no `src/` change; full detail in
`specs/arch/architecture-changelog.md`.)
Prior: 2026-07-04 (Sprint 54 / V0.29.8 — OBD capture-reliability +
power-hygiene doc-sync (US-447, Rule-10). New **§3.5 "OBD Connection Threading
Model — serialization + epoch fence" (US-441 / F-117 / A-17)** [authored in-sprint
by US-441 under its bound Rule-10 AC; registered here + in the changelog]:
python-obd's connection wraps ONE non-thread-safe serial port driven from multiple
threads (the lifecycle connect/query timeout daemons left running on timeout per
TD-036, the US-301 reconnect heartbeat, the realtime logger). The **A-17 defect**
was the V0.27.1 lock guarding only `connect()` while the logger read
`self.connection.obd.query()` *directly* → its reads raced an orphaned timed-out
daemon on the one port → interleaved ELM327 frames → **0 rows on every connect**.
The model: THE single serialization lock `ObdConnection._ioLock` lives on the
**wrapper** (not `lifecycle.py`) and guards every `self.obd` access
(connect/query/close/probe); every caller — the daemons, the heartbeat, AND the
logger's `queryParameter`/`_queryViaDecoder` (now `connection.query()`, not
`.obd.query()`) — goes through it. An **epoch fence** (`_generation` bumped per
connect-success + disconnect, captured via `activeGeneration()`) bars a superseded/
orphaned connect (refuses re-open) or query (raises `ObdConnectionSupersededError`,
never touches the port); live callers pass no generation and are never fenced.
TD-036 no-boot-hang preserved (only `.obd` *access* serialized, daemon + wall-clock
shape untouched); daemons thread-named `obd-connect-gen<N>`/`obd-query-<cmd>-gen<N>`
for observability. **Battery Health Log §** gains a "Sprint 54 power-path additions"
para (US-444/F-051 `SlowDrainDetector` HEALTH verdict in `UpsMonitor` + US-445/F-054
boot-time VCELL HEALTH verdict → `boot-battery-test` state slot — both battery-health
signals, neither writes the drain-event-shaped `battery_health_log`). US-432/F-049
(idle-poll cold-boot RPM-mask force-read) is a read-path fix on the existing OBD
connection with no new arch surface (documented in-story); US-442 (drain-row
annotation) + US-443 (data-profile triage) changed no runtime arch.
`regression_manifest.json`: F-117/F-051/F-054 pre-registered by Marcus, F-049 gains
Sprint 54. Docs-only; full detail in `specs/arch/architecture-changelog.md`.)
Prior: 2026-07-02 (Sprint 53 / V0.29.7 — bench-only bug/ops rollup
doc-sync (US-440, Rule-10): new **§10.7.2 "Derived motion signals + cross-drive
comparison (F-106/F-069)"** — server-side per-drive `drive_derived_signals` (peak
accel/decel m/s², estimated distance km via trapezoidal ∫speed·dt) computed by
`derived_signals_compute.py`, wired as the 3rd per-drive compute in the recompute
CLI + nightly batch, plus the read-only `compare_drives` CLI (F-069) over the
already-computed analytics tables. §10.7 Compute-path list + on-demand-CLI updated
for the 3rd compute; `drive_summary.profile_id` now populated from `realtime_data`
(US-437 N-8, preserve-NULL/never-clobber); Pi-side retirement scope gains
`ensureBatteryLogRetired()` (US-437 N-4). **Battery Health Log §** gains the
MAX17048 SoC% calibration protocol + the config-driven
`pi.hardware.upsMonitor.socColdStartWindowSeconds` cold-start window
(US-431/F-048, `scripts/calibrate_max17048.py`). US-433/US-434 were verify-only
(no code, no schema change → no doc change). Docs-only; full detail in
`specs/arch/architecture-changelog.md`.)
Prior: 2026-07-02 (Sprint 52 / V0.29.6 — BL-014/BL-015 landings +
display hardening doc-sync (US-430, Rule-10): **Battery Health Log §** re-pinned
to `start_vcell_v`/`end_vcell_v` (volts) + dedicated `start_soc_pct`/`end_soc_pct`
(SoC%) — the legacy misnamed `start_soc`/`end_soc` dropped in one forward-only
both-tier migration (server `v0016`); register SoC% recorded via the bench drain
CLI under the US-234 cold-start guard; the retired-in-SS-T5 orchestrator drain
consumer documented as removed (US-427/TD-058). New **"Power-mode SSOT" §** in
the System Status card (US-421/F-098): `PowerModeProvider` reads static config
`pi.power.mode ∈ {car,wall,unknown}` (honest `unknown`, config→GPIO seam). F-8
voltage-is-not-percent trap re-pinned to `*_vcell_v`/`*_soc_pct`. Kiosk-unit
install contract (US-428/F-103) documented in-story. Docs-only; full detail in
`specs/arch/architecture-changelog.md`.)
Prior: 2026-07-01 (Sprint 50 / V0.29.4 — new **§10.8 EDR Sensor Bus
Architecture**: **§10.8.1** F-110 `SampleBus` recap (Sprint 46 / V0.29.0) +
**§10.8.2** EDR sensor reader + raw-sensor persistence (F-113/F-114) — additive
`raw.imu.*`/`raw.light.*` LOSSY topics on the F-110 bus (one `seq` per IMU
burst), sibling `edr_imu_sample`/`edr_light_sample` tables authored once in the
`src/common/edr/sensor_schema.py` versioned contract (A-4 anti-divergence),
always-on decimated persist (`persistHz` 25) + rolling-window retention
(`retentionDays` 7), `drive_id` NULL-when-no-drive latch, graceful-absent probe,
ships dark behind `pi.sensors.*` under `pi.bus.enabled`. Rule-10 in-sprint per
Atlas's 2026-06-30 EDR ADR §5 (US-415). BENCH-validated (US-411 golden-master +
absent-path); live IRL acceptance (`i2cdetect` 0x29/0x69 + connect-when-wired)
pending the first V0.29.4 Pi deploy.)
Prior: 2026-06-29 (Sprint 47 / V0.29.1 — F-107 A-9 closure, two new
subsections under §10.7.1: **§10.7.1.1** Root-1 deploy-invariant closure
(US-389 — single-instance guard ⇄ `RuntimeDirectory` matched-pair tested deploy
invariant + version stamp) and **§10.7.1.2** Root-2 guaranteed-close (US-388 —
deadline-anchored close + off-tick `DriveDetector.evaluateTimeouts` driven by
the orchestrator loop, per Atlas's 2026-06-29 C-α…δ shape ruling). Both per the
2026-05-18 design-gate governance rule (PM Rule 10 / C-4 DoD); A-9 stays OPEN
until the live IRL re-gate (short / back-to-back / key-on-after-missed-close /
deploy-double-start) passes.)
Prior: 2026-06-01 (Sprint 44 / V0.28.1 — new §5 "V0.28.1 — B-076
first slice" subsection documenting the normalized `ecu` identity dimension
(pair-keyed on (ecu_signature, cal_signature); immutability carve-out),
`vehicle_info.ecu_id` NOT NULL FK + transitional-snapshot coherence guard, and
the `speed_pid_calibration` re-key to an `ecu_id` FK (US-376 + US-374, B-076
first slice; v0011 forward-only). Subsection by Marcus (PM) per PM Rule 10;
Atlas Rule 10 PASS recorded 2026-06-01 (verified against landed code; closes
Watch List A-12); IRL acceptance pending the first V0.28-chain hardware
deploy.)
Prior: 2026-05-29 (Sprint 43 / V0.28.0 — §10.7.1 F-107 DriveDetector
dual-attribution remediation (Mechanisms A/B/C) + new §5 "V0.28.0 Schema Pass"
subsection (5 landed surfaces: drive_summary/drive_statistics data_quality;
drive_statistics→summary_id rename; vehicle_info ECU lineage; dtc_freeze_frame;
drive_summary drive_id↔source_id invariant); speed_pid_calibration / US-370
built but deferred to V0.28.1. Atlas Rule 10 PASS 2026-05-29.)
Prior: 2026-05-21 (Sprint 41 / V0.27.17 — §10.7 amendment per
PM Rule 10 design-gate DoD: documents the B-104 Step 1 data-pipeline
architectural shift -- Pi = telemetry emitter; server = sole authority
for derived analytics (drive_summary analytics columns + drive_statistics
computed from raw realtime_data); Pi-side drive_statistics table retired
entirely; trigger seam shifts from Pi-side drive-end signal to nightly
batch + on-demand CLI. Atlas-gated; V0.27.17 IRL acceptance pending.)
Prior: 2026-05-20 (Sprint 40 / V0.27.16 — §10.6 amendment per
PM Rule 10 design-gate DoD: documents F-7 boot-grace latch defect + the
level-based post-grace fix (US-344), and the F-8 boot-progress-finalize
systemd-transaction-membership fix that restores the CLEAN_COMPLETE
shutdown-classification instrument (US-345). Atlas-gated.)
Prior: 2026-05-19 (SS-T9 — design-gate reconciliation:
§2 power-source SSOT, §10.6 ShutdownSequencer supersedes PowerDownOrchestrator,
§11 Wake-on-Power Pi 5 + X1209-HAT topology; resolves findings F-1/F-2/F-6.)
**Author**: Michael Cornelison

---

## 1. Architecture Overview

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        External Systems                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │
│  │  OBD-II      │  │  NHTSA API   │  │   ollama     │                  │
│  │  Dongle      │  │  (VIN decode)│  │   (AI/LLM)   │                  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                  │
└─────────┼─────────────────┼─────────────────┼───────────────────────────┘
          │ Bluetooth       │ HTTP/REST       │ HTTP/REST
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      Application Layer                                   │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Entry Points                                   │  │
│  │   main.py (CLI)  │  systemd service  │  shutdown.sh              │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Core Services                                  │  │
│  │   obd_client/  │  analysis/  │  alerts/  │  display/             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Common Utilities                               │  │
│  │   config_validator  │  logging  │  errors  │  secrets             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Output Targets                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │   SQLite     │  │  OSOYOO      │  │   Logs       │  │   Exports   │ │
│  │   Database   │  │  Display     │  │   (files)    │  │  (CSV/JSON) │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Separation of Concerns**: Each module has a single responsibility
2. **Configuration-Driven**: All behavior externalized to config.json
3. **Fail Fast**: Validate configuration early, fail with clear messages
4. **Graceful Degradation**: Continue operating when non-critical components fail
5. **Observability**: Comprehensive logging with PII masking
6. **Profile Isolation**: Each tuning profile maintains independent data and thresholds

---

## 2. Technology Stack

### Core Technologies

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| Runtime | Python | 3.11+ | Primary language |
| Config | JSON + .env | - | Configuration management |
| Testing | pytest | 7.x | Test framework with 80% minimum coverage |
| OBD Library | python-OBD | 0.7.x | OBD-II communication |
| Display | pygame | 2.x | OSOYOO 3.5" HDMI Touch driver (480x320) |
| AI | ollama | latest | LLM inference (remote on Chi-Srv-01) |

### External Dependencies

| System | Purpose | Connection Method |
|--------|---------|-------------------|
| OBDLink LX (MAC: `00:04:3E:85:0D:FB`, FW 5.6.19) | Vehicle data acquisition | Bluetooth (ELM327 protocol) |
| NHTSA API | VIN decoding | HTTPS REST API |
| Ollama on Chi-Srv-01 | AI recommendations | HTTP (10.27.27.120:11434) -- GPU-accelerated, never local on Pi |

### Hardware

| Component | Platform | Notes |
|-----------|----------|-------|
| Processor | Raspberry Pi 5 Model B | 8GB RAM for application headroom |
| Storage | 128GB A2 U3/V30 microSD | High-endurance recommended |
| Display | OSOYOO 3.5" HDMI Touch | 480x320, capacitive touch |
| Database | SQLite (WAL mode) | Local file database |
| Power | Geekworm X1209 UPS HAT | 18650 battery backup |
| Monitoring | I2C | Battery voltage/SOC/charge-rate via MAX17048 fuel gauge at 0x36 |

**Power-source detection (SSOT).** The power-source fact ("is external/USB-C
power present?") has exactly one authoritative provider: `PowerSourceProvider`
(`src/pi/power/power_source_provider.py`), which wraps the X1209 PLD line on
**BCM GPIO 6, digital, HIGH = power present** (vendor-confirmed: Geekworm
X1209 wiki "AC power loss … detection via GPIO" + Suptronics official
`pld.py`; no I2C in this path). The UI and the ShutdownSequencer both consume
this one provider and differ only by policy (UI = instantaneous; sequencer =
5 s smoothed).

`UpsMonitor` / the MAX17048 fuel gauge provides **battery charge/health only**
(VCELL volts, SOC). It is a *different fact* and is **not** a power-source
signal. The former `UpsMonitor.getPowerSource()` VCELL-trend heuristic is
**retired from the power-source path** — inferring power source from a charge
*trend* caused the 2026-05-18 self-bricking loop (false BATTERY on the boot
VCELL sag while external power was physically connected). Do not reintroduce
any second power-source acquisition path (SSOT invariant; Atlas design gate).
The retired method is retained in the codebase as a `NotImplementedError`
tripwire so any future reintroduction fails loudly at the call site.

**UI consumer wired (US-502, Sprint 69 / V0.29.24).** The "UI consumes this one
provider" half of the design above was specified but never built: the System-
Status power tile read `PowerMonitor.readPowerStatus()`, whose reader is never
configured in the orchestrator, so `power.source` was permanently `unknown` —
tile "unavailable", header bolt gray — while the real fact flowed to
`power_log` through the B1 `_PowerSourceUiBridge`. `CardStateEmitterMixin.
_gatherPowerSource` now reads `PowerSourceProvider` directly (one fact, one
provider) and `PowerMonitor` is no longer consulted for it. Two load-bearing
details:

- **Policy split on uncertainty.** `PowerSourceProvider.isAvailable` (new)
  exposes whether the PLD line is readable at all. The ShutdownSequencer keeps
  the non-bricking direction (unreadable ⇒ treat as power present); the DISPLAY
  must not, because that paints a confident `external` off a dead GPIO — it
  resolves unreadable/raising ⇒ `unknown` ⇒ the tile's honest "unavailable"
  branch. Same fact, one provider, two policies — the SSOT pattern, not a
  second acquisition path.
- **Lazy read, per emit.** The card emitters are constructed in
  `_initializeAllComponents`; `_powerSourceProvider` does not exist until
  `_startHardwareManager` runs later in `runLoop`. A reference captured at
  emitter-init time is `None` for the life of the process (dead tile, green
  tests), so the provider is fetched at emit time.

---

## 3. Component Architecture

### 3.1 Entry Points

Entry points coordinate high-level workflows:

```python
# src/main.py - Primary entry point
def main():
    args = parseArgs()
    config = loadConfiguration(args.config, args.envFile)
    setupLogging(config['logging']['level'])

    if args.dryRun:
        logger.info("Dry run mode - no changes will be made")
        return EXIT_SUCCESS

    return runWorkflow(config)
```

**CLI Arguments**:
- `--config/-c`: Path to configuration file (default: src/config.json)
- `--env-file/-e`: Path to environment file (default: .env)
- `--dry-run`: Run without making changes
- `--verbose/-v`: Enable DEBUG logging
- `--version`: Show version information

### 3.2 Core Services

Core services implement business logic. Each domain follows a standard subpackage structure:

```
src/obd/<domain>/
├── __init__.py      # Public API exports
├── types.py         # Enums, dataclasses, constants (no project deps)
├── exceptions.py    # Custom exceptions
├── <core>.py        # Main class implementation
└── helpers.py       # Factory functions, config helpers
```

**Implemented Domain Subpackages:**

| Domain | Purpose | Key Classes |
|--------|---------|-------------|
| `ai/` | AI-powered recommendations | AiAnalyzer, AiPromptTemplate, OllamaManager, RecommendationRanker |
| `alert/` | Threshold monitoring | AlertManager |
| `analysis/` | Statistical analysis | StatisticsEngine, ProfileStatisticsManager |
| `calibration/` | Calibration sessions | CalibrationManager, CalibrationComparator |
| `config/` | OBD configuration | loadObdConfig, validateObdConfig |
| `data/` | Data logging | ObdDataLogger, RealtimeDataLogger |
| `display/` | Display rendering | DisplayManager, drivers/, adapters/ |
| `drive/` | Drive detection | DriveDetector |
| `power/` | Power monitoring | PowerMonitor, PowerDownOrchestrator, BatteryHealthRecorder |
| `profile/` | Profile management | ProfileManager, ProfileSwitcher |
| `vehicle/` | Vehicle info | VinDecoder, StaticDataCollector |

**Top-level Packages (outside `src/obd/`):**

| Package | Purpose | Key Classes |
|---------|---------|-------------|
| `src/backup/` | Backup management | BackupManager, GoogleDriveUploader |
| `src/hardware/` | Raspberry Pi hardware | HardwareManager, UpsMonitor, ShutdownHandler, GpioButton, StatusDisplay |

See Sections 12 (Simulator) and 13 (Hardware) for detailed architecture of these components.

**Backward Compatibility:**
Original monolithic modules (e.g., `data_logger.py`) remain as facades that re-export from subpackages, ensuring existing imports continue to work.

### 3.3 Common Utilities

Shared utilities used across the application:

| Module | Purpose |
|--------|---------|
| `config_validator.py` | Validates configuration with required field checks, applies defaults via dot-notation paths |
| `secrets_loader.py` | Resolves `${VAR}` and `${VAR:default}` placeholders from environment |
| `logging_config.py` | Structured logging setup with PII masking (email, phone, SSN) |
| `error_handler.py` | Error classification (5-tier), retry decorator with exponential backoff |

### 3.4 Bluetooth Connection Resolution (Pi)

python-OBD's `obd.OBD(portstr=...)` expects a Linux serial device path like
`/dev/rfcomm0` — it does **not** perform Bluetooth discovery or binding.
Pairing and `rfcomm bind` are external prerequisites.

**Flow on Pi startup (real, non-simulator path):**

```
config.json: pi.bluetooth.macAddress = "00:04:3E:85:0D:FB"
   │
   ▼
ObdConnection.connect()
   │
   ▼
bluetooth_helper.isMacAddress(port)?
   │
   ├── yes → bluetooth_helper.bindRfcomm(mac, device=0, channel=1)
   │          │   (idempotent: no-op if already bound to same MAC;
   │          │    release+rebind if bound to a different MAC)
   │          ▼
   │        returns "/dev/rfcomm0"
   │
   └── no  → passthrough (value assumed to already be a device path;
             BC for operators who set /dev/rfcomm0 directly)
   │
   ▼
obd.OBD(portstr="/dev/rfcomm0", fast=False, timeout=...)
```

On `disconnect()`, the helper releases `/dev/rfcommN` **only when this
instance performed the bind**. When the operator supplied a literal path
(path passthrough), ownership is theirs and we never call `rfcomm release`.

**sudo policy.** `src/pi/obdii/bluetooth_helper.py` never calls `sudo` from
Python. Operators grant the service user passwordless access to
`/usr/sbin/rfcomm` via sudoers, e.g.:

```
mcornelison ALL=(root) NOPASSWD: /usr/sbin/rfcomm
```

Alternatively, `scripts/connect_obdlink.sh` wraps the same idempotent
bind/release semantics with `sudo` inside a bash script, for manual
smoke-tests and systemd-unit boot-time binding (see Sprint 14 US-196 for
unit-file persistence).

**Pairing prerequisites.** Pairing is a **separate, one-time**
operational step — the OBDLink LX uses Secure Simple Pairing (SSP) with
passkey confirmation, NOT the legacy "PIN 1234" flow. The LX firmware
sends a numeric passkey and bluez prompts:

```
Confirm passkey NNNNNN (yes/no):
```

`bt-agent -c NoInputNoOutput` does not intercept this — `bt-device`'s
internal agent grabs the callback first and prompts to its own stdin. So
non-interactive pairing needs a `pexpect`-driven bluetoothctl session
that auto-confirms the passkey. That is `scripts/pair_obdlink.sh`
(shellcheck-clean arg parsing + preflight) delegating to
`scripts/pair_obdlink_driver.py` (the session itself).

**The pairing driver contract (2026-07-31 hotfix, BL-025 half 2).** The
script was **unable to pair at all** from the Trixie/bluez upgrade until this
fix, for two independent reasons. Both are now regression-pinned in
`tests/pi/obdii/`:

- **Prompt.** bluez 5.82 prompts `[bluetoothctl]>` — a `>`, not the legacy
  `#` — and wraps it in ANSI: the captured bytes are
  `\x1b[0;94m[bluetoothctl]> \x1b[0m`. The old pattern `\[.+\]#` therefore
  timed out on the *first* `expect()`, before any command was sent. Note the
  escape sequence itself contains a `[`, so the greedy `.+` was wrong twice
  over — it would span from the escape into the prompt even on a `#` box. The
  driver's `PROMPT_PATTERN` forbids `[`/`]` inside the bracket body and
  accepts either terminator, so old and new bluez both work.
- **Agent capability.** The script registered `agent NoInputNoOutput`
  ("just works") while waiting for a `Confirm passkey` line that **only a
  display-capable agent produces** — the confirm branch was dead code and SSP
  could fail with `org.bluez.Error.AuthenticationFailed`. The agent is now
  `DisplayYesNo` (the mode the CIO's phone pairs with).

Three further properties of the driver are contract, not implementation
detail:

- **Success means a DURABLE bond, not a link.** `Pairing successful` is
  bluez's word for the connection. The driver re-reads `info <MAC>` after
  `trust` and **fails** unless `Paired`+`Bonded`+`Trusted` are all yes,
  because the in-car requirement is a bond that survives a reboot and
  reconnects unattended. An unread flag is never rendered as a positive.
- **Idempotent without `--force`.** An existing durable bond is reported and
  left alone. Re-pairing requires the dongle *powered* (engine on), so a
  reflexive `remove` on a working bond can strand the car. A *partial* bond is
  cleared first — that half-state is what makes `pair` fail with
  `AlreadyExists`.
- **Echo anchoring.** bluetoothctl redraws its prompt several times during
  startup, so a naive `sendline(); expect(PROMPT)` matches a **stale** prompt
  and reads terminal padding back as the command's output — a silent wrong
  answer rather than a hang. Each command waits for its own pty echo first.

The session lives in an importable module rather than a `<<'PYEOF'` heredoc
specifically so it can be tested: heredoc code cannot be imported, which is
why both defects above shipped undetected. `tests/pi/obdii/test_pair_obdlink_driver.py`
drives the real state machine against a bluetoothctl transcript **captured
verbatim from the Pi**, ANSI escapes included.

**Pair-mode re-trigger UX (operator-visible).** The LX drops out of
pair mode ~30s after each failed attempt. Solid blue LED = discoverable.
If pairing fails, the operator must either hold the LX button or
power-cycle the dongle before re-running the pair script. Keep within
1-2m of the Pi during pairing. Documented in `docs/testing.md`.

**Bond persistence.** Once paired/bonded/trusted, the bond survives
reboot — bluez stores it under `/var/lib/bluetooth/<adapter>/<mac>/`.
`scripts/pair_obdlink.sh` issues `trust <MAC>` after `pair`, which is
what enables the adapter to reconnect without user prompts on future
boots. Measured state 2026-07-31: `devices Paired` on adapter
`88:A2:9E:84:46:1D` returned **empty** — there is currently no bond of any
kind on this Pi, which is the second half of BL-025 and why the engine-on
re-pair is still owed.

**Radio soft-block survival — the layer below everything else (BL-025).**
Before a bond or an rfcomm bind can matter, the adapter has to be *unblocked*.
`systemd-rfkill` **persists rfkill soft-block state across reboots** under
`/var/lib/systemd/rfkill/<id>:bluetooth` and replays it at every boot. This Pi
carried a saved `[1]` there from ~2026-07-03, so Bluetooth came up soft-blocked
on every single boot and OBD capture recorded **zero rows for ~4 weeks** — while
every layer above reported an honest "no adapter". The lesson is the diagnostic
order: *radio → bond → bind → connect*, and the four-week cost came from
starting at the top.

`deploy/eclipse-rfkill-unblock.service` is the standing safety net
(`Type=oneshot`, `RemainAfterExit=yes`, `ExecStart=/usr/sbin/rfkill unblock all`).
Two details are load-bearing rather than stylistic:

- **`After=systemd-rfkill.service`** — that unit is what *restores* the saved
  block. Unblocking before it runs just lets it re-block afterwards: a green
  unit on a dark adapter.
- **`unblock all`, not `unblock bluetooth`** — the saved-block mechanism is
  per-radio and the WiFi phy can acquire one identically. On this Pi WiFi is
  also the remote-access path, so leaving a sibling radio blocked would move the
  outage rather than end it.

Installed + enabled by `step_install_rfkill_unblock` in `deploy-pi.sh` on
**every** deploy (not gated behind `--init`, same posture as
`step_reassert_obd_mac`: a block can be re-saved at any shutdown, so a drifted
Pi self-heals on the next ordinary re-deploy). The step additionally clears the
live block and zeroes any stale saved one, closing the window between deploying
and the next reboot. The unit is registered first in
`src/pi/ops/unit_manifest.py` START order, so `obdctl status all` surfaces it
ahead of the units that depend on it. Origin RCA of the saved block is tracked
separately (BL-025 #4 / US-513); this net stands regardless of the origin.

**RFCOMM bind reboot-survival.** While the bluez bond is persistent,
`rfcomm bind 0 <MAC> 1` state is NOT — it's cleared on every boot. Two
layers keep `/dev/rfcomm0` live after reboot:

1. `deploy/rfcomm-bind.service` (systemd oneshot, `After=bluetooth.service`,
   `Type=oneshot` + `RemainAfterExit=yes`). Sources MAC + channel from
   `/etc/default/obdlink` — no MAC literal in the unit file.
2. The production `ObdConnection.connect()` path calls `bluetooth_helper`
   anyway, so even if the systemd unit is missing the service self-heals
   on its first connect attempt.

Install via `deploy/install-rfcomm-bind.sh` (runs on the Pi) or let
`deploy-pi.sh --init` do it automatically — the init path writes
`/etc/default/obdlink` from the Pi's `.env` MAC and enables the unit.

**Config keys (all optional, override from defaults):**

| Key | Default | Meaning |
|-----|---------|---------|
| `pi.bluetooth.macAddress` | — | MAC **or** literal device path |
| `pi.bluetooth.rfcommDevice` | `0` | The `N` in `/dev/rfcommN` |
| `pi.bluetooth.rfcommChannel` | `1` | SPP RFCOMM channel (OBDLink LX = 1) |
| `pi.bluetooth.connectionTimeoutSeconds` | `30` | python-OBD command timeout |
| `pi.bluetooth.retryDelays` | `[1,2,4,8,16]` | Backoff delays on connect retry |

**Environment file (`/etc/default/obdlink`):**

| Key | Meaning |
|-----|---------|
| `OBD_BT_MAC` | MAC that `rfcomm-bind.service` rebinds on boot |
| `OBD_BT_CHANNEL` | SPP RFCOMM channel (defaults to 1 if unset) |

**Protocol confirmation (Session 23 empirical).** The Eclipse's ECU
answered on ISO 9141-2 K-line @ 10,400 bps via the LX; python-obd
reported `Car Connected | ISO 9141-2 | ELM327 v1.4b` on the first live
handshake. This matches the protocol documented in `specs/obd2-research.md`.

### 3.5 OBD Connection Threading Model — serialization + epoch fence (US-441 / F-117 / A-17)

`python-obd`'s connection object wraps **one serial port and is NOT
thread-safe**. eclipse-obd drives that connection from **multiple threads**:

- the lifecycle's bounded connect/query **timeout daemons**, which are
  deliberately **left running on timeout** (TD-036 / US-244 anti-boot-hang —
  `_runInitialConnectWithTimeout`, `_queryWithTimeout`);
- the **US-301 reconnect heartbeat** daemon (a second connect path);
- the **realtime logger**, which reads `ObdConnection.query()` on the capture
  loop thread.

**The defect (A-17, root-caused live 2026-07-03).** The V0.27.1 lock guarded
only `connect()`. The realtime logger read `self.connection.obd.query()`
*directly*, so its reads raced an **orphaned** (timed-out, left-running)
connect/query daemon on the one serial port → interleaved ELM327 frames →
`elm327 __read | Device disconnected while reading` → **0 rows on every
connect**. (A raw single-threaded `python-obd` session on the same port read
RPM flawlessly — proving the bug is eclipse-obd's concurrency, not the
dongle/ECU/K-line/pairing.)

**The model (US-441).** THE single serialization lock — `ObdConnection._ioLock`
— lives on the **wrapper** (`obd_connection.py`), NOT on `lifecycle.py`, and
guards **every** access to the underlying `self.obd`:

| Access | Path |
|--------|------|
| connect | `connect()` holds `_ioLock` for the whole attempt (ctor + probe) |
| query | `query()` holds `_ioLock` around `self.obd.query(cmd)` |
| close | `disconnect()` holds `_ioLock` around `self.obd.close()` |
| probe | US-199 supported-PID probe runs inside the held connect lock |

**Every caller goes through the wrapper** so no two threads ever drive the
port at once: the lifecycle connect/query daemons, the US-301 heartbeat's
`connectFn`, the realtime logger's reads (`logger.py` `queryParameter` /
`_queryViaDecoder`), **and the DTC read/clear paths (`DtcClient` — Mode 03 /
07 / 04, including the US-404 KOEO connect-edge read) — all call
`connection.query()`, never raw `connection.obd.query()`.** US-474 (F-117/A-17)
removed the last `getattr`-based raw fallback in `DtcClient._serializedQuery`
and made `query()` a **typed member of the `ObdConnectionLike` Protocol**
(`obd` stays exposed as the python-obd facade but is explicitly *not* the DTC
read path), so the raw-bypass hole that killed capture — a KOEO DTC read
interleaving with the logger's read on the one non-thread-safe port — is now
closed at the type level, not just by convention.

**Epoch fence (orphaned-daemon reconciliation).** A monotonically increasing
**generation** (`ObdConnection._generation`, guarded by `_ioLock`) is bumped on
each **successful connect** and each **disconnect**, so a live connection
carries a stable generation between the two. A bounded timeout daemon captures
the generation via `activeGeneration()` *before* it spawns and passes it back:

- `connect(callerGeneration=…)` — a superseded connect (a newer connection
  already won while this orphan was blocked) **refuses to re-open** and returns
  the current connectedness.
- `query(command, callerGeneration=…)` — a superseded read raises
  `ObdConnectionSupersededError` and **never touches the port**.

**Live callers pass no generation and are never fenced** — the realtime logger
always reads the *current* connection. Thus a timed-out daemon that finally
wakes cannot corrupt (re-open / read) a connection a newer owner now holds,
even though it cannot be force-killed.

**TD-036 preserved.** Only `.obd` *access* is serialized; the daemon-launch +
wall-clock-timeout shape (why boot never hangs) is untouched. A wedged connect
daemon holding `_ioLock` cannot hang boot because `_initializeConnection`
returns on its own wall-clock cap regardless, and a later query daemon that
blocks on the lock is itself wall-clock-bounded (and daemon=True, reaped at
exit).

**Observability.** Connection/query daemons are thread-named with their
generation (`obd-connect-gen<N>`, `obd-query-<cmd>-gen<N>`); the heartbeat is
`obd-reconnect-heartbeat`. `isConnectInFlight()` reflects `_ioLock` (any OBD
I/O in flight) so the heartbeat still skips a tick when a connect is already
happening.

Code: `src/pi/obdii/obd_connection.py` (`_ioLock`, `_generation`,
`activeGeneration`, `query`), `orchestrator/lifecycle.py`
(`_runInitialConnectWithTimeout`, `_queryWithTimeout`, `_resolveGeneration`),
`data/logger.py` (serialized reads), `obdii/dtc_client.py` (`ObdConnectionLike`
Protocol + `_serializedQuery` — all DTC reads via the locked `query()`).
Contract tests: `tests/pi/obdii/test_obd_connection_thread_safety.py`
(real-concurrency: logger read path + orphaned daemon on the same wrapper, no
interleaving) and `tests/pi/obdii/test_dtc_connect_edge_concurrency.py`
(US-474 / F-117 GAP-1: a real `DtcClient` KOEO read + a logger read serialize
through `_ioLock` on one faked non-thread-safe port; reverting the lock makes
it RED).

---

## 4. Data Flow

### Request Flow (OBD-II Data Acquisition)

```
1. OBD-II Client connects to Bluetooth dongle
   │
2. Polls configured realtime parameters (RPM, temp, etc.)
   │
3. Data validated and timestamped (millisecond precision)
   │
4. Threshold checker evaluates alert conditions
   │
5. Data written to SQLite (batch of 5-10 readings)
   │
6. Display updated with current values (1Hz)
```

### Analysis Flow (Post-Drive)

```
1. Drive end detected (RPM = 0 for 60 seconds)
   │
2. Statistical analysis triggered
   │  - Calculate: max, min, avg, mode, std_1, std_2
   │  - Calculate outliers: mean ± 2*std
   │
3. Results stored in statistics table with profile_id
   │
4. AI analysis triggered (if ollama available)
   │  - Prepare air/fuel ratio data window
   │  - Format prompt with vehicle context
   │
5. AI recommendations ranked and deduplicated
   │
6. Results stored in ai_recommendations table

**AI Graceful Degradation**: When ollama is unavailable (not installed, not running, or model not loaded), AI analysis is automatically skipped without affecting other system functionality. The system logs a warning on startup if AI is enabled but ollama is unavailable, then continues normal operation. Analysis requests return gracefully with an error message rather than throwing exceptions, ensuring the post-drive workflow completes successfully.
```

### Error Flow

```
1. Error occurs in any component
   │
2. Error classified by error_handler.py:
   │  - RETRYABLE: Network timeout, rate limit (429)
   │  - AUTHENTICATION: 401/403, credentials
   │  - CONFIGURATION: Missing fields, invalid values
   │  - DATA: Validation failures, parse errors
   │  - SYSTEM: Unexpected errors, resource exhaustion
   │
3. Handling based on category:
   │  Retryable: Exponential backoff (1s, 2s, 4s, 8s, 16s)
   │  Config: Fail fast with clear message
   │  Data: Log and continue/skip record
   │  System: Fail with full diagnostics
   │
4. Error logged with context, final status recorded
```

---

## 5. Database Architecture

### Schema Overview (13 Tables)

| Table | Purpose | FK to profiles? | On Delete |
|-------|---------|----------------|-----------|
| `vehicle_info` | NHTSA-decoded vehicle data, keyed by VIN | No | — |
| `profiles` | Driving profiles (daily, performance) | — (parent) | — |
| `static_data` | One-time OBD parameters (FUEL_TYPE, ECU_NAME) | FK to vehicle_info | — |
| `realtime_data` | Time-series OBD sensor readings | FK to profiles | SET NULL |
| `statistics` | Post-drive statistical analysis results | FK to profiles | CASCADE |
| `ai_recommendations` | AI-generated driving recommendations | FK to profiles, self-FK for duplicates | SET NULL |
| `calibration_sessions` | Calibration session tracking | FK to profiles | SET NULL |
| `alert_log` | Threshold violation alerts | FK to profiles | SET NULL |
| `connection_log` | OBD connection events (drive_start/end) | No FK | — |
| `power_log` | AC/battery power transitions (Pi-authoritative; delta-synced to server since US-412 / F-101) | No FK | — |
| `startup_log` | Boot-progress / RTC boot markers (Pi-authoritative; natural-key snapshot-synced since US-417 / F-101) | No FK | — |
| `sync_log` | Per-table high-water mark for Pi -> server delta sync | No FK | — |
| `sqlite_sequence` | SQLite internal autoincrement tracking | — | — |

#### `sync_log` — Walk-phase sync bookkeeping (US-148)

Owned by `src.pi.data.sync_log`, decoupled from `src.pi.obdii.database` so
sync contract changes do not drag OBD schema changes through the same module.
One row per synced table; `table_name` is the PRIMARY KEY.

| Column | Type | Notes |
|--------|------|-------|
| `table_name` | TEXT PK | Name of the Pi table being tracked (must be in the sync-scope whitelist) |
| `last_synced_id` | INTEGER NOT NULL DEFAULT 0 | Highest `id` successfully pushed; US-149 SyncClient **never** advances this on failed push |
| `last_synced_at` | TEXT | ISO-8601 UTC timestamp of the last push attempt |
| `last_batch_id` | TEXT | Batch identifier for server-side traceability |
| `status` | TEXT NOT NULL DEFAULT 'pending' | CHECK constraint: `ok` \| `pending` \| `failed` |

**Sync-scope tables** (eligible for Pi -> server delta sync): `realtime_data`,
`statistics`, `profiles`, `vehicle_info`, `ai_recommendations`,
`connection_log`, `alert_log`, `calibration_sessions`.

**Also synced (Pi health telemetry, added Sprint 50–51)**: `power_log`
(delta-by-PK, US-412 / F-101) and `startup_log` (natural-key snapshot,
US-416/US-417 / F-101). These were Pi-only "never uploaded" until F-101 gave
each a server mirror — see the *power_log + startup_log server sync*
subsection below.  (`battery_log` was the historical Pi-only exclusion until
US-223 deleted the table with its sole writer `BatteryMonitor`; US-216's
`PowerDownOrchestrator` + US-217's `battery_health_log` now cover the
battery-protection domain.)

##### US-194 (TD-025 + TD-026): Per-table PK registry + delta/snapshot split

The original US-148 delta query hardcoded `WHERE id > ?` and wrapped
`int(lastId)`, assuming every in-scope table had an integer `id` PK. That
assumption breaks on three of the eight tables:

- `calibration_sessions` — integer PK named `session_id`, not `id`.
- `profiles` — TEXT PK with semantic values (`'daily'`, `'performance'`).
- `vehicle_info` — TEXT PK `vin` (the actual vehicle VIN).

US-194 splits the sync set in two and adds an authoritative per-table PK
registry:

| Constant | Members | Semantic |
|----------|---------|----------|
| `sync_log.PK_COLUMN` | `{realtime_data:id, statistics:id, ai_recommendations:id, connection_log:id, alert_log:id, calibration_sessions:session_id}` | Maps each append-only table to its INTEGER PK column. Authoritative — no runtime schema introspection. |
| `sync_log.DELTA_SYNC_TABLES` | `frozenset(PK_COLUMN.keys())` | Six append-only tables eligible for delta-by-PK push. |
| `sync_log.SNAPSHOT_TABLES` | `{profiles, vehicle_info}` | TEXT-PK snapshot/upsert tables. Explicitly excluded from delta-sync; a future upsert-path story (post-Sprint 14) will add their transport. |
| `sync_log.IN_SCOPE_TABLES` | `DELTA_SYNC_TABLES ∪ SNAPSHOT_TABLES` | Unchanged whitelist (8 tables). Preserved for BC with the server payload validator, `seed_pi_fixture.py`, and integration fixtures. |

`getDeltaRows` now uses `PK_COLUMN[tableName]` for both the delta cursor
and the `ORDER BY`, and rejects snapshot tables with a clear
`"not delta-syncable"` ValueError rather than crashing on a missing
`id` column or an `int('daily')` cast.

`SyncClient.pushDelta()` returns `PushStatus.SKIPPED` (new in US-194) for
snapshot tables — a deliberate-skip status distinct from `FAILED`
(integrity problem) or `EMPTY` (no new rows). `pushAllDeltas()` still
reports one result per `IN_SCOPE_TABLES` entry, so operator output in
`scripts/sync_now.py` keeps visibility into every sync-scope table.

For `calibration_sessions`, `SyncClient` renames `session_id` → `id` in
each payload row before POSTing so the existing server rule
(`key == 'id'` → `source_id`) applies without any server-side protocol
change.

Public helpers (all take an open `sqlite3.Connection`; the module does no
connection management):
- `initDb(conn)` — idempotent CREATE TABLE IF NOT EXISTS.
- `getDeltaRows(conn, tableName, lastId, limit)` — rows with
  `PK_COLUMN[tableName] > lastId`, `ORDER BY <pk> ASC LIMIT limit`.
  Snapshot tables and unknown / out-of-scope table names raise
  `ValueError` (whitelist doubles as the SQL-injection guard — the table
  name is a SQL identifier and cannot be parameterized).
- `updateHighWaterMark(conn, tableName, lastId, batchId, status='ok')` —
  UPSERT that advances all four mutable columns atomically in a single
  transaction. Always advances `last_synced_id`; callers that need to record
  a failed-push event without advancing must use a distinct write path.
- `getHighWaterMark(conn, tableName)` — returns
  `(last_synced_id, last_synced_at, last_batch_id, status)` or the default
  `(0, None, None, 'pending')` if the row has not been created yet.

##### US-226: Sync trigger semantics + recovery playbook

The transport configuration (`pi.companionService.*`) defines HOW sync
reaches the server; `pi.sync.*` defines WHEN it fires.  Separating the
two lets operators disable the trigger without disturbing the wire
protocol (or vice-versa).

| `pi.sync.*` key | Default | Semantic |
|-----------------|---------|----------|
| `enabled` | `true` | Master switch.  `false` skips `_initializeSyncClient`; the runLoop interval gate observes `self._syncClient is None` as a no-op. |
| `intervalSeconds` | `60` | Cadence between interval-triggered pushes.  First trigger fires on the first `runLoop` pass after boot (flush-on-boot so pending rows from the previous session land immediately). |
| `triggerOn` | `['interval', 'drive_end']` | Which event sources fire a push.  `'interval'` is MANDATORY when `enabled=true` (defensive fallback; a bugged drive-end detector cannot strand rows).  `'drive_end'` hooks into `_handleDriveEnd` in `event_router.py`. |

Triggers are independent.  The drive-end trigger resets the interval
cadence so a recently-ended drive doesn't double-push on the next
interval tick.  A transport failure in one path (logged as WARNING) does
not affect the other; the high-water mark stays put per US-149 so the
next tick resends.

**Recovery playbook** — when the sync pipeline is observed stalled:

1. Confirm last-sync state (Pi side):
   ```
   ssh mcornelison@10.27.27.28 \
     'sqlite3 ~/Projects/Eclipse-01/data/obd.db \
      "SELECT table_name, last_synced_id, last_synced_at, status
        FROM sync_log ORDER BY last_synced_at DESC"'
   ```
2. Check server-side counts:
   ```
   ssh mcornelison@10.27.27.120 \
     'mysql obd2db -e "SELECT COUNT(*) FROM realtime_data"'
   ```
3. Manual flush (Walk-phase path — still valid in Run phase as an
   operator-driven override of the auto-trigger):
   ```
   python scripts/sync_now.py            # full push
   python scripts/sync_now.py --dry-run  # delta counts only
   ```
4. If the auto-trigger is silent (no `"Interval sync:"` log lines in
   `journalctl -u eclipse-obd`), check:
   * `pi.sync.enabled` — is the master switch off?
   * `pi.companionService.enabled` — is the transport off?
   * `COMPANION_API_KEY` — set in `/home/mcornelison/.env`?
   * Orchestrator log at boot should emit one of:
     `"SyncClient initialized: baseUrl=... intervalSeconds=... triggerOn=..."`
     (healthy) or
     `"SyncClient initialization failed, sync disabled: ..."` (warning).

##### US-412 / US-416 / US-417 (F-101): power_log + startup_log server sync

Sprint 50–51 extend sync past the eight US-194 tables to the two Pi
health-telemetry tables, using two distinct transports chosen by PK shape:

- **`power_log` — delta-by-PK (US-412).** `power_log` has an integer `id`
  PK, so it joins the US-194 delta path: `sync_log.PK_COLUMN['power_log'] =
  'id'`, delta cursor on `id`, server maps `id → source_id` with
  `UNIQUE(source_device, source_id)`; migration `v0013` creates the MariaDB
  mirror. This retires the old "power_log is Pi-only, never uploaded" rule.
- **`startup_log` — natural-key snapshot (US-416 mechanism, US-417
  registration).** `startup_log`'s PK is a TEXT `boot_id`, which has no
  stable integer cursor (and the SQLite `rowid` is unusable — `VACUUM`
  renumbers it), so it uses a new **snapshot-sync** path built by US-416 and
  reusable by F-115's future event-vault:
  - **Shared registry** `src/common/sync/snapshot_registry.py::SNAPSHOT_SYNC`
    maps `table → SnapshotSyncSpec(naturalKeyCols, cursorCol)`. Defined once;
    **both tiers import the same object** (A-4 — proven structurally by
    `test_piAndServerSeeTheSameRegistration`, which asserts Pi and server
    return the *identical* `SnapshotSyncSpec` instance, so the two lists
    physically cannot drift). `SNAPSHOT_SYNC['startup_log'] =
    (naturalKeyCols=('boot_id',), cursorCol='recorded_at')`; the registry is
    otherwise empty (mechanism-only).
  - **Pi reader** (`src/pi/data/sync_log.py`) deltas by an explicit
    `recorded_at` cursor tracked in `sync_log.last_snapshot_cursor` per table
    (never rewinds; MAX-guarded). Over-reading is harmless — the server dedups.
  - **Server upsert** (`src/server/api/sync.py::runSnapshotUpsert`) upserts on
    `UNIQUE(source_device, *naturalKeyCols)` with ON-CONFLICT — a new pattern
    **distinct** from the `id → source_id` delta path and carrying **no
    `source_id`**. Migration `v0014` creates `startup_log` with
    `UNIQUE KEY uq_startup_log_boot(source_device, boot_id)`.
  - `dtc_freeze_frame`'s pre-existing FK-resolution special-case is left
    untouched.

The Pi sweep (`pushAllDeltas`) runs the registered snapshot tables after the
delta tables and guards a registered-but-not-yet-created table (fresh/partial
DB) as EMPTY rather than crashing.

##### US-419 (F-080): boot clock-quality flag on power_log / startup_log

Post-reboot the Pi's RTC can read a stale/epoch time before
`systemd-timesyncd` corrects it, which would write drifted timestamps as
truth. US-419 adds a **Pi-local forensic** `data_quality` TEXT column to
`power_log` and `startup_log` (nullable; legacy rows stay NULL = unassessed).
`src/pi/diagnostics/clock_sync.py` is the SSOT for "is this boot timestamp
trustworthy?": a subprocess-free sanity FLOOR (a wall clock before
`CLOCK_SANITY_FLOOR_ISO='2025-01-01T00:00:00Z'` is a definitive dead-RTC
reset, flagged unconditionally — the floor wins even if NTP later reads
synced) combined with a best-effort `timedatectl NTPSynchronized` probe
(tri-state: an *unreachable* probe on a non-systemd/dev box returns None and
falls back to the floor alone, so it never false-flags). A drifted boot row is
stamped `data_quality='clock_unsynced'` rather than silently trusted; boot-log
writers apply the verdict as *policy* (they do not each re-acquire a clock
signal). The RTC coin-cell / timesyncd-ordering fix itself is ops (AI-1), out
of the code scope.

**Wire-strip.** `data_quality` here is Pi-local only — the server `power_log`
/ `startup_log` mirrors have no such column — so
`sync_log._WIRE_STRIPPED_COLUMNS` drops it on both the delta and snapshot push
paths (safe globally: `power_log` + `startup_log` are the only Pi tables
carrying `data_quality`).

```
┌─────────────────────┐     ┌─────────────────────┐
│    vehicle_info     │     │      profiles       │
├─────────────────────┤     ├─────────────────────┤
│ vin (PK)            │     │ id (PK)             │
│ make                │     │ name                │
│ model               │     │ description         │
│ year                │     │ alert_config_json   │
│ engine              │     │ created_at          │
│ ...                 │     └──────────┬──────────┘
└──────────┬──────────┘                │
           │                           │
┌──────────▼──────────┐     ┌──────────▼──────────┐
│    static_data      │     │   realtime_data     │
├─────────────────────┤     ├─────────────────────┤
│ id (PK)             │     │ id (PK)             │
│ vin (FK)            │     │ timestamp           │
│ parameter_name      │     │ parameter_name      │
│ value               │     │ value               │
│ unit                │     │ unit                │
│ queried_at          │     │ profile_id (FK)     │
└─────────────────────┘     └─────────────────────┘
                                       │
                            ┌──────────▼──────────┐
                            │    statistics       │
                            ├─────────────────────┤
                            │ id (PK)             │
                            │ parameter_name      │
                            │ analysis_date       │
                            │ profile_id (FK)     │
                            │ max, min, avg, mode │
                            │ std_1, std_2        │
                            │ outlier_min/max     │
                            └─────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐
│ ai_recommendations  │     │ calibration_sessions│
├─────────────────────┤     ├─────────────────────┤
│ id (PK)             │     │ session_id (PK)     │
│ timestamp           │     │ start_time          │
│ recommendation      │     │ end_time            │
│ priority_rank       │     │ notes               │
│ is_duplicate_of(FK) │     │ profile_id (FK)     │
│ profile_id (FK)     │     └─────────────────────┘
└─────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐
│    alert_log        │     │   connection_log    │
├─────────────────────┤     ├─────────────────────┤
│ id (PK)             │     │ id (PK)             │
│ timestamp           │     │ timestamp           │
│ parameter_name      │     │ event_type          │
│ value               │     │ mac_address         │
│ threshold           │     │ protocol            │
│ profile_id (FK)     │     │ details             │
└─────────────────────┘     └─────────────────────┘

┌─────────────────────┐
│     power_log       │
├─────────────────────┤
│ id (PK)             │
│ timestamp           │
│ event_type          │
│ source              │
│ details             │
└─────────────────────┘
```

### Indexes (14)

| Index | Table | Column(s) |
|-------|-------|-----------|
| `IX_realtime_data_timestamp` | realtime_data | timestamp |
| `IX_realtime_data_profile` | realtime_data | profile_id |
| `IX_realtime_data_param_timestamp` | realtime_data | parameter_name, timestamp |
| `IX_statistics_analysis_date` | statistics | analysis_date |
| `IX_statistics_profile` | statistics | profile_id |
| `IX_ai_recommendations_duplicate` | ai_recommendations | is_duplicate_of |
| `IX_alert_log_profile` | alert_log | profile_id |
| `IX_alert_log_timestamp` | alert_log | timestamp |
| `IX_connection_log_event_type` | connection_log | event_type |
| `IX_connection_log_timestamp` | connection_log | timestamp |
| `IX_power_log_timestamp` | power_log | timestamp |
| `IX_power_log_event_type` | power_log | event_type |
| `sqlite_autoindex_profiles_1` | profiles | id (auto) |
| `sqlite_autoindex_vehicle_info_1` | vehicle_info | vin (auto) |

### PRAGMAs (set per-connection by ObdDatabase.connect())

- `foreign_keys = ON`
- `journal_mode = WAL`
- `synchronous = NORMAL`

**Important**: PRAGMAs are per-connection, not persisted to the database file. Raw `sqlite3.connect()` does NOT set them -- always use `ObdDatabase.connect()`.

### Data Source Tagging (US-195, Spool CR #4; tightened US-212)

Every row written into a capture table carries a `data_source` column identifying its origin. This prevents replay / simulator / fixture rows from contaminating real-world analytics and AI prompts.

**Enum values** (closed set):

| Value | Owner | Used By |
|-------|-------|---------|
| `real` | Live OBD path | Pi collector, DB-level DEFAULT |
| `replay` | Flat-file replay harness (US-191, B-045) | Deterministic SQLite fixtures seeded ahead of a sync test |
| `physics_sim` | Physics simulator (SensorSimulator / scenario runner) | Simulator-driven captures + `scripts/seed_scenarios.py` output |
| `fixture` | Regression fixture seeder | `scripts/seed_pi_fixture.py` rows + hand-rolled test fixtures |
| `foreign` | Foreign-vehicle contamination marker (US-424 / F-116) | Rows captured from a vehicle that is **not** the Eclipse (the Ford Explorer, drive 33). Set by the Pi ingest guard's retro-tag + the writer latch — real captures of the wrong vehicle, preserved as evidence, NOT synthetic test data |

**Scope** — tables that carry the column (both Pi SQLite and server MariaDB): `realtime_data`, `connection_log`, `statistics`, `calibration_sessions`, `profiles`. Server also adds it to analytics `drive_summary`, and US-204 adds it to `dtc_log`. Tables that can only ever carry real data (`vehicle_info`, `sync_log`, `ai_recommendations`, `alert_log`, `power_log`) do not need the column.  (`battery_log` was also in this list until US-223 deleted the table with its writer BatteryMonitor.)

**SSOT + no-drift (A-4)** — the enum tuple is defined once per tier (`src/pi/obdii/data_source.py::DATA_SOURCE_VALUES` on the Pi, `src/server/db/models.py::DATA_SOURCE_VALUES` on the server) and pinned equal by `tests/pi/data/test_data_source_foreign_marker.py`. On the Pi every capture-table CHECK is *derived* from the tuple (`DATA_SOURCE_CHECK_CLAUSE` / `DATA_SOURCE_COLUMN_DDL`), so a new value propagates to all nine schema literals without hand-editing each. The server `data_source` column carries no DB-level CHECK (application-enforced), so widening the enum needs no server migration; the Pi widens existing DBs via the forward-only SQLite table-rebuild `ensureDataSourceCheckWidened('realtime_data')` (SQLite cannot `ALTER` a CHECK).

**Foreign-vehicle marker (US-424 / F-116) — two axes.** `data_source='foreign'` is the **primary row-level** exclusion axis: because the filter rule below already selects `WHERE data_source='real'`, foreign rows are auto-excluded with zero consumer changes. Its drive-level companion is `data_quality='foreign_vehicle'` on `drive_summary` / `drive_statistics` (see §7 / v0015 migration). Contamination is **re-tagged, never deleted** — evidence is preserved.

**Ingest guard (US-424 / F-116; ships DARK behind `pi.foreignGuard.enabled=false`).** The discriminator is protocol speed, not identity: a dongle-MAC allowlist can't tell the two cars apart (same dongle) and Mode-09 VIN is silent on the Eclipse's ECU. The 1998 Eclipse GST speaks ISO 9141-2 over the K-line with a sustained PID-response ceiling of ~6.3/s; one `realtime_data` row is written per response, so a **sustained** row rate above ~7/s (`pi.foreignGuard.busRateThresholdHz`) over a rolling window means a faster-protocol (non-Eclipse) vehicle is connected. `src/pi/obdii/foreign_guard.py::ForeignVehicleGuard` is the SSOT for the "is this drive foreign?" fact — the poll loop feeds it samples (`observeSample`) and the writer consults it (`isDriveForeign`); neither classifies on its own. "Sustained" is structural (rate held above the bar for the full `sustainedSeconds` window), so a legit start-of-drive Eclipse burst never false-trips. On trip the guard (a) retro-tags the open drive's already-written `'real'` rows `'foreign'` and (b) latches the drive so the writer stamps subsequent rows `'foreign'`. The rows still sync, but land tagged `'foreign'` so the server's `WHERE data_source='real'` filter excludes them — tagging **is** the exclusion.

**Default** — `'real'` at the DB level is a **narrow safety net for the single live-OBD collector path**, NOT a catchall for dev writers. Writers outside the live-OBD path MUST pass `data_source` explicitly at the call site. The live-OBD writer (:class:`src.pi.obdii.data.logger.ObdDataLogger` + :func:`src.pi.obdii.data.helpers.logReading`) honors this contract by auto-deriving the tag from `connection.isSimulated`: real connections produce `'real'`, :class:`SimulatedObdConnection` produces `'physics_sim'`. An explicit `dataSource=` override wins in both constructors so fixture harnesses can tag correctly. The call-site discipline is enforced by `tests/pi/data/test_data_source_hygiene.py`, an AST audit that fails the suite if any seed script INSERT into a capture table omits the `data_source` column (US-212 closed the ~352K-row hygiene bug surfaced by US-205).

**Filter rule** — server-side analytics, AI prompt inputs, and baseline calibrations MUST filter `WHERE data_source = 'real'` unless the caller is running a synthetic test. Pre-US-195 rows with `data_source IS NULL` are treated as `'real'` for backward compatibility.

**Migration** — idempotent at Pi boot via `src/pi/obdii/data_source.py::ensureAllCaptureTables()` (called from `ObdDatabase.initialize()`). Adds the column with `DEFAULT 'real'` to any pre-US-195 table; SQLite applies the default to every existing row in place. No backfill UPDATE is scripted — Session 23's 149 real-run rows are inherently `'real'` once the column lands.

### Drive Lifecycle (US-200, Spool Priority 3)

Captures are scoped to a specific drive via a `drive_id INTEGER` column on `realtime_data`, `connection_log`, `statistics`, and `alert_log` (Pi SQLite + server MariaDB). A row-level id lets server analytics ask *"give me the warmup curve of drive N"* without reconstructing boundaries from connection_log timestamps.

**Engine state machine** — `src/pi/obdii/engine_state.py::EngineStateMachine` classifies RPM + speed observations into four states:

| State | Entry condition |
|-------|-----------------|
| `UNKNOWN` | Initial, no RPM yet |
| `CRANKING` | RPM rises to ≥ 250 (default `crankingRpmThreshold`) from any non-running state |
| `RUNNING` | RPM climbs to ≥ 500 (default `runningRpmThreshold`) while `CRANKING` |
| `KEY_OFF` | RPM = 0 AND speed = 0 continuously for `keyOffDurationSeconds` (default 30s) while `RUNNING`, OR `forceKeyOff()` called |

**drive_id generation** — on `UNKNOWN → CRANKING` and `KEY_OFF → CRANKING` transitions the machine calls an injected `driveIdGenerator`. The production generator is `drive_id.makeDriveIdGenerator(conn)` backed by a single-row `drive_counter` table (monotonic, crash-safe, NTP-skew-immune). Once minted, the id remains stable across `CRANKING → RUNNING` and is cleared on `* → KEY_OFF`.

**Writer plumbing** — a process-wide context `drive_id._currentDriveId` (set via `setCurrentDriveId` / `getCurrentDriveId`) is updated by `DriveDetector._startDrive` / `_endDrive`. The four writers that know about an active drive consult the context at INSERT time:

| Writer | Site |
|--------|------|
| realtime_data | `pi.obdii.data.helpers.logReading` + `ObdDataLogger.logReading` |
| connection_log (drive events only) | `pi.obdii.drive.detector.DriveDetector._logDriveEvent` |
| statistics | `pi.analysis.engine.StatisticsEngine._storeStatistics` |
| alert_log | `pi.alert.manager.AlertManager._logAlertToDatabase` |

Writers outside a drive (boot/shutdown connection events, startup hardware alerts) leave `drive_id` NULL — that's the correct signal that the row doesn't belong to a drive.

**Invariants** (US-200):

1. drive_id is assigned ONCE on CRANKING entry and stable until KEY_OFF.
2. Monotonic Pi-local sequence — no wall-clock ms (NTP-resync-safe).
3. Engine state is RPM/speed-driven; BT disconnect is ONE input (`forceKeyOff`), not the primary driver.
4. No retroactive backfill — the Pi operational store was truncated per CIO directive 2026-04-20 via `scripts/truncate_session23.py --execute` (US-205, Sprint 15) after US-209 closed the server schema catch-up. Pre-US-200 rows (Session 23's 149 real-capture rows plus ~491K benchtest rows that inherited `data_source='real'` via the DEFAULT — see Spool amendment 3 / future-TD for the hygiene bug) were deleted from `realtime_data`, `connection_log`, `statistics` on both Pi SQLite and the chi-srv-01 MariaDB. `drive_counter.last_drive_id` reset to 0 on both sides. The regression fixture `data/regression/pi-inputs/eclipse_idle.db` (SHA-256 `0b90b188…`, 188,416 bytes) was hash-verified pre and post and is untouched. The next real Eclipse drive now mints `drive_id=1`. Pi `eclipse-obd.service` left stopped post-truncate to preserve the clean slate against the benchtest hygiene bug — operator restores the service (`sudo systemctl start eclipse-obd.service`) before the first real drive.

   **Second operational truncate 2026-04-27 (US-227, Sprint 18)** — a second hygiene wave was needed after Spool's post-deploy review of Drive 3 surfaced 2,939,090 rows tagged `data_source='real'` on `drive_id=1` spanning 2026-04-21 02:27 → 2026-04-23 03:12 UTC (car not running). Same root cause as US-205 (pre-US-212 hygiene bug — benchtest leakage inheriting the `'real'` DEFAULT before the explicit-tagging fix took effect), but with a critical difference: by the time US-227 ran, Drive 3 (the first multi-minute real drive on record, 6,089 rows on `drive_id=3`) was already in the database and MUST be preserved. The Sprint 18 script (`scripts/truncate_drive_id_1_pollution.py`) narrows the WHERE clause accordingly — `DELETE WHERE drive_id=1 AND data_source='real'` — so Drive 3 + Drive 2 sim rows + the 584 NULL-`drive_id` orphans (US-233 territory) all stay. `drive_counter.last_drive_id` is advanced to 3 (post-Drive-3 high-water) idempotently — never regressed, even if a later drive has already moved it forward. A pre-flight sync gate refuses `--execute` unless `sync_log.realtime_data.last_synced_id ≥ 3,439,960` (Drive 3's max id) so the local DELETE never runs while Drive 3 is stranded on the Pi. Same fixture-hash invariant as US-205 (pre + post SHA-256 assertion). Same Pi-service stop / start envelope around the DELETE. Sentinel filename `.us227-dry-run-ok` keeps the gate distinct from `.us205-dry-run-ok`. The pollution window 2026-04-21 .. 2026-04-23 also drives an orphan scan on server `ai_recommendations.created_at` and `calibration_sessions.start_time` — non-zero counts halt the run per US-227 stopCondition #2. After US-227 ships, the Pi keeps Drive 3 + Drive 2 sim + NULL-`drive_id` rows and otherwise returns to a clean baseline; future real drives mint `drive_id=4` onward.

**Drive-end detection (US-229)** — `DriveDetector._endDrive` can fire via two independent paths that must *both* be reliable:

| Path | Trigger | Where |
|------|---------|-------|
| **RPM-debounce** (primary) | `RPM ≤ driveEndRpmThreshold` (default `0`) for `driveEndDurationSeconds` (default `60s`) | `_processRpmValue` on each RPM tick |
| **ECU silence** (fallback) | No ECU-sourced `processValue` call for `driveEndDurationSeconds` while `_currentSession` is open | `_checkEcuSilenceDriveEnd` on *every* `processValue` tick |

The fallback path exists because the RPM-debounce signal collapses when the ECU stops responding entirely post-engine-off: python-obd returns null for RPM, `event_router` skips the `processValue` call (`value is None` guard), and the below-threshold timer never starts — the drive remains open indefinitely. Drive 3 (2026-04-23 engine-off 16:46:21 UTC) showed this exact symptom for 6+ minutes because `BATTERY_V` via `ELM_VOLTAGE` (ATRV, adapter-level) kept firing `processValue` ticks without any ECU-sourced reading in between.

The silence path distinguishes ECU-sourced vs adapter-level parameters via `decoders.isEcuDependentParameter(name)`:

- `PARAMETER_DECODERS` entries carry an explicit `isEcuDependent: bool` field (6/7 entries `True`; only `BATTERY_V` / `ELM_VOLTAGE` is `False`).
- Legacy Mode 01 PIDs polled via the getattr fallback path (RPM, SPEED, COOLANT_TEMP, ENGINE_LOAD, THROTTLE_POS, TIMING_ADVANCE, SHORT_FUEL_TRIM_1, LONG_FUEL_TRIM_1, INTAKE_TEMP, O2_B1S1, CONTROL_MODULE_VOLTAGE, INTAKE_PRESSURE) are enumerated in `decoders.LEGACY_ECU_PARAMETERS` and return `True`.
- Unknown / future adapter commands default to `False` (safe default: an unknown parameter won't extend drive_end spuriously).

On each `processValue` tick the detector stamps `_lastEcuReadingTime = now` when the parameter is ECU-dependent, then runs `_checkEcuSilenceDriveEnd(now)`: if `_currentSession` is open, `_driveState ∈ {RUNNING, STOPPING}`, and `now - _lastEcuReadingTime ≥ driveEndDurationSeconds`, the detector calls `_endDrive()`. Adapter-level ticks advance the check without resetting the timer — exactly the wake-up we need during ECU-silence-plus-ELM-heartbeat.

`_startDrive` seeds `_lastEcuReadingTime = startTime` so the silence check doesn't fire on the first tick after drive-start before the first Mode 01 poll lands. `_endDrive` clears it to `None` so a subsequent drive-start reseeds cleanly. Both drive-end paths converge on the same `_endDrive` entry point, which is idempotent (`if not self._currentSession: return`), so a rare race where RPM-debounce and ECU-silence both want to fire in the same tick is harmless.

**Pre-mint orphan policy (US-233)** — the python-obd capture loop opens a `realtime_data` writer the moment Bluetooth links to the OBDLink LX, but `EngineStateMachine` does not mint a `drive_id` until the RPM crossing fires `UNKNOWN/KEY_OFF → CRANKING`. Rows captured during that BT-connect-to-cranking window land with `drive_id IS NULL AND data_source = 'real'` — they belong to the *next* drive but were written before the id existed. Drive 3 (2026-04-23) shipped 225 such rows over 39 seconds (16:36:10 → 16:36:49Z) before drive_id=3 was minted at 16:36:50Z.

Policy: **option (a) — post-hoc backfill via `scripts/backfill_premint_orphans.py`.** The script associates each NULL-drive_id real row with the *nearest subsequent* `drive_id` whose `MIN(timestamp)` falls within `--window-seconds` (default 60s). Rows with no drive_start within the cap stay NULL — that's the correct signal for pre-US-212 pollution and other rows that don't belong to any drive.

Why not (b) provisional drive_id at BT-connect, or (c) document NULL as authoritative:

* (b) would change the US-200 state machine, risking `drive_summary` collisions and `connection_log` drive-event ordering vs. the US-200 invariants. Mid-window BT disconnect would orphan the provisional id with no clean recovery.
* (c) leaves Spool unable to include the BT-connect window in his per-drive analysis (warm-engine-fingerprint, baseline coolant, pre-cranking battery V) — and the rows are unambiguously associable in practice (single-drive Pi, drive_start visible in raw data, hard-cap window).

Backfill invariants:

1. **Idempotent.** Re-running on an already-backfilled DB matches zero rows (the orphan scan returns NULL-drive_id rows only).
2. **Hard cap window.** Default 60s; configurable via `--window-seconds`. Orphans with no subsequent drive within the cap MUST stay NULL — never be assigned to a much-later drive.
3. **Per-drive safety cap.** Default 1000 orphans per drive; if exceeded, the script raises `SafetyCapError` rather than silently associating millions of rows to a single drive_id (defensive against a divergent schema state).
4. **Tagged rows are inviolate.** The UPDATE WHERE clause requires `drive_id IS NULL AND data_source = 'real'`, so even a stale `BackfillMatch` cannot clobber a row that already has a non-NULL drive_id.
5. **Scope: `realtime_data` only.** `drive_summary`, `connection_log`, `statistics`, `alert_log` are not touched. Server-side propagation of the new drive_id values is deferred — the cursor-based sync uses `synced_at`, so a re-tagged row will not re-sync; server-side cleanup is a separate concern flagged in the closure inbox note.
6. **Session 23 fixture is out-of-scope.** The regression fixture `data/regression/pi-inputs/eclipse_idle.db` (188,416 bytes, SHA-256 `0b90b188…`) is a separate file; the script operates on the live DB at `data/obd.db` (or whatever path `--db` names) and never touches the fixture.

**Server-side pre-mint orphan policy (US-240, Sprint 19)** — `scripts/backfill_server_premint_orphans.py` is the server-side mirror of US-233 for the chi-srv-01 MariaDB `realtime_data` table. Same algorithm (orphan → nearest subsequent `drive_id` whose `MIN(timestamp)` falls within `--window-seconds`, default 60s), same per-drive cap, same idempotent re-run, same UPDATE WHERE-clause guard. Two deltas from the Pi-side:

1. **Transport.** SSH + `mysql -B -N` via the address + credential loaders re-exported from `scripts/apply_server_migrations.py` (no plumbing duplication). Backup uses `mysqldump --single-transaction` of the `realtime_data` table to `/tmp/obd2-us240-backup-<ts>.sql` on the server, with the same 60s / 500 MB safety ceilings as US-209. Distinct dry-run sentinel `.us240-dry-run-ok` (so a Pi-side US-233 dry-run cannot silently authorize a server execute).
2. **Explicit post-engine-off exclusion.** Per US-229, the Pi's adapter-level polls (BATTERY_V via `ELM_VOLTAGE`) continue after `engine_state` goes KEY_OFF. Those rows arrive on the server with `drive_id IS NULL AND data_source = 'real'` even though they are not part of any drive — they post-date the latest drive's `MAX(timestamp)`. The matcher excludes them via two paired checks: (a) any orphan whose timestamp is past the maximum `driveEndTimestamp` across all known drives stays NULL by design; (b) a defense-in-depth between-drives check skips orphans that are closer to a prior drive's end than to the next drive's start, so even a widened `--window-seconds` cannot pull a post-engine-off row into a future drive.

Pre-flight at story start (2026-04-30): 8,782 NULL-drive_id real rows on the server across drives {3, 4, 5}; the matcher associated 156 to drive_id=4 (81 rows) and drive_id=5 (75 rows), all within an 11-second max gap. The remaining 8,626 stay NULL — pre-Drive-4 pollution (carried over from the US-227 era), between-drive gaps, and post-Drive-5-engine-off accumulation. Drive 3 contributes zero matches because its BT-connect orphans were tagged `drive_id=1` by the pre-US-212 code and were already DELETEd by US-227's pollution truncate.

**Migration** — `drive_id.ensureAllDriveIdColumns(conn)` (called from `ObdDatabase.initialize()`) idempotently `ALTER TABLE`s every pre-US-200 schema and creates `IX_<table>_drive_id` indexes. `ensureDriveCounter(conn)` seeds the singleton row at `last_drive_id = 0`.

**Server schema catch-up (US-209, Sprint 15)** — the SQLAlchemy model changes from US-195 (`data_source`) and US-200 (`drive_id`, `drive_counter`) shipped in Sessions 65 / 66 but never ran as `ALTER TABLE` / `CREATE TABLE` on the live chi-srv-01 MariaDB. CI tested against ephemeral SQLite and did not catch the gap. `scripts/apply_server_migrations.py` (US-209) closes this for the four capture tables (`realtime_data`, `connection_log`, `statistics`, `alert_log` — `alert_log` drive_id only, no data_source per the Pi-side carve-out), plus `profiles` / `calibration_sessions` (data_source only), plus the `drive_counter` singleton. Safety posture matches US-205: `--dry-run` probes `INFORMATION_SCHEMA` and prints the plan; `--execute` refuses without a prior dry-run sentinel, backs up affected tables via `mysqldump --single-transaction`, and enforces per-statement timing guards (30s per ALTER; 60s + 500 MB ceilings on the backup). Idempotent: re-running on a fully-migrated DB emits zero DDL. See `TD-029` for the underlying deploy-flow gap and Sprint 16+ root-cause fix (Alembic or explicit migration gate in `deploy-server.sh`).

**Server analytics** — `src/server/analytics/basic.py::collectReadingsForDrive(session, driveId, deviceId)` is the preferred per-drive query. Filters `drive_id = ? AND data_source IN ('real', NULL) AND source_device = ?`. Preferred over the legacy time-window `_collectReadings` path for post-US-200 drives because drive_id is row-level and cheaper than a time-range scan.

**End-to-end verification** — `scripts/validate_first_real_drive.sh` (US-208, Sprint 15) is the CIO-runnable validator that confirms the full Sprint 14+15 capture surface lands on an actual drive: canonical ISO-8601Z timestamps, drive_id inheritance, data_source tagging, 21+ Mode 01 PIDs + ELM_VOLTAGE, DTC Mode 03/07 capture, drive_summary row, Pi→server sync, report.py summary, and Spool `/analyze` smoke. Activity-gated: runs against the latest `drive_id` on the Pi (or `--drive-id N`) and is read-only against both DBs. Off-Pi test path at `tests/pi/integration/test_first_drive_replay.py` exercises the query paths against a synthesized fixture so the validator is testable without a live drive. Drill protocol (I-016): the validator surfaces **BENIGN / ESCALATE / INCONCLUSIVE** for the coolant-thermostat disposition based on `MAX(coolant_temp)` vs the 82 C gate and duration vs 15-min sustained-warmup gate. Full procedure: `docs/testing.md` → "First Real Drive Validation".

**Post-drive review ritual (US-219, Sprint 16)** — `scripts/post_drive_review.sh` is the CIO-facing wrapper that runs after every real drive.  It orchestrates the already-shipped pieces — `scripts/report.py --drive-id N` (numeric summary), `scripts/spool_prompt_invoke.py --drive-id N` (renders Spool's Jinja prompt against live analytics and calls Ollama `/api/chat`), a `cat` of `offices/tuner/drive-review-checklist.md`, and a "where to record findings" pointer to `offices/tuner/reviews/` or `offices/pm/inbox/`.  The prompt templates themselves (`src/server/services/prompts/system_message.txt` + `user_message.jinja`) are reused verbatim; the CLI imports `_buildAnalyticsContext`, `_loadSystemMessage`, `_renderUserMessage`, and `_parseRecommendations` from `src.server.services.analysis` so the interactive review and the server's auto-analysis path emit byte-identical prompts.  Ollama base URL, model, and timeout come exclusively from `config.json`'s `server.ai` block (with `${ENV_VAR}` expansion) — never hardcoded.  All "information flow" outcomes (no drive, empty drive, missing tables, Ollama unreachable or HTTP-erroring, empty JSON array) exit 0 so the checklist + pointer steps still run and the CIO can always read all four sections.  Exit code 2 is reserved for argument parsing.  Full procedure: `docs/testing.md` → "Post-Drive Review Ritual".

### Drive-Start Metadata (US-206, Spool Priority 5 + 7)

On every `UNKNOWN/KEY_OFF → CRANKING` transition the Pi captures three values from the most-recent reading snapshot and writes one row to the `drive_summary` capture table:

| Column | Source | Cold-start rule |
|--------|--------|-----------------|
| `ambient_temp_at_start_c` | PID 0x0F (IAT) | Captured ONLY when `fromState ∈ {UNKNOWN, KEY_OFF}`; NULL on warm-restart (Spool Priority 7 — warm intakes are heat-soaked, not ambient). |
| `starting_battery_v` | `ELM_VOLTAGE` (ATRV, US-199) | Captured every drive; pre-cranking loads give the contextualised battery baseline Spool wants for cranking-current-drop analysis. |
| `barometric_kpa_at_start` | PID 0x33 | Captured every drive; pinned once since baro doesn't change mid-drive (Spool Priority 5). Chicago baseline ~101.3 kPa; weather range 97–103 kPa; altitude negligible. |

**Table shape** — Pi SQLite `drive_summary`: `drive_id INTEGER PRIMARY KEY`, three metadata columns (nullable), `drive_start_timestamp DATETIME DEFAULT strftime('%Y-%m-%dT%H:%M:%SZ','now')` (canonical ISO-8601 UTC per US-202), `data_source TEXT DEFAULT 'real'` with CHECK enum. UPSERT semantics on a row that already exists: re-calling `SummaryRecorder.captureDriveStart` with the same `drive_id` UPDATEs (clobbering) the row (acceptance #4 idempotency, US-206 replay path).  US-236 changes the **missing-row** semantics — see "Cold-start defer-INSERT (US-236)" below.

**Invariants**:

1. Zero new Mode 01 polls — `SummaryRecorder` consumes `ObdDataLogger.getLatestReadings()` (read-only snapshot) and never dispatches fresh ECU queries.
2. NULL ambient is semantically meaningful — analytics treat it as "ambient unknown" and skip the IAT-caution interpretation; do NOT fill it with a fabricated value on warm restarts.
3. drive_summary row inherits the minted `drive_id` from `_startDrive`; it NEVER mints a new one.
4. Timestamps are always written via the schema DEFAULT (no Python `datetime.now()` at the Pi writer — aligns with US-202 / TD-027).

**Capture site** — `DriveDetector._startDrive → _armDriveSummaryDeferInsert()` fires AFTER `_openDriveId` publishes the id on the process context and BEFORE the external `onDriveStart` callback.  No `drive_summary` write happens at drive_start itself (US-236 — see below).  The deferred state machine drives the eventual write from inside `processValue` ticks; recorder failures inside that loop are logged and swallowed so drive recording itself is never aborted by a summary-write error.

**Cold-start defer-INSERT (US-236, replaces Sprint 18 US-228)** — `drive_start` fires on RPM crossing the threshold, which routinely beats the first IAT / BATTERY_V / BAROMETRIC_KPA reading from the ECU.  Sprint 18's US-228 attempted to fix this by INSERTing an all-NULL row at drive_start and UPDATE-backfilling the columns as readings arrived; empirically, that path failed across drives 3, 4, 5 (every row stayed all-NULL).  Sprint 19's US-236 switches to **Option (a) defer-INSERT**: the row only appears once data is actually available, eliminating the "INSERTed-then-never-filled" failure mode by construction.

**Defer-INSERT state machine** — `DriveDetector._armDriveSummaryDeferInsert(startTime)` arms three pieces of per-drive state at `_startDrive`:

* `_driveSummaryBackfillDriveId` (the drive being captured)
* `_driveSummaryBackfillDeadline` (`startTime + driveSummaryBackfillSeconds`, default 60s)
* `_driveSummaryBackfillFromState` (snapshot of `_lastEngineState` -- the warm/cold rule sees the PRE-drive state for the entire window)
* `_driveSummaryInserted = False` flag

Each `processValue` tick calls `_maybeProgressDriveSummary(now)` which runs one of two phases:

1. **Defer-INSERT phase** (`_driveSummaryInserted=False`): pulls the latest reading snapshot, calls `SummaryRecorder.captureDriveStart(driveId, snapshot, fromState, forceInsert=deadlineExpired, reason=...)`.  The recorder's behavior:
   * Row missing + post-cold-start-rule payload all-NULL + `forceInsert=False` -> **deferred no-op** (`inserted=False, deferred=True`).  Detector keeps ticking.
   * Row missing + at least one of IAT/BATTERY_V/BARO present -> **INSERT** with available data (`inserted=True`).  Detector flips `_driveSummaryInserted=True` and transitions to backfill phase.
   * Row missing + `forceInsert=True` (60s deadline reached) -> **INSERT** with whatever's in the snapshot (possibly all-NULL).  `result.reason='no_readings_within_timeout'` propagates to the detector for operator-visible logging; the row itself does NOT carry the reason (table schema is fixed -- `reason` lives in logs + result objects only).
2. **Backfill phase** (`_driveSummaryInserted=True`): runs the existing `SummaryRecorder.backfillFromSnapshot` UPDATE-NULL loop until the row is complete (all 3 fields non-NULL, OR battery+baro on warm restart) OR the deadline expires.

**Defer-INSERT invariants**:

1. **No row at drive_start.** The `drive_summary` row only appears after the first IAT/BATTERY_V/BARO reading arrives, OR at the 60s deadline via `forceInsert=True`.  This is the **runtime-validation discriminator** -- a synthetic test that asserts "no row exists immediately after drive_start with empty snapshot" must FAIL against pre-US-236 code (which INSERTed all-NULL at drive_start) and PASS post-US-236 (per `feedback_runtime_validation_required`).
2. **Warm-restart payload-empty defers too.**  A warm restart with IAT-only in the snapshot has its IAT filtered by the cold-start rule, so the post-cold-start payload is all-NULL.  Defer-INSERT no-ops until BATTERY_V or BAROMETRIC_KPA arrives (or the deadline).  This avoids creating an all-NULL warm-restart row.
3. **The 60s deadline is a hard upper bound.**  No dynamic extension.  At the deadline, `forceInsert=True` ALWAYS produces a row even when the ECU stayed silent the entire window -- analytics need to see that the drive happened (the row's all-NULL columns + the propagated `reason` document the silence).
4. **Re-entry safety.**  A new `_startDrive` arms a fresh deferred state, overwriting any previous pending drive's state.  The recorder is stateless across calls; two pending defer-INSERTs for different `drive_id`s don't interfere.  `_endDrive` clears the deferred state so a late telemetry tick can never write to the just-ended drive.
5. **`SummaryRecorder.backfillFromSnapshot` semantics unchanged.**  Still a no-op on missing rows; still never clobbers non-NULL stored values; still respects the warm-restart rule.

**Engine-state tracking** — `DriveDetector` keeps a lightweight `_lastEngineState` (defaults to `UNKNOWN` at boot; set to `KEY_OFF` inside `_endDrive` after the clean debounce; set to `RUNNING` after a successful drive-start). The recorder reads this attribute for the cold-start rule. This is deliberately minimal: the full `EngineStateMachine` (US-200) is the authoritative classifier, but US-206 only needs the from-state at drive-start entry, and wiring the full machine into the RPM-threshold-driven `DriveDetector` is out of scope.

**Server mirror** — the Pi's `drive_summary` capture table syncs into the server-side `DriveSummary` SQLAlchemy model. The model was extended in US-206 (nullable `source_id`, `source_device`, `synced_at`, `sync_batch_id`, `drive_start_timestamp`, `ambient_temp_at_start_c`, `starting_battery_v`, `barometric_kpa_at_start`, `drive_id`) + `UNIQUE(source_device, source_id)` for the Pi-sync path.  The live MariaDB physical table reaches that shape via deploy-time migration `v0004_us237_drive_summary_reconcile.py` (Sprint 19) -- the Sprint-7-8 era table predated those columns and Sprint 16 US-213 / US-209 catch-up scope did not include `drive_summary`, so 148 Pi-sync attempts failed with `Unknown column 'drive_summary.source_id'` between Sprint 18 deploy and 2026-04-29.  v0004 ALTERs the 11 missing columns + adds `IX_drive_summary_drive_id` + `uq_drive_summary_source` then truncates the 9 Sprint-7-8 sim rows (`device_id IN ('sim-eclipse-gst', 'sim-eclipse-gst-multi', 'eclipse-gst-day1')`) and cascade-deletes their `drive_statistics` children (V-4 namespace cleanup, CIO directive 2026-04-29 -- the legacy auto-incremented ids 1-10 collide with Pi-minted drive_ids).  See Section 5 Server Schema Migrations subsection for migration registry mechanics.

**Sync shape** — `sync_log.PK_COLUMN['drive_summary'] = 'drive_id'`; the Pi sync client's `_renamePkToId` renames `drive_id → id` on the wire; the server maps `id → source_id` per its existing rule (US-194 pattern). Delta cursor is the monotonic `drive_id`.

**Reconciled single-writer semantics (US-214)** — US-206 shipped as a dual-writer table (two rows per drive: analytics-keyed + Pi-sync-keyed) so the capture story could ship without perturbing analytics code. US-214 converges on **one row per drive** via Option 1 (Pi writes first, analytics updates):

1. **Pi-sync writes first** at drive start with `source_device`, `source_id = drive_id`, `drive_id`, and the three metadata columns. Analytics fields (`device_id`, `start_time`, `end_time`, `duration_seconds`, `row_count`, `is_real`) stay NULL until analytics runs.
2. **Analytics runs at drive-end** via the auto-analysis trigger in `/sync`. `_ensureDriveSummary` receives the `drive_id` from the extended `extractDriveBoundaries` (US-214 extended it to extract `drive_id` from the `connection_log` rows), finds the Pi-sync row by `(source_device, drive_id)`, and UPDATES the analytics fields in place. `is_real = True` is set at this step (Pi-sync-only rows stay NULL until analytics confirms).
3. **Legacy path** (pre-US-200 data with no `drive_id` in connection_log) falls back to the historical `(device_id, start_time)` find-or-create. These rows leave `source_device`/`source_id`/`drive_id` NULL. SQL's NULL-is-distinct UNIQUE semantics keeps multiple legacy rows legal.
4. **Race / out-of-order sync**: if analytics runs before Pi-sync lands, `_ensureDriveSummary` INSERTs a fully-populated row with both halves. A later Pi-sync of the same `(source_device, source_id)` lands on that row via the UNIQUE constraint and only overwrites its own columns (`_PRESERVE_ON_UPDATE` + the fact Pi doesn't send `is_real`/`start_time`/etc. means analytics fields survive the upsert).

**One-shot migration** — `scripts/reconcile_drive_summary.py` merges pre-existing dual rows on the live DB. For each analytics-only row it finds a matching Pi-sync row (`device_id == source_device` AND `start_time` within 60s of `drive_start_timestamp`), copies analytics fields into the Pi-sync row, redirects `drive_statistics` / `anomaly_log` `drive_id` pointers onto the surviving row, then deletes the analytics-only row. Idempotent — re-runs find no unreconciled pairs. Run `--dry-run` first, then `--execute`. Analytics-only rows with no Pi-sync partner (pre-US-200 drives) stay as-is; the migration reports the orphan count so the operator can decide.

**Invariants**:
- One row per `(source_device, drive_id)` for post-US-200 drives.
- `is_real = TRUE` only after analytics confirms at drive-end. Pi-sync-only rows pre-analytics have `is_real = NULL`.
- Pi-sync writer owns metadata columns (`drive_start_timestamp`, `ambient_temp_at_start_c`, `starting_battery_v`, `barometric_kpa_at_start`). Analytics must not overwrite them.
- `drive_summary` table name is permanent (renaming was rejected in US-206 as too invasive).

### Collector Resilience (US-211, Spool Session 6 Story 2)

Spool Session 6 confirmed CIO's hypothesis: a BT drop today kills the
collector. US-211 adds a Python-side resilience layer so the collector
process stays alive across BT flaps and only surfaces FATAL errors to
systemd (Restart=always, US-210).

**Error taxonomy** — the capture loop classifies raised exceptions at
the capture boundary via
`src/pi/obdii/error_classification.classifyCaptureError()`:

| Class | Trigger | Reaction |
|-------|---------|----------|
| `ADAPTER_UNREACHABLE` | `OSError`/`FileNotFoundError`/`PermissionError` against /dev/rfcomm\*, `BluetoothHelperError`, `ObdConnectionError` with rfcomm/bluez/rfcomm-timeout string | Close python-obd, log `bt_disconnect`, run reconnect-wait loop, reopen on probe-success |
| `ECU_SILENT` | Plain `TimeoutError`/`ObdConnectionTimeoutError` without adapter signature, ambiguous `ObdConnectionError` | Stay connected, log `ecu_silent_wait`, caller reduces poll cadence |
| `FATAL` | Everything else (including `KeyboardInterrupt`, `SystemExit`, `MemoryError`) | Re-raise; systemd `Restart=always` handles process restart |

**Reconnect-wait loop** — `src/pi/obdii/reconnect_loop.ReconnectLoop`
implements Spool's backoff grounding verbatim: `(1, 5, 10, 30, 60)`
seconds capped at 60 thereafter. The loop accepts an injected probe
(`bluetooth_helper.isRfcommReachable` by default), event logger
(`connection_logger.logConnectionEvent` by default), and sleep
function so unit tests run in ~0 wall-clock. `reset()` rewinds the
schedule after a successful reconnect -- the next BT flap starts at
1s, not at the cap.

**Adapter-reachability probe** — `isRfcommReachable` is two-layered and
lightweight: stat `/dev/rfcomm{N}` first (short-circuits when the
kernel node is missing, e.g. post-boot before bind) then `rfcomm show
N` to confirm the MAC is still bound. NO full `obd.OBD()`
reconstruction in the probe -- that's expensive and stateful; the
caller owns the python-obd reopen after the probe returns `True`.

**Orchestrator wiring** — `src/pi/obdii/orchestrator/bt_resilience.BtResilienceMixin`
exposes `handleCaptureError(exc)` on `ApplicationOrchestrator`. The
existing `ConnectionRecoveryMixin` (background-threaded, state-change-
driven) is not replaced; it coexists with the new synchronous error-
class-driven path. Data-logger callers invoke `handleCaptureError`
whenever python-obd raises from the capture path.

**Capture-loop integration (US-221)** — the live wiring from Spool's
Sprint 16 YELLOW concern. `RealtimeDataLogger.__init__` accepts two
dependency-injection kwargs:

- `captureErrorHandler: Callable[[BaseException], CaptureErrorClass]`
  — production wires `ApplicationOrchestrator.handleCaptureError`.
- `onFatalError: Callable[[BaseException], None]`
  — production wires `LifecycleMixin._onCaptureFatalError`, which
  flips `_shutdownState` to `FORCE_EXIT` with `EXIT_CODE_FORCED` so
  systemd `Restart=always` bounces the process on genuinely broken
  state.

`RealtimeDataLogger._queryParameterSafe` unwraps the `__cause__` from
`ParameterReadError` wrappers so the underlying capture-boundary
exception (e.g. `OSError` from /dev/rfcomm loss) reaches
`_pollCycle`'s classifier branch -- without this unwrap,
`queryParameter`'s `raise ParameterReadError(...) from e` would mask
the real cause and the classifier would see only the wrapper. Benign
null responses (ParameterReadError with `__cause__=None`) still
short-circuit as they always have.

`_pollCycle` routes unexpected exceptions through
`_routeCaptureError`:

- **ADAPTER_UNREACHABLE** — handler synchronously tore down python-obd,
  ran the reconnect loop, reopened. Loop breaks out of the current
  cycle and starts the next one fresh. Process stays alive. Same PID.
- **ECU_SILENT** — handler logged `ecu_silent_wait`. Loop enters
  silent mode: `_getEffectivePollingIntervalMs()` multiplies by
  `DEFAULT_ECU_SILENT_MULTIPLIER=5` until the next successful query
  clears the flag (see `_onSuccessfulQuery`). Connection stays open.
- **FATAL** — handler re-raised. Loop sets `_stopEvent`, invokes
  `onFatalError(exc)` which marks the orchestrator for forced exit.
  The main thread observes the shutdown state and exits with code 2;
  systemd bounces.

**Example timeline** for a 2-second BT drop during capture:

```
t=0.00  RPM poll raises OSError("rfcomm: transport endpoint...")
t=0.00  classifier: ADAPTER_UNREACHABLE
t=0.00  connection_log: bt_disconnect
t=0.00  connection.disconnect() called
t=0.00  reconnect loop: schedule[0]=1s
t=0.00  connection_log: adapter_wait, retry_count=1
t=1.00  probe /dev/rfcomm0 -> still missing
t=1.00  connection_log: reconnect_attempt, retry_count=1
t=1.00  connection_log: adapter_wait, retry_count=2 (delay=5s)
t=6.00  probe -> reachable
t=6.00  connection_log: reconnect_attempt, retry_count=2
t=6.00  connection_log: reconnect_success, retry_count=2
t=6.00  connection.reconnect() called -> python-obd reopened
t=6.00  _pollCycle breaks; next cycle starts fresh at t=6.1
t=6.10  RPM poll succeeds; _ecuSilentMode was False (stayed at 100ms)
```

In production this plays against the rfcomm-bind.service (US-196)
rebind, so the reconnect loop waits for `/dev/rfcomm0` to be re-
populated by the bind daemon after BT restoration.

**connection_log timeline** — five new canonical event_types populate
the `connection_log` table so a post-hoc "what happened during that
drive?" review reads as a flap timeline rather than a silent gap.
Constants live in `src/pi/data/connection_logger.py`; the `event_type`
column stays TEXT (no CHECK constraint) so existing dynamic writers
(profile switcher, `shutdown_{event}` f-string) keep working --
US-211 is additive.

| event_type | Meaning | retry_count |
|------------|---------|-------------|
| `bt_disconnect` | ADAPTER_UNREACHABLE fired; python-obd torn down | 0 |
| `adapter_wait` | Reconnect loop about to sleep for next probe | iteration # |
| `reconnect_attempt` | Probe returned True; about to reopen python-obd | iteration # |
| `reconnect_success` | python-obd reopened; capture resumed | iteration # |
| `ecu_silent_wait` | ECU_SILENT fired; adapter OK, cadence reduced | 0 |

Invariants (Spool Session 6 amendment):

1. Process NEVER exits on BT disconnect. Only FATAL surfaces to systemd.
2. Backoff caps at 60s; no exponential blow-up.
3. Probe is lightweight (stat + `rfcomm show`); NOT a full `OBD()` reopen.
4. `connection_log` event_types are ADDITIVE -- existing types
   (`connect_attempt`, `connect_success`, `disconnect`, `drive_start`,
   `drive_end`, `shutdown_{event}`, etc.) remain valid.
5. ECU_SILENT stays connected; do NOT tear down on engine-off.

### Battery Health Log (US-217, Spool Session 6 Story 3)

Per CIO directive 3 (Spool Session 6 — monthly drain tests May–Sept driving season; quarterly in storage), the Pi maintains a `battery_health_log` capture table with one row per UPS drain event. US-217 lands the schema + writer surface; US-216 (Power-Down Orchestrator) will consume it when it wires the staged 30/25/20 SOC shutdown ladder.

**Table shape** — Pi SQLite `battery_health_log`: `drain_event_id INTEGER PK AUTOINCREMENT`, `start_timestamp TEXT NOT NULL DEFAULT strftime('%Y-%m-%dT%H:%M:%SZ','now')`, `end_timestamp TEXT NULL`, `start_vcell_v REAL NULL`, `end_vcell_v REAL NULL`, `start_soc_pct REAL NULL`, `end_soc_pct REAL NULL`, `runtime_seconds INTEGER NULL`, `ambient_temp_c REAL NULL`, `load_class TEXT NOT NULL DEFAULT 'production' CHECK IN ('production','test','sim')`, `notes TEXT NULL`, `data_source TEXT NOT NULL DEFAULT 'real'` with CHECK enum. Index `IX_battery_health_log_start` on `start_timestamp` for time-range queries. **US-426 (Sprint 52 / V0.29.6)** dropped the legacy misnamed `start_soc`/`end_soc` columns (which stored VCELL **volts**, not percent) and added the dedicated `start_soc_pct`/`end_soc_pct` (REAL nullable) as the durable home for MAX17048 State-of-Charge % — one forward-only both-tier migration (Pi SQLite CREATE-AS-SELECT-DROP-RENAME + server MariaDB `v0016`; both tiers now byte-identical incl. `*_vcell_v`, closing the A-4 divergence).

**load_class enum**:

- `production` — real drain (wall power lost while Pi was running normally).
- `test` — CIO's scheduled monthly drill (battery aging baseline).
- `sim` — developer / CI synthetic drain (never touches real hardware).

Analytics filter `production` + `test` for runtime-trend baselines; `sim` is excluded so unit-test fixture rows never contaminate battery-replacement alerts.

**Writer** — `src/pi/power/battery_health.BatteryHealthRecorder` exposes two methods:

- `startDrainEvent(startSoc, loadClass='production', notes=None, dataSource='real', startSocPct=None) → drain_event_id` — INSERTs a new row with NULL end columns. `startSoc` is VCELL **volts** and lands in `start_vcell_v` (its sole home post-US-426); the optional `startSocPct` register SoC% lands in `start_soc_pct` (NULL when omitted).
- `endDrainEvent(drainEventId, endSoc, ambientTempC=None, endSocPct=None) → DrainEventCloseResult` — UPDATEs end_timestamp + end_vcell_v + runtime_seconds (+ optional ambient, + optional `endSocPct → end_soc_pct`). **Close-once semantic**: re-calling on an already-closed row is a no-op that returns the stored values; the original close is authoritative.

**CLI helper** — `scripts/record_drain_test.py` opens and closes a drain event in one invocation for the CIO's monthly drill. Accepts `--start-soc`, `--end-soc`, `--runtime`, `--load-class`, `--ambient`, `--notes` — the operator-typed `--start-soc`/`--end-soc` are VCELL **volts** and land in `start_vcell_v`/`end_vcell_v`. **US-427 (Sprint 52 / V0.29.6)** additionally reads the real MAX17048 register SoC% (`UpsMonitor.getBatteryPercentage()`) into `start_soc_pct`/`end_soc_pct`, guarded by the **US-234 cold-start rule**: a read inside the ~3-min MAX17048 calibration window (or on a box that can't determine uptime) records **NULL, never a garbage percent** (honest-instrument). Follow with `scripts/sync_now.py` to push the row to Chi-Srv-01.

**SoC% calibration protocol + config-driven cold-start window (US-431 / F-048, Sprint 53 / V0.29.7).** The `~3-min` cold-start window that gates the SoC% read is no longer a bare constant — it is config-driven via the new `pi.hardware.upsMonitor.socColdStartWindowSeconds` key (validator DEFAULT + `config.json`, provisional `180.0`), read by `record_drain_test._resolveColdStartWindowSeconds` (falls back to the `COLD_START_CALIBRATION_WINDOW_SECONDS` constant), so the empirically-measured settle time can *feed* the guard rather than a guessed value. The bench tool `scripts/calibrate_max17048.py` samples the register SoC% / VCELL / CRATE at a fixed cadence from a **cold power-up**, logs a schema-free CSV (no `battery_health_log` write — it is a measurement, not a drain event), and its pure `analyzeSettling()` measures how long the MAX17048 ModelGauge takes to settle → prints a margin-padded recommended window + the exact config key to set. The step-by-step bench protocol is `docs/max17048-soc-calibration-protocol.md`. **BENCH-OWED**: the CIO runs the tool on the UPS-drain rig from a cold power-up and writes the measured settle recommendation into `socColdStartWindowSeconds`; `180.0` stays as the grounded provisional default until that rig run (Rule 2 — the measured number was not fabricated).

**Sync shape** — `sync_log.PK_COLUMN['battery_health_log'] = 'drain_event_id'`; the Pi sync client's `_renamePkToId` renames `drain_event_id → id` on the wire; the server's `runSyncUpsert` maps `id → source_id`. Server mirror `BatteryHealthLog` SQLAlchemy model with `UNIQUE(source_device, source_id)`. Registered in `_TABLE_REGISTRY`; deploy-time migration `v0002_us217_battery_health_log.py` creates the MariaDB table.

**Invariants**:

1. `start_vcell_v` + `start_soc_pct` + `start_timestamp` are authoritative once written; the close path only touches end-event columns.
2. `drain_event_id` is auto-incremented + monotonic (per-event, not a singleton).
3. Close-once: first `endDrainEvent` wins; re-call is a no-op so a crashed orchestrator that retries on next boot cannot overwrite the original close data.
4. Timestamps route through `src.common.time.helper.utcIsoNow` (US-202 canonical ISO-8601 UTC).

**Use case — the live consumer (bench drain CLI)**. The original US-216
Power-Down Orchestrator drain-event consumer was **retired in the SS-T5 shutdown
redesign** (its dead `batteryHealthRecorder` wiring was removed end-to-end in
US-427 / TD-058). The live consumer is now the CIO's monthly bench drill via
`scripts/record_drain_test.py`, which opens + closes one event per invocation.
**As of US-526 (Sprint 70 / V0.29.25) it is no longer the only one — see the
production drain-event writer below.**

### Production drain-event writer (US-526 / F-123 / BL-028, Sprint 70 — Atlas Option C)

`battery_health_log` had **no production writer** between the US-216 retirement
and this story: `BatteryHealthRecorder` wrote its columns correctly but nothing
in `src/` called it, so the F-123 battery-Health verdict had no rows and
honestly reported `unknown`. `src/pi/power/drain_event_writer.DrainEventWriter`
is that caller, in the shape Atlas ruled on 2026-08-02
(`offices/pm/inbox/2026-08-02-from-atlas-v0.29.25-prd-review.md`).

**The writer spans two PROCESSES, and that is the whole design constraint:**

| Event | Process | Site |
|---|---|---|
| OPEN at wall-power loss (AC→BATTERY) | collector (`src/pi/main.py`) | `PowerMonitor.onTransition` ← US-502 `_PowerSourceUiBridge` (GPIO6 truth) |
| CLOSE at restore (BATTERY→AC) | collector | same callback |
| CLOSE at cutoff — **the PRIMARY close** | `eclipse-powerwatch` | `ShutdownSequencer(prePowerOffFn=…)` |
| REAP still-open rows — crash BACKSTOP | collector, at boot | `LifecycleMixin._initializeDrainEventWriter` |

Because the open and the cutoff close are in **different processes**, a
`drain_event_id` held in memory is unavailable exactly where it matters most —
so every close **re-finds its row by query**. This is why Atlas disqualified the
memory-held option: under Spool's depth gate the run-to-cutoff drain is the only
qualifying drain, and a hard crash would drop precisely that row.

**`prePowerOffFn` fires on BOTH poweroff paths, and the fast path is the point.**
The VCELL-floor backstop **skips the bounded pipeline** and goes straight to
poweroff — which is exactly how a run-to-cutoff drain ends. A close implemented
as a pipeline `ShutdownTask` would therefore miss every depth-gate-qualifying
row. The hook is guarded like `phaseEmitFn` (§10.6): a close that raises can
never delay poweroff, and it is **not** called on an abort (transient blip, or
power returning mid-window) because an aborted shutdown is not a drain end.

**Three honest-NA rules (load-bearing):**

1. **An unreadable gauge writes NULL.** US-526 made `startDrainEvent(startSoc=…)`
   and `endDrainEvent(endSoc=…)` accept `None`, so a dead MAX17048 at the loss
   instant records NULL rather than a guessed voltage. The row still opens — the
   drain *did* happen. VCELL is read unguarded (trustworthy at cold start);
   SoC% routes through the shared US-234 cold-start guard, now at
   `src/pi/power/soc_calibration.py` so the CLI and the production writer share
   **one** implementation (a `src/` module must never import from `scripts/`).
2. **The reaper NEVER calls `endDrainEvent`.** That method derives
   `runtime_seconds` from the start/end timestamp delta, so across a reboot it
   would manufacture a multi-hour runtime. The reaper issues its own UPDATE
   stamping **`end_timestamp` only**, leaving `runtime_seconds` **and**
   `end_vcell_v` NULL — an interrupted drain's duration and depth are both
   unknown, and a fabricated `end_vcell_v ≤ 3.50 V` would falsely *pass* the
   depth gate. A NULL on either field fails the gate, so a reaped orphan cannot
   vote (double-safe). Its signature is queryable: `end_timestamp` NOT NULL with
   `runtime_seconds` NULL and `end_vcell_v` NULL; every reap logs at WARNING.
3. **Only rows the writer opened are ever touched.** Atlas's DoD says the reaper
   targets `WHERE end_timestamp IS NULL`; the implementation **narrows** that to
   still-open rows whose `notes` equal `DRAIN_OPEN_NOTE` (a stored ownership
   marker, not a log string). A narrowing can only make the backstop more
   conservative, and it is load-bearing: the four US-442 historical orphans
   (`drain_event_id` 1/9/18/21) hold `end_timestamp IS NULL` **deliberately** —
   there is no timing-truth source for them, and that NULL is what keeps
   `scripts/annotate_orphan_production_drain_events.py` idempotent. Without the
   narrowing, the first power-restore close would hand a months-old row to
   `endDrainEvent` and mint a row with a multi-month `runtime_seconds` **and** a
   real `end_vcell_v` — i.e. one that looks QUALIFYING to the verdict. That is
   strictly worse than the reaper trap the ruling names.

**Ordering invariant:** the reaper runs **before** `onTransition` is registered.
Reversed, it would stamp this boot's live drain as interrupted. It also means a
row later found open is necessarily *same-boot*, which is what makes every
`runtime_seconds` the writer computes truthful.

**Boot-order trap (US-501/502/503, sixth sighting):** the `UpsMonitor` is
resolved **late**, at transition time, via a closure over
`HardwareManager.upsMonitor`. It is built inside `HardwareManager.start()`, long
after this wiring — a reference captured at wiring time would pin `None` and
every drain would record NULL gauge values.

**Enum identity:** power-source comparison is on `.value`, never on enum
members. `pi.power.types` and `src.pi.power.types` are distinct module objects,
so their `PowerSource` members are not `==` — comparing members would let a
dual-imported enum make the writer silently inert (the cross-module
enum-identity class that cost the 9-drain saga).

**Import weight:** the powerwatch service builds its writer with
`makeDrainEventWriterForPath`, a stdlib-sqlite3 `DatabaseLike` adapter, rather
than `ObdDatabase` — importing `pi.obdii` would drag that whole package into a
shutdown-critical process for the sake of a `connect()` (the V0.27.12-DOA import
class). Its sqlite busy timeout is `pi.powerWatch.perTaskTimeoutSec` — the bound
the shutdown path already defines for one unit of work — so a locked database
cannot delay poweroff. No new config key.

**Scope note:** gated on the same `pi.power.power_monitor.enabled` flag as
`PowerMonitor` (no second flag for one fact) and soft-fail throughout —
battery-health bookkeeping must never cost the drive capture beside it.
**Qualifying-gate remap — LANDED US-527 / TD-074** (was "rides US-527" here).
`battery_health_verdict` admits a row on **depth, not duration**:
`end_vcell_v <= [EXACT:3.50] V AND runtime_seconds >= [EXACT:60] s`
(Spool ruling `c72677e`). The retired `runtime_seconds >= 600` gate was Spool's
own spec bug: 600 s sat **above** the 582 s good/degraded boundary, so every
surviving row necessarily landed in `good` and `degraded`/`replace` were
unreachable — the verdict failed toward *reassurance*, the one direction a health
verdict must never fail.

Note the vocabulary, because the phrase "depth bands" (used in the US-526-era
note this replaces) does not describe anything real: **there is no depth band.**
Only the *gate* is depth-based. The **bands are unchanged runtime bands** —
`good` ≥582 s, `degraded` 436–582 s, `replace` <436 s on the 727 s baseline —
and they are now fully reachable precisely because duration no longer filters
admission. Depth answers *"did the pack reach its shutdown region?"*; runtime is
still the capacity *measurement*.

Consequence worth carrying: because `end_vcell_v ≤ 3.50 V` is reachable only by
running down to cutoff, an AC→BATTERY→AC bench tap restored at ~3.8 V writes a
perfectly good row that **correctly never qualifies**. A green drain-writer
drill therefore does *not* demonstrate a working verdict — proving that
end-to-end needs a real run-to-cutoff drain (Spool, 2026-08-02).

**Use case — monthly drain drill (CIO)**:

- Unplug wall power, let Pi drain to the trigger threshold.
- Record results (the `--start-soc`/`--end-soc` values are VCELL **volts**): `python scripts/record_drain_test.py --start-soc 4.15 --end-soc 3.42 --runtime 1440 --load-class test --ambient 22`. Outside the MAX17048 cold-start window the CLI also stamps `start_soc_pct`/`end_soc_pct` from the register (US-427).
- Push to server: `python scripts/sync_now.py`.
- Analytics downstream tracks `runtime_seconds` decay for battery-replacement signal (future story).

**Sprint 52 / V0.29.6 status (BL-015 resolved).** The SoC% rework shipped this
sprint (Atlas-ruled, CIO-ratified): **US-426 (F-061)** dropped the legacy
misnamed `start_soc`/`end_soc` columns (they stored VCELL **volts**, not
percent) and added the dedicated `start_soc_pct`/`end_soc_pct` columns as one
forward-only both-tier migration; **US-427 (F-060)** wired the real MAX17048
register SoC% into the bench drain CLI's recording path under the US-234
cold-start guard. The BL-015 blocker (no `soc_pct` column + the removed
drain-event path) is closed: the durable column now exists, and the ruling moved
the SoC% recording onto the bench CLI rather than the deleted orchestrator path.
(Sprint 51's only `battery_health_log` change was US-424 widening the
`data_source` CHECK enum to include `'foreign'` — the column already existed.)

**Sprint 54 / V0.29.8 power-path additions (US-444 / F-051 + US-445 / F-054) —
battery-health signals adjacent to this log, NOT drain-event writes.** Two new
battery-health instruments landed this sprint. **Neither writes `battery_health_log`**
— that table is drain-EVENT-shaped (start/close/runtime/`load_class`) and feeds
drain baselines, so a health *snapshot* or *trend* written there would pollute the
baseline and re-open the US-442 orphan-row class.

- **Slow-drain detector (US-444).** `src/pi/hardware/slow_drain_detector.SlowDrainDetector`
  is a pure decision layer over a stream of `(timestamp, VCELL)` samples emitting a
  `DrainState` health verdict `{UNKNOWN, STABLE, SLOW_DRAIN}`. A rolling window
  (default `300 s`) + net-decline threshold (default `0.005 V`) trip the raw verdict;
  a debounce (default `30 s`) commits it only after the raw signal holds continuously
  for the interval (flap suppression — the 2026-04-29 inverted-power drill logged 4
  transitions in 45 s); a partial window returns `UNKNOWN` (honest instrument, never a
  confident STABLE). All three thresholds are module `DEFAULT_*` constants + injectable
  ctor params, grounded in F-051 drain-tests 1-4. `UpsMonitor` feeds each poll tick's
  VCELL to the detector (extracted `_pollOnce`, one shared timestamp) and exposes
  `getSlowDrainState()`; `getTelemetry()` shape is **unchanged** (the signal has its own
  accessor, so the telemetry-shape gate + DB stay stable). **Scope boundary (SS-T4,
  2026-05-19):** this is battery-HEALTH advisory telemetry, NOT a power-source decision
  — `UpsMonitor.getPowerSource()` stays a loud `NotImplementedError` tripwire; the
  detector never emits a source verdict and never feeds a shutdown decision (the retired
  VCELL-trend source heuristic bricked the Pi 2026-05-18).
- **Boot-time battery test (US-445).** `src/pi/splash/boot_battery_test` reads the
  MAX17048 VCELL once at boot and writes a grounded health verdict to the
  `boot-battery-test` **state slot** via the F-103/F-097 honest-instrument emitter idiom
  (pure builder + atomic tmpfs write, best-effort never-raise). `assessBootBatteryHealth(vcellV)`
  → `OK` at/above the ~3.70 V discharge knee; `WEAK` below it (a read below the ~3.30 V
  buck dropout knee = Drain-7 empirical carries a distinct reason, same coarse verdict);
  `UNKNOWN` when the read is `None` OR outside the ~2.5-4.35 V physical LiPo band (the
  classic ~20 V un-byte-swapped read → `UNKNOWN`, never a confident wrong health). The
  verdict is **VCELL-only** (a direct register read, trustworthy at power-up); the SoC%
  register needs a ~3-min ModelGauge warmup so it is carried as CONTEXT only (`socPct` +
  `socCalibrated` caveat), never the health basis. `runBootBatteryTest(...)` is
  best-effort (a reader that raises → `UNKNOWN`; a state-write failure is logged, never
  raised — a battery test must never fail boot); a `main()` CLI lets a boot oneshot unit
  invoke it (wiring that unit at boot is a deploy follow-up, out of scope here).

### Data Retention

- **realtime_data**: 365 days (configurable)
- **statistics**: Indefinite
- **ai_recommendations**: Indefinite
- **calibration_sessions**: Manual management

### Server Schema Migrations (US-213, TD-029 closure)

Every server-side schema change -- new column, new table, new index --
ships as a numbered migration module under
`src/server/migrations/versions/`.  The registry
(`src/server/migrations/__init__.py::ALL_MIGRATIONS`) is the authoritative
ordered list; `deploy-server.sh` invokes
`scripts/apply_server_migrations.py --run-all` between the pip install
step and the service restart on both `--init` and the default flow.

**Why this exists.** Before US-213 the live MariaDB had no deploy-time gate
for DDL: SQLAlchemy model additions (US-195 `data_source`,
US-200 `drive_id` / `drive_counter`) tested clean against CI's ephemeral
SQLite but never ran as `ALTER TABLE` on the live DB.  US-205 halted
mid-truncate when a missing column surfaced; US-209 applied the DDL as a
one-shot; TD-029 captured the root cause.  US-213 closes the class-of-bug
permanently.

**Design choices.**

- **Explicit registry over Alembic.**  Path B in TD-029 -- matches CIO's
  "single deploy script, keep it simple" directive, zero new runtime
  dependencies, same style as Pi-side `ensureAllCaptureTables`
  (`src/pi/obdii/data_source.py`) / `ensureAllDriveIdColumns`
  (`src/pi/obdii/drive_id.py`) idempotent migrations.  Alembic remains
  available in `requirements-server.txt` for future migrations that
  genuinely need autogenerate + downgrade; no such case today.
- **Tracking table.** `schema_migrations` on MariaDB: `version` (VARCHAR(64)
  PK), `description` (VARCHAR(512)), `applied_at` (DATETIME default
  CURRENT_TIMESTAMP).  Created idempotently on first `--run-all`.
- **Idempotency is the migration author's contract.**  Each `apply(ctx)`
  function must be safe to re-run on a fully-migrated DB (probe
  INFORMATION_SCHEMA; emit DDL only when missing).  The runner guarantees
  "apply once" on success by recording the version, but never revalidates
  schema state.
- **HARD fail.**  A migration failure raises `MigrationError`; the CLI
  returns non-zero; `deploy-server.sh` halts under `set -e` before the
  service restart.  No half-deployed state.
- **No rollback machinery.**  MariaDB DDL is implicit-commit; partial
  failure leaves the DB partially migrated.  Operator restores from the
  per-migration `mysqldump` backup (for migrations that take one) and
  re-runs after fixing the underlying cause.

**Adding a new migration (developer workflow).**

1. Create `src/server/migrations/versions/vNNNN_<slug>.py` following
   `v0001_us195_us200_catch_up.py` as the template -- export `VERSION`,
   `DESCRIPTION`, `apply(ctx)`, and a module-level `MIGRATION` instance.
2. Import the `MIGRATION` symbol into
   `src/server/migrations/__init__.py` and append to `ALL_MIGRATIONS`
   (numerically ascending order; new entries at the end).
3. Add a unit test under `tests/server/test_migrations.py` (or a dedicated
   file) verifying the migration's DDL is idempotent against a mocked
   `CommandRunner`.
4. Ship.  Next `deploy-server.sh` run applies pending migrations
   automatically.

**Post-deploy verification.**

    ssh mcornelison@10.27.27.120 'mysql obd2db -e \
        "SELECT version, description, applied_at FROM schema_migrations ORDER BY version"'

Should list every applied migration with its apply timestamp.  On an
already-migrated server, re-running `apply_server_migrations.py --run-all`
emits a single `[run-all] 0 applied ... idempotent no-op` line.

**Migration registry + history.** The per-version registry (v0001–v0012 — what
each migration did) and the V0.28.0→V0.28.2 schema-normalization narratives + the
Atlas Rule-10 design-gate records are in
**`specs/arch/schema-migration-history.md`** (extracted 2026-06-01).
`src/server/migrations/__init__.py::ALL_MIGRATIONS` is the authoritative ordered
source.

**Current server schema (post-V0.28.2 normalization).** A normalized `ecu`
identity dimension keyed on the `(ecu_signature, cal_signature)` pair (both
`VARCHAR(32) NOT NULL`) is referenced by `vehicle_info.ecu_id` (NOT NULL FK) and
`speed_pid_calibration.ecu_id` (NOT NULL FK, `UNIQUE(ecu_id)`). `vehicle_info`
carries append-only ECU lineage + a STORED single-active marker;
`dtc_freeze_frame` is the Mode-02 capture table;
`drive_summary`/`drive_statistics.data_quality` are `VARCHAR(20)` with the
`attribution_anomaly` tripwire (and the US-424 / F-116 `foreign_vehicle`
marker, added by the v0015 CHECK-widen migration); `drive_statistics`'s former `drive_id` is
`summary_id`; `drive_summary.drive_id ↔ source_id` is CHECK-invariant. See the
migration-history file for how each landed.

## 6. Configuration Architecture

### Configuration Hierarchy

```
.env (secrets only - never committed)
         ↓
   secrets_loader.py
   (resolve ${VAR} placeholders)
         ↓
  config.json (application settings)
         ↓
   config_validator.py
   (validate required, apply defaults)
         ↓
  Runtime Configuration (validated dict)
```

### Secret Management

Secrets use placeholder syntax in config.json:

```json
{
  "database": {
    "password": "${DB_PASSWORD}"
  },
  "api": {
    "clientSecret": "${API_CLIENT_SECRET}"
  }
}
```

Resolved at runtime from environment variables. Supports defaults: `${VAR:default_value}`

### Configuration Sections

| Section | Purpose |
|---------|---------|
| `application` | Name, version, environment |
| `database` | SQLite connection settings |
| `api` | External API configuration |
| `logging` | Log level, format, PII masking |
| `profiles` | Tuning profiles with thresholds |
| `alerts` | Alert thresholds per profile |
| `calibration` | Calibration mode settings |
| `backup` | Backup cloud storage, scheduling, retention settings |
| `pi.companionService` | Pi → Chi-Srv-01 sync endpoint + auth + retry policy (US-151) |
| `pi.homeNetwork` | Pi home-network detection (SSID/subnet/ping) for B-043 auto-sync building block (US-188) |
| `pi.network` | Pi infrastructure addresses (host, user, path, port, hostname, deviceId) — B-044 canonical source (US-201) |
| `server.network` | Server infrastructure addresses (host, user, port, hostname, projectPath, baseUrl) — B-044 canonical source (US-201) |
| `pi.location.home` | Home reference point (lat/lon + elevation ASL) — altitude anchor + future GPS home-geofence; PII, `.env`-only (US-517) |

### B-044: Config-Driven Infrastructure Addresses (US-201)

Infrastructure addresses (IPs, hostnames, ports, MACs) MUST live in
config and NEVER as string literals in source code, scripts, deploy
files, or tests. Literal drift is a class of bug equivalent to hardcoded
credentials — it breaks across environments and requires a global
rewrite when the address changes.

**Two canonical surfaces:**

1. `config.json` `pi.network.*` / `server.network.*` — consumed by Python
   code via the 3-layer config system (env → secrets_loader → validator).
2. `deploy/addresses.sh` — the bash-side mirror, sourced by every shell
   script that needs an address. Mirrors config.json field-for-field.
   Override pattern: env var > deploy.conf > addresses.sh defaults.

**Lint enforcement** (`tests/lint/test_no_hardcoded_addresses.py`,
`scripts/audit_config_literals.py`):

- Scans `src/`, `scripts/`, `deploy/`, the repo root — reports any
  non-exempt hit of the DeathStarWiFi subnet `10.27.27.*`, project
  hostnames (`chi-srv-01`, `chi-eclipse-01`, etc.), or the OBDLink MAC.
- Exempts: `specs/`, `docs/`, `offices/`, all `*.md` files, tool caches,
  canonical files (`config.json`, `.env*.example`, `deploy/addresses.sh`,
  `tests/conftest.py`), the `tests/` tree (category-C fixtures by
  design), and Python triple-quoted docstrings.
- Inline pragma: any line containing `b044-exempt` skips detection. Use
  with a one-line reason: `# b044-exempt: validator default`.
- `make lint-addresses` runs the audit; `pytest tests/lint/` runs the
  standing-rule gate in the fast suite.

**Adding a new address:**

1. Add to `config.json` `pi.network.*` or `server.network.*`.
2. Add the bash-side default to `deploy/addresses.sh`.
3. Python code reads via the config validator; shell scripts read via
   the sourced variable.
4. `make lint-addresses` (or `pytest tests/lint/`) must stay clean.

#### `pi.homeNetwork` — home-network detection (US-188)

Consumed by `src.pi.network.HomeNetworkDetector` to answer "is the Pi on
the home WiFi?" and "is Chi-Srv-01 reachable?"  The detector is the
Component 1 building block of B-043 (auto-sync + conditional shutdown on
power loss); the future PowerLossOrchestrator (US-189, Sprint 14) will
subscribe to `UpsMonitor.onPowerSourceChange` and branch on
`HomeNetworkState`.

The validator (`src.common.config.validator._validateHomeNetwork`) rejects
empty/whitespace-only SSID, non-CIDR `subnet`, non-positive
`pingTimeoutSeconds` (bool included), and relative `serverPingPath`
with `ConfigValidationError` at config-load time.

| Key | Default | Purpose |
|-----|---------|---------|
| `ssid` | `DeathStarWiFi` | Home WiFi SSID expected from `iwgetid -r` |
| `subnet` | `10.27.27.0/24` | Home LAN CIDR; defense-in-depth co-check with SSID |
| `pingTimeoutSeconds` | `3` | Bounded timeout on `GET {baseUrl}{serverPingPath}` |
| `serverPingPath` | `/api/v1/ping` | Must be absolute (start with `/`) |

Defense in depth: `isAtHomeWifi()` is True ONLY when BOTH the SSID check
AND the subnet check pass.  A spoofed home-SSID on a foreign router
fails subnet; a tethered hotspot that happens to use the home CIDR
fails SSID.  The composed `getHomeNetworkState()` returns `UNKNOWN`
(distinct from `AWAY`) when the `iwgetid` binary is missing or the
subprocess times out — the orchestrator can branch on that separately
(e.g., "retry later" vs "definitely not home").

#### `pi.companionService` — Pi → server reach (US-151)

Consumed by `src.pi.sync.SyncClient` (US-149) for delta upload to
Chi-Srv-01's `/api/v1/sync` endpoint.  Validator (`src.common.config.validator`)
rejects non-positive `syncTimeoutSeconds`, `batchSize < 1`, non-list
`retryBackoffSeconds`, or negative `retryMaxAttempts` with
`ConfigValidationError` so a corrupt surface never reaches the client.

| Key | Default | Purpose |
|-----|---------|---------|
| `enabled` | `true` | When `false`, sync short-circuits to a no-op (US-149 owns the check) |
| `baseUrl` | `http://10.27.27.120:8000` | Chi-Srv-01 FastAPI root |
| `apiKeyEnv` | `COMPANION_API_KEY` | Env var name resolved by `secrets_loader` — key itself is never in the JSON |
| `syncTimeoutSeconds` | `30` | Per-request HTTP timeout (positive number) |
| `batchSize` | `500` | Rows per `/api/v1/sync` POST (integer >= 1) |
| `retryMaxAttempts` | `3` | Retry budget on retryable failures (integer >= 0) |
| `retryBackoffSeconds` | `[1, 2, 4, 8, 16]` | Exponential-backoff schedule in seconds (list) |

#### `pi.location.home` — home reference point (US-517 / F-125)

The Pi's home location: the anchor US-518 re-anchors derived altitude to on
every successful server sync, and the reference point for the future GPS
home-geofence (US-516, hardware not yet ordered).

**This section is location PII and is the first config section whose VALUES
may never be committed.** The real coordinates live only in the gitignored
`.env`; `config.json` carries bare `${PI_HOME_LAT}` / `${PI_HOME_LON}` /
`${PI_HOME_ELEVATION_M}` placeholders, and the validator DEFAULTS are `None`.
The `${VAR:default}` inline-default form is deliberately NOT used — a fallback
coordinate baked into source would be both committed PII and a fabricated
anchor.

| Key | Default | Purpose |
|-----|---------|---------|
| `lat` | `None` | Home latitude, decimal degrees WGS-84 (`[-90, 90]`) |
| `lon` | `None` | Home longitude, decimal degrees WGS-84 (`[-180, 180]`) |
| `elevationM` | `None` | Home elevation above sea level in metres (`[-500, 9000]`) |

**Single read path:** `src.pi.location.HomeLocationProvider`
(`getHomeElevationM()` / `getHomeCoordinates()` / `getHome()`). Consumers call
the provider and never parse these keys themselves
(`specs/ssot-design-pattern.md`).

**No fail-fast validator sub-check, on purpose.** Unlike `pi.homeNetwork` and
`pi.companionService`, a malformed value here does NOT raise
`ConfigValidationError`. `validate()` runs on the Pi's boot path, so raising
would refuse to start the orchestrator over a typo in an *optional* altitude
anchor — trading a dead OBD capture for a cosmetic fault. The provider reports
the honest unknown instead; same policy as `pi.power.mode` (US-421).

**Honest-unknown surface.** The provider returns `None` for an absent key, a
blank env var, an unresolved `${...}` placeholder, a non-numeric string, a
NaN/infinity, a boolean, or a magnitude outside the physical band above. Two
consequences worth knowing:

- `elevationM` and the `(lat, lon)` pair are **separate facts**. US-518 needs
  only the elevation, so it is not coupled to a GPS fix the project has no
  hardware for. The coordinate pair is both-or-neither — half a fix is not a
  partial location, it is a different one.
- The provider **never logs a coordinate value**. `PIIMaskingFilter` (§8) masks
  email/phone/SSN only, so a coordinate written to journald is PII on a surface
  with no mask for it. Rejection warnings name the key and the reason only.

**Operational note (owed, not codeable):** `deploy/deploy-pi.sh` excludes
`.env` from the deploy payload, so the Pi keeps its own `.env`. The `PI_HOME_*`
values therefore do **not** propagate from the dev checkout — until they are
written into the Pi's `.env`, the placeholders stay unresolved and the provider
correctly reports unknown on the box.

#### Derived-altitude re-anchor on sync success (US-518 / F-125)

`AltitudeAnchor` (`src/pi/location/altitude_anchor.py`) owns the derived-altitude
**accumulator** and resets it to `pi.location.home.elevationM` on every successful
server sync. A completed push to the companion service means the Pi reached the
home network, so the car is home — a *verified* "at home" event. Re-anchoring
there bounds integration error to a single drive between syncs (Spool's altitude
ruling, 2026-08-01, item 4).

**Seam.** The hook is `CardStateEmitterMixin._recordSyncOutcome`, which is the one
point both sync-success paths (`_maybeTriggerIntervalSync` and
`triggerDriveEndSync`) converge on, and which runs only *after* a push completed
past the US-340 offline route gate. Hooking the convergence point rather than the
two call sites means a future third sync path cannot silently skip the re-anchor.
The powerwatch power-down `forcePush` runs in a **separate process**, so it has no
in-memory accumulator to re-anchor and is deliberately not wired.

**Scope — this owns the reset, not the integration.** The integrator that advances
the value (`altitude = home + ∫ sin(pitch)·speed dt`) is US-519, deferred pending
Spool's σ sizing on US-521's gyro-fused pitch; the display is US-520. Until then
nothing calls `setDerivedAltitudeM` in production and `states/imu.altitude` stays a
typed NULL with reason `no_source` (`imu_state_bridge`). Publishing
home-elevation-forever as an altitude would be a confident wrong number — strictly
worse than the honest "no source" shown today.

**Honest-instrument rules.** The accumulator starts at `None`, never `0.0` (sea
level is a 209 m error in Chicagoland). When the home elevation is unknown — the
Pi's actual state today per the operational note above — the re-anchor is a
**no-op**: it neither fabricates a value nor destroys the one the integrator owns,
and `getLastAnchoredAtIso()` is stamped only on a re-anchor that actually fired.
The whole path is exception-isolated: drift control is cosmetic, the sync is not,
so it can never turn a successful push into a reported failure (I-038 lesson).

---

## 7. Error Handling Strategy

### Error Classification

| Type | Category | Behavior | Example |
|------|----------|----------|---------|
| Network timeout | RETRYABLE | Exponential backoff | OBD-II connection lost |
| Rate limit (429) | RETRYABLE | Backoff with max retries | NHTSA API throttled |
| Auth failure | AUTHENTICATION | Fail, log credentials issue | Invalid API key |
| Missing config | CONFIGURATION | Fail fast, clear message | DB_PASSWORD not set |
| Invalid data | DATA | Log and skip record | Malformed OBD response |
| System error | SYSTEM | Fail with diagnostics | Out of memory |

### Retry Strategy

- **Max retries**: 3 (configurable)
- **Backoff**: Exponential (1s, 2s, 4s, 8s, 16s)
- **Retry codes**: 429, 500, 502, 503, 504

### Exit Codes

| Code | Constant | Meaning |
|------|----------|---------|
| 0 | EXIT_SUCCESS | Successful completion |
| 1 | EXIT_CONFIG_ERROR | Configuration error |
| 2 | EXIT_RUNTIME_ERROR | Runtime/workflow error |
| 3 | EXIT_UNKNOWN_ERROR | Unexpected exception |

---

## 8. Logging and Observability

### Log Levels

| Level | Usage |
|-------|-------|
| DEBUG | Variable values, flow tracing, detailed diagnostics |
| INFO | Normal operational events, milestones |
| WARNING | Unexpected but handled situations |
| ERROR | Errors requiring attention |

### Log Format

```
2026-01-21 10:30:45 | INFO     | module_name | functionName | Message here
```

### PII Masking

The PIIMaskingFilter automatically masks sensitive data:
- **Email**: `user@example.com` → `[EMAIL_MASKED]`
- **Phone**: `555-123-4567` → `[PHONE_MASKED]`
- **SSN**: `123-45-6789` → `[SSN_MASKED]`

### Metrics to Track

- OBD-II connection success rate
- Data logging rate (records/second)
- Analysis duration (seconds)
- AI recommendation frequency
- Error rates by category

### Persistent Journald (US-210, US-230 acceptance signal)

Pi logs land in `journalctl -u eclipse-obd` (and the system journal). The
default systemd-journald `Storage=auto` puts logs on tmpfs (`/run/log/journal`)
when `/var/log/journal` does not exist -- a power-loss or service crash
takes the logs with it. US-210 ships the drop-in
`/etc/systemd/journald.conf.d/99-obd-persistent.conf` with
`Storage=persistent` so journald creates `/var/log/journal/<machine-id>/`
on next restart.

**Acceptance signal is the machine-id subdir, not the parent.** Pre-US-230
the deploy-time check only looked for `/var/log/journal/` existence.
Spool's 2026-04-23 post-deploy audit caught the actual failure mode: the
parent dir was present but EMPTY, so journald still wrote to tmpfs.
US-230 tightens the check:

| Signal | Pass condition |
|--------|----------------|
| `cat /etc/machine-id` | non-empty string |
| `/var/log/journal/<machine-id>/` | exists as a directory |
| `journalctl --disk-usage` | reports `[1-9][0-9]*[BKMGT]? in the file system` (non-zero) |
| `systemctl is-active systemd-journald` | `active` |

The drop-in install requires an explicit `systemctl restart systemd-journald`
for Storage=persistent to take effect; systemd does not hot-reload
journald.conf.d/ changes without a service restart. The deploy step
sleeps 2s after restart to let journald create the machine-id subdir and
rotate the first log segment before verification.

**Failure-mode policy.** On any of the four signals failing, deploy-pi.sh
prints diagnostics (disk-usage, `ls /var/log/journal/`, `journalctl
--verify`, conf.d contents, `is-active`) and exits non-zero. It does NOT
silently `mkdir /var/log/journal/<machine-id>/` as a recovery -- that
paper-fix would hide the real cause (stale tmpfs bind, disk-full,
SELinux, journald failing to pick up Storage=persistent). The operator
files an inbox note with the diagnostic output and proposes the recovery
path before re-deploying.

Live verification: `bash tests/deploy/test_journald_persistent_install.sh`
(autotools-style SKIP exit 77 when SSH is unreachable; runs the same four
checks the deploy post-check runs).

---

## 9. Security Considerations

### Secrets Management

- Never commit secrets to version control
- Store credentials only in `.env` file
- Use `${VAR}` placeholders in config.json
- Secrets loader masks values in logs with `[LOADED]`

### Data Protection

- PII masking in all log output
- No external network exposure (local only)
- Database file permissions (owner read/write only)

### Input Validation

- All OBD-II responses validated before storage
- Configuration validated on startup
- Export filenames sanitized

---

## 10. Display Architecture

### Display Failure Contract (ARCH-014, 2026-08-30)

**A render loop must reschedule itself on a path an exception cannot skip, and a
failure that costs a frame must be visible.**

This section exists because there was no home for the invariant. Both live loops
(`tick` at 4 Hz, `imuTick` at 10 Hz in `carousel.js`) booked the next tick on the
LAST line of an `async` body, so any throw skipped the reschedule and ended the
loop permanently. Nothing awaited the returned promise, so the failure was an
unhandled rejection -- silent by construction, with no log written anywhere.
Measured on the car 2026-08-30: the renderer sat at flat cumulative CPU in state
`Sl` while every state file kept updating. **Zero CPU was the tell -- the loop was
not stuck, it had ceased to exist**, and touch died with it because a
deterministic throw in the render path also kills the touch-driven redraw.

The contract is enforced by `makeResilientLoop`, which books the next tick exactly
once whether the body returns, throws, or rejects, and by a level-gated reporter
whose **error level is never gated** -- the absence of error reporting is what hid
this defect for weeks, so making errors configurable would rebuild that blindness.
`setInterval` is NOT the remedy despite surviving a throw for free: it stacks when a
read outruns its period, which is why US-508 chose `setTimeout` in the first place.

⚠️ **This is a failure contract, not a scheduling implementation.** It binds any
future display stack, including the Ozone/DRM kiosk migration -- a rewritten render
loop inherits the obligation, and the reason this is written down is that the
invariant is precisely the kind of fact that gets silently re-broken by someone
tidying an async body.

### Display Layout (480x320)

```
┌───────────────────────────────────────────┐
│ Eclipse OBD-II                 ▲ Connected│
│ Profile: Daily                       [D]  │
├───────────────────────────────────────────┤
│                                           │
│  RPM:    2500         Speed:  45 mph      │
│  Temp:   185°F        A/F:    14.7:1      │
│  Boost:  8.2 psi      Volts:  14.2V      │
│                                           │
├───────────────────────────────────────────┤
│ No Alerts                    🔋 98% [AC]  │
└───────────────────────────────────────────┘
```

### Display Modes

| Mode | Behavior |
|------|----------|
| headless | No display output, logs only |
| minimal | OSOYOO HDMI display shows status screen |
| developer | Detailed console logging |

### Display Tiers

The primary driving screen has two data-rendering tiers, selected by the
orchestrator based on connectivity and data availability. Both share the
same 3x2 gauge grid; only the surrounding chrome differs.

| Tier | Module | Adds over previous |
|------|--------|--------------------|
| Basic (US-164) | `src/pi/display/screens/primary_screen.py` | 6-parameter grid, OBD dot, profile tag, alert line, SOC + power source |
| Advanced (US-165) | `src/pi/display/screens/primary_screen_advanced.py` | 3 connectivity dots (OBD / WiFi / Sync), `[min / max]` bracket per gauge, 4-band color coding (blue/white/orange/red), extended footer (last-sync relative time + drive count) |

**Color palette (advanced tier, spec 2.4)**: blue = cold/below normal,
white = normal, orange = caution, red = danger. Basic tier retains the
white/yellow/red palette — both tiers co-exist without regression.

**Threshold source**: `config.json::pi.tieredThresholds` (never hardcoded).
Evaluators in `src/pi/alert/tiered_thresholds.py` return an `AlertSeverity`;
`src/pi/display/theme.py::advancedTierSeverityToColor` maps severity to
color. No config duplication.

**Min/max markers**: sourced from `src/pi/data/recent_stats.py::queryRecentMinMax`,
which reduces the last N rows of the `statistics` table per parameter
(N configurable, default 5).

### Display Surface (primary driving screen)

> **pygame status overlay fully retired (US-485, V0.29.15).** There used to be
> **two** pygame surfaces (primary + a `pi.hardware.status_display` overlay). The
> overlay was config-disabled in US-402 (V0.29.3) once the F-092 HTML carousel
> reached parity, then **fully removed in US-485**: `status_display.py`,
> `dashboard_layout.py`, all `HardwareManager` wiring, and the
> `pi.hardware.statusDisplay` config key are gone. The **carousel is the sole
> dashboard surface** (fed by the US-480 state-file emitters), and the single
> remaining pygame surface is the primary driving screen below.

The Pi runtime wires one pygame surface for the live driving screen:

| Surface | Module | Owner | Renderer |
|---------|--------|-------|----------|
| Primary (driving screen) | `pi.display.manager` + `pi.display.screens.*` | Orchestrator | Headless / Minimal / Developer drivers; the Minimal driver calls `pygame.display.set_mode` under X11 with `DISPLAY=:0 XAUTHORITY=~/.Xauthority SDL_VIDEODRIVER=x11` per Session 22 baseline. |

**Historical note (TD-024 / US-198)** — the retired status overlay ran on SDL's
*software* renderer because pygame's wheel-bundled SDL2 defaulted to an EGL/GL
context under X11 and the X server denied GLX with `BadAccess`, whose Xlib
default handler calls `exit()` and killed the orchestrator runLoop at uptime
~0.6s (Session 23 live drill). That failure mode retired with the overlay
(US-485). The primary display keeps the native x11 renderer, proven in Session 22.

### Full-Canvas Status Overlay Redesign (US-257, B-052, Sprint 21) — RETIRED (US-485)

> **Retired (US-485, V0.29.15).** This section documents the pygame status
> overlay's canvas-aware redesign. The overlay is **fully removed** —
> `status_display.py`, `dashboard_layout.py` (`computeLayout` / `DashboardLayout`
> / the 4-quadrant layout / `updateShutdownStage` / `ShutdownStage`), and their
> tests no longer exist. Kept below only as historical record; the HTML carousel
> is the sole dashboard surface. The `pi.display.displayCanvas` config keys are
> likewise orphaned (no live consumer).

The legacy 480x320 strip rendered fine on the OSOYOO touchscreen but
occupied a small fraction of the Eclipse's HDMI canvas (CIO observation
during 2026-05-01 drain test 5). US-257 split the layout out of
`status_display.py` into a pure-geometry module
`pi.hardware.dashboard_layout` so the same render path drives any canvas
size — 480x320 dev/test, 1280x720, 1920x1080 — without code branches.

**Quadrant layout** (fixed for muscle memory):

```
┌────────────────────────┬────────────────────────┐
│  NW: engine            │  NE: power state       │
│  battery % + voltage   │  source + stage banner │
├────────────────────────┼────────────────────────┤
│  SW: drive             │  SE: alerts            │
│  OBD2 connection       │  warning/error counts  │
├────────────────────────┴────────────────────────┤
│              footer: uptime + IP                │
└─────────────────────────────────────────────────┘
```

`dashboard_layout.computeLayout(canvasWidth, canvasHeight)` produces a
frozen `DashboardLayout` with quadrant `Rect`s, a footer rect, scaled
`FontScale` (title / value / label / detail), and proportional padding.
Font sizes scale linearly with canvas height against a 1080-tall reference
and clamp to a readable minimum so the legacy 480x320 case still renders
without truncation.

**Staged-shutdown stage banner** (NE quadrant): the new
`updateShutdownStage(stage)` setter wires the US-216 / US-252 ladder
through to the dashboard. The NE quadrant background tints with the stage
color (NORMAL=green / WARNING=amber / IMMINENT=orange / TRIGGER=red)
during a transition so an operator several feet from the screen can read
the stage at a glance. NORMAL leaves the background black to avoid
"always-amber" alarm fatigue.

**Config surface** (additive, backwards-compat with 480x320):

```json
"pi": {
  "display": {
    "width": 480,
    "height": 320,
    "displayCanvas": {
      "width": 1920,
      "height": 1080,
      "mode": "auto"
    }
  }
}
```

`displayCanvas.mode='auto'` is a hint that the consumer can call
`pygame.display.Info()` to detect screen dims at start time. An explicit
`width`/`height` falls back to those values literally. The legacy
`pi.display.width`/`height` keys are unchanged so existing dev/test rigs
keep working.

**Test surface** (retired US-485): `tests/pi/hardware/test_dashboard_layout.py`
and `tests/pi/hardware/test_status_display.py` were removed alongside the
modules they exercised. They previously covered the geometry tiling across
(1920,1080) / (1280,720) / (480,320) and the `updateShutdownStage` enum/string
coercion.

### Live-Data HDMI Render (US-192)

The orchestrator writes `realtime_data` rows to the Pi's local SQLite; the
HDMI primary-screen renderer runs as a **peer process** that polls those
rows each frame. They do not share a pygame Surface — the decoupling keeps
the orchestrator free of GL context state and lets the renderer restart
independently.

```
main.py orchestrator ──writes──▶ data/obd.db (realtime_data)
                                        │
                                        │  polled each frame
                                        ▼
       scripts/render_primary_screen_live.py --from-db
                                        │
                                        │  pygame.display.flip()
                                        ▼
                              OSOYOO 3.5" HDMI @ 480x320
```

**Live-readings poll layer** — `src/pi/display/live_readings.py`:

| Function | Purpose |
|----------|---------|
| `PARAMETER_ALIASES` | Maps collector-side names (e.g., `BATTERY_V` from US-199 ELM_VOLTAGE path) to display-side gauge slots (`BATTERY_VOLTAGE`). |
| `buildReadingsFromDb(dbPath, names)` | Returns latest value per gauge. `data_source = 'real'` only (NULL BC for pre-US-195 rows). Opens SQLite read-only via `file:…?mode=ro` URI; missing file / missing table degrade to `{}`. |
| `resolveGaugeName(n)` | Alias-aware name resolution, unknown names pass through. |

**Render harness** — `scripts/render_primary_screen_live.py --from-db PATH`:

Each frame at ~10 FPS, the harness calls `buildReadingsFromDb` and feeds the
dict into `buildBasicTierScreenState`. Gauges without a fresh row render
the `---` placeholder (renderer already handles this via `_PLACEHOLDER_VALUE`
in `primary_screen.py`). Without `--from-db` the harness falls back to the
US-183 scripted RPM sweep (kiosk demo mode).

**systemd env block** — `deploy/eclipse-obd.service` sets:

```
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/mcornelison/.Xauthority
Environment=SDL_VIDEODRIVER=x11
```

These propagate to any process the service spawns AND to the interactive
SSH session the CIO uses to launch the render harness. `SDL_VIDEODRIVER=x11`
is the Session 22 baseline that visibly paints the OSOYOO; the Status
Overlay's `forceSoftwareRenderer` (US-198) is independent and does not need
overrides here.

**CIO verification**: `bash scripts/verify_hdmi_live.sh --duration 30`
stops the service, starts `main.py --simulate` in the background, launches
the render harness in `--from-db` mode against `data/obd.db`, and asks the
CIO to eyeball that the six gauges show live non-zero values. Simulator
path is the valid acceptance path — engine isn't required.

### Session 22 pygame hygiene — closure audit (US-215)

US-215 (2026-04-21) audited four informally-referenced Session 22 pygame
hygiene concerns — `TD-019` DISPLAY/XAUTHORITY env vars, `TD-020` pygame-on-tty,
`TD-021` multi-HDMI dev workflow, `TD-022` `--no-binary` pygame rebuild on
Python 3.13. Finding: **no formal TD files were ever filed** under
`offices/pm/tech_debt/TD-01{9,20,21,22}*.md`; the IDs appeared only in auto-memory
and inbox grooming notes as placeholders for "audit next session." Per-ID
disposition:

| ID (informal) | Concern | Status | Rationale |
|---------------|---------|--------|-----------|
| TD-019 | DISPLAY / XAUTHORITY / SDL_VIDEODRIVER env vars | **Resolved by US-192** | `deploy/eclipse-obd.service` lines 67–69 ship the env block; see §10 "systemd env block" above. |
| TD-020 | pygame on tty console (no-X) | **Moot in production** | Pi-in-car deployment auto-starts X via lxsession; tty-only was never a production target. |
| TD-021 | Multi-HDMI dev workflow (xrandr force primary) | **Moot in production** | Single-HDMI production config; dev-only note not carried forward. |
| TD-022 | `--no-binary :all:` pygame rebuild fails on Python 3.13 | **Deferred — wheel path is production** | SDL2 wheel-bundled pygame is the production install path; `--no-binary` path is a nice-to-have for kmsdrm work and not a blocker. |

No TD files created retroactively — per CIO drift-observation rule, TDs filed
post-hoc for informal references that never graduated to formal status add
noise without adding signal. The audit trail lives here and in the inbox note.

---

## 10.5 DTC Lifecycle (US-204)

Spool Data v2 Story 3 added Diagnostic Trouble Code (DTC) capture so the
"Is the check engine light on?" question — Question 1 of every engine
health review — has a recorded answer.

### Table shape

`dtc_log` (Pi SQLite + MariaDB mirror):

| Column | Notes |
|--------|-------|
| `id` | INTEGER PK AUTOINCREMENT (sync delta cursor). |
| `dtc_code` | TEXT NOT NULL (e.g. `"P0171"`). |
| `description` | TEXT — empty string for unknown / Mitsubishi P1XXX codes (never fabricated). |
| `status` | CHECK in (`stored`, `pending`, `cleared`). Sprint 15 only writes the first two. |
| `first_seen_timestamp` | DEFAULT `strftime('%Y-%m-%dT%H:%M:%SZ', 'now')` — US-202 canonical. |
| `last_seen_timestamp` | Same default; bumped via UPDATE on duplicate within the same drive. |
| `drive_id` | INTEGER NULL — inherited from US-200 context (`getCurrentDriveId()`). |
| `data_source` | DEFAULT `'real'` per US-195; CHECK enum (`real`/`replay`/`physics_sim`/`fixture`/`foreign`). `foreign` = US-424 foreign-vehicle marker. |

Indexes: `IX_dtc_log_drive_id` (per-drive analytics) + `IX_dtc_log_dtc_code`
(cross-drive lookup of a specific code).

### Capture timing

```
Drive starts (RPM crosses cranking threshold)
  -> DriveDetector._openDriveId mints drive_id, publishes via setCurrentDriveId
  -> DriveDetector._startDrive emits onDriveStart(session)
       -> EventRouterMixin._handleDriveStart
            -> DtcLogger.logSessionStartDtcs(driveId=None, connection=...)
                 -> Mode 03 GET_DTC          (stored DTCs)
                 -> Mode 07 GET_CURRENT_DTC  (pending DTCs; probe-first)
                 -> rows INSERTed with drive_id from context, data_source='real'

Mid-drive: each MIL_ON poll observation -> _handleReading
  -> MilRisingEdgeDetector.observe(value)
  -> if 0->1 transition: DtcLogger.logMilEventDtcs
       -> Mode 03 GET_DTC (re-fetch)
       -> per code: UPDATE last_seen if (drive_id, dtc_code) exists, else INSERT
```

### 2G DSM Mode 07 fallback

The 1998 2G ECU pre-dates full OBD2 compliance — Mode 07 may return a null
frame. `DtcClient.readPendingDtcs` returns
`(codes, Mode07ProbeResult(supported=...))`; when `supported=False` the
caller is expected to cache the result on the connection instance and
skip subsequent Mode 07 calls until reconnect. The probe verdict is
NOT persisted to disk — re-probing on reconnect is cheap and avoids
stale assumptions across hardware swaps.

### Server mirror

`src.server.db.models.DtcLog` — same column shape plus the standard
synced-table columns (`source_id`, `source_device`, `synced_at`,
`sync_batch_id`) and the `(source_device, source_id)` UNIQUE upsert
key. `_TABLE_REGISTRY` in `src/server/api/sync.py` includes `dtc_log`;
`PK_COLUMN['dtc_log'] = 'id'` registers the Pi-side delta cursor.

The live MariaDB physical table reaches that shape via deploy-time
migration `v0005_us238_create_dtc_log.py` (Sprint 19). Sprint 15 US-204
predated the US-213 explicit migration registry, so the ORM and
sync wiring shipped without a CREATE TABLE on the production server —
Ralph's Drive 4 health check on 2026-04-29 caught the gap as V-2
(`Table 'obd2db.dtc_log' doesn't exist`). Drive 4's DTC_COUNT was 0 so
no rows were lost, but the next DTC drive would have written to Pi
only. v0005 closes the gap with the same idempotent CREATE-TABLE-IF-NOT-EXISTS
+ post-condition probe pattern as v0002 (battery_health_log). See
Section 5 Server Schema Migrations subsection for migration registry
mechanics.

### Invariants honored

1. Every dtc_log row carries `drive_id` (or NULL only when no drive
   context exists — defensive; orchestrator should not dispatch MIL
   events outside RUNNING).
2. Mode 07 probe is per-connection cache, not persisted.
3. DTC descriptions come from python-obd's `DTC_MAP`; unknown codes
   land with empty description rather than fabricated text.
4. Duplicate detection scoped to `(drive_id, dtc_code)`. Same code in
   a new drive INSERTs a fresh row.
5. DTC capture is event-driven, not tier-scheduled. `dtc_log` is NOT
   in `config.json:realtimeData.parameters` and not in any pollingTier.
6. Schema-DEFAULT timestamps (`strftime('%Y-%m-%dT%H:%M:%SZ', 'now')`)
   keep US-202 canonical timestamp invariant intact.

---

## 10.6 Shutdown Sequencer (SS-T5, supersedes Power-Down Orchestrator)

The legacy `PowerDownOrchestrator` staged VCELL ladder
(NORMAL→WARNING→IMMINENT→TRIGGER) was **deleted** (commit `9adb0fb`,
Phase-2 T9). The sole shutdown decider is `ShutdownSequencer`
(`src/pi/power/power_watch/controller.py`), an isolated systemd service
(`eclipse-powerwatch`, separate failure domain from `eclipse-obd`).

**Flow.** `PowerSourceProvider` reports power LOST → **5 s smoothing**
(`pi.powerWatch.smoothingSec`, configurable; a single power-present read
within the interval cancels — pure blip rejection; this is the safety
property, shipped in V1) and **boot-grace** → arm-self-check (refuse to arm
if GPIO6 does not read power-present at start) → a bounded pre-shutdown
**window** of ordered `ShutdownTask`s (V1: exactly one, `SyncWithServerTask`;
pluggable seam via `__main__.buildV1Tasks`) → window exits on
**all-tasks-terminal OR `windowCapSec`** → graceful `systemctl poweroff`.
**Emergency:** a *successful* VCELL read ≤ `vcellFloorVolts` short-circuits
straight to poweroff; a *failed* VCELL read never powers off
(uncertainty ≠ power loss).

> **History extracted (2026-06-01):** the superseded `PowerDownOrchestrator`
> ladder + the SOC%-calibration lesson + the Sprint-40 **F-7** (boot-grace latch)
> and **F-8** (boot-progress instrument) bug-fix narratives + the Rule-10 gate
> record → **`specs/arch/subsystem-evolution-history.md`**. Current behavior is
> the Flow above.

### 10.6.1 F-103 shutdown-splash phase-emit hook (US-394, Sprint 48 / V0.29.2) [Atlas A-2]

The `ShutdownSequencer` is the **SSOT of shutdown phase + timing**. US-394 added a
**phase-emit hook** so the F-103 grace-period shutdown splash can render the staged
shutdown the driver is watching, instead of a frozen/blank screen. The hook is a
single OPTIONAL constructor dependency — `phaseEmitFn` — injected in
`__main__.py` from `pi.splash.shutdown_state_emitter.makeShutdownPhaseEmitter`
(gated on `pi.splash.enabled`). When unwired (`None`) the sequencer runs the exact
legacy path with **no extra `isOnBattery()` read** — byte-identical behavior.

**Dependency direction is strictly unidirectional (spec §6/§481).** The sequencer
owns the phase **decisions** and the canonical phase-string constants
(`PHASE_GRACE` / `PHASE_CANCELLED` / `PHASE_FLUSHING` / `PHASE_POWERING_OFF` in
`controller.py`); the splash subsystem **consumes** them
(`pi.splash.shutdown_state_emitter` imports them). The sequencer **never imports
the splash** — it calls a generic callback and stays ignorant of the splash schema.

**Phases emitted (mapped to the sequencer's code-path transitions):**

| Transition point in `handleOnBattery` | Phase | Splash response |
|---|---|---|
| Power-lost signal present at entry, **before** smoothing resolves (T=0) | `grace` | TRIGGER splash; play PRE_ROLL + ANIMATING (the animation *is* the grace countdown) |
| Smoothing window failed (power returned mid-smoothing) | `cancelled` | ABORT splash (kill chromium, no fadeout) |
| Smoothing confirmed + above VCELL floor; bounded pipeline about to run | `flushing` | CONTINUE (no state change) |
| Immediately before `systemctl poweroff` (normal path **or** VCELL-floor fast-path) | `powering_off` | CONTINUE → enters BLACK_TAIL |
| Power returned during the bounded pipeline window (late abort) | `cancelled` | ABORT splash (so it does not sit in BLACK_TAIL awaiting a poweroff that will not fire) |

The VCELL-floor fast-path skips the pipeline, so it emits `powering_off` **without**
a preceding `flushing` (honest instrument — no flush happened).

**Emit-hook constraints (Atlas A-2):** (a) the write is best-effort and non-blocking;
(b) emission happens **after** each transition is decided, never before; (c) a write
failure (or a hook that raises) is logged but **NEVER blocks shutdown progress** —
the emitter closure catches, and the sequencer's `_emitPhase` wraps the call site
belt-and-braces. The shutdown-state schema (`phase`, `tGraceStartedAt`,
`tGraceTotalS`, `tRemainingS`, `reason`, `ts`) is written atomically to
`/run/eclipse-obd/states/shutdown-state` (the `splash-grace.path` unit watches that
file; the kiosk polls it at 250 ms).

### 10.6.2 US-526 pre-poweroff hook — the PRIMARY drain-event close (Sprint 70 / V0.29.25)

A second OPTIONAL constructor dependency, `prePowerOffFn`, runs immediately
**before** `powerOffFn` on **every** path that actually powers off — the
bounded-pipeline path *and* the VCELL-floor fast path. `__main__.py` wires it via
`buildDrainCloseHook` to the production drain-event writer's close (§ *Production
drain-event writer*, Atlas Option C 2026-08-02).

**Why not a `ShutdownTask`:** the VCELL-floor fast path **skips the pipeline**,
and that path is exactly how a run-to-cutoff drain ends. Under Spool's depth gate
the run-to-cutoff drain is the *only* qualifying drain, so a task-based close
would miss every row the battery-Health verdict needs.

Ordering and guarantees mirror `phaseEmitFn` (§10.6.1): it runs **after**
`powering_off` is emitted and **last** before poweroff (so the recorded depth is
as deep as the drain actually got); a hook that raises is logged and **never**
blocks poweroff — a bookkeeping row is not worth leaving the Pi up on a dying
battery; and it is **not** called on either abort (transient blip, or power
returning mid-window), because an aborted shutdown is not a drain end and the
collector's BATTERY→AC transition owns that close. `None` (the default) runs the
exact legacy path. A missed close is not data loss with a wrong value — the boot
reaper marks that row interrupted (`runtime_seconds` + `end_vcell_v` NULL).

**Timing invariant [Atlas A-6]** (owned by the `controller.py` module docstring;
splash holds it by trust): the splash's 7.5 s animation budget fits inside the
sequencer's ~10–12 s time-to-poweroff at the default `pi.powerWatch.smoothingSec=7`.
If `smoothingSec < 4` the animation may be killed mid-frame — *acceptable* failure
mode (degraded UX, no data loss). No new config key, no runtime coordination.

**C-5 lifecycle — `shutdown-state` must survive `eclipse-obd.service` stop.** The
shutdown splash reads `shutdown-state` *during* the shutdown sequence, after
`eclipse-obd.service` may already have stopped. Because `eclipse-obd.service`'s
`RuntimeDirectory=eclipse-obd` is removed on its stop, the states dir would vanish
exactly when the splash needs it — unless another live unit holds the shared
ref-counted `RuntimeDirectory`. `eclipse-states-http.service` runs continuously and
shares `RuntimeDirectory=eclipse-obd` (+ `RuntimeDirectoryPreserve=yes`), and the
`/etc/tmpfiles.d/eclipse-obd-states.conf` entry recreates `states/` at every boot.
Together these keep `/run/eclipse-obd/states/shutdown-state` readable across
`eclipse-obd`'s stop. The multi-owner runtime-dir contract is documented in full in
the **F-103 Splash Subsystem** section below (US-393); this section is the
shutdown-state half of that contract.

### 10.6.3 Sync custody at poweroff (US-621, Sprint 77 / V0.29.34) [Atlas Rule 10]

**The defect this closes.** On 2026-08-28 the CIO drove off-WiFi, returned, and the Pi ran a full
graceful shutdown -- `systemd-poweroff`, filesystems synced, journal closed. Every signal said the
system had shut down correctly. **~35 minutes of capture, on the order of 15,000 rows, had never
left the Pi.**

The shutdown sequencer was correct about the thing it was built for -- the local DB is `fsync`'d and
crash-safe -- and simply had **no concept of the upload queue**. Verified at the time: `grep -i sync`
over `src/pi/power/` returned only SQLite-durability references.

**Why that is a defect and not a limitation.** Nothing was lost; the backlog drains on the next boot
in range. The defect is that **the operator could not tell.** "Clean shutdown" is precisely the
signal a human uses to decide the data is safe, and it was silent about the half that was not. That
is the same species as `power_log` recording only the healthy state and `data_quality` reading
`full` over a 751 s gap: *a system reporting a confidence it has not earned.*

**Shape: record first, drain second.** The recording half is cheap, needs no network, and closes the
*silent* defect on its own. A bounded drain is the optimisation. **Shipping only the drain would
have left the same false confidence every time the bound was hit.**

⚠️ **Wired on the PRE-POWEROFF path, NOT as a pipeline `ShutdownTask`** -- and the reason is
load-bearing. The **VCELL floor fast-path SKIPS the pipeline**, and that is precisely the
run-to-cutoff shutdown carrying the most undelivered data. A custody record that is absent from the
worst case is not a custody record. (Same reasoning as the US-526 drain close, §10.6.2.)

**Invariants:** never raises, and **never delays a poweroff.** The record is a diagnostic; a
diagnostic that can hold a dying machine open is worse than no diagnostic.

**Explicit non-goal:** a *guaranteed* full drain. On a UPS budget that is not achievable, and
promising it would be the same over-claim this section exists to remove.

### 10.6.4 The open drain row is checkpointed every 30 s (US-605, Sprint 77 / V0.29.34) [Atlas Rule 10]

An in-progress drain event was written once, at close. A power loss before that close lost the whole
event -- the exact scenario a drain log exists to describe.

The row is now checkpointed at **30 s** (Spool `[EXACT: 30]`), which converts a lost write from
*"the drain never happened"* into *"the drain is known up to its last checkpoint."*

⚠️ **The reaper can now close ONTO a checkpoint**, which is what the cadence buys. And an
**un-checkpointed reaped row is identifiable by its signature** -- so the record distinguishes
*"ended here"* from *"we stopped knowing here."* That distinction is the whole value: without it a
truncated drain and a completed one are indistinguishable rows.

### 10.6.5 `power_log` records transitions, not only the healthy state (US-626, Sprint 77 / V0.29.34) [Atlas Rule 10]

**The defect.** Across ten Pi boots on 2026-08-28, `power_log` held **14 rows, every one
`ac_power`.** Zero `battery_power`, zero `transition_to_battery`; `battery_power` last written
2026-08-17, `transition_to_battery` last written 2026-05-20. **A power monitor that cannot record
power loss is not a monitor** -- it reads "healthy" through every outage.

**Two structural additions:**

- **`PowerObservation` -- an honest THREE-STATE read.** The power source is *present*, *absent*, or
  *unknown*. Collapsing unknown into either of the other two is what let an unread sensor look like
  mains.
- **Which instrument witnessed a row is recorded.** A row now carries its observer, so "no
  transitions occurred" becomes a *positive statement* rather than an inference from an empty log.
  **An empty log and a dead writer were previously the same evidence.**

⚠️ **What this does NOT fix:** an in-process logger still cannot witness its own machine's death.
On a hard rail collapse there is no poll interval left and no time to reach SQLite. The structural
answer -- reconstructing the loss at next boot from a last-known-good heartbeat -- remains **open**
(A-22). This section documents a monitor that now records what it *can* see; it does not claim
coverage of the case where the observer dies with the observed.

## 10.7 Data Pipeline Architecture (B-104 Step 1, Sprint 41 / V0.27.17)

**Architectural principle (CIO 2026-05-21).** Pi = telemetry emitter +
event-log writer. Server = sole authority for derived/persisted analytics.
The Pi captures raw OBD events plus drive boundary event-log fields and
syncs both to the server; the server computes every derived analytics
table (`drive_summary` analytics columns, `drive_statistics`, future GEM
family, future Mahalanobis baselines, ...) from the raw event stream.
Pi *may* compute in-drive aggregates locally for HDMI dashboard / alert
consumers — engine running = AC power, no battery cost — but those
aggregates are **not transmitted**. Default rule: *if the server can redo
it from raw data, the Pi does not transmit it.*

### Compute path

The server compute path lives in
`src/server/analytics/drive_summary_compute.py` (US-350; analytics columns
on `drive_summary`), `src/server/analytics/drive_statistics_compute.py`
(US-351; per-`parameter_name` aggregate rows on `drive_statistics`), and
`src/server/analytics/derived_signals_compute.py` (US-436 / F-106; one
`drive_derived_signals` row per drive — see §10.7.2). All three are keyed on
the Pi-local `drive_id` (matches `realtime_data.drive_id` and
`drive_summary.source_id`) and persist on the server-side
`drive_summary.id` PK.

- `drive_summary` analytics columns (`start_time`, `end_time`,
  `duration_seconds`, `row_count`, `is_real`) are derived from
  `MIN(realtime_data.timestamp_utc)` / `MAX(...)` /
  `COUNT(*)` for the drive. `is_real` is derived from the Pi event-log
  `data_source` per Atlas Q2: `'real' → 1`, `'simulator' → 0`, NULL →
  NULL (never silently 0; NULL distinguishes *tested-not-real* from
  *untested*). The Pi event-log fields on `drive_summary`
  (`drive_start_timestamp`, `ambient_temp_at_start_c`,
  `starting_battery_v`, `barometric_kpa_at_start`, `data_source`) are
  preserved unchanged — the server compute path enriches from those
  columns but never overwrites them. **US-437 (N-8, Sprint 53 / V0.29.7)**
  additionally backfills `drive_summary.profile_id` from the earliest
  non-NULL `realtime_data.profile_id` for the drive (preserve-NULL,
  never-clobber, idempotent): the profile_id-population path was collateral
  of the US-350/B-104 trigger-seam retirement (the writer that set it was
  removed and `compute_drive_summary` never carried the assignment forward),
  which had left every server row's `profile_id` NULL.
- `drive_statistics` is computed via `compute_drive_statistics(session,
  driveId)`: read raw rows grouped by `parameter_name`, run
  `src/server/analytics/helpers.computeBasicStats` (Spool FLAG-1 SSOT
  pin — the 2-sigma outlier helper is the single source of truth for
  outlier math; cannot drift to IQR / 3-σ silently), DELETE-then-INSERT
  the per-PID rows for clean idempotent replay. The server-side schema
  (Atlas Q4 DDL, `src/server/db/models.py:DriveStatistic`) uses a
  composite PK `(drive_id, parameter_name)` with
  `FK drive_summary.id ON DELETE CASCADE`, a `data_quality` enum
  (`full` / `sparse` / `below_threshold`) classified per Atlas Refinement
  B (`<10 → below_threshold`, `10-99 → sparse`, `≥100 → full`), and
  `computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE
  CURRENT_TIMESTAMP` for observable idempotency on re-run.
- Atlas Refinement A generic invariants (`min ≤ avg ≤ max`,
  `std_dev ≥ 0`, no NaN/inf, `sample_count ≥ 1`) are enforced by the
  compute path and raise `InvariantViolation` on violation pre-flush so
  the caller's rollback is safe. Per-PID envelopes (RPM ≤ 8000, etc.)
  are deferred to V0.28+.

### Pi-side retirement scope

- The Pi-side `drive_summary` *computed-field* writer is retired. The Pi
  still writes the *event-log* fields above for in-drive diagnostics
  (`drive_start_timestamp`, `ambient_temp_at_start_c`,
  `starting_battery_v`, `data_source`) — those are event records the
  server cannot recompute and the file `src/pi/obdii/drive_summary.py`
  is untouched by US-350/US-351.
- The Pi-side `drive_statistics` table is **retired entirely** (US-351).
  `src/pi/obdii/drive_statistics.py` is deleted; the
  `SCHEMA_DRIVE_STATISTICS` constant + `ALL_SCHEMAS` registration are
  removed from `src/pi/obdii/database_schema.py`; the new
  `ensureDriveStatisticsRetired()` helper performs an idempotent
  `DROP TABLE IF EXISTS` invoked by `ObdDatabase.initialize()` (INFO
  row-count log on first boot with the legacy table present; DEBUG
  absence log on subsequent boots). Detector + lifecycle wiring
  (`src/pi/obdii/drive/detector.py`,
  `src/pi/obdii/orchestrator/lifecycle.py`) is reverted to the
  pre-US-349 shape. Any future `from pi.obdii.drive_statistics import …`
  raises `ImportError` by design.
- The Pi-side legacy `battery_log` table (whose sole writer
  `BatteryMonitor` was deleted in US-223) is retired the same way
  (US-437 N-4, Sprint 53 / V0.29.7): the new
  `ensureBatteryLogRetired()` helper in
  `src/pi/obdii/database_schema.py` performs an idempotent
  `DROP TABLE IF EXISTS`, invoked by `ObdDatabase.initialize()` — an
  empty `battery_log` had been lingering on the live Pi after the server
  dropped it in US-223 / `v0003`. Mirrors `ensureDriveStatisticsRetired()`
  exactly (forensic row-count log on first boot; no-op when absent). The
  battery-protection domain is covered by US-217's `battery_health_log`.
- Pi-side raw `realtime_data` table + sync transport
  (`src/pi/obdii/realtime_data.py`, `src/pi/obdii/sync/`) are
  unchanged — the canonical raw event stream still flows to the
  server in the V0.27.16 shape; only the derived-analytics writer
  surface moves tiers.

### Trigger seam shift

The V0.27.7 (US-326 / US-328) and V0.27.16 (US-348 / US-349) writer
architectures both depended on a Pi-side drive-end signal to fire the
writer / sync trigger. Argus's 2026-05-21 RCA established that this
signal does not fire when a drive is terminated by sequencer-driven
poweroff — there is no engine-off OBD signal before the stack tears
down, and `DriveDetector` is wired for future drive-end events but
never catches *this* drive's actual end. The third cycle of this
false-pass class was the trigger for the B-104 Step 1 advance.

Post-Sprint-41 trigger seams are both server-side and both
independent of any Pi-side end-of-drive marker:

1. **Nightly batch** — `deploy/server-analytics-batch.service` +
   `deploy/server-analytics-batch.timer` (`OnCalendar=*-*-* 03:30:00`
   chi-srv-01 local; `Persistent=true` so missed fires catch up on
   next boot). The unit runs the on-demand CLI in `--all-stale` mode
   and refreshes every drive with NULL `drive_summary` analytics
   columns or missing `drive_statistics` rows.
2. **On-demand CLI** — `python -m src.server.cli.recompute_drive_analytics`
   with `--drive-id N` / `--drive-id-range A-B` / `--all-stale` /
   `--dry-run`. The per-drive loop invokes
   `compute_drive_summary`, `compute_drive_statistics`, and
   `compute_drive_derived_signals` (US-436) atomically so a single CLI
   tick refreshes all three analytics tables (Atlas Q1
   single-timer-fires-both-paths). The derived-signals compute degrades
   silently — a drive with `<2` SPEED rows returns `None`, writes nothing,
   and leaves the existing OK/anomaly log untouched.

The sync receipt path is **decoupled from compute**:
`_tryAutoAnalysisTrigger` in `src/server/api/sync.py` is deleted;
`enqueueAutoAnalysisForSync` in `src/server/services/analysis.py` is
converted to a `NotImplementedError` tripwire so an accidental
re-introduction of the trigger seam trips at runtime rather than
silently shipping a fourth cycle of the same bug class.

### Idempotent recompute principle

Recompute is idempotent: same raw `realtime_data` + same logic = same
output. Re-running the CLI over an already-computed drive yields
identical analytics-column values (`drive_summary`) and identical
data values across `(drive_id, parameter_name)` rows
(`drive_statistics`); `computed_at` advances on `drive_statistics` via
`onupdate=func.now()` as the observable replay signal. The deploy-layer
backfill in `deploy/deploy-server.sh` Step 4.9 (US-352) is
marker-file-guarded
(`${PROJECT}/.backfill-V0.27.17-drives-11-20-complete`) for deploy
ergonomics, but the underlying compute is correct under repeated
invocation either way — the marker prevents redundant work, not
divergence.

> **History extracted (2026-06-01):** the retired-writer cross-links
> (US-326/328/348/349) + the V0.27.17 empirical-status snapshot →
> **`specs/arch/subsystem-evolution-history.md`**.

### Architectural invariants preserved by the shift

- Pi-side drive boundary event log (`drive_start` / `drive_end`
  timestamps + Pi event-log fields on `drive_summary`) preserved for
  diagnostics (CIO 2026-05-21 ratified).
- Pi-side raw `realtime_data` table + sync client untouched; the
  canonical raw event stream still flows in the V0.27.16 shape.
- `drive_summary` server table schema preserved (the writer
  architecture is what shifts; the schema is fine).
- SSOT pattern (`[[ssot-design-pattern]]`): the server compute path
  is the SSOT for derived analytics; consumers (CLI, nightly timer,
  future dashboards) apply policy not their own acquisition. B-104
  Step 1 is the **second production application** of the SSOT
  pattern (first was the Shutdown Sequencer
  / §10.6 / Sprint 39 V0.27.15) — see Atlas's 2026-05-21
  SSOT-pattern-load-bearing observation note.
- B-104 Step 2+ scope (GEM family B-086..B-094, Mahalanobis B-083,
  per-tuning-spec recompute) is deferred to V0.28+ and lands
  server-side from day one under this same architecture.

> **History extracted (2026-06-01):** the B-104 3-cycle false-pass retrospective
> lesson + the Rule-10 gate record →
> **`specs/arch/subsystem-evolution-history.md`**.

### 10.7.1 DriveDetector dual-attribution remediation (F-107, Sprint 43 / V0.28.0)

**Defect of record.** The V0.27.18 IRL drill (2026-05-22) produced two
`drive_id`s (drives 23 + 24) for one physical leg: time-overlapping
`realtime_data` rows, ~2× polling cadence, RPM readings 1500-2000 apart
within the same second. RCA:
`offices/ralph/findings/2026-05-28-drive-detector-dual-attribution-rca.md`.
This is a Pi-side defect upstream of the §10.7 B-104 Step 1 architecture
(orthogonal to the Pi=emitter/server=authority shift) — carved out of the
V0.27 chain merge as a known scoped exception. The remediation is
**defense-in-depth across three tiers**, because the evidence has two
distinct root causes (a single process minting a spurious second drive,
and two concurrent processes each minting their own).

**Mechanism A — ECU-silence continuation (Pi detector, LIVE; US-361).**
`src/pi/obdii/drive/detector.py`: an ECU-silence-inferred `drive_end`
(quiet OBD link ⇒ inferred engine-off) is now **tentative**, not terminal.
When `_checkEcuSilenceDriveEnd` fires it records the closed `drive_id` +
time; if the engine demonstrably resumes (RPM back above the start
threshold) within `MIN_INTER_DRIVE_SECONDS` (5 s — the previously-defined-
but-unused constant the RCA named), the next `_startDrive` **re-attaches to
the prior `drive_id`** instead of minting a second. RPM-debounce and forced
(`forceKeyOff`) ends never arm the marker, so confirmed-engine-off drives
still mint fresh — US-229 silence behavior and the US-311 warm-restart e2e
are untouched.

**Mechanism B — single-instance guard (Pi orchestrator, ships DEFAULT-OFF;
US-361).** The production drives-23/24 evidence is two **concurrent**
`eclipse-obd` orchestrator processes; a single process cannot produce
overlap because `drive_id` is a process-global singleton, so a detector fix
alone cannot prevent it. New `src/pi/obdii/orchestrator/single_instance.py`
(`SingleInstanceGuard`, pidfile + injectable liveness seam) makes a second
concurrent process refuse to start — wired as step-0 of
`_initializeAllComponents`, released last in `_shutdownAllComponents`.
**Ships behind `pi.runtime.singleInstanceGuard.enabled` (default `False`)
and stays dark for V0.28.0 (Atlas ruling 2026-05-29, CIO-ratified).** The
guard's as-built failure mode is the silent-wrong-winner class the V0.27
chain spent itself killing: a live peer holding the pidfile makes the
*newly-deployed* process silently refuse and exit while the *stale* one
keeps running (it reclaims only dead pids), which under a US-354
deploy-hygiene miss actively enforces the V0.27.16 "running old code despite
new `.deploy-version`" pathology. Mechanisms A + C already cover the observed
defect, so for a defect seen exactly once, observability is the honest
posture rather than a load-bearing boot-path refuse. Production-enable is
gated on BOTH: (1) the Mechanism C tripwire flagging a second, independent
two-concurrent-process overlap in production (the case demonstrably
recurs); AND (2) the refuse path made loud + deploy-visible (WARN/ERROR +
nonzero exit the deploy script checks) plus a deploy-hygiene check proving
`systemctl restart` release-then-acquire ordering — incremental US-361
follow-up, not this sprint.

> **Status update (Sprint 47 / V0.29.1, US-389 — both gates now met).** The
> two-concurrent-process overlap DID recur in production (drives 28/29,
> ~2026-06-06), so per Atlas's 2026-06-19 RCA ruling the guard was
> **enabled out-of-band** (`pi.runtime.singleInstanceGuard.enabled=true`,
> commit `d6d8b05`) with its required `RuntimeDirectory=eclipse-obd` partner
> (commit `fae7ee7`) and deployed to the Pi. US-389 makes that durable: see
> **§10.7.1.1** below. Mechanism B is now **LIVE**, not dark.

**Mechanism C — server-side `attribution_anomaly` tripwire (LIVE; US-362 +
US-363).** `src/server/analytics/overlap.py::detect_overlapping_drives` is
the SSOT detector over raw `realtime_data` (US-362). US-363 wires it into
both server compute paths (`drive_statistics_compute.py`,
`drive_summary_compute.py`) so an overlapping drive is stamped
`data_quality='attribution_anomaly'`, surfacing the dual-emission pattern
downstream as a per-row flag — **observability, not refusal** (analytics are
still computed; the flag marks them for human disposition). The on-demand
CLI `python -m src.server.cli.recompute_drive_analytics` surfaces an
`[ATTRIBUTION_ANOMALY]` marker on affected drives. The schema surfaces this
needs are in the §5 "V0.28.0 Schema Pass" subsection.

**IRL execution deferred (US-364).** The production-DB backfill —
`recompute_drive_analytics --drive-id 23/24/25` against chi-srv-01,
idempotent re-run zero-diff, and release of the `regression_manifest`
F-005 + F-007 HOLDs on the observed result — runs as part of the Sprint-43
IRL validation drill, not a headless dev iteration (BL-022). It executes the
already-built path; it does not change the architecture documented here.

### 10.7.1.1 Root 1 deploy-invariant closure (US-389, Sprint 47 / V0.29.1)

The drives-28/29 recurrence re-confirmed Root 1 (two concurrent `eclipse-obd`
processes racing the shared `drive_counter` — the per-process `_currentDriveId`
singleton means neither sees the other's open drive, so a single physical leg
splits across two minting processes; full trace in
`docs/rca/2026-06-28-us387-drivedetector-close-signal-rca.md`). The guard +
`RuntimeDirectory` mitigation was applied out-of-band; US-389 bakes it into the
boot/deploy path as a **tested invariant** so it cannot silently regress.

**Matched-pair invariant (Atlas C-5).** The guard config flag
(`pi.runtime.singleInstanceGuard.enabled=true`) and the systemd unit's
`RuntimeDirectory=eclipse-obd` are a **matched pair** — neither may ship
without the other:

- guard ON **without** `RuntimeDirectory` ⇒ the non-root service (`User=mcornelison`)
  hits `EPERM` on `mkdir(/run/eclipse-obd)` when `acquire()` creates the lock's
  parent dir, and crash-loops on boot;
- `RuntimeDirectory` **without** the guard ⇒ the Root-1 dual-process defect is
  left un-prevented.

`deploy/deploy-pi.sh::step_assert_single_instance_matched_pair` shells out to
`scripts/deploy_invariants.py check-pair` (the testable assertion) **before**
`sync_tree`, so a broken pair **fails the deploy on the workstation** (exit 10)
and never reaches the Pi. The assertion logic + its loud-failure contract are
pinned by `tests/deploy/test_deploy_invariants.py` (guard-flag-false and
`RuntimeDirectory`-removed fixtures both raise `MatchedPairViolation`) and the
deploy wiring by `tests/deploy/test_deploy_pi.py` (US-389 static assertions).

**Release-then-acquire deploy hygiene.** `step_restart_service` now does an
explicit `systemctl stop` → settle → `systemctl start` (not a bare
`systemctl restart`), pairing with the US-354 deploy-hygiene class: the outgoing
orchestrator fully exits and **releases** the single-instance pidfile before the
incoming process **acquires** it, so the guard cannot observe a still-dying old
pid and refuse the new instance.

**Version stamp.** `step_write_deploy_version` embeds the live
`{guardEnabled, runtimeDirectory}` summary under the `.deploy-version`
`singleInstance` key (via `deploy_invariants.py summarize` →
`version_helpers.py compose-record --single-instance`), so the V0.29.1 stamp
records the matched-pair state rather than being silent on top of V0.28.2.

**06-06 spawn-trigger (Atlas RCA condition C-3) — best-available evidence.**
The two concurrent `eclipse-obd` PIDs at ~2026-06-06 02:25 predate this sprint
by ~3 weeks; the boot-window journal has aged out of the Pi's persistent ring,
so the precise spawn event cannot be re-read (US-389 `conditionalOutcome`:
document best-available + most-likely trigger rather than block). **Most-likely
trigger:** a `systemctl restart` (or `Restart=always` flap, `StartLimitBurst=10`
within 300 s) that re-spawned the orchestrator **before** the prior process had
exited — at the time there was no `RuntimeDirectory` lock and no stop-before-start
ordering, so two `main.py` processes could briefly co-exist, each minting from
the shared counter. A manual `python src/pi/main.py` run overlapping the live
service is the secondary candidate. **Both are now structurally prevented**: the
guard refuses the second instance, the matched-pair invariant guarantees the
`RuntimeDirectory` lock exists, and stop-before-start removes the restart race.
Residual overlap remains backstopped server-side by the Mechanism C
`attribution_anomaly` tripwire (US-390 confirms it stays armed).

### 10.7.1.2 Root 2 guaranteed-close (US-388, Sprint 47 / V0.29.1)

Root 1 (above) explains the *overlap*; Root 2 explains the *stale-open leak*
that re-recurred on drives 28/29 (`drive_start` fired 29×, `drive_end` only
18× — 11 drives never closed). RCA:
`docs/rca/2026-06-28-us387-drivedetector-close-signal-rca.md`. The close state
machine was **tick-driven only**: every close decision is evaluated inside
`processValue`, whose sole caller is `EventRouter._handleReading`. When the
engine stops and the data-acquisition readings stop *before* the
`driveEndDurationSeconds` (60 s) RPM-debounce completes — with no adapter
heartbeat to drive the ECU-silence backstop either — **no close is ever
evaluated**. A later key-on then re-enters the still-open `STOPPING` session
(RPM-above-end → `belowThresholdSince=None` → back to `RUNNING`), never reaching
`_startDrive`, so the second physical drive is **absorbed** into the first's
`drive_id` (fewer ids than drives — the inverse signature of Root 1's overlap).
`_handleConnectionLost` does **not** close a drive, and the US-361
`_isEcuSilenceContinuation` path does not cover this (it requires a silence
`drive_end` to have fired first).

US-388 makes the close **guaranteed** under Atlas's 2026-06-29 shape ruling
(`offices/architect/reports/2026-06-29-us387-rca-acceptance-us388-close-shape-ruling.md`),
four binding constraints:

- **Deadline-anchored close (C-γ), evaluated regardless of the current reading.**
  `DriveDetector._processRpmValue`'s `STOPPING` branch now calls the new
  `_maybeCloseOnDeadline(now)` **first**: if `now - belowThresholdSince ≥
  driveEndDurationSeconds` the drive ends immediately — *even if this tick's RPM
  is back above threshold*. The debounce can complete inside a reading gap; the
  first tick after the gap (a key-on) is then past the deadline, so the stale
  drive closes and the same reading is re-evaluated in the now-`STOPPED` state,
  reaching `_startDrive` and minting a **fresh** `drive_id` (no absorption). A
  short blip that resumes *before* the deadline is still a continuation
  (`RUNNING`), so US-361 is not regressed.
- **Off-tick close (C-α).** New public `DriveDetector.evaluateTimeouts(now=None)`
  runs the same two close paths (`_maybeCloseOnDeadline` + the US-229
  `_checkEcuSilenceDriveEnd`) **off the reading-tick**. The orchestrator main
  loop (`orchestrator/core.py::runLoop`) calls it on every pass (every
  `_loopSleepInterval`, exception-isolated), so the close fires when the deadline
  elapses **even if no further reading ever arrives** — reusing the existing
  periodic loop rather than adding a watchdog thread.
- **Lock discipline (C-β).** `evaluateTimeouts` acquires the **existing**
  `self._lock` before reading/mutating `_currentSession`/`_driveState`, exactly
  like `processValue` — the off-tick writer is safe against an in-flight tick. No
  new lock, no lock-free mutation.
- **Fresh-mint vs re-attach.** A confirmed RPM-debounce/deadline close does **not**
  set the ECU-silence continuation marker, so the next `_startDrive` mints a fresh
  id (the missed-close *is* a real engine-off). Only the tentative link-dropped
  `_checkEcuSilenceDriveEnd` close arms the US-361 re-attach. This is what
  distinguishes "two back-to-back drives" (two ids) from "one drive with a
  mid-leg dropout" (one id).

**Gap-fence corollary.** Because the close now fires, `_closeDriveId` clears the
process-wide `drive_id` latch, so idle/KOEO rows after the close carry `NULL`
`drive_id` — a stale-open can no longer absorb a later key-on (US-388 AC#4).

**Oracle.** `tests/pi/obdii/drive/test_drive2829_close_signal_reproducer.py` (the
US-386 in-process reproducer, `xfail` markers removed) is the code oracle for the
gap-resume half; `tests/pi/obdii/drive/test_off_tick_close.py` pins the off-tick
method; `tests/test_orchestrator_loop_health.py::TestOffTickCloseWiring` pins the
loop wiring. Per Atlas, **true acceptance is the live IRL re-gate** (short /
back-to-back / key-on-after-missed-close / deploy-double-start) — an off-tick
close that rides the heartbeat loop can only be fully validated on the car;
A-9 stays OPEN until that passes.

*Gate-ratification note: §10.7.1 added per the 2026-05-18 design-gate
governance rule (PM Rule 10) + Atlas's Sprint-43 PM Rule 13 validation-block
PASS. Mechanism B's keep-dark production-enable disposition is the Atlas
Rule 10 ruling of 2026-05-29 (CIO-ratified), recorded here + in §20.*

### 10.7.1.3 Root 2 bounded-idle close — a finished drive stops claiming rows (US-625, Sprint 77 / V0.29.34) [Atlas Rule 10]

**Root 2 was never closed.** §10.7.1.2 shipped the *guaranteed close*, and it holds for the paths it
covers. It did not cover a drive whose session ends without any close signal ever firing.

**The evidence, measured on the server 2026-08-29.** Drive 51's real leg ran
`22:09:43 → 22:49:48`, 17,539 rows at a healthy 438 rows/min. Then **24 rows at
`23:42:15-23:42:24` — 52 minutes after the leg ended — still stamped `drive_id=51`.** The detector
never closed 51 and never opened 52.

The damage is not the 24 rows. It is that **drive 51 then reads as 189 rows/min when its real leg
ran 438** — so the row-rate cross-check, which is our best coarse quality signal, flags the drive
correctly while pointing at the wrong diagnosis. **Mis-attribution, not loss.**

**Two mechanisms, both fixed:**

- **`STOPPING` now counts as active.** It previously did not — so a context in `STOPPING` read as
  IDLE, `evaluateTimeouts` early-returned forever, and `stop()` was never reached. The state that
  exists to end a drive was invisible to the thing that ends drives.
- **A bounded idle clock, armed per context.** A `drive_id` with no session left to close still has
  to be closed, and the same activity signal that keeps a drive alive extends its bound. So the
  bound expires on *silence*, not on wall-clock alone.

⚠️ **DIRECTIONAL FENCE — this must never share a ticket with the start-side gap (US-567).** Root 2
is **OVER-attribution**: a dead drive claiming rows that are not its own. US-567 is
**UNDER-attribution**: live rows carrying no `drive_id` at all. **Opposite directions, opposite
fixes — and a fix for one re-opens the other if they are built together.** Spool's ruling of
2026-08-20, upheld.

⚠️ **AND: drives 45/46 are NOT evidence for Root 1.** They were filed as Root 1 regressing
(concurrent capture). **Ruled 2026-08-29: they are the A-23 clock artifact** — the two drives sit in
different boots whose *recorded windows themselves overlap*, and their `source_id` blocks are
disjoint and contiguous, which concurrent writers on one autoincrement cannot produce. **Root 1
stays CLOSED. Do not re-open it on that evidence.**

**What closes Root 2 for good is still owed:** the acceptance test must include the shape that
produced it — a drive whose session ends with no close signal — because *absence of reproduction is
not evidence of repair.* That criticism (Spool, 2026-08-28) is upheld: Root 1 was closed on one
clean pair, and that was too narrow.

### 10.7.2 Derived motion signals + cross-drive comparison (F-106 / F-069, Sprint 53 / V0.29.7)

**Derived motion signals (US-436, F-106).** A third server-side per-drive
compute derives *motion context* from the existing SPEED + timestamp stream — no
new PID, no Pi change (B-104: server is the sole analytics writer).

- **Compute** — `src/server/analytics/derived_signals_compute.py`. The core is a
  **pure** `computeDerivedSignals((timestamp, speed_kmh) series) → DerivedSignals`
  (`src/server/analytics/analytics_types.py`), fully unit-testable off-Pi against
  canned series:
  - `estimated_distance_km` = trapezoidal integral of `speed · dt` (SPEED is
    stored km/h per `obd_parameters.py`, so the integral is km).
  - `peak_acceleration_ms2` / `peak_deceleration_ms2` = most-positive /
    most-negative per-segment finite difference. km/h is converted to m/s
    (`/3.6`) **before** dividing by `dt`, so the peaks carry the physical m/s²
    unit (not km/h-per-second).
  - **Guards** (the AC's divide-by-zero / time-gap requirement): `dt ≤ 0`
    (duplicate / non-monotonic timestamps) → segment skipped, never divided by;
    `dt > GAP_DETECTION_THRESHOLD_SECONDS` (reuses the `drive_summary_compute`
    300 s SSOT — no second magic number) → excluded from distance + accel and
    tallied in `gap_skipped_count`; `<2` samples → `None`.
- **Storage** — `drive_derived_signals` (server MariaDB): one row per drive,
  `summary_id` PK + `FK drive_summary.id ON DELETE CASCADE` (mirrors
  `DriveStatistic`; ORM `DriveDerivedSignal` in `src/server/db/models.py`). Value
  columns (`estimated_distance_km`, `peak_acceleration_ms2`,
  `peak_deceleration_ms2`, `gap_skipped_count`) persist **alongside their unit
  strings** (`speed_unit`/`distance_unit`/`accel_unit`) so a downstream reader
  never guesses units (honest-instrument), plus `computed_at`. Created by
  forward-only migration `v0017_us436_drive_derived_signals.py` (mirrors the
  `v0013` power_log pattern — `INFORMATION_SCHEMA` probe + `CREATE TABLE IF NOT
  EXISTS` + post-condition probe; registered in `ALL_MIGRATIONS`).
- **DB adapter** — `compute_drive_derived_signals(session, driveId)` reads the
  ordered SPEED `realtime_data` rows, calls the pure core, and does an idempotent
  delete + insert keyed on `drive_summary.id`. Wired as the 3rd per-drive compute
  in the recompute CLI + nightly batch (degrades silently on `<2` SPEED rows).

**Cross-drive comparison CLI (US-438, F-069).**
`python -m src.server.cli.compare_drives` is a **read-only** reporting tool over
the already-computed analytics tables (it computes nothing, writes nothing → zero
base-module touch). It renders a side-by-side table (metrics = rows, drives =
columns) so a Spool tuning read scans one metric across N drives at a glance.

- **Data-driven metric registry** abstracts the 3 physical shapes a metric can
  live in: **statistic** — an EAV row in `drive_statistics`
  (`peak_rpm`=`RPM.max_value`, `ltft`=`LONG_FUEL_TRIM_1.avg_value`,
  `stft`=`SHORT_FUEL_TRIM_1.avg_value`); **derived** — a real column in
  `drive_derived_signals` (`peak_accel`, `peak_decel`, `distance`);
  **unavailable** — `knock_retard` honestly renders `--` with a note (the stock
  2G ECU exposes no OBD knock PID; ECMLink knock-retard is USB-only — Rule 2, no
  fabricated parameter name). Adding an ECMLink knock param later = one registry
  line, no consumer change.
- **F-116 honesty** — `driveExclusionReason()` excludes a drive stamped
  `data_quality='foreign_vehicle'` **or** `data_source ∉ {real, NULL}` (NULL =
  pre-US-195 real, matching `basic.py`); an excluded drive is **shown** with an
  EXCLUDED header + footnote (never silently dropped), and `--include-foreign`
  overrides for explicit inspection. Missing data (no computed row / NULL value)
  renders `--`, distinct from a real `0`. Flags: `--drives '11,20,27'|'11-14,27'`,
  `--metrics` (default all), `--include-foreign`, `--list-metrics`, `-v`.

### 10.7.3 Server-Side Analytics Authority (F-104, Sprint 55 / V0.29.9)

**The boundary rule (F-104, generalizes §10.7's B-104 Step-1 principle into a
formal authority contract).** A fact is **server-authoritative** iff the server
can reproduce it from synced raw → the **server is its sole writer** and the Pi
does **not** transmit it (the Pi *may* compute it locally for a live UI, thrown
away). If a fact is **irreproducible** → it is **raw** → the Pi emits it as a
first-class raw event and the server mirrors it (never recomputes). **There is no
"derived state the Pi transmits."** Division of labour: **B-076 = the schema;
F-104 = the authority + the writers.** Binding design authority is Atlas's F-104
ADR (`offices/architect/reports/2026-07-04-f104-server-analytics-authority-design-gate-ruling.md`);
the sprint implements it, does not deviate.

**Canonical `drives` identity SSOT (US-448 — LANDED).** A server-owned `drives`
table is the single drive-identity SSOT:

- `drive_id INTEGER PK AUTOINCREMENT` is the canonical identity, anchored by a
  `UNIQUE (source_device, source_drive_id)` constraint with an
  **upsert-by-natural-key mint** (`src/server/analytics/drive_identity.py::upsert_drive`)
  — a recompute/backfill re-uses the existing id for an already-seen drive and
  **never renumbers** (straight autoincrement would break US-449 idempotency and
  orphan FKs — Atlas Open-Q1). Advisory columns: `source_device VARCHAR`,
  `source_drive_id INTEGER NULL` (the Pi's id, **demoted to advisory**),
  `start_time`, `end_time NULL`, `data_source`, `data_quality`
  (`ck_drives_data_quality` reuses the `drive_summary` enum set).
- **`drive_id` SUBSUMES the de-facto identity `drive_summary.id`** (the existing
  server autoincrement PK that `drive_statistics_compute.py:41,144-186` already
  FKs to) — it is **not** a 5th orthogonal id (that would worsen the D-8
  id-family sprawl this spine exists to fix). The `v0018` forward-only migration
  inserts existing `drive_summary.id` values *in* as `drive_id`
  (`INSERT INTO drives (drive_id,…) SELECT ds.id,…`), so existing
  `drive_statistics.summary_id → drive_summary.id` FKs stay **numerically** valid;
  re-pointing those FK *constraints* onto `drives.drive_id` is the (blocked)
  US-451 family-collapse pass.

**Attribution tripwire re-point (US-448 — LANDED, backstop preserved).**
`src/server/analytics/overlap.py::detect_overlapping_drives` MUST keep **detecting**
overlap on the **raw** `realtime_data.drive_id` — that Pi-stamped id is the very
signal it exists to catch (the Pi minting two ids for one physical leg). It is
**not** regrouped by the server `drive_id` (already deduped → would blind the
Pi-dual-mint backstop). "Re-point" means only its anomaly **output/flag** maps to
the canonical identity (`drive_identity.map_overlap_to_canonical`; an unminted raw
id resolves to `None`, **never silently dropped**). A regression fixture proves a
raw Pi dual-mint pair (drives 23/24) still trips `data_quality='attribution_anomaly'`
against the new schema (extends the §10.7.1 Mechanism-C backstop, US-362/363).

**Pi ids → advisory (US-448 schema — LANDED).** The Pi's `drive_id` is recorded
only as advisory `source_drive_id`; the server never treats it as identity. (The
FK *migration* that collapses `drive_summary`/`drive_annotations` onto
`drives.drive_id` is US-451 — see status below.)

**Sole-writer compute-harness + owned-table registry (US-449 — formalization
IN PROGRESS).** The authority is the **existing** server harness, not a new one:
`src/server/analytics/{drive_summary_compute.py (US-350), drive_statistics_compute.py
(US-351), derived_signals_compute.py (US-436)}` fired by the on-demand
`recompute_drive_analytics` CLI + the `server-analytics-batch.timer` (§10.7
"Trigger seam shift"). Target owned-table registry (server-authoritative,
harness-derived-from-raw): `drive_summary` analytics columns · `drive_statistics`
· `drive_derived_signals` · the `statistics` rollup. It reads **only** synced raw
(`realtime_data`/`connection_log`) — never Pi-transmitted derived state — and is
**idempotent**: re-running over the same raw yields byte-identical owned rows
(proven by `tests/server/analytics/test_harness_idempotency.py`, excluding the
intentionally-advancing `computed_at` observability timestamp).

> **Implementation status (V0.29.9) — honest-instrument.** The boundary rule +
> the identity spine (US-448) + the idempotency proof are **landed**. Formalizing
> the harness as the *sole* writer is **BLOCKED (BL-017)**: `drive_statistics` has
> a **second live writer** — `POST /api/v1/analyze` → `services/analysis.py::runAnalysis`
> → `basic.py::computeDriveStatistics` writes the same table with *different*
> row-selection (drive time-window + `source_device` vs. the harness's
> `realtime_data.drive_id`), last-writer-wins. (This also contradicts the
> `analysis.py:72-75` header claim that US-351 "retired the parallel
> drive_statistics writer" — US-351 retired the *trigger-seam* writer, not the
> `/analyze` path.) Awaiting an Atlas ruling (read-vs-recompute). Downstream and
> blocked on the same ruling: **US-450** (re-key `drive_statistics` from
> `drive_summary.id` → canonical `drives.drive_id`; resolve the empty-table
> deploy gap), **US-451** (collapse the drive-identity id-families onto
> `drives.drive_id`; flag unmappable legacy — drives 1-12, foreign drive 33,
> NULL-`drive_id` — with `data_quality='unmappable_legacy'`, one row per distinct
> legacy key, never dropped/merged), **US-452** (reconcile `statistics` rollup
> vs. `drive_statistics` granular SSOT, no independent dual-write). The
> owned-table **manifest** (US-449 AC1) finalizes once the sole-writer question is
> ruled. Until then the authority-writer layer is documented as the **target**,
> not asserted as realized.

**Schema normalization landed this sprint (F-082 D-items, migration-first).**
These are the schema/data-hygiene half of the sprint, independent of the blocked
authority chain:

- **D-7 (US-453):** `power_log` + `pi_state` sync Pi→server as **raw** (the server
  mirrors, does not recompute — F-104 boundary rule); `pi_state`, a mutable
  singleton, rides the delta path *and* the `modified_at` update-propagation cursor
  so in-place flips re-sync (`v0019`). `startup_log` confirmed already-synced
  (US-416).
- **D-3 (US-454):** O2 sensor name canonicalization — the one divergent stored
  label `O2_BANK1_SENSOR2_V` → `O2_B1S2` (grounded in the `decoders.py` registry
  convention its sibling `O2_B1S1` already follows). Full source→data rename
  (`config.json` poll names + `decoders.py` key + US-229 fixture in lockstep) +
  forward-only `v0020` re-map across all 6 `parameter_name` tables (idempotent
  guard + zero-survivor post-probe).
- **D-4 (US-455):** unit-string canonicalization — the decoder path now emits the
  python-obd **native** strings (`volt`/`kilopascal`/`second`, not `V`/`kPa`/`s`),
  so a physical unit has ONE label across both write paths; the python-obd native
  enum overload (`CL`/`OL`/`ON`/`OFF`) is kept; `v0021` re-maps `realtime_data.unit`;
  a source-scan test pins `unit` as a **typed label, never numeric**.
- **D-5 (US-456):** `static_data` kept **honest-empty** (not dropped) — the VIN is
  un-gettable (the MD326328 ECU is Mode-09-silent) so no valid `vehicle_info(vin)`
  FK can exist; the collector already refuses to fabricate a placeholder VIN, now
  a guarded invariant. No `TD-061` (that path was only for the drop option).

**Stale-reference audit (US-457 AC).** No "Pi computes/transmits derived X" prose
is now false: §10.7's principle ("Pi = telemetry emitter; server = sole authority;
if the server can redo it from raw, the Pi does not transmit it") already states
the F-104 boundary rule, which this section formalizes. §5's Pi-`drive_id` →
`drive_summary.source_id` prose remains **current** — the US-451 FK collapse has
**not** landed — so it is deliberately left unchanged (honest-instrument: do not
document a migration that hasn't shipped).

**Cross-links.** §10.7 (the B-104 Step-1 pipeline this authority formalizes) ·
§10.7.1 Mechanism C (the tripwire this re-points) · §5 (schema / B-076) ·
`[[ssot-design-pattern]]` worked example #4 (server-analytics authority as the
derived-data boundary).

*Gate-ratification note: §10.7.3 is the Rule-10 in-sprint design-gate deliverable
(Atlas A-11 — US-448/US-449 do not close until this section lands). Sprint 55 is
**BENCH-ONLY**: every migration is forward-only + deployed-AND-verified via
`INFORMATION_SCHEMA` at PM-integration (no MariaDB on the Windows dev bench); the
authority-writer chain (US-449-452) awaits the BL-017 ruling. No drive drills.*

---

## 10.8 EDR Sensor Bus Architecture (F-110 bus + F-113/F-114 sensor reader)

### 10.8.1 F-110 SampleBus (Sprint 46 / V0.29.0)

The Event Data Recorder (EDR) program introduces a dedicated in-process
publish/subscribe bus, the **`SampleBus`** (`src/pi/bus/{bus,sample,persistence_subscriber}.py`),
so every data source is read once by a dedicated reader and published to N
policy-applying consumers — the "SSOT for derived data, enforced at a broker"
direction (`specs/ssot-design-pattern.md`). Slice 1 (F-110) shipped the bus
itself plus an OBD path that mirrors the inline logger: a `Sample` envelope
(`topic, source, value, unit, tsUtc, tsCapture, driveId, dataSource, seq`),
per-subscriber QoS (LOSSLESS/durable for the sync + safety lane, LOSSY
drop-oldest for display so a producer never blocks), and a `PersistenceSubscriber`
that drains `raw.obd.*` to `realtime_data`. It **ships dark** behind
`pi.bus.enabled` (default `false`); enabling it must reproduce the byte-identical
`realtime_data` golden master. Contract:
`$FLEET_SHARE/knowledge/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`.

### 10.8.2 EDR sensor reader + raw-sensor persistence (Sprint 50 / V0.29.4)

**EDR sensor reader (F-113/F-114).** A dedicated reader polls two I²C sensors on
bus-1 — ICM-20948 9-DoF IMU (@0x69) and TSL2591 light (@0x29) — and publishes
them on the F-110 `SampleBus` as **additive** LOSSY topics
(`raw.imu.{accel,gyro,mag,temp}`, `raw.light.{lux,raw}`), sharing one `seq` per
IMU burst. The channels never touch the `raw.obd.* → realtime_data` path, so the
F-110 byte-identical golden master is preserved by construction. A sibling
persistence subscriber writes `edr_imu_sample` / `edr_light_sample`, whose DDL is
authored once in the versioned `src/common/edr/sensor_schema.py` contract (A-4
anti-divergence: the future server table derives from the same module).
Persistence is **always-on** (key-on incl. engine-off — true black-box) at a
decimated baseline (`persistHz`, default 25 Hz); rows stamp `drive_id` only when
a drive is RUNNING, else explicit NULL (the A-9/DTC-KOEO latch rule). A
rolling-window purge job (`retentionDays`, default 7) bounds the Pi-local volume.
The reader is **graceful-absent** (probe → silence, never fabricate) and ships
**dark** behind `pi.sensors.{imu,light}.enabled` under `pi.bus.enabled`. Raw
samples are **Pi-local this phase**; server sync, the event vault, and the
event-triggered high-rate (100–200 Hz) capture are F-115. The reader stores
**sensor-frame** values; vehicle-frame rotation + magnetometer hard/soft-iron
calibration are deferred transforms (F-115), pending the recorded mounting
axis-orientation.

**Bus → `states/light` bridge (US-483-a / F-121, Sprint 61 / V0.29.15).** The
carousel display auto-dim consumer (US-483-b) is a **pure consumer of a
reader-owned state file** (Atlas DELTA-2) — it never touches the TSL2591. A
dedicated bridge (`src/pi/sensors/light_state_bridge.py`, `LightStateBridge`)
subscribes to the additive `raw.light.lux` channel (LOSSY — a display needs only
the freshest reading) and mirrors it into `states/light` (`{lux, ts}`, written
atomically via the shared `boot_state_emitter` primitives and served by
`eclipse-states-http` alongside the US-480-a card states). The bridge opens **no
I²C device and no OBD connection** — it is orchestrator-invoked as a bus
subscriber inside `_startEdrSensorPath` (subscribed *before* the readers publish,
stopped in `_shutdownDataLogger`), so it cannot re-introduce the A-17
second-connection race. Honest-instrument carries through the seam: a saturated
read (`lux=None`) is written as JSON `null` (never `inf`/fabricated), and the
freshness `ts` is the **sample's own read-time** (not write-time), so a stalled
feed goes honestly stale and the consumer falls back rather than trusting a
frozen value. Gated behind `pi.bus.enabled` + `pi.sensors.light.enabled`.

**Bus → `states/imu` DERIVED bridge (US-478 / F-113, Sprint 66 / V0.29.20).** The
same seam, one tier further: `src/pi/sensors/imu_state_bridge.py`
(`ImuStateBridge`) subscribes to `raw.imu.{accel,mag}` + the retained
`state.sensor.imu` presence topic (LOSSY) and writes the **display-derived view**
into `states/imu`. Two artifacts, deliberately separate (Atlas A-4): **raw**
accel/gyro/mag stay on the bus and in the versioned `edr_imu_sample` store; this
file is the *derived* view and holds no raw axes at all. **The reader computes,
the display consumes** (Atlas DELTA-2) — the card never fuses.

*Contract (Atlas Q-A, 2026-07-30; `pitchDeg` added by US-521).* `{available, ts,
gLat, gLon, gMag, headingDeg, pitchDeg, gradePct, altitude, reasons}`:

| Field | Meaning | Notes |
|---|---|---|
| `gLat` / `gLon` / `gMag` | horizontal acceleration, **units = g** (`g_n` = 9.80665 m/s²) | `gLon` + = accelerating, − = braking; `gLat` + = **RIGHT** (automotive convention); `gMag` = hypot |
| `headingDeg` | magnetic bearing of the vehicle nose, 0–359 | tilt-compensated; **magnetic, not true** (no declination in the contract) |
| `pitchDeg` | **gyro-fused, ZUPT-corrected** chassis pitch (US-521) | + = nose up; the single published attitude fact — US-519's altitude integrand and `gradePct` both read *this*, never a second derivation |
| `gradePct` | `tan(pitchDeg) × 100` | + = climbing; `null` past `MAX_GRADE_PITCH_DEG` (85°), where `tan` runs away |
| `altitude` | **always typed `null`** + `reasons.altitude = "no_source"` | the ICM-20948 has no barometer; a zeroed altitude renders as sea level — a confident lie. US-519 derives it from `pitchDeg`; a future GPS/baro supersedes that, not this bridge |
| `available` / `ts` | freshness | absent/stale → the US-497 idle-card fallback |
| `reasons` | per-field absence vocabulary | `sensor_absent`, `no_mag_reading`, `tilt_unresolved`, `pitch_out_of_range`, `pitch_unseeded`, `no_source` |

*Honest-availability is PER FIELD.* A dead magnetometer grays `headingDeg` alone
while the g fields stay live; an unwired sensor writes an **explicit**
`available: false` state (a state *change* bypasses the write-cadence window, so
an unplug can never leave the last live g reading frozen on the card looking
current); and a stale mag reading grays the heading rather than carrying an old
bearing forward — a frozen compass needle is worse than an absent one.

*Why a gravity low-pass (`pi.sensors.imu.gravityTauSec`, default 5 s).* The
accelerometer measures gravity and vehicle acceleration summed into one vector.
Publishing the raw horizontal components would pin a permanent phantom **0.17 g**
on the g-meter for a board bolted in at a 10° tilt. The slow estimate tracks
mount tilt and road grade (which change over tens of seconds); the fast residual
is the acceleration the g-meter exists to show. The **same** estimate defines the
level frame for `gLat`/`gLon` **and** the tilt compensation for `headingDeg` —
one gravity fact, two consumers, no chance for two derivations to disagree. The
default τ is a **Rex-derived filter constant flagged for Atlas/Spool confirmation
against a real drive**, not a tuning value.

##### Gyro-fused pitch + ZUPT (US-521 / F-125, Sprint 69 / V0.29.24)

**Why the low-pass above was not enough for pitch.** An accelerometer cannot
distinguish grade from acceleration — they are literally the same measurement
(Spool, 2026-08-01). Specific force is `a_vehicle − g_vector`, so a 0.3 g pull on
*flat* ground adds 0.3 g to the forward axis and any accel-derived tilt reads
`atan(0.3)` = **16.7° of climb**. The 5 s gravity τ rejects a 1 s event but *not*
a 10 s on-ramp (2 τ), so `gradePct` was structurally wrong under sustained
acceleration — and it is the integrand US-519's interim altitude would have
inherited, where a 0.5° sustained bias is 70 m of fake climb over a 10-minute
drive against ±10–20 m of real Chicagoland relief.

**`src/pi/sensors/pitch_fusion.py` (`PitchFusion`)** replaces that path. Pure and
I/O-free — no bus, no device, no clock — so it is deterministically testable and
US-519 reuses it unchanged. Three mechanisms, all Spool's:

1. **Gyro integration** carries the short term (`raw.imu.gyro`, rad/s, already
   published by the reader under the same burst `seq`; the bridge simply had
   never subscribed). Sign is *derived*, not guessed: the frame is right-handed
   `forward × left = up`, so `ω × forward = −ω_left · up` and a nose-up rate is a
   **negative** left-axis rate. It must agree with the accel convention or the
   two halves of the filter fight each other.
2. **The accel corrects the gyro only near 1 g** (`accelTrustBand`, default
   0.02 = 2%). This is what rejects the phantom: under 0.3 g the specific force is
   1.044 g, a 4.4% excess, well outside the band. The band cannot be much tighter
   or road vibration gates the accel off permanently, leaving pure gyro drift.
3. **ZUPT** at every confirmed stop — OBD speed 0 across `[EXACT: 3] s` (Spool,
   **load-bearing**). At zero velocity the accel reads *pure gravity*, so the
   measured tilt is the true chassis pitch: the one uncontaminated fix the
   estimator gets, applied as a **snap, not a blend**. One stop cannot separate
   mount tilt from the slope you parked on, but the rolling mean over stops
   converges on the **bias** — valid because this terrain is flat, so real road
   slopes average ~0. City stoplights are the free calibration signal. Published
   pitch is `fused − bias`.

**`raw.obd.SPEED` is the ZUPT gate and the bridge stays a pure bus consumer.**
The capture loop already publishes it onto the *same* `SampleBus`
(`realtime._publishReading`), so this is one more subscription, not a second
acquisition path — the bridge still opens no OBD connection and no I²C device.
The value is used as a boolean "is it zero", **never as a magnitude**, so the
reading's unit is irrelevant here by construction.

*Honest-instrument, per branch.* The pitch starts `null` and is never a
fabricated 0.0 (`reasons.pitchDeg = "pitch_unseeded"`, distinct from
`tilt_unresolved` — the sensor is fine, the attitude is simply not known yet); it
seeds **only** from an uncontaminated reading, because seeding mid-pull bakes the
phantom in as the origin the gyro then integrates from; no bias is applied until
`zuptMinStops` stops have been observed, since a bias claimed from one stop is a
calibration nobody measured; the bias window is **rolling**, so a physical
remount ages out rather than freezing on an old constant; and **an absent or
stale OBD speed is never read as "stopped"**. That last one is the dangerous
case, not a failed read: honouring a stale zero after a mid-stop link drop would
keep hard-correcting the attitude to whatever the accelerometer says for the rest
of the drive — snapping pitch to the 16.7° phantom on every on-ramp, with more
confidence than the drift it was fixing. A stop therefore requires zero speed
*observed across* the whole gate **and** still fresh (`zuptSpeedMaxAgeSec`,
default 2 s, deliberately **below** the 3 s gate); elapsed time after one zero
reading is evidence only that we stopped being told.

*Config (`pi.sensors.imu.*`, all positive-checked in `_validateImuStateBridge`).*
`pitchTauSec` (5.0), `accelTrustBand` (0.02), `zuptMinStopSec` (**3.0 — Spool
`[EXACT]`, flag him before any drift**), `zuptSpeedMaxAgeSec` (2.0),
`zuptMinStops` (5), `zuptWindowStops` (20). All but `zuptMinStopSec` are
**Rex-derived and routed to Spool for σ_pitch sizing** (US-521 AC4) before
US-519/US-520 build the altitude display on top.

*Config (all under `pi.sensors.imu.*`, validated in `_validateImuStateBridge`).*
`stateHz` (default 4) is the state-file write cadence, grounded to the
**consumer** — `carousel.js POLL_MS = 250` — not the sensor's 50 Hz burst;
writing tmpfs faster than the only reader polls is churn with no observable
effect. `mount.{forward,left,up}` (default `+x`/`+y`/`+z`) places the board in the
**vehicle** frame, so a physical remount is a config edit rather than a code
edit; a duplicated or malformed axis is rejected at config-validation time (fail
fast) instead of raising once per sample inside the bus drain, where it would be
logged and swallowed. Gated behind `pi.bus.enabled` + `pi.sensors.imu.enabled`
(flipped on in Sprint 66 — connect-when-wired, the genuine Adafruit ICM-20948
#4554 confirmed @0x69 via `WHO_AM_I = 0xEA`).

**Display auto-dim consumer + config-injection seam (US-483-b / F-121, Sprint 61
/ V0.29.15).** The carousel drives the panel brightness (a **software dim** — the
Chromium kiosk can't reach the panel backlight) from the `states/light` feed via
pure, node-tested logic in `carousel.js`: `brightnessLevel(lightData, cfg, nowMs,
alarmActive)` = `clamp(minLevel, brightnessCurve(lux), 1.0)` when the feed is
fresh, else a fixed `defaultLevel` (honest fallback — an absent/stale/`null`
reading never fabricates an "auto" behavior), then raised to at least
**FULL brightness** while a **real active STOP** alert is present
(`brightnessAlarmActive` — the load-bearing safety guard: the PULL-OVER alarm is
never dimmed, regardless of lux). US-484-b made the alarm go to FULL, which is
stronger than any floor, and **US-595 therefore RETIRED `alarmFloorLevel`
entirely** — a floor beneath a value that is already the maximum is unreachable
config. Applied as a CSS var
(`--display-brightness`) `filter: brightness()` on the `#screen` frame (the black
letterbox bars stay black; `#stage`'s own transform remains the containing block
for its descendants, so US-482 scaling is untouched). The curve values are
**GROUNDED CONFIG PARAMETERS** under `pi.display.autoDim.*` (`luxMin` 3.0 /
`luxFull` **300.0**; `minLevel` **0.75** / `defaultLevel` **1.0**; `luxStaleSec`
10; `curve` `logarithmic`)

> ⚠️ **These four values all moved on 2026-08-29/30 and this paragraph described
> the old ones.** Recorded because the drift was mine: `luxFull` was documented
> as a *"standard illuminance anchor"* of 1000 and had never been measured on
> this car — **measured overcast daylight through the windscreen is ~209 lux**,
> ~4.8x below it, so the panel sat at its floor through real daylight
> (ARCH-008). `minLevel` 0.15 → 0.5 → **0.75** and `defaultLevel` 0.70 → **1.0**
> are the CIO's, from a dark-garage check; `defaultLevel` is deliberately NOT
> matched to `minLevel` because the same fallback serves absent, stale **and
> saturated**, and saturated is bright sun where 0.75 is unreadable.
> `alarmFloorLevel` is retired (US-595).
>
> ⚠️ **`minLevel` at 0.75 makes the floor dominate until ~234 lux at
> `luxFull` 1000, ~42 lux at 300.** Auto-dim therefore has a deliberately narrow
> working range. That is a CHOICE, not a defect — do not "fix" it back.

**A NEGATIVE lux is not a dark reading (ARCH-010).** The TSL2591 lux equation
subtracts a multiple of the infrared channel, so an IR-dominated sample — low sun
through a windscreen — computes negative; 452 such samples were recorded on
2026-08-28, worst −721.4 at 83% IR. `freshLux` rejected non-finite values but not
negatives, and a negative **is** finite, so it passed every type check and hit
`lux <= luxMin -> 0`: **the brighter the sun, the dimmer the panel.** It is now
published as `null` at the producer and rejected again at the consumer.
⚠️ **Published as `null`, never CLAMPED to 0** — 0 lux reads as darkness and would
still dim. `null` routes to `defaultLevel`, i.e. full. The honest answer and the
correct behaviour are the same answer here, **NOT** `pi.display.brightness` (the distinct live 0–100
hardware-backlight scalar). Tuning is a **config change, not code** (CIO
2026-07-22): `eclipse-states-http` injects the `pi.display.autoDim` object into
the served `dashboard.html` at serve time — the same same-origin seam as the
`__SPLASH_TOKEN__` SSOT — via the quoted `"__DISPLAY_AUTODIM__"` placeholder
(`states_http_server.loadDisplayAutoDimConfig` reads config.json fail-safe; no
config → `null` → the carousel's built-in grounded defaults, which mirror
config.json). The consumer reads **only** `states/light` — it opens no OBD/second
connection.

**Config (connect-when-wired).** Master `pi.bus.enabled` → `pi.sensors.imu.enabled`
/ `pi.sensors.light.enabled` (each requires the bus gate);
`pi.sensors.imu.sampleHz` (`50`, bus publish rate), `pi.sensors.imu.persistHz`
(`25`, decimated persist), `pi.sensors.light.sampleHz` (`1`),
`pi.sensors.retentionDays` (`7`, rolling-window purge — confirm vs Pi free space
at deploy). Built US-408 (schema contract + Pi tables) / US-409 (IMU + light
readers) / US-410 (persistence subscriber + retention) / US-411 (bench harness +
golden-master regression + connect-when-wired drill). **US-483-a (V0.29.15)
flipped `pi.bus.enabled` + `pi.sensors.light.enabled` ON** — the TSL2591 is wired
+ I²C-addressable @0x29 (verified on the Pi 2026-07-22), so the light feed is now
live and bridged to `states/light`; the IMU stays dark (clone boards absent — the
graceful-absent reader stays silent, isolating the live light feed).

*Gate-ratification note: §10.8 added per the 2026-05-18 design-gate governance
rule (PM Rule 10 / C-4 DoD, in-sprint) from Atlas's 2026-06-30 EDR ADR
(`$FLEET_SHARE/knowledge/superpowers/specs/2026-06-30-edr-sensor-reader-schema-bus-adr.md` §5).
BENCH-validated (US-411 golden-master + absent-path); live IRL acceptance —
`i2cdetect` 0x29/0x69 + connect-when-wired — pending the first V0.29.4 Pi
deploy.*

---

## 11. Deployment Architecture

### Environments

| Environment | Purpose | Configuration |
|-------------|---------|---------------|
| Development | Local development | `.env.local` |
| Test | Automated testing | `.env.test` |
| Production | Raspberry Pi | `.env.production` |

### Auto-Start (systemd) -- per-tier units

Both tiers run under systemd with matching restart/security/logging shapes.
Living source-of-truth lives in `deploy/` (the snippet below is illustrative;
the canonical files are what ships).

| Tier | Unit | Source of Truth | Story |
|------|------|-----------------|-------|
| Pi (chi-eclipse-01) | `eclipse-obd.service` | `deploy/eclipse-obd.service` | US-210 (Sprint 16) |
| Server (chi-srv-01) | `obd-server.service` | `deploy/obd-server.service` | US-231 (Sprint 18) |

Shared invariants across both units:

- **`Restart=always`** + **`RestartSec=5`** -- backstop for unexpected process death.
- **`StartLimitIntervalSec=300` / `StartLimitBurst=10`** in the Unit section -- flap protection (modern systemd warns if these live in Service).
- **`User=mcornelison`** -- never root.
- **`Type=simple`** -- the venv-launched Python is the main process.
- **No inlined secrets** -- secrets live in `.env` referenced via `EnvironmentFile=`.
- **`journalctl -u <unit>` is the single source of truth** for runtime logs (no `StandardOutput=append:...` directives).

Tier-specific differences:

| Concern | Pi (eclipse-obd) | Server (obd-server) |
|---------|------------------|---------------------|
| `After=` deps | `network.target bluetooth.target` | `network.target mariadb.service` |
| Working directory | `/home/mcornelison/Projects/Eclipse-01` | `/home/mcornelison/obd2-server` |
| Venv | `/home/mcornelison/obd2-venv` | `/home/mcornelison/obd2-server-venv` |
| ExecStart | `python src/pi/main.py` | `uvicorn src.server.main:app --host 0.0.0.0 --port 8000` |
| Display env | DISPLAY/XAUTHORITY/SDL_VIDEODRIVER (US-192) | n/a (headless) |

Pre-US-231 the server ran as an unmanaged `nohup uvicorn` child launched by
`deploy-server.sh`. Spool's 2026-04-23 post-deploy audit caught it: any
chi-srv-01 reboot or process crash left the server down until manually
restarted, and Pi sync failed silently in the gap. US-231 mirrors the US-210
Pi-side fix: a systemd unit + a sync-if-changed install step in
`deploy-server.sh` (`step_install_server_unit`, mirror of
`step_install_eclipse_obd_unit`). Cutover is one-time -- the deploy script
kills any orphan pre-systemd `nohup uvicorn` (the `[u]vicorn` bracket trick
prevents the SSH shell from self-matching), then `sudo systemctl restart
obd-server` takes over. Subsequent deploys are no-op-or-restart depending
on whether the unit-file content changed.

```ini
# deploy/eclipse-obd.service (Pi tier, US-210; abridged)
[Unit]
Description=Eclipse OBD-II Performance Monitor
After=network.target bluetooth.target
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
User=mcornelison
WorkingDirectory=/home/mcornelison/Projects/Eclipse-01
Environment=PATH=/home/mcornelison/obd2-venv/bin:/usr/bin:/bin
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/mcornelison/.Xauthority
Environment=SDL_VIDEODRIVER=x11
ExecStart=/home/mcornelison/obd2-venv/bin/python src/pi/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```ini
# deploy/obd-server.service (Server tier, US-231; abridged)
[Unit]
Description=OBD2v2 Analysis Server (FastAPI/uvicorn)
After=network.target mariadb.service
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
User=mcornelison
WorkingDirectory=/home/mcornelison/obd2-server
EnvironmentFile=/home/mcornelison/obd2-server/.env
Environment=PYTHONPATH=/home/mcornelison/obd2-server
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/mcornelison/obd2-server-venv/bin/uvicorn src.server.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### F-103 Splash Subsystem -- state server + emitters + `/run/eclipse-obd/states/` lifecycle (US-393, Sprint 48 / V0.29.2)

The boot/shutdown splash is a **pure SSOT consumer** (`specs/ssot-design-pattern.md`):
a chromium kiosk that *renders* state but never *decides* system condition. Three
cooperating processes communicate via a tmpfs directory.

| Unit | Source of Truth | Role |
|------|-----------------|------|
| `eclipse-boot-state.service` | `deploy/eclipse-boot-state.service` | [A-1] Boot-state emitter (`python -m pi.splash.boot_state_emitter`). Polls `systemctl is-active` for the **CORE-readiness** set + checks the dashboard assets are installed, writes `boot-state` JSON @ 500ms. The authority for `healthy`/`degraded`. The eclipse-obd tier is sampled + reported but **does not gate** (US-494, below). |
| `eclipse-states-http.service` | `deploy/eclipse-states-http.service` | [A-4] Localhost state server (`python -m pi.splash.states_http_server`). Binds **127.0.0.1:9899 only**, serves the read-only `states/*` JSON, **token-gated** (token SSOT), path-traversal-guarded, `Cache-Control: no-store`. The only IPC chromium can `fetch()`. |
| `splash-boot.service.{wayland,x11}` | `src/pi/ui/splash/` | [A-8] Chromium kiosk. Loads `http://127.0.0.1:9899/` (same-origin, token injected) and runs the `boot-state-poll.js` state machine. |

**Code:** `src/pi/splash/` — `boot_state_emitter.py` (honest-instrument verdict
logic: CORE-readiness gate, dashboard-asset gate, informational 3-tier
eclipse-obd health with retry-once, hard-cap degrade), `states_http_server.py`
(the localhost server), `token.py` (the one-source auth token).

**Readiness contract = "Pi core / UI is up", NOT "a vehicle is connected"
(US-494, Sprint 66 / V0.29.20).** The handoff gate (`CORE_SERVICES_DEFAULT`) is
`eclipse-states-http` + `eclipse-powerwatch` + `boot-progress-finalize`, plus the
dashboard assets being installed (`/opt/dashboard/dashboard.html`). `eclipse-obd`
is **deliberately not a gate member**: the Pi spends most of its life on a bench
with no car, and a vehicle-shaped readiness gate makes the dashboard unreachable
there. The tier is still assessed and published in the payload's own `obdTier`
field for post-boot/vehicle-slice consumers, and `services` now carries **only**
`systemctl is-active` strings (one vocabulary per field) rather than overloading
the `eclipse-obd` entry with a tier verdict.

*Why this was a bug, not a preference:* before US-494 the tier was gating **and**
the systemd entry point never injected an `obdProbeFn`, so the probe defaulted to
`lambda: OBD_STARTING` — a claim that checks are *in progress*, permanently. The
tier never went terminal → `progress` capped at 2/3 → `healthy` never became true
→ `boot-state-poll.js` never called `window.close()` → `OnSuccess=eclipse-dashboard.service`
never fired. After the 12 s cap the splash pinned at *"eclipse-obd: not ready
(starting)"* until reboot. An absent probe now reports `OBD_NOT_PROBED`
(`"not-probed"`) — a reading **not taken** is never dressed up as a state.
Missing dashboard assets likewise **hold the splash with a named reason** rather
than handing off to a blank screen (the A-16 lesson, made loud).

*Guarded end-to-end since US-499:* `tests/ui/test_render_regression.py` runs the
**production wiring** (`buildEmitter` — what the systemd unit constructs) against
a faked `systemctl`, feeds the emitted payload sequence to the **shipped**
`boot-state-poll.js`, and asserts `window.close()` is actually called. Its
partner test loads the **pre-US-494 emitter from git** and asserts the splash
pins instead — the defect above is now reproducible on demand. See the
render-regression backstop under F-092.

**Launcher-URL ↔ served-route contract (US-525, Sprint 70 / V0.29.25 — I-042).**
The server serves exactly three buckets: `/` (and `index.html`) → the *first*
assets dir's index with placeholders injected; any name matching a file in an
assets dir → that asset **by extension** (`*.html` also gets injection); and
**everything else → a token-gated `states/` lookup**. So a *bare* route such as
`/boot`, `/dashboard` or `/shutdown` is not a page at all — it falls through to
the state bucket and answers **401 by design**. I-042 read those 401s as "a new
gate on bare routes" and suspected US-501's `_injectHtml`; both were wrong. No
launcher ever requests them: `splash-boot` loads `/`, `splash-grace` loads
`/shutdown.html`, `dashboard` loads `/dashboard.html` — all 200 with the token
injected. `_injectHtml` is **exonerated** (the index path serves 200).

*Guarded by `tests/pi/splash/test_splash_launcher_route_contract.py`:* it parses
the URL out of every real kiosk unit (both session variants) and drives it against
the real server over the real shipped kits, so the units and the router cannot
drift apart independently — the two-correct-halves class. The same file asserts
the bare routes **stay 401**: opening them re-opens TD-067 and is an Atlas BLOCK.

**Boot-splash minimum-VISIBLE floor (US-525).** `MIN_PLAY_MS` (2500 ms, spec §5)
is now anchored to the brand `<object>`'s `load` event, not to script parse. The
mark is a separate async SVG document, so on a cold chromium the poll loop ticks
while the stage is still blank — the old anchor let the splash satisfy its own
2.5 s floor having shown the brand for a fraction of it, then fade (I-042 cause
b). Measured on the Pi (boot `dc7a3848`, 2026-08-02): `splash-boot` lived
**9.806 s** but chromium's startup consumed the first ~5.4 s. The floor is
**bounded by `HARD_CAP_MS`** and falls back to the parse anchor when the brand
never loads — a cosmetic asset fault must never withhold the dashboard hand-off
(that is the US-494 pin-until-reboot failure, re-entered through its own fix).

**Shutdown splash fires only on a POWER-LOSS shutdown (US-525 finding, not a
defect).** The sole production writer of `shutdown-state` is the powerwatch
`ShutdownSequencer` grace path (`pi.power.power_watch.__main__` →
`makeShutdownPhaseEmitter`). A manual `sudo reboot`/`poweroff` stops
`eclipse-powerwatch.service` by SIGTERM without entering a grace sequence, so
`shutdown-state` is never written, `splash-grace.path` never triggers, and **no
reverse splash appears — correctly.** I-042's "shutdown splash did not appear"
after a deploy+reboot is therefore expected behaviour, not the regression. Any
future drill of the reverse splash must be a real AC-loss/grace event.

**Token SSOT (US-393 DoD):** exactly one file — `/run/eclipse-obd/states/.http-token`
(0600) — is the authority. `token.loadOrCreateToken` generates it once and never
regenerates. The server loads it to validate the `X-Splash-Token` /
`Authorization: Bearer` header on the state-JSON endpoints; the kiosk receives it
**injected into the index page the server serves same-origin**, so the token never
lands in an on-disk asset.

**`/run/eclipse-obd/states/` ownership + lifecycle (Atlas C-5 — the load-bearing
multi-owner runtime-dir contract).** `/run` is tmpfs (wiped every reboot). The dir
has three would-be owners that must be reconciled so they do not fight:

1. **`eclipse-obd.service`** declares `RuntimeDirectory=eclipse-obd` → systemd
   creates `/run/eclipse-obd` on *its* start and **removes it on its stop**, and
   it never creates the `states/` subdir. Owning the dir *exclusively* would make
   `states/` (and `shutdown-state`) vanish the moment eclipse-obd stops — exactly
   when the US-394 shutdown splash needs it.
2. **The F-103 units share `RuntimeDirectory=eclipse-obd`** (same name → systemd
   **ref-counts** it). `eclipse-states-http.service` runs continuously, so the
   ref-count never hits zero while it is up → `/run/eclipse-obd` **outlives**
   eclipse-obd.service across its stop/restart. `RuntimeDirectoryPreserve=yes`
   reinforces this.
3. **`/etc/tmpfiles.d/eclipse-obd-states.conf`** (`deploy/eclipse-obd-states.conf`)
   creates `/run/eclipse-obd/states/` (owned `mcornelison`) **at every boot,
   independent of any unit's start order** — the cold-reboot invariant the bench
   drill proves (splash renders without eclipse-obd having provisioned the dir).

The emitter + server also `ensureStatesDir()` the `states/` subdir in-process
(`RuntimeDirectory` makes only the parent `/run/eclipse-obd`, not `states/`).
Together: tmpfiles guarantees boot-time existence; the shared ref-counted
`RuntimeDirectory` guarantees mid-session survival across eclipse-obd's lifecycle.
The old deploy-time `install -d` alone is **insufficient** (tmpfs wipes it on the
next reboot).

**Deploy provisioning (US-395).** `deploy-pi.sh` folds the whole F-103 backend into
every Pi deploy, in dependency order, all `sync-if-changed` (mirroring the sibling
unit installers — `cmp -s`, `daemon-reload` only on change, `enable --now`
idempotent):

1. `step_install_states_tmpfiles` installs `deploy/eclipse-obd-states.conf` →
   `/etc/tmpfiles.d/` **and runs `systemd-tmpfiles --create`** so
   `/run/eclipse-obd/states/` exists *this* deploy, not only after the next reboot
   (the boot-durable provisioning mechanism AC#4 requires — **not** `install -d`
   alone).
2. `step_install_splash_assets` installs the served kit from
   `src/pi/ui/splash/` into `/opt/splash` and writes
   `/opt/splash/version.txt` (the bare SemVer string the kiosk version chip
   fetches; derived from `deploy/RELEASE_VERSION`, `V?.?.?` fallback). The
   manifest covers **both** surfaces — boot (`index.html`, `styles.css`,
   `boot-state-poll.js`, `splash.svg`) *and* closeout (`shutdown.html`,
   `shutdown-state-poll.js`, `splash-shutdown.svg`) — force-refreshed and
   byte-verified (US-498; see the `/opt` asset-ownership contract below).
   **A-9:** a missing splash kit **WARNs and the deploy continues** — it
   never blocks.
3. `step_install_state_server_units` installs + enables `eclipse-boot-state.service`
   + `eclipse-states-http.service`; both are long-running `Type=simple`, so they
   also `systemctl restart` on every deploy (the US-354 dead-code-in-memory class).

The chromium kiosk **unit** (`splash-boot.service.{wayland,x11}`) + the shutdown
render assets are the **render side (US-396)** — the same producer/render seam as
US-394.

> **Cross-ref:** the shutdown-state half of this contract (the ShutdownSequencer
> phase-emit hook + the "shutdown-state survives eclipse-obd stop" guarantee) is
> documented in **§10.6.1** (landed by US-394, same sprint).

**Closeout (shutdown) surface — the reversal contract (US-498).** The closeout
splash is the boot splash **played backwards**: one kit, one set of keyframes,
`splash-shutdown.svg` differing from `splash.svg` only by a trailing override
block. Two things have to be reversed there, and shipping only the first is a
black screen:

1. **direction** — `animation-direction: reverse` on every animated class; and
2. **order** — `animation-delay` recomputed as `T − (bootDelay + bootDuration)`,
   `T` = the boot animation's total (6.5 s). The *last* thing to happen on boot
   must be the *first* thing to happen on shutdown.

Skipping (2) is not a cosmetic ordering nit. The boot timeline ends with a
fadeout **delayed 6 s**, and `animation-fill-mode: both` holds the reversed
animation's *first relevant* keyframe throughout that delay — which for
`direction: reverse` is `to`, i.e. `opacity: 0`. The mark was therefore
invisible for 6 s of a 7 s grace window (`pi.powerWatch.smoothingSec`): the
operator watched a black screen for the whole shutdown while the code, the unit,
the state file and the poll script were all working correctly. The animation is
sized to **finish inside the grace window** so the closeout completes rather
than being cut off mid-motion by the power drop; after it completes the HTML
overlays (wordmark + version chip) remain on screen for the flush/poweroff tail,
so the surface is quiet, never blank.

`tests/ui/test_shutdown_splash_render.py` resolves the shipped CSS on a clock
(cascade, comma-list shorthands, fill-mode/direction/delay) and samples the
mark's opacity every 250 ms across the real grace window, so the guard is a
measurement of what is on screen at second *n*, not a grep for a magic string;
it re-derives the delays from `splash.svg`, so re-timing the boot animation
re-aims the closeout instead of silently leaving it out of step.
`tests/pi/splash/test_shutdown_splash_wiring.py` pins the chain end to end —
a real `ShutdownSequencer` grace transition writes the real state file, the real
`eclipse-states-http` serves the real kit, and the page is fetched at the URL
taken **out of the shipped `splash-grace.service` unit** (the US-494 lesson: the
defect lives in the seam nobody asserted, not in the parts).

**Kiosk-unit install contract (`step_install_ui_kiosk_units`, Bug-1/2/4 — finding
`offices/architect/findings/2026-07-01-pi-display-blank-deploy-contract-gaps.md`,
hardened US-428).** The asset + state-server steps above install what
`eclipse-states-http` *serves*; a separate deploy step installs the chromium kiosk
**units** that actually draw it (without it the backend serves 127.0.0.1:9899 with
no browser and the 3.5″ panel stays blank, pygame being sunset). It runs the kits'
own session-aware `install.sh` (`src/pi/ui/{splash-pi,dashboard-pi}/`) after the
state server is up. Three install-contract gaps are closed:

- **Bug-1 (units never installed):** deploy invokes both kit installers every deploy
  (idempotent), so a fresh deploy is sufficient to render — no manual `install.sh`.
- **Bug-2 (chromium binary name):** the unit templates parameterize the browser as
  `ExecStart=__CHROMIUM_BIN__`; each installer's **V-3** check detects the real path
  (`chromium-browser` OR `chromium` — Raspberry Pi OS Trixie ships `/usr/bin/chromium`)
  and substitutes it into `ExecStart`, exactly like **V-1** substitutes `User=`. This
  is **OS-version-proof with no `/usr/bin/chromium-browser` symlink shim**; an absent
  chromium makes the installer **fail loudly** (its non-zero exit is wrapped
  WARN-not-BLOCK by the deploy step, A-9), never a silent 203/EXEC unit.
- **Bug-4 (screen blanking):** deploy installs the persistent xorg drop-in
  `deploy/eclipse-kiosk-no-blank.conf` → `/etc/X11/xorg.conf.d/` (BlankTime/DPMS all
  `0`) so the status panel never sleeps to "no input", and applies it live via `xset`.

**Session detection (D-3 guard).** Over SSH the calling session reads as `tty`, so the
step detects the **ACTIVE graphical `seat0` session** type (x11|wayland) on the Pi and
passes it via `{SPLASH,DASHBOARD}_FORCE_SESSION`; if it genuinely can't be determined
it **WARN + skips** (never guesses — a wrong X11-vs-Wayland guess is the D-3
black-screen bug). **A-9 posture throughout:** an absent kit/installer WARNs and the
deploy continues; the step never BLOCKs. The units are installed + **enabled** (splash)
so the splash renders at the **next boot** (`WantedBy=graphical.target`) — the step does
not thrash the live screen mid-deploy. Coverage: `tests/deploy/test_kiosk_install.py`
(V-3 substitution + fail-loud + step assertions) and the `deploy-pi.sh` `--dry-run`
smoke test.

### F-092 Carousel Dashboard Subsystem -- shell + splash hand-off + full-runtime state server (US-399, Sprint 49 / V0.29.3) [Atlas A-1/A-2/A-5]

The post-boot touch dashboard reuses the F-103 splash seam wholesale: it is a
**pure SSOT consumer** chromium kiosk that *renders* state files and **never
polls hardware**. The carousel shell (US-399) is the frame; the System Status /
Battery Health card bodies + emitters are US-400 / US-401; the DTC card (Card 5)
+ viewer is US-404..407.

| Piece | Source | Role |
|------|--------|------|
| Dashboard kit | `src/pi/ui/dashboard/` | `dashboard.html` (top bar + card slots + page dots -- see the card model below), `dashboard.css` (≥40px tap targets), `carousel.js` (swipe-nav + dots + honest-instrument availability poll). Served at `/dashboard.html`. |
| `eclipse-dashboard.service.{wayland,x11}` | `src/pi/ui/dashboard/` | [A-5] Chromium **touch** kiosk (`--touch-events=enabled`). Loads `http://127.0.0.1:9899/dashboard.html` same-origin (token injected). **No `[Install]`** -- started by the splash hand-off, not enabled. |

**A-1 splash → dashboard hand-off.** `splash-boot.service.{wayland,x11}` carries
`OnSuccess=eclipse-dashboard.service`. When the boot splash reaches
`HEALTHY_YIELD`, `boot-state-poll.js` calls `window.close()`; the `Type=simple`
splash unit exits 0; systemd starts the dashboard. A **DEGRADED** boot keeps the
splash up (no `window.close`), so the dashboard never starts on a sick boot
(honest-instrument: the operator sees the amber-ring splash, not a dashboard
pretending all is well). No watchdog/timer, no `pkill` -- the same JS-driven exit
discipline as the splash (D-3). *(US-523 adds a watchdog that **restarts** an
already-running kiosk; it never **starts** one, so this hand-off remains the sole
path from splash to dashboard -- see the wedge-recovery subsection below.)*

**Kiosk freeze class + wedge recovery (F-124: US-522 primary, US-523
defense-in-depth).** The bench UI froze with chromium **alive**: its GPU
command-buffer context died and the client hot-looped on the fatal
`AllocateRingBuffer()` failure (Atlas measured 6,063,554 errors in one boot,
~500/sec, renderer/GPU/main pegged 39/31/24% CPU, **no crash**) -- the Pi 5 v3d
GPU on a 64 MiB CMA pool driving the animated carousel with GPU rasterization on.
Because nothing crashed, the kiosk unit's `Restart=on-failure` never fired; the
panel simply stopped updating while X stayed live. RCA:
`offices/architect/findings/2026-08-02-pi-ui-freeze-chromium-gpu-command-buffer-hotloop.md`.

- **US-522 (primary, removes the mechanism):** `--disable-gpu` in the
  `eclipse-dashboard.service.{wayland,x11}` `ExecStart`. It is an **override, not
  a deletion** -- `--enable-gpu-rasterization` is not in this repo; Debian/RPi-OS
  exports it from `/etc/chromium.d/default-flags`, which the `/usr/bin/chromium`
  wrapper sources before `exec`ing chromium with the caller's argv **last**. That
  `/etc/chromium.d/` surface is OS-shipped and repo-unmanaged: a chromium package
  upgrade can reintroduce GPU flags (noted at the deploy step, A-16 family).
- **US-523 (defense-in-depth, recovers if it recurs):**
  `deploy/eclipse-kiosk-watchdog.{service,timer}` +
  `src/pi/display/kiosk_watchdog.py`. A 30 s `Type=oneshot` tick counts
  `AllocateRingBuffer` markers in the kiosk's journal over a 60 s window and, at
  ≥100, restarts `eclipse-dashboard.service` -- the mitigation Atlas proved live
  (fresh GPU context, error count back to 0). It runs **unprivileged**, reusing
  the existing polkit `restart` grant
  (`deploy/polkit-rules/51-eclipse-service-control.rules`) and
  `SupplementaryGroups=systemd-journal`.
  **Honest-instrument bounds, all load-bearing:** it never restarts an *inactive*
  kiosk (that would usurp the A-1 hand-off); an unreadable journal is *uncertain*,
  never a wedge; the journal window never reaches back past the last restart; a
  cooldown separates attempts; and an **hourly restart budget** caps the loop --
  once spent the watchdog stops restarting, logs at ERROR and exits non-zero so
  the unit reads FAILED. A restart appearing in its journal means **US-522 did not
  hold**, which is the point: the watchdog surfaces a live freeze class instead of
  masking it. The attempt is recorded to a tmpfs ledger **before** the restart
  fires, so an unwritable ledger cancels the restart rather than silently
  uncapping it. Only the command-buffer signature is detected; the "CPU-pegged
  renderer with no repaint" variant is deliberately **not** implemented (repaint
  is not observable outside the browser and software rendering has no measured CPU
  baseline yet -- a threshold there would be fabricated, not grounded).

**A-2 "full runtime" extension of `eclipse-states-http`.** The server already
ran *continuously* (C-5: `WantedBy=multi-user.target`), so "boot-only → full
runtime" is a **serving** extension, not a lifecycle one: `states_http_server`
now accepts a **repeatable `--assets-dir`** (an ordered search path, first match
wins) so one server serves **both** co-located kits same-origin --
`deploy/eclipse-states-http.service` passes `--assets-dir /opt/splash
--assets-dir /opt/dashboard`. The splash owns `/` (its `index.html`); the
dashboard is reached at `/dashboard.html`. The token is injected into either
kit's HTML, so it still never lands on disk. A missing `/opt/dashboard` is
harmless (the asset lookup just skips it). The new state files the dashboard
reads (`system-status`, `battery-health`, `dtc`) are served by the existing
generic token-gated state route -- no per-endpoint code (US-400/401/404 add the
*emitters*; the server already serves whatever they write).

**Honest-instrument availability (carousel shell).** `carousel.js` polls each
card's `data-state` file at 4 Hz; a missing/malformed payload sets the card to
`unavailable` (never a fabricated value, never green-when-broken). Until the
US-400/401 emitters exist, both cards correctly read `unavailable`.

**Navigation model: wrap + auto-rotate + velocity swipe (US-506, F-124).** The
shipped shell clamped at both ends and classified swipes by *distance alone*.
Both are replaced:

| Fact | Owner | Contract |
|------|-------|----------|
| Wrap | `nextVisibleIndex(current, dir, hidden)` | Past the last card → the first, and back. **Traverses only VISIBLE cards** — a wrap onto a vehicle-gated card paints a blank frame the operator cannot swipe out of, strictly worse than the clamp it replaces. Bounded by `hidden.length`, so a row with ≤1 visible card terminates on `current` instead of spinning. |
| Auto-rotate | `shouldAutoAdvance(paused, sinceMs, autoRotateS)` | Visible cards cycle every `autoRotateS` while unpaused. A non-positive period **disables** rotation rather than firing every tick (fail-to-off: a carousel spinning at the poll rate reads as a hardware fault). |
| Time-to-next | `rotateProgress(sinceMs, autoRotateS)` | 0..1 for the calm thin `#rotate-progress` bar — a bar, never a countdown number. Clamped at 1 (the redraw is the 4 Hz poll tick, not a real-time clock). **Removed while paused**, not frozen part-filled: a stalled progress bar promises an advance that is not coming. Sits at `z-index: 8` under the DTC ribbon's `9` — an alert always wins that band. |
| Gesture class | `swipeGesture(dx, dy, dtMs, widthPx, cfg)` → `{dir, fast}` | Distance ≥ `swipeMinPx` is still required to be a swipe *at all* (the deadzone survives). `fast` = `|v| ≥ swipeFastVelocityPxPerMs` **or** travel ≥ `swipeFastTravelFrac` of the card. Flick → advance + **resume**; settle → advance one + **pause**. |
| Pause self-expiry | `shouldAutoResume(paused, idleMs, resumeIdleS)` | A pause expires after `resumeIdleS` of no interaction, so it can never become a freeze. |

Two honest-instrument guards on the derived quantities: an unmeasurable gesture
duration (`dt ≤ 0`) or an unusable card width (a transient 0×0 layout pass)
contributes **nothing** rather than a fabricated `Infinity`. Dividing by either
would manufacture a flick out of a measurement failure — and `fast` is the signal
that *resumes rotation under the operator's finger*, so a fabricated one is felt
immediately.

Pausing is hung on `document` `pointerdown` — **one** entry point — so a tap on a
card, a page dot, the kebab or any overlay pauses, and an overlay added later
cannot forget to. All of these constants are `pi.display.carousel.*` in `config.json`
(the tuning SSOT), injected at serve time as `window.DISPLAY_CAROUSEL` through
the *same* quoted-placeholder seam US-483-b built for the auto-dim curve
(`_DISPLAY_CAROUSEL_PLACEHOLDER`, `loadDisplayCarouselConfig`). `resolveCarouselConfig`
accepts only finite **positive** numbers over the grounded defaults — which is
what makes a permanent freeze *inexpressible in config*: a `resumeIdleS: 0` can
never reach the resume predicate to disable the self-unpause. Pinned by
`tests/ui/test_carousel_nav_model.py`.

**Debounced `parked` signal behind the `⋮` (US-511, F-124).** US-490 gated the
top-bar kebab directly on the emitter's `idle` SSOT boolean, so every brief
OBD-availability blip removed the button and put it straight back. Flicker on a
fixed affordance does not read as *"the state changed"* — it reads as a broken
panel. A hysteresis debounce now sits between the flag and the menu policy:

| Fact | Owner | Contract |
|------|-------|----------|
| Raw "is the vehicle idle?" | `carouselIdle(systemStatusData)` | Unchanged. Reads the `idle` SSOT boolean strictly; never re-derived from the drive-state string (Atlas idle-SSOT b). Fails closed to *not*-idle. |
| Debounced "is the vehicle parked?" | `parkedNext(prev, rawIdle, nowMs, cfg)` → `{parked, raw, sinceMs}` | `not parked → parked` needs idle held **true** for ≥ `parkedOnS` (8 s); `parked → not parked` needs idle held **false** for ≥ `parkedOffS` (3 s). `parkedInit()` starts **not parked** (fail-closed, matching the button's hidden-in-markup boot state). |
| Menu policy | `menuAccess(parked)` | Applies policy **only**. `tapVisible = parked === true`; `longPress` stays unconditional. |

**The thresholds are asymmetric on purpose.** Offering a single tap into a
service stop is a convenience and can afford to be slow; *withdrawing* it once
the car is moving is the safety half, so it is the fast one. A symmetric
debounce would hold the `⋮` on screen for a full 8 s of driving.

Three properties carry the design:

- **Re-anchor, don't accumulate.** Every change of reading restarts the run, so
  six 2 s blips never add up to one 3 s run — otherwise the flicker this removes
  merely takes longer to arrive.
- **`menuAccess` no longer acquires.** It used to call `carouselIdle` itself, so
  an upstream debounce could be bypassed by the next edit for free; it now
  receives the debounced boolean and cannot reach the raw flag (the standing
  SSOT directive — one authoritative provider per fact, consumers apply policy).
  The strict `parked === true` closes the footgun the signature change creates:
  a caller left un-migrated would pass an *object*, and a truthy test would read
  that as parked forever — the `⋮` pinned on screen at 70 mph.
- **An unmeasured hold is not a hold.** An unreadable clock returns the state
  untouched (recording the reading without a timestamp would let the next real
  clock credit this run's elapsed time to the previous reading), and a *negative*
  hold — an NTP step back on a Pi with no RTC — re-anchors rather than stranding
  the signal for the size of the step.

Display-side only, per the story's own AC: no emitter field, no new contract.
Promoting `parked` to an *emitted* fact is the same class of question as the open
idle-SSOT one and needs an Atlas ruling. `parkedOnS`/`parkedOffS` join the same
`pi.display.carousel.*` section and inherit `resolveCarouselConfig`'s
positive-only rule, so `parkedOnS: 0` falls back to the default rather than
silently deleting the debounce. Pinned by
`tests/ui/test_carousel_parked_debounce.py`.

**Surface invariant: `hidden` means NOT RENDERED (US-495, F-111).** Every
show/hide on this surface is `carousel.js` setting `el.hidden`. The UA sheet's
`[hidden] { display: none }` is a *user-agent* declaration, so **any** author
`display` outranks it -- and each of the five full-screen overlays
(`#dtc-takeover`, `#setup-menu`, `#confirm-modal`, `#dtc-detail`,
`#clear-confirm`) plus `#dtc-ribbon` set `display: flex` through an ID selector.
The attribute was therefore inert: all six painted simultaneously over the
carousel, and the stack swallowed every tap. The JS was correct throughout; the
stylesheet defeated it.

`dashboard.css` now declares **`[hidden] { display: none !important; }`**. The
`!important` is load-bearing, not defensive: an ID selector already outranks any
plain `[hidden]` rule, so the guard must win on *importance* or be duplicated
onto every element -- and the next overlay added would ship the bug again. This
is the one declaration on the surface that must not be overridable. An element
that needs to be present-but-invisible must therefore **not** use `hidden` (use
`aria-hidden` + `visibility`). Pinned by
`tests/ui/test_dashboard_overlay_hidden_guard.py`, which resolves the real
cascade (importance → specificity → source order) for every element the shipped
markup ships `hidden`, so a future overlay is covered the day it is added --
and, since US-499, by the render-regression backstop below, which reaches what
that static sweep cannot: JS-created elements, and the surface *after* the real
`carousel.js` has run.

##### Card model: always-present vs vehicle-gated (US-496, F-121)

Per the CIO-locked card model (Atlas,
`$FLEET_SHARE/knowledge/superpowers/specs/2026-07-28-pi-ui-carousel-ssot-wiring-design.md` §4) the
carousel has **two tiers**, and the difference is *availability semantics*, not
styling:

| Card | `data-state` | Tier | Absence renders |
|---|---|---|---|
| **Home** (US-508) | *(none -- `data-idle-home`)* | always-present | **the fallback face, see below** |
| Alerts (DTC) | `dtc` | always-present | **"no data -- codes not read"** |
| System Status (Pi Health) | `system-status` | always-present | `unavailable` |
| Battery | `battery-health` | always-present | "no data -- UPS feed absent" |
| Fuel Trim | `ltft-trend` | **vehicle-gated** | *gated:* **"no engine data"** / *ungated but silent:* "no data -- trend not computed" |
| Light | `light` | always-present | "no data -- light feed absent" |

The carousel is **six cards** as of V0.29.29, **in the order above**. US-507 had
merged the three slow-moving reference readouts into one *Health* card because
the CIO called six screens too many; **US-540-b split them back out** once
US-540-a's legibility scale changed the arithmetic that call rested on -- at
secondary 26px a card affords about three facts, and Health was carrying six, so
a screen became the cheaper thing to spend than a container of three unrelated
facts. The same markup moved **Alerts to second**.

The bare count remains a **vacuous** assertion and the warning still earns its
place, for a reason US-508 already demonstrated: the `class="card"` count stayed
4 across US-508 while the set changed underneath it, because the pre-US-508 idle
card wore `class="card idle-card"` and was not counted at all. The deploy-kit
inventory test therefore names every slot -- and, as of US-540-b, asserts them as
an **ordered** list, because Alerts moving to second is invisible to a
set-or-count assertion.

##### The three source cards (US-540-b / F-127)

Battery, Light and Fuel Trim are **three standalone cards** driven from one
table, `SOURCE_CARDS` in `carousel.js`, looked up per tick by
`sourceCardSpec(key)` and rendered through `sourceCardView()` /
`renderSourceCard()`. The table **is** the vocabulary -- one place, so a retitle
cannot land in the markup and the renderer out of step:

| Card | state | Gated? | Absence renders |
|---|---|---|---|
| Battery | `battery-health` | no | "no data -- UPS feed absent" |
| Light | `light` | no | "no data -- light feed absent" |
| Fuel Trim (was "LTFT Trend") | `ltft-trend` | **vehicle-gated** | *gated:* **"no engine data"** / *ungated but silent:* "no data -- trend not computed" |

> **The US-507 merged *Health* card is RETIRED.** It no longer exists, and
> neither do `data-states` (plural), `healthCardView()` or `renderHealthCard()`
> -- all deleted by US-540-b rather than left unreachable (US-500). A reader
> looking for a multi-source dispatch path will not find one, and the *plausible*
> wrong conclusion -- that fuel trim is still special-cased through it -- is
> precisely the design US-540-b removed.

Two properties are load-bearing and are pinned by test. Both **survived** the
split, but their justification inverted:

- **Availability is resolved PER SOURCE, never once for the group.** As a merged
  card this had to be *fought for*: one card-level check would have blanked two
  live instruments out of one real fault -- a fabricated *"nothing is
  readable."* Split back out it is **structural**: a dead UPS cannot reach the
  Light card at all. `SOURCE_CARDS` is what keeps this a per-source route rather
  than a group-level branch.
- **The gate SPEAKS instead of hiding.** Fuel trim keeps the US-507 *wording*
  rather than reverting to the pre-US-507 `hidden`, but for a new reason: the set
  is now locked at **six**, so a card that vanishes on a bench breaks the set
  exactly where the CIO reads the panel most days. The gate is still evaluated
  **before** the data and short-circuits, so a gated card carries **no view at
  all** and a stale `ltft-trend` file left from the last drive cannot paint a
  confident trim for an engine that is not running. It ships `data-gated="true"`
  to fail closed before the first poll.

Note the vocabulary now has **three** dispositions, not two: *gated* ("does not
apply"), *no-data* ("the instrument is broken"), and a live reading. Collapsing
the first two would tell an operator with a running engine that there is no
engine.

The card-level `data-vehicle-gated` mechanism below is **retained with zero
current members** -- the Slice-2 Live Engine Data card is its next user.

**Gray vs hidden is a real distinction.** Gray says *"this instrument is
broken/unreadable"*; hidden says *"this instrument does not apply right now."* On
a bench with no car, a grayed fuel-trim card is a false fault report. A card
marked **`data-vehicle-gated`** is therefore revealed only while
`vehicleConnected(sysData)` holds -- an **explicit** `source.obd.available ===
true`. That is deliberately stricter than `sourceUnavailable()`, which treats an
absent `source` block as available for pre-US-429 backward compatibility: that
default is right for "should I gray this tile?" and wrong for "should I reveal a
vehicle card?" An unreadable `system-status` leaves *"is a car plugged in?"*
genuinely **unknown**, and an unknown must never render as a state (the recurring
US-492/US-494 finding), so the gate **fails closed to hidden** and the card ships
`hidden` in the markup for the pre-first-poll window. The Slice-2 Live Engine Data
card carries the same attribute; gating LTFT is also what takes it out of the
always-present set while its emitter is orphaned, without faking or deleting it.

**Consequence -- the carousel geometry counts VISIBLE cards.** `#track` is a flex
row of full-width cards, so a card the `[hidden]` guard removes takes **no slot**.
`visualPosition` / `nextVisibleIndex` / `nearestVisibleIndex` (pure, node-tested)
own that math: the `translateX` step count is the visible position, a swipe steps
*over* a hidden card, a hidden card owns no page dot, and if the card the operator
is on disappears mid-session the view lands on the nearest visible one (preferring
the earlier -- the operator's "back", never a jump past unseen cards). This makes
`.card`/`.dot` keeping **plain** (non-`!important`) `display` declarations
load-bearing: adding `!important` to either would tie importance against the
`[hidden]` guard and restore a gated card to the track. Pinned in
`tests/ui/test_carousel_pi_local_cards.py`.

**Absent-state message per card.** The shell used to write the bare word
`unavailable` on every card. Two cards get a named `noDataView` because the wrong
reading of *their* silence is the dangerous one: a missing `dtc` state means the
codes were **never read** and must never render as "No stored codes" (a fabricated
clean read) or as an alert -- the F-6 no-phantom rule at card level; a missing
`light` state means the **feed stopped**, not "dark" (a fabricated 0 lux). Cards
not listed keep the one-word fallback.

**Light card (US-496).** A pure consumer of the same `states/light` file
(`{lux, ts}`) that drives the auto-dim (§ Display auto-dim consumer), so the
reading on the card can never disagree with the screen it explains -- one clock
per poll tick resolves both. Two tiles through the shared tokenized `.tile`
component: **AMBIENT** (the reading + its read age) and **CONDITION** (`DARK` /
`DIM` / `DAYLIGHT`, a *name* for the existing grounded `luxMin`/`luxFull`
thresholds -- not a third set of numbers that could drift from the curve). A null
`lux` (the bridge's honest saturated/unreadable marker), an undated payload, or a
reading older than `luxStaleSec` grays **both fields individually** with the
*reason* as the tile detail, so the operator learns which fault it is; the card
itself stays present. Screen brightness is deliberately **not** shown: a live STOP
alarm holds the surface at full regardless of lux (US-484-b ch.4), so a
lux-derived percent would contradict the actual screen exactly when it matters
most.

##### The HOME SLOT is two-faced -- live instrument / honest fallback (US-508, US-541/US-542 / F-124, F-127)

The CIO-locked round-2 design puts the live instrument on the **home slot**.
**US-541/US-542 (F-127) settle which two faces**: the live motion instrument is
the **permanent** face, and the second face is the honest fallback and nothing
else. **One slot, two faces**, not two cards -- a separate always-present motion
card beside a live home slot would poll and paint the same feed twice and put two
rules in charge of what the driver lands on.

`homeFace(imuData, nowMs)` is **the only arbiter** (a second one would be two
rules owning one fact -- exactly why US-497 declined to build the swap). It reads
**the motion feed only**; the vehicle state is deliberately **not** a parameter,
so a function that cannot see `system-status` cannot be re-coupled to it without
a visible signature change:

1. A **live and fresh** `states/imu` → the live face. This holds **parked**: the
   IMU is Pi-local and always-live, so parked is exactly when its readings are
   both true and worth reading (a true heading, a true 0.0 g). US-508's *"parked
   wins outright"* is **reversed** -- it spent the one always-on instrument on
   the one state where nothing else is readable.
2. Everything else -- no file, `available:false`, undated payload, reading older
   than `IMU_STALE_SEC` -- falls back to the fallback face (AC-3: never a frozen
   motion display).

**The fallback must not fabricate a parked state**, and US-542 closes that trap
by **deletion** rather than by a better condition. The old idle hero read
*"STANDBY · engine off · OBD asleep"*; with the fallback now reachable only from
a dead sensor, rendering it would state a confident fact about the vehicle
manufactured out of a sensor fault. The **STANDBY hero is retired** -- no
sentence claiming "engine off" survives on the surface -- and the single
surviving disposition renders **"NO MOTION DATA"** plus the bridge's own reason.

Two things left with the retired parked screen and neither is lost: the **wall
clock moved to the top bar** (`#topbar-clock`), where it is readable from every
card, and **"DTC not read · since key-off" moved to the Alerts card**, where it
was always an Alerts fact. The **date** was **not** relocated -- the 480px top
bar at the US-540-a scale affords a clock, not a clock and a date. That is a
deliberate, named copy loss, alongside US-510's locked parked-screen navigation
footer (the ⋮ affordance it taught is untouched and still in the top bar).

The retirement is **display-only**: `carouselIdle` / `parkedNext` remain the
parked SSOT for the auto-rotate pause and the ⋮ reveal, and
`tests/ui/test_carousel_idle_face_retirement.py` pins that separation so a future
edit cannot re-couple them. (Two different things in `carousel.js` are spelled
*idle* -- the parked SSOT and the retired face -- which is precisely why the
split is asserted rather than assumed.)

Navigation was **retargeted, not dropped**. US-481 sent the operator to System
Status when `idle` flipped false, because the home card was a parked-only view.
The home slot now *becomes* the live instrument, so both edges land on **home**.

**Transport (Atlas ruling, US-508).** A compass tape and a g-trail do not
animate at the 4 Hz card tick, so the live feed gets its **own ~10 Hz loop**
(`IMU_POLL_MS = 100`) against the same `states_http_server`, and the bridge
writes at `pi.sensors.imu.stateHz` = **10 Hz** latest-wins/lossy. Deliberately a
second loop rather than a faster shared tick: the tick reads five other state
files, and 2.5×-ing all of them to animate one card would be five reads nobody
can see for every one they can. The durable EDR persist stays at `persistHz` --
**one producer, two cadences**. No new transport; SSE remains a future EDR-bus
target and is explicitly not a gate here.

##### The live instrument itself (US-497 / F-113, re-issued by US-508)

A pure consumer of the `states/imu` file the § 10.8.2 bridge writes. The bridge
already resolved the hard physics (one slow gravity estimate defining the level
frame, the pitch *and* the heading tilt-compensation); the card **maps and
formats only** -- it never fuses and never re-derives, because a second
derivation is a second chance for the compass and the grade to disagree about
which way is down (Atlas DELTA-2). It is **always-present, not vehicle-gated**:
the ICM-20948 is a *Pi-local* sensor that reads on the bench with no car, so
gating it behind a vehicle would hide a working instrument.

**A live graphical instrument can FREEZE; a text tile cannot.** This is the one
property that shapes the whole card. A gray "NA" reads as dead at a glance, but a
g-dot frozen at 0.4 g reads exactly like a car holding a steady corner -- a
fabricated measurement, not a visible gap. So the freshness gate blanks the
**instrument** rather than graying a label: an explicit `available: false`, an
undated payload, or a reading older than `IMU_STALE_SEC` renders the calm gray
MOTION body and *no geometry at all* (US-497 AC-3). Within a live reading,
absence is still per field -- a dead magnetometer grays HEADING alone (and hides
the needle: a needle frozen at its last bearing is worse than an absent one),
an unresolved tilt grays G-FORCE **and carries no dot**, and `altitude` is
**always** typed-NA `"no source"` without ever blocking the card.

The **compass TAPE** (US-508) replaces the built rotating needle outright --
CIO-locked, and leaving the needle beside it would be two heading instruments on
one card that can disagree. A fixed caret marks the vehicle's bearing and the
tape scrolls under it: a bearing *clockwise* of the current heading sits to the
**right**, so turning right walks it toward the caret and the labels travel
right-to-left. That direction is the most likely defect in the whole card -- a
backwards tape is a perfectly plausible instrument, and no screenshot reveals
it -- so it is pinned by test, as is the wrap across north. A dead magnetometer
renders **no ticks at all**; a tape frozen under the caret reads as a confident
heading exactly as the frozen needle did.

**GEAR is not an IMU fact.** Atlas kept it out of the `states/imu` contract: it
is Spool's OBD derivation from a **separate producer** (F5M33 ratios + tyre
circumference, debounced, validated against drive 30). *That producer does not
exist yet*, so the glyph follows the **altitude precedent** on this same card --
the field stays in the contract so a real producer is zero-rework, and it
resolves to an honest `--` until one lands, never a guessed number. Nothing
polls a `states/gear` file, because a 404 ten times a second is not a data
source. The reason rides beside the glyph so *"no producer wired"* stays
distinguishable from *"the producer is refusing to guess right now"*.

| Constant | Value | Grounding |
|---|---|---|
| `IMU_STALE_SEC` | 2.0 s | **Re-grounded by US-508**: at the new 10 Hz `stateHz` this is *20* missed writes, not the 8 it was at 4 Hz. Deliberately NOT retightened in proportion -- this feed now drives the HOME slot, and a slot that flips to the fallback face on a brief scheduling stall is its own defect. Still far tighter than the light card's 10 s (a 10 s-old lux is roughly true; a 10 s-old g-vector is meaningless). *Rex-derived; flagged for Atlas/Spool against a real drive.* |
| `G_FULL_SCALE` | 1.0 g | outer ring. A street-tired car tops out near 0.9 g lateral, so 1 g frames real driving without compressing it. *Rex-derived DISPLAY scale, not a vehicle limit -- flagged for Spool.* |
| `G_AMBER_G` | 0.6 g | **Spool** (Iris locked spec, quoted verbatim in the US-508 AC). A **different fact** from the full scale above, and conflating them is what the built card got wrong: it only coloured at the 1.0 g *clamp*, so a hard 0.8 g corner painted identically to a gentle one. Advisory, never an alarm -- alarms ride the unified alert layer. |
| `G_TRAIL_WINDOW_SEC` | 35 s | Iris live-instrument spec. ~350 points at the 10 Hz live poll. |
| `GRADE_TREND_WINDOW_SEC` | 900 s | Iris locked spec's "~15-min moving trend". |
| `GRADE_TREND_BUCKET_MS` | 5000 | Decimation: 15 min at 10 Hz is ~9000 raw samples; one retained point per 5 s bucket is ≤180, more than a 480×320 sparkline resolves. **Latest-wins within a bucket** -- the retained value is a real reading, never an average that never happened. |
| `GRADE_TREND_SCALE_PCT` | 10 % | The sparkline's **fixed** vertical scale, deliberately not autoscaled to the observed range: an autoscale stretches a flat road's hundredth-of-a-percent wobble to full height and renders it as a mountain range -- a fabricated terrain built out of real noise. Beyond scale it clamps to the edge (pinned, not vanished). *Rex-derived DISPLAY scale -- flagged for Spool.* |

**Sign contract on screen.** `gLon` + = accelerating → the dot moves **up**
(negative screen y); `gLat` + = **right** → positive x. The G-FORCE tile spells
both components out in words ("0.30 right · 0.12 brake") so a board mounted
backwards becomes obvious to the operator instead of silently mirroring the dot.
An over-scale reading **clamps along its own direction** (never per-axis, which
would swing the dot to a corner and misreport which way the car was loaded) and
turns amber, while the tile keeps the true magnitude -- the clamp cannot
understate a 1.4 g stop as a tidy 1.0 g one.

**The trail is the card's only client state** (Atlas Q-B: animate from the
polled values; a higher-rate transport is a later refinement, not a gate). It
lives in the poll closure, is drawn as a single `<polyline>` -- 140 discrete
nodes rebuilt at 4 Hz would churn ~560 elements/sec on a kiosk Pi for nothing --
and is **reset the moment the instrument is not live**. Splicing a point from
before an outage onto one after it would draw a trail the vehicle never took;
eviction also runs on a tick with no usable point, so a stopped feed decays the
trail to empty instead of freezing its last shape.

**Deploy.** `deploy-pi.sh step_install_dashboard_assets` installs the served kit
to `/opt/dashboard` (WARN-not-BLOCK if absent, A-9), mirroring
`step_install_splash_assets`; the kiosk **unit** is installed by the kit's
session-aware `install.sh` (V-1/V-2), the same seam as the splash kiosk unit.

##### `/opt` asset-ownership contract -- force-refresh + prune (US-495, F-111)

The ordered search path above has a sharp edge that cost a sprint of "the deploy
succeeded but the Pi renders something else": **`/opt/splash` is searched
first**, so any file sitting there shadows the same-named file in
`/opt/dashboard` permanently, and the dashboard step -- which only ever writes to
`/opt/dashboard` -- can never dislodge it. Both asset steps used to *only*
install on top of `/opt`; nothing was ever removed, so retired kit generations
accumulated there indefinitely. That is how the Pi came to serve a wordmark
("Eclipse ODB2") that exists nowhere in this repo.

Both steps now delegate to **`deploy/asset-refresh.sh` →
`refresh_asset_dir SRC DST MANIFEST [KEEP]`**, which makes the installed dir an
exact mirror of what the repo vouches for:

1. **install** every manifest asset the source kit ships;
2. **prune** everything else -- including a *manifest* asset the source kit no
   longer ships. A file the repo cannot vouch for must not be served: an honest
   404 beats a confident stale render;
3. **verify** each installed file byte-for-byte against its source.

| Dir | Manifest (installed + owned) | Keep-list (another installer owns) |
|---|---|---|
| `/opt/splash` | `index.html`, `styles.css`, `boot-state-poll.js`, `shutdown.html`, `shutdown-state-poll.js`, `splash.svg`, `splash-shutdown.svg` | `version.txt` (generated by the same step, after) |
| `/opt/dashboard` | `dashboard.html`, `dashboard.css`, `carousel.js` | *(none -- single installer)* |

`/opt/<kit>` is **deploy-owned, not hand-edited**: anything dropped there
out-of-band is pruned by design.

**The keep-list is a cost, not a safety net (US-498).** A keep-listed asset is
never installed, never pruned and never byte-verified by the deploy, so every
entry is a piece of `/opt` the guard cannot vouch for. US-495 keep-listed the
whole closeout surface on the reasoning that the kit's own `install.sh` owns it
-- but that installer is the **A-9 kiosk-unit step, which is allowed to WARN and
skip** (it aborts outright when it cannot detect the session type or the
chromium binary), so the closeout surface had no guaranteed refresh path at all.
The exact hole US-495 closed for the boot surface stayed open for the shutdown
one, where a stale render only reveals itself *during a shutdown*, with nobody
watching and no way to re-run it. Both installers copy the same bytes from the
same synced kit dir, so the deploy owning them costs nothing and buys the
byte-verify. `version.txt` is the only legitimate entry: the deploy **generates**
it from `deploy/RELEASE_VERSION` after the refresh, so it is not a kit file the
manifest could name. Pruning it in the window before it is rewritten is the only
thing the keep-list now prevents.

**Posture change vs A-9, deliberate.** *Absence* still warns and continues (a Pi
without the UI kit still ships the rest of the tier). A *failed write* now
**blocks**. They are different facts: absence is a Pi that was never given a UI;
a failed write is a deploy that believes it shipped one and did not. Continuing
past the second is what prints "Deploy OK" over a stale surface and sends the
operator to debug the UI instead of the deploy (the A-16 lesson). Behaviour is
pinned by `tests/deploy/test_asset_refresh.py`, which drives the real shell
function against temp dirs rather than grepping the deploy script.

##### Render-regression backstop -- the automated A-16 guard (US-499, F-121)

Sprint 66 shipped three defects that **every unit test passed**, because all
three were *composition* failures rather than component failures:

| Defect | Every part was correct | What was broken |
|---|---|---|
| US-494 (S1) | `computeBootState` was right; the splash JS was right | the systemd entry point never injected `obdProbeFn`, so the payload the **production wiring** emits never reached `healthy` -> no handoff |
| US-495 (S2) | `carousel.js` set `el.hidden` correctly on 18 call sites | an ID-selector `display: flex` outranked the UA `[hidden]` rule, so six overlays painted at once |
| US-498 (S5) | the delay, the fill-mode and the direction were each valid | their *interaction* held the closeout mark at `opacity: 0` for 6 s of a 7 s grace window |

`tests/ui/test_render_regression.py` is the permanent guard on that class. It is
deliberately **compositional**, in two processes that cannot see each other's
verdict:

1. **node** (`tests/ui/dom_probe.js`, `splash_probe.js`, on `mini_dom.js`) boots
   the **shipped** `carousel.js` / `boot-state-poll.js` against the **shipped**
   markup and the state files a test declares, then dumps the resulting DOM. It
   knows nothing about CSS.
2. **python** (`tests/ui/render_harness.py`) resolves the **shipped** stylesheet
   over that DOM -- importance -> specificity -> source order, inline
   declarations, `display: none` inherited through ancestors -- and answers the
   only question that matters: *does this element have a box?*

The mini-DOM reflects IDL properties onto **content attributes** (`el.hidden =
true` becomes the `hidden` attribute) because the attribute is what the cascade
selects on. A harness that stored `hidden` as a private flag would have
reproduced the US-495 blind spot instead of catching it.

**It is proven RED, not asserted to be.** Each guard has a partner test that runs
the same harness against the **real pre-fix artifact from git** -- the
pre-US-495 stylesheet (all six overlays paint) and the pre-US-494 emitter loaded
as a live module (the splash pins, degrading with the literal
`eclipse-obd: not ready (starting)` the CIO read off the panel). Two **mutation**
proofs run unconditionally beside them (delete the `[hidden]` guard rule; strip
its `!important`), so the backstop stays self-verifying even where git history
is unavailable -- and they pin the `!important` as load-bearing, which is the
fragility US-496 flagged.

It also covers the one surface no static sweep can reach: the **page dots are
created by JS**, so `test_dashboard_overlay_hidden_guard.py` (which enumerates
elements the *markup* ships `hidden`) can never see them. Here they are built by
the real `carousel.js` and rendered through the real cascade, against the
visible-card geometry the US-496 vehicle gate introduced.

**Fidelity limit, stated because an unstated one is how a lenient test passes on
a broken layout:** this resolves the **cascade**, not **layout**. It sees "not
painted"; it cannot see overflow, wrapping, or a box pushed off-screen. Sibling
combinators (`+`, `~`) are not resolved. To stop that leniency being silent,
`Surface.unresolvableDisplaySelectors()` reports any `display` rule behind a
pseudo-class the resolver cannot evaluate, and
`test_harnessCanJudgeEveryDisplayRule` **fails** when one appears -- teach the
resolver or move the rule; do not delete the test. The residual gap is a real
kiosk smoke on the panel, which remains the per-story on-Pi render check.

> **Sequencing note (A-4):** the dashboard and the pygame `status_display` must
> never run simultaneously. The pygame surface was **retired (parity-gated) in
> US-402** — once the System Status + Battery Health cards reached parity
> (US-400/401) — by setting `pi.hardware.statusDisplay.enabled=false`, then
> **fully removed in US-485 (V0.29.15)** (module + wiring + config key deleted).
> There is now **exactly one** dashboard surface (the carousel) with no overlay
> flag left to re-enable. See the US-402 subsection below for the original
> cut-over fix.

#### System Status card + `system-status` emitter (US-400) [Atlas A-3]

The **System Status** card (Card 1) renders the `system-status` state file at 4
Hz: OBD-link / sync / power / drive tiles + the top-bar BT/sync/power glyphs.

**`system-status` emitter (`src/pi/splash/system_status_emitter.py`).** The
**orchestrator/sync tier owns this emitter** (A-3): it holds the live BT-link,
the `sync_log` high-water mark, the power source, and the `DriveDetector` state,
so it calls the injected `makeSystemStatusEmitter(...)` → `emit(...)` callable —
the same unidirectional seam as the shutdown emitter (`power_watch` → splash):
the emitter never reaches back into the orchestrator. The emit is **best-effort**
(write failures logged, never raised → the dashboard hook can never block the
orchestrator loop) and writes the A-3 schema atomically (`writeStateAtomic`,
reusing the boot-state primitives). Schema (spec §7):

```json
{ "obdLink": {"state":"reconnecting","retries":3,"lastSeenS":14},
  "sync": {"lastOkTs":"…","rows":1204,"pending":0,"stale":false},
  "power": {"mode":"car","source":"external"},
  "drive": {"state":"recording","driveId":27},
  "ts":"…" }
```

**I-033 reconnect visibility.** `obdLink.state` is reported **verbatim** —
`linked` (green) / `reconnecting` (amber, with `retries` + `lastSeenS`) / `down`
(red) — never fabricated as `linked`. On a mid-drive BT drop the reconnect loop
flips the state to `reconnecting`; the 4 Hz poll surfaces `RECONNECTING` on the
tile and an amber BT glyph within ≤2 s (the operator finally *sees* the
reconnect, closing the I-033 "did it capture my drive?" blind spot).

**Power-mode SSOT (US-421 / F-098, Sprint 52 / V0.29.6).** The `power.mode`
field (`car` / `wall` / `unknown`) reports the **deployment context** — Pi
installed in-car vs. bench/wall power — which is a *different fact* from
`power.source` (AC-vs-battery, the `power_source_provider`). Its single
acquisition path is `PowerModeProvider` (`src/pi/power/`), which reads the
static config key **`pi.power.mode ∈ {car, wall, unknown}`** (validator DEFAULT
`unknown`) and is THE SSOT for the fact (zero other acquisition paths). The
provider is wired through `system_status_emitter.buildSystemStatusState` into
`carousel.js#powerTile`, which renders CAR / WALL / **unknown**. An
absent/stale/invalid config resolves to `unknown` — **never a confident wrong
mode** (honest-instrument). The seam is designed so acquisition can later swap
config → a GPIO sense line behind the same `PowerModeProvider` interface with
zero consumer change (future; the GPIO line is out of scope for V0.29.6).

**Honest-instrument render (F-1).** `carousel.js#systemStatusView` maps the state
to tile levels (`ok`/`amber`/`down`/`unavailable`) + glyph states; a level/glyph
is **`ok` (green) only when the underlying state is genuinely good**. A
down/reconnecting link, a stale sync, or running on battery renders
amber/down/neutral — never green. A missing sub-object renders that tile
`unavailable` (the rest of the card still renders); a missing/malformed file
renders the whole card `unavailable` and resets the glyphs to neutral (no
lingering stale-green). Tiles are built with `textContent` (no `innerHTML`), so
emitter values render verbatim, never as markup.

**Stale-while-driving (I-4).** `isSyncStaleWhileDriving` flags `sync.stale=true`
**only while recording** (a parked Pi catches up on WiFi return) when the last
sync exceeds the threshold — and treats an absent/unparseable last-sync as stale
(never claim a freshness we can't prove). The **threshold is Spool-owned (S-3)**
and supplied by config: the emitter takes `syncStaleThresholdS` as a required
parameter and **hardcodes no tuning number** (PM Rule 7 / Refusal Rule 2).

**Summary drill-down (US-509, Sprint 68 / V0.29.23).** The US-489 one-glance
`SYSTEM · N ISSUE` line is **tappable → a drill-down overlay** (`#sys-detail`,
`carousel.js#systemIssueRows` / `#systemDrill`), one row per non-OK source,
**worst-first**: source label + state chip + the tile's own reason + freshness,
with a `‹ Back` that always returns. It is a **presentation of the same tiles**
the 2×2 grid renders — the drill rows travel on `systemStatusView().drill`, so
one read of the state file feeds the grid, the summary **and** the overlay, and
the overlay is structurally incapable of contradicting the card behind it. No
source state is recomputed. Four decisions are load-bearing:

- **The listing floor is `unavailable`, not `amber`.** `ok` is never listed (a
  green source in a fault list is a *fabricated* fault) and `neutral` is not
  either — `DRIVE=IDLE` means "not recording", **not broken**, so listing it
  would report a fault in the commonest state there is. But a known-**unknown**
  *is* listed: the summary reads `SYSTEM · N UNAVAILABLE` in that state, so
  excluding unavailables would make a tappable headline open an **empty**
  overlay — the exact dead end this surface exists to remove.
- **Freshness is never fabricated.** Only `obdLink` publishes `lastSeenS`; rows
  for sources that publish no age read **"age not reported"**, never
  `"seen 0s ago"` (which would claim we had just seen a source we never timed —
  the zeroed-altitude lie of US-508 in a different costume).
- **The affordance is gated on `drill.tappable`** (`rows.length > 0`), so a
  healthy card never advertises detail it does not have.
- **An open overlay repaints on every poll** rather than freezing on the
  snapshot that opened it — a frozen age readout is the same fabrication the
  g-dot (US-497) and the rotate bar (US-506) are guarded against.

The overlay **reuses the US-406 per-code detail shell** (`.detail-head` /
`.detail-body` / `.detail-card`, the same `‹ Back`) so the two drill-downs speak
one interaction language, and it inherits the auto-rotate pause from the single
document-level `pointerdown` seam US-506 established — no per-overlay pause call
site to forget.

#### Battery Health card + `battery-health` emitter (US-401) [Atlas A-3]

The **Battery Health** card (Card 2) renders the `battery-health` state file at 4
Hz: the Spool health verdict + VCELL + charge + temp, and a failsafe drain ladder
**only during a real drain**. The cell is the **Pi UPS-HAT LiPo (MAX17048 fuel
gauge), never the car's 12 V lead-acid (F-11)**.

**`battery-health` emitter (`src/pi/splash/battery_health_emitter.py`).** The
**orchestrator/power tier owns this emitter** (A-3): it holds the live MAX17048
reads, the `battery_health_log` history, and the power-watch draining state, so it
calls `makeBatteryHealthEmitter(...)` → `emit(...)` — the same unidirectional
best-effort seam as the system-status + shutdown emitters (write failures logged,
never raised; atomic `writeStateAtomic`). Schema (spec §7):

```json
{ "vcellV":4.02, "soc":76, "socCalibrated":false,
  "crate":1.8, "charging":true, "draining":false,
  "restedVcellV":4.05, "weakEvents30d":0, "restedHistory":[…],
  "health":"green", "fullChargeReached":true, "runtimeToCutoffS":714,
  "ambientTempC":null, "lastHealthCheckTs":"2026-05-16T00:00:00Z",
  "ladder":null, "ts":"…" }
```

**Two render-breaking honesty traps locked at the data contract:**

- **Voltage-is-not-percent (F-8).** `battery_health_log.*_vcell_v` columns hold
  **volts**; the dedicated `*_soc_pct` columns (US-426) hold percent — the legacy
  misnamed `*_soc` columns that stored volts were dropped in US-426. The emitter
  has **no code path from `vcellV` to `soc`** —
  the percent comes only from the MAX17048 SoC register, and a `null` register read
  passes through as `soc:null`. `carousel.js#batteryHealthView`/`socTile` renders
  the percent **only when `soc` is a real number** (tagged `(uncalibrated)` when
  `socCalibrated:false`); a `null` soc omits the percent and the card shows volts
  (`vcellTile`, `"3.44 V"`). The trap is locked by **absence** — a voltage can
  never be painted as a percent.
- **Stale-green guard (F-9).** A GREEN verdict **always** carries
  `"last health check · <date> (<age>)"`, computed by `healthCheckLine` from
  `ts − lastHealthCheckTs` (both in the state file, so the age is deterministic /
  node-testable, not browser-clock dependent). A month-old reading is never
  mistaken for live.

**Temp honest (F-10).** `ambientTempC:null` → the card renders **"not captured"**,
never a fabricated number.

**No-false-failsafe (A-6 / F-2).** The failsafe `ladder` block (stage + thresholds
+ runtime) renders **only when `draining === true`**. The invariant is enforced in
the **pure builder** (`buildBatteryHealthState` forces `ladder=None` whenever
`draining` is false, even if a caller supplies one) — the SSOT, so a buggy caller
can't light a phantom drain. The **live runtime-remaining + ladder thresholds
(3.70/3.55/3.45 V) are Spool-owned (S-2, failsafe-only)** and arrive inside the
caller's `ladder` dict; the emitter/render **never fabricate** them — a draining
pack with no Spool data shows the stage + volts only, no minutes.

**C-5 states-dir writers.** The `battery-health` emitter is the third post-boot
writer into the F-103-provisioned `states/` tmpfs dir, after `system-status` and
before the **fourth writer `dtc` (US-404)**. All four reuse
`ensureStatesDir`/`writeStateAtomic`, ordered after the states-dir provisioning —
they never re-invent the lifecycle. The full post-boot writer set is therefore
`system-status` · `battery-health` · `dtc` (the F-103 boot/shutdown emitters own
`boot-state` / `shutdown-state`).

#### Card-state emitter run-model + deploy-install (US-480, Sprint 61 / V0.29.15) [Atlas Q-1]

The three post-boot card emitters above describe **which tier owns each fact**
(A-3) — but an emitter only *runs* if something invokes it each loop, and only
survives a reboot if that host is deploy-installed to boot-start. Both were the
gap that shipped the emitters **dark**: code merged, but `/run/eclipse-obd/states/`
held only `boot-state` and the carousel cards rendered the NA/unavailable wall.

**Run-model (US-480-a — orchestrator-invoked, NOT standalone units).** The
OBD-dependent emitters are driven *in-process from the orchestrator process that
owns the single `ObdConnection`*, via `CardStateEmitterMixin`
(`src/pi/obdii/orchestrator/card_state_emitter.py`). The mixin constructs the
three emitters once (`_initializeCardStateEmitters`) and the run-loop calls
`_maybeEmitCardStates()` once per pass on a ~2 s cadence gate; every read is
best-effort + exception-isolated so a dashboard hiccup can never crash the
capture loop. The emitters are **pure consumers** of `self._connection` — they
open **no** connection of their own. This is load-bearing: a standalone systemd
unit that read OBD would open a **second** connection to the non-thread-safe
python-obd port and re-introduce the **A-17** serialization race the DTC-read
work just closed. (`battery-health` reads the MAX17048 over I²C, not the OBD
port, so it is safe either way, but rides the same in-process cadence for
coherence.) The `idle` boolean is written by the `system-status` emitter — it
owns both inputs (`obd.available` + `driveState`), so `idle` is an explicit SSOT
flag, not a display-derived guess (consumed by the idle home card, US-481).

**Deploy-install (US-480-b — boot-persistence).** Because the emitters run inside
`eclipse-obd.service`, deploy-installing their *execution* reduces to one systemd
fact: `deploy-pi.sh` must **`systemctl enable eclipse-obd`**
(`step_install_eclipse_obd_unit`) so a fresh `--init` Pi + reboot auto-starts the
orchestrator — and with it the emitters — with **no manual step**. The unit has
always declared `WantedBy=multi-user.target`, but "installed" ≠ "enabled"; the
deploy previously installed + restarted the unit yet never asserted the enable.
It is `enable` (not `enable --now`): `step_restart_service` owns the actual start
via an explicit stop→start (US-389 release-then-acquire of the single-instance
pidfile; a `--now` here would race it). The enable is re-asserted on every deploy
**outside** the `cmp -s` sync-if-changed gate, so a Pi installed pre-US-480-b —
or disabled out-of-band — self-heals on a routine re-deploy. The `states/` dir
itself is already boot-durable via the tmpfiles.d entry (Atlas C-5, above),
independent of the orchestrator's start order, so the cards render an honest
state even before eclipse-obd finishes coming up. **No separate emitter unit
exists — the orchestrator IS the emitter host.**

#### Pygame sunset — parity-gated cut-over (US-402) then full removal (US-485) [Atlas A-4]

Once the System Status (US-400) and Battery Health (US-401) cards reached parity
with the legacy pygame **status overlay**, that overlay was **retired** so the HTML
carousel is the **sole** dashboard surface (failure **F-4**: the two must never be
active simultaneously). The data the overlay used to paint is now republished
through the `system-status` + `battery-health` emitters into the state files the
carousel reads.

**US-402 cut-over mechanism (V0.29.3).** The initial retirement was a single
config flip: `pi.hardware.statusDisplay.enabled` → `false` in `config.json`. With
the overlay off, `HardwareManager` never opened a pygame surface; the carousel
kiosk (launched by the splash `OnSuccess=` hand-off) was the only surface. This
was parity-gated — pygame retired **only** once the cards existed, never before.
(That cut-over relied on a factory resolution fix: the canonical flag lives at the
pi-**nested** `pi.hardware.statusDisplay.*` path that `lifecycle.py` passes, so the
factory had to resolve the nested path first — the flat top-level path alone had
silently launched the overlay on its `True` default.)

**US-485 full removal (V0.29.15).** The config-disabled overlay was dead code
carrying a re-enable footgun, so US-485 completed the sunset: `status_display.py`,
`dashboard_layout.py`, every `HardwareManager` launch/wiring member
(`_initializeStatusDisplay`, the `_startComponents` display branch,
`_displayUpdateLoop`, the `_cleanup` branch, the `statusDisplay` property, the
`display*` constructor params + factory reads), the `pi.hardware.statusDisplay`
config key, and the two module tests are all **removed**. `HardwareManager` no
longer owns any display; its `updateObdStatus` / `updateErrorCount` remain as
documented **no-op stubs** so the orchestrator's best-effort status push
(`event_router`) stays valid without an `AttributeError`, and `getStatus()['display']`
is a permanent `None` for consumer back-compat. There is no longer any bench
re-enable path — the overlay is gone, not merely disabled.

#### System Setup menu + gated service control (US-403) [Atlas A-7/A-8]

The dashboard's persistent `⋮` and a deliberate **~5s long-press** (a filling
ring; an early release or any movement >10px cancels — `carousel.js`
`longPressProgress`/`isLongPressComplete`/`exceedsMoveCancel`) both open the
**System Setup menu** (D-6). The menu offers **gated service control** over an
**install-fixed allow-list** of `eclipse-*` units and an **Exit / Close UI**
item (A-8). Confirm-before-consequential: **Stop** and **Exit** require a confirm
modal; **Restart** acts directly; a `✕`/Back is always present (the operator is
never trapped, F-6).

**Privilege path (A-7) — three independent defense-in-depth layers.** The
chromium kiosk runs **unprivileged** and can only do HTTP; it never runs as root
and never holds sudo.

1. **UI layer** — the menu mirrors the allow-list (`carousel.js`
   `SERVICE_ALLOWLIST`/`serviceMenuItems`/`actionRequest`); `eclipse-powerwatch`'s
   Stop button is rendered **disabled** (it is the safe-shutdown guard — D-7).
2. **Action-path layer** — the kiosk POSTs `/service-control {unit, verb}` to the
   token-gated route on `eclipse-states-http` (the only IPC the kiosk has). The
   server delegates to `src/pi/splash/service_control.py`, the **SSOT** for the
   allow-list, which **re-checks** every action at execution time (a tampered or
   bypassed UI can never drive an off-list action — the F-092 analog of US-407's
   S-10 clear-gate re-check). Off-list → 403, never executed.
3. **PolicyKit layer** — `service_control` shells out to `systemctl <verb> <unit>`
   as the unprivileged `mcornelison` user; the net-new
   `deploy/polkit-rules/51-eclipse-service-control.rules` authorizes it. The rule
   grants `org.freedesktop.systemd1.manage-units` **keyed on BOTH the unit AND
   the verb**, so the verb can be denied per-unit. It is a **sibling** of the
   I-036 `50-…poweroff` rule (a different action, `manage-units`), **not** a
   widening of it and **not** a privileged helper daemon.

**Allow-list (one SSOT mirrored across the three layers):**

| Unit | Verbs | Note |
|------|-------|------|
| `eclipse-obd.service` | start / stop / restart | data capture |
| `eclipse-sync.service` | start / stop / restart | server upload (unit not yet deployed — see below) |
| `eclipse-dashboard.service` | stop / restart | **A-8**: Exit = stop the kiosk |
| `eclipse-powerwatch.service` | **restart ONLY** | **D-7/F-7**: stop/kill DENIED at the polkit rule itself |

**The powerwatch restart-only guard (D-7/F-7) is the load-bearing invariant.**
Stopping the safe-shutdown guard could leave the Pi unprotected on key-off. A
`stop`/`kill` is refused at **all three** layers — and critically at the polkit
rule (an explicit `polkit.Result.NO`), so even a direct
`systemctl stop eclipse-powerwatch` issued at the action path with the UI
bypassed is refused. This mirrors US-407's "re-check at the action path, never
trust the UI."

**Exit/Close lifecycle (A-8).** Exit issues `stop eclipse-dashboard.service`,
dropping to the desktop. The unit has no `[Install]` section — it is started by
the splash `OnSuccess=` hand-off — so the next **reboot** re-launches it (or
`systemctl restart eclipse-dashboard` over SSH brings it back immediately); the
confirm dialog states how it returns.

**Deploy note — `eclipse-sync.service` is not yet a deployed unit.** The design
names `eclipse-sync` as a controllable service, but no such unit ships in
`deploy/` yet (Pi sync currently runs inside the orchestrator / `sync_now.py`,
not a standalone unit). It is included in the install-fixed allow-list +
polkit rule as designed; until the unit exists, an action on it returns an honest
`systemctl` failure (the status reflects reality, no fabrication). Filed to PM as
a deploy gap — the mechanism is complete and forward-compatible.

#### DTC capture path — key-on (KOEO) read + `dtc` emitter (US-404) [Atlas A-9 / F-111]

The DTC viewer (Alerts card US-406, takeover/ribbon US-405, Mode-04 clear US-407)
is a **pure consumer** of a new `dtc` state file. US-404 builds the Pi-side data
layer that publishes it: the key-on read, the emitter, the severity loader, and
the read-only HTTP endpoint. One direction of data flow — the display never reads
hardware and never decides severity.

**Key-on (KOEO) read on the connection edge.** `EventRouterMixin._dispatchKeyOnDtcs`
fires a **one-shot** Mode 03(+07) read on the OBD **connection-established edge**
(`_handleConnectionRestored`), **gated on no active RUNNING drive**
(`_driveDetector.isDriving()` — the gate **fails closed**: an unverifiable drive
state skips the read). While a drive is RUNNING the drive-scoped paths
(session-start / MIL / periodic) own capture; the KOEO read exists only for
key-on/engine-off (RPM 0) where `DriveDetector` never arms — closing the "blank at
key-on" gap. **Ownership is the DTC capture path, NOT DriveDetector** (Atlas A-9):
the new `DtcLogger.logKeyOnDtcs` reuses the existing `DtcClient` and persists every
`dtc_log` row with **`drive_id = NULL` stamped EXPLICITLY** — it does **not**
consult `getCurrentDriveId`. A pre-US-388 stale-open-drive leak could leave a
phantom `drive_id` on the process context; inheriting it would mis-attribute a
key-on read to a drive that isn't happening (cross-links A-9 Root 2). NULL is the
honest attribution, and the display renders "key-on read" rather than "Drive N".

**`dtc` emitter (fourth states-dir writer).** `src/pi/splash/dtc_emitter.py`
mirrors the `system-status` / `battery-health` seam: a pure `buildDtcState` +
best-effort `makeDtcEmitter` that reuses `ensureStatesDir`/`writeStateAtomic` (C-5)
and writes `/run/eclipse-obd/states/dtc` atomically; a write failure is logged,
never raised, so the publish hook can never block the connection-edge read. The
DTC capture path **owns and calls** the emitter (the `_dtcEmitter` hook on the
orchestrator — its live injection follows the US-400/401 deferral pattern). The
state schema is design-spec §8: `mil` · `codes[]` (each with
`severity`/`severityCaveat`/`short`/`setAtTs`/`driveId`/`freezeFrame`/
`suggestedFix`/`fixProvenance`/`logged`/`syncAcked`/`clearEligible`) · `newSinceTs`
· `clearGate` · `sessionResetLock` · `ts`.

**Honest-instrument by construction.** The Pi never decides severity: a static
loader (`dtc_severity_table.py`) parses **Spool's SSOT**
(`offices/tuner/dsm-p1xxx-severity-table.md`) into the `{code → enrichment}` map
the emitter merges verbatim — engine P1xxx → `watch`, condition-dependent codes
carry a `severityCaveat` that **never auto-upgrades the tier** (R-1), auto-trans
P1xxx → `na` (quiet disposition). A code **absent** from the table degrades to
`severity: unknown` with whatever description python-obd supplied (empty → the
display shows "No description yet") — no fabricated severity or fix. `freezeFrame`
is always `null` (Mode 02 confirmed unsupported on MD326328; US-406 renders the
realtime fallback). The `clearGate` is the honest UI-side derivation from the
captured codes (severity_present → sync_pending → ok); **US-407 re-checks it
authoritatively at the privileged action path** — the UI is never the gate.

**Read-only endpoint.** `eclipse-states-http` already serves any safe file in the
states dir token-gated; the carousel polls `GET /dtc`. The endpoint is strictly
read-only — the only write route is `/service-control` (US-403), so `POST /dtc` →
404.

#### DTC takeover + STOP-red ribbon (US-405) [F-111 / design §5.1–5.2]

The dashboard-side consumers of the `dtc` state. The carousel polls `GET /dtc` in
the same 4 Hz tick as the cards and drives two surfaces, both pure functions in
`carousel.js` (node-tested) with thin DOM wiring:

**Full-screen takeover (`takeoverView` / `takeoverShouldShow`).** Fired on a
**new** code only. The `dtc` state is level-triggered (it always carries the
present codes), but the alarm must be **edge-triggered** — so the emitter stamps
`newSinceTs` when a new code appears and the display tracks the
last-acknowledged stamp: `takeoverShouldShow` compares them, so the same code
never re-takes-over, but a **newer** code (a different stamp) re-fires
(escalation, design D-3). One takeover at a time — the **highest-severity code is
the hero**, the rest fold into "+N more". The overlay is **severity-styled** (the
display maps a tier → color + directive + dismiss controls; it never classifies):
🔴 STOP = brand `--red` bg · "REDUCE LOAD · PULL OVER" · **Acknowledge only** (no
plain dismiss); 🟡 WATCH = amber · "DRIVE GENTLY · GET DIAGNOSED" · Dismiss; 🟢
MINOR = dark-green · "SAFE TO CLEAR ONCE LOGGED" · Dismiss. Every dismiss path
(incl. STOP's Acknowledge) **drops to the ribbon** — the driver always keeps view
control, never trapped full-screen while the road needs watching. `unknown`
(uncurated) gets the honest middle — a "GET DIAGNOSED" caution, never a false
"safe to clear" or a false "pull over".

**Persistent ribbon (`ribbonView`).** While any alert-eligible code is present, a
ribbon rides under the top bar on every card: `⚠ CHECK ENGINE · <hero code>
<desc> · +N more`. **R-2 (ribbon red ≠ brand red):** the ribbon shares cards with
brand-red chrome, so its STOP state uses the **brighter alert `--red-light`
(#F61D2D)** — distinct from brand `--red` (#E60012, used by the takeover bg) — plus
a leading ⚠ glyph and a subtle pulse, so it reads as an alarm and never as
decoration.

**`na` is a quiet disposition (design §4).** Auto-trans P1xxx on the manual F5M33
are dropped from `alertableCodes` — **no takeover, no ribbon**, and not counted in
"+N more". A missing/malformed `dtc` file → no alert (honest: absence of the state
= no active fault), never a fabricated code. The Mode-04 clear is US-407.

#### DTC Alerts card (Card 5) + detail (US-406) [F-111 / design §5.3–5.4]

The persistent home of the DTC state — a third carousel card (`data-state="dtc"`,
label **Alerts**) plus a per-code detail overlay. Both are pure functions in
`carousel.js` (node-tested) with thin DOM wiring; the Alerts card is polled in the
same 4 Hz tick as the other cards (the tick now fetches `GET /dtc` **once** and
shares it with the card render *and* the US-405 ribbon/takeover). The display maps
a Spool-classified tier → chip label + color + directive; **it never classifies.**

**Alerts card (`alertsCardView`).** Hero + list (design D-4). The **hero** is the
worst *alert-eligible* code (via `alertableCodes`, so `na` and unrecognized
severities are **never** a hero — S-12) with its tier directive; the **list**
(`dtcListSorted`) shows every code worst-first with **`na` sorted last** (design
§5.3, `DTC_LIST_RANK` gives `na` the lowest rank). A no-description code shows a
neutral `?` chip + "No description yet" (never blank — I-3). An empty `codes`
array is an honest **"No stored codes"** (never a fabricated green). A
missing/malformed file → the shell's `unavailable` (S-9). Every row + the hero are
≥40px tap targets that open the detail.

**Detail (`codeDetailView`).** Fixed skeleton: hero (chip + code + short) ·
severity directive band (🔴/🟡 only) · condition-dependent caveat **line** ·
status meta · freeze-frame-or-realtime fallback · severity-gated fix · log/sync
footer. Two render-safety invariants are **locked in the pure builders** (the SSOT,
so a buggy DOM layer can't violate them):

- **Severity-gated fix (`fixArea`, S-4/F-1 — load-bearing).** A 🔴/🟡 (or uncurated
  `unknown`) code's fix slot is **REPLACED** by a "diagnose, don't swap parts"
  directive — the raw `suggestedFix` is never rendered for it, **even when
  non-null**. Only a 🟢 MINOR code shows the actual fix + a **3-state trust badge**
  (`trustBadge`: `spool-validated` → ✓ Verified · Spool; `auto-unverified`/
  `sourced` → 👥 Community · unverified; `none`/absent → ⏳ Looking into it). A
  missing MINOR fix is honest text ("arrives on next sync"), never fabricated.
- **Caveat never upgrades the tier (S-13).** `severityCaveat` renders as a caveat
  line beneath the base chip; the display reads `severity` verbatim, so a P1300
  WATCH with a "🔴 if knock" caveat stays a **WATCH** chip.

**Freeze-frame fallback (`freezeFrameView`, S-5).** Mode 02 is confirmed
unsupported on MD326328, so `freezeFrame` is null and the default render is the
labeled realtime-context fallback ("no freeze frame captured (this ECU) — showing
context at fault time") — never blank. A grid renders only if a future
Mode-02-capable ECU supplies one. **`driveId` null → "key-on read"** (a US-404 KOEO
read), never a fabricated "Drive N" (A-9 cross-link). The takeover "View detail" +
a ribbon tap both navigate to the Alerts card and open the hero's detail. The
Mode-04 clear button + gate are US-407.

#### DTC Clear (Mode-04) path — the only vehicle-write (US-407) [F-111 / design §6, advisory §4]

The single DTC path that **writes to the ECU**. Mode 04 is **all-or-nothing**: it
wipes every stored + pending code, erases the freeze-frame, and resets emissions
readiness monitors in one shot — so the whole design is built around never
clearing a real fault's evidence and never being forced by a tampered UI. It
renders against **Spool's SSOT** (`offices/tuner/dtc-display-clear-safety-advisory.md`);
this story implements those semantics, it does not redefine them.

**The gate is re-checked at the privileged action path — never trusted from the
UI (S-10 / F-3, load-bearing).** `src/pi/splash/dtc_clear.py` is the authoritative
gate SSOT. `evaluateClearGate` **re-derives** the verdict from the raw captured
codes and deliberately **ignores** any precomputed `clearGate.enabled` in the
state: enabled only when **every stored (non-`na`) code is MINOR (green) AND
logged AND server-sync-acked**, and no code re-set this session. Any STOP/WATCH →
`severity_present`; an un-synced MINOR → `sync_pending` (capture-before-clear,
advisory §4c); a returned code (`sessionResetLock`) → `session_locked` ("don't
chase the light", §4d); nothing clearable → `no_codes`. This is the DTC analog of
US-403's action-path allow-list re-check in `service_control.py`.

**Three defense-in-depth layers (same shape as US-403's privilege path).**
1. **UI layer** — `carousel.js` `clearButtonView` mirrors the gate *for display*
   (the Clear button in the detail overlay is disabled with an honest reason
   label for a STOP/WATCH / un-synced / re-set code); a hard-confirm modal
   (`confirmClearText`) names the freeze-frame-erase + readiness-reset
   consequences (S-7). The button is convenience, not the gate.
2. **Action-path layer** — the unprivileged kiosk POSTs `/dtc-clear` (token-gated)
   to `eclipse-states-http`, which **re-reads its own `dtc` state** and calls
   `dtc_clear.performClear`. If the re-derived gate fails, the injected Mode-04
   runner is **never called** (403; no vehicle-write, no freeze-frame destroyed).
3. **Vehicle-write primitive** — `DtcClient.clearDtcs` issues Mode 04 (`CLEAR_DTC`)
   and then **immediately re-reads Mode 03(+07)** to *prove* the clear ("0 stored,
   0 pending, MIL off") rather than reporting a bare "command sent" (§4d), which
   also catches an **instant re-set**: a code present before AND after the wipe is
   flagged (`reSetCodes`) so US-407 locks Clear for the session.

**Honest unavailability + deferred live wiring.** `eclipse-states-http` runs as a
standalone service and holds **no** OBD connection, so `makeStatesHandler` takes
an injected `clearRunner` (owned by the connection holder — the orchestrator on
the Pi). When it is `None`, `POST /dtc-clear` returns an honest **503** rather than
fabricating a success. Wiring the live runner across the process boundary (the
orchestrator consuming the clear request on its OBD loop, then re-emitting the
`dtc` state with the updated `sessionResetLock`) is the same Pi-bench-deferred
integration as US-404's live `_dtcEmitter` injection; the gate, the Mode-04
primitive, and the endpoint mechanism are complete and unit-tested.

#### LTFT multi-drive trend card (Card 4) + `ltft-trend` emitter (US-420) [F-096]

The **LTFT Trend** card renders a long-term-fuel-trim trend across the last N
drives so the CIO can watch LTFT migrate toward 0 (healthy) vs drift beyond
±10%. It follows the same **SSOT / pure-consumer** carousel pattern as the
System Status / Battery Health / DTC cards: a Python emitter is the single
authoritative provider that **classifies** the drift; the JS card only maps the
verdict → colour, it never classifies.

**`ltft-trend` emitter (`src/pi/splash/ltft_trend_emitter.py`).**
`readLtftTrend()` aggregates per-drive avg/min/max of
`parameter_name='LONG_FUEL_TRIM_1'` (the single 4G63 bank — bank 2 is unlogged)
over `realtime_data`, `GROUP BY drive_id` oldest→newest, `WHERE
data_source='real' AND drive_id IS NOT NULL` (so replay/sim/fixture — and the
US-424 `'foreign'` rows — can never enter the tune trend, and NULL-drive noise
is excluded), `LEFT JOIN drive_summary` for the axis timestamp (NULL when a
drive has trims but no summary). `classifyLtftDrift()`: `|LTFT|≤5` ok, `≤10`
amber, `>10` down — thresholds grounded in
`offices/tuner/cards/safe-range-fuel-trims.md` (normal ±5, danger >±10).
`buildLtftTrendState()` is pure: per-drive levels + a headline verdict + a
migration direction (improving-toward-0 vs worsening, `TREND_EPSILON_PCT=0.5`
dead-band). **Honest-instrument**: below `MIN_DRIVES_FOR_TREND=2` the headline
level is forced to `'insufficient'` — a single in-band reading can never render
green. `makeLtftTrendEmitter()` is the same best-effort atomic
`ensureStatesDir`/`writeStateAtomic` (C-5) seam as the sibling emitters (write
failures logged, never raised).

**Render (`carousel.js`).** `ltftTrendView()` (pure) + `renderLtftTrendBody()`
paint a multi-drive bar row, each bar coloured by its **own** drift level so a
>±10% drive is visibly not-green. US-507 relocated the surface into the merged
Health card; **US-540-b returned it to a standalone "Fuel Trim" card**, reached
by the normal `data-state` dispatch through `sourceCardSpec()` /
`sourceCardView()` / `renderSourceCard()`. `healthCardView()` and
`renderHealthCard()` **no longer exist**. Across all three arrangements the
retitle is a LABEL change only -- the emitter, the thresholds, the classifier
and the insufficient guard are all untouched, so Spool's LTFT semantics are
preserved exactly. Defense-in-depth: the view re-forces `'insufficient'`
when `sufficient !== true`, so a mislabeled state can't paint green. As with the
other emitters, the runtime `emit()` wiring is owner/deploy-side (no `src` call
site yet), matching the shipped cards.

#### Visual token SSOT + the two-file mirror (US-510, Sprint 68 / V0.29.23) [Atlas Rule-10 2026-07-31]

`src/pi/ui/tokens.css` is the **visual SSOT** (Iris owns values; Atlas gates
additions under Rule-10). `dashboard.html` links **only `dashboard.css`**, so the
dist `:root` is a **runtime MIRROR** of the SSOT, not a second source: every
token is declared in both files and `tests/ui/test_dashboard_token_ssot.py` +
`test_dashboard_fidelity_pass.py` compare the VALUES. A value that exists in only
one file is drift by definition.

US-510 closed the TD-065/TD-067 residue and recorded three decisions worth
keeping:

1. **Promotion is zero-visual-change by construction.** `--bg #000000` /
   `--surface #111111` were dist-only literals; Atlas ruled them into the SSOT
   **at their shipped values**, making "a diff that moves a rendered pixel FAILS"
   the DoD gate. The same rule drove the takeover's deep gradient edges
   (`--amber-deep` / `--green-deep` / `--green-deepest`) to **named tokens
   holding the existing literals** rather than a derived `color-mix()`: a
   computed mix would produce a *different* colour, which is a restyle wearing a
   tokenization's clothes.
2. **A destructive ACTION is a different axis from an alarm STATE.**
   `--destructive #C62828` + `--destructive-border #7F1D1D` dress the Mode-04
   clear-confirm and **MUST stay distinct from `--critical-red #D32F2F`**.
   Aliasing them would "tokenize" the surface while destroying the distinction
   the split exists for — the operator could no longer tell "you are about to
   erase your codes" from "pull over". With these landed the brand reds
   (`--red*`) have **zero consumers** on the dashboard; they stay declared
   because the mirror carries the tier, not because anything paints it.
3. **Type is a token tier too.** `--font-mono` (all data/values — the tabular
   instrument vernacular, deliberately unchanged) and `--font-display` (brand
   moments ONLY: the `ECLIPSE OBD-II` wordmark + card titles). US-510 landed the
   token + the bindings; the woff2 payload followed as a fast-follow (below).

**BL-027 CLOSED (fast-follow, 2026-08-01) — the brand face is an EMBEDDED
asset, and the mirror rule extends to it.** The face is an OFL-licensed
**Oswald** subset (A–Z / 0–9 / space / hyphen, weight 600, 2,896 B) inlined as a
CSP-safe `@font-face` **base64 data-URI**. Four decisions worth keeping:

- **The mirror is load-bearing for the face, not just for values.** The
  `@font-face` is declared in **both** `tokens.css` and `dashboard.css`, because
  `dashboard.html` links only the latter. An SSOT-only drop leaves the panel on a
  fallback face **with a fully green suite** — the two-correct-halves-that-stopped-
  agreeing shape (US-494/US-499). `tests/ui/test_dashboard_brand_font_payload.py`
  asserts the kit sheet carries the face and that both payloads are identical.
- **Host-only faces left the stack.** The stack is `"Oswald", "Arial Narrow",
  system-ui, sans-serif`. The previously-locked **Bahnschrift is Microsoft-
  proprietary, absent from Pi OS and not redistributable** — naming it never put
  it on the panel, which is why BL-027 existed. Leading with any host-only face
  means a dev box and the Pi render *different* brand faces; the embedded face is
  the one face, so the stack lead is pinned **against the embedded family**, not
  a hardcoded name.
- **A single-weight subset constrains its consumers.** The subset carries weight
  600 only, so every rule binding `--font-display` must request 600 — a 700
  request yields a **synthesised** bold, which on a condensed face reads as a
  rendering fault. Pinned over the SET of bound rules, and the brand copy is
  pinned to stay inside the cut glyph range (a stray `·` falls back *per glyph*,
  splitting a title across two faces mid-word).
- **The licence ships with the artifact.** SIL OFL 1.1 travels with the font, and
  the font now travels *inside* the stylesheet — so `OFL.txt` is in the kit **and
  vouched in `deploy-pi.sh`'s asset list**, since `refresh_asset_dir` prunes
  unvouched files (an unvouched licence looks compliant in the repo while
  `/opt/dashboard` ships the face bare).

The no-CDN rule is pinned independently of the asset and now covers the `src`
descriptor itself: the plausible future "fix" when someone thinks the face is
broken is a Google Fonts `@import`, which works everywhere except in the car.

Remaining deliberate exception, enumerated rather than silent: `#fff`/`#000` on
a tiered chip/ribbon/takeover are **contrast pairs** chosen against that tier's
fill, not palette entries. Naming them means inventing `--on-amber`/`--on-critical`
(Iris's design call + an Atlas token addition) — routed as **TD-071**, which also
carries SSOT promotion of the three `--*-deep` edge tokens.

### Release Versioning + Deploy Records (US-241, B-047 US-A)

Pre-US-241 every deploy was anonymous: a `git pull` + service restart with no
durable record of what shipped or when. CIO's 2026-04-29 directive introduced
a SemVer-shaped version string and a structured release record so B-047's Pi
self-update path (US-B/C/D in Sprint 20+) has a stable comparison key, and
so the operator can answer "what's currently running on the server?" without
reading git history.

**Versioning scheme**: `V<major>.<minor>.<patch>`. Capital `V` is required.
Starting version is **`V0.18.0`** (post-Sprint-18, pre-stable -- we have not
shipped a stable V1.0.0 yet). Bump conventions:

| Bump kind | When | Example |
|-----------|------|---------|
| **major** | Breaking schema/API change | `V0.18.0` → `V1.0.0` |
| **minor** | Sprint completes, new feature lands | `V0.18.0` → `V0.19.0` |
| **patch** | Bug fix / hotfix between sprints | `V0.18.0` → `V0.18.1` |

`major` resets minor + patch to 0; `minor` resets patch to 0.

**Canonical version file**: `deploy/RELEASE_VERSION` at repo root (committed):

```json
{"version": "V0.18.0", "description": "Sprint 18 ops-hardening shipped + Sprint 19 runtime fixes loading"}
```

`description` is hard-capped at 400 characters. PM owns the bump at sprint
close; deploy scripts NEVER bump it themselves.

**Per-tier deploy record**: each `deploy-pi.sh` / `deploy-server.sh` run
stamps a JSON record onto the deployed tier:

| Tier | Path |
|------|------|
| Pi   | `/home/mcornelison/Projects/Eclipse-01/.deploy-version` |
| Server | `/home/mcornelison/obd2-server/.deploy-version` |

Record shape: `{version, releasedAt, gitHash, description}`. `releasedAt` is
UTC ISO-8601 with `T` separator + `Z` suffix (e.g.,
`2026-04-30T14:32:00Z`). `gitHash` is the short git hash of the deployed
tree (caller runs `git rev-parse --short HEAD`). Idempotent: re-running with
the same `version` + `gitHash` overwrites the tier file with a refreshed
`releasedAt` so the tier always knows when it was LAST deployed.

**Helpers + CLI** (`scripts/version_helpers.py`): single source of truth
for the JSON shape. Public API:

| Function | Purpose |
|----------|---------|
| `parseVersion(s)` | Returns `(major, minor, patch)`; raises `ValueError` on bad shape |
| `bumpVersion(version, kind)` | Returns bumped version string; `kind` ∈ `{major, minor, patch}` |
| `validateRelease(record)` | Returns `True` iff the record matches the {version, releasedAt, gitHash, description ≤400} contract |
| `readDeployVersion(path)` | Returns parsed record or `None` (missing file, malformed, or invalid shape) |
| `composeReleaseRecord(versionFile, gitHash, releasedAt=None)` | Composes a record from the inputs; raises `ValueError` on bad version-file contents |

The deploy scripts shell out to the `compose-record` CLI so the JSON-
composition lives in one testable Python module rather than in two bash
heredocs:

```bash
python scripts/version_helpers.py compose-record \
    --version-file deploy/RELEASE_VERSION \
    --git-hash $(git rev-parse --short HEAD)
# stdout: {"version": "V0.18.0", "releasedAt": "...", "gitHash": "...", "description": "..."}
```

**Tier query**: `readDeployVersion(path)` returns the active record on each
tier. B-047 US-B's `/api/v1/version` endpoint will read the server-side file;
US-C's Pi self-update path will read the Pi-side file before deciding whether
to pull a newer version. The shape is **stable from US-A onward** -- US-B/C/D
must NOT be blocked on US-A changing the contract.

**Why deploy writes the stamp, not git**: a stamped tier file survives even
a partial deploy where the git tree isn't pushed (e.g., a `--restart-only`
run). The git short-hash captured in the record provides forensic
traceability without coupling tier-state to git availability on the Pi.

### Pi Self-Update Lifecycle (B-047 US-A through US-E, Sprints 19-21)

The Pi self-update path is the runtime consumer of the deploy versioning +
release-record contract above. It is a two-process pipeline glued by a
single marker file. Both classes are in `src/pi/update/` and are wired
into the orchestrator's runLoop on configurable intervals.

```
┌───────────────────────┐                ┌───────────────────────┐
│ UpdateChecker (US-247)│                │ UpdateApplier (US-248)│
│                       │                │                       │
│ check_for_updates():  │                │ apply():              │
│                       │                │                       │
│ ┌── drive-state? ──┐  │                │ ┌── marker exists? ─┐ │
│ ├─ disabled?       │  │                │ ├─ marker valid?    │ │
│ ├─ API key set?    │  │                │ ├─ drive-state?     │ │
│ ├─ local .deploy   │  │                │ ├─ power=BATTERY?   │ │
│ │  -version OK?    │  │                │ ├─ recent OBD<5min? │ │
│ ├─ HTTP GET        │  │                │ ├─ applyEnabled?    │ │
│ │  /api/v1/release │  │   marker.json  │ ├─ git rev-parse    │ │
│ │  /current        │  │ ──────────►    │ ├─ git fetch        │ │
│ ├─ validateRelease │  │ {target_version│ ├─ git checkout     │ │
│ ├─ parseVersion    │  │  server_url    │ ├─ deploy-pi.sh     │ │
│ │  comparison      │  │  rationale     │ │  --dry-run        │ │
│ └─ NEWER → write   │  │  checked_at}   │ ├─ deploy-pi.sh     │ │
│    marker          │  │                │ ├─ readDeployVersion│ │
│                    │  │                │ │  verify == target │ │
│                    │  │                │ └─ clear marker     │ │
│                    │  │                │    OR rollback +    │ │
│                    │  │                │    clear marker     │ │
└───────────────────────┘                └───────────────────────┘
        │                                          │
        ▼                                          ▼
   no real subprocess                        every external command
   (HTTP only via                            via injected
   urllib.request.urlopen,                   subprocessRun callable
   injected as httpOpener)                   (default subprocess.run)
```

**Marker file is the only inter-step channel.** US-247 writes
`{target_version, server_url, rationale, checked_at}`; US-248 reads
`target_version`. The marker is cleared on EVERY terminal outcome that
touched the deploy path (`SUCCESS`, `ROLLBACK_OK`, `ROLLBACK_FAILED`,
`MARKER_INVALID`) so a poisoned target version cannot perma-trigger.
A deferred-apply marker (drive started before apply could fire) survives
the drive intentionally — the next post-drive tick resumes from that state.

**Safety gate ordering** (US-248): drive-state → power-source → recent-OBD
→ applyEnabled. Drive-state is most operationally sacred (mid-drive apply
could brick the Pi); power-source guards against dirty shutdown if the UPS
is on battery; recent-OBD-activity is the weakest gate (5-minute threshold)
but protects against the "engine just turned on but drive_detector hasn't
fired yet" window. `applyEnabled=False` is placed AFTER safety gates so
the operator log shows "would have been safe to apply" rather than hiding
under the disabled flag.

**Production rollout gate**: `applyEnabled` defaults to **False** (CIO
opt-in). Even when enabled, the four safety gates and the dry-run +
post-deploy verify steps must all pass before the marker is cleared.
Failure at any deploy phase rolls back to the priorRef (`git rev-parse
HEAD` captured before any state-mutating subprocess) and restarts the
service.

**E2E integration drill (US-258, B-047 US-E, Sprint 21)**: 7-test drill
in `tests/pi/integration/test_self_update_e2e.py` exercises the real
`UpdateChecker` + `UpdateApplier` classes across the marker-file handoff.
Mocks live ONLY at the HTTP boundary (`UpdateChecker(httpOpener=...)`)
and the subprocess boundary (`UpdateApplier(subprocessRun=...)`); no
internal-state monkeypatching. The fake subprocess runner simulates
`deploy-pi.sh`'s `.deploy-version` stamp side-effect when the full
deploy command runs (NOT `--dry-run`), so the post-deploy verify step
reads the same shape it would on a real Pi. Coverage:

| Test class | Scenario | Asserts |
|------------|----------|---------|
| `TestSelfUpdateE2EHappyPath` | server NEWER → check → apply → verify | marker written → cleared; phase ordering (rev-parse → fetch → checkout → dry-run → deploy); `.deploy-version` stamped to target; outcome=`SUCCESS` |
| `TestSelfUpdateE2EDeployFailureTriggersRollback` (×2) | full deploy fails / dry-run fails | rollback chain fires (`git checkout <priorRef>` + `systemctl restart eclipse-obd`); marker cleared; outcome=`DEPLOY_FAILED` / `DRY_RUN_FAILED`; full deploy NEVER runs after dry-run failure |
| `TestSelfUpdateE2EDriveStateGate` | drive-in-progress (with stale marker) | check skips HTTP request; apply skips ALL subprocesses; deferred-apply marker survives intact |
| `TestSelfUpdateE2EUpToDate` | server SAME version | no marker on disk; apply spawns zero subprocesses; outcome=`NO_MARKER` |
| `TestSelfUpdateE2EWireShape` | invariant audit | `X-API-Key` header + `GET /api/v1/release/current` flow through the integrated path |

This drill is the **integration-readiness gate** before flipping
`pi.update.applyEnabled=true` in production. Unit tests cover each class
in isolation (`tests/pi/update/test_update_checker.py`,
`test_update_applier.py`); the e2e drill catches gaps at the marker-
handoff seam that unit tests cannot reach.

### Wake-on-Power — Pi 5 + X1209-HAT topology (SS-T9, F-6 closed)

`POWER_OFF_ON_HALT=1` is the **locked setting** for this system (CIO
decision 2026-05-18), enforced by
`deploy/enforce-eeprom-power-off-on-halt.sh` (SS-T8 corrects the script to
enforce `1`; the prior force-`0` was a defect that reverted the correct
setting every deploy).

**Rationale (topology-specific).** With the X1209 UPS HAT holding the Pi's
5 V rail up off its battery, `=0` leaves the PMIC active after `poweroff`
and the PMIC **never sees a power-cycle edge** when external power returns
→ no unattended auto-boot (this is Finding B, observed empirically). `=1`
powers the PMIC fully off so a USB-C power-return is a real boot event.

**The previously documented "`=0` ⇒ auto-boots ✅ / `=1` ⇒ needs button ❌"
table was FALSE for this topology** (it described a bare Pi 5 with no HAT)
and was the documentation root of the V0.27.x chain blocker (finding F-6).
It has been removed, not patched.

**Empirically gated (stated honestly, do not assert beyond evidence).** The
exact wake mechanism at `=1` — whether the X1209 presents a true Pi 5 V rail
power-cycle on external-power-return — is confirmed by the **Atlas-gated
Bench Check B (2026-05-18)** at **1 cycle**, and the full **IRL acceptance
gate** is 5 consecutive clean unattended shutdown→restore cycles. Until that
gate passes, treat unattended in-car recovery as *designed-for and pending
empirical confirmation*, never as "solved." The empirical bench/IRL result
is the sole arbiter; no spec text or vendor doc overrides it.

**Enforcement: every deploy verifies and re-asserts.** `deploy-pi.sh` runs
`step_enforce_eeprom_power_off_on_halt` on every routine deploy and
`--init`, which SSH-invokes `deploy/enforce-eeprom-power-off-on-halt.sh` on
the Pi:

```
deploy-pi.sh
  └── step_enforce_eeprom_power_off_on_halt
        └── ssh Pi: sudo bash deploy/enforce-eeprom-power-off-on-halt.sh
              ├── reads `rpi-eeprom-config` output
              ├── line absent      → rewrite to explicit =1 (default 0 wrong on HAT)
              ├── value = 1        → no-op (already correct)
              ├── value ≠ 1        → rewrite via `rpi-eeprom-config --apply`
              └── tool missing/fails → exit non-zero, halt deploy
```

The enforcement script is idempotent — back-to-back runs converge with no
EEPROM writes after the first. The deploy script accepts the standard
`--dry-run` flag (prints what would be done without touching the Pi).

**Test fidelity.** `tests/deploy/test_eeprom_power_off_on_halt.sh` PATH-mocks
`rpi-eeprom-config` across 7 scenarios (absent / `=0` / `=1` / `=2` / tool
missing / apply fails / two-run idempotency drill — all converging on `=1`
post-SS-T8). The mock seam is the `RPI_EEPROM_CONFIG` env var the production
script reads first (falls back to a plain `rpi-eeprom-config` PATH lookup).
The pytest wrapper `tests/deploy/test_deploy_pi_eeprom_config.py` runs the
bash test in the fast suite so a regression in either the production script
or the mock harness shows up alongside other deploy regressions.

**What is still pending (IRL, out of code scope).** The 5-cycle IRL
acceptance drill — graceful `systemctl poweroff` → external power off →
wait → external power on → unattended Pi boot, **five times in a row** — is
the load-bearing acceptance gate Atlas + the CIO ratify before chain merge.
Code-side this section guarantees the EEPROM setting lands correctly on
every deploy; whether the wake actually fires in the car is the IRL drill's
question, not this document's.

---

## 12. Simulator Architecture

### Overview

The simulator subsystem provides hardware-free testing capabilities, enabling development and testing without physical OBD-II hardware.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Simulator Subsystem                                 │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Configuration Layer                            │  │
│  │   simulator.enabled  │  profilePath  │  scenarioPath  │  failures│  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Core Components                                │  │
│  │  SimulatedObdConnection  │  SensorSimulator  │  VehicleProfile   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Scenario System                                │  │
│  │  DriveScenario  │  DriveScenarioRunner  │  DrivePhase            │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Testing Support                                │  │
│  │  FailureInjector  │  SimulatedVinDecoder  │  SimulatorCli        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Purpose |
|-----------|---------|
| `SimulatedObdConnection` | Drop-in replacement for ObdConnection, same interface |
| `SensorSimulator` | Physics-based sensor value generation with noise |
| `VehicleProfile` | Vehicle characteristics (RPM limits, temperatures, etc.) |
| `DriveScenario` | Predefined sequences of drive phases |
| `DriveScenarioRunner` | Executes scenarios with smooth transitions |
| `FailureInjector` | Injects failures for error handling testing |
| `SimulatedVinDecoder` | Profile-based VIN decoding without NHTSA API |
| `SimulatorCli` | Keyboard commands for runtime control |

### Activation

Simulator mode is enabled via:
1. CLI flag: `python src/main.py --simulate`
2. Config: `simulator.enabled: true` in obd_config.json

### Built-in Scenarios

Located in `src/obd/simulator/scenarios/`:
- `cold_start.json` - Engine start and warmup cycle
- `city_driving.json` - Stop-and-go city driving (3 loops)
- `highway_cruise.json` - On-ramp acceleration and steady cruise
- `full_cycle.json` - Complete drive combining all phases

### Vehicle Profiles

Located in `src/obd/simulator/profiles/`:
- `default.json` - Generic 4-cylinder gasoline vehicle
- `eclipse_gst.json` - 1998 Mitsubishi Eclipse GST (project target)

---

## 13. Hardware Module Architecture

### Overview

The `src/hardware/` package provides Raspberry Pi hardware integration with graceful fallback on non-Pi systems.

### Components

| Component | Purpose |
|-----------|---------|
| `HardwareManager` | Central coordinator for all hardware modules |
| `UpsMonitor` | I2C telemetry from Geekworm X1209 UPS HAT |
| `ShutdownHandler` | Graceful shutdown on power loss or low battery |
| `GpioButton` | Physical shutdown button via GPIO |
| `StatusDisplay` | OSOYOO 3.5" HDMI touch display (480x320) |
| `TelemetryLogger` | System telemetry logging to rotating files |
| `I2cClient` | Low-level I2C communication with retry logic |

### Initialization Order

Hardware components must be initialized in specific order within the ApplicationOrchestrator:

```
1. Display (console/minimal) - First, provides fallback output
2. HardwareManager        - After display, before data components
3. Data components        - OBD connection, database, etc.
```

### Shutdown Order

Shutdown in reverse order:

```
1. Data components        - Stop data collection first
2. HardwareManager        - May use display for final status
3. Display                - Last, after all output complete
```

### Component Wiring

HardwareManager wires components via callbacks:

```
UpsMonitor.onPowerSourceChange -> ShutdownHandler (schedules shutdown)
UpsMonitor.telemetry -> StatusDisplay (updates battery/power display)
GpioButton.onLongPress -> ShutdownHandler._executeShutdown (manual shutdown)
UpsMonitor -> TelemetryLogger (battery data for logging — see TelemetryLogger Data Trail below)
```

### TelemetryLogger Data Trail

TelemetryLogger is **LIVE on Pi production** (US-251 audit, Sprint 20, 2026-05-01). Activation chain:

```
core.runLoop (core.py:726)
  -> _startHardwareManager (lifecycle.py:823)
  -> HardwareManager.start (hardware_manager.py:234)
     -> _initializeTelemetryLogger        (creates instance)
     -> _wireComponents                   (calls setUpsMonitor with the live UpsMonitor)
     -> _startComponents                  (calls TelemetryLogger.start -> daemon thread)
```

The daemon thread polls `UpsMonitor.getTelemetry()` every `telemetryLogInterval` seconds (default 10s) and emits a JSON line to a `RotatingFileHandler`.

| Property | Default value |
|----------|---------------|
| Output path | `/var/log/carpi/telemetry.log` (configurable via `HardwareManager(telemetryLogPath=...)`) |
| Rotation | 100 MB max, 7 backup files (`telemetry.log.1` … `telemetry.log.7`) |
| Format | One JSON object per line (`JsonFormatter`) |
| Cadence | 10 s |
| Activation gate | `isRaspberryPi() AND pi.hardware.enabled (default True)` — Pi-only by design |

JSON record shape (`TelemetryLogger.getTelemetry`):

```json
{
  "timestamp": "2026-05-01T13:42:18.123456Z",
  "power_source": "external|battery|unknown",
  "battery_v": 4.118,
  "battery_pct": 87,
  "battery_charge_rate_pct_per_hr": -2.5,
  "ext5v_v": 4.972,
  "cpu_temp": 47.5,
  "disk_free_mb": 38214
}
```

`battery_v`, `battery_pct`, `charge_rate`, and `ext5v_v` come from `UpsMonitor.getTelemetry()`; `cpu_temp` reads `/sys/class/thermal/thermal_zone0/temp`; `disk_free_mb` reads `shutil.disk_usage('/')`. UPS errors are spam-suppressed: first failure logs at WARNING, second at WARNING (with "suppressing further warnings"), all subsequent at DEBUG, until a successful read resets the counter.

**Drain-event forensic value (TD-033 closure).** During an AC→BATTERY transition, this file is the canonical 10-second-resolution record of `power_source`, `battery_v`, and `charge_rate` outside the database. Operators inspecting a drain post-mortem on the Pi:

```bash
ssh chi-eclipse-01 'tail -n 200 /var/log/carpi/telemetry.log | jq .'
ssh chi-eclipse-01 'zcat /var/log/carpi/telemetry.log.1 | jq "select(.power_source==\"battery\")"'
```

This complements `power_log` (post-US-243, every poll, schema-typed) and `battery_health_log` (one row per drain event). Where the DB tables are queryable but require a working SQLite/sync path, this file survives a database lock or sync outage.

### Non-Pi Fallback

All hardware modules check `isRaspberryPi()` and handle unavailability gracefully:
- Log warning message
- Set `isAvailable = False`
- Return safe defaults or skip operations
- Never crash on non-Pi systems

---

## 14. VIN Decoder

### Overview

The VIN decoder queries the NHTSA vPIC API to resolve vehicle information from the 17-character VIN.

| Property | Value |
|----------|-------|
| API endpoint | `https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json` |
| Timeout | 30s (configurable via `vinDecoder.apiTimeoutSeconds`) |
| Retry | 1 retry on transient failures |
| Caching | Results stored in `vehicle_info` table. Subsequent lookups return cached data (`fromCache=True`). |

### VIN Validation (ISO 3779)

- Must be exactly 17 characters
- Cannot contain I, O, or Q
- Invalid VINs return `success=False` without API call

### Known Behaviors

- **Pre-1996 VINs**: NHTSA returns ErrorCode 8 ("No detailed data available"). Make/year may be present but model, engine, transmission, etc. will be NULL. This is expected, not a bug.
- **TransmissionStyle**: Frequently empty in NHTSA data even for modern vehicles. Do not treat NULL transmission as an error.
- **Field mapping**: Make, Model, ModelYear, EngineModel, FuelTypePrimary, TransmissionStyle, DriveType, BodyClass, PlantCity, PlantCountry are stored in `vehicle_info` columns.

---

## 15. Component Initialization Order

The ApplicationOrchestrator initializes 12 components in strict dependency order (~2s startup):

```
Database → ProfileManager → Connection → VinDecoder → DisplayManager →
HardwareManager → StatisticsEngine → DriveDetector → AlertManager →
DataLogger → ProfileSwitcher → BackupManager
```

Shutdown is reverse order (~0.1s).

### Data Flow Through Components

| Event | Flow |
|-------|------|
| Reading | DataLogger → Orchestrator._handleReading → DisplayManager + DriveDetector + AlertManager |
| Drive start/end | DriveDetector → Orchestrator._handleDriveStart/End → DisplayManager + external callback |
| Alert | AlertManager → Orchestrator._handleAlert → DisplayManager + HardwareManager + external |
| Analysis | StatisticsEngine → Orchestrator._handleAnalysisComplete → DisplayManager + external |
| Profile change | ProfileSwitcher → Orchestrator._handleProfileChange → AlertManager + DataLogger |

---

## 16. Hardware Graceful Degradation

When hardware is absent, the system degrades gracefully without crashing:

| Component | Absent Behavior |
|-----------|----------------|
| **UPS (MAX17048 fuel gauge at 0x36)** | UpsMonitor logs first failure as WARNING, backs off polling interval from 5s to 60s after 3rd failure, logs subsequent failures at DEBUG. No crash. |
| **GPIO button** | One-time ERROR logged (`Cannot determine SOC peripheral base address`), button feature disabled. Needs `lgpio` package for Pi 5. No crash. |
| **HDMI display (no X11)** | StatusDisplay logs first GL context error, suppresses repeats at DEBUG level. Falls back to headless mode. No crash. |
| **Bluetooth dongle** | Connection manager handles via configurable retry with exponential backoff. |
| **Ollama (remote down)** | AiAnalyzer returns gracefully with error message. Post-drive workflow completes without AI analysis. |

All hardware modules check `isRaspberryPi()` and set `isAvailable = False` when hardware is not detected.

---

## 17. ECMLink Data Architecture (Phase 2)

> Moved to **`specs/arch/phase2-data-architecture.md`** (2026-06-01) — the
> Phase-2 ECMLink design (15 priority parameters, sample-rate tiers, the
> `ecmlink_*` tables, ingestion interface). Phase 2 is not yet implemented;
> extracted to keep this spec focused on the live system.

## 18. Data Volume Architecture (Phase 2)

> Moved to **`specs/arch/phase2-data-architecture.md`** (2026-06-01) — the
> Phase-1-vs-Phase-2 volume model, retention, MariaDB partitioning, and sync
> estimates.

---

## 19. Future Considerations

### Planned Enhancements

- [ ] Custom PID support for turbo boost monitoring
- [ ] Web dashboard for remote monitoring
- [ ] Mobile app integration
- [ ] GPS tracking module

### Technical Debt

- [ ] Async OBD-II polling for better performance
- [ ] Connection pooling for database writes
- [ ] Display rendering optimization

---

## 20. Modification History

> The full per-change history moved to
> **`specs/arch/architecture-changelog.md`** (2026-06-01) — it grew large and is
> rarely needed inline. **Append new architecture-change entries there** (newest
> first); keep this section as a pointer.
