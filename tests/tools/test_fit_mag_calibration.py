"""ARCH-064 Task 6: tests for the planar hard/soft-iron magnetometer fitter.

WHY AN ELLIPSE. As a car's heading sweeps 360 degrees, Earth's HORIZONTAL
field traces a circle in vehicle coordinates -- IF the magnetometer were
perfect. Hard iron shifts that circle's CENTRE; soft iron stretches and
rotates it into an ellipse. So a synthetic ellipse with a known centre, known
semi-axes and a known rotation is exactly the shape a real capture's
horizontal locus takes, and fitting it back out is the whole test.

The synthetic data is built in the BODY frame directly (accel pinned to
gravity along a chosen "up" direction -- level or tilted -- so the level-frame
basis this module derives is known exactly and the fit is scored against
unambiguous, exactly known ellipse parameters). The loader/CLI tests are where
device-frame conversion is exercised, round-tripped through the INVERSE of
the production ``resolveMountFrame`` mapping -- including, for fix round 1
(I4), under a NON-identity mount, with a proof that the round-trip assertion
can actually go red if ``resolveMountFrame`` were ever dropped from the loader.

Fix round 1 (reviewer rejected da39bc16) additions, by finding:

* C1 (Ruling 20) -- the loader accepts the REAL edr_imu_sample column names
  as primary, the unit-suffixed alias as a fallback, and raises naming what
  is missing rather than silently returning no rows.
* C2 (Ruling 22) -- hard-iron z now subtracts Earth's own vertical field
  before what is left is called hard iron; the old bug (raw mean vertical,
  no subtraction) is pinned as a NEGATIVE space -- these tests use a separate
  Earth V and a small true iron z and assert the SMALL number is recovered.
* C3 (Ruling 23) -- heading-coverage bins are centred on the FITTED ellipse
  centre, count only MOVING samples (gyro-gated), and require >=3 samples per
  bin; the dense-idle exploit that used to be accepted is now refused.
* I4 -- the mount round-trip test uses a genuinely non-identity mount and
  proves it can fail.
* I5 -- the 3x3 body-frame embedding (B^T C B) is exercised off-level, with
  the calibration applied exactly as AhrsFusion applies it
  (``m_c = S @ (m_u - h)``, src/pi/sensors/ahrs_fusion.py:310).
* m7/m8 -- the radius-spread quality floor and the (now clearly labelled)
  major-axis rotation.

Fix round 2 (reviewer rejected 143d0976; C1/C3/I4/I5/m7/m8 accepted, C2's
FORMULA accepted, but its "hz is decoupled by construction" claim REFUTED by
measurement through the production AhrsFusion), by finding, per Ruling 24:

* ``test_hardIronZDoesNotLeakIntoHeadingByConstruction`` is DELETED -- it
  evaluated heading using the SAME tilt/basis the calibration was fit from,
  comparing an attitude against itself, and so passed on the bug it existed
  to catch. See ``TestHeadingRegressionAtDifferentEvaluationTilt`` below.
* Real regression: a calibration fit from a capture at ONE gravity/tilt is
  evaluated at a DIFFERENT one, matching both the real-world case (a car is
  calibrated once; pitch varies afterward) and the reviewer's own repro.
* ``TestMainCli.test_loadColumnErrorsComeOutAsRefusedJsonNotATraceback`` --
  ``loadRows`` now runs inside ``main``'s try, so a C1 column error becomes
  this CLI's ``{"refused": ...}`` JSON, not an uncaught traceback.
* The moving/idle gyro gate now subtracts the per-axis MEDIAN gyro over the
  whole capture before comparing to ``MOVING_MIN_GYRO_RAD_S`` -- raw gyro
  carries whatever constant offset the sensor has (A-34: ~0.5 rad/s on one
  axis), which would otherwise mark every idle sample "moving" and make the
  Ruling 23 coverage defence inert. ``loadRows`` now returns the RAW gyro
  3-vector (not a precomputed magnitude); the bias estimate needs the whole
  loaded capture at once, so it lives in ``fitMagCalibration``.

Fix round 3 (reviewer re-review of 77a8bdc0; C1/C2/C3/I4/I5/m7/m8 items 1-3
addressed, item 4 -- the round-2 gyro-bias fix -- still needed work, plus
Ruling 26 was added mid-round), by finding:

* ``test_denseIdleWithAFaultedGyroBiasIsStillRefused`` was itself INERT --
  the reviewer mutated the bias to zero and it still passed, because the
  fitted-centre + >=3-per-bin coverage defences alone already refused that
  scenario. Replaced with a genuinely discriminating construction
  (``TestGyroBiasEstimation``): a FULL-COVERAGE moving sweep so coverage
  cannot save the test, plus a bias-estimation function
  (``_estimateGyroBias``) refactored out specifically so a test can patch it
  directly and PROVE the assertion goes red before trusting it green
  (``test_theAboveDiscriminates``, same pattern as I4).
* Ruling 25: the round-2 whole-capture-median bias estimate MEASURABLY fails
  on steady circling with no idle dwell -- the actual calibration procedure
  this tool expects -- because a uniformly-circling signal's own median
  converges toward the moving rate, self-cancelling and misclassifying the
  entire capture as idle (or, with idle rows added, inverting the gate
  instead). Replaced with a stationary-WINDOW estimate
  (``TestStationaryWindowBiasEstimation``): the bias comes only from samples
  whose horizontal mag direction held still over a short window, independent
  of the (possibly faulted) gyro itself.
* A real test-construction lesson found rebuilding the above: synthetic
  "moving" rows must be physically consistent -- the mag heading must
  actually move, over realistic elapsed time, at the rate the synthetic gyro
  claims -- once the fitter actually looks at mag-direction stability rather
  than trusting row order. ``_circlingRows`` / ``_boundedSweepRows`` /
  ``_stationaryRows`` replace the old index-parametrized helpers for every
  test that exercises a real gyro.
* Ruling 26 (added mid-round): a PLANAR capture cannot observe a horizontal/
  vertical gain mismatch (``TestHorizontalGainWarning``) -- ``horizontalGain``
  is always reported and a WARNING (never a refusal) fires outside 0.8-1.2.
"""

from __future__ import annotations

import csv
import json
import math

import numpy as np
import pytest

import pi.sensors.imu_state_bridge as imu_state_bridge_module
import tools.imu.fit_mag_calibration as fit_mag_calibration_module
from pi.sensors.imu_state_bridge import IMU_BODY_FRAME, resolveMountFrame
from tools.imu.fit_mag_calibration import (
    DEFAULT_EARTH_HORIZONTAL_UT,
    MAX_RADIUS_SPREAD_PERCENT_DEFAULT,
    MIN_OCCUPIED_BINS,
    fitMagCalibration,
    loadRows,
    main,
)

Vector3 = tuple[float, float, float]

_LEVEL_ACCEL: Vector3 = (0.0, 0.0, 9.80665)
_STANDARD_GRAVITY_MS2 = 9.80665
# Ruling 25: nominal EDR persist rate (~2 Hz) -- matches STATIONARY_WINDOW_S's
# own justification in the module. Synthetic gyro-bearing test data below
# uses this so the mag heading actually moves at the rate the synthetic gyro
# claims, which the stationary-window bias estimate now genuinely looks at
# (a mismatch reads as "stationary" and corrupts the bias -- this bit fix
# round 3 during construction of these very tests).
_EDR_PERSIST_DT_S = 0.5


def _ellipsePoints(
    *,
    centerP: float,
    centerQ: float,
    r1: float,
    r2: float,
    rotationDeg: float,
    hz: float,
    count: int = 360,
    noiseUt: float = 0.0,
    spanDeg: float = 360.0,
    seed: int = 42,
) -> list[Vector3]:
    """Trace a rotated ellipse in the horizontal (p, q) plane, constant z=hz.

    ``spanDeg`` lets a test cover only PART of the compass (to exercise the
    coverage refusal) without changing anything else about the shape.
    """
    rng = np.random.default_rng(seed)
    theta = math.radians(rotationDeg)
    cosT, sinT = math.cos(theta), math.sin(theta)
    points: list[Vector3] = []
    for i in range(count):
        t = math.radians(spanDeg * i / count)
        rx = r1 * math.cos(t)
        ry = r2 * math.sin(t)
        p = centerP + rx * cosT - ry * sinT
        q = centerQ + rx * sinT + ry * cosT
        r = hz
        if noiseUt:
            p += float(rng.normal(scale=noiseUt))
            q += float(rng.normal(scale=noiseUt))
            r += float(rng.normal(scale=noiseUt))
        points.append((p, q, r))
    return points


def _rowsFromMagPoints(
    points: list[Vector3],
    accel: Vector3 = _LEVEL_ACCEL,
    gyroRaw: Vector3 | None = None,
    tsStart: float = 0.0,
    tsStepS: float = 1.0,
) -> list[tuple[float, Vector3, Vector3, Vector3 | None]]:
    """Body-frame rows with no gyro column by default (Ruling 23 all-moving fallback).

    ``tsStepS`` defaults to 1.0 (not the realistic ~2 Hz EDR rate) because
    most callers pass ``gyroRaw=None``, where Ruling 25's stationary-window
    logic never runs at all and exact timestamps are irrelevant; callers
    that DO pass a real gyro and care about physically-consistent timing
    pass ``_EDR_PERSIST_DT_S`` explicitly (see ``_stationaryRows``).
    """
    return [
        (tsStart + i * tsStepS, accel, mag, gyroRaw) for i, mag in enumerate(points)
    ]


def _circlingRows(
    *,
    count: int,
    angularRateRadS: float | list[float],
    centerP: float,
    centerQ: float,
    r1: float,
    r2: float,
    rotationDeg: float,
    hz: float,
    gyroBias: Vector3 = (0.0, 0.0, 0.0),
    dtS: float = _EDR_PERSIST_DT_S,
    tsStart: float = 0.0,
    accel: Vector3 = _LEVEL_ACCEL,
) -> list[tuple[float, Vector3, Vector3, Vector3 | None]]:
    """Continuous circling (any total span, repeated laps as needed), at a
    constant or per-sample rate list -- the mag heading accumulates at the
    SAME rate the synthetic gyro reading claims, sampled at a realistic
    ~2 Hz, so the two are physically consistent (see ``_EDR_PERSIST_DT_S``).
    """
    rates = (
        angularRateRadS if isinstance(angularRateRadS, list) else [angularRateRadS] * count
    )
    theta = math.radians(rotationDeg)
    cosT, sinT = math.cos(theta), math.sin(theta)
    rows: list[tuple[float, Vector3, Vector3, Vector3 | None]] = []
    headingRad = 0.0
    for i in range(count):
        rx = r1 * math.cos(headingRad)
        ry = r2 * math.sin(headingRad)
        pLevel = centerP + rx * cosT - ry * sinT
        qLevel = centerQ + rx * sinT + ry * cosT
        magBody = (pLevel, qLevel, hz)
        gyroRawRow = (gyroBias[0] + rates[i], gyroBias[1], gyroBias[2])
        rows.append((tsStart + i * dtS, accel, magBody, gyroRawRow))
        headingRad += rates[i] * dtS
    return rows


def _boundedSweepRows(
    *,
    count: int,
    angularRateRadS: float,
    spanDeg: float,
    centerP: float,
    centerQ: float,
    r1: float,
    r2: float,
    rotationDeg: float,
    hz: float,
    gyroBias: Vector3 = (0.0, 0.0, 0.0),
    dtS: float = _EDR_PERSIST_DT_S,
    tsStart: float = 0.0,
    accel: Vector3 = _LEVEL_ACCEL,
) -> list[tuple[float, Vector3, Vector3, Vector3 | None]]:
    """Like ``_circlingRows``, but the heading bounces within ``[0, spanDeg]``
    (a triangle wave) instead of sweeping the full compass -- dense,
    physically-consistent samples confined to a limited arc, for tests where
    insufficient heading COVERAGE is the point. Only the gyro MAGNITUDE ever
    matters to the fitter, so a direction reversal at each bounce is modelled
    as a constant-magnitude reading throughout, matching a real gyro's |rate|.
    """
    stepDeg = math.degrees(angularRateRadS * dtS)
    period = 2.0 * spanDeg
    theta = math.radians(rotationDeg)
    cosT, sinT = math.cos(theta), math.sin(theta)
    rows: list[tuple[float, Vector3, Vector3, Vector3 | None]] = []
    for i in range(count):
        position = (i * stepDeg) % period
        headingDeg = position if position <= spanDeg else period - position
        t = math.radians(headingDeg)
        rx = r1 * math.cos(t)
        ry = r2 * math.sin(t)
        pLevel = centerP + rx * cosT - ry * sinT
        qLevel = centerQ + rx * sinT + ry * cosT
        magBody = (pLevel, qLevel, hz)
        gyroRawRow = (gyroBias[0] + angularRateRadS, gyroBias[1], gyroBias[2])
        rows.append((tsStart + i * dtS, accel, magBody, gyroRawRow))
    return rows


def _stationaryRows(
    *,
    count: int,
    centerP: float,
    centerQ: float,
    hz: float,
    noiseUt: float = 0.0,
    gyroBias: Vector3 = (0.0, 0.0, 0.0),
    dtS: float = _EDR_PERSIST_DT_S,
    tsStart: float = 0.0,
    accel: Vector3 = _LEVEL_ACCEL,
    seed: int = 0,
) -> list[tuple[float, Vector3, Vector3, Vector3 | None]]:
    """Parked at one heading (small noise only), realistic ~2 Hz spacing --
    so Ruling 25's window-based stationary check sees genuinely close-in-time
    neighbours, the way a real parked stretch would.
    """
    points = _ellipsePoints(
        centerP=centerP,
        centerQ=centerQ,
        r1=1.0,
        r2=1.0,
        rotationDeg=0.0,
        hz=hz,
        count=count,
        spanDeg=0.001,
        noiseUt=noiseUt,
        seed=seed,
    )
    return [(tsStart + i * dtS, accel, mag, gyroBias) for i, mag in enumerate(points)]


# ARCH-064 Task 6 brief's exact synthetic parameters for the horizontal shape.
_TRUE_CENTER_P = 12.0
_TRUE_CENTER_Q = -7.0
_TRUE_R1 = 20.0
_TRUE_R2 = 16.0
_TRUE_ROTATION_DEG = 25.0

# C2 (Ruling 22): Earth's vertical field and the TRUE (small) hard-iron z are
# now separate quantities -- the raw mean vertical (what the fit round 1 bug
# reported AS hard-iron z) is their SUM, -49.0, which is deliberately NOT
# asserted as the recovered hard-iron anywhere below.
_TRUE_EARTH_VERTICAL_UT = -52.0
_TRUE_IRON_Z_UT = 3.0
_TRUE_RAW_MEAN_VERTICAL_UT = _TRUE_EARTH_VERTICAL_UT + _TRUE_IRON_Z_UT  # -49.0


class TestFitMagCalibration:
    def test_recoversHardIronWithinPoint5UtOnACleanEllipse(self) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )

        assert fit.hardIronUt[0] == pytest.approx(_TRUE_CENTER_P, abs=0.5)
        assert fit.hardIronUt[1] == pytest.approx(_TRUE_CENTER_Q, abs=0.5)
        assert fit.hardIronUt[2] == pytest.approx(_TRUE_IRON_Z_UT, abs=0.5)

    def test_recoversHardIronWithNoise(self) -> None:
        """Realistic sensor noise, still well inside the 0.5 uT bound."""
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            noiseUt=0.15,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )

        assert fit.hardIronUt[0] == pytest.approx(_TRUE_CENTER_P, abs=0.5)
        assert fit.hardIronUt[1] == pytest.approx(_TRUE_CENTER_Q, abs=0.5)
        assert fit.hardIronUt[2] == pytest.approx(_TRUE_IRON_Z_UT, abs=0.5)

    def test_hardIronZDoesNotAbsorbEarthsField(self) -> None:
        """C2 negative check: the fix round 1 bug specifically -- the OLD
        (wrong) reading was the raw mean vertical, ~-49 uT. That must NOT be
        what the fixed fitter reports as hard-iron z.
        """
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert abs(fit.hardIronUt[2] - _TRUE_RAW_MEAN_VERTICAL_UT) > 40.0

    def test_softIronCorrectsRadiiToWithin3Percent(self) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            noiseUt=0.15,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert fit.radiusSpreadPercent < 3.0

    def test_softIronEmbedsAsIdentityOnTheZRowAndColumn(self) -> None:
        """The brief: "a 2x2 correction embedded in the 3x3 (z row/col identity)".

        Level accel means the body frame IS the level frame here, so the
        embedding is literally the z row/column -- this pins that shape.
        """
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )

        assert fit.softIron[0][2] == pytest.approx(0.0, abs=1e-9)
        assert fit.softIron[1][2] == pytest.approx(0.0, abs=1e-9)
        assert fit.softIron[2][0] == pytest.approx(0.0, abs=1e-9)
        assert fit.softIron[2][1] == pytest.approx(0.0, abs=1e-9)
        assert fit.softIron[2][2] == pytest.approx(1.0, abs=1e-9)

    def test_toConfigBlockMatchesTheMagCalibrationSchema(self) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        block = fit.toConfigBlock()

        assert set(block.keys()) == {"hardIronUt", "softIron"}
        assert len(block["hardIronUt"]) == 3
        assert len(block["softIron"]) == 3
        assert all(len(row) == 3 for row in block["softIron"])

    def test_majorAxisRotationNamesTheLargerAxis(self) -> None:
        """m8: semiAxesUt is (major, minor); the rotation describes the major one."""
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert fit.semiAxesUt[0] >= fit.semiAxesUt[1]
        assert fit.semiAxesUt[0] == pytest.approx(_TRUE_R1, abs=0.5)
        assert fit.semiAxesUt[1] == pytest.approx(_TRUE_R2, abs=0.5)
        # The major axis (r1=20) was rotated 25 degrees in construction; that
        # angle (mod 180, an axis has no direction) is what must come back.
        assert fit.majorAxisRotationDeg % 180.0 == pytest.approx(
            _TRUE_ROTATION_DEG, abs=0.5
        )

    def test_refusesInsufficientHeadingCoverage(self) -> None:
        """Only a third of the compass driven -- fewer than 25/36 bins."""
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=200,
            spanDeg=120.0,
        )
        with pytest.raises(ValueError, match="coverage"):
            fitMagCalibration(_rowsFromMagPoints(points))

    def test_acceptsCoverageRightAtTheFloor(self) -> None:
        """25/36 bins (MIN_OCCUPIED_BINS) is accepted, not rejected."""
        assert MIN_OCCUPIED_BINS == 25
        # 250 degrees of span at 10 deg/bin, ~10 pts/bin -- clears both the
        # bin-count floor and the >=3-samples-per-bin floor (Ruling 23).
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=250,
            spanDeg=250.0,
        )
        fit = fitMagCalibration(_rowsFromMagPoints(points))
        assert fit.headingBinsOccupied >= MIN_OCCUPIED_BINS

    def test_refusesTooFewSamples(self) -> None:
        with pytest.raises(ValueError, match="at least"):
            fitMagCalibration(_rowsFromMagPoints([(1.0, 2.0, 45.0)] * 5))

    def test_refusesWithNoGravityReference(self) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        rows = _rowsFromMagPoints(points, accel=(0.0, 0.0, 0.0))
        with pytest.raises(ValueError, match="gravity"):
            fitMagCalibration(rows)


class TestQualityFloor:
    """m7: refuse a fit whose corrected radius spread is untrustworthy."""

    def _noisyRows(self, noiseUt: float) -> list[tuple[float, Vector3, Vector3, float | None]]:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=360,
            noiseUt=noiseUt,
        )
        return _rowsFromMagPoints(points)

    def test_refusesASpreadOverTheFloor(self) -> None:
        # Noise scaled well past what recovers a <5% RMS spread.
        rows = self._noisyRows(noiseUt=3.0)
        with pytest.raises(ValueError, match="quality floor"):
            fitMagCalibration(rows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT)

    def test_forceAcceptsItAnywayAndMarksTheResult(self) -> None:
        rows = self._noisyRows(noiseUt=3.0)
        fit = fitMagCalibration(
            rows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT, force=True
        )
        assert fit.qualityForced is True
        assert fit.radiusSpreadPercent > MAX_RADIUS_SPREAD_PERCENT_DEFAULT

    def test_cleanFitIsNotForced(self) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert fit.qualityForced is False


class TestHorizontalGainWarning:
    """Ruling 26: a planar (level) capture cannot observe a horizontal/
    vertical gain mismatch -- it can only be MEASURED and WARNED on, never
    corrected or refused on.
    """

    def test_scaledHorizontalFieldReportsGainAndWarns(self) -> None:
        scale = 0.3
        radius = DEFAULT_EARTH_HORIZONTAL_UT * scale
        points = _ellipsePoints(
            centerP=0.0,
            centerQ=0.0,
            r1=radius,
            r2=radius,
            rotationDeg=0.0,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert fit.horizontalGain == pytest.approx(scale, abs=0.02)
        assert fit.horizontalGainWarning is not None
        assert "heading" in fit.horizontalGainWarning
        assert "grade" in fit.horizontalGainWarning

    def test_unscaledFieldDoesNotWarn(self) -> None:
        points = _ellipsePoints(
            centerP=0.0,
            centerQ=0.0,
            r1=DEFAULT_EARTH_HORIZONTAL_UT,
            r2=DEFAULT_EARTH_HORIZONTAL_UT,
            rotationDeg=0.0,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert fit.horizontalGain == pytest.approx(1.0, abs=0.02)
        assert fit.horizontalGainWarning is None


class TestCoverageExploit:
    """C3 (Ruling 23): the dense-idle exploit that fit round 1 accepted."""

    def test_denseIdleDwellIsRefused(self) -> None:
        """MEASURED regression: 2000 idle samples (parked) + a real,
        physically-consistent 300-sample sweep confined to 90 degrees, used
        to be ACCEPTED at 32/36 bins with the hard-iron offset off by 12 uT,
        because the naive centroid sat near the dense idle cluster and noise
        scattered it across many spurious bins. Moving-only, fitted-centre,
        >=3-per-bin binning must refuse this instead -- on insufficient
        coverage (a 90-degree arc reaches at most 9 of the 36 bins, however
        densely sampled).
        """
        idleRows = _stationaryRows(
            count=2000,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            noiseUt=0.6,
            gyroBias=(0.0, 0.0, 0.0),
            tsStart=0.0,
            seed=1,
        )
        movingRows = _boundedSweepRows(
            count=300,
            angularRateRadS=0.3,
            spanDeg=90.0,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            tsStart=2000.0 * _EDR_PERSIST_DT_S + 60.0,  # well after the idle block
        )
        with pytest.raises(ValueError, match="coverage"):
            fitMagCalibration(idleRows + movingRows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT)

    def test_idleSamplesDoNotCountEvenWhenCoverageWouldOtherwisePass(self) -> None:
        """A full-coverage moving sweep plus a huge idle cluster must fit
        (and refuse-or-not) IDENTICALLY to the moving sweep alone -- proving
        idle rows are excluded, not merely down-weighted.
        """
        movingRows = _circlingRows(
            count=360,
            angularRateRadS=0.3,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            tsStart=0.0,
        )
        # Ruling 25: even the "moving-only" baseline needs SOME stationary
        # samples to estimate a bias from (a pure, unbroken turn refuses --
        # see TestStationaryWindowBiasEstimation) -- a small bookend, at the
        # true centre so it cannot itself bias hardIronUt away from the
        # moving-only shape.
        baselineBookend = _stationaryRows(
            count=60,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            gyroBias=(0.0, 0.0, 0.0),
            tsStart=360.0 * _EDR_PERSIST_DT_S + 30.0,
            seed=6,
        )
        withoutIdle = fitMagCalibration(
            movingRows + baselineBookend, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert withoutIdle.movingSamples == 360

        idleRows = _stationaryRows(
            count=2000,
            centerP=_TRUE_CENTER_P + 5.0,  # deliberately off-centre
            centerQ=_TRUE_CENTER_Q - 5.0,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            noiseUt=0.6,
            gyroBias=(0.0, 0.0, 0.0),
            tsStart=360.0 * _EDR_PERSIST_DT_S + 60.0,  # well after the moving block
            seed=3,
        )
        withIdle = fitMagCalibration(
            movingRows + idleRows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )

        assert withIdle.hardIronUt == pytest.approx(withoutIdle.hardIronUt, abs=1e-6)
        assert withIdle.movingSamples == withoutIdle.movingSamples == 360


class TestGyroBiasEstimation:
    """Ruling 24/25: which samples the gyro bias is estimated from.

    Fix round 2's discrimination test for Ruling 24 (whole-capture median)
    was MEASURED to be INERT by the reviewer: it still passed with the bias
    mutated to zero, because the fitted-centre + >=3-per-bin coverage
    defences alone already refused that scenario regardless. Replaced here
    with the reviewer's own construction, which does discriminate, PROVEN
    below by patching ``_estimateGyroBias`` directly (not asserted blind).

    Ruling 25 replaced the whole-capture-median mechanism itself: it fails
    MEASURABLY on steady circling with no idle dwell -- the actual
    calibration procedure this tool expects -- because a uniformly-circling
    signal's own median converges toward the moving rate, self-cancelling.
    See ``TestStationaryWindowBiasEstimation`` below.
    """

    def test_denseIdleWithAFaultedGyroBiasIsExcludedFromTheFit(self) -> None:
        """Item A's exact construction: a full-coverage 360-row moving sweep
        (alternating 0.3/0.7 rad/s yaw, plus a +0.5 rad/s fault bias) plus
        2000 off-centre idle rows carrying the SAME fault bias alone. The
        idle rows must be excluded entirely: movingSamples stays at 360 and
        hardIronUt matches a moving-only fit, recovering the true iron
        (12, -7, 3).
        """
        faultBiasRadS = 0.5
        alternatingRates = [0.3 if i % 2 == 0 else 0.7 for i in range(360)]
        movingRows = _circlingRows(
            count=360,
            angularRateRadS=alternatingRates,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            gyroBias=(faultBiasRadS, 0.0, 0.0),
            tsStart=0.0,
        )
        # Ruling 25: the moving-only baseline needs its own small stationary
        # bookend to estimate the fault bias from (a pure, unbroken turn
        # refuses); placed at the TRUE centre so it cannot itself bias
        # hardIronUt away from the moving-only shape.
        baselineBookend = _stationaryRows(
            count=60,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            gyroBias=(faultBiasRadS, 0.0, 0.0),
            tsStart=360.0 * _EDR_PERSIST_DT_S + 30.0,
            seed=7,
        )
        withoutIdle = fitMagCalibration(
            movingRows + baselineBookend, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert withoutIdle.movingSamples == 360
        assert withoutIdle.hardIronUt == pytest.approx((12.0, -7.0, 3.0), abs=0.5)

        idleRows = _stationaryRows(
            count=2000,
            centerP=_TRUE_CENTER_P + 5.0,  # off-centre
            centerQ=_TRUE_CENTER_Q - 5.0,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            noiseUt=0.6,
            gyroBias=(faultBiasRadS, 0.0, 0.0),  # the fault alone, no real rate
            tsStart=360.0 * _EDR_PERSIST_DT_S + 60.0,
            seed=4,
        )
        combined = fitMagCalibration(
            movingRows + idleRows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )

        assert combined.movingSamples == 360
        assert combined.hardIronUt == pytest.approx(withoutIdle.hardIronUt, abs=1e-6)

    def test_theAboveDiscriminates(self, monkeypatch) -> None:
        """PROOF, not assertion: patch ``_estimateGyroBias`` to return zero
        (the reviewer's own mutation) and confirm the test above's assertion
        actually goes RED, before trusting that the real code is GREEN.
        """
        faultBiasRadS = 0.5
        alternatingRates = [0.3 if i % 2 == 0 else 0.7 for i in range(360)]
        movingRows = _circlingRows(
            count=360,
            angularRateRadS=alternatingRates,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            gyroBias=(faultBiasRadS, 0.0, 0.0),
            tsStart=0.0,
        )
        idleRows = _stationaryRows(
            count=2000,
            centerP=_TRUE_CENTER_P + 5.0,
            centerQ=_TRUE_CENTER_Q - 5.0,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            noiseUt=0.6,
            gyroBias=(faultBiasRadS, 0.0, 0.0),
            tsStart=360.0 * _EDR_PERSIST_DT_S + 60.0,
            seed=4,
        )
        baselineBookend = _stationaryRows(
            count=60,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            gyroBias=(faultBiasRadS, 0.0, 0.0),
            tsStart=360.0 * _EDR_PERSIST_DT_S + 30.0,
            seed=7,
        )
        withoutIdle = fitMagCalibration(
            movingRows + baselineBookend, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )

        originalEstimate = fit_mag_calibration_module._estimateGyroBias
        fit_mag_calibration_module._estimateGyroBias = (
            lambda tsArray, p, q, gyroMatrix: np.zeros(3)
        )
        try:
            # RED: with the bias forced to zero, the fault (0.5 rad/s) is
            # never removed, so the 2000 off-centre idle rows clear the
            # moving threshold too and corrupt the fit -- MEASURED by the
            # reviewer to land the radius spread at 22.6%, past the m7
            # quality floor.
            with pytest.raises(ValueError, match="quality floor"):
                fitMagCalibration(
                    movingRows + idleRows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
                )
        finally:
            fit_mag_calibration_module._estimateGyroBias = originalEstimate

        # GREEN: restored, the real code excludes the idle rows correctly.
        combined = fitMagCalibration(
            movingRows + idleRows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert combined.movingSamples == 360
        assert combined.hardIronUt == pytest.approx(withoutIdle.hardIronUt, abs=1e-6)


class TestStationaryWindowBiasEstimation:
    """Ruling 25: steady circling -- the calibration procedure this tool
    actually expects the CIO to drive -- must not be misread as idle.
    """

    def test_circlingWithStationaryBookendsIsAcceptedWithAFaultedBias(self) -> None:
        """MEASURED regression: 2500 samples circling at 0.3 rad/s (no idle
        at all) used to be REFUSED as "mostly idled" -- the old whole-capture
        median self-cancelled toward the moving rate itself, since there was
        no idle contrast to anchor it, misclassifying the ENTIRE capture as
        idle despite the car never stopping turning. Adding a stationary
        bookend (300 rows, ~30 s parked) gives the stationary-window
        estimate something real to find; a +0.5 rad/s fault bias on every
        row must not change the outcome.
        """
        faultBiasRadS = 0.5
        stationaryRows = _stationaryRows(
            count=300,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            noiseUt=0.6,
            gyroBias=(faultBiasRadS, 0.0, 0.0),
            tsStart=0.0,
            seed=5,
        )
        circlingRows = _circlingRows(
            count=2500,
            angularRateRadS=0.3,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            gyroBias=(faultBiasRadS, 0.0, 0.0),
            tsStart=300.0 * _EDR_PERSIST_DT_S + 60.0,
        )

        fit = fitMagCalibration(
            stationaryRows + circlingRows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )

        assert fit.hardIronUt[0] == pytest.approx(_TRUE_CENTER_P, abs=0.5)
        assert fit.hardIronUt[1] == pytest.approx(_TRUE_CENTER_Q, abs=0.5)

    def test_circlingWithNoStationaryRowsIsRefusedWithTheNewMessage(self) -> None:
        """No parked stretch anywhere in the capture -- there is nothing a
        gyro bias can be estimated FROM -- refuses with Ruling 25's own
        message, not the old (and here actively wrong) "mostly idled" one.
        """
        circlingRows = _circlingRows(
            count=2500,
            angularRateRadS=0.3,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            tsStart=0.0,
        )
        with pytest.raises(ValueError, match="non-turning samples"):
            fitMagCalibration(circlingRows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT)


def _deviceFrameFromBody(vecBody: Vector3, mount: dict[str, str] = IMU_BODY_FRAME) -> Vector3:
    """Invert ``resolveMountFrame``: body (forward, left, up) -> raw device axes.

    Generic over any signed-permutation mount (each device axis is named
    exactly once, across forward/left/up, optionally negated -- true of every
    ``IMU_BODY_FRAME_*`` this project has ever shipped), so this round-trips
    correctly under a non-identity mount too (I4).
    """
    device = [0.0, 0.0, 0.0]
    axisIndex = {"x": 0, "y": 1, "z": 2}
    for roleIdx, role in enumerate(("forward", "left", "up")):
        spec = mount[role].strip().lower()
        sign = -1.0 if spec.startswith("-") else 1.0
        axis = spec.lstrip("+-")
        device[axisIndex[axis]] = sign * vecBody[roleIdx]
    return (device[0], device[1], device[2])


def _writeCsv(
    path: str,
    rows: list[tuple[float, int | None, Vector3, Vector3]],
    *,
    columnStyle: str = "primary",
    includeGyro: bool = False,
    gyroDevice: Vector3 = (0.0, 0.0, 0.0),
) -> None:
    if columnStyle == "primary":
        accelHeader = ["accel_x", "accel_y", "accel_z"]
        magHeader = ["mag_x", "mag_y", "mag_z"]
        gyroHeader = ["gyro_x", "gyro_y", "gyro_z"]
    elif columnStyle == "alias":
        accelHeader = ["accel_x_ms2", "accel_y_ms2", "accel_z_ms2"]
        magHeader = ["mag_x_ut", "mag_y_ut", "mag_z_ut"]
        gyroHeader = ["gyro_x_rads", "gyro_y_rads", "gyro_z_rads"]
    else:
        raise ValueError(columnStyle)

    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        header = ["ts_capture", "drive_id", *accelHeader, *magHeader]
        if includeGyro:
            header += gyroHeader
        writer.writerow(header)
        for ts, driveId, accelDevice, magDevice in rows:
            line = [ts, "" if driveId is None else driveId, *accelDevice, *magDevice]
            if includeGyro:
                line += list(gyroDevice)
            writer.writerow(line)


# The LITERAL column order of `select * from edr_imu_sample` (C1), per
# src/common/edr/sensor_schema.py's SCHEMA_EDR_IMU_SAMPLE DDL -- what
# `sqlite3 -csv -header obd.db "select * from edr_imu_sample where drive_id=N"`
# actually produces, extra columns and all.
_REAL_EDR_IMU_SAMPLE_HEADER = [
    "id",
    "ts_utc",
    "ts_capture",
    "seq",
    "accel_x",
    "accel_y",
    "accel_z",
    "gyro_x",
    "gyro_y",
    "gyro_z",
    "mag_x",
    "mag_y",
    "mag_z",
    "temp_c",
    "drive_id",
    "data_source",
    "schema_version",
]


class TestLoadRows:
    def test_roundTripsThroughTheInverseMountMapping(self, tmp_path) -> None:
        """The defining property: what comes back out is what the body-frame
        producer would have seen, proving resolveMountFrame really ran.
        """
        accelBody: Vector3 = (0.1, -0.2, 9.75)
        magBody: Vector3 = (5.0, -3.0, 40.0)
        accelDevice = _deviceFrameFromBody(accelBody)
        magDevice = _deviceFrameFromBody(magBody)
        assert resolveMountFrame(accelDevice) == pytest.approx(accelBody)
        assert resolveMountFrame(magDevice) == pytest.approx(magBody)

        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), [(1.0, None, accelDevice, magDevice)])

        rows = loadRows(str(csvPath))
        assert len(rows) == 1
        tsCaptureS, loadedAccel, loadedMag, gyroRaw = rows[0]
        assert tsCaptureS == pytest.approx(1.0)
        assert loadedAccel == pytest.approx(accelBody)
        assert loadedMag == pytest.approx(magBody)
        assert gyroRaw is None  # no gyro columns in this CSV

    def test_roundTripUnderANonIdentityMountDiscriminates(self, tmp_path, monkeypatch) -> None:
        """I4: IMU_BODY_FRAME is currently the identity, so a round-trip test
        against it alone cannot fail. Monkeypatch it to a real, non-identity
        mount and PROVE the assertion below can go red -- by temporarily
        dropping resolveMountFrame from the loader (an identity pass-through)
        and confirming it disagrees with body-frame truth -- before trusting
        the restored, GREEN case.
        """
        nonIdentityMount = {"forward": "-y", "left": "+x", "up": "+z"}
        monkeypatch.setattr(imu_state_bridge_module, "IMU_BODY_FRAME", nonIdentityMount)

        accelBody: Vector3 = (0.1, -0.2, 9.75)
        magBody: Vector3 = (5.0, -3.0, 40.0)
        accelDevice = _deviceFrameFromBody(accelBody, mount=nonIdentityMount)
        magDevice = _deviceFrameFromBody(magBody, mount=nonIdentityMount)
        # Sanity: the (patched-default) resolveMountFrame really does invert
        # this device vector back to the body vector under the new mount.
        assert resolveMountFrame(accelDevice) == pytest.approx(accelBody)
        assert accelDevice != pytest.approx(accelBody)  # mount is genuinely non-identity

        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), [(1.0, None, accelDevice, magDevice)])

        # RED proof: with resolveMountFrame swapped for an identity pass-
        # through, the loader must return the raw DEVICE vector, which is NOT
        # close to accelBody under this non-identity mount.
        originalResolve = fit_mag_calibration_module.resolveMountFrame
        fit_mag_calibration_module.resolveMountFrame = lambda vec, mount=None: vec
        try:
            brokenRows = loadRows(str(csvPath))
            brokenAccel = brokenRows[0][1]
            assert brokenAccel != pytest.approx(accelBody)
        finally:
            fit_mag_calibration_module.resolveMountFrame = originalResolve

        # GREEN: restored, the loader recovers the true body-frame vectors.
        rows = loadRows(str(csvPath))
        assert len(rows) == 1
        _, loadedAccel, loadedMag, _ = rows[0]
        assert loadedAccel == pytest.approx(accelBody)
        assert loadedMag == pytest.approx(magBody)

    def test_acceptsTheRealEdrImuSampleColumnNames(self, tmp_path) -> None:
        """C1: the literal column list a real export produces, extra columns
        (id, ts_utc, seq, temp_c, data_source, schema_version) and all.
        """
        csvPath = tmp_path / "capture.csv"
        accelBody: Vector3 = (0.1, -0.2, 9.75)
        magBody: Vector3 = (5.0, -3.0, 40.0)
        gyroDevice: Vector3 = (0.01, -0.02, 0.03)
        accelDevice = _deviceFrameFromBody(accelBody)
        magDevice = _deviceFrameFromBody(magBody)

        with open(csvPath, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(_REAL_EDR_IMU_SAMPLE_HEADER)
            writer.writerow(
                [
                    1,  # id
                    "2026-09-28T00:00:00Z",  # ts_utc
                    12.5,  # ts_capture
                    7,  # seq
                    *accelDevice,
                    *gyroDevice,
                    *magDevice,
                    21.0,  # temp_c
                    99,  # drive_id
                    "real",  # data_source
                    1,  # schema_version
                ]
            )

        rows = loadRows(str(csvPath))
        assert len(rows) == 1
        tsCaptureS, loadedAccel, loadedMag, gyroRaw = rows[0]
        assert tsCaptureS == pytest.approx(12.5)
        assert loadedAccel == pytest.approx(accelBody)
        assert loadedMag == pytest.approx(magBody)
        # Ruling 24: gyro is returned RAW here (device frame, no bias
        # correction) -- the per-axis median bias subtraction is
        # fitMagCalibration's job, over the whole loaded capture at once.
        assert gyroRaw == pytest.approx(gyroDevice)

        assert loadRows(str(csvPath), driveId=99) == rows
        assert loadRows(str(csvPath), driveId=1) == []

    def test_acceptsTheAliasColumnNames(self, tmp_path) -> None:
        accelBody: Vector3 = (0.1, -0.2, 9.75)
        magBody: Vector3 = (5.0, -3.0, 40.0)
        accelDevice = _deviceFrameFromBody(accelBody)
        magDevice = _deviceFrameFromBody(magBody)
        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), [(1.0, None, accelDevice, magDevice)], columnStyle="alias")

        rows = loadRows(str(csvPath))
        assert len(rows) == 1
        assert rows[0][1] == pytest.approx(accelBody)
        assert rows[0][2] == pytest.approx(magBody)

    def test_raisesNamingMissingColumnsRatherThanReturningNoRows(self, tmp_path) -> None:
        """C1: the fit round 1 bug -- wrong header used to silently load 0
        rows. It must now raise, naming what is missing, before any row loop.
        """
        csvPath = tmp_path / "capture.csv"
        with open(csvPath, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ts_capture", "accel_x", "accel_y", "accel_z"])  # no mag at all
            writer.writerow([1.0, 0.0, 0.0, 9.8])

        with pytest.raises(ValueError, match="mag"):
            loadRows(str(csvPath))

    def test_raisesOnAnEmptyOrHeaderlessCsv(self, tmp_path) -> None:
        csvPath = tmp_path / "capture.csv"
        csvPath.write_text("")
        with pytest.raises(ValueError, match="header"):
            loadRows(str(csvPath))

    def test_parsesRawGyroWhenGyroColumnsArePresent(self, tmp_path) -> None:
        accelBody: Vector3 = (0.0, 0.0, 9.80665)
        magBody: Vector3 = (1.0, 2.0, 3.0)
        gyroDevice: Vector3 = (0.3, 0.4, 0.0)
        csvPath = tmp_path / "capture.csv"
        _writeCsv(
            str(csvPath),
            [(1.0, None, _deviceFrameFromBody(accelBody), _deviceFrameFromBody(magBody))],
            includeGyro=True,
            gyroDevice=gyroDevice,
        )
        rows = loadRows(str(csvPath))
        # Ruling 24: returned RAW (not a magnitude, no bias correction) --
        # the median bias estimate needs the whole capture at once.
        assert rows[0][3] == pytest.approx(gyroDevice)

    def test_filtersByDriveId(self, tmp_path) -> None:
        driveRows = [
            (1.0, 7, _LEVEL_ACCEL, (1.0, 2.0, 3.0)),
            (2.0, 8, _LEVEL_ACCEL, (4.0, 5.0, 6.0)),
            (3.0, 7, _LEVEL_ACCEL, (7.0, 8.0, 9.0)),
        ]
        csvPath = tmp_path / "capture.csv"
        _writeCsv(
            str(csvPath),
            [
                (ts, drive, _deviceFrameFromBody(a), _deviceFrameFromBody(m))
                for ts, drive, a, m in driveRows
            ],
        )

        assert len(loadRows(str(csvPath))) == 3
        onlyDrive7 = loadRows(str(csvPath), driveId=7)
        assert len(onlyDrive7) == 2
        assert all(ts in (1.0, 3.0) for ts, _, _, _ in onlyDrive7)

    def test_skipsRowsMissingFields(self, tmp_path) -> None:
        csvPath = tmp_path / "capture.csv"
        with open(csvPath, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ts_capture", "accel_x", "accel_y", "accel_z", "mag_x", "mag_y", "mag_z"])
            writer.writerow([1.0, 0.0, 0.0, 9.8, "", 0.0, 0.0])  # mag_x blank/unparsable
        assert loadRows(str(csvPath)) == []


def _tiltedBasis(tiltDeg: float) -> tuple[Vector3, Vector3, Vector3]:
    """Body-frame (forward, left, up) for a small tilt about the left axis.

    Hand-derived independently of the module's own ``_levelBasis`` (same
    Gram-Schmidt construction is the ONLY orthonormal answer for a given up
    vector and a forward seed, so the numbers necessarily agree -- but this
    test builds its ground truth without calling the private helper under
    test, per the module's own public-API testing style).
    """
    theta = math.radians(tiltDeg)
    forward = (math.cos(theta), 0.0, -math.sin(theta))
    left = (0.0, 1.0, 0.0)
    up = (math.sin(theta), 0.0, math.cos(theta))
    return forward, left, up


def _applyCalibrationLikeAhrsFusion(
    vec: Vector3, hardIronUt: Vector3, softIron: tuple[Vector3, Vector3, Vector3]
) -> np.ndarray:
    """m_c = S @ (m_u - h) -- verbatim, src/pi/sensors/ahrs_fusion.py:310."""
    h = np.asarray(hardIronUt, dtype=float)
    s = np.asarray(softIron, dtype=float)
    return s @ (np.asarray(vec, dtype=float) - h)


def _magBodyRows(
    *,
    tiltDeg: float,
    centerP: float,
    centerQ: float,
    r1: float,
    r2: float,
    rotationDeg: float,
    rLevel: float,
    headingsDeg: list[float],
) -> tuple[tuple[Vector3, Vector3, Vector3], Vector3, dict[float, Vector3]]:
    """Body-frame (basis, gravity, magByHeading) for a tilted mount.

    Independent of the module's own ``_levelBasis`` -- see ``_tiltedBasis``.
    """
    forward, left, up = _tiltedBasis(tiltDeg)
    gravityBody: Vector3 = (
        _STANDARD_GRAVITY_MS2 * up[0],
        _STANDARD_GRAVITY_MS2 * up[1],
        _STANDARD_GRAVITY_MS2 * up[2],
    )
    theta = math.radians(rotationDeg)
    cosT, sinT = math.cos(theta), math.sin(theta)

    magBodyByHeading: dict[float, Vector3] = {}
    for headingDeg in headingsDeg:
        t = math.radians(headingDeg)
        rx = r1 * math.cos(t)
        ry = r2 * math.sin(t)
        pLevel = centerP + rx * cosT - ry * sinT
        qLevel = centerQ + rx * sinT + ry * cosT
        magBody = (
            pLevel * forward[0] + qLevel * left[0] + rLevel * up[0],
            pLevel * forward[1] + qLevel * left[1] + rLevel * up[1],
            pLevel * forward[2] + qLevel * left[2] + rLevel * up[2],
        )
        magBodyByHeading[headingDeg] = magBody
    return (forward, left, up), gravityBody, magBodyByHeading


class TestTiltedEmbedding:
    """I5: the B^T C B embedding, exercised off-level with a genuinely
    anisotropic ellipse. Only the SHAPE claim (corrected locus is a circle)
    is asserted here -- a general hard/soft-iron fit from shape alone cannot
    recover an absolute heading REFERENCE (a circle has full rotational
    symmetry; nothing in the ellipse's shape says which point on it is
    heading zero), so asserting recovered angle == true parametrized heading
    for an ANISOTROPIC ellipse is not a sound thing to test -- that is what
    ``TestHeadingRegressionAtDifferentEvaluationTilt`` (Ruling 24, below) is
    for, with a pure circle, and evaluated at a DIFFERENT tilt than the
    capture that produced the calibration.

    Ruling 24 correction: fix round 1 had a test here
    (``test_hardIronZDoesNotLeakIntoHeadingByConstruction``) claiming a wrong
    hz provably cannot move corrected heading, "proven algebraically" from
    the embedding's block-diagonal structure. That test evaluated heading
    using the SAME tilt/basis the calibration was fitted from -- so it
    compared an attitude against itself and passed on the bug by
    construction. REFUTED BY MEASUREMENT: run through the production
    ``pi.sensors.ahrs_fusion.AhrsFusion`` with the capture level and heading
    evaluated at a genuinely DIFFERENT pitch, the pre-fix hz gives 8.6 degree
    error at +3 degrees and 17.1 at +6; the fixed default gives 0.5 and 1.0.
    The mechanism (module docstring, Ruling 22 section) was right all along:
    hard iron is fixed in BODY coordinates, so a wrong hz applied against a
    reading taken at a tilt OTHER than the fit's own re-introduces exactly
    the leak the algebra above wrongly ruled out. The disproven test has been
    deleted, not reworked -- it asserted a property that does not hold.
    """

    def test_correctedEllipseLocusIsACircleAtRealisticMountTilt(self) -> None:
        """I5: nose-up gravity (2.5 degrees) + a genuinely rotated/anisotropic
        ellipse. Apply the emitted (h, S) exactly as AhrsFusion does.
        """
        headingsDeg = [float(d) for d in range(0, 360, 2)]
        (forward, left, up), gravityBody, magBodyByHeading = _magBodyRows(
            tiltDeg=2.5,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            rLevel=_TRUE_RAW_MEAN_VERTICAL_UT,
            headingsDeg=headingsDeg,
        )
        rows = [
            (float(i), gravityBody, magBody, None)
            for i, magBody in enumerate(magBodyByHeading.values())
        ]

        fit = fitMagCalibration(rows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT)

        correctedRadii = []
        for magBody in magBodyByHeading.values():
            corrected = _applyCalibrationLikeAhrsFusion(magBody, fit.hardIronUt, fit.softIron)
            pC = float(np.dot(corrected, forward))
            qC = float(np.dot(corrected, left))
            correctedRadii.append(math.hypot(pC, qC))

        radii = np.array(correctedRadii)
        spreadPercent = (
            (float(np.max(radii)) - float(np.min(radii))) / float(np.mean(radii)) * 100.0
        )
        assert spreadPercent < 1.0, f"corrected locus is not a circle: spread {spreadPercent}%"


def _pitchRotationMatrix(tiltDeg: float) -> np.ndarray:
    """R(theta): LEVEL-frame (forward, left, up) coords -> BODY (x, y, z)
    coords, nose-up pitch of ``tiltDeg`` about the left axis. Matches
    ``_tiltedBasis`` (``bodyVec = p*forward + q*left + r*up``), as a matrix.
    """
    theta = math.radians(tiltDeg)
    return np.array(
        [
            [math.cos(theta), 0.0, math.sin(theta)],
            [0.0, 1.0, 0.0],
            [-math.sin(theta), 0.0, math.cos(theta)],
        ]
    )


def _headingFromAccelAndMag(accelBody: np.ndarray, magBody: np.ndarray) -> float:
    """Tilt-compensated heading, degrees 0..360, from the CURRENT accel.

    Ruling 24's formula: west = ghat x m; north = west x ghat;
    heading = atan2(-west.xhat, north.xhat). Verified by hand: level, facing
    north (m purely along body +x) gives heading 0; facing east (m purely
    along body +y) gives heading 90 -- both match the standard 0=north,
    90=east, clockwise convention.
    """
    ghat = accelBody / np.linalg.norm(accelBody)
    west = np.cross(ghat, magBody)
    north = np.cross(west, ghat)
    xhat = np.array([1.0, 0.0, 0.0])
    return math.degrees(math.atan2(-np.dot(west, xhat), np.dot(north, xhat))) % 360.0


# Ruling 24's own synthetic parameters -- deliberately NOT
# DEFAULT_EARTH_VERTICAL_UT, so a test that accidentally used the module
# default instead of the value actually passed in would be caught.
_R24_H_UT = 18.0
_R24_V_TRUE_UT = -52.0
_R24_IRON: Vector3 = (12.0, -7.0, 3.0)


def _fieldAndAccelAtTilt(
    tiltDeg: float, psiDeg: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(accelBody, ironedMagBody, pureFieldBody) at a given tilt and heading psi.

    Ruling 24's exact construction: the PURE field (H cos psi, -H sin psi,
    V_true), expressed in the level frame, is rotated into body coordinates
    by R(tiltDeg); hard iron is added AFTER that rotation, directly in BODY
    coordinates, because it is a property of the sensor/chassis and does NOT
    rotate with vehicle pitch (unlike the ambient field).
    """
    rot = _pitchRotationMatrix(tiltDeg)
    levelField = np.array(
        [
            _R24_H_UT * math.cos(math.radians(psiDeg)),
            -_R24_H_UT * math.sin(math.radians(psiDeg)),
            _R24_V_TRUE_UT,
        ]
    )
    pureFieldBody = rot @ levelField
    ironedFieldBody = pureFieldBody + np.array(_R24_IRON)
    accelBody = rot @ np.array([0.0, 0.0, _STANDARD_GRAVITY_MS2])
    return accelBody, ironedFieldBody, pureFieldBody


class TestHeadingRegressionAtDifferentEvaluationTilt:
    """Ruling 24: the calibration is fit from a capture at ONE gravity/tilt
    and then applied to readings at a DIFFERENT one -- exactly the real-world
    case (a car is calibrated once; its pitch varies afterward with mount
    tilt, hills, braking dive) and exactly what fix round 1's disproven
    ``test_hardIronZDoesNotLeakIntoHeadingByConstruction`` did NOT do (it
    fit and evaluated at the SAME tilt, comparing an attitude against
    itself). H=18, V_true=-52 (deliberately not the module default), iron
    (12, -7, 3), a pure circle (no soft-iron shape distortion, matching the
    reviewer's own repro through the production ``AhrsFusion``).
    """

    @pytest.mark.parametrize("captureTiltDeg", [0.0, 2.5])
    def test_fixedCalibrationHoldsWithinHalfADegreeAcrossPitch(
        self, captureTiltDeg: float
    ) -> None:
        # The CAPTURE is denser than the evaluation sweep purely so the fit
        # clears MIN_SAMPLES_PER_BIN (Ruling 23, >=3 moving samples/bin) --
        # the coordinator's "psi in 0..350" is the EVALUATION sweep below.
        capturePsiValues = list(range(0, 360, 2))
        evalPsiValues = list(range(0, 360, 10))  # psi in 0..350

        captureRows = []
        for i, psi in enumerate(capturePsiValues):
            accelBody, ironedField, _ = _fieldAndAccelAtTilt(captureTiltDeg, psi)
            captureRows.append((float(i), tuple(accelBody), tuple(ironedField), None))
        fit = fitMagCalibration(captureRows, earthVerticalUt=_R24_V_TRUE_UT)

        for deltaDeg in (3.0, 6.0):
            evalTiltDeg = captureTiltDeg + deltaDeg
            worstDiff = 0.0
            for psi in evalPsiValues:
                accelBody, ironedField, pureField = _fieldAndAccelAtTilt(evalTiltDeg, psi)
                corrected = _applyCalibrationLikeAhrsFusion(
                    tuple(ironedField), fit.hardIronUt, fit.softIron
                )
                headingCalibrated = _headingFromAccelAndMag(accelBody, corrected)
                headingTrue = _headingFromAccelAndMag(accelBody, pureField)
                diff = abs((headingCalibrated - headingTrue + 180.0) % 360.0 - 180.0)
                worstDiff = max(worstDiff, diff)
            assert worstDiff < 0.5, (
                f"worst heading error {worstDiff} deg: capture {captureTiltDeg} deg, "
                f"eval {evalTiltDeg} deg"
            )

    def test_skippingEarthSubtractionDegradesHeadingAtDifferentEvaluationTilt(self) -> None:
        """Discrimination arm: earthVerticalUt=0.0 (fit round 1's exact bug,
        capture level per the reviewer's own repro) must show clearly worse
        heading error than the fixed default at the SAME +3 degree eval tilt.
        """
        capturePsiValues = list(range(0, 360, 2))
        evalPsiValues = list(range(0, 360, 10))
        captureTiltDeg = 0.0

        captureRows = []
        for i, psi in enumerate(capturePsiValues):
            accelBody, ironedField, _ = _fieldAndAccelAtTilt(captureTiltDeg, psi)
            captureRows.append((float(i), tuple(accelBody), tuple(ironedField), None))
        buggyFit = fitMagCalibration(captureRows, earthVerticalUt=0.0)

        evalTiltDeg = captureTiltDeg + 3.0
        worstDiff = 0.0
        for psi in evalPsiValues:
            accelBody, ironedField, pureField = _fieldAndAccelAtTilt(evalTiltDeg, psi)
            corrected = _applyCalibrationLikeAhrsFusion(
                tuple(ironedField), buggyFit.hardIronUt, buggyFit.softIron
            )
            headingCalibrated = _headingFromAccelAndMag(accelBody, corrected)
            headingTrue = _headingFromAccelAndMag(accelBody, pureField)
            diff = abs((headingCalibrated - headingTrue + 180.0) % 360.0 - 180.0)
            worstDiff = max(worstDiff, diff)

        # Reviewer MEASURED 8.6 deg at +3 deg (production AhrsFusion).
        assert worstDiff > 5.0, f"expected the old bug to degrade heading, got only {worstDiff} deg"


class TestMainCli:
    def test_loadColumnErrorsComeOutAsRefusedJsonNotATraceback(self, tmp_path, capsys) -> None:
        """Ruling 24: loadRows raising (C1's wrong-column case) must be a
        refusal like any other -- caught inside main's try -- not an
        uncaught traceback out of the CLI process.
        """
        csvPath = tmp_path / "capture.csv"
        with open(csvPath, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ts_capture", "accel_x", "accel_y", "accel_z"])  # no mag columns
            writer.writerow([1.0, 0.0, 0.0, 9.8])

        exitCode = main([str(csvPath)])
        assert exitCode == 1
        output = json.loads(capsys.readouterr().out)
        assert "refused" in output
        assert "mag" in output["refused"]
        assert output["samples"] == 0

    def test_printsMagCalibrationAndFitQuality(self, tmp_path, capsys) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            noiseUt=0.1,
        )
        rows = [
            (float(i), 42, _deviceFrameFromBody(_LEVEL_ACCEL), _deviceFrameFromBody(mag))
            for i, mag in enumerate(points)
        ]
        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), rows)

        exitCode = main(
            [str(csvPath), "--drive-id", "42", "--earth-vertical-ut", str(_TRUE_EARTH_VERTICAL_UT)]
        )
        assert exitCode == 0

        output = json.loads(capsys.readouterr().out)
        assert "magCalibration" in output
        assert "fitQuality" in output
        hardIron = output["magCalibration"]["hardIronUt"]
        assert hardIron[0] == pytest.approx(_TRUE_CENTER_P, abs=0.5)
        assert hardIron[1] == pytest.approx(_TRUE_CENTER_Q, abs=0.5)
        assert hardIron[2] == pytest.approx(_TRUE_IRON_Z_UT, abs=0.5)
        assert output["fitQuality"]["headingBinsOccupied"] == 36
        assert output["fitQuality"]["radiusSpreadPercent"] < 3.0
        assert output["fitQuality"]["qualityForced"] is False
        assert "majorAxisRotationDeg" in output["fitQuality"]
        # Ruling 26: reported for every fit; this ellipse's radius
        # (sqrt(20*16)=17.9) sits well inside 0.8-1.2x DEFAULT_EARTH_
        # HORIZONTAL_UT (19.4), so no warning is expected here.
        assert "horizontalGain" in output["fitQuality"]
        assert output["fitQuality"]["horizontalGainWarning"] is None

    def test_horizontalGainWarningPrintsAStderrLineNotARefusal(self, tmp_path, capsys) -> None:
        """Ruling 26: an attenuated horizontal field WARNS (exit 0, stdout
        JSON unchanged in shape) rather than refusing.
        """
        scale = 0.3
        radius = DEFAULT_EARTH_HORIZONTAL_UT * scale
        points = _ellipsePoints(
            centerP=0.0,
            centerQ=0.0,
            r1=radius,
            r2=radius,
            rotationDeg=0.0,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        rows = [
            (float(i), None, _deviceFrameFromBody(_LEVEL_ACCEL), _deviceFrameFromBody(mag))
            for i, mag in enumerate(points)
        ]
        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), rows)

        exitCode = main([str(csvPath), "--earth-vertical-ut", str(_TRUE_EARTH_VERTICAL_UT)])
        assert exitCode == 0

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["fitQuality"]["horizontalGain"] == pytest.approx(scale, abs=0.02)
        assert output["fitQuality"]["horizontalGainWarning"] is not None
        assert "WARNING:" in captured.err
        assert "heading" in captured.err

    def test_reportsRefusalInsteadOfCrashing(self, tmp_path, capsys) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=100,
            spanDeg=90.0,
        )
        rows = [
            (float(i), None, _deviceFrameFromBody(_LEVEL_ACCEL), _deviceFrameFromBody(mag))
            for i, mag in enumerate(points)
        ]
        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), rows)

        exitCode = main([str(csvPath)])
        assert exitCode == 1
        output = json.loads(capsys.readouterr().out)
        assert "refused" in output
        assert "coverage" in output["refused"]

    def test_forceFlagAcceptsAnOverQualityFloorFit(self, tmp_path, capsys) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=360,
            noiseUt=3.0,
        )
        rows = [
            (float(i), None, _deviceFrameFromBody(_LEVEL_ACCEL), _deviceFrameFromBody(mag))
            for i, mag in enumerate(points)
        ]
        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), rows)

        refused = main([str(csvPath), "--earth-vertical-ut", str(_TRUE_EARTH_VERTICAL_UT)])
        assert refused == 1
        capsys.readouterr()

        forced = main(
            [str(csvPath), "--earth-vertical-ut", str(_TRUE_EARTH_VERTICAL_UT), "--force"]
        )
        assert forced == 0
        output = json.loads(capsys.readouterr().out)
        assert output["fitQuality"]["qualityForced"] is True
