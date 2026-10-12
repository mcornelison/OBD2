"""ARCH-064 Task 6b: tests for the Li & Griffiths (2004) ellipsoid fit.

``mag_fit.ellipsoidFit`` is the ONE ellipsoid implementation (Ruling 19, SSOT):
the accelerometer calibration and the sensor-intrinsic magnetometer calibration
both call it. So both regimes are exercised here, with the brief's exact
synthetic parameters, and every synthetic row carries noise and a real
orientation (Task 6 lesson: idealised data hid three defects).

What "correct" means: ``A . (raw - b)`` lies on a sphere. For a SYMMETRIC
distortion ``D`` (raw = D . true + b), a symmetric ``A`` is exactly
``c . D^-1``, so the tests can check the recovered matrix itself, not only the
residual. A non-symmetric ``D`` is recoverable only up to a rotation (the
ellipsoid fixes ``D . D^T``, not ``D``); the accel test uses one to show the
norms are still right.
"""

from __future__ import annotations

import numpy as np
import pytest

from pi.sensors.mag_fit import EllipsoidFit, ellipsoidFit

STANDARD_GRAVITY_MS2 = 9.80665


def _randomUnitVectors(count: int, rng: np.random.Generator) -> np.ndarray:
    """Uniform directions on the sphere (normalised Gaussian triples)."""
    v = rng.normal(size=(count, 3))
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def _rotation(axis: tuple[float, float, float], angleDeg: float) -> np.ndarray:
    """Rodrigues rotation matrix."""
    k = np.asarray(axis, dtype=float)
    k = k / np.linalg.norm(k)
    kx = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    t = np.radians(angleDeg)
    return np.eye(3) + np.sin(t) * kx + (1.0 - np.cos(t)) * (kx @ kx)


# --- the brief's accel-like parameters -----------------------------------------
ACCEL_OFFSET = np.array([0.2, -0.1, 0.18])
ACCEL_SCALE = np.array([1.02, 0.99, 1.018])
ACCEL_CROSS = 0.01
ACCEL_NOISE = 0.02


def _accelDistortion() -> np.ndarray:
    """Per-axis scale + ~0.01 cross-coupling, deliberately NOT symmetric."""
    d = np.diag(ACCEL_SCALE)
    d[0, 1], d[1, 0] = ACCEL_CROSS, -0.6 * ACCEL_CROSS
    d[0, 2], d[2, 0] = -ACCEL_CROSS, 0.8 * ACCEL_CROSS
    d[1, 2], d[2, 1] = 0.5 * ACCEL_CROSS, ACCEL_CROSS
    return d


def accelLikePoints(directions: np.ndarray, seed: int, noise: float = ACCEL_NOISE) -> np.ndarray:
    """raw = D . (g . u) + offset + N(0, 0.02) on every axis of every row."""
    rng = np.random.default_rng(seed)
    true = STANDARD_GRAVITY_MS2 * directions
    raw = true @ _accelDistortion().T + ACCEL_OFFSET
    return raw + rng.normal(scale=noise, size=raw.shape)


def sixFaceDirections(perFace: int, faces: int = 6, seed: int = 7) -> np.ndarray:
    """``perFace`` samples at each of the first ``faces`` of +x,-x,+y,-y,+z,-z,
    each face held a few degrees off-axis (a hand never places it exactly)."""
    rng = np.random.default_rng(seed)
    axes = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)][:faces]
    out = []
    for axis in axes:
        tilt = _rotation(tuple(rng.normal(size=3)), float(rng.uniform(1.0, 4.0)))
        u = tilt @ np.asarray(axis, dtype=float)
        out.extend([u] * perFace)
    return np.asarray(out)


# --- the brief's mag-like parameters -------------------------------------------
MAG_OFFSET = np.array([12.0, -7.0, 20.0])
MAG_GAINS = np.array([1.05, 0.93, 1.0])
MAG_SOFT_IRON_ROTATION = _rotation((1.0, 2.0, -0.5), 30.0)
MAG_NOISE = 0.3
MAG_FIELD_UT = 50.0


def magDistortion() -> np.ndarray:
    """A ROTATED soft iron: U . diag(gains) . U^T (symmetric, as soft iron is)."""
    u = MAG_SOFT_IRON_ROTATION
    return u @ np.diag(MAG_GAINS) @ u.T


def magLikePoints(count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    true = MAG_FIELD_UT * _randomUnitVectors(count, rng)
    raw = true @ magDistortion().T + MAG_OFFSET
    return raw + rng.normal(scale=MAG_NOISE, size=raw.shape)


def _correctedNorms(fit: EllipsoidFit, raw: np.ndarray) -> np.ndarray:
    a = np.asarray(fit.matrix, dtype=float)
    b = np.asarray(fit.offset, dtype=float)
    return np.linalg.norm((raw - b) @ a.T, axis=1)


class TestAccelLike:
    def test_allOrientationsRecoversOffsetAndNormalisesToG(self) -> None:
        raw = accelLikePoints(_randomUnitVectors(3000, np.random.default_rng(1)), seed=2)
        fit = ellipsoidFit([tuple(p) for p in raw], referenceNorm=STANDARD_GRAVITY_MS2)

        assert np.asarray(fit.offset) == pytest.approx(ACCEL_OFFSET, abs=0.01)
        # Calibration accuracy: the fit applied to the NOISE-FREE sensor, in
        # every orientation, lands within 0.3 % of g everywhere.
        clean = accelLikePoints(_randomUnitVectors(2000, np.random.default_rng(9)), seed=0, noise=0.0)
        cleanErr = np.abs(_correctedNorms(fit, clean) / STANDARD_GRAVITY_MS2 - 1.0)
        assert np.max(cleanErr) < 0.003
        # And on the noisy capture itself, the RMS norm error is within 0.3 %
        # (per-sample maxima are noise: 0.02 m/s^2 is 0.2 % of g, 1 sigma).
        noisyErr = _correctedNorms(fit, raw) / STANDARD_GRAVITY_MS2 - 1.0
        assert float(np.sqrt(np.mean(noisyErr**2))) < 0.003
        assert fit.samples == 3000
        assert fit.radius == pytest.approx(STANDARD_GRAVITY_MS2)

    def test_rawNormsAreOutsideTheToleranceTheCorrectionMeets(self) -> None:
        """The data is not already within 0.3 % -- else the test above proves nothing."""
        raw = accelLikePoints(_randomUnitVectors(3000, np.random.default_rng(1)), seed=2, noise=0.0)
        rawErr = np.abs(np.linalg.norm(raw, axis=1) / STANDARD_GRAVITY_MS2 - 1.0)
        assert np.max(rawErr) > 0.01

    def test_sixStaticFacesStillRecoverTheOffset(self) -> None:
        raw = accelLikePoints(sixFaceDirections(50), seed=3)
        fit = ellipsoidFit([tuple(p) for p in raw], referenceNorm=STANDARD_GRAVITY_MS2)
        assert np.asarray(fit.offset) == pytest.approx(ACCEL_OFFSET, abs=0.02)

    def test_residualRmsIsReportedInInputUnits(self) -> None:
        raw = accelLikePoints(_randomUnitVectors(3000, np.random.default_rng(1)), seed=2)
        fit = ellipsoidFit([tuple(p) for p in raw], referenceNorm=STANDARD_GRAVITY_MS2)
        norms = _correctedNorms(fit, raw)
        expected = float(np.sqrt(np.mean((norms - STANDARD_GRAVITY_MS2) ** 2)))
        assert fit.residualRms == pytest.approx(expected, rel=1e-9)
        # Noise 0.02 m/s^2 per axis -> radial RMS of the same order.
        assert 0.005 < fit.residualRms < 0.05


class TestMagLike:
    def test_correctedLocusIsASphereWithinOnePercentRms(self) -> None:
        raw = magLikePoints(2000, seed=11)
        fit = ellipsoidFit([tuple(p) for p in raw])
        norms = _correctedNorms(fit, raw)
        spread = float(np.sqrt(np.mean((norms - norms.mean()) ** 2)) / norms.mean())
        assert spread < 0.01

    def test_rawLocusIsNotASphere(self) -> None:
        """Guard: the uncorrected locus fails the 1 % bar (with the true offset
        removed, so only the soft iron is left) -- the correction is doing work."""
        raw = magLikePoints(2000, seed=11) - MAG_OFFSET
        norms = np.linalg.norm(raw, axis=1)
        assert float(np.std(norms) / norms.mean()) > 0.03

    def test_recoversTheOffsetAndTheInverseSoftIron(self) -> None:
        raw = magLikePoints(2000, seed=11)
        fit = ellipsoidFit([tuple(p) for p in raw])
        assert np.asarray(fit.offset) == pytest.approx(MAG_OFFSET, abs=0.3)
        # A . D must be a multiple of the identity (symmetric D -> A = c D^-1).
        product = np.asarray(fit.matrix) @ magDistortion()
        c = float(np.trace(product) / 3.0)
        assert product / c == pytest.approx(np.eye(3), abs=0.01)

    def test_matrixIsSymmetric(self) -> None:
        fit = ellipsoidFit([tuple(p) for p in magLikePoints(2000, seed=11)])
        a = np.asarray(fit.matrix)
        assert a == pytest.approx(a.T, abs=1e-12)

    def test_noReferenceNormPreservesScale(self) -> None:
        """Scale-preserving: the reference is the geometric-mean semi-axis, so
        det(A) == 1 -- the correction changes SHAPE, never overall gain."""
        raw = magLikePoints(2000, seed=11)
        fit = ellipsoidFit([tuple(p) for p in raw])
        assert float(np.linalg.det(np.asarray(fit.matrix))) == pytest.approx(1.0, abs=1e-9)
        expected = MAG_FIELD_UT * float(np.prod(MAG_GAINS)) ** (1.0 / 3.0)
        assert fit.radius == pytest.approx(expected, rel=0.005)

    def test_referenceNormSetsTheCorrectedRadius(self) -> None:
        raw = magLikePoints(2000, seed=11)
        fit = ellipsoidFit([tuple(p) for p in raw], referenceNorm=1.0)
        assert float(np.mean(_correctedNorms(fit, raw))) == pytest.approx(1.0, rel=0.002)


class TestRefusals:
    def test_refusesAPlanarCircle(self) -> None:
        """A car on level ground: the SAME refusal the sphere fit makes."""
        rng = np.random.default_rng(5)
        t = rng.uniform(0.0, 2.0 * np.pi, 500)
        pts = np.column_stack([20 * np.cos(t), 20 * np.sin(t), rng.normal(scale=0.3, size=500)])
        with pytest.raises(ValueError, match="do not span 3D"):
            ellipsoidFit([tuple(p) for p in pts])

    def test_refusesTooFewPoints(self) -> None:
        pts = [tuple(p) for p in magLikePoints(9, seed=1)]
        with pytest.raises(ValueError, match="at least"):
            ellipsoidFit(pts)

    def test_refusesANonPositiveReferenceNorm(self) -> None:
        pts = [tuple(p) for p in magLikePoints(200, seed=1)]
        with pytest.raises(ValueError, match="referenceNorm"):
            ellipsoidFit(pts, referenceNorm=0.0)

    def test_refusesNonFiniteInput(self) -> None:
        pts = [tuple(p) for p in magLikePoints(200, seed=1)]
        pts[10] = (float("nan"), 1.0, 2.0)
        with pytest.raises(ValueError, match="finite"):
            ellipsoidFit(pts)


# --- fix round 1, I1: a rotation-invariant span test --------------------------------


def _planeNormal111Points(seed: int = 6) -> np.ndarray:
    """MEASURED reviewer case: 8 held orientations in the plane with normal
    (1,1,1). Every AXIS spans widely, so the axis-aligned check passes."""
    e1 = np.array([1.0, -1.0, 0.0]) / np.sqrt(2.0)
    e2 = np.array([1.0, 1.0, -2.0]) / np.sqrt(6.0)
    dirs = np.array([np.cos(t) * e1 + np.sin(t) * e2 for t in np.linspace(0, 2 * np.pi, 8, endpoint=False)])
    return accelLikePoints(np.repeat(dirs, 50, axis=0), seed=seed)


def _band(normal, halfAngleDeg: float, count: int = 3000, seed: int = 4) -> np.ndarray:
    """Directions within +/-halfAngle of the great circle perpendicular to ``normal``."""
    rng = np.random.default_rng(seed)
    n = np.asarray(normal, dtype=float) / np.linalg.norm(normal)
    e1 = np.cross(n, [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    t = rng.uniform(0.0, 2.0 * np.pi, count)
    lat = np.radians(rng.uniform(-halfAngleDeg, halfAngleDeg, count))
    return (np.cos(lat)[:, None] * (np.cos(t)[:, None] * e1 + np.sin(t)[:, None] * e2)
            + np.sin(lat)[:, None] * n)


class TestRotationInvariantSpan:
    def test_aTiltedPlaneIsRefused(self) -> None:
        from pi.sensors.mag_fit import _assertSpansThreeDimensions

        pts = [tuple(p) for p in _planeNormal111Points()]
        _assertSpansThreeDimensions(pts)  # guard: the axis-aligned check is blind to it
        with pytest.raises(ValueError, match="do not span 3D"):
            ellipsoidFit(pts, referenceNorm=STANDARD_GRAVITY_MS2)

    @pytest.mark.parametrize("normal", [(0.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.3, -1.0, 0.5)])
    def test_aTenDegreeBandAroundARingPassesTheSpanTestInAnyOrientation(self, normal) -> None:
        """The thinnest capture the axis-aligned check accepts is a band about
        +/-8.6 degrees (0.15 span ratio); a +/-10 degree band must pass the new
        check whichever way the ring is tilted -- it changes the ORIENTATION
        dependence, not the thickness floor."""
        from pi.sensors.mag_fit import _assertSpansThreeDimensionsAnyOrientation

        pts = [tuple(p) for p in 50.0 * _band(normal, 10.0)]
        _assertSpansThreeDimensionsAnyOrientation(pts)  # does not raise

    def test_facesAndCornersPassWithAWideMargin(self) -> None:
        from pi.sensors.mag_fit import MIN_SINGULAR_VALUE_RATIO, singularValueRatio

        corners = np.array([(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]) / np.sqrt(3.0)
        dirs = np.vstack([sixFaceDirections(50), np.repeat(corners, 50, axis=0)])
        assert singularValueRatio([tuple(p) for p in accelLikePoints(dirs, seed=1)]) > 5 * MIN_SINGULAR_VALUE_RATIO

    def test_theFloorSitsBetweenANoisyPlaneAndTheThinnestAcceptedBand(self) -> None:
        from pi.sensors.mag_fit import MIN_SINGULAR_VALUE_RATIO, singularValueRatio

        plane = singularValueRatio([tuple(p) for p in _planeNormal111Points()])
        band = singularValueRatio([tuple(p) for p in 50.0 * _band((1, 1, 1), 8.6)])
        assert plane < MIN_SINGULAR_VALUE_RATIO / 5
        assert band > MIN_SINGULAR_VALUE_RATIO * 2
