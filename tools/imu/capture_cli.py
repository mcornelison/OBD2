"""ARCH-027: stream magnetometer + accelerometer samples to CSV while the sensor
is rotated by hand, then fit the hard-iron sphere.

Rotating through many orientations is the ONLY way to separate the hard-iron
offset (the sphere's centre) from the true field strength (its radius). A car on
flat ground samples a horizontal circle and cannot do it -- which is why the
A-30 gate could never pass on driving data.

Usage on chi-eclipse-01, with the collector stopped:

    sudo systemctl stop eclipse-obd
    python3 tools/imu/capture_cli.py --seconds 120 --out ~/arch027/mag_rotate.csv
    sudo systemctl start eclipse-obd

Prints progress to stderr so the operator can hear how long is left, and a JSON
summary (including the fit, if the rotation spanned 3D) to stdout.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time

from pi.sensors.mag_fit import ellipticity, sphereFit
from tools.imu.imu_probe import (
    ADDR_IMU,
    MAG_ADDRESS,
    MAG_REG_HXL,
    MAG_REG_ST1,
    decodeMagTriple,
    magDataReady,
    magOverflowed,
    openBus,
    ownsBus,
    readConfiguration,
    readRawSample,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rotate-and-capture magnetometer (ARCH-027)")
    parser.add_argument("--seconds", type=float, default=120.0)
    parser.add_argument("--hz", type=float, default=25.0)
    parser.add_argument("--out", required=True, help="CSV path for the raw samples")
    parser.add_argument("--label", default="", help="free-text note stored in the summary")
    parser.add_argument("--allow-shared-bus", action="store_true")
    args = parser.parse_args(argv)

    if not ownsBus() and not args.allow_shared_bus:
        print(json.dumps({"error": "eclipse-obd is active; stop it first"}))
        return 2

    bus = openBus()
    period = 1.0 / args.hz
    deadline = time.monotonic() + args.seconds
    nextReport = time.monotonic() + 10.0
    points: list[tuple[float, float, float]] = []
    overflows = 0
    notReady = 0

    # Scale is read from the registers rather than assumed, same as the probe.
    config = readConfiguration(bus, ADDR_IMU)
    lsbPerG = config["accel"].lsbPerG  # type: ignore[union-attr]

    try:
        with open(args.out, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["ts_utc", "ts_mono", "mag_x_ut", "mag_y_ut", "mag_z_ut", "acc_x_g", "acc_y_g", "acc_z_g"]
            )
            while time.monotonic() < deadline:
                st1 = bus.read_byte_data(MAG_ADDRESS, MAG_REG_ST1)
                if not magDataReady(st1):
                    notReady += 1
                    time.sleep(period)
                    continue
                frame = bus.read_i2c_block_data(MAG_ADDRESS, MAG_REG_HXL, 8)
                if magOverflowed(frame[7]):
                    overflows += 1
                    time.sleep(period)
                    continue
                mag = decodeMagTriple(frame[0:6])
                rawAccel, _ = readRawSample(bus, ADDR_IMU)
                accel = [value / lsbPerG for value in rawAccel]
                now = time.monotonic()
                writer.writerow(
                    [
                        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        round(now, 3),
                        round(mag[0], 3),
                        round(mag[1], 3),
                        round(mag[2], 3),
                        round(accel[0], 4),
                        round(accel[1], 4),
                        round(accel[2], 4),
                    ]
                )
                points.append(mag)
                if now >= nextReport:
                    remaining = int(deadline - now)
                    print(f"  {len(points)} samples, {remaining}s left", file=sys.stderr, flush=True)
                    nextReport = now + 10.0
                time.sleep(period)
    finally:
        bus.close()

    summary: dict[str, object] = {
        "label": args.label,
        "out": args.out,
        "samples": len(points),
        "overflows": overflows,
        "notReady": notReady,
        "axisSpanUt": [
            round(max(p[axis] for p in points) - min(p[axis] for p in points), 2)
            for axis in range(3)
        ]
        if points
        else [],
    }
    try:
        summary["ellipticity"] = round(ellipticity(points), 3)
    except ValueError as exc:
        summary["ellipticity"] = f"unavailable: {exc}"
    try:
        fit = sphereFit(points)
        summary["fit"] = {
            "hardIronOffsetUt": [round(value, 2) for value in fit.center],
            "fieldRadiusUt": round(fit.radius, 2),
            "residualRmsUt": round(fit.residualRms, 3),
            "samples": fit.samples,
        }
    except ValueError as exc:
        # Refusing is a result. It means the rotation did not cover enough
        # orientations -- not that the sensor is bad.
        summary["fit"] = f"refused: {exc}"
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
