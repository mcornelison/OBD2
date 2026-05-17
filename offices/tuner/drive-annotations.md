# Drive Annotations — Pre-Mod Baseline Shelf

> Captured by Spool from CIO interview, 2026-05-09 (after drive_id=7).
> Source: `data/spool/drive1-7.txt` (CIO direct input).
>
> **Purpose**: Capture tuning-relevant context that the OBD telemetry doesn't record — fuel grade, fuel level, ambient conditions, driving intent, seat-of-pants observations. The schema doesn't have columns for these yet (Sprint 28+ candidate per Spool's PM note 2026-05-09); until it does, this file is the canonical source.
>
> **Maintenance**: Append-only per drive. When a drive is captured, interview the CIO same-day if possible. Don't overwrite — annotations are the historical record of what conditions a drive happened under.

---

## Cross-Drive Observations (read these first)

### Fuel grade is constant across the entire pre-mod baseline shelf

> **⚠ CORRECTION 2026-05-15 (CIO directive):** Fuel grade was **[EXACT: 93 octane — DO NOT CHANGE]**, NOT 91. CIO misreported 91 in the original 2026-05-09 interview; corrected the record 2026-05-15. ALL past drives (3–16) AND all future fillings are 93 octane until the E85 flex-fuel sensor is installed + wired. Every "91 octane" below is superseded by 93. `obd2db.drive_annotations` table updated (backup `/tmp/drive_annotations_pre_octane_fix_20260515.sql` on chi-srv-01). Analytical impact: the knock-retard baseline in `knowledge.md` is a 93-octane baseline; no octane-uplift A/B is extractable.

All drives (3–16) ran **[EXACT: 93 octane — DO NOT CHANGE] premium**. CIO commits to premium "until we add E85 capability." This is a major confound *eliminated* — when comparing drives across the shelf, fuel grade is not a variable. **Drive 7's WOT pull (100% engine load, MAF 158.69 g/s, timing 34° BTDC, no knock pull) is interpretable cleanly as 93-octane stock-EPROM behavior**, not as "we don't know what was in the tank."

### Drive 5/6/7 fuel chronology — bottom of tank → fill → top of tank

| Drive | Fuel level at start | Notes |
|---|---|---|
| 3 | < 1/4 | parked-idle, low fuel |
| 4 | < 1/4 | same day system test (parked) |
| 5 | < 1/4 | post-jump-start, parked-idle (rainy day system test) |
| **6** | **E (Empty)** | **Drive intent was "get gas" — drove on bottom of tank to the pump** |
| **7** | **F (Full)** | **Same-day fill (5/8/2026) before the highway/WOT segment — fresh 91 in tank** |

**Tuning implications**:
- **Drive 6's LTFT lock at -6.25% on a near-empty tank** is a free validation of fuel system pressure stability under low tank conditions. The ECU did not show drift from fuel pickup uncovery during city driving, which means stock fuel pump + stock pickup + smooth-route driving = stable fueling even at E.
- **Drive 7's WOT pull on a freshly-filled tank** is the cleanest possible WOT data — fresh fuel, full pickup coverage, max fuel system supply. If a future under-load drive on a low tank shows different behavior under WOT, the fuel system (not the engine) is the suspect.
- For future drives, **prefer logging fuel-level transition events.** A drive that crosses the 1/4 mark mid-pull is a mixed-state capture and should be interpreted with caution.

### Drives 3, 4, 5 are IDLE-ONLY system tests, NOT driving captures

Despite being labeled as "drives" in the schema, drives 3, 4, and 5 were all CIO sitting in a parked car running system-test data captures. **They contain zero throttle-input data, zero speed data, zero load-state data.** They are valuable for:
- Idle-cell LTFT/STFT behavior
- Coolant warm-up curve (thermostat function — opens at 80°C, confirmed 4× across drives 3/4/5/6)
- Idle RPM stability (Drive 5: ±16 RPM spread)
- Closed-loop O2 switching at idle
- Battery/alternator behavior at engine running, no load

They are NOT useful for:
- Load-cell fuel trim analysis
- Throttle response
- WOT analysis
- Driving-style anything

**Therefore**: the pre-Drive-6 baseline shelf is **idle-only**. Drive 6 is the first actual city-driving capture in the project. Drive 7 is the first under-load capture. The "5-drive baseline shelf" framing in knowledge.md is correct in row count but mixed in driving-state.

### All 5 drives — no seat-of-pants anomalies

CIO reported `none` for all 5 drives. Combined with zero DTCs / zero MIL across all captures, the engine has shown no observable issues across the entire pre-mod shelf, both via the data and via the driver. **This is the cleanest "engine baseline = healthy" assertion the project has had.**

### Weather observations across the shelf

| Drive | Ambient °F | Weather | Pavement |
|---|---:|---|---|
| 3 | 52 | overcast | implied dry (parked) |
| 4 | 45 | rainy | parked, n/a |
| 5 | 45 | rainy | parked, n/a |
| 6 | 65 | cloudy | implied dry |
| 7 | 67 | cloudy | implied dry |

Both actual driving captures (6 + 7) happened in dry, mild conditions. **No wet-pavement driving capture exists yet** — for future under-load analysis, a wet-pavement WOT comparison will tell us whether traction events confound any fueling/timing observations.

---

## Per-Drive Annotations

### Drive 7 — 2026-05-08 evening — Highway + WOT (10 min, 84 mph, 100% load pull)

**Significance**: First under-load capture in project history. Authoritative under-load baseline in `knowledge.md`.

| Field | Value | Spool note |
|---|---|---|
| fuel_grade | 93 octane | Premium, CIO standard |
| fuel_level_at_start | F (Full) | Same-day fill 5/8/2026 — fresh tank |
| last_fill | 2026-05-08 | Pre-Drive-7, post-Drive-6 |
| ambient_temp_F | 67°F (~19°C) | Matches IAT min in knowledge.md (19°C) |
| weather | cloudy | Dry pavement implied — clean WOT data |
| engine_soak_state | "cold" per CIO | **DISCREPANCY**: OBD telemetry shows coolant=74°C at start = warm-restart, not cold. Best interpretation: CIO meant ambient was cool (67°F), not engine. Resolution: treat Drive 7 as **warm-restart, ~40 min after Drive 6 end** per knowledge.md timing data. |
| route | city | Highway segments included per knowledge.md (84 mph reached). "City" framing is loose — actual route was mixed city/highway with the WOT pull on the highway portion. |
| driving_intent | errand | NOT a planned datalog pull — incidental WOT during normal driving. **This makes the under-load data more valuable**, not less: it's representative of how the car gets used. |
| anything_unusual | none | Confirms zero-DTC zero-MIL data record |

**Authoritative for**:
- Under-load fueling on [EXACT: 93 octane — DO NOT CHANGE] (LTFT load-cells, STFT swings during enrichment)
- WOT timing advance ceiling on stock EPROM (34° BTDC observed)
- MAF behavior at stock turbo peak (158.69 g/s)
- Coolant + IAT thermal margin under sustained load (coolant max 91°C / IAT max 26°C)
- Knock-pull baseline (none observed) on full tank of premium

---

### Drive 6 — 2026-05-08 morning — Cold-start city (16 min)

**Significance**: First actual driving capture in project history. Authoritative cold-start city baseline.

| Field | Value | Spool note |
|---|---|---|
| fuel_grade | 93 octane | Premium |
| fuel_level_at_start | E (Empty) | **Below the F-gauge calibrated minimum** — drive intent was to get to the pump |
| last_fill | 2026-05-08 (this drive ENDED with a fill) | Drive 6 was the run-down drive; Drive 7 was post-fill |
| ambient_temp_F | 65°F (~18°C) | |
| weather | cloudy | Dry pavement implied |
| engine_soak_state | cold | True cold-start — sat overnight per the morning timestamp |
| route | city | Stop-go, low-speed (max 46 mph per knowledge.md) |
| driving_intent | get gas | Light pedal use throughout |
| anything_unusual | none | |

**Authoritative for**:
- Cold-start warm-up curve to operating temp (38°C → 89°C, thermostat opens at 80°C)
- Idle LTFT cell baseline (-6.25%, re-locked after post-jump-start adaptation per `knowledge.md`)
- Light-load fuel trim cell drift (idle = -6.25%, light-load cells = closer to 0%)
- Fuel system stability at low tank under smooth driving (no anomalies on E)

**Caveat**: Because the tank was at E throughout, this is NOT a representative "city driving" capture for fuel system load testing. Any future-drive comparison should match fuel level, or note the discrepancy.

---

### Drive 5 — 2026-04-29 evening — Post-jump-start parked-idle system test (17:39 min)

**Significance**: Authoritative warm-idle baseline. **NOT a driving capture** — CIO sat in parked car running system test.

| Field | Value | Spool note |
|---|---|---|
| fuel_grade | 93 octane | Premium |
| fuel_level_at_start | < 1/4 | Low tank but stationary, no pickup uncovery risk |
| last_fill | unknown | Pre-Sprint-15-cleanup era |
| ambient_temp_F | 45°F (~7°C) | Cold ambient |
| weather | rainy | Sat in car during rain |
| engine_soak_state | cold | Started cold, captured full warm-up curve |
| route | parked throughout — idle-only sit | **NOT DRIVEN** |
| driving_intent | system test | OBD pipeline / data capture validation |
| anything_unusual | none | |

**Trigger context per knowledge.md**: Earlier same day, CIO had used the Eclipse battery to jump another car, which caused an ECU adaptation reset. Drive 5 captured the ECU's active re-learning behavior (LTFT ranging -7.03 to -4.69, 3 quantized notches). The "post-jump-start" framing is what makes Drive 5 historically interesting — it was the first capture of the ECU's adaptation mode in action.

**Authoritative for**:
- Warm-idle baseline (RPM 753-785 ± 16, MAF 3.04-3.14 g/s)
- LTFT post-disturbance re-learning behavior (closed by Drive 6)
- Coolant warm-up curve (~6°C/min ramp to 89°C steady-state)
- Long-duration idle stability (17:39 min)

**NOT authoritative for**: anything load-related, throttle-related, speed-related, or driving-related.

---

### Drive 4 — 2026-04-29 morning — Parked-idle system test (10:47 min)

**Significance**: Earlier same-day pair to Drive 5 (pre-jump-start version). Idle-only.

| Field | Value | Spool note |
|---|---|---|
| fuel_grade | 93 octane | |
| fuel_level_at_start | < 1/4 | Same day as Drive 5 |
| last_fill | unknown | Pre-cleanup era |
| ambient_temp_F | 45°F | Same day, similar ambient |
| weather | rainy | |
| engine_soak_state | cold | |
| route | parked throughout — idle-only sit | **NOT DRIVEN** |
| driving_intent | system test | |
| anything_unusual | none | |

**Authoritative for**: same idle-only categories as Drive 5, but with PRE-jump-start LTFT lock (-6.25% flat across 197 samples). Drive 4 is the "before" half of the LTFT adaptation story Drive 5 captured the "during" half of.

---

### Drive 10 — 2026-05-10 early AM — Garage pull-in (2 min 10 sec)

**Significance**: NOT ELIGIBLE FOR BASELINE. Parking maneuver. Captured for completeness only.

| Field | Value | Spool note |
|---|---|---|
| fuel_grade | 93 octane | Same chain as Drive 8 + 9 |
| fuel_level_at_start | F | Burned ~30+18+2 min total since 5/8 fill — still at F per gauge |
| last_fill_date | 2026-05-08 | |
| ambient_temp_F | 73°F (~23°C) | Same evening as Drive 9 |
| weather | overcast | |
| engine_soak_state | warm-restart | ~30 min after Drive 9 ended |
| route | driveway / garage approach | |
| driving_intent | park in garage | |
| anything_unusual | Drain id=12 opened 8 sec into drive | Pi went to UPS battery DURING engine-running. Smoking-gun confirmation that stereo USB-C is undersized. |
| is_actual_drive | TRUE | Brief but real driving event |

**NOT eligible** because: (1) 2:10 too short to capture meaningful tuning data, (2) power flicker mid-drive (drain id=12 opened 8 sec post drive_start). Together with Drive 9 demonstrates the stereo USB-C hardware path is a dead end — fuse-box wiring required before further IRL test drives.

---

### Drive 9 — 2026-05-10 early AM — Pizza run (~30 min, USB-C loose)

**Significance**: HELD OUT FROM BASELINE SHELF. Hardware-induced data quality issue, not engine behavior issue.

| Field | Value | Spool note |
|---|---|---|
| fuel_grade | 93 octane | |
| fuel_level_at_start | F (Full) | ~18 min since Drive 8 + 2-3 min around-the-block test → still essentially F |
| last_fill_date | 2026-05-08 | No new fill since |
| ambient_temp_F | 73°F (~23°C) | Slightly cooler than Drive 8 |
| weather | overcast | |
| engine_soak_state | warm-restart | ~37 min after Drive 8 ended |
| route | city | |
| driving_intent | go get pizza | |
| anything_unusual | **USB-C loose, dashboard flickering between `power=car` and `power=battery` throughout drive** | Pi cycling between wall and UPS power |
| is_actual_drive | TRUE | Real drive, just with compromised data capture |

**Capture quality issue**: 1,095 rows over 30 min = 36 rows/min. Compare Drive 8: 459 rows/min. Drive 6: 443 rows/min. Drive 7: 422 rows/min. **Drive 9 is 12× lower than expected.** Cause: Pi was brownout-throttling under unstable USB-C power; data logger was probably running in degraded mode. Drains id=10 + id=11 opened around drive boundaries from power flicker events.

**NOT comparable** to other shelf drives. Engine itself was running fine — no DTCs, no MIL — but the recording side was broken. Confirms the USB-C hardware blocker on its own; even if the DriveDetector + data logger code were perfect, this drive's data would be unusable due to power instability.

---

### Drive 8 — 2026-05-09 evening — Cold-start city/highway, portable-inverter Pi power (~18 min, captured CLEAN)

**Significance**: First **cold-start + city/highway** baseline drive (Drive 6 was cold-start city only; Drive 7 was warm-restart highway+WOT; Drive 8 spans both). **JOINS the shelf** as a baseline. **Power source was Pi's stock 5A supply fed by a camping-battery AC inverter — NOT car-coupled stereo USB-C.** Same power model as Drives 6+7.

| Field | Value | Spool note |
|---|---|---|
| fuel_grade | 93 octane | |
| fuel_level_at_start | F (Full) | First drive after Drive 7's 5/8 post-fill state, no driving in between |
| last_fill_date | 2026-05-08 | Same chain as Drive 7 |
| ambient_temp_F | 75°F (~24°C) | Mild May evening |
| weather | cloudy | Dry pavement implied |
| engine_soak_state | cold | True cold-start — coolant 23°C at start, ambient ~24°C |
| route | city | Mixed city/highway per the data (Speed up to 85 mph) |
| driving_intent | errand | |
| anything_unusual | none | Clean drive, no operator-observed issues |
| is_actual_drive | TRUE | |

**Capture quality**: 8,268 rows over 18 min = 459 rows/min. Matches Drive 6 (443) and Drive 7 (422). **Stable power throughout — NO drains opened during drive.** Pi was on its stock 5A power supply, fed by a camping-battery-with-inverter setup (Mike was in the car with the portable battery; Pi power state was DECOUPLED from car ignition state — key-on/off didn't affect Pi).

**Authoritative for**:
- Cold-start warm-up curve under driving load (coolant 23°C → 92°C ramp)
- City + highway combination behavior on stable Pi-spec power (no WOT — RPM peak 4055, max load <90%)
- Cleanest "engine cold-start + transition to operating temp + driving load" baseline on the shelf

**Compare against Drive 7** (warm-restart highway+WOT, also portable-inverter power): Drive 8 fills the cold-start half of "city + highway" envelope that Drive 7 left open. Drive 8 + 7 together approach a "complete envelope" pre-mod baseline minus the gap items (sustained WOT, hot-soak restart, wet-pavement, cold-engine WOT).

**The car-coupled-power validation Drive 8 did NOT provide** is the role intended for Drives 9 + 10, both of which failed: the stereo USB-C path is undersized. Future drive 11 (post-fuse-box-wiring) will be the actual first car-coupled-power baseline.

---

### Drive 3 — 2026-04-23 — First real engine data, parked-idle system test (9.5 min)

**Significance**: First real engine data in the project. Idle-only.

| Field | Value | Spool note |
|---|---|---|
| fuel_grade | 93 octane | |
| fuel_level_at_start | < 1/4 | |
| last_fill | unknown | |
| ambient_temp_F | 52°F (~11°C) | Slightly warmer than 4/5 |
| weather | overcast | |
| engine_soak_state | cold | |
| route | parked throughout — idle-only sit | **NOT DRIVEN** |
| driving_intent | system test | |
| anything_unusual | none | |

**Authoritative for**: idle behavior, cold-warm cycle, LTFT lock at -6.25% (the original observation). Superseded as warm-idle authority by Drive 5 (longer capture, more samples) but remains the historical first.

---

## Going Forward — Annotation Capture Discipline

For every future drive, capture at minimum:

```
fuel_grade:           [octane number]
fuel_level_at_start:  [F / 3/4 / 1/2 / 1/4 / E]
last_fill:            [date — flag if grade changed at the pump]
ambient_temp_F:       [actual reading from phone/dashboard if possible]
weather:              [sunny/cloudy/rain — note any pavement state]
engine_soak_state:    [cold / warm-restart (<30 min) / hot-restart (<5 min)]
route:                [city / highway / mixed / specific roads]
driving_intent:       [commute / errand / spirited / datalog pull]
anything_unusual:     [seat-of-pants observations]
```

**Best capture timing**: same day as the drive, before memory fades. After 1 week, ambient temp recall starts drifting. After 2 weeks, fuel-level recall starts drifting. Last_fill recall drifts the slowest because of phone receipts.

When the schema-side `drive_annotations` table or `mod_state` column ships (PM note 2026-05-09 Item 1), this file becomes the migration source. Until then, this is canonical.
