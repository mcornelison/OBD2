################################################################################
# File Name: test_mag_max_age_sec_config_key.py
# Purpose/Description: US-803-b -- the magnetometer staleness window is carried
#     in SECONDS (pi.sensors.imu.magMaxAgeSec), not in polls. The shipped value
#     is 1.25 s, exactly the window the car ran as MAG_MAX_AGE_POLLS 5 at
#     sampleHz 4: the UNIT changes, the VALUE does not. An override moves the
#     gate the bridge actually applies, the window no longer moves when an
#     unrelated key (sampleHz) does, the poll count in force is logged at
#     construction, and the validator rejects a wrong-typed value.
# Author: Rex (US-803-b)
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-25    | Rex (US-803-b) | Initial -- shipped value, override, log, validator.
# ================================================================================
################################################################################
"""US-803-b: pi.sensors.imu.magMaxAgeSec, the mag/gyro pairing window in seconds."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from pi.bus.bus import SampleBus
from pi.bus.sample import Sample
from pi.sensors.imu_state_bridge import (
    DEFAULT_MAG_MAX_AGE_S,
    ImuStateBridge,
    createImuStateBridgeFromConfig,
)
from src.common.config.validator import ConfigValidationError, ConfigValidator

_REPO_ROOT = Path(__file__).resolve().parents[3]

_KEY = "magMaxAgeSec"

# The window the car ran before this story: MAG_MAX_AGE_POLLS (5) / sampleHz (4).
_LEGACY_POLLS = 5
_SHIPPED_SAMPLE_HZ = 4
_LEGACY_WINDOW_S = _LEGACY_POLLS / _SHIPPED_SAMPLE_HZ

# A non-default window, and a mag age that only it admits: 2.0 s is past the
# shipped 1.25 s edge and inside 2.5 s.
_OVERRIDE_S = 2.5
_AGE_ONLY_OVERRIDE_ADMITS_S = 2.0


def _shippedConfig() -> dict[str, Any]:
    with open(_REPO_ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)


def _busConfig(imu: dict[str, Any]) -> dict[str, Any]:
    """A config with the bus on and ONLY the IMU enabled."""
    return {
        "pi": {
            "bus": {"enabled": True},
            "sensors": {"imu": dict(imu, enabled=True), "light": {"enabled": False}},
        }
    }


def _shippedImu() -> dict[str, Any]:
    return dict(_shippedConfig()["pi"]["sensors"]["imu"])


def _mag(capture: float) -> Sample:
    return Sample(
        topic="raw.imu.mag",
        source="imu",
        value=(20.0, 0.0, -40.0),
        unit="uT",
        tsUtc="2026-09-25T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=1,
    )


def _pairsAt(bridge: ImuStateBridge, ageS: float) -> bool:
    """True when a mag captured at t=0 still pairs with a burst ``ageS`` later."""
    bridge.handleSample(_mag(0.0))
    return bridge._freshMag(ageS) is not None


# ---------------------------------------------------------------------------
# The value did not move
# ---------------------------------------------------------------------------


def test_shippedConfig_magMaxAgeSecIsTheWindowTheCarRanToday():
    """
    Given: the shipped config.json
    When: pi.sensors.imu.magMaxAgeSec is read
    Then: it is 1.25 s -- 5 polls at the shipped sampleHz 4, reproduced from the
          config's own rate rather than restated
    """
    imu = _shippedImu()

    assert imu["sampleHz"] == _SHIPPED_SAMPLE_HZ
    assert imu[_KEY] == _LEGACY_WINDOW_S == 1.25


def test_moduleDefault_equalsTheShippedValue():
    """
    Given: the bridge module's fallback window
    When: compared to the config value
    Then: they agree, so an absent key keeps the car's window
    """
    assert DEFAULT_MAG_MAX_AGE_S == _LEGACY_WINDOW_S


def test_bridgeFromShippedConfig_windowIsOnePointTwoFiveSeconds():
    """
    Given: the shipped IMU section through the production factory
    When: the pairing window is applied
    Then: a mag 1.25 s old pairs and one 1.5 s old does not
    """
    bridge = createImuStateBridgeFromConfig(_busConfig(_shippedImu()), SampleBus())
    assert bridge is not None
    assert _pairsAt(bridge, _LEGACY_WINDOW_S) is True

    bridge = createImuStateBridgeFromConfig(_busConfig(_shippedImu()), SampleBus())
    assert bridge is not None
    assert _pairsAt(bridge, _LEGACY_WINDOW_S + 1.0 / _SHIPPED_SAMPLE_HZ) is False


# ---------------------------------------------------------------------------
# An override changes behaviour
# ---------------------------------------------------------------------------


def test_bridgeFromConfig_nonDefaultMagMaxAgeSec_widensTheGate():
    """
    Given: magMaxAgeSec overridden to 2.5 s
    When: a mag 2.0 s old meets an accel burst
    Then: it pairs -- and with the shipped value the same mag does not
    """
    shipped = createImuStateBridgeFromConfig(_busConfig(_shippedImu()), SampleBus())
    overridden = createImuStateBridgeFromConfig(
        _busConfig(dict(_shippedImu(), **{_KEY: _OVERRIDE_S})), SampleBus()
    )

    assert shipped is not None and overridden is not None
    assert _pairsAt(shipped, _AGE_ONLY_OVERRIDE_ADMITS_S) is False
    assert _pairsAt(overridden, _AGE_ONLY_OVERRIDE_ADMITS_S) is True


def test_bridgeFromConfig_nonDefaultMagMaxAgeSec_alsoGovernsTheGyroPairing():
    """
    Given: magMaxAgeSec overridden to 2.5 s
    When: a gyro reading 2.0 s old meets an accel burst
    Then: it pairs -- mag and gyro share ONE pairing window, as before
    """
    bridge = createImuStateBridgeFromConfig(
        _busConfig(dict(_shippedImu(), **{_KEY: _OVERRIDE_S})), SampleBus()
    )
    assert bridge is not None
    gyro = _mag(0.0)
    bridge.handleSample(
        Sample(
            topic="raw.imu.gyro",
            source="imu",
            value=(0.0, 0.0, 0.0),
            unit="rad/s",
            tsUtc=gyro.tsUtc,
            tsCapture=0.0,
            driveId=None,
            dataSource="real",
            seq=1,
        )
    )

    assert bridge._freshGyro(_AGE_ONLY_OVERRIDE_ADMITS_S) is not None
    assert bridge._freshGyro(_OVERRIDE_S + 0.25) is None


def test_bridgeFromConfig_keyAbsent_behavesAsOnePointTwoFiveSeconds():
    """
    Given: an IMU section with NO magMaxAgeSec key
    When: the bridge is built through the production factory
    Then: the window is 1.25 s -- 1.25 s pairs, 1.5 s does not
    """
    imu = _shippedImu()
    imu.pop(_KEY, None)

    inside = createImuStateBridgeFromConfig(_busConfig(imu), SampleBus())
    outside = createImuStateBridgeFromConfig(_busConfig(imu), SampleBus())

    assert inside is not None and outside is not None
    assert _pairsAt(inside, 1.25) is True
    assert _pairsAt(outside, 1.5) is False


def test_bridgeFromConfig_sampleHzChange_doesNotMoveTheWindow():
    """
    Given: magMaxAgeSec at the shipped 1.25 s and sampleHz halved to 2
    When: the pairing window is applied
    Then: it is still 1.25 s -- under the poll count it would have silently
          doubled to 2.5 s, which is the defect this story removes
    """
    bridge = createImuStateBridgeFromConfig(
        _busConfig(dict(_shippedImu(), sampleHz=2)), SampleBus()
    )
    assert bridge is not None
    assert _pairsAt(bridge, _AGE_ONLY_OVERRIDE_ADMITS_S) is False


@pytest.mark.parametrize("bad", [0, -1.0, None])
def test_bridge_nonPositiveWindow_fallsBackToTheShippedDefault(bad: Any):
    """
    Given: a constructor handed a zero, negative or missing window
    When: the bridge is built
    Then: it runs on the shipped 1.25 s rather than a window that never pairs
    """
    bridge = ImuStateBridge(None, "unused", magMaxAgeSec=bad)

    assert bridge._magMaxAgeS == DEFAULT_MAG_MAX_AGE_S


# ---------------------------------------------------------------------------
# The poll count IN FORCE is logged
# ---------------------------------------------------------------------------


def _windowLog(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if "magMaxAgeSec" in r.getMessage()]


def test_bridgeConstruction_logsThePollCountInForce(caplog: pytest.LogCaptureFixture):
    """
    Given: magMaxAgeSec 2.5 at sampleHz 4
    When: the bridge is constructed
    Then: one INFO line records 2.5 s, 4 Hz and the 10 polls that implies
    """
    with caplog.at_level(logging.INFO, logger="pi.sensors.imu_state_bridge"):
        ImuStateBridge(None, "unused", sampleHz=4, magMaxAgeSec=_OVERRIDE_S)

    lines = _windowLog(caplog)
    assert len(lines) == 1
    assert "2.5" in lines[0] and "sampleHz=4" in lines[0] and "10.00 polls" in lines[0]


def test_bridgeConstruction_logsTheRateActuallyUsed_notTheOneDeclared(
    caplog: pytest.LogCaptureFixture,
):
    """
    Given: a constructor handed an unusable sampleHz (0), which falls back
    When: the bridge is constructed with the shipped 1.25 s window
    Then: the log names the FALLBACK rate and its poll count (4 Hz, 5 polls),
          not the 0 the caller passed
    """
    with caplog.at_level(logging.INFO, logger="pi.sensors.imu_state_bridge"):
        ImuStateBridge(None, "unused", sampleHz=0, magMaxAgeSec=1.25)

    lines = _windowLog(caplog)
    assert len(lines) == 1
    assert "sampleHz=4" in lines[0] and "5.00 polls" in lines[0]


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def _validated(value: Any) -> dict[str, Any]:
    raw = _shippedConfig()
    raw["pi"]["sensors"]["imu"][_KEY] = value
    return ConfigValidator().validate(raw)


def test_validate_shippedConfig_acceptsTheKey():
    """
    Given: the shipped config.json
    When: it is validated
    Then: it passes and carries 1.25 through unchanged
    """
    config = ConfigValidator().validate(_shippedConfig())

    assert config["pi"]["sensors"]["imu"][_KEY] == 1.25


def test_validate_nonDefaultValue_isKeptNotReplacedByTheDefault():
    """
    Given: magMaxAgeSec 2.5
    When: validated
    Then: 2.5 survives -- the default applies only when the key is absent
    """
    assert _validated(_OVERRIDE_S)["pi"]["sensors"]["imu"][_KEY] == _OVERRIDE_S


def test_validate_keyAbsent_defaultsToOnePointTwoFive():
    """
    Given: an IMU section without the key
    When: validated
    Then: the default 1.25 is applied
    """
    raw = _shippedConfig()
    raw["pi"]["sensors"]["imu"].pop(_KEY, None)

    config = ConfigValidator().validate(raw)

    assert config["pi"]["sensors"]["imu"][_KEY] == 1.25


@pytest.mark.parametrize("bad", ["1.25", True, [1.25], 0, -1.25])
def test_validate_wrongTypedOrNonPositive_isRejected(bad: Any):
    """
    Given: magMaxAgeSec as a string, bool, list, zero or negative
    When: validated
    Then: ConfigValidationError names the key -- never a silent fallback
    """
    with pytest.raises(ConfigValidationError) as info:
        _validated(bad)

    assert _KEY in str(info.value)
