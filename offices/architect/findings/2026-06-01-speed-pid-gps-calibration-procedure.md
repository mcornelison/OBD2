# SPEED-PID calibration procedure — GPS measured-run (new ECU MD326328)

**Author:** Atlas (Architect) · **Date:** 2026-06-01 · **Status:** spec for Spool to operationalize + CIO to drive
**Goal:** replace the new ECU's rough `0.5` seed in `speed_pid_calibration` with an
empirically-derived, `empirical-`-prefixed `correction_factor`, so distance /
avg-speed / gear-inference on drives ≥25 are trustworthy.
**Lane:** Atlas owns the method + data-flow; **Spool owns the ratified factor +
gear constants** (tuning values are sacred); CIO drives the IRL captures.

> Depends on the ECU-identity correction landing first: the calibration row is
> keyed by `ecu_id` → the **MD326328 / E2T61683** `ecu` row (supersedes the
> mis-recorded `MD335287`; see the companion notes to Spool + Marcus, 2026-06-01).
> Don't write the factor until the corrected `ecu` row exists. *(ECU correction
> landed 2026-06-01; prod `ecu` id=2 = `MD326328`.)*

---

## ADDENDUM 2026-06-05 — Strava as the GPS source + FIT reading + decisions (CIO)

CIO decisions this session (drive imminent):
- **GPS source tool = [Strava](https://strava.com).** CIO drives, records, exports
  **a single FIT file**, downloads it into the project. FIT (not GPX/TCX) by his call.
- **SSOT for the scalar = the `speed_pid_calibration` table** (confirmed — §5 path stands).
- **Two-tool split (CIO):** (1) a reader that extracts the GPS truth from the FIT
  file; (2) an aligner that pairs it with the OBD2 drive data and emits the average
  correction scale. **Build (2) only once real data is in hand** (CIO instruction).

**Reading the FIT file (research, sources at bottom):**
- FIT is Garmin/ANT binary. Python parsers: **`fitparse`** or **`fitdecode`**.
- "record" messages carry, per point: `timestamp` (UTC), `position_lat`/`position_long`,
  `speed` (+ often `enhanced_speed`, m/s), `distance` (cumulative m), `altitude`.
- **Gotcha:** FIT lat/long are int32 **semicircles** → degrees = `value × 180 / 2³¹`.
- **Method choice (architectural):** even though FIT *embeds* speed, embedded speed
  is smoothed by the recording device/Strava. For a "source of truth" we **derive
  ground speed ourselves from raw consecutive positions** (haversine ÷ Δt) so we
  control the method; FIT's embedded `speed`/`distance` become an independent
  cross-check, not the input we trust blindly.

**Design refinement — elevate the distance-ratio to a CO-PRIMARY estimator.**
The body below (§2/§3) treats cross-correlation time-alignment as the primary path
and distance-consistency (§4) as only a cross-check. Invert that emphasis, because
FIT hands us cumulative `distance` directly and the clock-skew gotcha (§2) is real:

- **Estimator A — distance-ratio (primary, robust):**
  `scale = Σ GPS_distance / Σ OBD_integrated_distance` over the same window.
  **Immune to clock skew** — needs no time-alignment at all. Simplest, hardest to fool.
- **Estimator B — speed-ratio (diagnostic + scalar-vs-curve gate):** the §2 cross-
  correlation + §3 median-ratio. Its real job is the **scalar-vs-curve gate** (§3.1)
  — confirm the ratio is flat across speed before trusting any single number.
- **Agreement check:** A and B must agree (both ≈ **0.5**, per the gear-math
  prediction). Disagreement = investigate before writing anything.

Both estimators land in the same tool (2); it reports A, B, their spread, and the
scalar-vs-curve verdict. Spool ratifies the final value before it's written (§5).

**Sources:** [python-fitparse](https://github.com/dtcooper/python-fitparse) ·
[fitdecode](https://pypi.org/project/fitdecode/) ·
[Strava export (GPX has no stored speed; it's derived)](https://support.strava.com/hc/en-us/articles/216918437-Exporting-your-Data-and-Bulk-Export)

---

## 0. Why GPS is the right primary reference

The `speed_pid_calibration` schema holds **one multiplicative `correction_factor`
per ECU**: `OBD-SPEED × correction_factor = true speed`. The new ECU reads ~2×
high because its ECMLink tune carries wrong VSS constants (tire-size /
pulse-per-rev / speedo-gear assumption) — a *linear* error, so a single scalar
should fit.

A reference must be **independent of the ECU's VSS error**:
- **Phone / cycling-app GPS** — fully external to the car. Gold standard.
- **Dash odometer / speedometer** — likely independent (separate cluster
  calibration), a strong secondary anchor *if* the 10-second check below confirms it.
- **OBD distance PID 0x31** — **rejected as ground truth**: the ECU derives it
  from the *same* bad VSS constants, so it's wrong by the same factor (circular).
  Useful only as an internal-consistency check that SPEED-integral == distance-PID.

GPS also removes the need for gear-math constants entirely (no gear ratio / tire
circumference required for the primary fit) — gear-math demotes to a cross-check.

**10-second pre-check (do this first):** at a steady cruise, eyeball the dash
speedo vs the live OBD-SPEED value. If dash ≈ true and OBD ≈ 2×, then (a) the
dash is an independent anchor and (b) the error is confirmed scalar before any
data pull.

---

## 1. Capture (CIO drives)

**Tooling the CIO has:** cell-phone GPS + a **cycling GPS app** that exports a
track with **per-point UTC timestamp + speed** (GPX, or CSV/FIT). This is better
than a single measured mile — it yields a dense set of (time, GPS-speed) samples
for a regression fit and the scalar-vs-curve check.

**Drive profile (one run is enough; two is better):**
- Several **steady-state plateaus** (~20–30 s each) at distinct speeds — e.g.
  ~40 / 70 / 100 km/h (≈25 / 45 / 60 mph) on flat road, top gear, no clutch slip.
  Plateaus give clean scalar points across the range.
- Include some **brisk accel/decel transitions** between plateaus. These are the
  alignment fingerprint (§2) — the sharper, the better.
- Note the **drive in the OBD system** (which `drive_id`) and roughly when it
  started, so the right `realtime_data` window is easy to find.

**Both data sources we then have:**
- `realtime_data` rows where `parameter_name='SPEED'` (**unit km/h**,
  `defaultLogData=True` — already logged) with their timestamps.
- The cycling-app export: (UTC time, GPS speed [normalize units → km/h], lat/lon).

---

## 2. Time alignment — the one real gotcha

The CIO's instinct ("match the exact time from the OBD2 data") is right, **if both
clocks are accurate**. The risk: the **Pi clock may not be NTP-synced in the car**
(no internet), so `realtime_data` timestamps can carry a constant offset vs the
phone's (NTP-accurate) GPS timestamps.

- **Simple path:** before the drive, make sure the Pi clock is synced (or note
  the Pi's current time against the phone). Then a direct timestamp join works.
  *Verify Pi clock sync as the first analysis step — don't assume it.*
- **Robust path (recommended, survives clock skew):** **cross-correlate** the two
  speed traces. Resample both to a common 1 Hz grid; slide one against the other
  and take the lag that maximizes correlation — that lag *is* the clock offset.
  The accel/decel transitions (§1) make this unambiguous. Apply the offset, then join.
- A constant offset barely affects the *steady-state* ratio (both sides flat), so
  even an unaligned first pass gives a usable scalar; alignment mainly sharpens the
  transitions and the per-sample fit.

---

## 3. The fit

After alignment, you have paired `(OBD_speed_kmh, GPS_speed_kmh)` samples.

1. **Scalar-vs-curve gate (do not skip):** compute the per-sample ratio
   `GPS / OBD` across the whole speed range. If it's ~constant → the single-scalar
   schema is valid. If it **drifts with speed** → the scalar model is wrong and
   this becomes a **B-076 schema finding** (need a curve / piecewise; the current
   table can't represent it). Flag to Atlas if so.
2. **Estimate the factor** (assuming scalar holds): fit `GPS = k · OBD` through the
   origin (least-squares slope), or take the **median** of the per-sample ratio on
   the steady-state plateaus (median is robust to GPS noise + transition smear).
   `correction_factor = k`. Report the spread (it tells us the confidence).
   - Low-speed GPS samples are noisy/laggy — weight the steady moderate/high-speed
     plateaus; down-weight < ~20 km/h.

---

## 4. Cross-checks (corroboration, not the primary)

- **Dash-odometer delta:** read the odometer before/after a run of known GPS
  distance → independent distance factor. Free, and independent of GPS.
- **Gear-math:** `true_speed = RPM × wheel_circumference / (gear_ratio ×
  final_drive)`. Needs the **wheel circumference** (from the CIO's wheel make/model
  — offered) and the **top-gear + final-drive ratios** (Spool to source for the
  4G63 GST). If gear-math and GPS agree → high confidence; if they diverge, the
  gear constants are wrong, not the GPS. *Bonus:* if the factor resolves to a clean
  fraction, that pins the exact VSS misconfiguration (physical-cause validation).
- **Distance consistency:** GPS-integrated distance vs OBD-SPEED-integrated
  distance over the window should differ by the same factor (sanity that the error
  is internally consistent / linear).

---

## 5. Write the result (writer path; Spool ratifies the value)

Once Spool signs the factor:

```python
insert_speed_pid_calibration(
    session,
    ecu_id=<MD326328 ecu.id>,            # the corrected new-ECU row
    correction_factor=<fitted k>,         # Spool-ratified
    provenance="empirical-gps-correlation-Drive-NN",   # 'empirical-' prefix → gate INCLUDES it
    capture_method="gps_correlation",     # sanctioned enum value
    captured_by="<CIO/Spool>",
    captured_at=<run UTC>,
    notes="GPS cross-correlated; gear-math/odometer corroboration <values>",
)
```

`UNIQUE(ecu_id)` makes this an upsert replacing the `0.5` rough seed; the
`empirical-` prefix flips `select_empirical_calibrations()` to start using it.
`capture_method='gps_correlation'` is already in the sanctioned enum
(`{gps_correlation, gear_math, vendor_spec, default}`).

---

## 6. Validate end-to-end

Re-run distance / avg-speed analytics on a new-ECU drive; cross-check integrated
distance against a known GPS route distance; confirm gear-inference now lands in
plausible gears. This rides the V0.28.1 hardware-deploy / drive-27 drill alongside
US-367 (ECU backfill) — same surface, same drive.

---

## Open decisions for Spool / CIO
1. **GPS-only first pass, or GPS + gear-math together?** (gear-math needs the wheel
   circumference + gear/final-drive ratios). My rec: GPS-primary; gear-math as a
   same-drive corroboration since the CIO can supply wheel data cheaply.
2. **Scalar confirmed?** Depends on §3.1 — must hold before we trust one number.
3. **Provenance/capture_method strings** — `empirical-gps-correlation-Drive-NN` /
   `gps_correlation` proposed; Spool's call on the exact string.
