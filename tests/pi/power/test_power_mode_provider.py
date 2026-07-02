################################################################################
# File Name: test_power_mode_provider.py
# Purpose/Description: Unit tests for PowerModeProvider (US-421, BL-014) -- the
#                      Single Source of Truth for the "power mode" fact (in-car
#                      vs bench/wall deployment). Verifies the config-key
#                      acquisition path, the honest-instrument coercion
#                      (undeterminable/invalid/absent -> unknown, NEVER a
#                      confident wrong mode), and the swappable acquisition seam
#                      (config today, GPIO later, zero consumer change). This is
#                      a DISTINCT fact from PowerSourceProvider (AC-vs-battery).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Ralph (Rex)  | Initial -- config-key SSOT provider, honest
#               |              | unknown, swap-seam (US-421 / BL-014).
# ================================================================================
################################################################################
"""Tests for src/pi/power/power_mode_provider.py (US-421 / BL-014)."""

import pytest

from src.pi.power.power_mode_provider import (
    POWER_MODE_CAR,
    POWER_MODE_UNKNOWN,
    POWER_MODE_WALL,
    ConfigPowerModeSource,
    PowerModeProvider,
)


class _RaisingSource:
    """A source whose acquire() blows up -- the provider must resolve to
    unknown (honest), never propagate the error or fabricate a mode."""

    def acquire(self) -> str | None:
        raise RuntimeError("acquisition backend unavailable")


class _StubGpioSource:
    """Stands in for a FUTURE GPIO-backed acquisition (not built this sprint):
    it implements the same acquire() -> str | None seam the config source does,
    proving a swap needs zero provider/consumer change."""

    def __init__(self, value: str | None) -> None:
        self._value = value

    def acquire(self) -> str | None:
        return self._value


def _config(mode) -> dict:
    """A minimal validated-config-shaped dict carrying pi.power.mode."""
    return {"pi": {"power": {"mode": mode}}}


# ---------------------------------------------------------------------------
# ConfigPowerModeSource -- reads the raw pi.power.mode config value.
# ---------------------------------------------------------------------------


def test_configSource_readsRawMode():
    assert ConfigPowerModeSource(_config("car")).acquire() == "car"
    assert ConfigPowerModeSource(_config("wall")).acquire() == "wall"


def test_configSource_absentKey_returnsNone():
    # The source reports "undeterminable" as None; the provider maps that to
    # unknown. The source itself never invents a value.
    assert ConfigPowerModeSource({}).acquire() is None
    assert ConfigPowerModeSource({"pi": {}}).acquire() is None
    assert ConfigPowerModeSource({"pi": {"power": {}}}).acquire() is None


# ---------------------------------------------------------------------------
# PowerModeProvider -- the SSOT: validate/coerce to {car, wall, unknown}.
# ---------------------------------------------------------------------------


def test_provider_carAndWall_passThrough():
    assert PowerModeProvider.fromConfig(_config("car")).getPowerMode() == POWER_MODE_CAR
    assert PowerModeProvider.fromConfig(_config("wall")).getPowerMode() == POWER_MODE_WALL


def test_provider_explicitUnknown_isUnknown():
    got = PowerModeProvider.fromConfig(_config("unknown")).getPowerMode()
    assert got == POWER_MODE_UNKNOWN


@pytest.mark.parametrize("bad", ["garage", "", "CAR", "Wall", "battery", 3, True, None])
def test_provider_invalidOrAbsent_isUnknownNeverConfidentWrong(bad):
    # honest-instrument: anything not exactly in the valid set -> unknown.
    assert PowerModeProvider.fromConfig(_config(bad)).getPowerMode() == POWER_MODE_UNKNOWN


def test_provider_absentKey_isUnknown():
    assert PowerModeProvider.fromConfig({}).getPowerMode() == POWER_MODE_UNKNOWN


def test_provider_acquisitionError_isUnknown():
    # A raising acquisition backend must degrade to unknown, not crash.
    assert PowerModeProvider(_RaisingSource()).getPowerMode() == POWER_MODE_UNKNOWN


def test_provider_swapSeam_gpioSourceNeedsNoProviderChange():
    # The whole point of the SSOT seam: swap the acquisition, consumers/provider
    # unchanged. A GPIO-style source that yields "car" resolves to car; one that
    # can't read (None) resolves to unknown -- same provider, same interface.
    assert PowerModeProvider(_StubGpioSource("car")).getPowerMode() == POWER_MODE_CAR
    assert PowerModeProvider(_StubGpioSource("wall")).getPowerMode() == POWER_MODE_WALL
    assert PowerModeProvider(_StubGpioSource(None)).getPowerMode() == POWER_MODE_UNKNOWN
