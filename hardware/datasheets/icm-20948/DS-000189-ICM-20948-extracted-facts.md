# TDK InvenSense ICM-20948 — extracted electrical facts

**Source of truth:** `DS-000189-ICM-20948-v1.3.pdf`, beside this file. Every row below was read out
of that PDF on 2026-09-22 and is **DOCUMENTED**, not recalled.

**Provenance, retrieval traps and the library index live in [`../README.md`](../README.md)** — that
file owns them; this one does not repeat them. ⚠️ Two you should not rediscover the hard way:
Adafruit's `adafru.it/Iqf` link **resolves to an ST LSM6DS33 — a different part**, and
`product.tdk.com` answers an automated fetch with a **533-byte `Access Denied` HTML page that lands
as a file named `.pdf`**. **Check the part number on page 1, and the `%PDF-` header, before
trusting either.**

⚠️ **Not to be confused with `hardware/enclosures/case-imu-icm20948/datasheets/adafruit-…pdf`** —
that is the Adafruit **breakout guide** (board pinout, wiring, CircuitPython usage). It carries no
specification tables and contradicts itself on the gyro unit. **For any electrical number, this
file and the PDF beside it are the authority.**

> **Why this exists.** On 2026-09-21 three of four errors in one tuning fact-check traced to no TDK
> datasheet being held anywhere — figures were written as *"the datasheet specifies"* while actually
> being recalled. Landed at the CIO's instruction under his 2026-09-22 grounding rule.

---

## Gyroscope (p. 11)

| Fact | Value | Conditions |
|------|-------|------------|
| Full-scale range | **±250 dps** at `GYRO_FS_SEL=0` (±500/±1000/±2000 at 1/2/3) | |
| Sensitivity scale factor | **131 LSB/dps** at `GYRO_FS_SEL=0` | |
| Sensitivity initial tolerance | **±1.5 %** | 25 °C |
| Sensitivity variation over temperature | **±3 %** | −40 to +85 °C |
| Nonlinearity | **±0.1 %** | best-fit straight line, 25 °C |
| 🔴 **Initial ZRO tolerance** | **±5 dps** | **25 °C, component-level** |
| 🔴 **ZRO variation over temperature** | **±0.05 dps/°C** | **−40 to +85 °C** |
| Noise spectral density | **0.015 dps/√Hz** | noise BW 10 Hz, `GYRO_FS_SEL=0` |

### 🔴 What the two ZRO rows mean for the parked-grade defect (mechanism #3)

**Zero-rate output is the gyro's standing output with no rotation — a bias, in dps. It is a
specified property of a healthy part, not a fault.**

**1. The part is good, so the defect cannot be fixed by replacing it.**

    measured healthy residual (gyro_y, parked)   0.01304 rad/s = 0.747 dps
    datasheet Initial ZRO Tolerance              +/-5 dps
    => 6.7x INSIDE the part's own specification

Corroborated in-repo: the gyro-quality classifier quoted at `src/pi/sensors/pitch_fusion.py:169-174`
measured **healthy 0.0127–0.0153 rad/s over 4,337 quiet minutes**. ⇒ **A ZRO of this size must be
estimated and subtracted, never swapped out.** It is also a second, independent reason the
**per-boot re-estimate is right and a stored constant is wrong** — see the tempco row.

**2. 🔴 The resulting error is TEMPERATURE-DEPENDENT and nothing currently models it.** The
complementary filter settles at `accelPitch + rate × τ` with `DEFAULT_PITCH_TAU_S = 5.0 s`, so a
standing rate becomes a standing pitch error. Applying **±0.05 dps/°C**:

| cabin ΔT | added bias | phantom pitch | phantom grade |
|---|---|---|---|
| baseline (measured) | 0.01304 rad/s | 3.74° | **6.5 %** |
| +20 °C | 0.0175 rad/s | 5.0° | **8.7 %** |
| +30 °C | 0.0262 rad/s | 7.5° | **13.2 %** |
| +40 °C | 0.0349 rad/s | 10.0° | **17.6 %** |

⚠️ **Every row is still BELOW the US-749 plausibility guard**, which needs `11.36° / 5 s =
0.0397 rad/s` to trip. **A car parked in the sun can carry 2–3× the phantom of one in shade and
never raise a flag. Size mechanism #3 as a 6–18 % temperature-dependent band, not a fixed 6.5 %.**

## Accelerometer (p. 12)

| Fact | Value | Conditions |
|------|-------|------------|
| Full-scale range | **±2 g** at `ACCEL_FS=0` | |
| Sensitivity scale factor | **16,384 LSB/g** at `ACCEL_FS=0` | |
| 🔴 **Sensitivity initial tolerance** | **±0.5 %** | component-level |
| Sensitivity change vs. temperature | **±0.026 %/°C** | −40 to +85 °C, `ACCEL_FS=0` |
| 🔴 **Zero-g initial tolerance** | **±25 mg** component-level, **±50 mg** board-level, all axes | |
| 🔴 **Zero-g level change vs. temperature** | **±0.80 mg/°C** | 0 to +85 °C |
| Nonlinearity | **±0.5 %** | best-fit straight line |
| ADC word length | **16 bit**, two's complement | |

⚠️ The driver's `initialize()` sets accel full scale explicitly to **±8 g**, not the `ACCEL_FS=0`
±2 g the headline rows assume. Read the scale-factor row for the range actually selected.

### 🔴 These rows discriminate OFFSET from SCALE — and they revise US-783

The resting excess on the up axis is **+0.180 m/s²**. Two models fit it, and the datasheet does not
treat them equally:

    read as OFFSET:  +18.35 mg   vs +/-25 mg component, +/-50 mg board   -> INSIDE spec
    read as SCALE :  +1.835 %    vs +/-0.5 % sensitivity tolerance       -> 3.67x OUTSIDE spec

⇒ 🔴 **The multiplicative (scale) model requires the part to be out of its own sensitivity spec by
nearly 4×; the additive (offset) model requires only ordinary, in-spec zero-g offset.** **Offset is
much the better-supported model.**

**Parked, the two are indistinguishable** — they give identical corrections, which is why millions
of parked samples could not separate them. **In motion they diverge**, and in-motion trust is
exactly what US-783 exists to provide: under 0.5 g braking a scale correction trims the longitudinal
axis ~1.8 % that an offset would leave alone. **Applying the wrong model does not merely fail to
help — it injects error on the axis that matters most, under braking.**

⚠️ **A third model, considered and eliminated:** mount tilt cannot explain it. A tilted board makes
the up axis read **g·cos θ — less than g, not more** — so tilt has the wrong sign. **Local gravity
is not the explanation either:** Chicago's ~9.8036 m/s² differs from standard 9.80665 by **0.31 mg**,
also the wrong sign and ~50× too small.

🟢 **The discriminator is a six-position tumble test** (read ‖a‖ with each axis up and down): an
offset makes each orientation read g plus that axis's own offset, differently; a scale makes every
orientation read g × 1.018 alike. ⚠️ **Hands required, and it voids the current mount
characterisation — pair it with the next remount.**
⚠️ **What the tumble test CANNOT show:** it is a static, single-temperature measurement. It cannot
separate the temperature-dependent part of the offset (**±0.80 mg/°C** — a 20 °C swing moves zero-g
~16 mg, *as large as the whole effect*) from the fixed part, unless it is repeated at two
temperatures. **A one-temperature tumble gives the model, not a constant good across seasons.**

## Magnetometer — AK09916 (p. 13)

| Fact | Value |
|------|-------|
| Full-scale range | **±4900 µT** |
| Sensitivity scale factor | **0.15 µT/LSB** |

## Temperature sensor (p. 14)

| Fact | Value | Conditions |
|------|-------|------------|
| Operating range | **−40 to +85 °C** | ambient |
| Sensitivity | **333.87 LSB/°C** | untrimmed |
| Room-temp offset | **0** | at 21 °C |

🔴 **The part HAS a temperature sensor; our driver does not expose it.** This settles what was
briefly an open *part-identity* doubt — a plausible dithering 26.85–27.18 °C read at `0x69` was
suspected to mean the part is not what we believe. **It is the genuine part** (`WHO_AM_I = 0xEA`
read live), and this table is the primary-source confirmation the register exists. The Adafruit
**CircuitPython** driver (ours, 2.1.10) has no `temperature` property; the **Arduino** driver does.
**Both true, at different layers.** ⇒ **A-34's register assumptions are not in doubt.** Whether to
read `TEMP_OUT` past the driver is the CIO's call.

⚠️ **Revision note.** This is rev **1.3**; TDK's current web revision is **1.5**. The rows carrying
our error budgets — gyro **±5 dps** and **±0.05 dps/°C** — were checked in **both** and are
identical. Rows outside those two are verified against 1.3 only.

🔴 **Still not held locally: the Maxim MAX17048 and the Geekworm X1209 wiki.** The `STATUS (0x1A)` /
`RI` semantics the **F-048** ruling rests on, and the **2.1 A charge-current** safety finding, both
remain **RECALLED, not documented.** Tracked as human tasks in [`../README.md`](../README.md).
