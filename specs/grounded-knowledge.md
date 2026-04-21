# Grounded Knowledge Sources

Authoritative, fact-based sources for the Eclipse OBD-II Performance Monitoring System. All thresholds, ranges, technical specs, and community guidance referenced in this project MUST trace back to one of these sources, real vehicle data, or explicit CIO input (see PM Rule 7 in `pm/projectManager.md`).

---

## Authoritative Sources

### 1. DSMTuners Community
- **URL**: https://www.dsmtuners.com/
- **What it is**: The primary online community for Diamond Star Motors (DSM) vehicles — Mitsubishi Eclipse, Eagle Talon, Plymouth Laser (1989-1999). Forum-based knowledge with decades of accumulated tuning experience.
- **What we use it for**:
  - Safe operating ranges (coolant 190-210F, boost ~12 psi stock, AFR 11.0-11.8 WOT, knock count 0 ideal)
  - 2G DSM-specific OBD-II quirks and limitations
  - Community consensus on monitoring approaches ("OBDII loggers suck on 2G's" but adequate for health monitoring)
  - Mod compatibility and tuning advice
  - PiLink concept validation (community member's Pi-based OBD-II logger)
- **Reliability note**: High volume of posts — look for common success patterns, not one-off advice. Cross-reference across multiple threads.
- **Referenced in**: `specs/obd2-research.md` (Sections 5, 7, 8, 10)

### 2. OBDLink LX (ScanTool.net)
- **URL**: https://www.obdlink.com/products/obdlink-lx/
- **What it is**: Official product page for the OBDLink LX Bluetooth OBD-II adapter — the hardware dongle used in this project.
- **What we use it for**:
  - Hardware specifications and protocol support
  - Firmware version reference (current: 5.6.19)
  - Bluetooth connectivity specs (MAC: `00:04:3E:85:0D:FB`, Serial: 115510683434)
  - Supported OBD-II protocols (ISO 9141-2 for our 1998 Eclipse)
  - ELM327-compatible AT command set
- **Reliability note**: Manufacturer source — authoritative for hardware specs. Community forums supplement with real-world performance data.
- **Referenced in**: `specs/architecture.md` (External Dependencies), `specs/glossary.md`, `specs/OBDLink-LX-Info.txt`

### 3. ECMLink V3 (ECMTuning)
- **URL**: https://ecmlink.com/
- **What it is**: Official site for ECMLink V3 — the industry-standard programmable ECU tuning software for 1990-1999 DSM vehicles. Made by ECMTuning.
- **What we use it for**:
  - Phase 2 integration planning (after programmable ECU installation)
  - Understanding MUT protocol (proprietary Mitsubishi, 15,625 baud — 10x faster than OBD-II)
  - Available tuning parameters: fuel maps, timing maps, airflow tables, boost control
  - Datalogging capabilities (1000+ samples/sec vs OBD-II's ~4-5 PIDs/sec)
  - Wideband O2 integration, speed density mode, GM MAF translation
  - Data export format (Excel-compatible, copy-paste)
- **Reliability note**: Manufacturer source — authoritative for ECMLink capabilities and requirements. CIO owns ECMLink V3 (not yet installed).
- **Referenced in**: `pm/projectManager.md` (Project Vision, ECMLink V3 Context), `pm/backlog/B-025.md`, `specs/obd2-research.md` (Section 12)

---

## Vehicle Facts

| Fact | Value | Source |
|------|-------|--------|
| Vehicle | 1998 Mitsubishi Eclipse GST (2G DSM) | CIO |
| VIN | `4A3AK54F8WE122916` | CIO (Eclipse 1998 Projects spreadsheet) |
| Engine | 4G63 turbocharged | CIO / DSMTuners |
| OBD-II Protocol | ISO 9141-2 (K-Line, 10,400 bps) | OBD-II spec + DSMTuners |
| Max polling rate | ~4-5 PIDs/sec via Bluetooth | Research (specs/obd2-research.md) |
| Core PIDs (Phase 1) | STFT (0x06), Coolant (0x05), RPM (0x0C), Timing (0x0E), Load (0x04) | Research + CIO approval |
| Current ECU | Stock with modified EPROM | CIO |
| Planned ECU | ECMLink V3 (owned, not installed) | CIO |
| OBD Dongle | OBDLink LX BT, MAC `00:04:3E:85:0D:FB`, FW 5.6.19 | CIO hardware |
| Installed bolt-on mods | Cold air intake, BOV, fuel pressure regulator, fuel lines, oil catch can, coilovers, engine/trans mounts | CIO (Eclipse 1998 Projects spreadsheet) |

---

## Safe Operating Ranges (Community-Sourced)

Source: DSMTuners community consensus, compiled in `specs/obd2-research.md` Section 7.

| Parameter | Safe Range | Alert Threshold | Notes |
|-----------|-----------|-----------------|-------|
| Coolant Temp | 190-210°F | >220°F | Stock thermostat opens at 190°F |
| Boost (stock turbo) | ~12 psi | >15 psi on stock | Stock wastegate actuator limit |
| AFR at WOT | 11.0-11.8:1 | >12.5:1 under boost (lean danger) | Rich is safe, lean kills engines |
| Knock count | 0 | >0 sustained | Any knock is bad; transient single counts can be noise |
| Oil pressure | Varies by RPM | Low at idle is concern | No OBD-II PID on stock ECU; future with ECMLink |

**Important**: These ranges are community-sourced baselines for a stock-turbo 2G DSM. The refinement with real vehicle data has begun — see **Real Vehicle Data** section below (Session 23 first-light capture, 2026-04-19).

---

## Real Vehicle Data

Authoritative empirical observations from this specific Eclipse. These values win over community baselines when they disagree (PM Rule 7 — real vehicle data beats community consensus). Append-only, timestamped.

### PID Support — Empirically Confirmed (Session 23, 2026-04-19)

**Confirmed SUPPORTED** on this 2G ECU (responded correctly under python-obd query):

| PID | Name | Authority |
|-----|------|-----------|
| 0x04 | Calculated Engine Load | Session 23 live capture |
| 0x05 | Engine Coolant Temperature | Session 23 live capture |
| 0x06 | Short-Term Fuel Trim (B1) | Session 23 live capture |
| 0x07 | Long-Term Fuel Trim (B1) | Session 23 live capture |
| 0x0C | Engine RPM | Session 23 live capture |
| 0x0D | Vehicle Speed | Session 23 live capture |
| 0x0E | Timing Advance | Session 23 live capture |
| 0x0F | Intake Air Temperature | Session 23 live capture |
| 0x10 | MAF Air Flow Rate | Session 23 live capture |
| 0x11 | Throttle Position | Session 23 live capture |
| 0x14 | O2 Sensor B1S1 (upstream narrowband) | Session 23 live capture |

**Confirmed UNSUPPORTED** on this 2G ECU (did not respond or returned no-data):

| PID | Name | Workaround |
|-----|------|-----------|
| 0x0A | Fuel Pressure | None via OBD-II. ECMLink or aftermarket sensor in future phases. |
| 0x0B | Intake Manifold Pressure (MAP) | None via OBD-II. Aftermarket 3-bar MAP (GM) or ECMLink in Phase 2. |
| 0x42 | Control Module Voltage | **Use ELM327 `ATRV` / python-obd `ELM_VOLTAGE`** — adapter-level query, not a PID. See note below. |

### Battery Voltage — NOT a PID on this car

PID 0x42 is unsupported on this 2G ECU. The battery voltage source for the primary display and all voltage alerts is the **ELM327 adapter's `ATRV` command** (accessed in python-obd as `obd.commands.ELM_VOLTAGE`). This is an adapter function, not an OBD-II Mode 01 PID — it measures voltage directly at the OBD-II port's pin 16 and is independent of ECU bandwidth. All code and tests that reference battery voltage must use this path.

### Battery Voltage via ELM_VOLTAGE (2G workaround) — Thresholds

Sprint 14 US-199 promoted `BATTERY_V` to a first-class parameter_name polled from ELM_VOLTAGE (tier 3, ~0.1 Hz). Thresholds apply to the *battery voltage as seen at the OBD-II connector while the ECU is powered*; they match Spool's Phase 1 tuning spec (`offices/pm/inbox/2026-04-10-from-spool-system-tuning-specifications.md` §Battery Voltage, locked source of truth per PM Rule 7).

| Level | Range | Action |
|-------|-------|--------|
| Normal | 13.5-14.5V (engine running) | Charging system healthy |
| Caution | 12.5-13.5V OR 14.5-14.8V | Low = weak alternator. High = voltage regulator starting to fail. |
| Danger | <12.0V OR >15.0V | **Low = charging failure, engine may stall. High = regulator failed, will cook battery and electronics.** |

Config path: `pi.tieredThresholds.batteryVoltage` in `config.json`. Consumers must read from config — do not hard-code thresholds. `BATTERY_V` rows carry `unit='V'` and are independent of the K-line bandwidth envelope (ELM327 pin-16 read is an adapter-local operation).

### Real-World K-Line Throughput (Session 23)

| Metric | Theoretical (from research) | Measured (Session 23) |
|--------|----------------------------|----------------------|
| Per-PID update rate | ~0.5-1 Hz per PID | **~0.6 Hz per PID** (6.4 rows/sec across 11 PIDs) |
| Total PID throughput | ~6-8 PIDs/sec | **~6.4 rows/sec** |
| Per-request round trip | 120-200 ms | Consistent with measured throughput |

**Theoretical and empirical match.** Polling strategy designed against theoretical numbers is sound. Adding the Sprint 14 PIDs (fuel system status, runtime, barometric, MIL) will proportionally reduce per-PID rate on the bus — account for this in tiered polling design.

### Warm-Idle Fingerprint (Session 23) — Authoritative Baseline

Observed on this specific vehicle, 2026-04-19, ~23 seconds captured across 2 windows. Use as reference values for range-check tests, sim fixture validation, regression tests, and AI prompt grounding.

| Parameter | Observed | Interpretation Anchor |
|-----------|----------|----------------------|
| RPM (warm idle) | 761–852 rpm (±45 around 793) | Healthy idle stability. >±75 variation = IAC/vacuum/coil investigation. |
| LTFT | **0.00% flat** | Tune is dialed. Any drift from 0.00% on future captures = investigate. |
| STFT | −0.78% to +1.56% (avg +0.06%) | Normal closed-loop noise. >±3% amplitude = investigate. |
| O2 B1S1 | 0–0.82V switching, avg 0.46V | Healthy narrowband, stoich-crossing. |
| MAF (warm idle) | 3.49–3.68 g/s | Plausible idle airflow for 2.0L/4-cyl. |
| Engine Load (warm idle) | 19.22–20.78% | Normal warm idle. |
| Throttle Position (closed) | 0.78% flat | Clean TPS zero offset. |
| Timing Advance (warm idle) | 5–9° BTDC (avg 7°) | ⚠ Conservative vs community norm of 10–15°. Revisit at ECMLink baseline. |
| Coolant (warm-ish idle) | 73–74°C (163–165°F) flat | ⚠ Below full op temp (180°F+). Capture window was short; flag for next drill — if still below 180°F after sustained warmup, investigate thermostat. |
| IAT (short idle, cold ambient) | 14°C (57°F) flat | Matches Chicago spring ambient. |

**Data-capture context**: Engine-on wall-clock ~10 min; real OBD-connected data-capture time ~23 sec across 2 windows due to TD-023 connection churn. Captured window was steady-state warm (no cold-start, no warmup curve, no load). Pipeline integrity verified end-to-end Pi SQLite → chi-srv-01 MariaDB byte-for-byte.

**Sources for this section**:
- Raw data: `chi-eclipse-01:~/Projects/Eclipse-01/data/obd.db` (synced to `chi-srv-01:obd2db`)
- Review note: `offices/pm/inbox/2026-04-19-from-spool-real-data-review.md`
- Deep interpretation: `offices/tuner/knowledge.md` section "This Car's Empirical Baseline"

### Measured Eclipse 4G63 Idle Values (2026-04-19) — checked-in regression fixture

US-197 snapshots the Session 23 capture into a committed, regenerable regression fixture so these measurements are reproducible without re-driving the car:

| Asset | Path | Purpose |
|-------|------|---------|
| Fixture DB | `data/regression/pi-inputs/eclipse_idle.db` | 149 real rows, 11 PIDs, post-US-195/US-200 schema, `data_source='real'`, `drive_id=NULL` |
| Metadata | `data/regression/pi-inputs/eclipse_idle.metadata.json` | Drive context, PID list, capture window, tune context |
| Range tests | `tests/pi/obdii/test_live_idle_ranges.py` | Warm-idle tolerance bands (Spool-approved) assert on every CI run |
| Replay-shape tests | `tests/pi/regression/test_eclipse_idle_replay.py` | Determinism + replay-harness contract |
| Regenerate | `scripts/export_regression_fixture.sh` | SCPs live Pi db → applies US-195/US-200 migrations → writes fixture + metadata |
| Live re-verify | `scripts/verify_live_idle.sh` | SSH-driven in-vehicle capture + threshold check (CIO-runnable) |

Per-parameter measured values (Session 23 raw, authoritative):

| Parameter | Samples | Min | Max | Avg |
|-----------|---------|------|------|------|
| RPM | 15 | 761.5 | 851.5 | 793.1 |
| COOLANT_TEMP (°C) | 14 | 73.0 | 74.0 | 73.7 |
| LONG_FUEL_TRIM_1 (%) | 13 | 0.00 | 0.00 | 0.00 |
| SHORT_FUEL_TRIM_1 (%) | 13 | -0.78 | +1.56 | +0.06 |
| O2_B1S1 (V) | 13 | 0.000 | 0.820 | 0.458 |
| TIMING_ADVANCE (°BTDC) | 13 | 5.0 | 9.0 | 7.1 |
| MAF (g/s) | 13 | 3.49 | 3.68 | 3.57 |

These anchor future range-check tests and Spool AI grounding. Drift from these bands on a future capture is a signal, not a failure — update this table with new empirical values (append-only per Usage Rule #3) and investigate the delta.

---

## 2G DSM DTC Behavior (US-204)

### Confirmed supported modes

| Mode | python-obd command | 2G DSM (1998 Eclipse GST) | Notes |
|------|--------------------|---------------------------|-------|
| 03 | `GET_DTC` | ✅ supported | Stored DTCs. Universal OBD-II. |
| 07 | `GET_CURRENT_DTC` | ⚠ probe-first | Pending DTCs. May return null on 2G — pre-OBD2-full-compliance. The Pi `DtcClient.readPendingDtcs` returns a `Mode07ProbeResult` so callers cache the verdict per connection. |

When the Mode 07 probe lands `unsupported`, document it here per Usage Rule
#3. Until that empirical evidence is captured against the live Eclipse,
the production code treats it as a runtime probe — no assumption baked in.

### Unknown DTC descriptions

`python-obd`'s `DTC_MAP` covers the standard SAE J2012 set
(`P0XXX`, `B0XXX`, `C0XXX`, `U0XXX`). Mitsubishi-specific codes
(`P1XXX`) lack mapped descriptions and land in `dtc_log.description`
as the empty string per US-204 Invariant #6 (never fabricate). When
real DSM codes are captured, append the code → description mapping
under this section as the canonical source-of-truth — the schema does
NOT auto-update from this document.

| DTC | Description | Provenance |
|-----|-------------|------------|
| _(none captured yet)_ | _(populate after first MIL event on the live car)_ | _(source link required per Usage Rule #1)_ |

---

## Ambient Temperature Proxy via IAT at Key-On (US-206)

The 2G Eclipse does not support PID 0x46 (ambient air temperature). Spool's Phase 1 spec references ambient for IAT-caution interpretation (e.g., "IAT > 131°F = caution IF ambient was cold; 90°F ambient means heat-soaked IAT > 130°F is less alarming"). The workaround is to capture IAT (PID 0x0F) at drive-start and store it as `drive_summary.ambient_temp_at_start_c` — but only when the engine was genuinely off beforehand.

**Cold-start capture rule (US-206, Spool Priority 7)**:

* `fromState ∈ {UNKNOWN, KEY_OFF}` → cold-soaked intake ≈ ambient. Capture IAT as `ambient_temp_at_start_c`.
* `fromState = RUNNING` (warm restart; stall-and-go without hitting the 30s KEY_OFF debounce) → intake is heat-soaked from the hot engine bay. **Store NULL, not the IAT value.** Analytics treat NULL as "ambient unknown" and skip any IAT-caution interpretation that relies on ambient.

**Operational caveat**: on a cold morning with a cold-soaked engine, IAT-at-key-on is a solid ambient proxy. On a 90°F day after a 10-minute shutdown the engine bay is still holding heat — "cold-start" in the state-machine sense (KEY_OFF transition) does NOT guarantee ambient accuracy. Spool's downstream analytics should flag `ambient_temp_at_start_c > 40°C` as UNRELIABLE_HEATSOAK even when fromState was cold-qualifying; the capture-time rule is the first filter, not the last.

**Source**: Spool note `offices/pm/inbox/2026-04-19-from-spool-data-collection-gaps.md` Priority 7. PM Rule 7: cold-start rule is an [EXACT: fromState ∈ {UNKNOWN, KEY_OFF}] spec; the UNRELIABLE_HEATSOAK downstream flag is Spool's call and out of scope for US-206.

---

## Usage Rules

1. **Never fabricate values.** If a threshold or range is not in this document or `specs/obd2-research.md`, the story is `blocked` until data is provided.
2. **Cross-reference DSMTuners advice.** Look for patterns across multiple threads, not single posts.
3. **This document is append-only for facts.** New grounded knowledge gets added here as it's discovered. Existing facts are only updated with better data, never removed without CIO approval.
4. **CIO is the final authority.** If CIO provides a value that contradicts community guidance, CIO's value wins (it's their car).
