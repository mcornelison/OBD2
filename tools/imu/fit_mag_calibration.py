"""ARCH-064 Task 6: planar hard/soft-iron magnetometer calibration fitter.

THE DEFECT THIS FITS AWAY. ``AhrsFusion`` (``pi.sensors.ahrs_fusion``) applies
``m_c = S . (m_u - h)`` to every magnetometer reading before it feeds the
heading estimate, but ships with ``h = 0`` and ``S = I`` -- a no-op. Nearby
steel (hard iron) adds a fixed offset to every reading regardless of heading,
and magnetically soft material (soft iron) distorts the field directionally,
so the raw horizontal locus is an OFF-CENTRE ELLIPSE rather than a circle
centred on the origin. Left uncorrected, the published heading carries a
heading-dependent error of tens of degrees (A-46, drive 77: hard-iron
|offset| 17.59 uT against a 16.43 uT rotating radius -- the offset EXCEEDS the
radius, so the raw bearing cannot even complete a circle).

THE METHOD. Earth's field, in vehicle coordinates, has a HORIZONTAL component
that rotates with the car's heading and a VERTICAL component that does not (it
only moves with pitch/roll, and a car is ~level). So:

* **Hard-iron x/y and soft-iron** come from a 2-D ellipse fit on the
  horizontal field: as heading sweeps 360 degrees, the (uncorrected)
  horizontal vector traces an ellipse whose CENTRE is the horizontal hard-iron
  offset and whose ECCENTRICITY/ROTATION is the soft-iron distortion. Fitting
  a scale+rotation that maps that ellipse onto a circle IS the soft-iron
  correction.
* **Hard-iron z** is just the MEAN of the vertical component across the whole
  capture (the brief's "mean vertical residual"): since the vertical
  component does not depend on heading, averaging over many headings cancels
  any horizontal leakage and leaves Earth's (constant) vertical field plus the
  z hard-iron offset.

LEVEL PROJECTION -- CHOICE MADE, AND WHY. The brief allows either gyro-gated
quasi-static rows (as ``pi.sensors.accel_cal.quasiStaticSamples`` selects for
the accelerometer fit) or a single robust mean-gravity vector. **This tool
uses the mean of ALL body-frame accel samples across the capture as the
gravity/up reference, not gyro-gated quasi-static filtering.** Reason: the
useful samples for THIS fit are exactly the ones where the car is TURNING (its
heading is changing), which is precisely when gyro magnitude is large --
gating on small gyro the way the accelerometer fit does would throw away most
of the heading diversity the ellipse needs. Averaging over the whole capture
instead relies on cornering/braking acceleration events summing toward zero
over a long, varied drive, leaving a residual dominated by the vehicle's fixed
mount tilt (measured ~2.5 degrees nose-up -- see ``imu_state_bridge``'s
IMU_BODY_FRAME_C commentary) -- the brief calls that residual "acceptable".

FRAME (Ruling 18, binding). ``edr_imu_sample`` rows hold the raw DEVICE frame.
Every accel and mag row is converted with the PRODUCTION
``pi.sensors.imu_state_bridge.resolveMountFrame`` (default mount) before
anything else runs, so the fit -- and the calibration it emits -- lives in the
same BODY/VEHICLE frame ``AhrsFusion`` applies it in.

COVERAGE REFUSAL. A capture that never turned through most of the compass
cannot determine an ellipse -- the fit would return numbers for headings it
never saw. The horizontal locus is binned into 36 10-degree heading buckets
(relative to the raw centroid, before any calibration is known) and the fit
REFUSES when fewer than 25 of 36 are occupied.

⚠️ ONLY DRIVES CAPTURED **AFTER** ARCH-064 DEPLOYS ARE VALID INPUT. Earlier
rows were recorded under the pre-ARCH-064 AK09916 axis map; feeding them here
would fit a calibration for an axis convention the sensor no longer uses.

Input: a CSV exported from ``edr_imu_sample`` (see
``src/common/edr/sensor_schema.py``) with columns ``ts_capture``,
``accel_x_ms2``/``accel_y_ms2``/``accel_z_ms2``, ``mag_x_ut``/``mag_y_ut``/
``mag_z_ut`` and (optionally, for ``--drive-id``) ``drive_id`` -- the same
unit-suffixed naming ``tools/imu/accel_cal_cli.py`` and ``tools/imu/fit_csv.py``
already use for this export shape.

Usage:
    python -m tools.imu.fit_mag_calibration capture.csv [--drive-id 42]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass

import numpy as np

from pi.sensors.imu_state_bridge import resolveMountFrame

Vector3 = tuple[float, float, float]

# 36 buckets of 10 degrees span the compass. Fewer than 25 occupied means more
# than a third of the compass was never sampled -- the ellipse the ordinate
# axes least-squares would return is an interpolation over headings never
# driven, not a fit.
HEADING_BINS = 36
BIN_WIDTH_DEG = 360.0 / HEADING_BINS
MIN_OCCUPIED_BINS = 25

# A conic has 6 coefficients (5 degrees of freedom); well under this many
# points the "fit" is closer to an exact interpolation than a measurement.
# In practice MIN_OCCUPIED_BINS is the binding constraint -- occupying 25 of
# 36 bins already requires at least 25 samples -- this is only a defensive
# floor against a pathological CSV with heavy duplication.
_MIN_SAMPLES = HEADING_BINS

# Below this, a would-be unit vector (gravity, or a horizontal-plane basis
# vector) is numerically indistinguishable from zero.
_MIN_VECTOR_NORM = 1e-6


@dataclass(frozen=True)
class MagCalibrationFit:
    """Result of the planar hard/soft-iron fit, in BODY-frame coordinates."""

    hardIronUt: Vector3
    softIron: tuple[Vector3, Vector3, Vector3]
    samples: int
    headingBinsOccupied: int
    headingBinsTotal: int
    semiAxesUt: tuple[float, float]
    rotationDeg: float
    radiusTargetUt: float
    radiusSpreadPercent: float
    residualRmsUt: float

    def toConfigBlock(self) -> dict[str, object]:
        """The ``pi.sensors.imu.magCalibration`` config block, verbatim shape."""
        return {
            "hardIronUt": [round(v, 4) for v in self.hardIronUt],
            "softIron": [[round(v, 6) for v in row] for row in self.softIron],
        }

    def describe(self) -> str:
        """One line for a log or a report."""
        return (
            f"hard iron ({self.hardIronUt[0]:+.2f}, {self.hardIronUt[1]:+.2f}, "
            f"{self.hardIronUt[2]:+.2f}) uT, ellipse axes "
            f"({self.semiAxesUt[0]:.2f}, {self.semiAxesUt[1]:.2f}) uT rotated "
            f"{self.rotationDeg:.1f} deg, {self.headingBinsOccupied}/"
            f"{self.headingBinsTotal} heading bins, corrected radius spread "
            f"{self.radiusSpreadPercent:.2f}% over {self.samples} samples"
        )


def loadRows(path: str, driveId: int | None = None) -> list[tuple[float, Vector3, Vector3]]:
    """Load ``(tsCaptureS, accelBody, magBody)`` rows from an ``edr_imu_sample`` CSV.

    Every accel and mag vector passes through ``resolveMountFrame`` (default
    mount) exactly once, here, so every consumer downstream is already in the
    BODY frame ``AhrsFusion`` applies the calibration in -- Ruling 18.

    Args:
        path: CSV path, columns as the module docstring documents.
        driveId: When given, only rows whose ``drive_id`` column matches are
            kept. A row with an unparseable or missing ``drive_id`` is
            dropped rather than assumed to match -- an ambiguous drive
            membership must not silently enter the fit.
    """
    rows: list[tuple[float, Vector3, Vector3]] = []
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            if driveId is not None:
                try:
                    rowDriveId = int(row["drive_id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if rowDriveId != driveId:
                    continue
            try:
                tsCaptureS = float(row["ts_capture"])
                accelDevice = (
                    float(row["accel_x_ms2"]),
                    float(row["accel_y_ms2"]),
                    float(row["accel_z_ms2"]),
                )
                magDevice = (
                    float(row["mag_x_ut"]),
                    float(row["mag_y_ut"]),
                    float(row["mag_z_ut"]),
                )
            except (KeyError, TypeError, ValueError):
                # A row with a missing or unparseable field is skipped rather
                # than defaulted: a fabricated zero would enter the fit as data.
                continue
            rows.append((tsCaptureS, resolveMountFrame(accelDevice), resolveMountFrame(magDevice)))
    return rows


def _meanGravity(accelBody: list[Vector3]) -> Vector3:
    """Average body-frame accel across the whole capture (see module docstring)."""
    n = len(accelBody)
    mean = (
        sum(v[0] for v in accelBody) / n,
        sum(v[1] for v in accelBody) / n,
        sum(v[2] for v in accelBody) / n,
    )
    if math.sqrt(sum(c * c for c in mean)) < _MIN_VECTOR_NORM:
        raise ValueError(
            "mean accel across the capture is ~zero -- no usable gravity reference "
            "(accel channel absent, or the capture never included any driving)"
        )
    return mean


def _levelBasis(gravity: Vector3) -> tuple[Vector3, Vector3, Vector3]:
    """Build an orthonormal (forwardHorizontal, leftHorizontal, up) body-frame basis.

    ``up`` is the gravity direction; ``forwardHorizontal`` is body +x projected
    onto the plane perpendicular to it (removing the mount-tilt component);
    ``leftHorizontal`` completes a right-handed set with a cross product, which
    -- unlike projecting +y independently -- guarantees the two horizontal axes
    are exactly orthogonal (needed for the basis-change matrix below to be its
    own inverse transpose).
    """
    gLen = math.sqrt(sum(c * c for c in gravity))
    up = (gravity[0] / gLen, gravity[1] / gLen, gravity[2] / gLen)
    fwdRaw = (1.0, 0.0, 0.0)
    dot = fwdRaw[0] * up[0] + fwdRaw[1] * up[1] + fwdRaw[2] * up[2]
    fwdProj = (fwdRaw[0] - dot * up[0], fwdRaw[1] - dot * up[1], fwdRaw[2] - dot * up[2])
    fwdLen = math.sqrt(sum(c * c for c in fwdProj))
    if fwdLen < _MIN_VECTOR_NORM:
        raise ValueError(
            "mount is tilted ~90 degrees from level (forward axis is parallel to "
            "gravity) -- no horizontal plane to project the magnetometer onto"
        )
    forward = (fwdProj[0] / fwdLen, fwdProj[1] / fwdLen, fwdProj[2] / fwdLen)
    # left = up x forward, matching the body convention (forward x left = up,
    # e.g. IMU_BODY_FRAME_C: +x forward, +y left, +z up is right-handed).
    left = (
        up[1] * forward[2] - up[2] * forward[1],
        up[2] * forward[0] - up[0] * forward[2],
        up[0] * forward[1] - up[1] * forward[0],
    )
    return forward, left, up


def _headingBinCoverage(p: np.ndarray, q: np.ndarray) -> int:
    """Count occupied 10-degree heading bins around the raw (uncalibrated) centroid."""
    centroidP = float(np.mean(p))
    centroidQ = float(np.mean(q))
    angleDeg = np.degrees(np.arctan2(q - centroidQ, p - centroidP)) % 360.0
    binIdx = (angleDeg // BIN_WIDTH_DEG).astype(int) % HEADING_BINS
    return int(np.unique(binIdx).size)


def _fitConic(p: np.ndarray, q: np.ndarray) -> tuple[float, float, float, float, float, float]:
    """General conic least-squares fit: a.x^2 + b.xy + c.y^2 + d.x + e.y + f = 0.

    Points are centred first, purely for the numerical conditioning of the
    SVD (the [x^2, xy, y^2] columns otherwise dwarf [x, y, 1] once the ellipse
    sits far from the origin); the centring is undone by the caller.
    """
    design = np.column_stack([p * p, p * q, q * q, p, q, np.ones_like(p)])
    _, _, vt = np.linalg.svd(design)
    a, b, c, d, e, f = vt[-1]
    return float(a), float(b), float(c), float(d), float(e), float(f)


def _ellipseParams(
    a: float, b: float, c: float, d: float, e: float, f: float
) -> tuple[float, float, float, float, np.ndarray]:
    """Centre, semi-axis lengths and eigenvectors of a general conic.

    Raises:
        ValueError: the conic is degenerate (singular centre system) or is not
            an ellipse (non-positive axis-squared) -- both mean the data does
            not determine an ellipse, most likely too little heading coverage
            or too much noise relative to the field's horizontal swing.
    """
    lhs = np.array([[2.0 * a, b], [b, 2.0 * c]])
    rhs = np.array([-d, -e])
    try:
        x0, y0 = np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "ellipse fit is singular -- the horizontal magnetometer samples do "
            "not determine a centre (collinear or too little heading spread)"
        ) from exc
    f0 = a * x0 * x0 + b * x0 * y0 + c * y0 * y0 + d * x0 + e * y0 + f
    quadForm = np.array([[a, b / 2.0], [b / 2.0, c]])
    eigvals, eigvecs = np.linalg.eigh(quadForm)
    axesSquared = -f0 / eigvals
    if not np.all(np.isfinite(axesSquared)) or np.any(axesSquared <= 0):
        raise ValueError(
            "conic fit is not an ellipse (non-positive axis) -- the horizontal "
            "magnetometer samples are too noisy or too collinear to fit"
        )
    axes = np.sqrt(axesSquared)
    return float(x0), float(y0), float(axes[0]), float(axes[1]), eigvecs


def fitMagCalibration(rows: list[tuple[float, Vector3, Vector3]]) -> MagCalibrationFit:
    """Fit the planar hard/soft-iron calibration from BODY-frame capture rows.

    Args:
        rows: ``(tsCaptureS, accelBody, magBody)`` as returned by ``loadRows``.

    Raises:
        ValueError: too few samples, insufficient heading coverage (< 25/36
            bins), no usable gravity reference, or a degenerate/non-ellipse fit.
    """
    if len(rows) < _MIN_SAMPLES:
        raise ValueError(f"need at least {_MIN_SAMPLES} samples, got {len(rows)}")

    accelBody = [r[1] for r in rows]
    magBody = [r[2] for r in rows]

    gravity = _meanGravity(accelBody)
    forward, left, up = _levelBasis(gravity)

    p = np.array([m[0] * forward[0] + m[1] * forward[1] + m[2] * forward[2] for m in magBody])
    q = np.array([m[0] * left[0] + m[1] * left[1] + m[2] * left[2] for m in magBody])
    r = np.array([m[0] * up[0] + m[1] * up[1] + m[2] * up[2] for m in magBody])

    occupied = _headingBinCoverage(p, q)
    if occupied < MIN_OCCUPIED_BINS:
        raise ValueError(
            f"heading coverage insufficient: {occupied}/{HEADING_BINS} 10-degree "
            f"bins occupied, need at least {MIN_OCCUPIED_BINS}. Drive through more "
            "headings -- a capture that only ever turned through part of the "
            "compass cannot determine an ellipse for the rest of it."
        )

    hz = float(np.mean(r))

    pMean, qMean = float(np.mean(p)), float(np.mean(q))
    coeffs = _fitConic(p - pMean, q - qMean)
    x0c, y0c, r1, r2, eigvecs = _ellipseParams(*coeffs)
    x0, y0 = x0c + pMean, y0c + qMean

    # Map the fitted ellipse onto a circle of the geometric-mean radius: this
    # preserves the field's total horizontal magnitude (r1 * r2 == target^2)
    # rather than favouring either axis.
    radiusTarget = math.sqrt(r1 * r2)
    rotationMatrix = eigvecs  # columns are the (orthonormal) ellipse axes
    scaleDiag = np.diag([radiusTarget / r1, radiusTarget / r2])
    softIron2D = rotationMatrix @ scaleDiag @ rotationMatrix.T

    centred = np.column_stack([p - x0, q - y0])
    corrected = centred @ softIron2D.T
    correctedRadii = np.hypot(corrected[:, 0], corrected[:, 1])
    residualRmsUt = float(np.sqrt(np.mean((correctedRadii - radiusTarget) ** 2)))
    # RMS residual as a percentage of the target radius, not (max-min)/mean:
    # with hundreds of samples a couple of noise-tail points can double a
    # max-min spread without the fit itself being any worse, exactly the way
    # SphereFit/AccelCalibration elsewhere in this codebase score a fit by its
    # RMS residual rather than by its widest single outlier.
    radiusSpreadPercent = (
        residualRmsUt / radiusTarget * 100.0 if radiusTarget > 0 else float("inf")
    )

    # Embed: B's rows are (forward, left, up) -- body vector v -> level coords
    # is B @ v. The 2-D soft-iron correction (plus an identity z row/col) is
    # applied in level coords, then B^T (== B^-1, B orthonormal) maps back to
    # the body frame AhrsFusion actually applies the calibration in.
    basis = np.array([forward, left, up])
    correction3D = np.eye(3)
    correction3D[:2, :2] = softIron2D
    softIronBody = basis.T @ correction3D @ basis
    hardIronBody = basis.T @ np.array([x0, y0, hz])

    return MagCalibrationFit(
        hardIronUt=tuple(float(v) for v in hardIronBody),
        softIron=tuple(tuple(float(v) for v in row) for row in softIronBody),
        samples=len(rows),
        headingBinsOccupied=occupied,
        headingBinsTotal=HEADING_BINS,
        semiAxesUt=(r1, r2),
        rotationDeg=math.degrees(math.atan2(eigvecs[1, 0], eigvecs[0, 0])),
        radiusTargetUt=radiusTarget,
        radiusSpreadPercent=radiusSpreadPercent,
        residualRmsUt=residualRmsUt,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Planar hard/soft-iron magnetometer calibration fit (ARCH-064)"
    )
    parser.add_argument("csv")
    parser.add_argument("--drive-id", type=int, default=None)
    args = parser.parse_args(argv)

    rows = loadRows(args.csv, driveId=args.drive_id)
    try:
        fit = fitMagCalibration(rows)
    except ValueError as exc:
        print(json.dumps({"refused": str(exc), "samples": len(rows)}, indent=2))
        return 1

    result = {
        "magCalibration": fit.toConfigBlock(),
        "fitQuality": {
            "samples": fit.samples,
            "headingBinsOccupied": fit.headingBinsOccupied,
            "headingBinsTotal": fit.headingBinsTotal,
            "semiAxesUt": [round(v, 3) for v in fit.semiAxesUt],
            "rotationDeg": round(fit.rotationDeg, 2),
            "radiusTargetUt": round(fit.radiusTargetUt, 3),
            "radiusSpreadPercent": round(fit.radiusSpreadPercent, 3),
            "residualRmsUt": round(fit.residualRmsUt, 3),
            "describe": fit.describe(),
        },
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
