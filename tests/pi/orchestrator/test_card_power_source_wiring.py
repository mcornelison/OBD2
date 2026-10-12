################################################################################
# File Name: test_card_power_source_wiring.py
# Purpose/Description: US-502 tests for the System-Status power tile's SOURCE
#   field. The tile read PowerMonitor.readPowerStatus(), whose reader is never
#   configured in the orchestrator -- so `source` was permanently "unknown" and
#   the tile rendered "unavailable" with a grayed header bolt while the real
#   AC/battery fact was sitting in the PowerSourceProvider SSOT (X1209 GPIO6
#   PLD) that lifecycle already builds. These tests pin the tile to that one
#   provider, pin the UI's own uncertainty policy (unreadable line => unknown,
#   never a confident wrong source), and pin the LAZY read -- the provider is
#   constructed later in the boot order than the emitters, so a reference
#   captured at emitter-init time is always None.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)  | Initial -- US-502 power tile/bolt source wiring.
# ================================================================================
################################################################################

"""US-502: the power tile's source comes from the PowerSourceProvider SSOT."""

import json

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin


class _FakePld:
    """Models the REAL PldSensor contract (src/pi/hardware/pld_sensor.py:96-121).

    Load-bearing: an unreadable line returns ``isExternalPowerPresent() ==
    True`` (the non-bricking safe direction), NOT the stored value. A fake
    that returned ``_present`` when unavailable would hide the exact lie this
    story has to keep off the tile.
    """

    def __init__(self, present: bool, available: bool = True) -> None:
        self._present, self.isAvailable = present, available

    def isExternalPowerPresent(self) -> bool:
        return True if not self.isAvailable else self._present

    def isPowerLost(self) -> bool:
        return self.isAvailable and not self._present

    def startupPolarityOk(self) -> bool:
        return self.isAvailable and self._present


def _provider(*, present: bool, available: bool = True):
    from pi.power.power_source_provider import PowerSourceProvider

    return PowerSourceProvider(pld=_FakePld(present=present, available=available))


class _FakeOrch(CardStateEmitterMixin):
    """Minimal composing object exposing the attrs the mixin reads."""

    def __init__(self, config, *, powerMonitor=None, powerSourceProvider=None):
        self._config = config
        self._connection = None
        self._driveDetector = None
        self._hardwareManager = None
        self._powerMonitor = powerMonitor
        if powerSourceProvider is not None:
            self._powerSourceProvider = powerSourceProvider
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


def _config(tmp_path, *, mode=None):
    cfg = {
        "pi": {
            "splash": {"statesDir": str(tmp_path / "states")},
            "dashboard": {"stateEmitIntervalSeconds": 0.0},
        }
    }
    if mode is not None:
        cfg["pi"]["power"] = {"mode": mode}
    return cfg


def _source(orch) -> str:
    # US-668: _gatherPowerState returns (source, reason). It used to return
    # (mode, source, reason); the operator-declared mode is gone, so the source
    # moved from index 1 to index 0.
    return orch._gatherPowerState()[0]


# ---------------------------------------------------------------------------
# The real fact reaches the tile.
# ---------------------------------------------------------------------------


def test_gatherPowerState_externalPowerPresent_sourceIsExternal(tmp_path):
    """GPIO6 reads power present -> `external` (tile renders CAR/WALL + a lit
    header bolt), not the "unavailable" branch."""
    orch = _FakeOrch(_config(tmp_path), powerSourceProvider=_provider(present=True))
    assert _source(orch) == "external"


def test_gatherPowerState_powerLost_sourceIsBattery(tmp_path):
    """GPIO6 reads power lost -> `battery` (amber tile + amber bolt: the car
    is running the Pi off the UPS pack)."""
    orch = _FakeOrch(_config(tmp_path), powerSourceProvider=_provider(present=False))
    assert _source(orch) == "battery"


# US-668 deleted test_gatherPowerState_modeAndSourceStayIndependentFacts.
# Its whole subject was that `mode` and `source` are two independent facts. The
# operator-declared mode is gone (CIO 2026-09-02: "if I can see the screen then
# the power is on"), so there is no second fact to stay independent of.


def test_gatherPowerState_unreadableLine_isUnknown_notAConfidentExternal(tmp_path):
    """THE honest-instrument case. An unreadable PLD answers
    ``isExternalPowerPresent() == True`` on purpose -- that is the shutdown
    path's "never self-brick on a dead signal" policy, and taking it at face
    value here would paint a confident green "external" off a dead GPIO. The
    UI applies its OWN policy over the same fact: unreadable => unknown."""
    orch = _FakeOrch(
        _config(tmp_path), powerSourceProvider=_provider(present=False, available=False)
    )
    assert _source(orch) == "unknown"


def test_gatherPowerState_providerRaises_isUnknown(tmp_path):
    """A provider that throws yields unknown -- never a guess, and never an
    exception out of the emit path."""

    class _Exploding:
        isAvailable = True

        def isExternalPowerPresent(self):
            raise RuntimeError("gpio gone")

    orch = _FakeOrch(_config(tmp_path), powerSourceProvider=_Exploding())
    assert _source(orch) == "unknown"


def test_gatherPowerState_noProvider_isUnknown(tmp_path):
    """Bench / non-Pi: lifecycle never builds a provider (PldSensor import
    fails) -> unknown -> the tile keeps its honest "unavailable" branch."""
    orch = _FakeOrch(_config(tmp_path))
    assert _source(orch) == "unknown"


# ---------------------------------------------------------------------------
# SSOT + boot-order guards.
# ---------------------------------------------------------------------------


def test_gatherPowerState_providerIsTheOnlySource_notPowerMonitorsReader(tmp_path):
    """SSOT invariant (architecture.md §2): exactly ONE acquisition path for
    the power-source fact. A PowerMonitor reader disagreeing with GPIO6 must
    not be able to reach the tile -- if it can, we shipped the second
    acquisition path the design gate forbids."""
    orch = _FakeOrch(
        _config(tmp_path),
        powerMonitor=type("_Pm", (), {"readPowerStatus": lambda self: True})(),
        powerSourceProvider=_provider(present=False),
    )
    assert _source(orch) == "battery"


def test_gatherPowerState_providerBuiltAfterEmitterInit_isStillRead(tmp_path):
    """BOOT-ORDER GUARD. ``_initializeCardStateEmitters`` runs inside
    ``_initializeAllComponents``; ``_powerSourceProvider`` is not built until
    ``_startHardwareManager``, which runLoop calls LATER. So a provider
    reference captured at emitter-init time is always None and the tile is
    permanently "unavailable" -- green tests, dead tile. The read must happen
    at emit time."""
    orch = _FakeOrch(_config(tmp_path))
    orch._initializeCardStateEmitters()
    assert _source(orch) == "unknown"  # not wired yet: honest unknown

    orch._powerSourceProvider = _provider(present=True)  # hardware comes up

    assert _source(orch) == "external"


# ---------------------------------------------------------------------------
# End-to-end: the emitted state file the carousel actually reads.
# ---------------------------------------------------------------------------


def _emittedPower(tmp_path, orch) -> dict:
    assert orch._maybeEmitCardStates() is True
    state = json.loads(
        (tmp_path / "states" / "system-status").read_text(encoding="utf-8")
    )
    return state["power"]


def test_maybeEmit_onBattery_stateFileCarriesBatterySource(tmp_path):
    orch = _FakeOrch(
        _config(tmp_path, mode="car"), powerSourceProvider=_provider(present=False)
    )
    orch._initializeCardStateEmitters()
    # US-628: a resolved source publishes an EMPTY reasons map. Asserted as an
    # exact shape so a reason quietly appearing beside a real reading fails.
    assert _emittedPower(tmp_path, orch) == {
        "source": "battery",
        "reasons": {},
    }


def test_maybeEmit_onExternal_stateFileCarriesExternalSource(tmp_path):
    orch = _FakeOrch(
        _config(tmp_path, mode="car"), powerSourceProvider=_provider(present=True)
    )
    orch._initializeCardStateEmitters()
    assert _emittedPower(tmp_path, orch) == {
        "source": "external",
        "reasons": {},
    }
