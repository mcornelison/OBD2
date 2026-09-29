"""ARCH-027: accelerometer scale and bias calibration from a multi-orientation capture.

THE DEFECT. At rest the ICM-20948 reads **1.0184 g** (four independent readings,
2026-09-15) against ``DEFAULT_ACCEL_TRUST_BAND = 0.02``. ``pitch_fusion`` trusts
the accelerometer as gravity only while ``| |a|/g - 1 | <= band``, so today the
reading is admitted with **0.0016 of margin**, and in-car readings of
1.020-1.021 g fall OUTSIDE it. The accelerometer is then distrusted precisely
when it is needed, the complementary filter runs on gyro alone, and pitch drifts.

🔴 **The fix is calibrating the scale, NEVER widening the band.** The band exists
to reject real acceleration -- a car braking produces a vector that is not
gravity. Widening it to admit a mis-scaled sensor also admits braking, which is
the failure the band was added to prevent.

THE METHOD. Gravity's MAGNITUDE is 9.80665 m/s^2 in every orientation. So at
rest the acceleration vector lies on a sphere of radius g centred on the
sensor's bias. Rotate through many orientations and both are measurable: the
centre is the per-axis bias, the radius is the true reading of 1 g, and their
ratio is the scale error. This is the same geometry as the magnetometer's
hard-iron fit, so it reuses ``mag_fit.sphereFit`` rather than re-deriving it --
including its REFUSAL on data that does not span 3D.

THE PRECONDITION. Only samples where the sensor is not being accelerated are
usable. During a hand rotation that means the pauses between movements, and gyro
magnitude is the available proxy for "not moving right now".
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from pi.sensors.mag_fit import ellipsoidFit, sphereFit

STANDARD_GRAVITY_MS2 = 9.80665

# Gyro magnitude below which a sample counts as "not being moved". Well above
# the healthy rest noise floor (~0.015 rad/s) and far below a hand rotation
# (0.5-3 rad/s), so it selects the pauses without selecting the sweeps.
DEFAULT_MAX_GYRO_RAD_S = 0.05

Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]

# ARCH-064 Task 6b: the ellipsoid fit has 9 unknowns (offset + symmetric 3x3).
# Six held faces (+x, -x, +y, -y, +z, -z up) are the minimum that constrain
# every per-axis offset and gain from both sides; five still SPAN 3D, so the
# generic span test cannot catch them -- this count does.
MIN_DISTINCT_ORIENTATIONS = 6

# Two gravity directions closer than this are the SAME orientation. The six
# faces are 90 degrees apart, so anything under 45 separates them; 30 absorbs a
# hand that holds a face 10-15 degrees off-axis.
ORIENTATION_CLUSTER_DEG = 30.0

# A cluster needs this many quasi-static samples to count as a held face --
# three samples caught as the hand passes through do not constrain anything.
# 10 is 0.2 s at 50 Hz; the tumble procedure holds each face for 10 s.
MIN_SAMPLES_PER_ORIENTATION = 10

# ARCH-064 fix round 1 (I1): the held orientations must not all lie in one
# plane. Smallest eigenvalue of the mean u u^T over the held-orientation seeds
# (unit vectors): 1/3 for the six faces (and for faces + corners), 0 for any
# set of coplanar directions -- eight orientations in the plane normal to
# (1,1,1) passed the count and were fitted (MEASURED, 1.38-1.45 g out of
# plane). 0.05 is one sixth of the faces' value.
MIN_ORIENTATION_SPREAD = 0.05


@dataclass(frozen=True)
class AccelCalibration:
    """Per-axis bias and a single scale factor, with the evidence to judge it."""

    biasMs2: Vector3
    measuredGMs2: float
    scaleFactor: float
    errorPercent: float
    residualRmsMs2: float
    samples: int

    def describe(self) -> str:
        """One line for a log or a report."""
        return (
            f"accel reads {self.errorPercent:+.2f}% high at 1 g "
            f"(measured {self.measuredGMs2:.4f} m/s^2, scale {self.scaleFactor:.5f}), "
            f"bias ({self.biasMs2[0]:+.3f}, {self.biasMs2[1]:+.3f}, {self.biasMs2[2]:+.3f}) m/s^2, "
            f"residual {self.residualRmsMs2:.3f} over {self.samples} samples"
        )


def quasiStaticSamples(
    rows: Sequence[tuple[Vector3, Vector3]], maxGyroRadS: float = DEFAULT_MAX_GYRO_RAD_S
) -> list[Vector3]:
    """Keep the accel vectors from moments the sensor was not being rotated.

    A sample taken mid-swing measures hand motion plus gravity, and including it
    would fit a sphere to something that is not gravity. The gyro is the
    instrument for "is it moving", because it answers that question directly
    rather than being inferred from the accelerometer under test.
    """
    kept: list[Vector3] = []
    for accel, gyro in rows:
        if math.sqrt(sum(rate * rate for rate in gyro)) <= maxGyroRadS:
            kept.append(accel)
    return kept


def calibrateAccel(points: Sequence[Vector3]) -> AccelCalibration:
    """Fit bias and scale from acceleration vectors spanning many orientations.

    Raises:
        ValueError: when the samples do not span 3D or are too few. A sensor
            sitting in ONE orientation cannot yield a scale, and returning a
            number from such data would be a guess presented as a measurement.
    """
    fit = sphereFit(points)
    measuredG = fit.radius
    scaleFactor = STANDARD_GRAVITY_MS2 / measuredG
    return AccelCalibration(
        biasMs2=fit.center,
        measuredGMs2=measuredG,
        scaleFactor=scaleFactor,
        errorPercent=(measuredG / STANDARD_GRAVITY_MS2 - 1.0) * 100.0,
        residualRmsMs2=fit.residualRms,
        samples=fit.samples,
    )


@dataclass(frozen=True)
class AccelEllipsoidCalibration:
    """Offset + 3x3 correction, ``a_c = matrix . (a - offsetMs2)``, DEVICE frame.

    ARCH-064 Task 6b. Unlike :class:`AccelCalibration` (per-axis bias + ONE
    scalar scale), this corrects per-axis gain and cross-axis coupling.
    """

    offsetMs2: Vector3
    matrix: Matrix3
    residualRmsMs2: float
    samples: int
    orientations: int

    def describe(self) -> str:
        """One line for a log or a report."""
        o = self.offsetMs2
        diag = tuple(self.matrix[i][i] for i in range(3))
        return (
            f"accel ellipsoid: offset ({o[0]:+.4f}, {o[1]:+.4f}, {o[2]:+.4f}) m/s^2, "
            f"gain diagonal ({diag[0]:.5f}, {diag[1]:.5f}, {diag[2]:.5f}), "
            f"residual {self.residualRmsMs2:.4f} m/s^2 over {self.samples} samples "
            f"in {self.orientations} orientations"
        )


def countDistinctOrientations(points: Sequence[Vector3]) -> int:
    """Count held orientations: clusters of gravity DIRECTION.

    Greedy clustering of the unit vectors: a sample joins the nearest existing
    cluster within ``ORIENTATION_CLUSTER_DEG`` of that cluster's seed, else it
    seeds a new one. Only clusters with at least
    ``MIN_SAMPLES_PER_ORIENTATION`` samples count.
    """
    return len(_heldOrientationSeeds(points))


def orientationSpread(points: Sequence[Vector3]) -> float:
    """Smallest eigenvalue of mean(u u^T) over the held-orientation seeds.

    0 when every held orientation lies in one plane (in any orientation);
    1/3 for the six faces. 0.0 when fewer than one orientation is held.
    """
    import numpy as np  # noqa: PLC0415 -- mag_fit's rule: numpy only where needed

    seeds = _heldOrientationSeeds(points)
    if not seeds:
        return 0.0
    u = np.asarray(seeds, dtype=float)
    return float(np.linalg.eigvalsh(u.T @ u / len(seeds))[0])


def _heldOrientationSeeds(points: Sequence[Vector3]) -> list[Vector3]:
    cosLimit = math.cos(math.radians(ORIENTATION_CLUSTER_DEG))
    seeds: list[Vector3] = []
    counts: list[int] = []
    for p in points:
        norm = math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2])
        if norm <= 0.0 or not math.isfinite(norm):
            continue
        u = (p[0] / norm, p[1] / norm, p[2] / norm)
        best, bestDot = -1, cosLimit
        for index, seed in enumerate(seeds):
            dot = u[0] * seed[0] + u[1] * seed[1] + u[2] * seed[2]
            if dot >= bestDot:
                best, bestDot = index, dot
        if best < 0:
            seeds.append(u)
            counts.append(1)
        else:
            counts[best] += 1
    return [seed for seed, c in zip(seeds, counts, strict=True) if c >= MIN_SAMPLES_PER_ORIENTATION]


def calibrateAccelEllipsoid(points: Sequence[Vector3]) -> AccelEllipsoidCalibration:
    """Fit offset + 3x3 from quasi-static accel vectors (ARCH-064 Task 6b).

    Feed it :func:`quasiStaticSamples` output -- the same input gate as
    :func:`calibrateAccel`. The fit is ``mag_fit.ellipsoidFit`` referenced to
    standard gravity, so ``|matrix . (a - offset)| = g`` at rest in every
    orientation. Fitted and returned in the frame the points are in (DEVICE,
    for a tumble capture); the config block is conjugated to BODY by the tool
    that emits it (Ruling 30).

    Raises:
        ValueError: fewer than ``MIN_DISTINCT_ORIENTATIONS`` held orientations,
            held orientations that lie near one plane (``MIN_ORIENTATION_SPREAD``),
            or anything ``ellipsoidFit`` refuses (too few points, not 3D).
    """
    pts = [(float(p[0]), float(p[1]), float(p[2])) for p in points]
    orientations = countDistinctOrientations(pts)
    if orientations < MIN_DISTINCT_ORIENTATIONS:
        raise ValueError(
            f"accel ellipsoid calibration needs at least {MIN_DISTINCT_ORIENTATIONS} "
            f"distinct orientations (each held for >= {MIN_SAMPLES_PER_ORIENTATION} "
            f"quasi-static samples); found {orientations}. Hold each of the six faces "
            "(+x, -x, +y, -y, +z, -z up) still."
        )
    spread = orientationSpread(pts)
    if spread < MIN_ORIENTATION_SPREAD:
        raise ValueError(
            f"the {orientations} held orientations lie near one plane (spread {spread:.3f} < "
            f"{MIN_ORIENTATION_SPREAD}); an ellipsoid is not determined out of that plane. "
            "Hold the six faces."
        )
    fit = ellipsoidFit(pts, referenceNorm=STANDARD_GRAVITY_MS2)
    return AccelEllipsoidCalibration(
        offsetMs2=fit.offset,
        matrix=fit.matrix,
        residualRmsMs2=fit.residualRms,
        samples=fit.samples,
        orientations=orientations,
    )
