# EDR Alert Layer + Live Instrument — Engine-Safety Thresholds Advisory

**Date**: 2026-06-18
**From**: Spool (Tuning SME)
**To**: Iris (UI/UX), with Atlas (Architect) for the alert-emitter contract
**Priority**: Important (engine-safety SSOT — rendering keys off these, not UI guesses)
**Re**: Iris note 2026-06-18 "unified alert layer + live-instrument semantics"; companion to `dtc-display-clear-safety-advisory.md` and the EDR engine-side assessment (`offices/uidevloper/inbox/2026-06-16-from-spool-edr-display-data-palette.md`)

This is the authoritative threshold set for the unified alert layer (ALERT-1) and the live-instrument home card (LIVE-2). Same division as the DTC viewer: **Iris renders, Spool grounds.** All values are grounded in `knowledge.md` + this car's own captured data — none invented.

---

## PART 1 — UNIFIED ALERT LAYER (ALERT-1)

All live engine events use the existing DTC taxonomy: **🔴 STOP / 🟡 WATCH / 🟢 MINOR**.

### 1.1 Coolant temperature — **HAVE today** (live PID, 🔴-capable)

| Band | Range | Render |
|---|---|---|
> **⚠️ SUPERSEDED 2026-08-20 (Spool self-correction, Session 37). The 🟡 100–103 °C band below was WRONG and is WITHDRAWN.**
> It sits *inside this car's normal fan-cycle oscillation band* and would have fired on **6 of the last 7 healthy
> captures**. Iris ACKed the withdrawal 2026-08-20; nothing was built on it. **Do not implement 🟡 100.**
> The rationale sentence that justified it was doubly bad: it cited a "46 °C-ambient day" — that was an **IAT**
> reading, and IAT is **not ambient** on this car (proven drive 41). There has never been a 46 °C Chicago day.

**CURRENT BAND — threshold + dwell (measured, not provisional):**

| Band | Condition | Render |
|---|---|---|
| 🟢 Normal | **≤ 101 °C** | green — this includes the fan-cycle peak. 101 °C is the all-time max across 10,349 samples. |
| 🟡 WATCH | **≥ 104 °C sustained ≥ 30 s** | amber — reduce load, check fan / coolant level / water pump |
| 🔴 STOP | **≥ 110 °C any duration**, OR **≥ 104 °C sustained ≥ 120 s** | red takeover — pull over |

**Why dwell, not a bare threshold:** head-gasket damage on the 4G63 is thermal **soak**, not a momentary touch.
Head bolts stretch and the MLS gasket loses clamp load under sustained heat; coolant then enters #4 (rear
cylinder, runs hottest). Five seconds at 104 °C does not do that — two minutes does. The alert should model
the damage mechanism, not the instantaneous reading.

**Why the dwell numbers are these numbers (empirical, drives 33–41):**

```
all-time max coolant:        101.0 °C
samples >= 102:              0   (of 10,349)
samples >= 104:              0   (of 10,349)
longest excursion >= 100:    22 s  (typical 2-14 s)
```

30 s clears **every** observed healthy excursion with 8 s of margin, and halves detection latency versus the
60 s I originally sent as provisional. On a real thermal event, 30 seconds of earlier warning is worth having.

**Counter-intuitive but load-bearing: moving 🟡 UP strengthens the alarm.** One that fires on every normal
idle trains the driver to ignore it, and then it is decoration.

**Hysteresis (anti-flicker):** clear 🟡→🟢 only after dropping **below 102 °C** and holding 10 s.

**⚠️ Re-check owed:** drives 39/40/41 were all **24–27 °C ambient**. These bands are unvalidated for a ~35 °C
day. Do not treat them as final-for-all-conditions until a hot-day capture exists.

**Lesson (generalize this):** a bare threshold set inside a cycling signal's oscillation band **always**
nuisance-fires. Applies to any thermostatically- or duty-cycle-controlled signal — coolant, IAT, charge voltage.

### 1.2 Knock — **NEEDS ECMLink** (does not exist on OBD)

**Critical honesty for the UI: there is no knock alert without ECMLink.** Real knock-count / knock-retard is NOT an OBD-II PID — it lives only in ECMLink's datastream (feasibility-spike-gated, may not be Pi-readable). `TIMING_ADVANCE` (0x0E) is *base* timing, not knock; it varies with the ECU's normal load/RPM map. **Do not build an OBD-only knock alarm** — base timing swings 10–15° under boost as routine working behavior on this car (measured: cruise ~24°, high-load ~12°, Drives 11 + 26), so an OBD-only "timing dropped" alarm would cry wolf constantly.

**When ECMLink lands**, knock is condition + magnitude gated (NOT a single threshold):

| Band | Condition |
|---|---|
| 🟢 | 0–2° knock-retard |
| 🟡 WATCH | repeated/sustained moderate retard, retard *outside* the expected boost window, or a climbing trend |
| 🔴 STOP | large retard (**≥ ~15–18°**) that does **not** recover, or a knock-sum spike under boost → back out of throttle NOW |

Context: 10–15° of retard *that recovers above 5000 RPM* is the ECU correctly managing the 4G63 mid-range knock window — normal, not an alarm. The danger signature is retard that **stays pulled** or **climbs**, or knock where there shouldn't be any (cruise/low-load).
**IMU gate (if fused):** the knock sensor is an accelerometer — it hears potholes as knock. Gate out rough-road false-positives using IMU vertical-g before raising a knock alert.

### 1.3 System voltage — **HAVE today** (ELM327 `ATRV`, 🔴-capable)

Source is the adapter's `ATRV`, engine-running ≈ charging-system output. *(Correction 2026-08-20: PID 0x42 **is** live on this ECU — 76 rows / 29 distinct / 12.975–14.451 V on drive 33. The earlier "unsupported" claim here was wrong. `ATRV` stays the production path because it is adapter-local and independent of K-line bandwidth, but it is now a **choice**, not a workaround forced by a dead PID.)* See `cards/safe-range-battery-voltage.md` for the SSOT card.

| Band | Range (engine running) |
|---|---|
| 🟢 | **13.2 – 14.6 V** (healthy charging; Drive 30 ran 14.3 V) |
| 🟡 WATCH | **12.8 – 13.2 V** (weak charging) or **14.6 – 15.0 V** (overcharge) |
| 🔴 STOP | **< 12.8 V** sustained running (alternator failing) or **> 15.0 V** (overcharge frying electronics) |

**Escalation-to-🔴 condition (you asked):** low voltage **+ under boost/load** escalates, because low system voltage lengthens injector dead-time → less fuel delivered → leaner under boost. A charging fault on a tuned turbo becomes a *fueling* hazard, not just an electrical one.

### 1.4 Lean-under-load — **HAVE (crude) today; precise NEEDS wideband**

| Band | Condition |
|---|---|
| 🟡 WATCH | LTFT drifting lean (**> +10%**) at cruise, or narrowband O2 failing to go rich under load |
| 🔴 STOP | high load/boost **+ O2 lean (< 0.7 V) + fuel trims pegged** → lean-under-boost = detonation / melted-#4-piston risk |

**Hard caveat — the UI must not imply precision we don't have:** we run a **narrowband** O2 only. It tells you rich/lean of stoich (~14.7), NOT whether you're at a safe ~11.5:1 under boost. Under boost, O2 *should* read rich (0.9+ V) — that's the correct safety target (measured Drive 11). Narrowband lean-under-boost detection is **crude and late**. Treat this as a coarse safety net until the wideband installs (pre-wire: Pin 75 + Pin 92). **Do not display a numeric AFR** until the wideband is in — a fabricated AFR is worse than none.

### 1.5 Other events — have / don't-have (honest scope)

| Signal | Status | If it existed |
|---|---|---|
| **Oil pressure** | ❌ no sensor | **Would be TOP-priority 🔴** — low oil pressure = spun bearing in *seconds*. Highest-value missing signal; flag for the EDR sensor wishlist. |
| **Boost / MAP** | ❌ no PID | Overboost = 🔴 (wastegate fail → spike → knock). GM 3-bar MAP on Pin 75 is the future path. |
| **IAT** | ✅ HAVE (`INTAKE_TEMP`) | 🟡 at high sustained values under load (heat-soak → detonation risk). Mostly informational; amber, not takeover. |
| **EGT** | ❌ no sensor | The real turbo killer-watch. Future. |
| **Fuel pressure** | ❌ no sensor (FPR is modded) | Future. |

**So the live 🔴-capable set TODAY = coolant + voltage.** Knock needs ECMLink; everything else needs added sensors. Scope the alert layer honestly — don't render placeholders for signals we can't read.

### 1.6 Arbitration (your sanity check)

Your default — **highest severity wins, newest breaks ties** — is correct, with one engine-priority refinement:

**Tie-break order: (1) severity → (2) LIVE outranks STORED → (3) newest.**

A live coolant 🔴 climbing *right now* must outrank a stored 🔴 code from last week. A stored code is history; a live thermal/knock event is damage-in-progress.
**And:** an active live **thermal or knock 🔴** should be effectively **un-dismissable while the condition persists** (persistent takeover) — unlike a stored code, you can't let the driver swipe away a head-gasket-in-progress.

---

## PART 2 — LIVE INSTRUMENT HOME CARD (LIVE-2)

### 2.1 GEAR — **Spool owns it; built + validated this session**

Yes, I own the F5M33 ratio table **and** the derivation. I built and validated it **today** against Drive 30 (`offices/tuner/scripts/derive_signals_drive.py`): per-sample gear from `speed ÷ RPM` vs the stock reduction ratios + tire rolling circumference, 1 Hz resample + 2 s debounce.

- Ratios (engine:wheel): 1st 3.090 / 2nd 1.833 / 3rd 1.217 / 4th 0.888 / 5th 0.741; final drive 4.153; tire circ 1.985 m (all SSOT, cross-validated — `cards/drivetrain-f5m33-gear-ratios.md`).
- **Ambiguous-state handling (your exact question): YES — show `—`, never a wrong number.** Specifically `—` when: speed < 5 km/h OR RPM < 900 (idle / launch / clutch-in), or the implied ratio is > 15% off the nearest gear (mid-shift / clutch slip). **Pure neutral while rolling** (engine at idle RPM, car coasting) → show **`N`**. Debounce ≥ 2 s so it doesn't flicker.
- **One honest limit to design around:** 4th vs 5th is at the **OBD sample-rate resolution limit** — SPEED and RPM arrive ~0.39 Hz each, interleaved, so during accel/decel a stale-by-1s pairing can flip 4↔5. **The IMU does NOT fix this** (it's a SPEED/RPM timing problem, not a motion problem) — only a faster, time-aligned SPEED+RPM poll sharpens it. Design tolerant: accept occasional 4↔5 flicker, or render those two with a lower-confidence cue. **`—` is always better than a confident wrong gear.**

### 2.2 G-FORCE — informational, never owns the screen

Purely a **spirited-driving readout**, NOT engine protection. Your amber **> 0.6 g** placeholder is fine as a driver-interest cue (that's enthusiastic cornering). Keep it **ambient — never a takeover, never a safety alarm.**
**One car-specific note:** these are **23-year-old tires** (DOT 1003 / March 2003). Sustained high lateral-g is *exactly* the heat-and-load regime where aged-tire belt separation bites. So a soft amber at high *sustained* lateral-g doubles as a quiet "you're loading old rubber hard" nudge — **advisory, not an alarm.** Don't escalate it; just don't let it be invisible either.

### 2.3 ROAD GRADE / ALTITUDE — informational live; valuable logged

Live card: **informational / driver-interest only** — no alarm. The real tuning value is in the **logged** stream: grade lets me compute **grade-corrected load** post-drive (separating "engine working because uphill" from "engine working because boost") — that's server-side analysis in my lane, not a live readout. So: show it for the driver, log it for me.

### 2.4 LIGHT-SENSOR auto-dim — your instinct is RIGHT; strengthen it

**Confirmed, and make it a hard rule:**
- **🔴 takeover = FULL brightness, ALWAYS, independent of the dim curve.** A red alert dimmed into a dark cabin is a safety *failure* — it defeats the entire purpose of the alert.
- **🟡 ribbon = clamped to a guaranteed-readable minimum** (your alert-brightness floor — yes, clamp it independent of the auto-dim curve).
- Auto-dim applies **only** to ambient / informational content (gear, g, grade, the live gauges). Alerts are exempt.

This isn't a preference — it's a safety requirement. An alert the driver can't see at night is worse than no alert, because the system *thinks* it warned them.

---

## Quick-reference confirm/correct table (for Iris)

| Your question | Spool's answer |
|---|---|
| Coolant 🔴 threshold | ✅ ≥ 104 °C / 220 °F (absolute) |
| Coolant 🟡 pre-warn | ✅ YES, but **dwell-gated** — 🟡 ≥104 °C sustained ≥30 s (the old 100–103 °C absolute band is **WITHDRAWN**, see §1.1). 🔴 ≥110 °C is NOT dwell-gated. |
| Knock 🔴 always vs gated | Gated (≥~15–18° non-recovering / knock-sum spike); **ECMLink-only — no alert without it** |
| Voltage / lean tiers + escalation | Tiers above; escalate on low-V **+ boost** (injector-lean) and O2-lean **+ high-load** |
| Other screen-owners | Today: coolant + voltage only. Oil-pressure would be top-🔴 but **no sensor exists** |
| Arbitration | ✅ your default + **live outranks stored** within a tier; live thermal/knock 🔴 un-dismissable |
| Gear derivation owner | ✅ Spool — built/validated this session; `—` for ambiguous, `N` for neutral, never a wrong number |
| G-force color | Informational; 0.6 g amber OK; **never a takeover** (soft aged-tire nudge at high sustained lat-g) |
| Grade/altitude | Informational live; valuable logged (grade-corrected load) |
| Light-sensor alert floor | ✅ YES — 🔴 = full brightness always; 🟡 = readable floor; dim only ambient content |

## Sources

- `knowledge.md` — coolant danger ceiling (104 °C/220 °F head-gasket band), knock-retard envelope (Drives 11/26), voltage source (ELM327 `ATRV`), Mode 02 / knock not OBD-accessible.
- `cards/safe-range-coolant-temp.md`, `cards/safe-range-timing-knock.md`, `cards/safe-range-battery-voltage.md`, `cards/drivetrain-f5m33-gear-ratios.md`, `cards/wheels-tires-potenza-205-55r16.md`.
- This car's captured data: Drive 11 (knock-retard characterization), Drive 26 (new-ECU knock event), Drive 27 (101 °C peak), Drive 30 (gear derivation validation, 14.3 V charging).
