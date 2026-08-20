# Fix specs — (1) sensor variance/plausibility gate, (2) GPIO6 single ownership, (3) US-552 mode-pin sequencing

**Author:** Atlas (Architect)
**Date:** 2026-08-20
**For:** Marcus (groom into stories) → Ralph (build)
**Status:** design specs, CIO-directed. Each section is independently buildable.

---

# SPEC 1 — Sensor variance/plausibility gate (ONE story, not three)

## 1.1 Problem

Three defects found this week are **one defect**: a value that is not a measurement, persisted or
displayed as `data_source='real'` with nothing marking it.

| # | Instance | Shape |
|---|---|---|
| A | `syncPending = 0` (`card_state_emitter.py:307`) | a count nobody measured |
| B | IMU all-zero frames (43,203 rows, 08-17) | reads "succeed", values are 0.0 |
| C | Magnetometer latched (08-20) | ~3 real reads, then the same value forever |

**Why the existing honest-availability layer cannot catch C** — and this is the load-bearing point:
`-26.7 uT` is **fresh, finite and physically plausible**. Every individual sample passes inspection. The
defect exists only ACROSS samples. **The current gate asks "is this value possible?"; it must also ask
"is this channel actually varying?"**

## 1.2 Design

Two independent checks on the **SUCCESS path only**. Do NOT touch the absence path or the error path —
both are proven honest (`imu read failed ... no sample this poll`, live-verified 08-17).

### Check 1 — implausible magnitude (catches B)

For the IMU accel channel: a frame whose vector magnitude is below `MIN_GRAVITY_MS2` is not a reading
(a stationary sensor must read ~9.81 m/s^2; a moving one reads more, never ~0).

### Check 2 — invariance (catches C)

A channel that returns **N consecutive BIT-IDENTICAL samples** is not reading.

**CRITICAL — test bit-identity, NOT low variance.** Every real sensor dithers +/-1 LSB from thermal
noise and ADC quantization even in a perfectly constant field. That is why this test cannot
false-positive on a legitimately stationary vehicle: a parked car's accel is *nearly* constant but never
*bit-identical*. Empirically confirmed 08-20 — stationary accel produced 743 distinct values in 90 s
while the magnetometer produced 1.

A "variance below threshold" test would be wrong: it needs a magic number and it WILL false-positive on
a genuinely still vehicle. Bit-identity needs no threshold and cannot.

### On detection, route into the EXISTING failed-poll path

Do not build a new silence mechanism. The existing path already writes nothing and logs correctly;
classify an implausible/invariant success AS a failed poll and reuse it. Cheapest correct change.

**Reason vocabulary — must be DISTINCT from `sensor_absent`** (the chip IS enumerated and responding):

- `sensor_mute` — reads succeed, values implausible (check 1)
- `sensor_stale` — reads succeed, values invariant (check 2)

### Derived fields must go typed-NA with their input

`headingDeg` MUST NOT be derived from a stale magnetometer. When a source channel is gated, every field
derived from it publishes typed NULL + reason. **Never a precise bearing from a frozen vector** — the UI
currently prints `236.9` to a tenth of a degree from a latched input.

### 1.2.1 The `syncPending` half (instance A) — BOTH layers or it is a no-op

- Emitter: `card_state_emitter.py:307` — emit `syncPending=None`, not `0`.
- Display: `carousel.js::syncTile` — remove `s.pending == null ? 0 : s.pending`; render "— pending" or
  omit the clause on null.

**Fixing either layer alone changes nothing on screen** (both independently default to zero). One story,
two files, or it ships green and still reads "0 pending".

## 1.3 Acceptance criteria

1. An all-zero IMU frame produces **no persisted row** and a `sensor_mute` reason.
2. N consecutive bit-identical samples on any channel produce **no persisted row** and `sensor_stale`.
3. `headingDeg`/`gradePct`/`pitchDeg` publish typed NULL + reason when their source channel is gated.
4. Absence and error paths are **behaviourally unchanged** (regression test: pull the sensor, still
   `no sample this poll`, still zero rows).
5. **A stationary-vehicle recording does NOT trigger check 2** — the anti-false-positive test. Use real
   captured stationary data, not synthetic constants.
6. `syncPending` renders honestly on BOTH layers; a null from the emitter is not coerced to 0.
7. Rate-limit the failed-poll WARNING — it currently fires per poll at 50 Hz (seq hit 128,422 in
   minutes). Log the transition plus a periodic summary; do NOT silence it.

## 1.4 Non-goals

Do NOT fix the magnetometer ACQUISITION here (that is 1.5). The gate must exist independently — its
whole purpose is catching the next sensor fault, whatever it is.

## 1.5 Companion (separate story) — magnetometer acquisition

Root cause confirmed live: the AK09916 is in **single-measurement mode** — one conversion, back to
power-down, `EXT_SLV_SENS_DATA` holds the last value because nothing re-triggers it.

**A complete fix is NOT established.** Measured, fresh init, 8 stationary samples each:

| `MagDataRate` | distinct/8 |
|---|---|
| default (production) | 1 (latched) |
| `RATE_10HZ` | 1 (latched) |
| `RATE_100HZ` | 1 — **all zeros** |
| `RATE_50HZ` | **3** — partial |

`CNTL2` is the right control surface but the correct configuration needs real investigation, including
whether the ICM aux I2C master needs explicit cyclic-polling setup. **Do not merely set 50 Hz and
declare victory** — acceptance must be "N distinct values across a rotation", not "it changed once".

**Library defect to work around and report upstream:** `adafruit_icm20x.magnetometer_data_rate` getter
has **no `return`** — it reads `_AK09916_CNTL2` and discards it, returning `None`. Do not use it to
verify the fix; read the register directly.

**Version suspicion:** `adafruit-circuitpython-icm20x` is at **2.1.10** against a `>=1.0.0` constraint —
a MAJOR-version jump, and aux-master behaviour is exactly what changes across one. Check the 1.x to 2.x
changelog before writing code.

---

# SPEC 2 — GPIO6 single ownership

## 2.1 Problem

`PldSensor` (the X1209 GPIO6 external-power ground truth) is constructed in **two processes**:

```
src/pi/obdii/orchestrator/lifecycle.py:2342   -> eclipse-obd.service
src/pi/power/power_watch/__main__.py:376      -> eclipse-powerwatch.service
```

A GPIO line is an **exclusive OS resource**. Whichever starts second gets `GPIO busy` and latches the
power-present fallback. Verified live: powerwatch (PID 739) holds the line, `eclipse-obd` loses it every
boot. This violates the contract `power_source_provider.py:24-33` declares —
*"consumers... never acquire power source any other way."*

## 2.2 Design

1. **`eclipse-powerwatch` is the sole owner.** It is the safety-critical watcher; power state is its job.
2. **`eclipse-obd` must NOT construct a `PldSensor`.** It CONSUMES the fact — same posture as the
   carousel consuming `states/*` rather than polling hardware. Publish via a state file
   (e.g. `states/power-source`) written by powerwatch, following the existing emitter pattern.
3. **Preserve the unreadable-to-power-present invariant.** It is correct: never self-shutdown on an
   unreadable signal.
4. **But make permanent unavailability LOUD.** Today it warns once at init and then runs forever in a
   degraded mode indistinguishable from healthy. **A safe default that never clears is a disabled
   subsystem wearing a safety label.** Surface it as a degraded source in `system-status` (the US-429
   honest-availability slot exists) so the operator can SEE that safe-shutdown protection is off.
5. **Powerwatch must log its arm decision to the journal.** Today it emits ZERO application log lines —
   neither the success INFO nor the failure ERROR, both of which are unconditional on their branches
   (`__main__.py:439-456`). We are currently blind to whether the safety service armed. Fix the logging
   configuration so those lines reach journald.

## 2.3 Acceptance criteria

1. Exactly ONE process opens BCM GPIO6; verifiable with `lsof /dev/gpiochip*`.
2. `eclipse-obd` obtains power source WITHOUT touching the GPIO, and no `GPIO busy` warning appears.
3. Behaviour is **independent of service start order** (today's outcome is boot-order-dependent and
   could silently flip).
4. `journalctl -u eclipse-powerwatch -b` shows the arm decision on every boot.
5. A forced-unavailable PLD surfaces as a degraded source in `system-status`.

## 2.4 Out of scope — SEPARATE, and the CIO's call

**This spec does NOT fix "key-off kills the Pi instantly."** Powerwatch holds a working pin
(`gpio-6 (GPIO6 |lg) in hi` = power present, correct) and the UPS battery is healthy (4.18 V / 98 %), so
detection is not obviously the blocker. **"Instantly" points at the X1209 HOLD-UP path** — whether the
UPS output actually powers the Pi on input loss, or whether the Pi is fed from the car feed with the
X1209 only monitoring. That is wiring, in the CIO B-063 domain, not a code fix.

---

# SPEC 3 — US-552 mode-pin sequencing

## 3.1 Problem

`cmdline.txt` carries no `video=` token; the panel negotiates whatever it advertises. Measured 08-20
with the 3.5in panel connected: **`fb0 = 1280x720`**, not the native 480x320 — **6x the pixel count**.

`set-display-mode.sh` behaved CORRECTLY: it writes only when EXACTLY ONE connector reports `connected`,
else WARNs and exits 0 so an unplugged panel cannot block a deploy (`:31,:157-159`). No panel was
attached at deploy time. **Not a deploy bug** — but the pin has therefore never been applied or
validated on real hardware.

## 3.2 Design

1. **Make the pin re-assertable outside a full deploy** — a standalone invocation the CIO or a later
   boot can run once the panel is present. Today its only path is deploy-time, which is exactly when the
   panel is least likely to be attached.
2. **Pin the connector that actually reports `connected` at run time — never an assumed one.** Mapping
   confirmed 08-20: port 1 = 3.5in panel (`HDMI-A-1`), port 2 = desk monitor (`HDMI-A-2`, EDID Samsung
   SA300/SA350). **Pinning 480x320 onto a desktop monitor would blank it.**
3. **Verify after reboot** — assert `/sys/class/graphics/fb0/virtual_size` equals the target and report
   honestly if not. The change is next-boot-only; do not let the deploy imply the panel is already 1:1.

## 3.3 Acceptance criteria

1. With the 3.5in panel attached, after pin plus reboot: `fb0 = 480,320`.
2. With no panel (or more than one connector) attached: WARN plus exit 0, nothing written (unchanged).
3. The verification step reports the ACTUAL negotiated mode, not the intended one.

## 3.4 Why this should go FIRST

It is owed anyway (F-127 in-car legibility is still outstanding), it is cheap, **and it is the last
untested lever on the AllocateRingBuffer freeze** — which is now confirmed in-car (22,548 markers, 2
watchdog restarts mid-drive, 08-20). Every freeze observation so far has been at 1080p or 720p, never at
the shipping 480x320. Eliminate that variable before anyone scopes the freeze itself.

---

# Suggested sprint shape

| Story | Spec | Priority | Note |
|---|---|---|---|
| Mode pin re-assert + verify | 3 | **First** | cheap; unblocks F-127; last freeze variable |
| Variance/plausibility gate | 1 | High | one story, all three fabrications |
| Magnetometer acquisition | 1.5 | High | separate; needs real investigation |
| GPIO6 single ownership | 2 | High | plus powerwatch logging |
| Watchdog defects | (08-17 finding §3) | High | threshold, `--grep` exit-1, lag, budget |

**Not in this sprint:** the freeze itself (re-measure after the mode pin); the X1209 hold-up path (CIO
hardware); hard/soft-iron compass calibration (only meaningful AFTER 1.5 lands — you cannot calibrate a
sensor that is not reading).
