"""ARCH-027: least-squares sphere fit for magnetometer calibration.

Separates two quantities that a single stationary reading confuses:

* **centre** -- the hard-iron offset, in sensor axes. Body-fixed; it moves with
  anything magnetised that is attached to the sensor.
* **radius** -- the true field strength. Earth's total field here is ~52 uT.
  A radius well below that means field is being LOST (soft iron shunting flux,
  or a scale error), which no offset subtraction can restore.

Pure Python on purpose: no numpy, so it runs in the bench venv and on the Pi
alike, and the tests need no hardware.

🔴 The fit REFUSES ill-conditioned input. Points confined to a plane (a car on
flat ground samples a horizontal circle) do not determine a sphere. Returning a
radius from such data is what made the A-30 gate unsatisfiable: the number came
back, it looked like a measurement, and it could never pass.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

# Below this, the normal-equations pivot is numerically indistinguishable from
# zero and the solution is an artefact of rounding.
_SINGULAR_PIVOT = 1e-9

# Each axis must show at least this fraction of the largest axis' spread before
# the sample set counts as spanning 3D. A horizontal circle fails on Z.
_MIN_AXIS_SPAN_RATIO = 0.15

_MIN_POINTS = 8

Vector3 = tuple[float, float, float]


@dataclass(frozen=True)
class SphereFit:
    """Result of a hard-iron sphere fit."""

    center: Vector3
    radius: float
    residualRms: float
    samples: int


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting on a small dense system."""
    size = len(rhs)
    augmented = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(size):
        pivotRow = max(range(col, size), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivotRow][col]) < _SINGULAR_PIVOT:
            raise ValueError(
                "magnetometer samples do not span 3D: the system is singular, so "
                "no sphere is determined. Rotate through more orientations."
            )
        augmented[col], augmented[pivotRow] = augmented[pivotRow], augmented[col]
        for row in range(col + 1, size):
            factor = augmented[row][col] / augmented[col][col]
            for k in range(col, size + 1):
                augmented[row][k] -= factor * augmented[col][k]
    solution = [0.0] * size
    for row in reversed(range(size)):
        total = augmented[row][size] - sum(
            augmented[row][k] * solution[k] for k in range(row + 1, size)
        )
        solution[row] = total / augmented[row][row]
    return solution


def _assertSpansThreeDimensions(points: Sequence[Vector3]) -> None:
    spans = [
        max(p[axis] for p in points) - min(p[axis] for p in points) for axis in range(3)
    ]
    widest = max(spans)
    if widest <= 0:
        raise ValueError("magnetometer samples do not span any axis (identical readings)")
    if min(spans) < widest * _MIN_AXIS_SPAN_RATIO:
        thin = [("xyz"[i], round(spans[i], 2)) for i in range(3) if spans[i] < widest * _MIN_AXIS_SPAN_RATIO]
        raise ValueError(
            f"magnetometer samples do not span 3D; thin axes {thin} against widest "
            f"{widest:.2f}. A plane or circle cannot determine a sphere."
        )


def sphereFit(points: Sequence[Vector3]) -> SphereFit:
    """Fit centre and radius by linear least squares.

    For points on a sphere: x^2+y^2+z^2 = 2ax + 2by + 2cz + d, with
    d = r^2 - a^2 - b^2 - c^2. Linear in (a, b, c, d), so the normal equations
    are a 4x4 solve.
    """
    pts = [(float(p[0]), float(p[1]), float(p[2])) for p in points]
    if len(pts) < _MIN_POINTS:
        raise ValueError(f"sphere fit needs at least {_MIN_POINTS} points, got {len(pts)}")
    _assertSpansThreeDimensions(pts)

    design = [[2.0 * x, 2.0 * y, 2.0 * z, 1.0] for x, y, z in pts]
    target = [x * x + y * y + z * z for x, y, z in pts]

    normal = [[sum(row[i] * row[j] for row in design) for j in range(4)] for i in range(4)]
    moment = [sum(design[k][i] * target[k] for k in range(len(pts))) for i in range(4)]

    a, b, c, d = _solve(normal, moment)
    radiusSquared = d + a * a + b * b + c * c
    if radiusSquared <= 0:
        raise ValueError("sphere fit produced a non-physical (negative) radius")
    radius = math.sqrt(radiusSquared)

    residuals = [
        math.sqrt((x - a) ** 2 + (y - b) ** 2 + (z - c) ** 2) - radius for x, y, z in pts
    ]
    residualRms = math.sqrt(sum(r * r for r in residuals) / len(residuals))
    return SphereFit(center=(a, b, c), radius=radius, residualRms=residualRms, samples=len(pts))


def axisRadii(points: Sequence[Vector3], center: Vector3) -> Vector3:
    """RMS distance from the centre along each axis.

    Equal on a sphere. Unequal means the field has been distorted directionally,
    which is soft iron and needs a matrix, not an offset.
    """
    count = len(points)
    if count == 0:
        raise ValueError("no points")
    sums = [0.0, 0.0, 0.0]
    for point in points:
        for axis in range(3):
            delta = point[axis] - center[axis]
            sums[axis] += delta * delta
    return (
        math.sqrt(sums[0] / count),
        math.sqrt(sums[1] / count),
        math.sqrt(sums[2] / count),
    )


def ellipticity(points: Sequence[Vector3]) -> float:
    """Ratio of largest to smallest axis radius. 1.0 is a perfect sphere.

    Uses the centroid rather than a fitted centre so it can be computed on data
    the sphere fit would refuse -- it is a diagnostic, not a calibration.
    """
    count = len(points)
    centroid = (
        sum(p[0] for p in points) / count,
        sum(p[1] for p in points) / count,
        sum(p[2] for p in points) / count,
    )
    radii = axisRadii(points, centroid)
    smallest = min(radii)
    if smallest <= 0:
        raise ValueError("degenerate point set: an axis has zero extent")
    return max(radii) / smallest
