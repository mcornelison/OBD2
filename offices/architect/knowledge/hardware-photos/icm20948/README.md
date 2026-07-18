# ICM-20948 IMU board — identification + bring-up notes

**Photos (this folder):** `icm20948-front-labeled.jpg`, `icm20948-back-labeled.jpg` (CIO's actual board, 2026-07-03).

## Vendor ID (2026-07-03, Atlas — verified vs official Adafruit docs + datasheet)

**Board = Adafruit #4554 *pinout*, but this physical unit is an unbranded CLONE (not genuine Adafruit).**
**CONFIRMED vendor (2026-07-04, Amazon listing scraped): brand "NebulaGo", title "2PCS ICM-20948
9-DoF Sensor", ASIN B0G5LP4JRQ (~$17 2-pack — hence the CIO's "secondary board").** Generic
reseller; listing carries NO electrical spec (no pull-up/CS/logic detail) → no schematic to lean on,
no guaranteed on-board CS pull-up → the datasheet CS-high-at-power-up rule governs.

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

**CS-high source: use `1V8`, NOT the AD (AUX_DA) pad (2026-07-04).** AD is AUX_DA — an *active*
signal pin, not a rail. The ICM-20948 bypass mux ties AUX_CL/AUX_DA to the internal AK09916 mag
master (I²C-master mode drives AUX_DA) and/or analog-switches AUX_DA onto the main SDA (pass-through
mode). So bridging CS→AD only holds during a bare `i2cdetect` (aux bus idle); the instant any 9-DoF
driver reads the magnetometer, AUX_DA toggles and drags CS low → chip drops out of I²C. **Bridge
CS→`1V8` (static VDDIO rail).** Board-2 wiring: VIN→3.3V, GND, SCL→GPIO3, SDA→GPIO2, CS→1V8,
SDO/AD0→default(0x69), power-up with CS already high. (Source: InvenSense DS-000189 bypass-mux /
aux-I²C section.)

## Correction guard (2026-07-15, Atlas)

CIO re-confirmed: **this is a CLONE, not genuine Adafruit.** Web research on the *generic* ICM-20948
describes the GENUINE Adafruit 4554 (primary pins level-shifted to 3–5V → "CS→3.3V"). **That is WRONG
for this clone** — measured AD/AC = 1.8V (no level shifter; bare 1.8V-logic board). **CS→1V8 (VDDIO),
never 3.3V** (3.3V > 1.95V abs-max → damage risk). Do not regress to the genuine-Adafruit CS→3.3V
guidance. Config path is **exhausted** (CS→1V8 + power-cycle tried on BOTH boards, still dark on a
healthy bus) → remaining suspects = dead SDA/SCL QFN joint or bad batch, NOT config. EDR hardware,
ships dark, blocks nothing.

## FINAL VERDICT (2026-07-18 — powered diagnosis, Atlas + CIO + Copilot 365) — DO NOT re-litigate

**Conclusion: both clone boards are DEFECTIVE at the host-I2C interface. NOT the wiring, NOT the Pi,
NOT power, NOT the CS/mode-select. Replace with a genuine Adafruit #4554. This closes the ICM-20948
clone bring-up.**

Reached by elimination with LIVE + powered evidence (not a guess this time):

| Checked | Result | Verdict |
|---|---|---|
| Pi I2C enabled | `/dev/i2c-1` present, `dtparam=i2c_arm=on` | ✅ not a Pi issue |
| Bus 1 healthy | UPS `i2cget -y 1 0x36` → `0xff` | ✅ bus works |
| IMU address | `i2cget 0x68` AND `0x69` → both "Read failed" | ❌ no ACK either addr |
| **VDDIO rail** | **`1V8`→GND powered ≈ 1.8V** (analog: >1.5, <3) | ✅ **regulator works, NOT over-volted** — VIN→1V8 continuity was THROUGH the regulator, not a short |
| Bus lines | SDA/SCL idle ≈ 3.3V | ✅ not stuck low (rules out held-bus) |
| Arbitration | intermittent `i2c_dw_handle_tx_abort: lost arbitration` on FULL scans only; none on targeted probes | symptom of the mis-routed host iface, not a hard jam |
| Both boards | identical dead behavior | → the boards, not a one-off |

**Root (internal to the clone):** the soldered SDA/SCL pads don't electrically reach the ICM die's
I2C pins (clone pad-mapping dead-end) and/or the host interface is damaged. Supporting hints: the
CIO's continuity showed **`SDA→AC` and `SCL→AC` continuity** (AUX_CL entangled with the main bus —
routing ≠ silkscreen), and SDA/SCL sat at a FULL 3.3V rather than clamping toward ~2.4V, as they
would if the chip's 1.8V I/O were truly on those lines.

**Superseded:** the earlier CS→1V8 / "config path exhausted / power-cycle" guidance above — powered
measurement proved power/VDDIO/CS-strap are all FINE (Copilot continuity: CS/AD/SDO already tied to
1V8 on-board → board strapped for I2C @0x69). The defect is the die-side host interface, unreachable
by any wiring change. EDR sensor, ships dark, blocks nothing — no urgency; buy a real Adafruit 4554.

**Sources:** Adafruit 4554 pinouts (learn.adafruit.com) · InvenSense ICM-20948 datasheet DS-000189 · eMD software guide · CIO+Copilot 365 diagnostic notes 2026-07-18 (continuity + powered voltages) · Atlas live Pi probes 2026-07-18 (i2cdetect/i2cget/dmesg).
