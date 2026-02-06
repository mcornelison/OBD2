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

**Important**: These ranges are community-sourced baselines for a stock-turbo 2G DSM. They will be refined with real vehicle data once CIO collects OBD-II samples via Torque Pro.

---

## Usage Rules

1. **Never fabricate values.** If a threshold or range is not in this document or `specs/obd2-research.md`, the story is `blocked` until data is provided.
2. **Cross-reference DSMTuners advice.** Look for patterns across multiple threads, not single posts.
3. **This document is append-only for facts.** New grounded knowledge gets added here as it's discovered. Existing facts are only updated with better data, never removed without CIO approval.
4. **CIO is the final authority.** If CIO provides a value that contradicts community guidance, CIO's value wins (it's their car).
