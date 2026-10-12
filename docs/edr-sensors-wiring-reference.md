# EDR Sensor Wiring Reference — TSL2591 (light) + ICM-20948 (9-DoF IMU)

**Purpose:** Field card for wiring the two EDR (black-box / event-data-recorder)
sensors onto the Raspberry Pi 5. Keep this open while soldering.

**Date:** 2026-06-27 · **Author:** Atlas (Architect) · **Status:** hardware
install reference. The *software* reader (publishing these onto the EDR bus) is
the EDR epic — see `specs/architecture.md` / the EDR-bus contract. Getting
`i2cdetect` to show all three addresses **is** the hardware milestone.

---

## TL;DR

Both sensors are **I²C** devices. They join the **same I²C bus the UPS HAT
already uses** (bus 1, `/dev/i2c-1`, pins 3/5). **4 wires per sensor** — 3.3 V,
GND, SDA, SCL — all in parallel. **No address collision.** Power both at
**3.3 V**.

| Device | I²C address | On bus already? |
|---|---|---|
| MAX17048 fuel gauge (inside X1209 UPS HAT) | `0x36` | yes |
| **TSL2591** (light) | `0x29` (fixed) | adding now |
| **ICM-20948** (9-DoF IMU) | `0x69` default *(0x68 if AD0→GND)* | adding now |

Three distinct addresses → all coexist cleanly on one bus.

---

## Pin map (Raspberry Pi 5 — 40-pin header, accessible via the HAT's stacking pins)

```
        +---+---+
   3.3V | 1 | 2 | 5V
   SDA1 | 3 | 4 | 5V        Pin 1  = 3.3 V power     (also Pin 17)
   SCL1 | 5 | 6 | GND       Pin 3  = SDA  (I²C data) <- existing bus
  GPIO4 | 7 | 8 | TX        Pin 5  = SCL  (I²C clock) <- existing bus
    GND | 9 |10 | RX        Pin 6  = GND            (also Pin 9, 14, 20, 25…)
        +---+---+
```

**Both sensors wire identically** (Adafruit STEMMA-cable color convention):

| Sensor pad | → Pi pin | Wire |
|---|---|---|
| `VIN` | Pin 1 or Pin 17 (3.3 V) | red |
| `GND` | Pin 6 / 9 / 14 (any GND) | black |
| `SDA` | **Pin 3** | blue |
| `SCL` | **Pin 5** | yellow |

Leave unconnected: TSL2591 `3V3`-out and `INT`; ICM-20948 `AD0`, `INT`,
`FSYNC`, `AUX_*`. (Wire colors are convention only — electrically interchangeable.)

> **Power at 3.3 V, not 5 V.** Both boards accept 3–5 V on `VIN` (onboard
> regulator + level shifting), but the existing bus runs 3.3 V logic. Feeding
> 3.3 V keeps the whole bus at one level and removes any chance of a 5 V
> backfeed onto the Pi's non-5 V-tolerant GPIO.

---

## The junction (two sensors, one bus)

Each stacking pin takes one wire comfortably, but both sensors need
SDA→Pin 3 and SCL→Pin 5. Don't fight it pin-by-pin — make a junction:

```
  Pi Pin 1 (3V3) ──┐
  Pi Pin 6 (GND) ──┤   4 wires      ┌── TSL2591  (VIN/GND/SDA/SCL)
  Pi Pin 3 (SDA) ──┼──> [protoboard │
  Pi Pin 5 (SCL) ──┘    or 4 rails] └── ICM-20948 (VIN/GND/SDA/SCL)
```

Run **4 wires from the Pi** to a small protoboard / 4-row terminal strip, then
**fan out 4 wires to each sensor.** This is also the natural anchor point for
the cable runs back to the enclosures. (Daisy-chain sensor→sensor works too,
but the junction is far easier to debug in-car.)

**Pull-ups:** every board already has ~10 kΩ pull-ups on SDA/SCL. Three in
parallel ≈ 3.3 kΩ — fine, and actually *better* for longer runs. **Add none.**

---

## Automotive run notes (where I²C bites)

- **Keep runs short.** I²C is a board-level bus; feet of wire in a noisy cabin
  is the usual failure point.
- **Twist the pairs** (SDA-with-GND, SCL-with-GND) or use 4-conductor shielded
  cable — shield to GND **at the Pi end only**.
- **Route away** from the coil / injector / ignition harness.
- **If a long run is flaky,** slow the bus in `/boot/firmware/config.txt`:
  `dtparam=i2c_arm_baudrate=50000` (or lower), then reboot.

---

## Mounting (determines whether the data is *usable*)

**ICM-20948 (accel / gyro / compass):**
- Bolt **rigidly to the chassis** — loose mounting = vibration garbage in the
  g-force trace.
- **Decide and write down the axis orientation** (which pad-axis = forward /
  lateral / up). Software can rotate the frame, but only if the true mounting
  orientation is known.
- Near the car's center of gravity is ideal for clean longitudinal/lateral g.
- **Magnetometer (compass):** keep away from speakers, motors, and large steel;
  plan a one-time hard/soft-iron calibration **in its final mounted position**.

**TSL2591 (light):**
- Point it at representative ambient light (windshield / dash area), not buried
  in a dark cubby, or the auto-dim has nothing to read. Behind tinted/IR glass
  it reads low — fine for *relative* dimming.

---

## Verify (do this the moment it's connected — proves every joint)

```bash
sudo i2cdetect -y 1
```

Expect **three** addresses: `29` (TSL2591), `36` (MAX17048), and `69`
(ICM-20948; `68` if you grounded AD0).

> If `36` **disappears**, you've shorted SDA/SCL — the UPS telemetry dropped off
> the bus too. Back off and recheck before powering anything else.

I²C is already enabled on this Pi (the UPS HAT uses it). If it ever isn't:
`sudo raspi-config nonint do_i2c 0 && sudo reboot`.

---

## Software quick-start (CircuitPython / Blinka)

These are bench-test snippets to confirm the sensors talk. The *production*
reader lives in the EDR-bus epic, not here.

```bash
# In the Pi venv:
pip install adafruit-blinka \
            adafruit-circuitpython-tsl2591 \
            adafruit-circuitpython-icm20x
```

### TSL2591 — light (lux / visible / IR)
```python
import board
import adafruit_tsl2591

i2c = board.I2C()                      # bus 1 (pins 3/5)
sensor = adafruit_tsl2591.TSL2591(i2c) # fixed address 0x29

# Optional tuning (defaults: GAIN_MED 25x, 100 ms):
# sensor.gain = adafruit_tsl2591.GAIN_LOW          # 1x  (bright sun)
# sensor.integration_time = adafruit_tsl2591.INTEGRATIONTIME_100MS

print(f"Light:    {sensor.lux} lux")
print(f"Visible:  {sensor.visible}")
print(f"Infrared: {sensor.infrared}")
print(f"Full:     {sensor.full_spectrum}")
```
- **Gain:** `GAIN_LOW` 1x · `GAIN_MED` 25x (default) · `GAIN_HIGH` 428x ·
  `GAIN_MAX` 9876x.
- **Integration time:** `INTEGRATIONTIME_100MS` (default) … `_600MS`.
- A bright-sun cabin needs **low gain / short integration** to avoid saturating
  `.lux` (returns overflow/inf when saturated).

### ICM-20948 — 9-DoF (accel / gyro / compass)
```python
import time
import board
import adafruit_icm20x

i2c = board.I2C()
icm = adafruit_icm20x.ICM20948(i2c)        # default 0x69
# icm = adafruit_icm20x.ICM20948(i2c, 0x68)  # if you grounded AD0

while True:
    print("Accel  X:{:.2f} Y:{:.2f} Z:{:.2f} m/s^2".format(*icm.acceleration))
    print("Gyro   X:{:.2f} Y:{:.2f} Z:{:.2f} rad/s".format(*icm.gyro))
    print("Mag    X:{:.2f} Y:{:.2f} Z:{:.2f} uT".format(*icm.magnetic))
    print("")
    time.sleep(0.5)
```
- `.acceleration` → m/s² (gravity included → resting Z-axis ≈ **9.8** when level;
  that's your axis-orientation sanity check).
- `.gyro` → **rad/s** (Adafruit lib returns radians, not degrees — convert if
  you want °/s).
- `.magnetic` → µT, from the onboard **AK09916** magnetometer.
- Default I²C address **0x69**; pull `AD0`→GND for 0x68.

---

## Sources (verified 2026-06-27)

- [Adafruit TSL2591 — Python/CircuitPython](https://learn.adafruit.com/adafruit-tsl2591/python-circuitpython)
- [Adafruit_CircuitPython_TSL2591 (GitHub)](https://github.com/adafruit/Adafruit_CircuitPython_TSL2591)
- [Adafruit ICM-20948 — Python/CircuitPython](https://learn.adafruit.com/adafruit-tdk-invensense-icm-20948-9-dof-imu/python-circuitpython)
- [Adafruit_CircuitPython_ICM20X (GitHub)](https://github.com/adafruit/Adafruit_CircuitPython_ICM20X)
- [adafruit_icm20x API docs](https://docs.circuitpython.org/projects/icm20x/en/latest/api.html)
