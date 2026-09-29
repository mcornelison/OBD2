"""ARCH-064 Task 6b: accelerometer ellipsoid calibration (Ruling 19 -- EXTENDS
``accel_cal``; ``calibrateAccel`` is unchanged and still tested by
``test_accel_cal.py``).

``calibrateAccelEllipsoid`` = ``mag_fit.ellipsoidFit`` referenced to standard
gravity, plus one refusal the generic fit cannot make: fewer than six DISTINCT
orientations. Five faces still span 3D (the span test passes), so without the
orientation count the fit would return a 3x3 matrix that the data never
constrained.
"""

from __future__ import annotations

import numpy as np
import pytest

from pi.sensors.accel_cal import (
    MIN_DISTINCT_ORIENTATIONS,
    STANDARD_GRAVITY_MS2,
    calibrateAccelEllipsoid,
    countDistinctOrientations,
)
from tests.pi.sensors.test_ellipsoid_fit import (
    ACCEL_OFFSET,
    _randomUnitVectors,
    accelLikePoints,
    sixFaceDirections,
)


def _pts(raw: np.ndarray) -> list[tuple[float, float, float]]:
    return [tuple(float(c) for c in p) for p in raw]


def _correctedNorms(cal, raw: np.ndarray) -> np.ndarray:
    a = np.asarray(cal.matrix)
    return np.linalg.norm((raw - np.asarray(cal.offsetMs2)) @ a.T, axis=1)


class TestCalibrateAccelEllipsoid:
    def test_allOrientationsRecoversOffsetAndNormalisesToG(self) -> None:
        raw = accelLikePoints(_randomUnitVectors(3000, np.random.default_rng(1)), seed=2)
        cal = calibrateAccelEllipsoid(_pts(raw))
        assert np.asarray(cal.offsetMs2) == pytest.approx(ACCEL_OFFSET, abs=0.01)
        clean = accelLikePoints(_randomUnitVectors(2000, np.random.default_rng(9)), seed=0, noise=0.0)
        assert np.max(np.abs(_correctedNorms(cal, clean) / STANDARD_GRAVITY_MS2 - 1.0)) < 0.003
        assert cal.samples == 3000
        assert cal.orientations >= MIN_DISTINCT_ORIENTATIONS

    def test_sixStaticFacesRecoverTheOffsetWithinPoint02(self) -> None:
        raw = accelLikePoints(sixFaceDirections(50), seed=3)
        cal = calibrateAccelEllipsoid(_pts(raw))
        assert np.asarray(cal.offsetMs2) == pytest.approx(ACCEL_OFFSET, abs=0.02)
        assert cal.orientations == 6

    def test_sixStaticFacesCorrectEachFaceToG(self) -> None:
        raw = accelLikePoints(sixFaceDirections(50), seed=3)
        cal = calibrateAccelEllipsoid(_pts(raw))
        norms = _correctedNorms(cal, raw)
        assert abs(float(np.mean(norms)) / STANDARD_GRAVITY_MS2 - 1.0) < 0.001

    @pytest.mark.parametrize("faces", [1, 2, 3, 4, 5])
    def test_fewerThanSixFacesIsRefused(self, faces: int) -> None:
        raw = accelLikePoints(sixFaceDirections(50, faces=faces), seed=3)
        with pytest.raises(ValueError, match="distinct orientations"):
            calibrateAccelEllipsoid(_pts(raw))

    def test_fiveFacesPassTheSpanTestSoTheRefusalIsTheOrientationCount(self) -> None:
        """Guard for the test above: five faces DO span 3D, so it is the
        orientation count -- not the generic span check -- doing the refusing."""
        from pi.sensors.mag_fit import _assertSpansThreeDimensions

        raw = accelLikePoints(sixFaceDirections(50, faces=5), seed=3)
        _assertSpansThreeDimensions(_pts(raw))  # does not raise

    def test_aFewStraySamplesDoNotCountAsAFace(self) -> None:
        """Five held faces plus three samples caught at -z (a hand passing
        through) is still five faces."""
        five = accelLikePoints(sixFaceDirections(50, faces=5), seed=3)
        stray = accelLikePoints(np.array([[0.0, 0.0, -1.0]] * 3), seed=4)
        with pytest.raises(ValueError, match="distinct orientations"):
            calibrateAccelEllipsoid(_pts(np.vstack([five, stray])))

    def test_describeNamesTheCorrection(self) -> None:
        raw = accelLikePoints(sixFaceDirections(50), seed=3)
        text = calibrateAccelEllipsoid(_pts(raw)).describe()
        assert "offset" in text and "6 orientations" in text


class TestCountDistinctOrientations:
    def test_sixFacesAreSix(self) -> None:
        raw = accelLikePoints(sixFaceDirections(50), seed=3)
        assert countDistinctOrientations(_pts(raw)) == 6

    def test_oneFaceWithNoiseIsOne(self) -> None:
        raw = accelLikePoints(sixFaceDirections(200, faces=1), seed=3)
        assert countDistinctOrientations(_pts(raw)) == 1

    def test_facesTiltedByAHandStillCountOnce(self) -> None:
        """A face held 15 degrees off-axis at two different moments is ONE face."""
        from tests.pi.sensors.test_ellipsoid_fit import _rotation

        up = np.array([0.0, 0.0, 1.0])
        dirs = np.array([_rotation((1.0, 0.0, 0.0), 15.0) @ up] * 30 + [up] * 30)
        raw = accelLikePoints(dirs, seed=5)
        assert countDistinctOrientations(_pts(raw)) == 1
