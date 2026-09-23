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

from pi.sensors.mag_fit import sphereFit

STANDARD_GRAVITY_MS2 = 9.80665

# Gyro magnitude below which a sample counts as "not being moved". Well above
# the healthy rest noise floor (~0.015 rad/s) and far below a hand rotation
# (0.5-3 rad/s), so it selects the pauses without selecting the sweeps.
DEFAULT_MAX_GYRO_RAD_S = 0.05

Vector3 = tuple[float, float, float]


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
