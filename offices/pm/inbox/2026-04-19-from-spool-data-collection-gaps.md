# Data Collection — Gaps Exposed by Session 23 Real Data
**Date**: 2026-04-19
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important (sizes into Sprint 14 planning)

## Context

CIO asked, after reviewing the Session 23 first-real-data capture: *"are there any new specs or requirements you would like to see added to data collection?"*

Yes. The 23 seconds of real data exposed real gaps beyond what was already tracked. Some of these were oversights in my Phase 1 spec; others became obvious only once we saw real ECU behavior. Listed in **priority order** — not all Sprint 14, but all belong in the data-collection roadmap.

**Related inbox note from same session**: `2026-04-19-from-spool-real-data-review.md` — the first-light data review. This note is its follow-up, focused on **what to add next**.

---

## Priority 1 — Fuel System Status (Mode 01 PID 0x03)

**Why critical**: Without this PID, STFT and LTFT **cannot be correctly interpreted**. Fuel trims only apply in closed-loop operation. In open-loop (warmup enrichment, WOT enrichment, decel fuel cut, fault mode) the ECU ignores the O2 sensor and STFT stays at 0 **by definition, not by tune quality**. My Session 23 review graded LTFT = 0% as "tune is dialed" based on the inference that closed-loop was active (O2 switching supports this) — but that inference is fragile.

**What it returns**: One of OL (open-loop cold), CL (closed-loop), OL-drive (open-loop under load), OL-fault, CL-fault.

**Recommendation**: Poll at 1 Hz minimum. Store as a parameter_name in `realtime_data` (or as a session-state column if that's a cleaner fit — Ralph to decide). Include in AI prompt inputs and threshold filtering (trims only checked when `fuel_system_status = 'CL'`).

**Support**: Universally supported on OBD-II, including 1998 2G DSM.

---

## Priority 2 — MIL Status and Stored DTCs (Mode 01 PID 0x01 + Mode 03 + Mode 07)

**Why critical**: **"Is the check engine light on?" is Question 1 of every engine health review and we don't capture the answer.**

My Session 23 grade of "engine is healthy" rests on LTFT/STFT/O2 looking clean. But if the ECU has P0171 (lean condition), P0300 (misfire), P0420 (cat efficiency), or any number of pending codes below MIL threshold, I missed it. That's a material gap for a first-real-data review.

**What to capture**:
- **Mode 01 PID 0x01**: MIL-on bit + count of stored DTCs. Poll at 0.5 Hz minimum so live illumination is caught.
- **Mode 03**: retrieve the actual stored DTC codes. Run once at session start + whenever MIL illuminates mid-session.
- **Mode 07**: retrieve pending codes (sub-threshold, not yet illuminated). Run at session start.

**Storage**: A new `dtc_log` table — one row per DTC occurrence, keyed to `drive_id` (see Priority 3). Columns: dtc_code, description, status (stored/pending/cleared), first_seen_timestamp, last_seen_timestamp, drive_id.

**Support**: Universal OBD-II. 2G DSM supports Modes 01/03. Mode 07 may not be supported (pre-OBD2 full compliance) — Ralph to probe, skip silently if unavailable.

---

## Priority 3 — Drive / Session ID Column

**Why critical**: As of today, `realtime_data` is just timestamped rows. Once Sprint 14 post-TD-023 lands + US-191 flat-file replay runs + sim testing continues, we'll have multiple real drives, multiple replay sessions, and multiple sim runs all interleaved. Every per-drive analytic (warmup curve, peak boost, avg AFR, drive summary → AI input, drive_statistics table) needs grouping.

**Recommendation**:
- Add `drive_id` (BIGINT or UUID) column to `realtime_data`, `connection_log`, `statistics`, `alert_log`, and any other per-session table
- Increment on engine-start transition: detection heuristic = RPM goes from 0 (or no-connection) → RPM ≥ cranking threshold (~250 RPM)
- Drive-end detection: RPM = 0 AND speed = 0 for N seconds (tune N — 30s is a reasonable start), OR explicit engine-off event from connection_log
- Combined with `data_source` column (CR #4 from previous note), the canonical analytic filter becomes:
  ```sql
  WHERE data_source = 'real' AND drive_id = <target>
  ```

**Sizing**: Ralph to size. The engine-state machine is the non-trivial part; the column is easy. Should land **before** Sprint 14's post-TD-023 drill so the first substantive real-data capture is grouped correctly from the start.

---

## Priority 4 — Runtime Since Engine Start (Mode 01 PID 0x1F)

**Why valuable**: Anchors every data row to "how far into this drive are we?" Without it, I cannot tell if Session 23's coolant plateau at 73°C was 2 seconds after startup or 8 minutes after. Also catches engine-restart-mid-capture scenarios (Runtime resets to 0) as a cross-check against drive_id logic.

**What it returns**: Seconds since last engine crank. 16-bit, rolls over at ~18 hours (non-issue for normal use).

**Recommendation**: Poll at 0.2 Hz (once every 5 seconds is plenty). Cheap, always supported, huge analytic value.

---

## Priority 5 — Barometric Pressure (Mode 01 PID 0x33)

**Why valuable**: Altitude and weather compensation for calculated airflow, MAP-derived boost (Phase 2), engine load interpretation.

Chicago's near sea level so daily impact is tiny, but:
- Low-pressure weather systems affect mixture tendency (richer)
- Any altitude change (unlikely but possible) makes uncorrected MAP/MAF readings misleading
- E85 tuning at altitude is materially different (Phase 2 concern)

**Recommendation**: Poll once per drive at drive-start (it doesn't change during a drive) OR at 0.05 Hz (once every 20s) as a compromise. Store in `drive_summary` or as a metadata field on the drive record.

**Support**: Universal, including 2G.

---

## Priority 6 — Post-Catalyst O2 Sensor (Mode 01 PID 0x15)

**Why valuable**: Downstream O2 = catalyst health monitor. A healthy cat makes the rear O2 steady near 0.7-0.8V with minimal switching. A worn cat lets exhaust chemistry pass through unchanged, and the rear O2 starts mirroring the front. Also:
- Required signal for Illinois emissions readiness monitor completion
- E85 is hard on cats — want baseline + trending

**Support uncertain**: 1998 2G is pre-OBD2 full compliance. May not support PID 0x15. Ralph to probe Mode 01 PID 0x00 response at integration time. If unsupported, skip silently and note in grounded-knowledge that this platform doesn't offer post-cat O2. If supported, poll at 0.5 Hz.

---

## Priority 7 — Ambient Temperature Baseline (Proxy via IAT at Key-On)

**Why useful**: My Phase 1 spec references ambient air temperature for IAT caution threshold interpretation ("IAT >131°F = caution IF ambient was cold"; ambient 90°F means heat-soaked IAT >130°F is less alarming). We have no ambient capture.

**Approach**: 2G likely doesn't support PID 0x46 (ambient air temp). Workaround: capture IAT at **key-on BEFORE engine start** (cold-soaked intake ≈ ambient). Store as `ambient_temp_at_start` metadata field on the drive record.

**Recommendation**: Part of the drive-start sequence — immediately after power-on, before engine crank, read IAT once and store as drive metadata. If the Pi isn't powered until engine crank (ignition-switched power), then fall back to first-IAT-sample as best-available proxy with a confidence flag.

---

## What I'm Explicitly NOT Asking For (Phase 2 or Out of Scope)

Listed here so you don't add them to Sprint 14 by mistake:

- **Knock count / knock sum** — ECMLink territory, Phase 2 only
- **Injector pulse width / duty cycle** — ECMLink only
- **Wideband AFR** — Phase 2 after AEM UEGO install
- **Boost (MAP)** — 2G ECU lacks it, Phase 2 adds aftermarket 3-bar MAP or ECMLink
- **Cam timing / VVT** — 4G63 doesn't have variable cam timing
- **Transmission gear** — manual trans, no PID

---

## Suggested Sprint 14 Bundle

If you want a tidy bundle for Ralph, the **"Data Collection Completeness v2"** story group would be:

- **Story 1**: Add PIDs 0x01 (MIL), 0x03 (fuel system status), 0x1F (runtime), 0x33 (barometric), ELM_VOLTAGE (battery voltage from CR #1), optional 0x15 (post-cat O2, probe-first) to the Pi poll set. Persist to realtime_data. (M size)
- **Story 2**: Add `drive_id` column + engine-state detection (start/end transitions) to Pi collector. Retroactively tag existing rows as `drive_id = 0` or NULL. (M size)
- **Story 3**: Add DTC handling — Mode 03/07 retrieval on session start + MIL illumination events. New `dtc_log` table, server-side mirror. (L size — this is a new capability, not a PID addition)
- **Story 4**: Drive-metadata capture — ambient-temp-proxy via key-on IAT, barometric pressure, starting voltage. New `drive_summary` columns or fields. (S size if `drive_summary` already exists; it does on server.)

Priorities 1-4 above map cleanly to Stories 1-4.

Pair this with **CR #4 from the Session 23 review note** (`data_source` column) — same sprint, same table migrations, do them together.

---

## Sources

- Mode 01 PID spec: `specs/obd2-research.md`
- 2G DSM OBD compliance notes: `offices/tuner/knowledge.md` (2G-specific PID support section)
- Phase 1 tuning spec original: `offices/pm/inbox/2026-04-10-from-spool-system-tuning-specifications.md`
- Session 23 first-light data review: `offices/pm/inbox/2026-04-19-from-spool-real-data-review.md` (sibling note — read together)

— Spool
