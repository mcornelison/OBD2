# EDR PID-Priority Allocation — Spool SME Deliverable

**Author**: Spool (Tuning SME)
**Date**: 2026-07-26
**Status**: Authoritative (engine-signal allocation SSOT for the EDR bus/reader)
**Audience**: Atlas (F-113 bus-contract rate-handling input), Marcus (tracking), Ralph (config impl)
**Refs**: F-112, F-113, E-006; `src/pi/obdii/data/polling_tiers.py` (US-136 tier engine, already built); `config.json → pi.pollingTiers`; `offices/tuner/knowledge.md` OBD-II § + 2026-05-22 capability probe; `offices/tuner/edr-alert-live-instrument-thresholds-advisory.md` (trigger SSOT)

> This is the F-113 input I owed: how to allocate the fixed K-line budget across PIDs for the EDR. It **re-grounds the existing 4-tier structure** against the *measured* budget + the *confirmed-supported* PID set — it does not invent a new mechanism (the tier engine already exists).

---

## 1. The budget — a hard, fixed ceiling you ALLOCATE (not a rate you set)

**Measured (Drive 27, 2026-06-06):** 16 PIDs @ ~0.39 Hz/PID = **~6.3 samples/sec aggregate**, on ISO 9141-2 @ 10,400 bps → **~160 ms per PID round-trip**. This is the ceiling every Pi-side EDR feature budgets against. Higher per-PID rate comes ONLY from polling *fewer* PIDs. There is no "turn up the Hz" knob.

**Consequence that must drive the design:** 6 PIDs at a true 1 Hz = 6 samples/sec = **the entire budget**. That's why the measured drive ran a flat ~0.39 Hz across all 16 — everything shares one thin pipe. Real prioritization = **trim Tier 1 to the few signals that genuinely need freshness**, move what can go off-K-line off it, and delete dead queries.

## 2. Two budget wins BEFORE allocating (grounded in the capability probe)

**2a. Move voltage to the free channel.** The adapter answers `ATRV` (battery voltage at OBD pin 16) **independent of the K-line** — it's an ELM327 AT command, not an ECU K-line transaction. Voltage monitoring therefore costs **~0** of the 6.3/s budget and can sample as fast as we want. `BATTERY_V` already uses this. Voltage 🔴 alerting (my advisory bands) is effectively free — exploit it.

**2b. Delete confirmed dead queries.** ⚠️ **CORRECTED 2026-08-20 — this item said 3 PIDs; it is 2.** `CONTROL_MODULE_VOLTAGE` (0x42) is **LIVE**, not dead (drive 33: 76 rows, 29 distinct, 12.975–14.451 V). My "drop all three" instruction would have deleted a working query. Genuinely dead: `FUEL_PRESSURE` (0x0A) and `INTAKE_PRESSURE` (0x0B / MAP — double-dead, it reads the MDP/EGR monitor so it is the wrong quantity even where it answers). **Drop those two from the rotation.**

**0x42 disposition — still drop it from the rotation, but for a different reason.** It answers, so it is not burning a slot on NO_DATA; it is burning a slot on a value we already get for free. `ATRV` reads the same voltage adapter-locally at pin 16, off the K-line, at zero cost against the ~6.3 samples/s budget. Keep `ATRV` as the production path and free the poll slot — a capacity decision, not a capability one. **Do not record 0x42 as unsupported anywhere.**
- Note for the upgrade path: `INTAKE_PRESSURE`/MAP being unsupported = **boost/manifold pressure is NOT OBD-reachable on this car**. Boost logging needs the GM 3-bar MAP sensor + ECMLink (already in my upgrade plan) — not a polling-tier fix.

## 3. The allocation (re-grounded tiers)

Off-K-line free channel — sample at will, ~0 budget:
| Signal | Source | EDR role |
|---|---|---|
| **Voltage** (`BATTERY_V`) | adapter `ATRV`, pin 16 | 🔴-capable (charging-system + injector-lean-under-boost); free → high rate |

On-K-line rotation (shares the ~6.3/s budget):

| Tier | Cycle | Eff. rate* | PIDs | Why here |
|---|---|---|---|---|
| **1 — safety/context, freshest** | every cycle | **~1.2 Hz** | `COOLANT_TEMP`, `RPM`, `ENGINE_LOAD` | Coolant = the #1 OBD-reachable 🔴 thermal signal. RPM + LOAD are the context every other signal and every trigger is gated on (redline, lean-under-load, grade-corrected load, gear). |
| **2 — driving context/fueling** | every 3rd | ~0.41 Hz | `THROTTLE_POS`, `SPEED`, `SHORT_FUEL_TRIM_1`, `TIMING_ADVANCE`, `O2_B1S1`, `MIL_ON` | SPEED→gear/grade derivation (debounced, slow-OK). STFT+O2 = the lean-under-load watch. TIMING_ADVANCE is **base timing, NOT knock** (demoted from Tier 1 — swings 10–15° under boost as normal). MIL_ON for edge-triggered DTC re-fetch. |
| **3 — trend/emissions health** | every 10th | ~0.12 Hz | `LONG_FUEL_TRIM_1`, `INTAKE_TEMP`, `O2_B1S2`, `FUEL_SYSTEM_STATUS` | LTFT drift, IAT heat-soak, downstream O2, open/closed-loop state — trends, not events. |
| **4 — background** | every 30th | ~0.04 Hz | `BAROMETRIC_KPA`, `RUNTIME_SEC` | Baro for altitude/grade + future boost-vs-baro math; runtime for warm-up gating. |

*Effective rate math: over one 30-cycle supercycle the scheduler issues 3×30 + 6×10 + 4×3 + 2×1 = **154 K-line samples** ÷ 6.3/s ≈ **24.4 s** → base cycle ≈ **0.81 s**. Tier 1 = 1/0.81 ≈ **1.23 Hz**. This gives coolant/RPM/load **~3× the freshness** of the flat 0.39 Hz they get today, paid for by demoting trend PIDs and dropping the dead queries.

## 4. Dynamic priority — the EDR event burst (design input for F-113)

Priority is **not static**. When a trigger fires (MIL rising edge; coolant crossing 🟡→🔴; sustained lean-under-load), the reader should **temporarily reallocate** budget to the event's diagnostic PIDs and shed Tier 3/4 for the capture window — e.g. a thermal event promotes COOLANT/RPM/LOAD/IAT and drops trend polling. **Burst = reallocate, never accelerate** — the 6.3/s ceiling is physical. F-113's per-subscriber QoS should model this as a priority the trigger layer can assert, not a rate change. (Freeze-frame Mode 02 is UNSUPPORTED on this ECU — the "state at trigger" snapshot falls back to a full `realtime_data` capture, per the DTC advisory.)

## 5. What the K-line CANNOT cover at ANY allocation → ECMLink (F-112)

No budget split buys these — they aren't on the OBD surface (probe-confirmed):
- **Knock sum / knock retard / per-cylinder timing** — the #1 engine-killer signal; ECMLink RAM via MUT-II only (F-112).
- **True AFR** — narrowband O2 only toggles at stoich; needs wideband.
- **Injector duty, boost/MAP** — MAP unsupported; boost needs the GM 3-bar sensor.

This is the point: **OBD's ~6.3/s is a monitoring budget, not a fast safety net.** The fast safety net (knock) lives on the ECMLink path — which is why F-112 gates the high-value half of the EDR, and why the K-line arbitration between the OBDLink and any ECMLink reader (single-K-line = one reader) is the load-bearing F-113 question.

## 6. Implementation note (Ralph, when it grooms — not now)
The tier engine (`polling_tiers.py`) + `pi.pollingTiers` config already exist. This is a **config re-grounding** (move voltage off-rotation, drop 3 dead PIDs, re-tier the rest per §3) + a trigger-priority hook for §4 — not a new subsystem. Ping me at groom; I'll confirm final tier membership against any newly-supported PIDs if the ECU changes.
