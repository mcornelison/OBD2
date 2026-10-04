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


Matrix3 = tuple[Vector3, Vector3, Vector3]

# ARCH-064 fix round 1 (I1): ROTATION-INVARIANT span floor for the ellipsoid
# fit. ``_assertSpansThreeDimensions`` measures per-AXIS spans, so a plane that
# is not axis-aligned passes it (MEASURED: 8 accel orientations in the plane
# with normal (1,1,1) were ACCEPTED and read 1.38-1.45 g out of plane). The
# ratio of the smallest to the largest singular value of the centred points
# does not depend on orientation.
#   * A noisy PLANE: ratio ~ noise / field -- 0.002 (accel, 0.02 m/s^2 at g),
#     0.006 (mag, 0.3 uT at 50 uT). MEASURED < 0.01 on the reviewer's case.
#   * The THINNEST capture the axis check already accepts is a band about
#     +/-8.6 degrees around a ring (span ratio 0.15): singular ratio ~0.12.
# 0.05 sits ~5x above the noisy plane and ~2.5x below that band, so it refuses
# tilted planes without refusing anything the axis check accepts level.
MIN_SINGULAR_VALUE_RATIO = 0.05


def singularValueRatio(points: Sequence[Vector3]) -> float:
    """Smallest / largest singular value of the centred points (0 = coplanar)."""
    import numpy as np  # noqa: PLC0415 -- see ellipsoidFit

    raw = np.asarray(points, dtype=float)
    singular = np.linalg.svd(raw - raw.mean(axis=0), compute_uv=False)
    return 0.0 if singular[0] <= 0.0 else float(singular[-1] / singular[0])


def _assertSpansThreeDimensionsAnyOrientation(points: Sequence[Vector3]) -> None:
    ratio = singularValueRatio(points)
    if ratio < MIN_SINGULAR_VALUE_RATIO:
        raise ValueError(
            f"samples do not span 3D: smallest/largest singular value {ratio:.4f} is under "
            f"{MIN_SINGULAR_VALUE_RATIO} -- they lie near a plane (in ANY orientation, not "
            "only an axis-aligned one). Rotate through more orientations."
        )


# A general quadric has 10 coefficients (9 degrees of freedom). Below this the
# "fit" is an interpolation, not a measurement.
_MIN_ELLIPSOID_POINTS = 10

# Li & Griffiths' k. With k = 4 the constraint 4J - I^2 = 1 is SUFFICIENT for
# an ellipsoid whenever its shortest semi-axis is at least half its longest --
# true of every sensor this project calibrates (per-axis gains within ~10 %).
_LI_GRIFFITHS_K = 4.0


@dataclass(frozen=True)
class EllipsoidFit:
    """Result of an ellipsoid fit: ``matrix . (raw - offset)`` lies on a sphere.

    Attributes:
        offset: ``b``, the ellipsoid centre, in the input's units and frame.
        matrix: ``A``, symmetric positive-definite 3x3 (rows), mapping the
            centred ellipsoid onto a sphere of radius ``radius``.
        radius: The sphere ``A`` maps onto: ``referenceNorm`` when one was
            given, else the fitted ellipsoid's geometric-mean semi-axis (then
            ``det(A) == 1``: shape corrected, overall gain preserved).
        residualRms: RMS of ``|A . (raw - b)| - radius`` over the input.
        samples: Number of points fitted.
    """

    offset: Vector3
    matrix: Matrix3
    radius: float
    residualRms: float
    samples: int


def ellipsoidFit(
    points: Sequence[Vector3], referenceNorm: float | None = None
) -> EllipsoidFit:
    """Least-squares ellipsoid-specific fit (Li & Griffiths 2004).

    Implemented from the paper -- Q. Li and J. G. Griffiths, "Least squares
    ellipsoid specific fitting", Proc. Geometric Modeling and Processing 2004,
    pp. 335-340. The quadric

        a x^2 + b y^2 + c z^2 + 2f yz + 2g xz + 2h xy + 2p x + 2q y + 2r z + d = 0

    is fitted by minimising the algebraic residual ``|D^T v|^2`` subject to the
    ellipsoid constraint ``k J - I^2 = 1`` (``I = a+b+c``,
    ``J = ab+bc+ca-f^2-g^2-h^2``, k = 4). Partitioning ``S = D D^T`` into the
    6 quadratic and 4 linear coefficients reduces that to the eigenproblem
    ``C1^-1 (S11 - S12 S22^-1 S21) v1 = lambda v1``; the solution is the
    eigenvector of the one positive eigenvalue, and ``v2 = -S22^-1 S21 v1``.

    What the data cannot see, the fit cannot recover: six axis-aligned faces
    leave the cross terms f, g, h (nearly) unobserved. The constraint biases
    them toward zero (they lower J), but they remain noise-limited -- MEASURED
    +/-0.01 across interleaved subsets of a six-face capture at 0.02 m/s^2
    noise. Offsets and per-axis gains are unaffected; for cross-axis terms the
    capture must include oblique orientations.

    Points are centred and scaled before the fit (the quadric's columns span
    x^2 against 1, so raw magnitudes near 50 condition the system poorly) and
    the result is mapped back exactly.

    The correction is the SYMMETRIC square root: for the fitted form
    ``(x - b)^T Q (x - b) = 1``, ``A = radius . Q^(1/2)``. A symmetric ``A``
    recovers a distortion only up to a rotation when the distortion itself is
    not symmetric -- the ellipsoid fixes ``D D^T``, not ``D``.

    numpy is imported here, not at module load: ``sphereFit`` and the rest of
    this module stay pure Python (see the module docstring).

    Args:
        points: Raw 3-vectors spanning many orientations.
        referenceNorm: Radius the corrected points should have (e.g. standard
            gravity for an accelerometer). None keeps the input's own scale.

    Returns:
        :class:`EllipsoidFit`.

    Raises:
        ValueError: too few points, a non-finite value, points that do not
            span 3D (the axis test :func:`sphereFit` uses, AND the
            rotation-invariant singular-value floor), a non-positive
            ``referenceNorm``, or a fit that is not an ellipsoid.
    """
    import numpy as np  # noqa: PLC0415 -- deliberate, see docstring

    pts = [(float(p[0]), float(p[1]), float(p[2])) for p in points]
    if len(pts) < _MIN_ELLIPSOID_POINTS:
        raise ValueError(
            f"ellipsoid fit needs at least {_MIN_ELLIPSOID_POINTS} points, got {len(pts)}"
        )
    if not all(math.isfinite(c) for p in pts for c in p):
        raise ValueError("ellipsoid fit input contains a non-finite value")
    if referenceNorm is not None and not (referenceNorm > 0.0 and math.isfinite(referenceNorm)):
        raise ValueError(f"referenceNorm must be a positive finite number, got {referenceNorm!r}")
    _assertSpansThreeDimensions(pts)
    _assertSpansThreeDimensionsAnyOrientation(pts)

    raw = np.asarray(pts, dtype=float)
    mu = raw.mean(axis=0)
    sigma = float(np.sqrt(np.mean(np.sum((raw - mu) ** 2, axis=1))))
    x, y, z = ((raw - mu) / sigma).T

    design = np.vstack(
        [x * x, y * y, z * z, 2 * y * z, 2 * x * z, 2 * x * y, 2 * x, 2 * y, 2 * z, np.ones_like(x)]
    )
    s = design @ design.T
    s11, s12, s21, s22 = s[:6, :6], s[:6, 6:], s[6:, :6], s[6:, 6:]

    k = _LI_GRIFFITHS_K
    c1 = np.zeros((6, 6))
    c1[:3, :3] = k / 2.0 - 1.0
    np.fill_diagonal(c1[:3, :3], -1.0)
    c1[3:, 3:] = np.diag([-k, -k, -k])

    try:
        s22Inv = np.linalg.inv(s22)
        reduced = np.linalg.inv(c1) @ (s11 - s12 @ s22Inv @ s21)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            f"ellipsoid fit is singular ({exc}); rotate through more orientations"
        ) from exc
    eigenvalues, eigenvectors = np.linalg.eig(reduced)
    eigenvalues = np.real(eigenvalues)
    positive = np.flatnonzero(eigenvalues > 0.0)
    if positive.size == 0:
        raise ValueError("ellipsoid fit found no ellipsoid solution (no positive eigenvalue)")
    v1 = np.real(eigenvectors[:, positive[np.argmax(eigenvalues[positive])]])
    v2 = -s22Inv @ s21 @ v1
    a, b, c, f, g, h = v1
    p, q, r, d = v2

    quad = np.array([[a, h, g], [h, b, f], [g, f, c]])
    linear = np.array([p, q, r])
    try:
        centreNorm = -np.linalg.solve(quad, linear)
    except np.linalg.LinAlgError as exc:
        raise ValueError(f"ellipsoid fit is degenerate ({exc})") from exc
    scale = float(centreNorm @ quad @ centreNorm - d)
    if scale == 0.0:
        raise ValueError("ellipsoid fit is degenerate (zero scale)")
    # (u - c)^T (quad / scale) (u - c) = 1 in normalised units u = (x - mu) / sigma.
    formNorm = quad / scale
    formNorm = (formNorm + formNorm.T) / 2.0
    eigQ, vecQ = np.linalg.eigh(formNorm)
    if np.any(eigQ <= 0.0):
        raise ValueError(
            "ellipsoid fit is not an ellipsoid (the fitted quadric is not positive-definite); "
            "the samples do not describe a sensor with a stable offset and gain"
        )
    # Back to input units: (x - b)^T (Q_n / sigma^2) (x - b) = 1.
    offset = mu + sigma * centreNorm
    semiAxes = sigma / np.sqrt(eigQ)
    meanRadius = float(np.prod(semiAxes) ** (1.0 / 3.0))
    radius = meanRadius if referenceNorm is None else float(referenceNorm)
    sqrtForm = vecQ @ np.diag(np.sqrt(eigQ) / sigma) @ vecQ.T
    matrix = radius * sqrtForm
    matrix = (matrix + matrix.T) / 2.0

    corrected = np.linalg.norm((raw - offset) @ matrix.T, axis=1)
    residualRms = float(np.sqrt(np.mean((corrected - radius) ** 2)))
    rows = [(float(row[0]), float(row[1]), float(row[2])) for row in matrix]
    return EllipsoidFit(
        offset=(float(offset[0]), float(offset[1]), float(offset[2])),
        matrix=(rows[0], rows[1], rows[2]),
        radius=radius,
        residualRms=residualRms,
        samples=len(pts),
    )


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
