################################################################################
# File Name: test_imu_config_arch064.py
# Purpose/Description: ARCH-064 Task 5 -- config.json / validator agreement for
#     acquisition C (magMode "direct") + the x-io Fusion AHRS. Pins: the
#     validator accepts the new pi.sensors.imu keys (fusionEngine,
#     magDeclinationDeg, magCalibration) and their defaults; it REJECTS a
#     magMode outside {direct, bypass, master} and a fusionEngine outside
#     {imufusion, legacy}; the shipped config.json imu block validates as-is;
#     and the sampleHz 50 / persistHz 2 split decimates by an EXACT factor of
#     25 (edr_persistence_subscriber._decimationFactor(50, 2) == 25) -- the
#     storage-side consequence of the CIO 2026-09-28 ruling that sampleHz is
#     now the IMU's internal fusion read rate while persistHz/stateHz stay
#     under the 4 Hz ceiling.
# Author: Atlas (architect)
# Creation Date: 2026-09-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-28    | Atlas        | Initial -- ARCH-064 Task 5.
# ================================================================================
################################################################################
"""ARCH-064 Task 5: config.json / validator agreement for acquisition C + AHRS."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common.config.validator import ConfigValidationError, ConfigValidator
from src.pi.bus.edr_persistence_subscriber import _decimationFactor

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _shippedImu() -> dict:
    with open(_REPO_ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)["pi"]["sensors"]["imu"]


def _baseCfg(imu: dict | None = None) -> dict:
    return {
        "protocolVersion": "1",
        "schemaVersion": "1",
        "deviceId": "d",
        "pi": {} if imu is None else {"sensors": {"imu": imu}},
        "server": {},
    }


# ---------------------------------------------------------------------------
# Defaults: the validator accepts and fills the new keys
# ---------------------------------------------------------------------------


def test_validatorDefaults_fusionEngine_isImufusion():
    """
    Given: a config with no pi.sensors.imu.fusionEngine
    When: the validator applies defaults
    Then: it defaults to 'imufusion' (the x-io Fusion AHRS, ARCH-064)
    """
    result = ConfigValidator().validate(_baseCfg({}))
    assert result["pi"]["sensors"]["imu"]["fusionEngine"] == "imufusion"


def test_validatorDefaults_magMode_isDirect():
    """
    Given: a config with no pi.sensors.imu.magMode
    When: the validator applies defaults
    Then: it defaults to 'direct' (acquisition C, ARCH-064 -- supersedes the
          ARCH-057 'master' default)
    """
    result = ConfigValidator().validate(_baseCfg({}))
    assert result["pi"]["sensors"]["imu"]["magMode"] == "direct"


def test_validatorDefaults_magDeclinationDeg_isZero():
    """
    Given: a config with no pi.sensors.imu.magDeclinationDeg
    When: the validator applies defaults
    Then: it defaults to 0.0 -- an inert module default; the real value ships
          in config.json, not here
    """
    result = ConfigValidator().validate(_baseCfg({}))
    assert result["pi"]["sensors"]["imu"]["magDeclinationDeg"] == 0.0


def test_validatorDefaults_magCalibration_isZeroHardIronIdentitySoftIron():
    """
    Given: a config with no pi.sensors.imu.magCalibration
    When: the validator applies defaults
    Then: it defaults to zero hard-iron / identity soft-iron -- a NO-OP so an
          unset car's heading accuracy is unchanged, not silently miscorrected
    """
    result = ConfigValidator().validate(_baseCfg({}))
    cal = result["pi"]["sensors"]["imu"]["magCalibration"]
    assert cal["hardIronUt"] == [0.0, 0.0, 0.0]
    assert cal["softIron"] == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


# ---------------------------------------------------------------------------
# Rejection: an out-of-set magMode / fusionEngine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("badMode", ["adafruit", "auto", "", "MASTER", "Direct"])
def test_validator_rejectsMagModeOutsideTheThree(badMode):
    """
    Given: pi.sensors.imu.magMode set to anything other than
           direct / bypass / master
    When: the validator runs
    Then: it raises ConfigValidationError naming the bad value and the
          allowed set -- a typo must not silently ship a wrong acquisition path
    """
    with pytest.raises(ConfigValidationError) as excinfo:
        ConfigValidator().validate(_baseCfg({"magMode": badMode}))
    message = str(excinfo.value)
    assert "magMode" in message
    assert badMode in message


@pytest.mark.parametrize("goodMode", ["direct", "bypass", "master"])
def test_validator_acceptsEachOfTheThreeMagModes(goodMode):
    """
    Given: pi.sensors.imu.magMode set to direct, bypass or master
    When: the validator runs
    Then: it validates without error and preserves the value -- all three are
          live, supported revert paths, not just the default
    """
    result = ConfigValidator().validate(_baseCfg({"magMode": goodMode}))
    assert result["pi"]["sensors"]["imu"]["magMode"] == goodMode


@pytest.mark.parametrize("badEngine", ["madgwick", "mahony", "", "Legacy", "IMUFUSION"])
def test_validator_rejectsFusionEngineOutsideTheTwo(badEngine):
    """
    Given: pi.sensors.imu.fusionEngine set to anything other than
           imufusion / legacy
    When: the validator runs
    Then: it raises ConfigValidationError naming the bad value and the
          allowed set
    """
    with pytest.raises(ConfigValidationError) as excinfo:
        ConfigValidator().validate(_baseCfg({"fusionEngine": badEngine}))
    message = str(excinfo.value)
    assert "fusionEngine" in message
    assert badEngine in message


@pytest.mark.parametrize("goodEngine", ["imufusion", "legacy"])
def test_validator_acceptsEachOfTheTwoFusionEngines(goodEngine):
    """
    Given: pi.sensors.imu.fusionEngine set to imufusion or legacy
    When: the validator runs
    Then: it validates without error and preserves the value
    """
    result = ConfigValidator().validate(_baseCfg({"fusionEngine": goodEngine}))
    assert result["pi"]["sensors"]["imu"]["fusionEngine"] == goodEngine


# ---------------------------------------------------------------------------
# The shipped config.json imu block
# ---------------------------------------------------------------------------


def test_configJson_imuBlock_validates():
    """
    Given: the shipped config.json pi.sensors.imu block
    When: run through the full validator
    Then: it validates without error -- sampleHz 50, magMode 'direct',
          fusionEngine 'imufusion', magDeclinationDeg and magCalibration all
          agree with the validator's allowed sets
    """
    result = ConfigValidator().validate(_baseCfg(dict(_shippedImu())))
    got = result["pi"]["sensors"]["imu"]
    assert got["sampleHz"] == 50
    assert got["magMode"] == "direct"
    assert got["fusionEngine"] == "imufusion"
    assert got["persistHz"] == 2
    assert got["stateHz"] == 1


def test_configJson_magDeclinationDeg_isDocumentedNoaaValue():
    """
    Given: the shipped config.json
    When: pi.sensors.imu.magDeclinationDeg is read
    Then: it is the DOCUMENTED NOAA/WMM value for the Chicago area (41.79 N,
          87.88 W), 2026-09 -- east-positive, so negative here (west) -- not
          the inert 0.0 module default
    """
    imu = _shippedImu()
    assert imu["magDeclinationDeg"] == pytest.approx(-4.0)


# ---------------------------------------------------------------------------
# Storage-side decimation: sampleHz 50 / persistHz 2 -> EXACT factor 25
# ---------------------------------------------------------------------------


def test_decimationFactor_fiftyToTwo_isExactlyTwentyFive():
    """
    Given: sampleHz 50 (the IMU's internal fusion read rate, ARCH-064) and
           persistHz 2 (the STORED rate, unchanged under the 4 Hz ceiling)
    When: edr_persistence_subscriber derives the keep-1-of-N decimation factor
    Then: it is exactly 25 -- an integer factor, no config field that lies
          about its effective persisted rate
    """
    assert _decimationFactor(50, 2) == 25
    assert 50 / _decimationFactor(50, 2) == 2


def test_configJson_imuTriple_decimatesExactly():
    """
    Given: the shipped config.json sampleHz / persistHz
    When: the decimation factor is derived
    Then: it is exactly 25, and the effective persisted rate equals persistHz
    """
    imu = _shippedImu()
    factor = _decimationFactor(imu["sampleHz"], imu["persistHz"])
    assert factor == 25
    assert imu["sampleHz"] / factor == imu["persistHz"]


# ---------------------------------------------------------------------------
# ARCH-064 Task 6b: pi.sensors.imu.accelCalibration {offsetMs2, matrix}
# ---------------------------------------------------------------------------

_IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def test_validatorDefaults_accelCalibration_isZeroOffsetIdentityMatrix():
    """
    Given: no pi.sensors.imu.accelCalibration
    When: the validator applies defaults
    Then: zero offset / identity matrix -- a NO-OP, the accel passes unchanged
    """
    result = ConfigValidator().validate(_baseCfg({}))
    cal = result["pi"]["sensors"]["imu"]["accelCalibration"]
    assert cal["offsetMs2"] == [0.0, 0.0, 0.0]
    assert cal["matrix"] == _IDENTITY


def test_validatorDefaults_accelCalibration_partialBlockIsCompleted():
    """
    Given: an accelCalibration carrying only offsetMs2
    When: defaults apply
    Then: the missing matrix is the identity (per-leaf defaults), not absent
    """
    result = ConfigValidator().validate(_baseCfg({"accelCalibration": {"offsetMs2": [0.1, 0.2, 0.3]}}))
    cal = result["pi"]["sensors"]["imu"]["accelCalibration"]
    assert cal["offsetMs2"] == [0.1, 0.2, 0.3]
    assert cal["matrix"] == _IDENTITY


def test_validator_acceptsAFittedAccelCalibration():
    cal = {"offsetMs2": [0.2, -0.1, 0.18], "matrix": [[0.98, 0.01, 0.0], [0.01, 1.01, 0.0], [0.0, 0.0, 0.982]]}
    result = ConfigValidator().validate(_baseCfg({"accelCalibration": cal}))
    assert result["pi"]["sensors"]["imu"]["accelCalibration"] == cal


@pytest.mark.parametrize(
    "cal, fragment",
    [
        ({"offsetMs2": [0.1, 0.2]}, "offsetMs2"),
        ({"offsetMs2": [0.1, 0.2, 0.3, 0.4]}, "offsetMs2"),
        ({"offsetMs2": "0,0,0"}, "offsetMs2"),
        ({"offsetMs2": [0.1, True, 0.3]}, "offsetMs2"),
        ({"offsetMs2": [0.1, float("nan"), 0.3]}, "offsetMs2"),
        ({"offsetMs2": [0.1, None, 0.3]}, "offsetMs2"),
        ({"matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]}, "matrix"),
        ({"matrix": [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]}, "matrix"),
        ({"matrix": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]}, "matrix"),
        ({"matrix": [[1.0, 0.0, 0.0], [0.0, float("inf"), 0.0], [0.0, 0.0, 1.0]]}, "matrix"),
        ({"matrix": [[1.0, 0.0, 0.0], [0.0, "1", 0.0], [0.0, 0.0, 1.0]]}, "matrix"),
        ("not-a-block", "accelCalibration"),
    ],
)
def test_validator_rejectsMalformedAccelCalibration(cal, fragment):
    """
    Given: an accelCalibration whose offset is not a finite 3-vector or whose
           matrix is not a finite 3x3
    When: the validator runs
    Then: ConfigValidationError naming the field -- AhrsFusion would otherwise
          refuse it at runtime and silently fall back to the legacy engine
    """
    with pytest.raises(ConfigValidationError) as excinfo:
        ConfigValidator().validate(_baseCfg({"accelCalibration": cal}))
    assert fragment in str(excinfo.value)


@pytest.mark.parametrize(
    "matrix",
    [
        [[-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],  # a reflection: det -1
        [[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],  # an axis swap: det -1
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 0.0]],  # singular: det 0
    ],
)
def test_validator_rejectsANonPositiveDeterminant(matrix):
    """
    Given: a matrix with det <= 0 (a mirror, an axis swap, or a collapse)
    When: the validator runs
    Then: rejected -- a calibration is a small correction near the identity;
          det <= 0 flips handedness (gravity reads upside-down on one axis)
    """
    with pytest.raises(ConfigValidationError) as excinfo:
        ConfigValidator().validate(_baseCfg({"accelCalibration": {"matrix": matrix}}))
    assert "determinant" in str(excinfo.value)


def test_configJson_accelCalibration_shipsAsTheNoOp():
    """
    Given: the shipped config.json
    When: pi.sensors.imu.accelCalibration is read
    Then: it is present, beside magCalibration, as zero/identity -- real
          values are Task 8's, not this task's
    """
    imu = _shippedImu()
    assert imu["accelCalibration"] == {"offsetMs2": [0.0, 0.0, 0.0], "matrix": _IDENTITY}


# ---------------------------------------------------------------------------
# ARCH-064 Task 6b fix round 1 (Ruling 32): magCalibration shape validation,
# mirroring accelCalibration.
# ---------------------------------------------------------------------------


def test_validator_acceptsAFittedMagCalibration():
    cal = {"hardIronUt": [21.1, -11.4, 22.6], "softIron": [[0.87, -0.09, 0.0], [-0.09, 1.16, 0.0], [0.0, 0.0, 1.0]]}
    result = ConfigValidator().validate(_baseCfg({"magCalibration": cal}))
    assert result["pi"]["sensors"]["imu"]["magCalibration"] == cal


def test_validatorDefaults_magCalibration_partialBlockIsCompleted():
    result = ConfigValidator().validate(_baseCfg({"magCalibration": {"hardIronUt": [1.0, 2.0, 3.0]}}))
    cal = result["pi"]["sensors"]["imu"]["magCalibration"]
    assert cal["hardIronUt"] == [1.0, 2.0, 3.0]
    assert cal["softIron"] == _IDENTITY


@pytest.mark.parametrize(
    "cal, fragment",
    [
        ({"hardIronUt": [1.0, 2.0]}, "hardIronUt"),
        ({"hardIronUt": [1.0, 2.0, 3.0, 4.0]}, "hardIronUt"),
        ({"hardIronUt": [1.0, False, 3.0]}, "hardIronUt"),
        ({"hardIronUt": [1.0, float("inf"), 3.0]}, "hardIronUt"),
        ({"hardIronUt": "1,2,3"}, "hardIronUt"),
        ({"softIron": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]}, "softIron"),
        ({"softIron": [[1.0, 0.0, 0.0], [0.0, float("nan"), 0.0], [0.0, 0.0, 1.0]]}, "softIron"),
        ({"softIron": [[1.0, 0.0, 0.0], [0.0, None, 0.0], [0.0, 0.0, 1.0]]}, "softIron"),
        ([1.0, 2.0, 3.0], "magCalibration"),
    ],
)
def test_validator_rejectsMalformedMagCalibration(cal, fragment):
    with pytest.raises(ConfigValidationError) as excinfo:
        ConfigValidator().validate(_baseCfg({"magCalibration": cal}))
    assert fragment in str(excinfo.value)


@pytest.mark.parametrize(
    "matrix",
    [
        [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]],
        [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 0.0]],
    ],
)
def test_validator_rejectsASoftIronWithANonPositiveDeterminant(matrix):
    with pytest.raises(ConfigValidationError) as excinfo:
        ConfigValidator().validate(_baseCfg({"magCalibration": {"softIron": matrix}}))
    assert "determinant" in str(excinfo.value) and "softIron" in str(excinfo.value)


# ---------------------------------------------------------------------------
# ARCH-064 Ruling 35 (M1): magDeclinationDeg must be a finite angle
#
# It was only DEFAULTED. A NaN reached AhrsFusion and every heading became NaN;
# a string raised inside the engine build and fell back to legacy; 200 deg is a
# typo that no declination on Earth produces.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["-4.1", float("nan"), float("inf"), 200.0, -180.5, True],
)
def test_validator_rejectsANonFiniteOrOutOfRangeDeclination(bad):
    with pytest.raises(ConfigValidationError, match="magDeclinationDeg"):
        ConfigValidator().validate(_baseCfg({"magDeclinationDeg": bad}))


@pytest.mark.parametrize("good", [0, -4.1, 180, -180.0, 12.25])
def test_validator_acceptsAFiniteDeclinationWithinPlusMinus180(good):
    result = ConfigValidator().validate(_baseCfg({"magDeclinationDeg": good}))
    assert result["pi"]["sensors"]["imu"]["magDeclinationDeg"] == good


def test_validator_explicitNullDeclination_isDefaultedNotPassedThrough():
    """An explicit null is treated as absent by the defaults pass -> 0.0."""
    result = ConfigValidator().validate(_baseCfg({"magDeclinationDeg": None}))
    assert result["pi"]["sensors"]["imu"]["magDeclinationDeg"] == 0.0
