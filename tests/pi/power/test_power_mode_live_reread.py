################################################################################
# File Name: test_power_mode_live_reread.py
# Purpose/Description: US-533 (F-126) tests for the LIVE power-mode acquisition
#   path -- the drop-in PowerModeSource that re-reads pi.power.mode from disk
#   through the US-530 shared overlay seam on EVERY acquire(), so a settings-band
#   write reaches the power tile on the emitter's next cycle instead of waiting
#   for an orchestrator restart. Today's ConfigPowerModeSource closes over the
#   STARTUP config snapshot, which is why the toggle was a restart-only setting.
#
#   The load-bearing property here is that a SECOND call sees a value written
#   AFTER the first -- a source that caches passes every single-call test.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-08    | Ralph (Rex)  | Initial -- US-533 live power-mode re-read.
# ================================================================================
################################################################################
"""US-533 tests for the live (per-cycle) power-mode acquisition source."""

import json

import pytest

from common.config import overlay
from src.pi.power.power_mode_provider import (
    POWER_MODE_CAR,
    POWER_MODE_UNKNOWN,
    POWER_MODE_WALL,
    OverlayConfigPowerModeSource,
    PowerModeProvider,
)


def _writeConfig(tmp_path, mode="unknown"):
    """A shipped config.json carrying pi.power.mode, plus its path."""
    configPath = tmp_path / "config.json"
    configPath.write_text(
        json.dumps({"pi": {"power": {"mode": mode}}}), encoding="utf-8"
    )
    return str(configPath)


def _setOverlay(configPath, mode):
    """Write the operator override exactly the way POST /settings does."""
    assert overlay.writeOverlayValue(
        overlay.overlayPathFor(configPath), overlay.POWER_MODE_KEY, mode
    )


# ---------------------------------------------------------------------------
# The whole point of the story: a write reaches the provider WITHOUT a restart.
# ---------------------------------------------------------------------------


def test_overlayWrittenAfterConstruction_isSeenOnTheNextCycle(tmp_path):
    """THE load-bearing test. The provider is built ONCE (as the orchestrator
    builds it at boot) and then the operator taps WALL. The very next
    getPowerMode() must report wall.

    A source that reads config once at construction -- which is exactly what
    ConfigPowerModeSource does -- returns `unknown` here forever, which is the
    silent no-op AC-5 forbids.
    """
    configPath = _writeConfig(tmp_path, mode="unknown")
    provider = PowerModeProvider.fromConfigPath(configPath)

    assert provider.getPowerMode() == POWER_MODE_UNKNOWN

    _setOverlay(configPath, POWER_MODE_WALL)

    assert provider.getPowerMode() == POWER_MODE_WALL


def test_successiveWritesEachLand_notJustTheFirst(tmp_path):
    """Bench -> car -> bench. A source that memoises its first successful read
    passes the test above and fails this one."""
    configPath = _writeConfig(tmp_path, mode="unknown")
    provider = PowerModeProvider.fromConfigPath(configPath)

    for mode in (POWER_MODE_WALL, POWER_MODE_CAR, POWER_MODE_WALL):
        _setOverlay(configPath, mode)
        assert provider.getPowerMode() == mode


def test_noOverlay_readsTheShippedDefault(tmp_path):
    """The shipped state: no operator override yet -> config.json wins."""
    configPath = _writeConfig(tmp_path, mode="car")
    assert PowerModeProvider.fromConfigPath(configPath).getPowerMode() == POWER_MODE_CAR


def test_liveSourceResolvesThroughTheSharedSeam_notItsOwnMerge(tmp_path):
    """A-4: the live source must agree with every other config reader.

    Proven by AGREEMENT, not by inspection -- the same overlay resolved through
    ``overlay.readEffectiveValue`` (what the settings band and the POST /settings
    re-read report) and through the provider must give the same answer, for a
    value that DIFFERS from the shipped default so a broken reader cannot pass
    by accident (US-530's fixture-vs-default lesson).
    """
    configPath = _writeConfig(tmp_path, mode="car")
    _setOverlay(configPath, POWER_MODE_WALL)

    found, effective = overlay.readEffectiveValue(configPath, overlay.POWER_MODE_KEY)
    assert (found, effective) == (True, POWER_MODE_WALL)
    assert PowerModeProvider.fromConfigPath(configPath).getPowerMode() == effective


# ---------------------------------------------------------------------------
# Honest-instrument: the live path must never become a confident wrong mode.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("junk", ["moon-base", "CAR", 1, True, None, {}])
def test_illegalOverlayValue_isUnknown_neverAConfidentMode(tmp_path, junk):
    """An overlay hand-edited to nonsense must degrade to unknown -- and NOT to
    the shipped `car`, because a corrupt mode means the deployment context is
    genuinely not known (US-530 coercion, re-proven on the live path)."""
    configPath = _writeConfig(tmp_path, mode="car")
    overlayPath = overlay.overlayPathFor(configPath)
    with open(overlayPath, "w", encoding="utf-8") as fh:
        json.dump({overlay.POWER_MODE_KEY: junk}, fh)

    assert (
        PowerModeProvider.fromConfigPath(configPath).getPowerMode()
        == POWER_MODE_UNKNOWN
    )


def test_unreadableConfig_isUnknown_notACrash(tmp_path):
    """The emitter cycle must survive a missing/renamed config.json: the tile
    reads UNKNOWN rather than taking the card-state thread down."""
    missing = str(tmp_path / "not-there.json")
    assert PowerModeProvider.fromConfigPath(missing).getPowerMode() == POWER_MODE_UNKNOWN


def test_malformedConfig_isUnknown_notACrash(tmp_path):
    configPath = tmp_path / "config.json"
    configPath.write_text("{ not json", encoding="utf-8")
    assert (
        PowerModeProvider.fromConfigPath(str(configPath)).getPowerMode()
        == POWER_MODE_UNKNOWN
    )


def test_sourceReportsAbsence_asNone_notAsAGuess(tmp_path):
    """The SOURCE contract (US-421): acquire() returns the raw candidate or None
    and never coerces -- coercion belongs to the provider, so a future GPIO swap
    stays a drop-in."""
    configPath = tmp_path / "config.json"
    configPath.write_text(json.dumps({"pi": {}}), encoding="utf-8")
    assert OverlayConfigPowerModeSource(str(configPath)).acquire() is None


def test_liveSourceSatisfiesTheExistingSwapSeam(tmp_path):
    """It is a PowerModeSource like any other: the provider takes it directly,
    with no provider change (the seam US-421 built for exactly this)."""
    configPath = _writeConfig(tmp_path, mode="wall")
    provider = PowerModeProvider(OverlayConfigPowerModeSource(configPath))
    assert provider.getPowerMode() == POWER_MODE_WALL
