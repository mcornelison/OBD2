################################################################################
# File Name: test_gear_state_emitter.py
# Purpose/Description: US-630 -- the PRODUCER half of the GEAR tile. The
#   derivation landed last iteration as a pure function wired to nothing, and
#   the measured bands landed this iteration; neither puts a gear on the panel.
#   This file pins the path that does: a SPEED/RPM reading arriving at the
#   orchestrator's real reading seam -> the deriver -> states/gear on tmpfs.
#
#   THE SEAM CHOICE IS THE LOAD-BEARING DECISION AND IS PINNED HERE. Gear is
#   derived on the READING callback (~4-5 PIDs/sec), not on the 2 s card-state
#   cadence the other emitters use. On that cadence the newest SPEED/RPM sample
#   would be up to 2 s old at emit time, against a 2 s freshness window -- the
#   tile would flicker to `stale` at random on a perfectly healthy car. A test
#   below drives exactly that timing so the coupling cannot be reintroduced.
#
#   SHIPS-DARK IS PINNED TOO. `pi.gear.enabled` false must leave NO states/gear
#   file at all -- an absent file is what the carousel already renders as an
#   honest "-- / no source", whereas an `available: false` file is a producer
#   claiming to have looked.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Rex (US-630) | Initial -- gear producer: reading seam -> file.
# ================================================================================
################################################################################

"""US-630: the gear producer, from the orchestrator's reading seam to tmpfs."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from pi.obdii import gear_derivation as gd
from pi.obdii import gear_state_emitter as gse
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.obdii.orchestrator.event_router import EventRouterMixin

# The measured table, as config.json carries it (US-630 / Atlas 2026-08-31).
_BANDS = [
    {"gear": 5, "ratioMin": 0.0, "ratioMax": 29.5},
    {"gear": 4, "ratioMin": 29.5, "ratioMax": 37.8},
    {"gear": 3, "ratioMin": 37.8, "ratioMax": 54.3},
    {"gear": 2, "ratioMin": 54.3, "ratioMax": 86.7},
    {"gear": 1, "ratioMin": 86.7, "ratioMax": 999.0},
]

# A steady 3rd-gear cruise: 44.3 rpm/kph is Atlas's measured 3rd-gear median.
_SPEED_3RD = 80.0
_RPM_3RD = 44.3 * _SPEED_3RD

# A steady 5th-gear cruise: 27.0 rpm/kph, Atlas's measured 5th-gear median.
_SPEED_5TH = 100.0
_RPM_5TH = 27.0 * _SPEED_5TH

_NOW_ISO = "2026-08-31T15:04:05Z"


class _Reading:
    """The shape RealtimeDataLogger hands the reading callback."""

    def __init__(self, parameterName: str, value: float) -> None:
        self.parameterName = parameterName
        self.value = value
        self.unit = None


class _Clock:
    """A monotonic clock the test advances by hand.

    Injected rather than patched: freshness and debounce are the two things
    these tests are about, so the clock has to be an argument, not an ambient
    fact a sleep would have to race.
    """

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _Orch(EventRouterMixin, CardStateEmitterMixin):
    """The two REAL mixins, driven with only the gear facts attached.

    Composing both is the point: the reading arrives at ``_handleReading`` --
    the production callback, with every other consumer on it inert -- so a
    change that stops routing SPEED/RPM to the deriver fails here even though
    the deriver itself still works perfectly.
    """

    def __init__(self, statesDir: str, *, enabled: bool = True, bands: Any = None):
        gear: dict[str, Any] = {
            "enabled": enabled,
            "bands": _BANDS if bands is None else bands,
            "minSpeedKph": 5.0,
            "minRpm": 900,
            "debounceSec": 2.0,
            "maxAgeSec": 2.0,
        }
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "gear": gear,
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
            }
        }
        self.clock = _Clock()
        # Every other collaborator on the reading path, inert.
        self._connection = None
        self._driveDetector = None
        self._hardwareManager = None
        self._displayManager = None
        self._alertManager = None
        self._milEdgeDetector = None
        self._dtcLogger = None
        self._alertsPausedForReconnect = False
        self._dashboardParameters = []
        self._healthCheckStats = type("S", (), {"totalReadings": 0, "totalErrors": 0})()
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
        self._initializeCardStateEmitters()
        # Inject the hand-advanced clock over the real time.monotonic seam.
        self._gearClock = self.clock

    def feed(self, speedKph: float | None, rpm: float | None) -> None:
        """Deliver one poll cycle's SPEED and RPM through the real callback."""
        if speedKph is not None:
            self._handleReading(_Reading("SPEED", speedKph))
        if rpm is not None:
            self._handleReading(_Reading("RPM", rpm))


def _gearFile(tmp_path) -> str:
    return os.path.join(str(tmp_path / "states"), gse.GEAR_STATE_FILENAME)


def _readGear(tmp_path) -> dict:
    with open(_gearFile(tmp_path), encoding="utf-8") as fh:
        return json.load(fh)


# The OBD link sustains ~4-5 PIDs/sec over Bluetooth (specs/obd2-research.md),
# so one full SPEED+RPM cycle lands about every 0.25 s. Cruises are fed at that
# cadence rather than in two samples straddling the debounce window, because
# the derivation is evaluated on EVERY reading: a pair whose halves are 2 s
# apart is genuinely stale, and refusing it is correct behaviour, not a defect.
# A test that fed the slower stream would be asserting against a feed the
# documented poll rate never produces.
_POLL_PERIOD_S = 0.25


def _cruise(orch, speedKph: float, rpm: float, seconds: float) -> None:
    """Feed a steady operating point at the real poll cadence for `seconds`."""
    elapsed = 0.0
    while elapsed <= seconds:
        orch.feed(speedKph, rpm)
        orch.clock.advance(_POLL_PERIOD_S)
        elapsed += _POLL_PERIOD_S


def _settleThirdGear(orch, tmp_path) -> dict:
    """Hold a steady 3rd-gear cruise past the debounce and read the file."""
    _cruise(orch, _SPEED_3RD, _RPM_3RD, gd.DEFAULT_DEBOUNCE_S + 0.5)
    return _readGear(tmp_path)


# ---------------------------------------------------------------------------
# The payload contract: exactly what carousel.js gearView() reads, plus ts.
# ---------------------------------------------------------------------------


class TestPayloadShape:
    """buildGearState emits the states/gear contract and nothing else."""

    def test_buildGearState_resolvedGear_carriesTheCarouselKeysPlusTs(self):
        """
        Given: a resolved 3rd gear
        When:  it is built into a states/gear payload
        Then:  it carries available/gear/reason/ts and no other key
        """
        reading = gd.GearReading(available=True, gear=3, reason=gd.REASON_ENGAGED)

        assert gse.buildGearState(reading, nowIso=_NOW_ISO) == {
            "available": True,
            "gear": 3,
            "reason": gd.REASON_ENGAGED,
            "ts": _NOW_ISO,
        }

    def test_buildGearState_typedAbsence_keepsTheReasonAndNullsTheGear(self):
        """
        Given: a typed absence (the clutch is in)
        When:  it is built into a payload
        Then:  gear is null and the reason survives to the panel

        `gear: null` rather than an omitted key: carousel.js reads
        `gearData.gear`, and an absent key and a null both read `undefined`
        there -- but only the null says the producer looked and found nothing.
        """
        reading = gd.GearReading(available=False, gear=None, reason=gd.REASON_NO_BAND)

        assert gse.buildGearState(reading, nowIso=_NOW_ISO) == {
            "available": False,
            "gear": None,
            "reason": gd.REASON_NO_BAND,
            "ts": _NOW_ISO,
        }

    def test_makeGearStateEmitter_writesTheFileNamedGear(self, tmp_path):
        """
        Given: an emitter pointed at a states dir
        When:  it emits a resolved gear
        Then:  a file called `gear` appears there, which is what /gear serves
        """
        emit = gse.makeGearStateEmitter(
            str(tmp_path / "states"), nowIsoFn=lambda: _NOW_ISO
        )

        emit(gd.GearReading(available=True, gear=4, reason=gd.REASON_ENGAGED))

        assert _readGear(tmp_path)["gear"] == 4

    def test_makeGearStateEmitter_unwritableDir_neverRaises(self, tmp_path):
        """
        Given: a states dir that cannot be provisioned
        When:  the emitter is invoked
        Then:  it returns quietly -- a dashboard hook must never crash the poll

        Same contract as every other card emitter: the orchestrator's realtime
        loop is safety-adjacent and a tmpfs hiccup must not reach it.
        """
        blocked = tmp_path / "not-a-dir"
        blocked.write_text("i am a file", encoding="utf-8")
        emit = gse.makeGearStateEmitter(str(blocked / "states"))

        emit(gd.GearReading(available=True, gear=4, reason=gd.REASON_ENGAGED))


# ---------------------------------------------------------------------------
# THE WIRING. A derivation nothing calls is exactly the state this story
# inherited, so the pin is on the orchestrator's real reading callback.
# ---------------------------------------------------------------------------


class TestTheOrchestratorFeedsIt:
    """SPEED/RPM arriving at _handleReading reach the state file."""

    def test_handleReading_steadyCruise_publishesTheDerivedGear(self, tmp_path):
        """
        Given: a steady 3rd-gear cruise arriving as real SPEED/RPM readings
        When:  the cruise has held longer than the debounce
        Then:  states/gear reports gear 3, available
        """
        orch = _Orch(str(tmp_path / "states"))

        state = _settleThirdGear(orch, tmp_path)

        assert state["available"] is True
        assert state["gear"] == 3
        assert state["reason"] == gd.REASON_ENGAGED

    def test_handleReading_atTheCardStateCadence_doesNotGoStale(self, tmp_path):
        """
        Given: readings arriving every 0.25 s, as the ~4-5 PID/s poll delivers
        When:  a full 2 s card-state emit window passes
        Then:  the gear is still live -- freshness is measured from the READING

        This is the coupling test. Derived on the 2 s card cadence instead, the
        newest sample would be ~2 s old at emit time and this steady cruise
        would report `stale` on a healthy car.
        """
        orch = _Orch(str(tmp_path / "states"))
        for _ in range(12):
            orch.feed(_SPEED_3RD, _RPM_3RD)
            orch.clock.advance(0.25)

        state = _readGear(tmp_path)
        assert state["reason"] == gd.REASON_ENGAGED
        assert state["gear"] == 3

    def test_handleReading_gearChanges_theFileFollowsIt(self, tmp_path):
        """
        Given: a settled 3rd gear on the panel
        When:  the car settles into 5th
        Then:  the file reports 5 -- it is not written once and left

        Guards the emit-once mistake: a producer that publishes at init and
        never again looks perfectly correct on a single-shot test.
        """
        orch = _Orch(str(tmp_path / "states"))
        assert _settleThirdGear(orch, tmp_path)["gear"] == 3

        _cruise(orch, _SPEED_5TH, _RPM_5TH, gd.DEFAULT_DEBOUNCE_S + 0.5)

        assert _readGear(tmp_path)["gear"] == 5

    def test_feedStopsEntirely_theCardTickDropsTheGearRatherThanHoldingIt(
        self, tmp_path
    ):
        """
        Given: a settled 3rd gear
        When:  the OBD feed stops dead and only the card-state tick keeps running
        Then:  the file reports a typed `stale` -- never the last real gear

        THE DEFECT THIS EXISTS TO PREVENT is a producer wired ONLY to the
        reading callback. Derivation and file would both be perfect, and a
        stopped pipe would simply never rewrite the file -- so the panel would
        show a confident 3rd gear for as long as the car stayed silent. That is
        the story's "never a held previous one", and no test that feeds readings
        can reach it, because feeding readings is exactly what has stopped.
        """
        orch = _Orch(str(tmp_path / "states"))
        assert _settleThirdGear(orch, tmp_path)["gear"] == 3

        orch.clock.advance(5.0)
        assert orch._maybeEmitCardStates() is True

        state = _readGear(tmp_path)
        assert state["available"] is False
        assert state["gear"] is None
        assert state["reason"] == gd.REASON_STALE

    def test_noReadingEverArrives_theCardTickPublishesNoData(self, tmp_path):
        """
        Given: a booted Pi that has never seen a SPEED or RPM reading
        When:  the card-state tick runs
        Then:  the file says no_data -- distinguishable from a stopped feed

        `no_data` and `stale` are two different operator facts: never connected
        versus connected and gone quiet. Collapsing them would make a dead
        dongle look like a car that has simply stopped reporting.
        """
        orch = _Orch(str(tmp_path / "states"))

        assert orch._maybeEmitCardStates() is True

        assert _readGear(tmp_path)["reason"] == gd.REASON_NO_DATA

    def test_handleReading_belowTheSpeedFloor_reportsTheThresholdNotAGear(
        self, tmp_path
    ):
        """
        Given: a settled 3rd gear, then the car creeps to a stop
        When:  SPEED falls below the 5 km/h floor
        Then:  the file reports below_threshold with no gear
        """
        orch = _Orch(str(tmp_path / "states"))
        assert _settleThirdGear(orch, tmp_path)["gear"] == 3

        orch.clock.advance(0.25)
        orch.feed(2.0, 1100.0)

        state = _readGear(tmp_path)
        assert state["available"] is False
        assert state["gear"] is None
        assert state["reason"] == gd.REASON_BELOW_THRESHOLD


# ---------------------------------------------------------------------------
# Ships dark, and stays dark. An uncalibrated Pi must not acquire a gear tile
# by accident, and a disabled one must not write a file at all.
# ---------------------------------------------------------------------------


class TestShipsDark:
    """pi.gear.enabled false writes nothing; enabled-but-uncalibrated is honest."""

    def test_disabled_writesNoStateFileAtAll(self, tmp_path):
        """
        Given: pi.gear.enabled false
        When:  a full settled cruise is fed through the reading callback
        Then:  no states/gear file exists

        An ABSENT file is the honest dark state: the carousel already renders
        that as "-- / no source". A file saying `available: false` would be a
        producer claiming to have looked when it never ran.
        """
        orch = _Orch(str(tmp_path / "states"), enabled=False)

        _cruise(orch, _SPEED_3RD, _RPM_3RD, gd.DEFAULT_DEBOUNCE_S + 0.5)
        assert orch._maybeEmitCardStates() is True

        assert not os.path.exists(_gearFile(tmp_path))

    def test_enabledWithNoBands_publishesNotCalibrated_notAGuess(self, tmp_path):
        """
        Given: the derivation enabled but with no band table
        When:  a real cruise is fed
        Then:  the file says not_calibrated and names no gear

        The state every deployment was in before Atlas published the table, and
        the state any future car is in before it is calibrated.
        """
        orch = _Orch(str(tmp_path / "states"), bands=[])

        _cruise(orch, _SPEED_3RD, _RPM_3RD, gd.DEFAULT_DEBOUNCE_S + 0.5)

        state = _readGear(tmp_path)
        assert state["available"] is False
        assert state["gear"] is None
        assert state["reason"] == gd.REASON_NOT_CALIBRATED


# ---------------------------------------------------------------------------
# Rule B: gear is derived ONCE and published. Nothing else may recompute it.
# ---------------------------------------------------------------------------


def test_noSecondDerivationExistsInTheTree():
    """
    Given: the ssot-design-pattern rule B constraint the story states
    When:  the shipped source is searched for a second ratio computation
    Then:  GearDeriver is constructed in exactly one production module

    Scoped to the construction site rather than the import, so deleting the
    pin cannot satisfy it and a second consumer building its own deriver fails
    here rather than on the panel.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3] / "src"
    sites = sorted(
        str(p.relative_to(root)).replace(os.sep, "/")
        for p in root.rglob("*.py")
        if "GearDeriver(" in p.read_text(encoding="utf-8")
    )

    assert sites == ["pi/obdii/gear_derivation.py"]


@pytest.mark.parametrize("param", ["SPEED", "RPM"])
def test_bothInputParameters_areRoutedToTheDeriver(tmp_path, param):
    """
    Given: a settled gear
    When:  ONE of the two inputs stops arriving while the other continues
    Then:  the gear drops -- both parameters are genuinely consumed

    Held per-parameter because a wiring that routed only SPEED (or only RPM)
    would pass every whole-cycle test above: the other value would simply stay
    at its last-seen sample forever and the ratio would look plausible.
    """
    orch = _Orch(str(tmp_path / "states"))
    assert _settleThirdGear(orch, tmp_path)["gear"] == 3

    # Let the dropped parameter age past the freshness window while the other
    # keeps arriving on cadence.
    for _ in range(16):
        orch.clock.advance(0.25)
        orch.feed(
            _SPEED_3RD if param == "RPM" else None,
            _RPM_3RD if param == "SPEED" else None,
        )

    state = _readGear(tmp_path)
    assert state["available"] is False
    assert state["reason"] == gd.REASON_STALE
