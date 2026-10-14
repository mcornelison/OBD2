# TDK InvenSense ICM-20948 — Authoritative Electrical Facts

**Source of truth:** `DS-000189-ICM-20948-v1.3.pdf` (this folder) — the **TDK/InvenSense part
datasheet**, Document Number `DS-000189`, **Revision 1.3**, 89 pages.
`sha256 5a6c1b7b71633986bec05439335844a91769e46f9d90c2602d0f7c1a559ae016`, 1,142,045 bytes.
Landed 2026-09-22 (ARCH-044) at the CIO's instruction, after it was established that **no TDK
datasheet was held anywhere on the share or in the repo.**

⚠️ **This is a different document from `adafruit-tdk-invensense-icm-20948-9-dof-imu.pdf`** beside
it. That one is the **Adafruit breakout guide** — board pinout, wiring and CircuitPython usage. It
does **not** carry the part's electrical specification tables, and it is **self-contradictory on
the gyro unit** (prose says degrees/sec, its code prints rad/s). **For any electrical or error-budget
number, this file is the authority; for board/wiring questions, use the Adafruit guide.**

> **Why this document had to exist.** On 2026-09-21 three of four errors in a single tuning
> fact-check traced to this datasheet being absent — facts were written as *"the datasheet
> specifies"* while actually being **recalled**. Every row below was read out of the PDF in this
> folder on 2026-09-22 and is **DOCUMENTED**, not recalled.

---

## Gyroscope — the rows our pitch/grade error budget rests on (p. 11)

| Fact | Value | Conditions |
|------|-------|------------|
| Full-scale range | **±250 dps** at `GYRO_FS_SEL=0` (±500/±1000/±2000 at 1/2/3) | |
| Sensitivity scale factor | **131 LSB/dps** at `GYRO_FS_SEL=0` | |
| Sensitivity tolerance | **±1.5 %** | 25 °C |
| Sensitivity variation over temperature | **±3 %** | −40 °C to +85 °C |
| Nonlinearity | **±0.1 %** | best-fit straight line, 25 °C |
| 🔴 **Initial ZRO tolerance** | **±5 dps** | **25 °C, component-level** |
| 🔴 **ZRO variation over temperature** | **±0.05 dps/°C** | **−40 °C to +85 °C** |
| Noise spectral density | **0.015 dps/√Hz** | noise BW = 10 Hz, `GYRO_FS_SEL=0` |

### 🔴 What those two ZRO rows mean for this vehicle

**Zero-rate output (ZRO) is the gyro's standing output with no rotation applied — a bias, in dps.**
It is a normal, specified property of a healthy part, not a fault.

**1. Our measured healthy bias is well inside spec — the part is good.**

    measured healthy residual (gyro_y, parked)   0.01304 rad/s = 0.747 dps
    datasheet Initial ZRO Tolerance              +/-5 dps
    => we are 6.7x INSIDE the part's own specification

Corroborated independently in-repo: the gyro-quality classifier quoted at
`src/pi/sensors/pitch_fusion.py:169-174` measured **healthy 0.0127–0.0153 rad/s over 4,337 quiet
minutes**. ⇒ **A ZRO of this size can never be "fixed" by replacing the part.** It must be
estimated and subtracted, which is what the ZUPT rate-bias learner exists to do.

**2. 🔴 The resulting attitude error is TEMPERATURE-DEPENDENT, and nothing currently models it.**
The complementary filter settles at `accelPitch + rate × τ` with `DEFAULT_PITCH_TAU_S = 5.0 s`, so a
standing rate becomes a standing pitch error. Applying the **±0.05 dps/°C** row:

| cabin ΔT | added bias | phantom pitch | phantom grade |
|---|---|---|---|
| baseline (measured) | 0.01304 rad/s | 3.74° | **6.5 %** |
| +20 °C | 0.0175 rad/s | 5.0° | **8.7 %** |
| +30 °C | 0.0262 rad/s | 7.5° | **13.2 %** |
| +40 °C | 0.0349 rad/s | 10.0° | **17.6 %** |

⚠️ **Every one of those rows is still BELOW the US-749 plausibility guard**, which needs
`11.36° / 5 s = 0.0397 rad/s` to trip. **A car parked in the sun can carry 2–3× the phantom grade
of one parked in shade and never raise a flag.** Size the parked-grade defect as a **6–18 %
temperature-dependent band, not a fixed 6.5 %.**

## Accelerometer (p. 12)

| Fact | Value | Conditions |
|------|-------|------------|
| Full-scale range | **±2 g** at `ACCEL_FS=0` | |
| Sensitivity scale factor | **16,384 LSB/g** at `ACCEL_FS=0` | |
| Nonlinearity | **±0.5 %** | best-fit straight line |
| Sensitivity change vs. temperature | **±0.026 %/°C** | −40 °C to +85 °C, `ACCEL_FS=0` |
| ADC word length | **16 bit**, two's complement | |

⚠️ **The driver's `initialize()` sets accel full scale explicitly to ±8 g**, not the `ACCEL_FS=0`
±2 g this table's headline rows assume. Read the scale-factor row for the range actually selected.

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

🔴 **The part HAS a temperature sensor. Our driver does not expose it.** This settles a question
that was open as a *part-identity* doubt: a plausible dithering 26.85–27.18 °C read at `0x69` was
suspected to mean the part is not what we believe. **It is the genuine part** — `WHO_AM_I = 0xEA`
read live, and this table is the primary-source confirmation that the register exists. The
Adafruit **CircuitPython** driver (ours, 2.1.10) simply has no `temperature` property, while the
Adafruit **Arduino** driver does. **Both facts are true at different layers.** Whether to read
`TEMP_OUT` past the driver is a separate decision, and the CIO's call.

---

## Provenance and retrieval

`product.tdk.com` serves this PDF behind an **Akamai edge block** that returns a 533-byte
`Access Denied` HTML page to a plain fetch — **a naive download silently yields an HTML file with a
`.pdf` name.** Retrieved instead from the SparkFun CDN mirror and verified before landing:
`%PDF-` header, 89 pages, text extractable, `DS-000189 / Revision: 1.3` on pages 1, 2 and 89.

⚠️ **Revision note.** The current TDK web revision is **1.5**; this is **1.3**. Both were checked
on the two rows that carry our error budget — **Initial ZRO Tolerance ±5 dps** and **ZRO Variation
Over Temperature ±0.05 dps/°C** — and they are **identical across the two revisions**. Anything
read from this file *outside* those two rows has been verified against 1.3 only.

🔴 **Still not held locally: the Maxim MAX17048 datasheet.** The `STATUS (0x1A)` / `RI` semantics
the F-048 ruling depends on remain **RECALLED, not documented.**
