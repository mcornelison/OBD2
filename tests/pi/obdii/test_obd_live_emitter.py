################################################################################
# File Name: test_obd_live_emitter.py
# Purpose/Description: US-874 -- states/obd-live: every live PID with its value,
#   unit, own event time and a band (null until US-875). Pins the pure builder's
#   three per-PID shapes (fresh / stale / never read = absent), the conversion of
#   the reading's NAIVE LOCAL timestamp to canonical UTC, the file-level
#   dataSource taken from the logger's own resolved tag, the path from the real
#   _handleReading seam to the file, and the contract fixture.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-13    | Rex (US-874) | Initial -- obd-live producer and fixture.
# 2026-10-14    | Rex (US-875) | Bands: noBandReason beside a null band, RPM
#                                scale, fixture cases rebuilt through the tracker.
# 2026-10-15    | Rex (US-888-b) | Canonical units: measured python-obd names in,
#                                C/km/h/V/rpm out. PIN CHANGE: the fixture
#                                builder-equality test now feeds each fixture
#                                unit as its python-obd name (inverse map).
# 2026-10-15    | Rex (US-890-b) | params.MAF.scale {max} from
#                                pi.display.scale.mafMaxGs (default 160).
# 2026-10-15    | Rex (US-890-c) | The fuel block {loop, totalTrimNow}. PIN
#                                CHANGES: _TOP_LEVEL_KEYS gains 'fuel'; the two
#                                exact-state asserts (fresh shape, empty params)
#                                gain the not-read fuel block. The fixture
#                                builder-equality test itself is unchanged.
# ================================================================================
################################################################################

"""US-874: the states/obd-live producer, from the reading seam to tmpfs."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from pi.obdii import obd_live_emitter as ole
from pi.obdii import units
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.obdii.orchestrator.event_router import EventRouterMixin
from tests.pi.obdii.test_units import MEASURED_TO_CANONICAL

_ZONE_CONFIG = {"pi": {"time": {"localZone": "America/Chicago"}}}
_PID_KEYS = {"value", "unit", "ts", "stale", "band", "last"}
_OPTIONAL_PID_KEYS = {"noBandReason", "scale"}
# US-890-c PIN CHANGE: the top level gains the fuel block {loop, totalTrimNow}.
_TOP_LEVEL_KEYS = {"params", "fuel", "dataSource", "ts"}

# The fuel block while no fuel trim has been read (US-890-c).
_FUEL_NOT_READ = {
    "loop": None,
    "totalTrimNow": {"value": None, "unit": "%", "ts": None, "reason": "not_read"},
}

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "ui" / "fixtures" / "states" / "obd-live.json"
)


def _obs(value: Any, unit: str | None, ts: str) -> ole.ObdLiveObservation:
    return ole.ObdLiveObservation(value=value, unit=unit, ts=ts)


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


class _Reading:
    """The shape RealtimeDataLogger hands the reading callback (LoggedReading)."""

    def __init__(
        self, parameterName: str, value: Any, timestamp: Any, unit: str | None = None
    ) -> None:
        self.parameterName = parameterName
        self.value = value
        self.unit = unit
        self.timestamp = timestamp


class _UtcClock:
    """A wall clock the test advances by hand (aware UTC)."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


# ================================================================ pure builder


class TestBuildObdLiveState:
    """The three per-PID shapes, decided at emit time against the stale window."""

    def test_freshReading_publishesValueUnitTsAndNullBand(self) -> None:
        """
        Given: SPEED 40 read at 12:05:01Z (no band rule)
        When: the state is built at 12:05:03Z with a 5 s window
        Then: the fresh shape -- value 40, stale false, band null with
              noBandReason no_band_defined, last null
        """
        state = ole.buildObdLiveState(
            {"SPEED": _obs(40, "km/h", "2026-10-13T12:05:01Z")},
            nowUtc=_utc("2026-10-13T12:05:03Z"),
            staleSec=5.0,
            dataSource="real",
        )

        assert state == {
            "params": {
                "SPEED": {
                    "value": 40, "unit": "km/h", "ts": "2026-10-13T12:05:01Z",
                    "stale": False, "band": None, "noBandReason": "no_band_defined",
                    "last": None,
                }
            },
            "fuel": _FUEL_NOT_READ,
            "dataSource": "real",
            "ts": "2026-10-13T12:05:03Z",
        }

    def test_staleReading_neverPublishesTheOldValueAsCurrent(self) -> None:
        """
        Given: COOLANT_TEMP 88 read at 12:04:55Z
        When: built at 12:05:03Z (8 s later, window 5 s)
        Then: value null, ts of the last reading, stale true, band null with
              noBandReason stale, last {value: 88, band: <the frozen band>}
        """
        green = {"band": "green", "since": "2026-10-13T12:04:55Z", "reason": "r"}
        state = ole.buildObdLiveState(
            {"COOLANT_TEMP": ole.ObdLiveObservation(88, "C", "2026-10-13T12:04:55Z", green)},
            nowUtc=_utc("2026-10-13T12:05:03Z"),
            staleSec=5.0,
            dataSource="real",
        )

        assert state["params"]["COOLANT_TEMP"] == {
            "value": None, "unit": "C", "ts": "2026-10-13T12:04:55Z",
            "stale": True, "band": None, "noBandReason": "stale",
            "last": {"value": 88, "band": green},
        }

    def test_ageExactlyAtTheWindow_isStillFresh(self) -> None:
        """
        Given: a reading exactly staleSec old
        When: built
        Then: fresh -- the rule is age > window, not >=
        """
        state = ole.buildObdLiveState(
            {"SPEED": _obs(40, "km/h", "2026-10-13T12:00:00Z")},
            nowUtc=_utc("2026-10-13T12:00:05Z"),
            staleSec=5.0,
            dataSource="real",
        )

        assert state["params"]["SPEED"]["stale"] is False
        assert state["params"]["SPEED"]["value"] == 40

    def test_staleWindow_isTheArgumentNotALiteral(self) -> None:
        """
        Given: a reading 3 s old
        When: built with a 2 s window
        Then: stale -- the window comes from the caller (config), not the module
        """
        state = ole.buildObdLiveState(
            {"SPEED": _obs(40, "km/h", "2026-10-13T12:00:00Z")},
            nowUtc=_utc("2026-10-13T12:00:03Z"),
            staleSec=2.0,
            dataSource="real",
        )

        assert state["params"]["SPEED"]["stale"] is True

    def test_noObservations_publishesEmptyParams(self) -> None:
        """
        Given: nothing read this process
        When: built
        Then: params is empty -- a PID never read is ABSENT, not 0 or null
        """
        state = ole.buildObdLiveState(
            {}, nowUtc=_utc("2026-10-13T12:00:00Z"), staleSec=5.0, dataSource=None
        )

        assert state == {
            "params": {}, "fuel": _FUEL_NOT_READ, "dataSource": None,
            "ts": "2026-10-13T12:00:00Z",
        }

    def test_noBandReason_presentExactlyWhenBandIsNull(self) -> None:
        """
        Given: one banded fresh PID, one unbanded fresh PID, one banded stale PID
        When: built
        Then: noBandReason is ABSENT beside a band and present beside every null
              band; a stale band never outlives its value
        """
        green = {"band": "green", "since": "2026-10-13T12:00:09Z", "reason": "r"}
        state = ole.buildObdLiveState(
            {
                "RPM": ole.ObdLiveObservation(812, "rpm", "2026-10-13T12:00:09Z", green),
                "SPEED": _obs(0, "km/h", "2026-10-13T12:00:09Z"),
                "COOLANT_TEMP": ole.ObdLiveObservation(88, "C", "2026-10-13T12:00:00Z", green),
            },
            nowUtc=_utc("2026-10-13T12:00:10Z"),
            staleSec=5.0,
            dataSource="real",
        )

        params = state["params"]
        assert params["RPM"]["band"] == green
        assert "noBandReason" not in params["RPM"]
        assert params["SPEED"]["noBandReason"] == "no_band_defined"
        assert params["COOLANT_TEMP"]["band"] is None
        assert params["COOLANT_TEMP"]["noBandReason"] == "stale"

    def test_bandIsNullWheneverValueIsNull(self) -> None:
        """
        Given: an observation carrying a band but a null value
        When: built fresh
        Then: band null, noBandReason not_read -- a band never outlives its value
        """
        green = {"band": "green", "since": "2026-10-13T12:00:09Z", "reason": "r"}
        state = ole.buildObdLiveState(
            {"RPM": ole.ObdLiveObservation(None, "rpm", "2026-10-13T12:00:09Z", green)},
            nowUtc=_utc("2026-10-13T12:00:10Z"),
            staleSec=5.0,
            dataSource="real",
        )

        assert state["params"]["RPM"]["band"] is None
        assert state["params"]["RPM"]["noBandReason"] == "not_read"

    def test_scale_isPublishedEvenWhenStale(self) -> None:
        """
        Given: an RPM observation carrying a scale, stale
        When: built
        Then: scale is still published -- the bar zones do not depend on a reading
        """
        scale = {"amberFrom": 5500.0, "redFrom": 7000.0}
        state = ole.buildObdLiveState(
            {"RPM": ole.ObdLiveObservation(812, "rpm", "2026-10-13T12:00:00Z", scale=scale)},
            nowUtc=_utc("2026-10-13T12:00:10Z"),
            staleSec=5.0,
            dataSource="real",
        )

        assert state["params"]["RPM"]["scale"] == scale


# ============================================================ the fuel block


def _fuel(
    observations: dict[str, ole.ObdLiveObservation], now: str = "2026-10-20T12:00:03Z",
    staleSec: float = 5.0,
) -> dict[str, Any]:
    fuel: dict[str, Any] = ole.buildObdLiveState(
        observations, nowUtc=_utc(now), staleSec=staleSec, dataSource="real"
    )["fuel"]
    return fuel


def _fss(code: Any, ts: str = "2026-10-20T12:00:02Z") -> ole.ObdLiveObservation:
    return _obs(code, "CL", ts)


def _ltft(value: Any, ts: str = "2026-10-20T12:00:01Z") -> ole.ObdLiveObservation:
    return _obs(value, "%", ts)


def _stft(value: Any, ts: str = "2026-10-20T12:00:02Z") -> ole.ObdLiveObservation:
    return _obs(value, "%", ts)


class TestFuelBlock:
    """US-890-c (Atlas S104 ruling (b)): fuel {loop, totalTrimNow} from the
    SAME observations as params, through the ONE closed-loop code set."""

    def test_closedLoop_totalTrimNow_isTheUnroundedSum_atTheOlderTs(self) -> None:
        """
        Given: FUEL_SYSTEM_STATUS 5, LTFT -1.6 at 12:00:01, STFT 3.1 at 12:00:02
        When: built at 12:00:03
        Then: loop closed; totalTrimNow {value -1.6 + 3.1 (unrounded), unit %,
              ts 12:00:01Z (the OLDER input), reason null}
        """
        fuel = _fuel({
            "FUEL_SYSTEM_STATUS": _fss(5),
            "LONG_FUEL_TRIM_1": _ltft(-1.6),
            "SHORT_FUEL_TRIM_1": _stft(3.1),
        })

        assert fuel == {
            "loop": "closed",
            "totalTrimNow": {
                "value": -1.6 + 3.1, "unit": "%", "ts": "2026-10-20T12:00:01Z", "reason": None,
            },
        }
        assert fuel["totalTrimNow"]["value"] == pytest.approx(1.5)

    def test_tsIsTheOlderInput_whicheverTrimItIs(self) -> None:
        fuel = _fuel({
            "FUEL_SYSTEM_STATUS": _fss(2),
            "LONG_FUEL_TRIM_1": _ltft(1.0, "2026-10-20T12:00:02Z"),
            "SHORT_FUEL_TRIM_1": _stft(0.5, "2026-10-20T11:59:59Z"),
        })

        assert fuel["totalTrimNow"]["ts"] == "2026-10-20T11:59:59Z"

    def test_code3_isOpen_andTheTrimIsNotApplied(self) -> None:
        """
        Given: FUEL_SYSTEM_STATUS 3 (OL-drive), both trims fresh
        When: built
        Then: loop open; totalTrimNow reason open_loop, value null, ts kept
        """
        fuel = _fuel({
            "FUEL_SYSTEM_STATUS": _fss(3.0),
            "LONG_FUEL_TRIM_1": _ltft(-1.6),
            "SHORT_FUEL_TRIM_1": _stft(3.1),
        })

        assert fuel == {
            "loop": "open",
            "totalTrimNow": {
                "value": None, "unit": "%", "ts": "2026-10-20T12:00:01Z", "reason": "open_loop",
            },
        }

    def test_code5_isClosed_code2FloatIsClosed(self) -> None:
        assert _fuel({"FUEL_SYSTEM_STATUS": _fss(5)})["loop"] == "closed"
        assert _fuel({"FUEL_SYSTEM_STATUS": _fss(2.0)})["loop"] == "closed"

    def test_stftNeverRead_isNotRead_beforeStaleAndLoop(self) -> None:
        """
        Given: STFT never read; LTFT stale; FUEL_SYSTEM_STATUS never read
        When: built
        Then: reason not_read -- it precedes stale and loop_unknown; ts null
        """
        fuel = _fuel({"LONG_FUEL_TRIM_1": _ltft(-1.6, "2026-10-20T11:59:00Z")})

        assert fuel == {
            "loop": None,
            "totalTrimNow": {"value": None, "unit": "%", "ts": None, "reason": "not_read"},
        }

    def test_ltftNeverRead_isNotRead(self) -> None:
        fuel = _fuel({"FUEL_SYSTEM_STATUS": _fss(2), "SHORT_FUEL_TRIM_1": _stft(3.1)})

        assert fuel["loop"] == "closed"
        assert fuel["totalTrimNow"]["reason"] == "not_read"
        assert fuel["totalTrimNow"]["value"] is None

    def test_aStaleTrim_isStale_beforeLoopUnknownAndOpenLoop(self) -> None:
        """
        Given: LTFT 6 s old (window 5 s), STFT fresh, loop open
        When: built
        Then: reason stale, value null, ts the older (stale) input's
        """
        fuel = _fuel({
            "FUEL_SYSTEM_STATUS": _fss(3),
            "LONG_FUEL_TRIM_1": _ltft(-1.6, "2026-10-20T11:59:57Z"),
            "SHORT_FUEL_TRIM_1": _stft(3.1),
        })

        assert fuel["totalTrimNow"] == {
            "value": None, "unit": "%", "ts": "2026-10-20T11:59:57Z", "reason": "stale",
        }

    def test_staleTrim_usesTheSameWindowArgument(self) -> None:
        """A 2 s-old trim is fresh at 5 s and stale at 1 s: the params window."""
        observations = {
            "FUEL_SYSTEM_STATUS": _fss(2, "2026-10-20T12:00:03Z"),
            "LONG_FUEL_TRIM_1": _ltft(1.0),
            "SHORT_FUEL_TRIM_1": _stft(1.0, "2026-10-20T12:00:03Z"),
        }

        assert _fuel(observations, staleSec=5.0)["totalTrimNow"]["reason"] is None
        assert _fuel(observations, staleSec=1.0)["totalTrimNow"]["reason"] == "stale"

    def test_statusStale_trimsFresh_isLoopUnknown(self) -> None:
        """
        Given: FUEL_SYSTEM_STATUS 2 read 8 s ago, both trims fresh
        When: built
        Then: loop null; totalTrimNow reason loop_unknown, value null
        """
        fuel = _fuel({
            "FUEL_SYSTEM_STATUS": _fss(2, "2026-10-20T11:59:55Z"),
            "LONG_FUEL_TRIM_1": _ltft(-1.6),
            "SHORT_FUEL_TRIM_1": _stft(3.1),
        })

        assert fuel["loop"] is None
        assert fuel["totalTrimNow"] == {
            "value": None, "unit": "%", "ts": "2026-10-20T12:00:01Z", "reason": "loop_unknown",
        }

    def test_statusNeverRead_isLoopUnknown(self) -> None:
        fuel = _fuel({"LONG_FUEL_TRIM_1": _ltft(-1.6), "SHORT_FUEL_TRIM_1": _stft(3.1)})

        assert fuel["loop"] is None
        assert fuel["totalTrimNow"]["reason"] == "loop_unknown"

    def test_statusNotACode_isLoopUnknown_neverOpen(self) -> None:
        fuel = _fuel({
            "FUEL_SYSTEM_STATUS": _fss("CL"),
            "LONG_FUEL_TRIM_1": _ltft(-1.6),
            "SHORT_FUEL_TRIM_1": _stft(3.1),
        })

        assert fuel["loop"] is None
        assert fuel["totalTrimNow"]["reason"] == "loop_unknown"

    def test_totalTrimNow_isUnbanded(self) -> None:
        """No band, no noBandReason: exactly {value, unit, ts, reason}."""
        fuel = _fuel({
            "FUEL_SYSTEM_STATUS": _fss(2),
            "LONG_FUEL_TRIM_1": _ltft(9.0),
            "SHORT_FUEL_TRIM_1": _stft(9.0),
        })

        assert set(fuel) == {"loop", "totalTrimNow"}
        assert set(fuel["totalTrimNow"]) == {"value", "unit", "ts", "reason"}

    def test_paramsAreUnchangedByTheFuelBlock(self) -> None:
        """The trims and the status still publish as ordinary params entries."""
        state = ole.buildObdLiveState(
            {"FUEL_SYSTEM_STATUS": _fss(2), "LONG_FUEL_TRIM_1": _ltft(-1.6)},
            nowUtc=_utc("2026-10-20T12:00:03Z"), staleSec=5.0, dataSource="real",
        )

        assert state["params"]["LONG_FUEL_TRIM_1"]["value"] == -1.6
        assert state["params"]["FUEL_SYSTEM_STATUS"]["value"] == 2
        assert "totalTrimNow" not in state["params"]


# ===================================================================== tracker


class TestObdLiveTracker:
    """Every PID observed this process, stamped with its own event time."""

    def test_observeReading_convertsNaiveLocalTimestampToCanonicalUtc(self) -> None:
        """
        Given: America/Chicago declared, an RPM reading stamped 12:00:00 local (CDT)
        When: observed
        Then: its ts is 17:00:00Z -- not the local wall time
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)

        tracker.observeReading(_Reading("RPM", 812.0, datetime(2026, 10, 13, 12, 0, 0), "rpm"))

        obs = tracker.snapshot()["RPM"]
        assert (obs.value, obs.unit, obs.ts) == (812.0, "rpm", "2026-10-13T17:00:00Z")

    def test_observeReading_coolantInDegreeCelsius_publishesC(self, tmp_path) -> None:
        """
        Given: COOLANT_TEMP 88 carrying python-obd's MEASURED 'degree_Celsius'
        When: observed and built
        Then: params.COOLANT_TEMP.unit is 'C' (US-888-b)
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)

        tracker.observeReading(
            _Reading("COOLANT_TEMP", 88, datetime(2026, 10, 13, 12, 0, 0), "degree_Celsius")
        )
        built = ole.buildObdLiveState(
            tracker.snapshot(),
            nowUtc=_utc("2026-10-13T17:00:01Z"),
            staleSec=ole.DEFAULT_OBD_LIVE_STALE_S,
            dataSource="real",
        )

        assert built["params"]["COOLANT_TEMP"]["unit"] == "C"

    @pytest.mark.parametrize(("raw", "canonical"), MEASURED_TO_CANONICAL)
    def test_observeReading_measuredUnit_isStoredCanonical(self, raw: str, canonical: str) -> None:
        """
        Given: a reading carrying a MEASURED python-obd unit name
        When: observed
        Then: the stored observation holds the canonical short unit
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)

        tracker.observeReading(_Reading("PID", 1.0, datetime(2026, 10, 13, 12, 0, 0), raw))

        assert tracker.snapshot()["PID"].unit == canonical

    def test_observeReading_statusLabels_unchanged_andWarnOncePerString(self, caplog) -> None:
        """
        Given: FUEL_SYSTEM_STATUS 'OL-drive' and MIL_ON 'ON', each read three times
        When: observed
        Then: units unchanged; one WARN per distinct string, not per reading
        """
        units._warnedUnits.clear()
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)

        with caplog.at_level(logging.WARNING, logger=units.logger.name):
            for second in range(3):
                at = datetime(2026, 10, 13, 12, 0, second)
                tracker.observeReading(_Reading("FUEL_SYSTEM_STATUS", 4, at, "OL-drive"))
                tracker.observeReading(_Reading("MIL_ON", 1, at, "ON"))

        snap = tracker.snapshot()
        assert (snap["FUEL_SYSTEM_STATUS"].unit, snap["MIL_ON"].unit) == ("OL-drive", "ON")
        warned = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warned) == 2

    def test_observeReading_keepsOnlyTheLatestPerPid(self) -> None:
        """
        Given: two RPM readings and one SPEED reading
        When: observed
        Then: one entry per PID, holding the newest reading
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)
        t = datetime(2026, 10, 13, 12, 0, 0)

        tracker.observeReading(_Reading("RPM", 800.0, t, "rpm"))
        tracker.observeReading(_Reading("SPEED", 0.0, t, "km/h"))
        tracker.observeReading(_Reading("RPM", 900.0, t + timedelta(seconds=2), "rpm"))

        snap = tracker.snapshot()
        assert set(snap) == {"RPM", "SPEED"}
        assert (snap["RPM"].value, snap["RPM"].ts) == (900.0, "2026-10-13T17:00:02Z")

    def test_snapshot_carriesTheBandProducersResult(self) -> None:
        """
        Given: RPM 812, SPEED 0 and BATTERY_V 12.4 at the same instant
        When: snapshotted
        Then: RPM green with scale; SPEED no_band_defined without scale;
              BATTERY_V engine_not_running (inside the first RPM's crank guard)
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)
        t = datetime(2026, 10, 13, 12, 0, 0)

        tracker.observeReading(_Reading("RPM", 812.0, t, "rpm"))
        tracker.observeReading(_Reading("SPEED", 0.0, t, "km/h"))
        tracker.observeReading(_Reading("BATTERY_V", 12.4, t, "V"))

        snap = tracker.snapshot()
        assert snap["RPM"].band == {
            "band": "green", "since": "2026-10-13T17:00:00Z", "reason": "rpm below 5500",
        }
        assert snap["RPM"].scale == {"amberFrom": 5500.0, "redFrom": 7000.0}
        assert snap["SPEED"].band is None
        assert snap["SPEED"].noBandReason == "no_band_defined"
        assert snap["SPEED"].scale is None
        assert snap["BATTERY_V"].noBandReason == "engine_not_running"

    def test_scale_followsTheRpmKeys(self) -> None:
        """
        Given: pi.bands.rpm.amberRpm 4000 and redRpm 6000
        When: an RPM is snapshotted
        Then: params.RPM.scale is {4000, 6000} -- read from config, not literals
        """
        config = {"pi": {
            "time": {"localZone": "America/Chicago"},
            "bands": {"rpm": {"amberRpm": 4000, "redRpm": 6000}},
        }}
        tracker = ole.ObdLiveTracker(config)

        tracker.observeReading(_Reading("RPM", 812.0, datetime(2026, 10, 13, 12), "rpm"))

        assert tracker.snapshot()["RPM"].scale == {"amberFrom": 4000.0, "redFrom": 6000.0}

    def test_mafScale_defaultsToTheValidatorDefault(self) -> None:
        """
        Given: no pi.display.scale key (US-890-b)
        When: a MAF reading is snapshotted
        Then: params.MAF.scale is {max: 160.0} -- the validator DEFAULT (Spool)
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)

        tracker.observeReading(_Reading("MAF", 16.24, datetime(2026, 10, 13, 12), "gps"))

        assert tracker.snapshot()["MAF"].scale == {"max": 160.0}

    def test_mafScale_followsTheConfigKey(self) -> None:
        """
        Given: pi.display.scale.mafMaxGs 150
        When: a MAF reading is snapshotted
        Then: params.MAF.scale is {max: 150.0} -- read from config, not a literal
        """
        config = {"pi": {
            "time": {"localZone": "America/Chicago"},
            "display": {"scale": {"mafMaxGs": 150}},
        }}
        tracker = ole.ObdLiveTracker(config)

        tracker.observeReading(_Reading("MAF", 158.69, datetime(2026, 10, 13, 12), "gps"))

        assert tracker.snapshot()["MAF"].scale == {"max": 150.0}

    def test_mafScale_leavesRpmAndEveryOtherPidAlone(self) -> None:
        """
        Given: RPM, MAF and SPEED read, pi.display.scale.mafMaxGs 150
        When: snapshotted
        Then: RPM keeps its {amberFrom, redFrom}; SPEED carries no scale
        """
        config = {"pi": {
            "time": {"localZone": "America/Chicago"},
            "display": {"scale": {"mafMaxGs": 150}},
        }}
        tracker = ole.ObdLiveTracker(config)
        t = datetime(2026, 10, 13, 12)

        tracker.observeReading(_Reading("RPM", 812.0, t, "rpm"))
        tracker.observeReading(_Reading("MAF", 4.1, t, "gps"))
        tracker.observeReading(_Reading("SPEED", 0.0, t, "km/h"))

        snap = tracker.snapshot()
        assert snap["RPM"].scale == {"amberFrom": 5500.0, "redFrom": 7000.0}
        assert snap["MAF"].scale == {"max": 150.0}
        assert snap["SPEED"].scale is None

    def test_mafScale_isPublished_freshAndStale(self) -> None:
        """
        Given: a MAF reading at 12:00:00 local (17:00:00Z)
        When: built 1 s later (fresh) and 6 s later (stale)
        Then: params.MAF carries scale {max: 160.0} both times, beside the
              unclamped value or last.value -- the scale never depends on a reading
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)
        tracker.observeReading(_Reading("MAF", 158.69, datetime(2026, 10, 13, 12), "gps"))
        snap = tracker.snapshot()

        fresh = ole.buildObdLiveState(
            snap, nowUtc=_utc("2026-10-13T17:00:01Z"), staleSec=5.0, dataSource="real"
        )["params"]["MAF"]
        stale = ole.buildObdLiveState(
            snap, nowUtc=_utc("2026-10-13T17:00:06Z"), staleSec=5.0, dataSource="real"
        )["params"]["MAF"]

        assert fresh["value"] == 158.69
        assert fresh["unit"] == "g/s"
        assert fresh["scale"] == {"max": 160.0}
        assert stale["value"] is None
        assert stale["last"]["value"] == 158.69
        assert stale["scale"] == {"max": 160.0}
        assert set(fresh) <= _PID_KEYS | _OPTIONAL_PID_KEYS

    def test_nullReading_resetsTheDwellButIsNotRecorded(self) -> None:
        """
        Given: coolant 105 C for 20 s, a null reading, then 105 C for 20 s more
        When: snapshotted
        Then: the null is not recorded as a value, and the band is still green
              (the null gap reset the dwell)
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)
        t = datetime(2026, 10, 13, 12, 0, 0)
        for i in range(21):
            tracker.observeReading(_Reading("COOLANT_TEMP", 105.0, t + timedelta(seconds=i), "C"))
        tracker.observeReading(_Reading("COOLANT_TEMP", None, t + timedelta(seconds=21), "C"))
        for i in range(22, 43):
            tracker.observeReading(_Reading("COOLANT_TEMP", 105.0, t + timedelta(seconds=i), "C"))

        obs = tracker.snapshot()["COOLANT_TEMP"]
        assert obs.value == 105.0
        assert obs.band is not None and obs.band["band"] == "green"

    def test_readingWithoutTimestamp_isNotObserved(self) -> None:
        """
        Given: a reading with no capture timestamp
        When: observed
        Then: nothing is recorded -- the write time is never substituted
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)

        tracker.observeReading(_Reading("RPM", 812.0, None, "rpm"))

        assert tracker.snapshot() == {}

    def test_readingWithNoValue_isNotObserved(self) -> None:
        """
        Given: a reading whose value is None
        When: observed
        Then: nothing is recorded -- null means not read, so it cannot be a reading
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)

        tracker.observeReading(_Reading("RPM", None, datetime(2026, 10, 13, 12), "rpm"))

        assert tracker.snapshot() == {}

    def test_snapshot_isACopy(self) -> None:
        """
        Given: a snapshot taken
        When: a later reading arrives
        Then: the earlier snapshot is unchanged (the emit tick reads a stable view)
        """
        tracker = ole.ObdLiveTracker(_ZONE_CONFIG)
        tracker.observeReading(_Reading("RPM", 800.0, datetime(2026, 10, 13, 12), "rpm"))
        snap = tracker.snapshot()

        tracker.observeReading(_Reading("SPEED", 5.0, datetime(2026, 10, 13, 12), "km/h"))

        assert set(snap) == {"RPM"}


# ================================================================= the emitter


def test_makeObdLiveEmitter_writesTheStateFileAtomically(tmp_path) -> None:
    """
    Given: an emitter over a tmp states dir
    When: it emits one observation
    Then: states/obd-live holds the built payload
    """
    statesDir = str(tmp_path / "states")
    emit = ole.makeObdLiveEmitter(statesDir)

    emit(
        {"RPM": _obs(812, "rpm", "2026-10-13T12:05:01Z")},
        nowUtc=_utc("2026-10-13T12:05:03Z"),
        staleSec=5.0,
        dataSource="real",
    )

    with open(os.path.join(statesDir, ole.OBD_LIVE_STATE_FILENAME), encoding="utf-8") as fh:
        written = json.load(fh)
    assert written["params"]["RPM"]["value"] == 812
    assert set(written) == _TOP_LEVEL_KEYS


def test_makeObdLiveEmitter_neverRaisesOnAWriteFailure(tmp_path, monkeypatch) -> None:
    """
    Given: the atomic writer raises
    When: the emitter is called
    Then: it logs and returns -- the orchestrator loop is never crashed
    """
    import pi.splash.boot_state_emitter as bse

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("tmpfs full")

    monkeypatch.setattr(bse, "writeStateAtomic", boom)
    emit = ole.makeObdLiveEmitter(str(tmp_path / "states"))

    emit({}, nowUtc=_utc("2026-10-13T12:00:00Z"), staleSec=5.0, dataSource="real")


# ======================================================= through the real seam


class _DataLogger:
    """ObdDataLogger stand-in: only the resolved tag the emitter reads."""

    def __init__(self, dataSource: str) -> None:
        self.dataSource = dataSource


class _RealtimeLogger:
    """RealtimeDataLogger stand-in: exposes the inner writer as ``dataLogger``."""

    def __init__(self, dataSource: str) -> None:
        self.dataLogger = _DataLogger(dataSource)


class _Orch(EventRouterMixin, CardStateEmitterMixin):
    """The two REAL mixins; the reading arrives at the production callback."""

    def __init__(
        self, statesDir: str, clock: _UtcClock, *, staleSec: float | None = None,
        dataSource: str | None = "real",
    ) -> None:
        display: dict[str, Any] = {}
        if staleSec is not None:
            display = {"stale": {"obdLiveSec": staleSec}}
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
                "display": display,
                "time": {"localZone": "America/Chicago"},
                "gear": {"enabled": False},
                "captureHealth": {"enabled": False},
            }
        }
        self._obdLiveClock = clock
        self._dataLogger = None if dataSource is None else _RealtimeLogger(dataSource)
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
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0
        self._initializeCardStateEmitters()


def _readObdLive(statesDir: str) -> dict:
    with open(os.path.join(statesDir, ole.OBD_LIVE_STATE_FILENAME), encoding="utf-8") as fh:
        return json.load(fh)


# 12:00:00 America/Chicago in October is CDT (UTC-5) -> 17:00:00Z.
_T_LOCAL = datetime(2026, 10, 13, 12, 0, 0)
_T_UTC = datetime(2026, 10, 13, 17, 0, 0, tzinfo=UTC)


class TestThroughTheReadingSeam:
    """Readings arriving at _handleReading reach states/obd-live."""

    def test_eachPidCarriesItsOwnEventTime(self, tmp_path) -> None:
        """
        Given: RPM read at t and SPEED at t+1 through _handleReading
        When: the card tick emits
        Then: params.RPM.ts = t, params.SPEED.ts = t+1; RPM banded, SPEED not
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(statesDir, _UtcClock(_T_UTC + timedelta(seconds=2)))

        orch._handleReading(_Reading("RPM", 812.0, _T_LOCAL, "rpm"))
        orch._handleReading(_Reading("SPEED", 40.0, _T_LOCAL + timedelta(seconds=1), "km/h"))
        orch._maybeEmitCardStates()

        params = _readObdLive(statesDir)["params"]
        assert params["RPM"]["ts"] == "2026-10-13T17:00:00Z"
        assert params["SPEED"]["ts"] == "2026-10-13T17:00:01Z"
        assert params["RPM"]["band"]["band"] == "green"
        assert params["RPM"]["scale"] == {"amberFrom": 5500, "redFrom": 7000}
        assert params["SPEED"]["band"] is None
        assert params["SPEED"]["noBandReason"] == "no_band_defined"

    def test_aReadingSixSecondsOld_isPublishedStale(self, tmp_path) -> None:
        """
        Given: COOLANT_TEMP 85 at t, default window
        When: emitted at t+6 s with no further reading
        Then: {value: null, ts: t, stale: true, band: null, noBandReason: stale,
              last: {value: 85, band: <green, frozen at t>}}
        """
        statesDir = str(tmp_path / "states")
        clock = _UtcClock(_T_UTC)
        orch = _Orch(statesDir, clock)

        orch._handleReading(_Reading("COOLANT_TEMP", 85.0, _T_LOCAL, "C"))
        clock.now = _T_UTC + timedelta(seconds=6)
        orch._maybeEmitCardStates()

        assert _readObdLive(statesDir)["params"]["COOLANT_TEMP"] == {
            "value": None, "unit": "C", "ts": "2026-10-13T17:00:00Z",
            "stale": True, "band": None, "noBandReason": "stale",
            "last": {"value": 85.0, "band": {
                "band": "green", "since": "2026-10-13T17:00:00Z",
                "reason": "coolant has not held >= 104 C for 30 s",
            }},
        }

    def test_staleWindow_isReadFromConfig(self, tmp_path) -> None:
        """
        Given: pi.display.stale.obdLiveSec = 10
        When: a reading is emitted 6 s old
        Then: still fresh -- the window is the config key
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(statesDir, _UtcClock(_T_UTC + timedelta(seconds=6)), staleSec=10.0)

        orch._handleReading(_Reading("COOLANT_TEMP", 85.0, _T_LOCAL, "C"))
        orch._maybeEmitCardStates()

        assert _readObdLive(statesDir)["params"]["COOLANT_TEMP"]["value"] == 85.0

    def test_aPidNeverReadIsAbsent(self, tmp_path) -> None:
        """
        Given: only RPM has been read
        When: emitted
        Then: params holds RPM alone
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(statesDir, _UtcClock(_T_UTC))

        orch._handleReading(_Reading("RPM", 812.0, _T_LOCAL, "rpm"))
        orch._maybeEmitCardStates()

        assert set(_readObdLive(statesDir)["params"]) == {"RPM"}

    @pytest.mark.parametrize("tag", ["real", "replay", "physics_sim"])
    def test_dataSource_isTheLoggersResolvedTag(self, tmp_path, tag: str) -> None:
        """
        Given: the data logger resolved its rows' data_source as <tag>
        When: emitted
        Then: obd-live.dataSource is that same tag, once, at file level
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(statesDir, _UtcClock(_T_UTC), dataSource=tag)

        orch._handleReading(_Reading("RPM", 812.0, _T_LOCAL, "rpm"))
        orch._maybeEmitCardStates()

        state = _readObdLive(statesDir)
        assert state["dataSource"] == tag
        assert "dataSource" not in state["params"]["RPM"]

    def test_fuelBlock_reachesTheFile_fromTheSeam(self, tmp_path) -> None:
        """
        Given: FUEL_SYSTEM_STATUS 2.0 ('CL'), LTFT -1.6 and STFT 3.1 ('percent')
              through _handleReading
        When: the card tick emits 2 s later
        Then: states/obd-live carries fuel {loop closed, totalTrimNow ~1.5 %}
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(statesDir, _UtcClock(_T_UTC + timedelta(seconds=2)))

        orch._handleReading(_Reading("FUEL_SYSTEM_STATUS", 2.0, _T_LOCAL, "CL"))
        orch._handleReading(_Reading("LONG_FUEL_TRIM_1", -1.6, _T_LOCAL, "percent"))
        orch._handleReading(
            _Reading("SHORT_FUEL_TRIM_1", 3.1, _T_LOCAL + timedelta(seconds=1), "percent")
        )
        orch._maybeEmitCardStates()

        fuel = _readObdLive(statesDir)["fuel"]
        assert fuel["loop"] == "closed"
        assert fuel["totalTrimNow"]["value"] == pytest.approx(1.5)
        assert fuel["totalTrimNow"]["ts"] == "2026-10-13T17:00:00Z"
        assert fuel["totalTrimNow"]["reason"] is None

    def test_noDataLogger_publishesNullDataSource(self, tmp_path) -> None:
        """
        Given: no data logger exists
        When: emitted
        Then: dataSource null -- never a guessed 'real'
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(statesDir, _UtcClock(_T_UTC), dataSource=None)

        orch._maybeEmitCardStates()

        assert _readObdLive(statesDir)["dataSource"] is None

    def test_cardsDisabled_writesNoFile(self, tmp_path) -> None:
        """
        Given: pi.dashboard.stateEmitEnabled false (no producer built)
        When: a reading arrives
        Then: no obd-live file and no error on the poll path
        """
        statesDir = str(tmp_path / "states")

        class _Off(_Orch):
            _cardStateEmitEnabled = False

            def _initializeCardStateEmitters(self) -> None:
                self._cardStateEmitEnabled = False
                super()._initializeCardStateEmitters()

        orch = _Off(statesDir, _UtcClock(_T_UTC))
        orch._handleReading(_Reading("RPM", 812.0, _T_LOCAL, "rpm"))
        orch._maybeEmitCardStates()

        assert not os.path.exists(os.path.join(statesDir, ole.OBD_LIVE_STATE_FILENAME))


# ================================================================ the fixture


class TestTheContractFixture:
    """tests/ui/fixtures/states/obd-live.json: named, complete payloads (Iris S-7)."""

    _CASES = (
        "fresh", "stale", "pid-absent", "replay",
        "engine-off-battery", "coolant-amber", "coolant-red",
    )

    # Readings fed BEFORE each case's own (published) readings -- the history a
    # dwell needs. Case -> [(PID, value, unit, canonical ts)].
    _HISTORY: dict[str, list[tuple[str, float, str, str]]] = {
        "coolant-amber": [
            ("COOLANT_TEMP", 105, "C", f"2026-10-13T12:10:{s:02d}Z") for s in range(30)
        ],
    }

    @staticmethod
    def _load() -> dict[str, Any]:
        with open(_FIXTURE_PATH, encoding="utf-8") as fh:
            return json.load(fh)

    def test_fixture_holdsTheNamedCases(self) -> None:
        """
        Given: the fixture file
        When: loaded
        Then: it is an object holding at least this story's four cases
        """
        assert set(self._CASES) <= set(self._load())

    def test_replayCase_carriesReplayDataSource(self) -> None:
        """
        Given: the replay case
        When: read
        Then: its file-level dataSource is 'replay'
        """
        assert self._load()["replay"]["dataSource"] == "replay"

    @pytest.mark.parametrize("case", _CASES)
    def test_fixture_everyCaseIsWhatTheBuilderEmits(self, case: str) -> None:
        """
        Given: one named case, a complete obd-live payload
        When: its history and its readings (fresh value or last.value, unit, ts)
              are fed in event order through a real ObdLiveTracker (default
              bands) and built at the case's ts with the default window -- each
              unit fed as the python-obd name the car reports (US-888-b)
        Then: the builder's output -- bands and canonical units included --
              equals the case exactly
        """
        payload = self._load()[case]
        assert set(payload) == _TOP_LEVEL_KEYS

        readings = list(self._HISTORY.get(case, []))
        for name, pid in payload["params"].items():
            assert _PID_KEYS <= set(pid) <= _PID_KEYS | _OPTIONAL_PID_KEYS
            value = pid["last"]["value"] if pid["stale"] else pid["value"]
            readings.append((name, value, pid["unit"], pid["ts"]))

        # US-888-b: feed what python-obd returns, not the target vocabulary.
        pythonObdName = {canonical: raw for raw, canonical in units.CANONICAL_UNITS.items()}
        tracker = ole.ObdLiveTracker({})
        for name, value, unit, ts in sorted(readings, key=lambda r: r[3]):
            assert unit in pythonObdName, f"fixture unit {unit!r} has no python-obd name"
            tracker.observeReading(_Reading(name, value, _utc(ts), pythonObdName[unit]))

        built = ole.buildObdLiveState(
            tracker.snapshot(),
            nowUtc=_utc(payload["ts"]),
            staleSec=ole.DEFAULT_OBD_LIVE_STALE_S,
            dataSource=payload["dataSource"],
        )

        assert built == payload

    def test_engineOffBatteryCase_isUnbandedEngineNotRunning(self) -> None:
        """
        Given: the engine-off-battery case (RPM stopped reporting, then 11.9 V)
        When: read
        Then: BATTERY_V band null with engine_not_running -- not red
        """
        battery = self._load()["engine-off-battery"]["params"]["BATTERY_V"]
        assert battery["band"] is None
        assert battery["noBandReason"] == "engine_not_running"

    def test_coolantAmberCase_isAmberAfterTheDwell(self) -> None:
        """
        Given: the coolant-amber case (105 C held 30 s)
        When: read
        Then: band amber with its since and reason
        """
        coolant = self._load()["coolant-amber"]["params"]["COOLANT_TEMP"]
        assert coolant["band"] == {
            "band": "amber",
            "since": "2026-10-13T12:10:30Z",
            "reason": "coolant >= 104 C for 30 s",
        }

    def test_coolantRedCase_isRedOnASingleSample(self) -> None:
        """
        Given: the coolant-red case (one 110 C reading)
        When: read
        Then: band red, no noBandReason
        """
        coolant = self._load()["coolant-red"]["params"]["COOLANT_TEMP"]
        assert coolant["band"]["band"] == "red"
        assert "noBandReason" not in coolant
