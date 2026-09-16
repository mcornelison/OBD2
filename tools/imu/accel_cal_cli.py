"""ARCH-027: apply the accelerometer calibration to a captured rotation CSV.

Expects the columns exported from `edr_imu_sample`:
`accel_x_ms2, accel_y_ms2, accel_z_ms2, gyro_x_rads, gyro_y_rads, gyro_z_rads`.

Imports the PRODUCTION `pi.sensors.accel_cal` rather than re-deriving the fit; a
tool that re-implements what it is measuring proves only that the copy works.

Validation is by INTERLEAVING, not by consecutive stretches. Every Nth sample
means each subset spans the whole capture and contains every orientation, so the
subsets differ only by noise. Consecutive chunks of a one-axis-at-a-time
rotation must disagree by construction, and reading that as contamination would
reject a good calibration -- which is exactly what happened to the magnetometer
fit earlier tonight before the validator was corrected.

Usage:
    python -m tools.imu.accel_cal_cli path/to/capture.csv [--max-gyro 0.05]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from pi.sensors.accel_cal import DEFAULT_MAX_GYRO_RAD_S, calibrateAccel, quasiStaticSamples


def loadRows(path: str) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    rows: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                accel = (
                    float(row["accel_x_ms2"]),
                    float(row["accel_y_ms2"]),
                    float(row["accel_z_ms2"]),
                )
                gyro = (
                    float(row["gyro_x_rads"]),
                    float(row["gyro_y_rads"]),
                    float(row["gyro_z_rads"]),
                )
            except (KeyError, TypeError, ValueError):
                # A row with a missing or unparseable field is skipped rather
                # than defaulted: a fabricated zero would enter the fit as data.
                continue
            rows.append((accel, gyro))
    return rows


def _summary(points: list[tuple[float, float, float]]) -> dict[str, object]:
    try:
        cal = calibrateAccel(points)
    except ValueError as exc:
        return {"refused": str(exc), "samples": len(points)}
    return {
        "biasMs2": [round(value, 4) for value in cal.biasMs2],
        "measuredGMs2": round(cal.measuredGMs2, 4),
        "measuredG": round(cal.measuredGMs2 / 9.80665, 5),
        "scaleFactor": round(cal.scaleFactor, 5),
        "errorPercent": round(cal.errorPercent, 3),
        "residualRmsMs2": round(cal.residualRmsMs2, 4),
        "samples": cal.samples,
        "describe": cal.describe(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Accelerometer scale/bias calibration")
    parser.add_argument("csv")
    parser.add_argument("--max-gyro", type=float, default=DEFAULT_MAX_GYRO_RAD_S)
    parser.add_argument("--subsets", type=int, default=4)
    args = parser.parse_args(argv)

    rows = loadRows(args.csv)
    still = quasiStaticSamples(rows, maxGyroRadS=args.max_gyro)

    result: dict[str, object] = {
        "totalRows": len(rows),
        "quasiStaticRows": len(still),
        "maxGyroRadS": args.max_gyro,
        "overall": _summary(still),
        "interleaved": [_summary(still[i :: args.subsets]) for i in range(args.subsets)],
    }

    scales = [s["scaleFactor"] for s in result["interleaved"] if "scaleFactor" in s]  # type: ignore[index]
    if len(scales) >= 2:
        spread = max(scales) - min(scales)  # type: ignore[type-var]
        result["stability"] = {
            "scaleSpread": round(float(spread), 5),
            # 0.002 is a tenth of the 0.02 trust band: tight enough that the
            # corrected reading lands well inside it whichever subset is used.
            "verdict": "stable" if float(spread) < 0.002 else "unstable",
        }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
