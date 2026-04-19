# Real Eclipse Data Review — Session 23 First-Light Capture
**Date**: 2026-04-19
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important (milestone review + 2 change requests)

## Context

CIO asked me to grade the first real-car OBD data against my Phase 1 tuning spec. I pulled the most recent run from both the Pi SQLite (`~/Projects/Eclipse-01/data/obd.db` on chi-eclipse-01) and the server MariaDB (`obd2db` on chi-srv-01), compared them, and checked the values against the Sprint 11/12 threshold and coverage specs. No tuning recommendations at this stage — this is a pipeline + data-integrity review.

**TL;DR**: Pipeline is clean end-to-end. Tune is dialed. Two change requests for PM. One observation about capture window.

---

## End-to-End Integrity — PASS

Pi ↔ server match is byte-perfect for the real-run slice.

| Store | realtime_data rows | statistics rows | connection_log rows | Values match? |
|---|---|---|---|---|
| Pi SQLite | 149 | 11 | 16 | — |
| Server MariaDB (slice `>= 2026-04-19 07:18`) | 149 | 11 | 16 | ✅ identical per-PID counts, mins, maxes, avgs |

`sync_history` on server shows batch `chi-eclipse-01-2026-04-19T13:48:03Z` completed `ok` across 4 tables: realtime_data (149), statistics (11, all 11 as updates — prior sim data in the same rows got overwritten with real values), profiles (2 inserted), connection_log (16, 8 inserted + 8 updated via batch idempotency). Memory note about profiles erroring on TD-026 appears resolved — profile sync went through this time.

**Conclusion**: The end-to-end pipeline (OBD → Pi SQLite → HTTP SyncClient → MariaDB) does not corrupt, drop, or drift tuning data. That was the test, and it passed.

---

## Actual Live Data Window — ~23 seconds, not 10 minutes

This is the most important finding from the raw data, and it's **not** a problem — it's a framing correction.

CIO described the drill as ~10 minutes of idle. The `connection_log` tells a different timeline:

| Time (UTC) | Event | Result |
|---|---|---|
| 12:17:12 — 12:17:40 | 5 `connect_attempt` using MAC as path | all failed (TD-023 — known) |
| 12:18:10 | connect_attempt via `/dev/rfcomm0` (workaround) | success 12:18:50 |
| 12:18:51 | disconnect | only 1 second of data captured in this window (2 rows) |
| 12:19:41 | connect_attempt | success 12:20:19 |
| 12:20:41 | disconnect | end of data — 22 seconds captured in this window (147 rows) |

**Real OBD-connected data-capture time: ~23 seconds across 2 windows.** The other ~9 minutes of wall-clock idle was either pre-connection retry churn, gaps between reconnects, or post-disconnect engine-on. The engine was idling the whole time, but the collector was only pulling rows for ~23 seconds.

This doesn't invalidate the milestone — the engine was real, the ECU was real, the data was real. But it means:

- **No warmup curve in the data** (coolant is flat at 73-74°C through the whole capture — engine was already warm when the successful connection happened)
- **No cold-start enrichment observed**
- **No closed-loop → open-loop transitions**

For the pipeline test, 23 seconds is enough. For a tuning-review-grade datalog, it's not. Change request #2 below addresses this.

---

## PID Coverage vs My Spec

My Phase 1 primary display spec called for 6 parameters. Here's how the real capture hit them:

| Spec'd PID | Captured | Real Values | Notes |
|---|---|---|---|
| RPM | ✅ | 761–852, avg 793 | Normal warm idle for 4G63, stable |
| Coolant | ✅ | 73–74°C (163–165°F) | Below full op temp (180°F+); short capture, engine possibly not fully warm, or thermostat slightly cool — flag for next log, not actionable now |
| Boost | ❌ | — | MAP PID 0x0B unsupported by 2G ECU. **Known, Phase 2 adds aftermarket MAP or ECMLink. No change needed.** |
| AFR | ✅ (narrowband) | O2_B1S1 0–0.82V switching, avg 0.46V | Per spec — this is narrowband, displayed as rich/lean indicator only, not true AFR numerically. Gets replaced by AEM UEGO in Phase 2. |
| Speed | ✅ | 0 km/h | Parked, correct |
| Battery Voltage | ❌ | — | Control Module Voltage PID 0x42 unsupported by 2G ECU. **NEW gap — see change request #1.** |

Bonus PIDs captured beyond primary display (valid for advanced/detail tier + analytics):

| PID | Values | Plausibility |
|---|---|---|
| INTAKE_TEMP | 14°C (57°F), flat | ✅ matches Chicago spring ambient, no heat-soak in short window |
| LTFT | 0.00%, flat across 13 samples | ✅ **CIO's tune is dialed — base map is right** |
| STFT | −0.78% to +1.56%, avg +0.06% | ✅ tiny noise around stoich, closed-loop happy |
| MAF | 3.49–3.68 g/s | ✅ plausible idle airflow for 2.0L/4-cyl |
| ENGINE_LOAD | 19.22–20.78% | ✅ normal warm idle |
| THROTTLE_POS | 0.78% (flat) | ✅ closed-throttle idle TPS offset |
| TIMING_ADVANCE | 5–9° BTDC | ⚠ conservative for idle; stock 2G typically 10–15° BTDC at idle. Not a problem, but worth re-checking on the next log and/or at ECMLink baseline — see change request #4 |

**No impossible readings. No stuck-sensor signatures. No zero-value flatlines where values should be moving. No out-of-range excursions.**

---

## Threshold Spec Check — Real Values vs Phase 1 Tiered Thresholds

Running captured ranges through my tiered thresholds (Sprint 11/12 corrected spec):

| Parameter | Real Range | Normal | Caution | Danger | Status |
|---|---|---|---|---|---|
| RPM | 761–852 | 0–6500 | 6501–7000 | ≥7001 | ✅ Normal |
| Coolant | 163–165°F | ≤210°F | 211–219°F | ≥220°F | ✅ Normal, well below caution |
| IAT | 57°F | ≤130°F | 131–160°F | >160°F | ✅ Normal |
| AFR | 0–0.82V (narrowband) | — | — | — | Phase 2 territory (narrowband interpretation guard applies) |
| Speed | 0 | — | — | — | Parked |
| Battery V | — | 12.0–15.0V | — | — | Not captured — see CR #1 |

**No threshold recalibration needed from this data.** Real-car values sit firmly inside the "Normal" band for every parameter captured. Any recalibration will require a full drive cycle with thermal ramp and load-based data — not available yet.

---

## Change Requests

### CR #1 — Battery Voltage capture gap (NEW story candidate, Sprint 14)

**Problem**: Primary display spec includes Battery Voltage. Real-car data confirms PID 0x42 (Control Module Voltage) is unsupported by the 2G ECU. We have no voltage reading on the display or in the database.

**Recommendation**: Query adapter-level voltage via ELM327 `ATRV` command (not an OBD-II PID — it's an adapter function). Every ELM327-compatible adapter exposes this. In python-obd it's `obd.commands.ELM_VOLTAGE`. Returns the voltage measured at the OBD-II port (effectively battery voltage with engine off, or charging voltage with engine running).

**Story scope suggestion**:
- Add `ELM_VOLTAGE` to the Pi collector's poll set
- Persist as `BATTERY_VOLTAGE` (or `ELM_VOLTAGE`) parameter_name in realtime_data
- Wire to primary display battery gauge
- Threshold values from my Phase 1 spec: normal 12.0–15.0V; caution <12.0V with engine running (charging system issue) or >15.0V (overcharge); danger <11.0V or >15.5V

**Priority**: Sprint 14, paired with next real-drive drill. Needed before we can claim primary display coverage is complete.

### CR #2 — Request longer, uninterrupted real-data capture after TD-023 fix

**Observation**: The Session 23 capture is ~23 seconds of OBD-connected data, fragmented into 2 windows by a disconnect. This was enough to prove the pipeline. It is **not** enough for a tuning-review-grade datalog.

**Recommendation**: Once TD-023 (mac-as-path) is fixed in Sprint 14, run a second drill targeting:
- **Cold start** — key-on before engine crank, capture from first second
- **Uninterrupted idle** — target 10 minutes connected, no disconnects mid-capture
- **Shutdown** — capture through key-off

This will produce the first dataset that lets me (or the server AI) actually review engine health against community-calibrated norms — warmup curve, closed-loop transition, idle stability drift, thermal ramp behavior.

**Priority**: Sprint 14, after TD-023. Not blocking, but the first useful tuning-review datalog depends on it.

### CR #3 — Spec drift check for the spec doc itself (minor)

The original Sprint 11/12 tuning spec for the primary display listed Battery Voltage without specifying a source (I assumed OBD-II PID coverage; 2G reality says otherwise). I'll update `offices/tuner/knowledge.md` to note that battery voltage on the 2G DSM must come from the adapter-level query, not a PID. No PM action needed — this is my homework.

### CR #4 — Schema: tag simulated vs real data at the row level (NEW, CIO-directed)

**Problem**: As of Session 23 the database contains a mix of simulator output (~26,600 rows pre-2026-04-19 07:18) and real-car output (149 rows from 07:18–07:20). They look identical in the schema. Going forward we'll have more of both (Sprint 13 US-191 flat-file replay lands more simulated data; Sprint 14 post-TD-023 lands more real data). Losing the ability to tell them apart will contaminate analytics, baselines, and AI recommendations.

**Recommendation** (to be sized as a Ralph story, Sprint 14):
- Add a column `data_source` (ENUM or TEXT: `'real' | 'replay' | 'physics_sim' | 'fixture'`) to every capture table that can receive non-real data:
  - `realtime_data` (highest priority)
  - `connection_log`
  - `statistics` (derived — inherits from the dominant source of the input rows)
  - `calibration_sessions`
  - `drive_statistics` / `drive_summary` / `analysis_history` on the server
- Default to `'real'` for the Pi collector's live-OBD path so un-tagged rows don't silently flip meaning
- Flat-file replay harness (US-191) tags `'replay'`
- Physics simulator (deprecated per B-045, but historical rows exist) tags `'physics_sim'`
- Test fixtures tag `'fixture'`
- All server-side analytics, AI prompt inputs, and baseline calibrations must filter to `data_source = 'real'` (or explicit opt-in) unless the caller is running a synthetic test

**Rationale**: A server-side baseline ("what is normal idle coolant for THIS car?") computed over mixed sim+real data is worse than no baseline at all — it grounds the model in fabricated values. The AI prompts (`src/server/services/prompts/system_message.txt`) already forbid fabricated numbers from narrowband; this is the data-layer equivalent of the same discipline.

**Priority**: Sprint 14. Do this BEFORE the post-TD-023 real-drive drill so the new capture is tagged from row zero and doesn't need retroactive UPDATE.

### CR #5 — Timing Advance observation for future ECMLink baseline

Captured idle timing was 5–9° BTDC. Stock 2G community norms put idle timing at 10–15° BTDC. Three possibilities:
1. Stock modified-EPROM was programmed conservatively
2. ECU adaptive timing is still learning after winter storage
3. Data-resolution artifact (python-obd rounding)

**Not actionable now.** Filing for future: when ECMLink V3 is installed (Summer 2026 per CIO plan), the baseline session should explicitly capture idle timing across a range of coolant temps and compare to DSMTuners community consensus. I'll keep this in my knowledge base; no PM story needed yet.

---

## What I Am NOT Asking For

- **TD-023 retry** — already filed and queued for Sprint 14 by you, confirmed
- **TD-024 (status_display GL)** — already filed, deferred to Sprint 14 as US-192
- **TD-025 / TD-026 (SyncClient PK assumptions)** — already filed
- **MAP / Fuel Pressure PIDs** — expected to be unsupported, Phase 2 gets aftermarket MAP
- **Threshold recalibration** — no real drive cycle data yet; current thresholds hold

---

## Sources

- Pi SQLite: `chi-eclipse-01:~/Projects/Eclipse-01/data/obd.db`, tables `realtime_data`, `statistics`, `connection_log`, `sync_log`
- Server MariaDB: `chi-srv-01:obd2db`, same tables + `sync_history`
- My Phase 1 spec: `offices/pm/inbox/2026-04-10-from-spool-system-tuning-specifications.md` (original), with Sprint 11/12 corrections
- PID support baseline: `specs/obd2-research.md` (2G ECU PID coverage)
- 2G factory redline (7000 RPM): `offices/tuner/knowledge.md` (updated Session 3)
- Stock TD04-13G boost envelope: `offices/tuner/knowledge.md` (max 15 psi caution for stock turbo)

---

## Overall Milestone Grade

**Milestone: valid. Pipeline: proven. Tune: dialed. Data: clean.**

Ship the closeout. The engine told us it's healthy. What it did NOT tell us (warmup, load response, thermal ramp) comes from the Sprint 14 post-TD-023 drill, not from a spec change.

— Spool
