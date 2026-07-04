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

## Power-up sequencing gotcha (2026-07-04 — datasheet-confirmed, load-bearing)

**No I²C init *command* is needed** — `i2cdetect` finds the device by address-ACK at the hardware
layer, below any register interaction. A "missing command" is NOT why it's invisible.

**BUT** InvenSense DS-000189: *"Power-up with SCL and nCS pins held low is not a supported use case;
a software reset via PWR_MGMT_1 is required prior to initialization."* → **CS (nCS) must be HIGH at
the instant power is applied.** On a clone with no CS pull-up, CS floats/low at boot → chip comes up
SPI-latched/unsupported → won't ACK I²C. **Tying CS high *after* boot does NOT fix it** (and the
PWR_MGMT_1 reset is chicken-and-egg over a dead bus). **Only fix: power-cycle with CS already high.**

**Corrected CS-high voltage — tie CS → the `1V8` pin (VDDIO), NOT 3.3V.** Measured 2026-07-04:
AD/AC = 1.8V (chip logic domain = 1.8V), FS = 0 (FSYNC idle-low, normal), power present. Datasheet:
CS→VDDIO=1.8V. On a clone CS may not be level-shifted → 3–5V exceeds the 1.95V abs-max; `1V8` can't
over-volt. (Supersedes the "CS→3V3" line above — 3.3V both risked over-voltage AND was applied while
already powered, so it couldn't re-latch I²C.)

**Live scan 2026-07-04:** `i2cdetect -y 1` → 0x29 + 0x36 present, **0x69/0x68 absent.** Untested
variable: **CS→1V8 + power-cycle + re-scan.** Then check SDO/AD0 defined (0x69 default) + SCL/SDA
continuity to the QFN die pad (not just header).

**Sources:** Adafruit 4554 pinouts (learn.adafruit.com) · InvenSense ICM-20948 datasheet DS-000189 · eMD software guide.
