################################################################################
# File Name: temp_register_probe.py
# Purpose/Description: ARCH-046 -- settle, as a FACT, whether the ICM-20948's
#                      temperature register exists and works on THIS board.
#                      Read-only raw-register probe. Reads WHO_AM_I, PWR_MGMT_1
#                      (the TEMP_DIS bit), accel, gyro and TEMP_OUT for a fixed
#                      window and reports whether each VARIES.
# Author: Atlas (ARCH-046, at CIO direction 2026-09-22)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Settle the ICM-20948 temperature-register question by reading the chip.

The question bounced between "the vendor guide says the part has one" and
"``temp_c`` is NULL in 6.94M rows" for two days because **nobody read the
register**. One argued from a DRIVER, the other from a COLUMN.

Register facts are DOCUMENTED, from DS-000189 rev 1.3 (held at
``hardware/datasheets/icm-20948/``), not recalled::

    REG_BANK_SEL  0x7F              bank select; bank 0 for all of the below
    WHO_AM_I      0x00  -> 0xEA     identity
    PWR_MGMT_1    0x06  reset 0x41  BIT 3 = TEMP_DIS ("1 disables the temperature sensor")
    ACCEL_XOUT_H  0x2D              6 bytes, big-endian signed
    GYRO_XOUT_H   0x33              6 bytes, big-endian signed
    TEMP_OUT_H    0x39  reset 0x00  2 bytes, big-endian signed
    TEMP_degC = ((TEMP_OUT - RoomTemp_Offset) / 333.87) + 21   RoomTemp_Offset = 0 @ 21 degC

**Reset value 0x41 is 0b0100_0001, so bit 3 is 0: temperature is ENABLED by
default.** If it reads disabled here, something wrote that bit.

🔴 **READ-ONLY. No register is written, and the Adafruit driver is never
instantiated** -- ``ICM20948.__init__`` calls ``self.reset()``, which would
reset the live IMU and could provoke the A-34 latch this project has been
chasing. Raw SMBus reads only.

⚠️ Run with ``eclipse-obd`` STOPPED so nothing else holds the bus, and restart
it afterwards.

Usage::

    sudo systemctl stop eclipse-obd
    python3 tools/imu/temp_register_probe.py --seconds 60
    sudo systemctl start eclipse-obd
"""

from __future__ import annotations

import argparse
import json
import sys
import time

I2C_BUS = 1
ADDR = 0x69

REG_BANK_SEL = 0x7F
REG_WHO_AM_I = 0x00
REG_PWR_MGMT_1 = 0x06
REG_PWR_MGMT_2 = 0x07
REG_ACCEL_XOUT_H = 0x2D
REG_GYRO_XOUT_H = 0x33
REG_TEMP_OUT_H = 0x39

WHO_AM_I_EXPECTED = 0xEA
TEMP_SENSITIVITY_LSB_PER_C = 333.87
ROOM_TEMP_OFFSET = 0.0
ROOM_TEMP_C = 21.0
TEMP_DIS_BIT = 1 << 3


def _s16(hi: int, lo: int) -> int:
    """Big-endian signed 16-bit, as every ICM-20948 output register is."""
    raw = (hi << 8) | lo
    return raw - 65536 if raw & 0x8000 else raw


def tempDegC(rawTemp: int) -> float:
    """Datasheet 8.31 conversion. Exposed so a test can pin it."""
    return ((rawTemp - ROOM_TEMP_OFFSET) / TEMP_SENSITIVITY_LSB_PER_C) + ROOM_TEMP_C


def probe(seconds: float, intervalS: float) -> dict:
    """Sample the registers for ``seconds`` and return the raw findings."""
    try:
        from smbus2 import SMBus
    except ImportError:  # pragma: no cover - environment probe
        return {"error": "smbus2 not installed; cannot read the bus"}

    out: dict = {"samples": [], "errors": []}
    with SMBus(I2C_BUS) as bus:
        # Bank 0 holds every register below. Selecting the bank is the ONE write
        # this probe would need -- and it is avoided: the driver leaves bank 0
        # selected, which Spool verified (BANK_SEL read 0x00 before and after his
        # raw reads). Read it and REFUSE if it is not bank 0, rather than write.
        bank = bus.read_byte_data(ADDR, REG_BANK_SEL)
        out["regBankSel"] = bank
        if bank != 0x00:
            out["error"] = (
                f"REG_BANK_SEL reads 0x{bank:02X}, not bank 0. Refusing to write it. "
                f"Every address below is bank-0, so the readings would be meaningless."
            )
            return out

        whoAmI = bus.read_byte_data(ADDR, REG_WHO_AM_I)
        pwr1 = bus.read_byte_data(ADDR, REG_PWR_MGMT_1)
        pwr2 = bus.read_byte_data(ADDR, REG_PWR_MGMT_2)
        out["whoAmI"] = whoAmI
        out["whoAmIExpected"] = WHO_AM_I_EXPECTED
        out["pwrMgmt1"] = pwr1
        out["pwrMgmt2"] = pwr2
        out["tempDisBitSet"] = bool(pwr1 & TEMP_DIS_BIT)

        if whoAmI != WHO_AM_I_EXPECTED:
            out["error"] = (
                f"WHO_AM_I reads 0x{whoAmI:02X}, expected 0x{WHO_AM_I_EXPECTED:02X}. "
                f"Addressing or bank is wrong -- STOP, this is not a temp finding."
            )
            return out

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                a = bus.read_i2c_block_data(ADDR, REG_ACCEL_XOUT_H, 6)
                g = bus.read_i2c_block_data(ADDR, REG_GYRO_XOUT_H, 6)
                t = bus.read_i2c_block_data(ADDR, REG_TEMP_OUT_H, 2)
            except OSError as e:
                out["errors"].append(str(e))
                time.sleep(intervalS)
                continue
            rawTemp = _s16(t[0], t[1])
            out["samples"].append(
                {
                    "t": round(time.monotonic(), 3),
                    "accel": [_s16(a[0], a[1]), _s16(a[2], a[3]), _s16(a[4], a[5])],
                    "gyro": [_s16(g[0], g[1]), _s16(g[2], g[3]), _s16(g[4], g[5])],
                    "tempRaw": rawTemp,
                    "tempC": round(tempDegC(rawTemp), 3),
                }
            )
            time.sleep(intervalS)
    return out


def summarise(out: dict) -> dict:
    """Reduce the samples to the facts that decide the question."""
    samples = out.get("samples", [])
    if not samples:
        return {"verdict": "NO SAMPLES", "n": 0}

    temps = [s["tempRaw"] for s in samples]
    accelMag = [abs(s["accel"][0]) + abs(s["accel"][1]) + abs(s["accel"][2]) for s in samples]
    gyroMag = [abs(s["gyro"][0]) + abs(s["gyro"][1]) + abs(s["gyro"][2]) for s in samples]

    tempVaries = len(set(temps)) > 1
    # THE CONTROL. If accel/gyro are frozen too, the read path is broken and a
    # frozen temp proves nothing about temp.
    controlAlive = len(set(accelMag)) > 1 and len(set(gyroMag)) > 1

    if not controlAlive:
        verdict = "VOID -- accel/gyro are FROZEN too, so the read path is broken"
    elif out.get("tempDisBitSet"):
        verdict = "EXISTS BUT DISABLED -- PWR_MGMT_1 bit 3 (TEMP_DIS) is SET"
    elif tempVaries:
        verdict = "EXISTS AND WORKS -- the NULL column is a DRIVER gap, not a dead register"
    else:
        verdict = "DEAD -- enabled, read path proven live, and TEMP_OUT never moved"

    return {
        "verdict": verdict,
        "n": len(samples),
        "tempRawDistinct": len(set(temps)),
        "tempRawMin": min(temps),
        "tempRawMax": max(temps),
        "tempCMin": round(tempDegC(min(temps)), 3),
        "tempCMax": round(tempDegC(max(temps)), 3),
        "tempVaries": tempVaries,
        "controlAlive": controlAlive,
        "accelDistinct": len(set(accelMag)),
        "gyroDistinct": len(set(gyroMag)),
        "readErrors": len(out.get("errors", [])),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--json", action="store_true", help="dump every sample too")
    args = ap.parse_args(argv)

    out = probe(args.seconds, args.interval)
    if "error" in out:
        print(f"PROBE REFUSED: {out['error']}")
        return 2

    summary = summarise(out)
    print("=== ICM-20948 TEMP REGISTER PROBE (ARCH-046) ===")
    print(f"REG_BANK_SEL  0x{out['regBankSel']:02X}")
    print(f"WHO_AM_I      0x{out['whoAmI']:02X}  (expect 0x{WHO_AM_I_EXPECTED:02X})")
    print(f"PWR_MGMT_1    0x{out['pwrMgmt1']:02X}  TEMP_DIS(bit3)={'SET' if out['tempDisBitSet'] else 'clear'}")
    print(f"PWR_MGMT_2    0x{out['pwrMgmt2']:02X}")
    print()
    for k, v in summary.items():
        print(f"  {k:18} {v}")
    if args.json:
        print(json.dumps(out["samples"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
