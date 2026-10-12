"""ARCH-064 Task 6b: sensor-intrinsic magnetometer calibration from a hand tumble.

STAGE 1 of Ruling 27's two-stage magnetometer calibration. A hand tumble IN
PLACE rotates the sensor through every orientation in a field that does not
rotate with it, so the raw readings trace an ellipsoid whose centre is the
sensor's OWN hard iron and whose shape is its OWN per-axis gain and cross-axis
coupling -- the terms a car, which cannot tumble, can never observe (Task 6's
planar fit sees one horizontal circle). The car's iron does not rotate with the
sensor, so it only bends the reference field; it does not bias this fit.

The fit is ``mag_fit.ellipsoidFit`` (the ONE implementation, Ruling 19) with
NO reference norm: scale-preserving, ``det(A) = 1``, so the corrected field
keeps the sensor's own overall gain and stage 2 still sees a physical field
strength.

FRAME (Ruling 30). Fitted and emitted in the DEVICE frame, because stage 2
(``fit_mag_calibration --sensor-cal``) applies it to each raw device row BEFORE
the mount mapping, and composes the single body-frame ``magCalibration``
config block from both stages. A body-frame ``bodyFrameEquivalent`` is also
printed (``R b``, ``R A R^T``) for the case where no in-car fit is made; it
corrects the sensor only, not the car.

CHECKS. Refused: fewer than 3-D span or too few points (``ellipsoidFit``); a
residual RMS over ``MAX_RESIDUAL_PERCENT`` of the radius (the locus is not an
ellipsoid -- typically the sensor was carried through a field gradient rather
than rotated in place); direction coverage under ``MIN_COVERAGE_FRACTION``
(the Adafruit SensorLab procedure's "gaps"). ``--force`` accepts either and
marks the output. Warned, never refused: a field strength outside
``FIELD_STRENGTH_RANGE_UT`` (SensorLab: a corrected field should read
25-65 uT).

Usage::

    python -m tools.imu.fit_mag_tumble tumble.csv > sensor_mag_cal.json
    python -m tools.imu.fit_mag_calibration drive.csv --sensor-cal sensor_mag_cal.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass

import numpy as np

from pi.sensors.mag_fit import ellipsoidFit
from tools.imu.cal_frames import (
    SENSOR_CAL_FRAME,
    SENSOR_CAL_KEY,
    conjugateToBody,
    toMatrix,
    toVector,
)
from tools.imu.fit_mag_calibration import MAG_COLUMNS_ALIAS, MAG_COLUMNS_PRIMARY, _resolveColumnSet

Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]

MAX_RESIDUAL_PERCENT = 5.0

# Equal-area direction bins: Z_BANDS bands uniform in z (equal area on a unit
# sphere, Archimedes) x AZIMUTH_BINS sectors. 64 bins of ~1/64 sphere each.
Z_BANDS = 8
AZIMUTH_BINS = 8
MIN_SAMPLES_PER_DIRECTION_BIN = 3
MIN_COVERAGE_FRACTION = 0.6

FIELD_STRENGTH_RANGE_UT = (25.0, 65.0)


@dataclass(frozen=True)
class SensorMagFit:
    """Stage-1 result, DEVICE frame: ``m_s = matrix . (m - offsetUt)``."""

    offsetUt: Vector3
    matrix: Matrix3
    radiusUt: float
    residualRmsUt: float
    samples: int
    coverageFraction: float
    forced: bool
    fieldStrengthWarning: str | None

    @property
    def residualPercent(self) -> float:
        return 100.0 * self.residualRmsUt / self.radiusUt

    def describe(self) -> str:
        o = self.offsetUt
        forced = " (FORCED)" if self.forced else ""
        return (
            f"sensor mag ellipsoid: offset ({o[0]:+.2f}, {o[1]:+.2f}, {o[2]:+.2f}) uT, "
            f"field {self.radiusUt:.2f} uT, residual {self.residualRmsUt:.3f} uT "
            f"({self.residualPercent:.2f} %), direction coverage "
            f"{100.0 * self.coverageFraction:.0f} % over {self.samples} samples{forced}"
        )


def directionCoverage(unitVectors: np.ndarray) -> float:
    """Fraction of the 64 equal-area direction bins holding >= 3 samples."""
    z = np.clip(unitVectors[:, 2], -1.0, 1.0 - 1e-12)
    band = np.floor((z + 1.0) / 2.0 * Z_BANDS).astype(int)
    azimuth = np.arctan2(unitVectors[:, 1], unitVectors[:, 0])
    sector = np.floor((azimuth + math.pi) / (2.0 * math.pi) * AZIMUTH_BINS).astype(int) % AZIMUTH_BINS
    counts = np.bincount(band * AZIMUTH_BINS + sector, minlength=Z_BANDS * AZIMUTH_BINS)
    return float(np.count_nonzero(counts >= MIN_SAMPLES_PER_DIRECTION_BIN)) / (Z_BANDS * AZIMUTH_BINS)


def fitSensorMag(points: list[Vector3], *, force: bool = False) -> SensorMagFit:
    """Stage 1: scale-preserving ellipsoid fit of DEVICE-frame tumble readings.

    Raises:
        ValueError: anything ``ellipsoidFit`` refuses; and, unless ``force``,
            a residual over ``MAX_RESIDUAL_PERCENT`` or direction coverage
            under ``MIN_COVERAGE_FRACTION``.
    """
    fit = ellipsoidFit(points)
    raw = np.asarray(points, dtype=float)
    corrected = (raw - np.asarray(fit.offset)) @ np.asarray(fit.matrix).T
    unit = corrected / np.linalg.norm(corrected, axis=1, keepdims=True)
    coverage = directionCoverage(unit)
    residualPercent = 100.0 * fit.residualRms / fit.radius

    problems = []
    if residualPercent > MAX_RESIDUAL_PERCENT:
        problems.append(
            f"residual {residualPercent:.2f} % of the field exceeds {MAX_RESIDUAL_PERCENT} %: "
            "the locus is not an ellipsoid -- was the sensor ROTATED IN PLACE, or carried "
            "through a field gradient?"
        )
    if coverage < MIN_COVERAGE_FRACTION:
        problems.append(
            f"direction coverage {100.0 * coverage:.0f} % is under "
            f"{100.0 * MIN_COVERAGE_FRACTION:.0f} %: tumble through more orientations"
        )
    if problems and not force:
        raise ValueError("; ".join(problems))

    low, high = FIELD_STRENGTH_RANGE_UT
    warning = None
    if not low <= fit.radius <= high:
        warning = (
            f"field strength {fit.radius:.1f} uT is outside {low:.0f}-{high:.0f} uT "
            "(Earth's field): a gain error, or strong nearby iron"
        )
    return SensorMagFit(
        offsetUt=fit.offset,
        matrix=fit.matrix,
        radiusUt=fit.radius,
        residualRmsUt=fit.residualRms,
        samples=fit.samples,
        coverageFraction=coverage,
        forced=bool(problems),
        fieldStrengthWarning=warning,
    )


def loadMagPoints(path: str) -> list[Vector3]:
    """DEVICE-frame mag triples from a tumble CSV; rows with an empty or
    unparseable mag field are skipped, never defaulted."""
    points: list[Vector3] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or ())
        if not fieldnames:
            raise ValueError(f"CSV has no header row: {path}")
        magCols = _resolveColumnSet(fieldnames, "mag", MAG_COLUMNS_PRIMARY, MAG_COLUMNS_ALIAS)
        assert magCols is not None
        for row in reader:
            try:
                x, y, z = (float(row[c]) for c in magCols)
            except (KeyError, TypeError, ValueError):
                continue
            if all(math.isfinite(v) for v in (x, y, z)):
                points.append((x, y, z))
    return points


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sensor-intrinsic magnetometer ellipsoid from a hand tumble (ARCH-064 Task 6b)"
    )
    parser.add_argument("csv", help="tumble_capture.py output (DEVICE frame)")
    parser.add_argument("--force", action="store_true", help="accept a fit over the residual/coverage floors")
    args = parser.parse_args(argv)

    points: list[Vector3] = []
    try:
        points = loadMagPoints(args.csv)
        fit = fitSensorMag(points, force=args.force)
    except ValueError as exc:
        print(json.dumps({"refused": str(exc), "samples": len(points)}, indent=2))
        return 1

    bodyOffset, bodyMatrix = conjugateToBody(fit.offsetUt, fit.matrix)
    result = {
        SENSOR_CAL_KEY: {
            "frame": SENSOR_CAL_FRAME,
            "offsetUt": toVector(np.asarray(fit.offsetUt), 4),
            "matrix": toMatrix(np.asarray(fit.matrix), 6),
        },
        "bodyFrameEquivalent": {
            "hardIronUt": toVector(bodyOffset, 4),
            "softIron": toMatrix(bodyMatrix, 6),
            "note": (
                "sensor-only magCalibration (R b, R A R^T): corrects the sensor, NOT the "
                "car. Prefer fit_mag_calibration --sensor-cal, which composes both."
            ),
        },
        "fitQuality": {
            "samples": fit.samples,
            "radiusUt": round(fit.radiusUt, 3),
            "residualRmsUt": round(fit.residualRmsUt, 4),
            "residualPercent": round(fit.residualPercent, 3),
            "coverageFraction": round(fit.coverageFraction, 3),
            "forced": fit.forced,
            "fieldStrengthWarning": fit.fieldStrengthWarning,
            "describe": fit.describe(),
        },
    }
    print(json.dumps(result, indent=2))
    if fit.fieldStrengthWarning:
        print(f"WARNING: {fit.fieldStrengthWarning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
