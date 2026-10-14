################################################################################
# File Name: test_capture_health_wiring.py
# Purpose/Description: US-688 (F-138) -- the JOIN. `capture_health.py` decides
#                      correctly in isolation and that is worth nothing until
#                      the orchestrator actually CALLS it, with the real power
#                      fact and the real logger reading, on the real emit tick.
#
#                      🔴 WHY THIS FILE EXISTS SEPARATELY. Every emitter on this
#                      mixin is a CLASS default of None, so a `_maybeEmitCardStates`
#                      that never calls the capture emitter leaves EVERY OTHER
#                      TEST IN THIS SPRINT GREEN and the operator's alert
#                      permanently dark. That is the US-687-b `linkHealthy`
#                      failure exactly -- it defaulted False, and one wiring test
#                      was the single RED in a file of seven.
#
#                      Nothing here sets `powerSource` or the row age directly.
#                      Doing so would prove `buildCaptureHealthState` works,
#                      which the producer suite already proves, and would say
#                      NOTHING about whether the orchestrator ever computes
#                      them -- which is the only thing in doubt.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-08    | Rex (US-688) | Initial -- the emit-tick join, driven through
#               |              | a real provider and a real data logger.
# 2026-10-13    | Rex (US-873) | The feeds join: OBD first row, UPS read, bridges.
# ================================================================================
################################################################################

"""US-688: the capture-health producer must actually run on the emit tick.

The two facts are acquired through the SAME methods production uses --
``_gatherPowerSource`` (the US-502 GPIO6 SSOT) and the US-302 data-logger
freshness read.  A test that injected either one would be green against an
orchestrator that never gathers it.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

# Sentinel so a caller can pass database=None (the "cannot consult it" case)
# and still be distinguished from "use the default empty record".
_UNSET = object()

from pi.obdii.capture_health import (
    REASON_LOGGER_ABSENT,
    REASON_NEVER_WRITTEN,
    STATE_IDLE,
    STATE_OK,
    STATE_STALLED,
    STATE_UNKNOWN,
)
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.obdii.orchestrator.health_monitor import HealthMonitorMixin

_STALL_S = 60.0


class _FakePowerSourceProvider:
    """The two methods `_gatherPowerSource` actually calls on the provider.

    Models the REAL contract: `isAvailable` is a PROPERTY and gates the read,
    `isExternalPowerPresent()` is the reading. Nothing here shortcuts the
    mapping -- production code is what turns these into external/battery/unknown.
    """

    def __init__(self, *, available: bool, external: bool):
        self._available = available
        self._external = external

    @property
    def isAvailable(self) -> bool:
        return self._available

    def isExternalPowerPresent(self) -> bool:
        return self._external


class _FakeDataLogger:
    """A data logger exposing only US-302's freshness property.

    `lastRowWrittenSecondsAgo` is `None` when no row has ever been written --
    the literal shape the Pi held for two days on 2026-09-04.
    """

    def __init__(self, lastRowWrittenSecondsAgo):
        self.lastRowWrittenSecondsAgo = lastRowWrittenSecondsAgo


class _Orch(HealthMonitorMixin, CardStateEmitterMixin):
    """The real mixins, composed IN THE PRODUCTION ORDER.

    🔴 THE COMPOSITION IS PART OF WHAT THIS FILE PINS. The row-freshness read
    lives on ``HealthMonitorMixin`` and the emit tick on ``CardStateEmitterMixin``
    -- a CROSS-MIXIN call, and `ApplicationOrchestrator` lists them in exactly
    this order (core.py:127-136). US-630 lost a whole feature to this seam: a
    `def foo(): ...` stub declared for mypy SHADOWED the real implementation
    because of MRO order, and the producer logged "wired" while deriving
    nothing. Composing only `CardStateEmitterMixin` here would raise
    AttributeError inside the emit tick's own try/except and be swallowed --
    green init log, no file, no alert.
    """

    def __init__(self, statesDir, *, powerProvider, dataLogger, stallSeconds=_STALL_S,
                 database=None):
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
                "captureHealth": {"enabled": True, "stallSeconds": stallSeconds},
            }
        }
        self._connection = None
        self._driveDetector = None
        self._hardwareManager = None
        self._dataLogger = dataLogger
        # US-727: the durable record the freshness read falls back to when the
        # logger's in-process marker is None. A restart clears that marker, so
        # "this process has written nothing" is no longer taken as "nothing was
        # ever written" -- the table is asked.
        self._database = database
        self._powerSourceProvider = powerProvider
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0


class _EmptyCaptureDb:
    """A database whose ``realtime_data`` exists and is EMPTY.

    US-727: this is what "the Pi has genuinely never captured" looks like once
    the freshness read consults the durable record -- MAX(timestamp) over an
    empty table is NULL, which is still ``never_written``. Before US-727 the
    fixture needed no database at all, because the absent in-process marker was
    taken as proof on its own; that is the conflation the story removed.
    """

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.dbPath = str(path)
        with sqlite3.connect(self.dbPath) as conn:
            conn.execute("CREATE TABLE realtime_data (id INTEGER PRIMARY KEY, timestamp TEXT)")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.dbPath)
        try:
            yield conn
        finally:
            conn.close()


def _runTick(tmp_path, *, available=True, external=True, lastRow=None,
             withLogger=True, stallSeconds=_STALL_S, database=_UNSET):
    """Drive the REAL emit path once; return the parsed states/capture-health.

    Everything between the fakes and the parsed JSON is production code: the
    emitter construction, the power gather, the logger read, the decision and
    the atomic write.
    """
    statesDir = str(tmp_path / "states")
    if database is _UNSET:
        database = _EmptyCaptureDb(tmp_path / "capture.db")
    orch = _Orch(
        statesDir,
        powerProvider=_FakePowerSourceProvider(
            available=available, external=external
        ),
        dataLogger=_FakeDataLogger(lastRow) if withLogger else None,
        stallSeconds=stallSeconds,
        database=database,
    )
    orch._initializeCardStateEmitters()
    orch._maybeEmitCardStates()

    path = tmp_path / "states" / "capture-health"
    assert path.exists(), (
        "no states/capture-health was written -- the producer is not wired into "
        "the emit tick, which is the one failure every other test in this story "
        "stays green for"
    )
    return json.loads(path.read_text())


class TestTheJoin:
    """The emit tick must reach the producer at all."""

    def test_maybeEmitCardStates_writesCaptureHealth(self, tmp_path) -> None:
        """
        Given: a wired orchestrator on car power with rows landing
        When: one emit tick runs
        Then: states/capture-health exists and is a real verdict

        The bare existence assertion. It is in its own test because every other
        test in this file depends on it, and a shared helper that silently
        returned None would make them all pass vacuously.
        """
        state = _runTick(tmp_path, lastRow=1.0)

        assert state["state"] == STATE_OK
        assert state["stallSeconds"] == _STALL_S


class TestTheIncidentThroughTheRealPath:
    """The 2026-09-04 outage, driven end-to-end."""

    def test_maybeEmitCardStates_neverWrittenOnCarPower_publishesStalled(
        self, tmp_path
    ) -> None:
        """
        Given: the Pi is on car power and the logger has never written a row
        When: one emit tick runs
        Then: states/capture-health says `stalled` with the never_written reason

        This is the alert the operator did not get for two days, produced by the
        real path rather than by a hand-built payload.
        """
        state = _runTick(tmp_path, lastRow=None)

        assert state["state"] == STATE_STALLED
        assert state["reason"] == REASON_NEVER_WRITTEN
        assert state["lastRowSecondsAgo"] is None

    def test_maybeEmitCardStates_stalledWithNoConnectionAtAll(self, tmp_path) -> None:
        """
        Given: `_connection` is None -- no dongle, no link, nothing on OBD
        When: one emit tick runs on car power with no rows written
        Then: `stalled` still publishes

        🔴 THE DEAD-BRANCH GUARD AT THE WIRING LEVEL. The producer's own suite
        proves the DECISION ignores OBD; this proves the WIRING does too. An
        orchestrator that gathered an OBD fact and passed it in would have to
        cope with a None connection here, and the natural implementation of
        "engine running" would go false and take the alert with it.
        """
        state = _runTick(tmp_path, lastRow=None)

        assert state["state"] == STATE_STALLED


class TestThePowerGateIsGathered:
    """`powerSource` must come from the provider, not from a default."""

    def test_maybeEmitCardStates_onBattery_publishesIdleNotStalled(
        self, tmp_path
    ) -> None:
        """
        Given: the provider reports the car's power is GONE (key off)
        When: one emit tick runs with no rows ever written
        Then: `idle` -- the story's negative case, through the real gather

        Paired with the incident test above on the SAME row-age fixture: the
        only thing that differs is the GPIO reading. An orchestrator that
        hardcoded `external` passes the incident test and fails this one.
        """
        state = _runTick(tmp_path, external=False, lastRow=None)

        assert state["state"] == STATE_IDLE
        assert state["state"] != STATE_STALLED

    def test_maybeEmitCardStates_unreadablePowerLine_publishesUnknown(
        self, tmp_path
    ) -> None:
        """
        Given: the power provider cannot be read
        When: one emit tick runs with no rows ever written
        Then: `unknown` -- neither a confident alarm nor a confident all-clear
        """
        state = _runTick(tmp_path, available=False, lastRow=None)

        assert state["state"] == STATE_UNKNOWN

    def test_maybeEmitCardStates_noProviderWired_publishesUnknownNotStalled(
        self, tmp_path
    ) -> None:
        """
        Given: no power provider exists on this orchestrator at all
        When: one emit tick runs with no rows ever written
        Then: `unknown`, never `stalled`

        The bench/boot-order case. `_gatherPowerSource` is LAZY precisely
        because the provider lands after the emitters are built, so an early
        tick genuinely has no provider -- and must not alert on that.
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(
            statesDir, powerProvider=None, dataLogger=_FakeDataLogger(None)
        )
        orch._initializeCardStateEmitters()
        orch._maybeEmitCardStates()

        state = json.loads((tmp_path / "states" / "capture-health").read_text())
        assert state["state"] == STATE_UNKNOWN
        assert state["state"] != STATE_STALLED


class TestTheLoggerReadIsGathered:
    """The row age must come from the real US-302 property read."""

    def test_maybeEmitCardStates_freshRow_publishesTheRealAge(self, tmp_path) -> None:
        """
        Given: the logger reports a row written 5 s ago
        When: one emit tick runs
        Then: that exact age reaches the state file

        Pins the value as TRANSPORTED rather than re-derived. A wiring that
        passed a constant would pass every state-name assertion in this file.
        """
        state = _runTick(tmp_path, lastRow=5.0)

        assert state["lastRowSecondsAgo"] == 5.0
        assert state["state"] == STATE_OK

    def test_maybeEmitCardStates_agedRow_publishesStalled(self, tmp_path) -> None:
        """
        Given: the logger's newest row is older than the stall window
        When: one emit tick runs on car power
        Then: `stalled`

        The second route into the alert. `never_written` is a cold Pi that never
        captured; THIS is a Pi that was capturing and stopped -- the shape a
        mid-drive dongle drop actually produces.
        """
        state = _runTick(tmp_path, lastRow=_STALL_S + 30.0)

        assert state["state"] == STATE_STALLED
        assert state["lastRowSecondsAgo"] == _STALL_S + 30.0

    def test_maybeEmitCardStates_noDataLogger_publishesUnknownNotStalled(
        self, tmp_path
    ) -> None:
        """
        Given: no data logger is wired at all
        When: one emit tick runs on car power
        Then: `unknown` with the logger_absent reason, NEVER `stalled`

        🔴 THE DISTINCTION US-302's READER LOSES, asserted through the wiring.
        `_readDataLoggerLastRowSecondsAgo` returns None for BOTH this and the
        incident. If the orchestrator passes only that None through, this test
        goes RED as `stalled` -- and every bench run without a logger would
        have raised a capture alarm.
        """
        state = _runTick(tmp_path, withLogger=False)

        assert state["state"] == STATE_UNKNOWN
        assert state["reason"] == REASON_LOGGER_ABSENT
        assert state["state"] != STATE_STALLED


class TestTheWindowIsConfigured:
    """The stall window is a config value, not a constant in the wiring."""

    def test_maybeEmitCardStates_configuredWindowReachesTheDecision(
        self, tmp_path
    ) -> None:
        """
        Given: the same row age judged against two configured windows
        When: each emit tick runs
        Then: the verdict follows the CONFIG, not a hardcoded number

        US-686 closed this sprint on a value that lived in three files with no
        lint over them. This asserts the config value is the one that decides,
        so a wiring that fell back to the module default would be caught here.
        """
        aged = 120.0

        assert _runTick(tmp_path / "a", lastRow=aged, stallSeconds=60.0)[
            "state"
        ] == STATE_STALLED
        assert _runTick(tmp_path / "b", lastRow=aged, stallSeconds=600.0)[
            "state"
        ] == STATE_OK


class TestItStaysDarkWhenDisabled:
    """A disabled producer writes NO file -- it does not write a false all-clear."""

    def test_maybeEmitCardStates_disabled_writesNoFile(self, tmp_path) -> None:
        """
        Given: pi.captureHealth.enabled is false
        When: one emit tick runs
        Then: no states/capture-health exists

        An absent file is what the carousel renders as an honest absence. A file
        saying `ok` would be a producer claiming to have looked when it never
        ran -- the same reason gear writes nothing when its derivation is dark.
        """
        statesDir = str(tmp_path / "states")
        orch = _Orch(
            statesDir,
            powerProvider=_FakePowerSourceProvider(available=True, external=True),
            dataLogger=_FakeDataLogger(None),
        )
        orch._config["pi"]["captureHealth"]["enabled"] = False
        orch._initializeCardStateEmitters()
        orch._maybeEmitCardStates()

        assert not (tmp_path / "states" / "capture-health").exists()


# ------------------------------------------------------------ US-873: the feeds


class _FakeWriter:
    """The inner ObdDataLogger's US-873 marker: ``firstRowTs``, None until set."""

    def __init__(self, firstRowTs=None):
        self.firstRowTs = firstRowTs


class _FakeUps:
    """The three gauge reads `_emitBatteryHealthState` makes, scripted.

    ``onPercentage`` runs inside the SECOND read, so a test can observe what the
    producer had already recorded the instant the VCELL read returned.
    """

    def __init__(self, vcell, onPercentage=None):
        self._vcell = vcell
        self._onPercentage = onPercentage

    def getBatteryVoltage(self):
        if isinstance(self._vcell, Exception):
            raise self._vcell
        return self._vcell

    def getBatteryPercentage(self):
        if self._onPercentage is not None:
            self._onPercentage()
        return 80

    def getChargeRatePercentPerHour(self):
        return None


def _feedOrch(tmp_path, *, lastRow=None, database=_UNSET, external=True):
    """A wired orchestrator, initialised but not yet ticked.

    Its data logger carries a ``dataLogger`` writer, as RealtimeDataLogger does.
    """
    if database is _UNSET:
        database = _EmptyCaptureDb(tmp_path / "capture.db")
    dataLogger = _FakeDataLogger(lastRow)
    dataLogger.dataLogger = _FakeWriter()
    orch = _Orch(
        str(tmp_path / "states"),
        powerProvider=_FakePowerSourceProvider(available=True, external=external),
        dataLogger=dataLogger,
        database=database,
    )
    orch._initializeCardStateEmitters()
    return orch


def _tickFeeds(orch, tmp_path):
    orch._lastCardStateEmitTime = None
    orch._maybeEmitCardStates()
    return json.loads((tmp_path / "states" / "capture-health").read_text())["feeds"]


class TestTheFeedsAreGathered:
    """US-873: the tick publishes a feeds block from the owners of each fact."""

    def test_tick_publishesExactlyTheFourFeeds(self, tmp_path) -> None:
        """
        Given: a wired orchestrator with nothing produced yet
        When: one emit tick runs
        Then: feeds has obd/imu/light/ups, every value null, never 0
        """
        feeds = _tickFeeds(_feedOrch(tmp_path), tmp_path)

        assert set(feeds) == {"obd", "imu", "light", "ups"}
        for entry in feeds.values():
            assert entry["firstSampleTs"] is None
            assert entry["lastSampleSecondsAgo"] is None
            assert entry["state"] == STATE_UNKNOWN

    def test_obdFirstSample_isTheWritersFirstRowTs(self, tmp_path) -> None:
        """
        Given: a writer that has committed nothing, then its first row
        When: ticks run before and after that row
        Then: obd.firstSampleTs is the writer's firstRowTs, with the in-process
              row age beside it
        """
        orch = _feedOrch(tmp_path)

        before = _tickFeeds(orch, tmp_path)
        orch._dataLogger.dataLogger.firstRowTs = "2026-10-13T12:01:05Z"
        orch._dataLogger.lastRowWrittenSecondsAgo = 0.5
        first = _tickFeeds(orch, tmp_path)

        assert before["obd"]["firstSampleTs"] is None
        assert first["obd"] == {
            "state": STATE_OK,
            "firstSampleTs": "2026-10-13T12:01:05Z",
            "lastSampleSecondsAgo": 0.5,
        }

    def test_obdFirstSample_isNoneSafeWithoutAWriter(self, tmp_path) -> None:
        """
        Given: no data logger at all (bench), or one with no inner writer
        When: a tick runs
        Then: obd.firstSampleTs is null -- the tick does not raise
        """
        bare = _feedOrch(tmp_path / "a")
        bare._dataLogger = None
        noWriter = _feedOrch(tmp_path / "b")
        del noWriter._dataLogger.dataLogger

        assert _tickFeeds(bare, tmp_path / "a")["obd"]["firstSampleTs"] is None
        assert _tickFeeds(noWriter, tmp_path / "b")["obd"]["firstSampleTs"] is None

    def test_obdFirstSample_comesFromTheRealWriter(self, tmp_path) -> None:
        """
        Given: a REAL ObdDataLogger that commits one row
        When: a tick runs
        Then: obd.firstSampleTs is byte-identical to that row's timestamp
        """
        from datetime import datetime

        from pi.obdii.data.logger import ObdDataLogger
        from pi.obdii.data.types import LoggedReading
        from pi.obdii.database import ObdDatabase

        db = ObdDatabase(str(tmp_path / "real.db"), walMode=False)
        db.initialize()
        writer = ObdDataLogger(
            None, db, config={"pi": {"time": {"localZone": "America/Chicago"}}}
        )
        writer.logReading(LoggedReading(
            parameterName="RPM", value=800.0, unit="rpm",
            timestamp=datetime(2026, 10, 13, 7, 1, 5),
        ))
        orch = _feedOrch(tmp_path)
        orch._dataLogger.dataLogger = writer
        with db.connect() as conn:
            stored = conn.execute("SELECT timestamp FROM realtime_data").fetchone()[0]

        assert _tickFeeds(orch, tmp_path)["obd"]["firstSampleTs"] == stored

    def test_obdRowsOnly_theOtherFeedsAreNullNotZero(self, tmp_path) -> None:
        """
        Given: OBD rows written and no IMU/light/UPS samples (validation 1)
        When: a tick runs
        Then: obd has a firstSampleTs; imu/light/ups are null and unknown
        """
        orch = _feedOrch(tmp_path)
        orch._dataLogger.dataLogger.firstRowTs = "2026-10-13T12:01:05Z"
        orch._dataLogger.lastRowWrittenSecondsAgo = 1.0

        feeds = _tickFeeds(orch, tmp_path)

        assert feeds["obd"]["firstSampleTs"] == "2026-10-13T12:01:05Z"
        for name in ("imu", "light", "ups"):
            assert feeds[name] == {
                "state": STATE_UNKNOWN,
                "firstSampleTs": None,
                "lastSampleSecondsAgo": None,
            }

    def test_obdFeed_neverPublishesAPreviousProcessRow(self, tmp_path) -> None:
        """
        Given: a restart -- the table holds an old row, this process wrote none
        When: a tick runs
        Then: the verdict may carry the durable age, but feeds.obd stays null
        """
        db = _EmptyCaptureDb(tmp_path / "capture.db")
        with sqlite3.connect(db.dbPath) as conn:
            conn.execute("INSERT INTO realtime_data (timestamp) VALUES (?)",
                         ("2026-10-13T11:59:00Z",))
        orch = _feedOrch(tmp_path, database=db)

        orch._maybeEmitCardStates()
        state = json.loads((tmp_path / "states" / "capture-health").read_text())

        assert state["lastRowSecondsAgo"] is not None
        assert state["feeds"]["obd"]["firstSampleTs"] is None
        assert state["feeds"]["obd"]["lastSampleSecondsAgo"] is None


class TestTheUpsFeed:
    """Validation 3: raise, then 0xFFFF, then 12.6 V."""

    def _emitWith(self, orch, ups):
        from types import SimpleNamespace

        orch._hardwareManager = SimpleNamespace(upsMonitor=ups)
        orch._emitBatteryHealthState()

    def test_raiseThenSentinelThenARealRead(self, tmp_path, monkeypatch) -> None:
        """
        Given: a gauge read that raises, then returns 0xFFFF, then 12.6 V
        When: the battery-health tick runs after each
        Then: ups.firstSampleTs stays null through the first two and is set
              by the third -- before the next gauge read is even made
        """
        import common.time.helper as helper

        monkeypatch.setattr(helper, "utcIsoNow", lambda: "2026-10-13T12:00:20Z")
        orch = _feedOrch(tmp_path)
        seenAtNextRead = []

        self._emitWith(orch, _FakeUps(OSError("i2c nack")))
        afterRaise = orch._upsFirstSampleTs
        self._emitWith(orch, _FakeUps(0xFFFF))
        afterRawSentinel = orch._upsFirstSampleTs
        self._emitWith(orch, _FakeUps(0xFFFF * 78.125e-6))
        afterScaledSentinel = orch._upsFirstSampleTs
        self._emitWith(orch, _FakeUps(
            12.6, onPercentage=lambda: seenAtNextRead.append(orch._upsFirstSampleTs)
        ))

        assert afterRaise is None
        assert afterRawSentinel is None
        assert afterScaledSentinel is None
        assert seenAtNextRead == ["2026-10-13T12:00:20Z"]
        assert orch._upsFirstSampleTs == "2026-10-13T12:00:20Z"

    def test_upsAge_comesFromTheValidReadOnly(self, tmp_path) -> None:
        """
        Given: a valid read at t=100, then a sentinel read, and the tick at t=103
        When: the capture-health tick runs
        Then: ups.lastSampleSecondsAgo is 3.0 -- the sentinel did not refresh it
        """
        orch = _feedOrch(tmp_path)
        clock = [100.0]
        orch._feedClock = lambda: clock[0]
        self._emitWith(orch, _FakeUps(4.1))
        clock[0] = 102.0
        self._emitWith(orch, _FakeUps(0xFFFF))
        clock[0] = 103.0

        orch._emitCaptureHealthState()
        feeds = json.loads((tmp_path / "states" / "capture-health").read_text())["feeds"]

        assert feeds["ups"]["lastSampleSecondsAgo"] == 3.0
        assert feeds["ups"]["state"] == STATE_OK

    def test_aRestartReArmsTheFirstSample(self, tmp_path) -> None:
        """
        Given: a process that sampled the UPS, then a new process (a restart)
        When: the new process ticks before its first read
        Then: its ups.firstSampleTs is null -- never the old process's time
        """
        first = _feedOrch(tmp_path / "a")
        self._emitWith(first, _FakeUps(4.1))
        restarted = _feedOrch(tmp_path / "b")

        assert first._upsFirstSampleTs is not None
        assert _tickFeeds(restarted, tmp_path / "b")["ups"]["firstSampleTs"] is None


class TestTheBridgeFeeds:
    """IMU and light come from the live bridges, never a gated database row."""

    def _sample(self, topic, tsUtc, tsCapture, value=None, seq=1):
        from types import SimpleNamespace

        return SimpleNamespace(topic=topic, tsUtc=tsUtc, tsCapture=tsCapture,
                               value=value, unit="", seq=seq)

    def test_lightBridge_firstAndNewestSampleReachTheFeed(self, tmp_path) -> None:
        """
        Given: the real light bridge drains two lux samples (one saturated)
        When: the tick runs with the clock 5 s past the newest capture
        Then: feeds.light names the FIRST sample's ts and a 5 s age
        """
        from pi.sensors.light_state_bridge import LightStateBridge
        from pi.sensors.sensor_reader import TOPIC_LIGHT_LUX

        bridge = LightStateBridge(None, str(tmp_path / "states"))
        bridge.handleSample(
            self._sample(TOPIC_LIGHT_LUX, "2026-10-13T12:00:21Z", 50.0, 12.0, seq=1)
        )
        bridge.handleSample(
            self._sample(TOPIC_LIGHT_LUX, "2026-10-13T12:00:22Z", 51.0, None, seq=2)
        )
        orch = _feedOrch(tmp_path)
        orch._lightStateBridge = bridge
        orch._feedClock = lambda: 56.0

        light = _tickFeeds(orch, tmp_path)["light"]

        assert light == {
            "state": STATE_OK,
            "firstSampleTs": "2026-10-13T12:00:21Z",
            "lastSampleSecondsAgo": 5.0,
        }

    def test_imuBridge_countsRawChannelsNotStates(self, tmp_path) -> None:
        """
        Given: the real IMU bridge drains a presence STATE, then a gyro sample
        When: the tick runs
        Then: feeds.imu's first sample is the gyro's -- a state is not a sample
        """
        from pi.sensors.imu_state_bridge import (
            STATE_IMU_PRESENCE,
            TOPIC_IMU_GYRO,
            ImuStateBridge,
        )

        bridge = ImuStateBridge(None, str(tmp_path / "states"))
        bridge.handleSample(self._sample(STATE_IMU_PRESENCE, "2026-10-13T12:00:19Z", 9.0, 1.0))
        assert bridge.firstSampleTs is None
        bridge.handleSample(
            self._sample(TOPIC_IMU_GYRO, "2026-10-13T12:00:21Z", 10.0, (0.0, 0.0, 0.0))
        )
        orch = _feedOrch(tmp_path)
        orch._imuStateBridge = bridge
        orch._feedClock = lambda: 10.25

        imu = _tickFeeds(orch, tmp_path)["imu"]

        assert imu["firstSampleTs"] == "2026-10-13T12:00:21Z"
        assert imu["lastSampleSecondsAgo"] == 0.25
        assert imu["state"] == STATE_OK
