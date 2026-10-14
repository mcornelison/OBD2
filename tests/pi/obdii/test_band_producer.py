################################################################################
# File Name: test_band_producer.py
# Purpose/Description: US-875 -- the band producer behind states/obd-live. Runs
#   Spool's eleven fixtures and Atlas's stale-coolant fixture, the coolant
#   dwell / clear hysteresis on event time, the battery engine-running gate with
#   SUB-SECOND event ts, the RPM cues and scale read from config, and the
#   noBandReason vocabulary.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-875) | Initial -- band producer fixtures.
# ================================================================================
################################################################################

"""US-875: one provider derives every live band; pages hold no threshold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pi.obdii import band_producer as bp
from pi.obdii import obd_live_emitter as ole

_T0 = datetime(2026, 10, 13, 12, 10, 0, tzinfo=UTC)


def _at(seconds: float) -> datetime:
    return _T0 + timedelta(seconds=seconds)


def _producer(config: dict[str, Any] | None = None) -> bp.BandProducer:
    return bp.BandProducer(bp.BandSettings.fromConfig(config or {}))


def _feed(
    producer: bp.BandProducer, name: str, value: Any, start: float, end: float, step: float
) -> None:
    """Feed ``value`` for ``name`` every ``step`` s from ``start`` to ``end`` inclusive."""
    t = start
    while t <= end + 1e-9:
        producer.observe(name, value, _at(t))
        t += step


def _band(producer: bp.BandProducer, name: str) -> str | None:
    result = producer.resultFor(name)
    return None if result.band is None else result.band["band"]


def _running(producer: bp.BandProducer, start: float, end: float, rpm: float = 800) -> None:
    """A running engine: fresh RPM every 2.2 s (the measured ~0.45 Hz cadence)."""
    _feed(producer, "RPM", rpm, start, end, 2.2)


# ======================================================== Spool's fixtures


class TestSpoolFixtures:
    """Spool 2026-10-13 fixtures, plus Atlas's stale-coolant case."""

    def test_coolant104HeldTwentyNineSeconds_isGreen(self) -> None:
        """
        Given: coolant 104 C every 1 s for 29 s
        When: classified
        Then: green -- the 30 s dwell is not met
        """
        producer = _producer()
        _feed(producer, "COOLANT_TEMP", 104, 0, 29, 1)

        assert _band(producer, "COOLANT_TEMP") == "green"

    def test_coolant104HeldThirtyOneSeconds_isAmber(self) -> None:
        """
        Given: coolant 104 C every 1 s for 31 s
        When: classified
        Then: amber
        """
        producer = _producer()
        _feed(producer, "COOLANT_TEMP", 104, 0, 31, 1)

        assert _band(producer, "COOLANT_TEMP") == "amber"

    def test_singleCoolant110_isRedImmediately(self) -> None:
        """
        Given: one coolant reading of 110 C
        When: classified
        Then: red, no dwell
        """
        producer = _producer()
        producer.observe("COOLANT_TEMP", 110, _at(0))

        result = producer.resultFor("COOLANT_TEMP")
        assert result.band == {
            "band": "red", "since": "2026-10-13T12:10:00Z", "reason": "coolant >= 110 C",
        }
        assert result.noBandReason is None

    def test_coolantAmberThen101_clearsOnlyAfterTenSeconds(self) -> None:
        """
        Given: coolant amber at 105 C, then 101 C every 1 s
        When: 101 C has held 9 s, then 10 s
        Then: still amber at 9 s, green at 10 s
        """
        producer = _producer()
        _feed(producer, "COOLANT_TEMP", 105, 0, 30, 1)
        assert _band(producer, "COOLANT_TEMP") == "amber"

        _feed(producer, "COOLANT_TEMP", 101, 31, 40, 1)
        assert _band(producer, "COOLANT_TEMP") == "amber"

        producer.observe("COOLANT_TEMP", 101, _at(41))
        result = producer.resultFor("COOLANT_TEMP")
        assert result.band is not None
        assert result.band["band"] == "green"
        assert result.band["since"] == "2026-10-13T12:10:41Z"
        assert result.band["reason"] == "coolant below 102 C for 10 s"

    def test_coolantStaleGap_resetsTheDwell(self) -> None:
        """
        Given: coolant 105 C for 5 s, then 40 s with no reading, then 105 C at +45 s
        When: classified
        Then: NOT amber -- 45 s apart is not 45 s held (a dwell is not a window)
        """
        producer = _producer()
        _feed(producer, "COOLANT_TEMP", 105, 0, 5, 1)
        producer.observe("COOLANT_TEMP", 105, _at(45))

        assert _band(producer, "COOLANT_TEMP") == "green"

    def test_intakeAir64_hasNoBand(self) -> None:
        """
        Given: IAT 64 C (heat soak, informational only)
        When: classified
        Then: band null, noBandReason no_band_defined
        """
        producer = _producer()
        producer.observe("INTAKE_TEMP", 64, _at(0))

        assert producer.resultFor("INTAKE_TEMP") == bp.BandResult(None, "no_band_defined")

    def test_crank_rpm208With11VSameTs_isNotBanded(self) -> None:
        """
        Given: RPM 208 and BATTERY_V 11.0 at the same event ts (a crank)
        When: classified
        Then: battery band null, engine_not_running -- never red on a crank
        """
        producer = _producer()
        producer.observe("RPM", 208, _at(0))
        producer.observe("BATTERY_V", 11.0, _at(0))

        assert producer.resultFor("BATTERY_V") == bp.BandResult(None, "engine_not_running")

    def test_stall_lastRpm734ThenSixtySecondsSilent_isNotBanded(self) -> None:
        """
        Given: last RPM 734, then 60 s with no RPM sample, BATTERY_V 11.9
        When: classified
        Then: band null, engine_not_running (not red): a last-known RPM is not running
        """
        producer = _producer()
        producer.observe("RPM", 734, _at(0))
        producer.observe("BATTERY_V", 11.9, _at(60))

        assert producer.resultFor("BATTERY_V") == bp.BandResult(None, "engine_not_running")

    def test_running13_4VHeld130Seconds_isAmberNotShipped(self) -> None:
        """
        Given: the engine running, BATTERY_V 13.4 held 130 s
        When: classified
        Then: band null, amber_not_shipped (CIO R38: no battery amber this sprint)
        """
        producer = _producer()
        readings = 61  # 60 gaps of 2.2 s = 132 s held
        for i in range(readings):
            t = 10 + i * 2.2
            producer.observe("RPM", 800, _at(t))
            producer.observe("BATTERY_V", 13.4, _at(t + 0.5))

        assert producer.resultFor("BATTERY_V") == bp.BandResult(None, "amber_not_shipped")

    def test_running11_8VOutsideTheCrankGuard_isRedImmediately(self) -> None:
        """
        Given: the engine running for 20 s, then BATTERY_V 11.8
        When: classified
        Then: red on that single sample
        """
        producer = _producer()
        _running(producer, 0, 20)
        producer.observe("BATTERY_V", 11.8, _at(20.4))

        result = producer.resultFor("BATTERY_V")
        assert result.band is not None
        assert result.band["band"] == "red"
        assert result.band["reason"] == "battery below 12 V with the engine running"

    def test_running14V_isGreen(self) -> None:
        """
        Given: the engine running, BATTERY_V 14.0
        When: classified
        Then: green
        """
        producer = _producer()
        _running(producer, 0, 20)
        producer.observe("BATTERY_V", 14.0, _at(20.4))

        assert _band(producer, "BATTERY_V") == "green"

    def test_coolantAmberThenSixSecondsSilent_publishesStaleWithFrozenBand(self) -> None:
        """
        Given: coolant amber (Atlas 2026-10-13), then 6 s with no reading
        When: states/obd-live is built
        Then: value null, stale true, band null, noBandReason stale, last.band amber
        """
        tracker = ole.ObdLiveTracker({})

        class _R:
            def __init__(self, value: float, ts: datetime) -> None:
                self.parameterName = "COOLANT_TEMP"
                self.value = value
                self.unit = "C"
                self.timestamp = ts

        for i in range(32):
            tracker.observeReading(_R(105.0, _at(i)))

        state = ole.buildObdLiveState(
            tracker.snapshot(), nowUtc=_at(31 + 6), staleSec=5.0, dataSource="real"
        )

        entry = state["params"]["COOLANT_TEMP"]
        assert entry["value"] is None
        assert entry["stale"] is True
        assert entry["band"] is None
        assert entry["noBandReason"] == "stale"
        assert entry["last"]["value"] == 105.0
        assert entry["last"]["band"]["band"] == "amber"


# ================================================================ coolant


class TestCoolant:
    """Threshold + dwell + clear hysteresis, all on event ts."""

    def test_storyExample_amberSinceIsTheDwellEnd(self) -> None:
        """
        Given: coolant reaches 105 C at 12:10:00 and stays (1 s readings)
        When: classified at 12:10:30
        Then: {band: amber, since: 12:10:30Z, reason: 'coolant >= 104 C for 30 s'}
        """
        producer = _producer()
        _feed(producer, "COOLANT_TEMP", 105, 0, 29, 1)
        assert _band(producer, "COOLANT_TEMP") == "green"

        producer.observe("COOLANT_TEMP", 105, _at(30))

        assert producer.resultFor("COOLANT_TEMP").band == {
            "band": "amber",
            "since": "2026-10-13T12:10:30Z",
            "reason": "coolant >= 104 C for 30 s",
        }

    def test_amberHeldTwoMinutes_escalatesToRed(self) -> None:
        """
        Given: coolant 105 C held 120 s
        When: classified
        Then: red by dwell, not by the single-sample edge
        """
        producer = _producer()
        _feed(producer, "COOLANT_TEMP", 105, 0, 119, 1)
        assert _band(producer, "COOLANT_TEMP") == "amber"

        producer.observe("COOLANT_TEMP", 105, _at(120))

        result = producer.resultFor("COOLANT_TEMP")
        assert result.band is not None
        assert result.band["band"] == "red"
        assert result.band["reason"] == "coolant >= 104 C for 120 s"

    def test_red_holdsBetweenClearAndAmber(self) -> None:
        """
        Given: red at 110 C, then 103 C (below amber, above clear) for 60 s
        When: classified
        Then: still red -- only below 102 C held 10 s clears it
        """
        producer = _producer()
        producer.observe("COOLANT_TEMP", 110, _at(0))
        _feed(producer, "COOLANT_TEMP", 103, 1, 61, 1)

        assert _band(producer, "COOLANT_TEMP") == "red"

    def test_dipBelowAmber_resetsTheAmberDwell(self) -> None:
        """
        Given: 105 C for 20 s, one 103 C reading, then 105 C for 20 s more
        When: classified
        Then: green -- the dwell is consecutive readings, not accumulated time
        """
        producer = _producer()
        _feed(producer, "COOLANT_TEMP", 105, 0, 20, 1)
        producer.observe("COOLANT_TEMP", 103, _at(21))
        _feed(producer, "COOLANT_TEMP", 105, 22, 42, 1)

        assert _band(producer, "COOLANT_TEMP") == "green"

    def test_nullReading_resetsTheDwell(self) -> None:
        """
        Given: 105 C for 20 s, one null reading, then 105 C for 20 s more
        When: classified
        Then: green -- a null gap resets the dwell
        """
        producer = _producer()
        _feed(producer, "COOLANT_TEMP", 105, 0, 20, 1)
        producer.observe("COOLANT_TEMP", None, _at(21))
        _feed(producer, "COOLANT_TEMP", 105, 22, 42, 1)

        assert _band(producer, "COOLANT_TEMP") == "green"

    def test_staleGapWhileAmber_resetsTheClearHold(self) -> None:
        """
        Given: amber, then 101 C for 8 s, a 6 s gap, then 101 C for 8 s more
        When: classified
        Then: still amber -- the clear hold restarted after the gap
        """
        producer = _producer()
        _feed(producer, "COOLANT_TEMP", 105, 0, 30, 1)
        _feed(producer, "COOLANT_TEMP", 101, 31, 39, 1)
        _feed(producer, "COOLANT_TEMP", 101, 45, 53, 1)

        assert _band(producer, "COOLANT_TEMP") == "amber"

    def test_thresholdsAreTheConfigKeys(self) -> None:
        """
        Given: pi.bands.coolant.amberC 90, amberDwellSec 5
        When: coolant 95 C held 5 s
        Then: amber -- the numbers come from config
        """
        producer = _producer(
            {"pi": {"bands": {"coolant": {"amberC": 90, "amberDwellSec": 5}}}}
        )
        _feed(producer, "COOLANT_TEMP", 95, 0, 5, 1)

        result = producer.resultFor("COOLANT_TEMP")
        assert result.band is not None
        assert result.band["band"] == "amber"
        assert result.band["reason"] == "coolant >= 90 C for 5 s"


# ================================================================ battery


class TestBatteryEngineGate:
    """Sub-second event ts: stored ts are whole seconds, so only units prove the margin."""

    def test_rpmJustInsideMaxAge_isRunning(self) -> None:
        """
        Given: the engine running; the last RPM 2.95 s before BATTERY_V 14.0
        When: classified
        Then: green
        """
        producer = _producer()
        _running(producer, 0, 13.2)
        producer.observe("BATTERY_V", 14.0, _at(13.2 + 2.95))

        assert _band(producer, "BATTERY_V") == "green"

    def test_rpmJustPastMaxAge_isNotRunning(self) -> None:
        """
        Given: the engine running; the last RPM 3.05 s before BATTERY_V 14.0
        When: classified
        Then: band null, engine_not_running -- a late poll is honest, never wrong
        """
        producer = _producer()
        _running(producer, 0, 13.2)
        producer.observe("BATTERY_V", 14.0, _at(13.2 + 3.05))

        assert producer.resultFor("BATTERY_V") == bp.BandResult(None, "engine_not_running")

    def test_withinCrankGuardOfTheRunningTransition_isNotBanded(self) -> None:
        """
        Given: drive 87's restart -- RPM 208 then RPM 1516 two s later, 14.0 V with it
        When: classified
        Then: band null, engine_not_running -- inside the 3 s crank guard
        """
        producer = _producer()
        producer.observe("RPM", 208, _at(0))
        producer.observe("BATTERY_V", 11.0, _at(0))
        producer.observe("RPM", 1516, _at(2.0))
        producer.observe("BATTERY_V", 14.0, _at(2.0))

        assert producer.resultFor("BATTERY_V") == bp.BandResult(None, "engine_not_running")

    def test_justPastTheCrankGuard_isBanded(self) -> None:
        """
        Given: the running transition at t=2.0, fresh RPM at 4.2, BATTERY_V at 5.1
        When: classified (3.1 s after the transition)
        Then: green
        """
        producer = _producer()
        producer.observe("RPM", 208, _at(0))
        producer.observe("RPM", 1516, _at(2.0))
        producer.observe("RPM", 900, _at(4.2))
        producer.observe("BATTERY_V", 14.0, _at(5.1))

        assert _band(producer, "BATTERY_V") == "green"

    def test_firstRpmAfterSilenceIsATransition(self) -> None:
        """
        Given: the engine restarts straight to RPM 900 after 60 s of silence
        When: BATTERY_V 14.0 arrives 1 s later
        Then: not banded -- the first running sample after silence starts the guard
        """
        producer = _producer()
        producer.observe("RPM", 800, _at(0))
        producer.observe("RPM", 900, _at(60))
        producer.observe("BATTERY_V", 14.0, _at(61))

        assert producer.resultFor("BATTERY_V") == bp.BandResult(None, "engine_not_running")

    def test_batteryBeforeItsSameTsRpm_isRePaired(self) -> None:
        """
        Given: running, then BATTERY_V 14.0 arrives BEFORE an RPM 300 with the same ts
        When: the RPM arrives
        Then: the battery is re-evaluated on event ts -- engine_not_running
        """
        producer = _producer()
        _running(producer, 0, 20)
        producer.observe("BATTERY_V", 14.0, _at(21.0))
        assert _band(producer, "BATTERY_V") == "green"

        producer.observe("RPM", 300, _at(21.0))

        assert producer.resultFor("BATTERY_V") == bp.BandResult(None, "engine_not_running")

    def test_engineOff_noRpmEver(self) -> None:
        """
        Given: BATTERY_V 12.4 and no RPM ever
        When: classified
        Then: band null, engine_not_running
        """
        producer = _producer()
        producer.observe("BATTERY_V", 12.4, _at(0))

        assert producer.resultFor("BATTERY_V") == bp.BandResult(None, "engine_not_running")

    @pytest.mark.parametrize(
        ("volts", "expected"),
        [
            (11.99, "red"),
            (12.0, None),
            (13.49, None),
            (13.5, "green"),
            (14.5, "green"),
            (14.51, None),
            (15.0, None),
            (15.01, "red"),
        ],
    )
    def test_runningEdges_greenOwnsBothEdges(self, volts: float, expected: str | None) -> None:
        """
        Given: the engine running
        When: BATTERY_V sits on or beside each edge
        Then: green owns 13.5 and 14.5; red is strictly outside 12.0 / 15.0;
              everything else is amber_not_shipped
        """
        producer = _producer()
        _running(producer, 0, 20)
        producer.observe("BATTERY_V", volts, _at(20.4))

        result = producer.resultFor("BATTERY_V")
        assert _band(producer, "BATTERY_V") == expected
        if expected is None:
            assert result.noBandReason == "amber_not_shipped"

    def test_runningRpmMin_isTheConfigKey(self) -> None:
        """
        Given: pi.bands.battery.runningRpmMin 900
        When: the engine idles at 800 with BATTERY_V 14.0
        Then: not banded -- the gate reads config
        """
        producer = _producer({"pi": {"bands": {"battery": {"runningRpmMin": 900}}}})
        _running(producer, 0, 20, rpm=800)
        producer.observe("BATTERY_V", 14.0, _at(20.4))

        assert producer.resultFor("BATTERY_V") == bp.BandResult(None, "engine_not_running")


# ==================================================================== RPM


class TestRpm:
    """Bar cues and the scale the bar draws from."""

    @pytest.mark.parametrize(
        ("rpm", "expected"),
        [(3200, "green"), (5499, "green"), (5500, "amber"), (6999, "amber"), (7000, "red")],
    )
    def test_rpmCues(self, rpm: float, expected: str) -> None:
        """
        Given: an RPM reading
        When: classified with the defaults
        Then: amber from 5500, red from 7000
        """
        producer = _producer()
        producer.observe("RPM", rpm, _at(0))

        assert _band(producer, "RPM") == expected

    def test_scale_defaults(self) -> None:
        """
        Given: the defaults
        When: the scale is read
        Then: {amberFrom: 5500, redFrom: 7000}
        """
        assert _producer().rpmScale == {"amberFrom": 5500, "redFrom": 7000}

    def test_scaleAndBand_followTheSameKeys(self) -> None:
        """
        Given: pi.bands.rpm.amberRpm 4000 and redRpm 6000
        When: RPM 4500 is classified and the scale is read
        Then: amber, and scale {amberFrom: 4000, redFrom: 6000}
        """
        producer = _producer({"pi": {"bands": {"rpm": {"amberRpm": 4000, "redRpm": 6000}}}})
        producer.observe("RPM", 4500, _at(0))

        assert _band(producer, "RPM") == "amber"
        assert producer.rpmScale == {"amberFrom": 4000, "redFrom": 6000}


# =========================================================== no band defined


@pytest.mark.parametrize(
    "pid",
    ["INTAKE_TEMP", "SHORT_FUEL_TRIM_1", "LONG_FUEL_TRIM_1", "TIMING_ADVANCE", "ENGINE_LOAD"],
)
def test_unbandedPids_alwaysNoBandDefined(pid: str) -> None:
    """
    Given: a reading of a PID with no live band
    When: classified
    Then: band null, no_band_defined
    """
    producer = _producer()
    producer.observe(pid, 99, _at(0))

    assert producer.resultFor(pid) == bp.BandResult(None, "no_band_defined")


def test_noBandReasonVocabulary_isTheFiveCodes() -> None:
    """The machine codes Atlas ruled 2026-10-13 on Iris S-5, and no others."""
    assert set(bp.NO_BAND_REASONS) == {
        "not_read", "stale", "no_band_defined", "engine_not_running", "amber_not_shipped",
    }
