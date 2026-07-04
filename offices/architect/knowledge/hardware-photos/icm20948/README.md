# ICM-20948 IMU board — identification + bring-up notes

**Photos (this folder):** `icm20948-front-labeled.jpg`, `icm20948-back-labeled.jpg` (CIO's actual board, 2026-07-03).

## Vendor ID (2026-07-03, Atlas — verified vs official Adafruit docs + datasheet)

**Board = Adafruit #4554 *pinout*, but this physical unit is an unbranded CLONE (not genuine Adafruit).**

- **Matches Adafruit 4554 exactly:** pin labels `FS AD AC G SDO CS` (top) / `VIN 1V8 GND SCL SDA INT` (bottom); the `1V8` regulator-output pin; `AD`/`AC` aux-I²C names; dual STEMMA-QT/Qwiic connectors; X/Y axis arrows. Pin-for-pin 4554-compatible.
- **But NOT genuine Adafruit:** no "Adafruit" text / no Penguin logo; older vector-font silkscreen; the **back prints a spec table** (`Accel ±2~16g / Gyro ±250~2000 dps / Mag ±49 Gauss`) — genuine Adafruit backs carry branding, not a spec table.

**Address:** default **0x69** (Adafruit-pinout default); `ADR` jumper (back) bridged → 0x68. `i2cdetect` scans all addresses, so absence ≠ wrong-address.

## The CS gotcha (why vendor matters)

InvenSense datasheet (DS-000189): **CS/CSB must be pulled HIGH to VDDIO for I²C** (low = SPI; floating = undefined). Genuine Adafruit 4554 pulls CS high on-board → I²C automatic. **A clone may not** → CS floats → chip sits in SPI mode → **silent on I²C entirely.**

## Live diagnosis (as of 2026-07-03)

TSL2591 @0x29 reads fine on the same bus → I²C healthy. ICM absent from the *entire* scan → chip not ACKing at all → leading causes: (1) **CS not high → SPI mode** (CIO's hypothesis — live because this is a clone), or (2) dead joint on the QFN pads / no die power. CIO reflowed SDA+SCL, confirmed continuity + no bridges.

**Next-step tests (multimeter):**
1. CS→GND should read ~3.3V (pulled up). If ~0V/floating → tie **CS→3V3** (NOT 5V VIN) → re-scan; expect 0x69.
2. `1V8`→GND should read ~1.8V (proves regulator alive + die powered).
3. If CS high + 1V8 ok + continuity good but still absent → reflow the QFN's own SDA/SCL pads, or suspect a dead chip.

**Sources:** Adafruit 4554 pinouts (learn.adafruit.com) · InvenSense ICM-20948 datasheet DS-000189.
