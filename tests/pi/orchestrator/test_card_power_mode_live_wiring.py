################################################################################
# File Name: test_card_power_mode_live_wiring.py
# Purpose/Description: US-533 (F-126) -- the wiring half of the LIVE power-mode
#   setting. tests/pi/power/test_power_mode_live_reread.py proves the source
#   re-reads; this proves PRODUCTION actually builds that source, which is the
#   difference between a working toggle and a green suite over a dead one.
#
#   The band labels pi.power.mode "applies now". That label is a claim about
#   THIS wiring: if the orchestrator keeps building PowerModeProvider.fromConfig
#   over its boot-time config snapshot, the operator taps WALL, the label says it
#   took effect, and the power tile keeps reading CAR forever -- the exact silent
#   no-op the band exists to prevent.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-08    | Ralph (Rex)  | Initial -- US-533 live power-mode wiring.
# ================================================================================
################################################################################
"""US-533: the orchestrator builds the LIVE power-mode source when it can."""

import json

from common.config import overlay
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.power.power_mode_provider import (
    POWER_MODE_CAR,
    POWER_MODE_WALL,
    ConfigPowerModeSource,
    OverlayConfigPowerModeSource,
)


class _FakeOrch(CardStateEmitterMixin):
    """The smallest composer the emitter-construction path needs."""

    def __init__(self, config, configPath=None):
        self._config = config
        self._connection = None
        self._driveDetector = None
        self._hardwareManager = None
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = None
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 2.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0
        if configPath is not None:
            self._configPath = configPath


def _config(tmp_path, mode):
    return {
        "pi": {
            "power": {"mode": mode},
            "splash": {"statesDir": str(tmp_path / "states")},
            "dashboard": {"stateEmitEnabled": True},
        }
    }


def _writeConfigFile(tmp_path, mode):
    configPath = tmp_path / "config.json"
    configPath.write_text(json.dumps(_config(tmp_path, mode)), encoding="utf-8")
    return str(configPath)


def test_withAConfigPath_theOrchestratorBuildsTheLiveSource(tmp_path):
    (tmp_path / "states").mkdir()
    configPath = _writeConfigFile(tmp_path, POWER_MODE_CAR)
    orch = _FakeOrch(_config(tmp_path, POWER_MODE_CAR), configPath=configPath)

    orch._initializeCardStateEmitters()

    assert isinstance(
        orch._cardPowerModeProvider._source, OverlayConfigPowerModeSource
    )


def test_theWiredProviderActuallyFollowsAnOverlayWrite(tmp_path):
    """Behaviour, not just the type: build the emitters as boot does, then write
    the overlay as POST /settings does, and read the mode as the emit cycle
    does. This is the round-trip AC-1 asks for, minus the HTTP hop."""
    (tmp_path / "states").mkdir()
    configPath = _writeConfigFile(tmp_path, POWER_MODE_CAR)
    orch = _FakeOrch(_config(tmp_path, POWER_MODE_CAR), configPath=configPath)
    orch._initializeCardStateEmitters()
    assert orch._cardPowerModeProvider.getPowerMode() == POWER_MODE_CAR

    overlay.writeOverlayValue(
        overlay.overlayPathFor(configPath), overlay.POWER_MODE_KEY, POWER_MODE_WALL
    )

    assert orch._cardPowerModeProvider.getPowerMode() == POWER_MODE_WALL


def test_withoutAConfigPath_theSnapshotSourceStillWorks(tmp_path):
    """Composers with no config path (the standalone/test paths) keep the US-421
    behaviour rather than losing the power tile entirely -- degrade to stale,
    never to broken."""
    (tmp_path / "states").mkdir()
    orch = _FakeOrch(_config(tmp_path, POWER_MODE_WALL))

    orch._initializeCardStateEmitters()

    assert isinstance(orch._cardPowerModeProvider._source, ConfigPowerModeSource)
    assert orch._cardPowerModeProvider.getPowerMode() == POWER_MODE_WALL


def test_orchestratorCarriesTheConfigPathFromMain(tmp_path):
    """The path has to REACH the mixin. ApplicationOrchestrator must accept it
    and main() must pass it, or the live source is unreachable in production and
    every test above is exercising a code path nothing builds."""
    import inspect

    from pi import main as pi_main
    from pi.obdii.orchestrator.core import (
        ApplicationOrchestrator,
        createOrchestratorFromConfig,
    )

    assert "configPath" in inspect.signature(ApplicationOrchestrator.__init__).parameters
    assert "configPath" in inspect.signature(createOrchestratorFromConfig).parameters
    assert "configPath" in inspect.signature(pi_main.runWorkflow).parameters

    orch = ApplicationOrchestrator(
        config=_config(tmp_path, POWER_MODE_CAR), configPath="config.json"
    )
    assert orch._configPath == "config.json"

    # main() must hand runWorkflow the SAME path it loaded the config from --
    # a different default here would point the live re-read at a file the
    # orchestrator never validated.
    source = inspect.getsource(pi_main.main)
    assert "configPath=args.config" in source
