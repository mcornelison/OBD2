"""ARCH-027: run the independent IMU probe on the Pi and print what it finds.

Usage on chi-eclipse-01 (the collector MUST be stopped first):

    sudo systemctl stop eclipse-obd
    python3 tools/imu/probe_cli.py --seconds 20
    python3 tools/imu/probe_cli.py --seconds 20 --power-cycle   # A-34 recovery
    sudo systemctl start eclipse-obd

Prints JSON on stdout and nothing else, so it can be piped, diffed and stored as
evidence. It writes no files and touches no database.

What it answers, none of which our source code can tell you:
  * what full-scale range and filter bandwidth the sensor is ACTUALLY running
  * whether the kept 50 Hz stream is exposed to aliasing at that bandwidth
  * what the accel and gyro read at rest, in physical units, with their spread
  * whether the gyro is in the A-34 latched fault right now
  * whether a PWR_MGMT_2 power cycle clears it, measured before and after
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from typing import Any

from tools.imu.imu_probe import (
    ADDR_IMU,
    aliasingRisk,
    classifyGyroHealth,
    gyroPowerCycle,
    openBus,
    ownsBus,
    readConfiguration,
    readMagnetometerDirect,
    readRawSample,
    readSelfTest,
)

DEGREES_TO_RADIANS = math.pi / 180.0
STANDARD_GRAVITY_MS2 = 9.80665


def _summarise(values: list[float]) -> dict[str, float]:
    return {
        "mean": round(statistics.fmean(values), 6),
        "sd": round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0,
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }


def collectRest(bus, address: int, seconds: float, sampleHz: float) -> dict[str, Any]:
    """Sample the sensor for a fixed window and report physical-unit statistics.

    Scaling uses the full-scale range read from the REGISTERS, not an assumed
    one -- the whole point of the probe is that nothing in our code sets it.
    """
    config = readConfiguration(bus, address)
    accelConfig = config["accel"]
    gyroConfig = config["gyro"]

    period = 1.0 / sampleHz
    deadline = time.monotonic() + seconds
    accelAxes: list[list[float]] = [[], [], []]
    gyroAxes: list[list[float]] = [[], [], []]
    magnitudes: list[float] = []

    while time.monotonic() < deadline:
        rawAccel, rawGyro = readRawSample(bus, address)
        accelG = [value / accelConfig.lsbPerG for value in rawAccel]
        gyroRadS = [
            (value / gyroConfig.lsbPerDps) * DEGREES_TO_RADIANS for value in rawGyro
        ]
        for axis in range(3):
            accelAxes[axis].append(accelG[axis] * STANDARD_GRAVITY_MS2)
            gyroAxes[axis].append(gyroRadS[axis])
        magnitudes.append(math.sqrt(sum(component**2 for component in accelG)))
        time.sleep(period)

    meanGyro = tuple(statistics.fmean(axis) for axis in gyroAxes)
    return {
        "samples": len(magnitudes),
        "accelMs2": {
            name: _summarise(axis) for name, axis in zip("xyz", accelAxes, strict=True)
        },
        "gyroRadS": {
            name: _summarise(axis) for name, axis in zip("xyz", gyroAxes, strict=True)
        },
        "accelMagnitudeG": _summarise(magnitudes),
        "gyroHealth": classifyGyroHealth(meanGyro),
        "gyroMeanRadS": [round(value, 6) for value in meanGyro],
    }


def describeConfiguration(config: dict[str, Any], sampleHz: float) -> dict[str, Any]:
    accel = config["accel"]
    gyro = config["gyro"]
    return {
        "whoAmI": hex(config["whoAmI"]),
        "whoAmIOk": config["whoAmI"] == config["whoAmIExpected"],
        "pwrMgmt1": hex(config["pwrMgmt1"]),
        "pwrMgmt2": hex(config["pwrMgmt2"]),
        "accel": {
            "raw": hex(accel.raw),
            "fullScaleG": accel.fullScaleG,
            "lsbPerG": accel.lsbPerG,
            "dlpfEnabled": accel.dlpfEnabled,
            "dlpfConfig": accel.dlpfConfig,
            "bandwidthHz": accel.bandwidthHz,
            "odrHz": round(config["accelOdrHz"], 2),
            "aliasingRisk": aliasingRisk(accel.bandwidthHz, sampleHz),
        },
        "gyro": {
            "raw": hex(gyro.raw),
            "fullScaleDps": gyro.fullScaleDps,
            "lsbPerDps": gyro.lsbPerDps,
            "dlpfEnabled": gyro.dlpfEnabled,
            "dlpfConfig": gyro.dlpfConfig,
            "bandwidthHz": gyro.bandwidthHz,
            "odrHz": round(config["gyroOdrHz"], 2),
            "aliasingRisk": aliasingRisk(gyro.bandwidthHz, sampleHz),
        },
        "keptStreamHz": sampleHz,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent ICM-20948 probe (ARCH-027)")
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--sample-hz", type=float, default=50.0)
    parser.add_argument("--bus", type=int, default=1)
    parser.add_argument("--addr", type=lambda v: int(v, 0), default=ADDR_IMU)
    parser.add_argument(
        "--power-cycle",
        action="store_true",
        help="measure, run the A-34 gyro power cycle, then measure again",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run the vendor self-test on both blocks (restores config afterwards)",
    )
    parser.add_argument(
        "--mag",
        action="store_true",
        help="read the AK09916 directly, independently of our own bypass module",
    )
    parser.add_argument(
        "--allow-shared-bus",
        action="store_true",
        help="proceed even if eclipse-obd is running (readings may be corrupted)",
    )
    args = parser.parse_args(argv)

    if not ownsBus() and not args.allow_shared_bus:
        print(
            json.dumps(
                {
                    "error": "eclipse-obd is active; two I2C masters would corrupt "
                    "this reading. Stop it, or pass --allow-shared-bus."
                }
            )
        )
        return 2

    bus = openBus(args.bus)
    try:
        result: dict[str, Any] = {
            "tsUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "configuration": describeConfiguration(
                readConfiguration(bus, args.addr), args.sample_hz
            ),
            "before": collectRest(bus, args.addr, args.seconds, args.sample_hz),
        }
        if args.mag:
            # Before the self-test, which rewrites config registers.
            result["magnetometer"] = readMagnetometerDirect(bus)
        if args.self_test:
            result["selfTest"] = readSelfTest(bus, args.addr)
        if args.power_cycle:
            gyroPowerCycle(bus, args.addr)
            result["after"] = collectRest(bus, args.addr, args.seconds, args.sample_hz)
            result["recovered"] = (
                result["before"]["gyroHealth"] == "faulted"
                and result["after"]["gyroHealth"] == "healthy"
            )
        print(json.dumps(result, indent=2))
    finally:
        bus.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
