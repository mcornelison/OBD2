################################################################################
# File Name: test_pitch_fusion_config_keys.py
# Purpose/Description: US-802-a -- the six pitch-fusion tunables that
#     createImuStateBridgeFromConfig already reads via imu.get(key, DEFAULT) now
#     ship in config.json at their module defaults. Each is proven LIVE: the
#     shipped config.json, overridden with a non-default value and run through
#     the validator and the real factory, yields a PitchFusion carrying that
#     value; with the key absent it carries the module default.
# Author: Rex (US-802-a)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-24    | Rex (US-802-a) | Initial -- override, absent and no-change pins.
# ================================================================================
################################################################################
"""Tests that the six pitch-fusion config keys reach the running PitchFusion."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from common.config.validator import ConfigValidator
from pi.bus.bus import SampleBus
from pi.sensors import pitch_fusion
from pi.sensors.imu_state_bridge import createImuStateBridgeFromConfig
from pi.sensors.pitch_fusion import PitchFusion

_REPO_ROOT = Path(__file__).resolve().parents[3]

# key -> (module default, a NON-default override, how to read it off PitchFusion).
# The defaults are read from pitch_fusion itself, never restated here, so a test
# can only pass when config.json agrees with the code.
_KEYS: dict[str, tuple[Any, Any, Callable[[PitchFusion], Any]]] = {
    "pitchTauSec": (
        pitch_fusion.DEFAULT_PITCH_TAU_S,
        9.0,
        lambda f: f._tauS,  # noqa: SLF001
    ),
    "accelTrustBand": (
        pitch_fusion.DEFAULT_ACCEL_TRUST_BAND,
        0.05,
        lambda f: f._trustBand,  # noqa: SLF001
    ),
    "zuptMinStopSec": (
        pitch_fusion.ZUPT_MIN_STOP_S,
        7.5,
        lambda f: f._minStopS,  # noqa: SLF001
    ),
    "zuptSpeedMaxAgeSec": (
        pitch_fusion.DEFAULT_ZUPT_SPEED_MAX_AGE_S,
        1.25,
        lambda f: f._speedMaxAgeS,  # noqa: SLF001
    ),
    "zuptMinStops": (
        pitch_fusion.DEFAULT_ZUPT_MIN_STOPS,
        9,
        lambda f: f._minStops,  # noqa: SLF001
    ),
    "zuptWindowStops": (
        pitch_fusion.DEFAULT_ZUPT_WINDOW_STOPS,
        40,
        lambda f: f._stopObs.maxlen,  # noqa: SLF001
    ),
}


def _shippedConfig() -> dict[str, Any]:
    return json.loads((_REPO_ROOT / "config.json").read_text(encoding="utf-8"))


def _buildFusion(raw: dict[str, Any], statesDir: Path) -> PitchFusion:
    """Validate ``raw`` and build the bridge the way the running Pi does."""
    config = ConfigValidator().validate(copy.deepcopy(raw))
    config["pi"]["bus"]["enabled"] = True
    config["pi"]["sensors"]["imu"]["enabled"] = True
    config["pi"].setdefault("splash", {})["statesDir"] = str(statesDir)
    bridge = createImuStateBridgeFromConfig(config, SampleBus())
    assert bridge is not None
    return bridge._pitchFusion  # noqa: SLF001 -- pinning the wiring


def test_configJson_carriesAllSixKeysAtTheModuleDefaults():
    """
    Given: the shipped config.json
    When: pi.sensors.imu is read
    Then: all six keys are present, each equal to the pitch_fusion default
    """
    imu = _shippedConfig()["pi"]["sensors"]["imu"]

    for key, (default, _override, _read) in _KEYS.items():
        assert key in imu, key
        assert imu[key] == default, key
        assert type(imu[key]) is type(default), key


@pytest.mark.parametrize("key", list(_KEYS))
def test_factory_nonDefaultInConfig_reachesPitchFusion(key: str, tmp_path: Path):
    """
    Given: the shipped config.json with one key set to a non-default value
    When: it is validated and the bridge is built by the real factory
    Then: the PitchFusion carries the override, not the module default
    """
    default, override, read = _KEYS[key]
    assert override != default
    raw = _shippedConfig()
    raw["pi"]["sensors"]["imu"][key] = override

    fusion = _buildFusion(raw, tmp_path)

    assert read(fusion) == override


@pytest.mark.parametrize("key", list(_KEYS))
def test_factory_keyAbsent_pitchFusionCarriesTheModuleDefault(key: str, tmp_path: Path):
    """
    Given: the shipped config.json with one key removed
    When: it is validated and the bridge is built
    Then: the PitchFusion carries the module default
    """
    default, _override, read = _KEYS[key]
    raw = _shippedConfig()
    del raw["pi"]["sensors"]["imu"][key]

    fusion = _buildFusion(raw, tmp_path)

    assert read(fusion) == default


def test_factory_shippedConfig_effectiveValuesMatchAnUnconfiguredPitchFusion(tmp_path: Path):
    """
    Given: the shipped config.json, unmodified
    When: the bridge is built from it
    Then: every one of the six resolves to what PitchFusion() carries with no
          arguments -- adding the keys changed no effective value
    """
    fusion = _buildFusion(_shippedConfig(), tmp_path)
    baseline = PitchFusion()

    for key, (_default, _override, read) in _KEYS.items():
        assert read(fusion) == read(baseline), key
