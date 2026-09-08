################################################################################
# File Name: test_gear_park_link_health_wiring.py
# Purpose/Description: US-687-b (F-138) -- the JOIN. `GearDeriver.update()` grew a
#   `linkHealthy` input whose default is FALSE, so a producer that never passes
#   it is a Park branch that can never fire: perfect derivation, correct
#   renderer, dark tile. That is the US-494/495/498 shape this project keeps
#   re-finding, and it is why this file exists as well as the two that pin the
#   halves.
#
#   THE MAPPING IS THE CLAIM, and it is taken from the REAL `_gatherObdLinkState`
#   over a REAL connection status rather than from a hand-set boolean:
#   `linkHealthy = obdAvailable and linkState == OBD_LINKED`. A test that set
#   the flag itself would prove the deriver works and say nothing about whether
#   the orchestrator ever computes it -- which is the only thing in doubt.
#
#   NOT A NODE TEST, deliberately: the claim here is about the state file the
#   orchestrator writes, so it must run on every box including the ones that
#   cannot render. The rendered half lives in tests/ui/test_carousel_gear_park.py.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-07    | Rex (US-687-b) | Initial -- link health reaches the gear
#               |                | producer, and the three not-linked states
#               |                | that must never publish P.
# ================================================================================
################################################################################

"""US-687-b: the orchestrator's link health reaches the gear derivation."""

from __future__ import annotations

import json

from pi.obdii import gear_derivation as gd
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin

# A band table so the deriver is CALIBRATED -- `not_calibrated` dominates every
# other branch, so an uncalibrated fixture here would report the same absence
# whether or not the wiring exists, and this file would prove nothing.
_BANDS = [{"gear": 2, "ratioMin": 54.0, "ratioMax": 74.0}]

_MEASURED_IDLE_RPM = 800.0


class _FakeStatus:
    """The three fields `_gatherObdLinkState` actually reads off a status."""

    def __init__(self, *, connected: bool, state: str, totalConnections: int):
        self.connected = connected
        self.state = state
        self.retryCount = 0
        self.totalConnections = totalConnections


class _FakeConnection:
    """A connection whose status is whatever the test hands it.

    Models the REAL contract at `_gatherObdLinkState`: `connected` decides
    LINKED, `totalConnections` decides availability, and the state STRING
    decides reconnecting-vs-down. Nothing here shortcuts the mapping -- the
    production method is what turns these into `linkHealthy`.
    """

    def __init__(self, status):
        self._status = status

    def getStatus(self):
        return self._status


class _Orch(CardStateEmitterMixin):
    """The real mixin with only the gear + link facts attached."""

    def __init__(self, statesDir, *, connection, clock, parkDwellSec):
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
                "gear": {
                    "enabled": True,
                    "bands": _BANDS,
                    "parkDwellSec": parkDwellSec,
                },
            }
        }
        self._connection = connection
        self._driveDetector = None
        self._hardwareManager = None
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
        self._gearClock = clock


class _Clock:
    """A monotonic clock the test advances by hand."""

    def __init__(self, start=1000.0):
        self.nowS = start

    def __call__(self):
        return self.nowS


def _runParkedTicks(tmp_path, status, *, holdS=25.0, parkDwellSec=20.0) -> dict:
    """Drive the REAL emit path with NO RPM ever arriving; return states/gear.

    Everything between the fake status and the parsed JSON is production code:
    _gatherObdLinkState -> _emitGearState -> GearDeriver.update ->
    makeGearStateEmitter -> the state file. A pin taken anywhere short of the
    file would not catch a missing passthrough, which is the entire risk here.
    """
    clock = _Clock()
    orch = _Orch(
        str(tmp_path / "states"),
        connection=_FakeConnection(status),
        clock=clock,
        parkDwellSec=parkDwellSec,
    )
    orch._initializeCardStateEmitters()

    end = clock.nowS + holdS
    while clock.nowS <= end:
        orch._emitGearState()
        clock.nowS += 0.5

    return json.loads((tmp_path / "states" / "gear").read_text(encoding="utf-8"))


def _linkedStatus() -> _FakeStatus:
    """Parked with the key off and the dongle powered: connected, ECU dark.

    This is the case clause 74 made reachable -- the port has CONSTANT power on
    this car (CIO looked at the lit dongle key-out, 2026-09-06), so the serial
    link survives key-off while the ECU stops answering PIDs. On a key-switched
    port the link would drop at key-off and P would never appear at all.
    """
    return _FakeStatus(connected=True, state="connected", totalConnections=3)


# ---------------------------------------------------------------------------
# The join: link health reaches the producer, and Park depends on it.
# ---------------------------------------------------------------------------


def test_emitGearState_healthyLink_withNoRpm_publishesPark(tmp_path):
    """
    Given: a REAL connected status and no RPM ever observed
    When:  the orchestrator's own emit path runs past the park dwell
    Then:  states/gear says P

    THE ONE THAT WOULD HAVE CAUGHT A MISSING PASSTHROUGH. `linkHealthy`
    defaults to False, so an `_emitGearState` that forgot the argument leaves
    every other test in this sprint green and the tile permanently dark.
    """
    state = _runParkedTicks(tmp_path, _linkedStatus())

    assert state["available"] is True
    assert state["gear"] == gd.GEAR_PARK
    assert state["reason"] == gd.REASON_PARK


def test_emitGearState_linkDown_theLooseDongleIncident_publishesNoPark(tmp_path):
    """
    Given: a status that has NEVER connected -- no dongle, or a dead one
    When:  the same 25 s of ticks run
    Then:  no P

    The 2026-09-04 incident: `Connected: no` with 41 failed attempts, and two
    days of zero rows. Without the link condition the panel would have shown a
    confident PARK the whole time.
    """
    state = _runParkedTicks(
        tmp_path,
        _FakeStatus(connected=False, state="disconnected", totalConnections=0),
    )

    assert state["gear"] != gd.GEAR_PARK
    assert state["available"] is False


def test_emitGearState_reconnecting_isNotHealthy_soNoPark(tmp_path):
    """
    Given: a car we HAVE reached, now mid-reconnect
    When:  the same 25 s of ticks run
    Then:  no P -- a flapping link is not evidence the car is parked

    🔴 THE SUBTLE ONE, and the reason the condition is `linkState ==
    OBD_LINKED` rather than `obdAvailable`. A reconnecting link reports
    obdAvailable TRUE (US-672: availability asks whether the source is ABSENT,
    and we have reached this car before). An implementation that gated Park on
    availability alone passes the loose-dongle test above and fails HERE --
    which is exactly the state a car throws while being driven out of Bluetooth
    range.
    """
    state = _runParkedTicks(
        tmp_path,
        _FakeStatus(connected=False, state="reconnecting", totalConnections=5),
    )

    assert state["gear"] != gd.GEAR_PARK


def test_gatherObdLinkState_reconnecting_reportsAvailableButNotLinked(tmp_path):
    """
    Given: the reconnecting status the test above feeds
    When:  the REAL link-state mapping is asked about it
    Then:  available is True while the state is NOT `linked`

    A GUARD ON THE FIXTURE, NOT ON THE CODE. The test above is only meaningful
    because `reconnecting` is the state where availability and linked-ness
    DISAGREE. If that mapping ever changed so the two agreed, that test would
    still pass and would quietly stop distinguishing the two conditions.
    """
    from pi.splash.system_status_emitter import OBD_LINKED

    orch = _Orch(
        str(tmp_path / "states"),
        connection=_FakeConnection(
            _FakeStatus(connected=False, state="reconnecting", totalConnections=5)
        ),
        clock=_Clock(),
        parkDwellSec=20.0,
    )
    linkState, _retries, obdAvailable, _reason = orch._gatherObdLinkState()

    assert obdAvailable is True, (
        "the reconnecting branch no longer reports available, so the test above "
        "has stopped distinguishing linked-ness from availability"
    )
    assert linkState != OBD_LINKED


def test_gatherObdLinkState_connected_isTheOneStateThatCountsAsHealthy(tmp_path):
    """
    Given: the connected status the Park test feeds
    When:  the REAL link-state mapping is asked about it
    Then:  it is available AND linked

    The other half of the fixture guard: the positive case must genuinely be
    the healthy one, or `test_emitGearState_healthyLink...` is passing for a
    reason unrelated to link health.
    """
    from pi.splash.system_status_emitter import OBD_LINKED

    orch = _Orch(
        str(tmp_path / "states"),
        connection=_FakeConnection(_linkedStatus()),
        clock=_Clock(),
        parkDwellSec=20.0,
    )
    linkState, _retries, obdAvailable, _reason = orch._gatherObdLinkState()

    assert obdAvailable is True
    assert linkState == OBD_LINKED


def test_emitGearState_healthyLinkButBeforeTheDwell_publishesNoPark(tmp_path):
    """
    Given: a healthy link and no RPM, for less than the park dwell
    When:  states/gear is read
    Then:  no P

    The dwell survives the wiring. Written because the tempting way to make the
    first test pass is to publish P as soon as the link is healthy and RPM is
    missing -- which paints Park during every ordinary bus stall.
    """
    state = _runParkedTicks(tmp_path, _linkedStatus(), holdS=10.0)

    assert state["gear"] != gd.GEAR_PARK


def test_emitGearState_liveRpmOnAHealthyLink_isNeutralNotPark(tmp_path):
    """
    Given: a healthy link that IS delivering RPM, with the car stopped
    When:  the reading is routed in through the real observe seam
    Then:  N, not P -- US-687-a's branch survives the wiring

    Driven through `observeGearInput`, the REAL callback the orchestrator hangs
    off the realtime poll, rather than by calling the emitter directly: US-630
    lost a session to a wiring that logged "wired" and never derived, and only
    a test that used the real seam could see it.
    """
    clock = _Clock()
    orch = _Orch(
        str(tmp_path / "states"),
        connection=_FakeConnection(_linkedStatus()),
        clock=clock,
        parkDwellSec=20.0,
    )
    orch._initializeCardStateEmitters()

    orch.observeGearInput("SPEED", 0.0)
    orch.observeGearInput("RPM", _MEASURED_IDLE_RPM)

    state = json.loads((tmp_path / "states" / "gear").read_text(encoding="utf-8"))

    assert state["gear"] == gd.GEAR_NEUTRAL
    assert state["reason"] == gd.REASON_NEUTRAL
