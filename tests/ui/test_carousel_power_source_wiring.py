################################################################################
# File Name: test_carousel_power_source_wiring.py
# Purpose/Description: US-502 END-TO-END pin for the power tile + header bolt.
#   The two halves of this feature were each individually correct and did not
#   agree: carousel.js has always rendered `source: "battery"|"external"`
#   properly, and the Pi has always known the real AC/battery state via the
#   PowerSourceProvider SSOT -- but nothing carried the fact from one to the
#   other, so the tile rendered "unavailable" and the bolt stayed gray forever.
#   A test on either half alone stays green through that failure; only a test
#   that feeds the REAL emitted state file into the REAL renderer catches it.
#   So these drive the orchestrator emitter for real, read the state file the
#   kiosk reads, and hand it to carousel.js under node.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)  | Initial -- US-502 emitter->tile/bolt chain.
# ================================================================================
################################################################################

"""US-502: emitted power state -> carousel powerTile/powerGlyphState (node)."""

import json
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _view(fn: str, arg):
    # encoding="utf-8" is load-bearing on Windows: `text=True` alone decodes
    # node's UTF-8 stdout with the locale codec (cp1252 here), which turns the
    # tile's `—` / `·` glyphs into U+FFFD and fails a correct assertion.
    proc = subprocess.run(
        [_NODE, _PROBE, fn, json.dumps(arg)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


class _Orch(CardStateEmitterMixin):
    """The real mixin, driven with only the power source attached."""

    def __init__(self, statesDir, provider):
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "power": {"mode": "car"},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
            }
        }
        self._connection = None
        self._driveDetector = None
        self._hardwareManager = None
        self._powerSourceProvider = provider
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = None
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0


def _emitPower(tmp_path, provider) -> dict:
    """Run the real emitter, return the `power` object the carousel reads."""
    orch = _Orch(str(tmp_path / "states"), provider)
    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True
    state = json.loads(
        (tmp_path / "states" / "system-status").read_text(encoding="utf-8")
    )
    return state["power"]


def _pld(present: bool, available: bool = True):
    from pi.power.power_source_provider import PowerSourceProvider

    return PowerSourceProvider(
        pld=SimpleNamespace(
            isAvailable=available,
            # Real PldSensor: unreadable line answers "present" (safe dir).
            isExternalPowerPresent=lambda: True if not available else present,
        )
    )


def test_onExternalPower_tileIsRealAndBoltIsLit(tmp_path):
    """Wall/bench or engine-running: the tile renders the deployment mode with
    an `external` detail at level ok, and the header bolt lights -- issue #2
    (grayed bolt) and #6 ("power unavailable") both gone."""
    power = _emitPower(tmp_path, _pld(present=True))

    tile = _view("powerTile", power)
    # US-668: the tile renders the SENSED source as its value now, not the
    # operator-declared mode. EXTERNAL is the fact a lit screen cannot give you.
    assert tile["value"] == "EXTERNAL"
    assert tile["detail"] == "wall/car power"
    assert tile["level"] == "ok"
    assert _view("powerGlyphState", power) == "ok"


def test_onBatteryPower_tileSaysBatteryAndBoltIsAmber(tmp_path):
    """Power dropped: the Pi is running off the UPS pack -> BATTERY tile +
    amber bolt, so the operator sees it before the pack runs out."""
    power = _emitPower(tmp_path, _pld(present=False))

    tile = _view("powerTile", power)
    assert tile["value"] == "BATTERY"
    # Escapes, not literals: this file stays pure ASCII so the pin cannot be
    # softened by whatever encoding a given box reads the source with.
    assert tile["detail"] == "on UPS"
    assert tile["level"] == "amber"
    assert _view("powerGlyphState", power) == "amber"


def test_unreadableLine_staysHonestlyUnavailable(tmp_path):
    """Honest-instrument: a PLD we cannot read renders the neutral/unavailable
    tile and a neutral bolt -- the SAME surface as before this story. Wiring a
    real source must not turn "I don't know" into a confident claim."""
    power = _emitPower(tmp_path, _pld(present=False, available=False))
    assert power["source"] == "unknown"

    tile = _view("powerTile", power)
    assert tile["value"] == "\u2014"
    assert tile["detail"] == "unavailable"
    assert tile["level"] == "unavailable"
    assert _view("powerGlyphState", power) == "neutral"
