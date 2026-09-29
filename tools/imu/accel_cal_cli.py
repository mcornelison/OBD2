"""ARCH-027: apply the accelerometer calibration to a captured rotation CSV.

Expects the columns exported from `edr_imu_sample` -- the REAL names
`accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z` (Ruling 20; also what
`tools/imu/tumble_capture.py` writes), or the unit-suffixed alias
`accel_x_ms2, accel_y_ms2, accel_z_ms2, gyro_x_rads, gyro_y_rads, gyro_z_rads`.

Imports the PRODUCTION `pi.sensors.accel_cal` rather than re-deriving the fit; a
tool that re-implements what it is measuring proves only that the copy works.

Validation is by INTERLEAVING, not by consecutive stretches. Every Nth sample
means each subset spans the whole capture and contains every orientation, so the
subsets differ only by noise. Consecutive chunks of a one-axis-at-a-time
rotation must disagree by construction, and reading that as contamination would
reject a good calibration -- which is exactly what happened to the magnetometer
fit earlier tonight before the validator was corrected.

ELLIPSOID MODE (ARCH-064 Task 6b, Ruling 19). ``--ellipsoid`` fits offset +
3x3 (``accel_cal.calibrateAccelEllipsoid``: Li & Griffiths, referenced to g,
>= 6 held orientations) instead of bias + one scalar, on the SAME quasi-static
gate and with the SAME interleaved validation. The fit is in the capture's
DEVICE frame; the ``accelCalibration`` block it prints is conjugated into the
BODY frame through the live mount (``R b``, ``R A R^T`` -- Ruling 30), ready for
``pi.sensors.imu.accelCalibration``. The default mode is unchanged.

Usage:
    python -m tools.imu.accel_cal_cli path/to/capture.csv [--max-gyro 0.05]
    python -m tools.imu.accel_cal_cli tumble.csv --ellipsoid
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

import numpy as np

from pi.sensors import imu_state_bridge
from pi.sensors.accel_cal import (
    DEFAULT_MAX_GYRO_RAD_S,
    STANDARD_GRAVITY_MS2,
    calibrateAccel,
    calibrateAccelEllipsoid,
    quasiStaticSamples,
)
from tools.imu.cal_frames import conjugateToBody, toMatrix, toVector

ACCEL_COLUMNS_PRIMARY = ("accel_x", "accel_y", "accel_z")
ACCEL_COLUMNS_ALIAS = ("accel_x_ms2", "accel_y_ms2", "accel_z_ms2")
GYRO_COLUMNS_PRIMARY = ("gyro_x", "gyro_y", "gyro_z")
GYRO_COLUMNS_ALIAS = ("gyro_x_rads", "gyro_y_rads", "gyro_z_rads")

# Ellipsoid-mode stability: interleaved subsets must agree this closely.
# 0.002 on the matrix is the default mode's scale-spread bar; 0.02 m/s^2 of
# offset is ~0.1 degree of tilt.
ELLIPSOID_MATRIX_SPREAD_MAX = 0.002
ELLIPSOID_OFFSET_SPREAD_MAX_MS2 = 0.02


def loadRows(path: str) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    rows: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        accelCols = ACCEL_COLUMNS_PRIMARY if fields.issuperset(ACCEL_COLUMNS_PRIMARY) else ACCEL_COLUMNS_ALIAS
        gyroCols = GYRO_COLUMNS_PRIMARY if fields.issuperset(GYRO_COLUMNS_PRIMARY) else GYRO_COLUMNS_ALIAS
        for row in reader:
            try:
                accel = (
                    float(row[accelCols[0]]),
                    float(row[accelCols[1]]),
                    float(row[accelCols[2]]),
                )
                gyro = (
                    float(row[gyroCols[0]]),
                    float(row[gyroCols[1]]),
                    float(row[gyroCols[2]]),
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


def _ellipsoidSummary(points: list[tuple[float, float, float]]) -> dict[str, object]:
    try:
        cal = calibrateAccelEllipsoid(points)
    except ValueError as exc:
        return {"refused": str(exc), "samples": len(points)}
    raw = np.asarray(points, dtype=float)
    corrected = np.linalg.norm((raw - np.asarray(cal.offsetMs2)) @ np.asarray(cal.matrix).T, axis=1)
    correctedG = corrected / STANDARD_GRAVITY_MS2
    return {
        "deviceFrame": {
            "offsetMs2": toVector(np.asarray(cal.offsetMs2), 6),
            "matrix": toMatrix(np.asarray(cal.matrix), 6),
        },
        "orientations": cal.orientations,
        "residualRmsMs2": round(cal.residualRmsMs2, 4),
        "samples": cal.samples,
        "rawMeanG": round(float(np.mean(np.linalg.norm(raw, axis=1))) / STANDARD_GRAVITY_MS2, 5),
        "correctedMeanG": round(float(np.mean(correctedG)), 5),
        "correctedRmsErrorPercent": round(100.0 * float(np.sqrt(np.mean((correctedG - 1.0) ** 2))), 4),
        "describe": cal.describe(),
    }


def _mainEllipsoid(still: list[tuple[float, float, float]], result: dict[str, object], subsets: int) -> int:
    """--ellipsoid: overall + interleaved fits, and the BODY-frame config block."""
    overall = _ellipsoidSummary(still)
    result["overall"] = overall
    interleaved = [_ellipsoidSummary(still[i::subsets]) for i in range(subsets)]
    result["interleaved"] = interleaved
    fitted = [s["deviceFrame"] for s in interleaved if "deviceFrame" in s]
    if len(fitted) >= 2:
        offsets = np.asarray([f["offsetMs2"] for f in fitted])  # type: ignore[index]
        matrices = np.asarray([f["matrix"] for f in fitted])  # type: ignore[index]
        offsetSpread = float(np.max(offsets.max(axis=0) - offsets.min(axis=0)))
        elementSpread = matrices.max(axis=0) - matrices.min(axis=0)
        diagonalSpread = float(np.max(np.diag(elementSpread)))
        crossSpread = float(np.max(elementSpread[~np.eye(3, dtype=bool)]))
        if offsetSpread >= ELLIPSOID_OFFSET_SPREAD_MAX_MS2 or diagonalSpread >= ELLIPSOID_MATRIX_SPREAD_MAX:
            verdict = "unstable"
        elif crossSpread >= ELLIPSOID_MATRIX_SPREAD_MAX:
            # MEASURED: six axis-aligned faces fix offset and per-axis gain but
            # leave the cross terms to the noise (they wander +/-0.01 across
            # subsets). The fit is still right AT the faces; off-axis it can
            # be wrong by up to the true coupling. Hold oblique orientations.
            verdict = "crossAxisUnobserved"
        else:
            verdict = "stable"
        result["stability"] = {
            "offsetSpreadMs2": round(offsetSpread, 5),
            "diagonalSpread": round(diagonalSpread, 6),
            "crossSpread": round(crossSpread, 6),
            "verdict": verdict,
        }
    if "deviceFrame" not in overall:
        print(json.dumps(result, indent=2))
        return 1
    device = overall["deviceFrame"]
    bodyOffset, bodyMatrix = conjugateToBody(device["offsetMs2"], device["matrix"])  # type: ignore[index]
    result["accelCalibration"] = {
        "offsetMs2": toVector(bodyOffset, 6),
        "matrix": toMatrix(bodyMatrix, 6),
    }
    result["mount"] = dict(imu_state_bridge.IMU_BODY_FRAME)
    print(json.dumps(result, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Accelerometer scale/bias calibration")
    parser.add_argument("csv")
    parser.add_argument("--max-gyro", type=float, default=DEFAULT_MAX_GYRO_RAD_S)
    parser.add_argument("--subsets", type=int, default=4)
    parser.add_argument(
        "--ellipsoid",
        action="store_true",
        help="offset + 3x3 (ARCH-064 Task 6b) instead of bias + one scale; "
        "prints the BODY-frame accelCalibration",
    )
    args = parser.parse_args(argv)

    rows = loadRows(args.csv)
    still = quasiStaticSamples(rows, maxGyroRadS=args.max_gyro)
    if args.ellipsoid:
        return _mainEllipsoid(
            still,
            {"totalRows": len(rows), "quasiStaticRows": len(still), "maxGyroRadS": args.max_gyro},
            args.subsets,
        )

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
