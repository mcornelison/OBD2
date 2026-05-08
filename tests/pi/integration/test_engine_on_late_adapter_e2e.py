################################################################################
# File Name: test_engine_on_late_adapter_e2e.py
# Purpose/Description: US-303 (Spool Story C) -- engine-on bench harness for
#                      the adapter-late-arrives production flow that BUG-1
#                      and BUG-2 lived in.  The May 4 + May 5 + May 8 zero-
#                      data engine-on tests proved US-286's harness was not
#                      enough on its own: US-286 mocks at the BT edge but
#                      ALSO assumes the adapter is present at orchestrator
#                      init.  Production realistic flow once the Pi gets
#                      wired to ignition (~5/9 weekend) is:
#
#                          service starts (no adapter present)
#                            -> _initializeConnection 30s timeout fires
#                            -> runReconnectHeartbeat daemon spawned (US-301)
#                            -> heartbeat ticks every 10s w/ INFO log
#                            -> adapter wakes up
#                            -> heartbeat tick succeeds, loop exits
#                            -> runLoop state-change check observes connect-up
#                            -> _handleConnectionRestored fires
#                            -> _restartDataLoggerOnConnectionRestored (US-302)
#                            -> dataLogger.start() runs
#                            -> realtime_data rows accumulate
#
#                      US-301 + US-302 close the silent gaps in steps 4 + 7.
#                      US-303 (this file) is the durable regression gate that
#                      exercises the WHOLE flow end-to-end and would have
#                      caught BUG-1 + BUG-2 pre-Sprint-25-deploy.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex (US-303) | Initial -- Spool Story C / Sprint 27 P0
#               |              | Drive-6-unblock regression gate.  Mock
#               |              | surface = adapter availability + sleepFn
#               |              | (clock) + connection.obd.query (BT edge).
#               |              | Real reconnect_loop.runReconnectHeartbeat,
#               |              | real EventRouterMixin._handleConnectionRestored
#               |              | + ._restartDataLoggerOnConnectionRestored,
#               |              | real ObdDataLogger.logReading writes to
#               |              | realtime_data.  Discriminators: pre-US-301
#               |              | the heartbeat function does not exist
#               |              | (ImportError); pre-US-302 _handleConnection
#               |              | Restored does not (re-)start the data logger
#               |              | (start.assert_called_once fails).
# ================================================================================
################################################################################

"""US-303 -- engine-on bench harness for the adapter-late-arrives flow.

The test-coverage gap this closes
---------------------------------
US-286 (Sprint 25 Story 3) shipped the engine+OBD end-to-end harness, but
narrowed its mock surface to the BT edge ONLY -- the orchestrator was
already in the connected state when the test began.  Production realistic
behaviour once the Pi gets car-coupled lifecycle (Pi-to-ignition wiring
~5/9 weekend) is the OPPOSITE of that:

* every key-on = Pi cold-boot;
* OBDLink LX is not yet ready when ``_initializeConnection`` hits its
  30s wall-clock cap;
* the orchestrator drops to PENDING and the reconnect daemon is the
  ONLY thread trying to bring the link up;
* when the adapter eventually wakes, the runLoop's state-change check
  fires ``_handleConnectionRestored`` which must (re-)start the data
  logger -- otherwise the live OBD link sits there ignored.

That whole-flow path is exactly where Spool's 2026-05-08 inbox note found
two P0 bugs sitting behind the Sprint 25 ``_initializeConnection`` fix:

* **BUG-1**: 11 hours of PENDING with ZERO retry attempts logged.  No
  heartbeat, no canary, no loud bail.  Closed by US-301
  (``runReconnectHeartbeat`` -- 10s INFO heartbeat + per-tick connect
  attempt with 5s wall-clock cap + WARNING-level loud bail per the
  V0.24.1 lesson).
* **BUG-2**: ``_handleConnectionRestored`` updated display + status fields
  but never (re-)started the data logger.  Result: 8-second window of
  live OBD with zero ``realtime_data`` rows.  Closed by US-302
  (``_restartDataLoggerOnConnectionRestored`` invoked from
  ``_handleConnectionRestored`` exception-isolated).

US-303 ships the regression gate: a single integration test that walks
the production code paths from "no adapter present" through
"row written to realtime_data" with everything above the BT edge running
real, deterministic via FakeClock, completing inside the 30-sec test
runtime budget.

Mock surface (per Spool Story C invariant)
------------------------------------------
* **Adapter availability** -- a mutable boolean that flips mid-test
  between heartbeat ticks (mirrors a Pi cold-boot where OBDLink LX
  becomes BT-reachable a few seconds after Pi systemd userspace).
* **Connection.obd.query** -- the same BT-edge seam US-286 uses;
  returns RPM=750 once the adapter is up.
* **Sleep function** -- replaces :func:`time.sleep` between heartbeat
  ticks so the test runs in ~0 wall-clock.  This is also the seam
  through which the test mutates adapter availability between ticks.

Real production code under test:

* :func:`src.pi.obdii.reconnect_loop.runReconnectHeartbeat` -- the US-301
  function that closes BUG-1.  Tick cadence + INFO heartbeat format +
  WARNING loud-bail + per-tick connect attempt all run real.
* :meth:`EventRouterMixin._handleConnectionRestored` -- the US-302 wired
  handler that closes BUG-2.  Calls
  ``_restartDataLoggerOnConnectionRestored`` which calls the (mocked at
  the outer level) ``dataLogger.start()``.
* :meth:`ObdDataLogger.queryParameter` + :meth:`ObdDataLogger.logReading`
  -- the realtime_data write path that Spool's 2026-05-08 journal showed
  was never reached.
* :class:`ApplicationOrchestrator` (``simulate=True``) -- bare-built per
  the US-286 / US-260 pattern.

Discriminators (per ``feedback_runtime_validation_required.md``)
----------------------------------------------------------------
This test FAILS against pre-Sprint-27 code in two distinct places:

* **Pre-US-301**: ``runReconnectHeartbeat`` does not exist -- the import
  ``from src.pi.obdii.reconnect_loop import runReconnectHeartbeat``
  raises :class:`ImportError` at module load.  The test cannot even
  start.  This is the BUG-1 silent-thread anti-pattern in regression-
  gate form.
* **Pre-US-302**: ``_handleConnectionRestored`` updated display + status
  but did not call ``_restartDataLoggerOnConnectionRestored`` (which did
  not exist).  The
  ``outerDataLogger.start.assert_called_once()`` assertion in Phase 4
  fires because ``start`` was never invoked from the handler -- the
  exact 8-second-of-live-OBD-with-zero-rows symptom Spool documented.

It MUST PASS today against post-US-301 + post-US-302 production code
paths under test.

Wall-clock budget
-----------------
US-303 acceptance: "Test runtime under 30 sec via mocked clock (FakeClock
pattern from Sprint 26 US-298)".  The production target is the 60-sec
boot-to-DriveDetector-operational figure US-286 inherits from US-285.
The synthetic test compresses this through:

* ``runReconnectHeartbeat(sleepFn=...)`` -- the injected sleep is a
  near-no-op (only side effect is the mid-test adapter-state flip);
  no real wall-clock between ticks.
* ``maxTicks=2`` -- safety net so the heartbeat exits in 2 iterations
  even if the test scaffolding has a bug;
* synchronous direct invocation of :meth:`_handleConnectionRestored`
  (mirrors what runLoop's state-change check would do on its next pass)
  -- no real runLoop spawn, no real polling thread.

Per US-303 stop condition (1), this is the alternative-route that the
story authorises if the FakeClock pattern doesn't compose with
reconnect_loop's threading model: direct synchronous invocation through
the public ``runReconnectHeartbeat`` function with maxTicks + sleepFn,
NOT spawning the daemon and trying to join.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pi.obdii.data.logger import ObdDataLogger
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive_id import clearCurrentDriveId
from src.pi.obdii.orchestrator.core import ApplicationOrchestrator
from src.pi.obdii.reconnect_loop import (
    HEARTBEAT_LOG_PREFIX,
    runReconnectHeartbeat,
)

# Spool spec: feed RPM=750 samples (well above any DriveDetector
# threshold; matches an Eclipse warm-idle baseline.  US-303 does not
# exercise the drive-start path -- that's US-286's territory -- but
# keeping the value consistent makes journal cross-reads easier.
_RPM_ENGINE_ON: float = 750.0

# US-303 acceptance: "Test runtime under 30 sec".  Wall-clock guard fires
# at the test boundary so a regression in real-time-driven code (e.g.
# someone wires a `time.sleep` into the heartbeat path) is loud +
# immediate.
_TEST_RUNTIME_BUDGET_SECONDS: float = 30.0

# Tight cap on the heartbeat connect attempt: tests run synchronously
# against a fast mock so the worker-thread Event.wait() returns in <50ms.
# Setting the cap to 1.0 gives plenty of headroom while keeping the test
# loud if a regression introduces real I/O on this path.
_TEST_HEARTBEAT_ATTEMPT_TIMEOUT_SEC: float = 1.0


# ================================================================================
# Helpers / fixtures
# ================================================================================


def _baseConfig() -> dict[str, Any]:
    """Tier-aware minimal config for the engine-on late-adapter path.

    Mirrors US-286 baseline (single RPM parameter, daily profile, sync
    disabled) so journal cross-reads against US-286's harness stay
    aligned.  The drive-detector thresholds are not exercised here -- the
    flow under test is purely "no-adapter -> heartbeat -> connection-
    restored -> data-logger-restart -> row-written".
    """
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "obdii": {
                "orchestrator": {
                    "engineOnVoltageThreshold": 13.8,
                    "engineOnSampleCount": 3,
                    # 30s production default; US-303 does not actually
                    # call _initializeConnection (we fast-path the bare
                    # orchestrator into the PENDING-state preconditions).
                    "initialConnectTimeoutSec": 30,
                },
            },
            "analysis": {
                "driveStartRpmThreshold": 500,
                "driveStartDurationSeconds": 0.0,
                "driveEndRpmThreshold": 0,
                "driveEndDurationSeconds": 0.0,
                "triggerAfterDrive": False,
                "driveSummaryBackfillSeconds": 60,
            },
            "realtimeData": {
                "pollingIntervalMs": 100,
                "parameters": [
                    {"name": "RPM", "logData": True,
                     "displayOnDashboard": False},
                ],
            },
            "profiles": {
                "activeProfile": "daily",
                "availableProfiles": [
                    {"id": "daily", "pollingIntervalMs": 100},
                ],
            },
            "sync": {"enabled": False},
        },
        "server": {},
    }


class _LateAdapterConnection:
    """Mock OBD connection that simulates an adapter that wakes up late.

    Mirrors the python-obd-shaped contract that
    :class:`ObdDataLogger.queryParameter` + the heartbeat path consume:

    * :meth:`isConnected` -- returns the current connected state.  Used
      by ``_buildHeartbeatIsConnectedFn`` and the runLoop state-change
      check.
    * :meth:`connect` -- real production connect attempts the ELM327 +
      ECU handshake.  This mock returns True iff
      :attr:`adapterAvailable` is True at call time; success side-
      effects ``_isConnected = True`` so subsequent :meth:`isConnected`
      reflects the new state.
    * :attr:`obd` -- python-obd ``OBD()`` instance equivalent; the
      :class:`ObdDataLogger` reads ``connection.obd.query`` to fetch
      readings.
    * :attr:`adapterAvailable` -- the test-only mutable knob.  Mutate
      between heartbeat ticks via the injected ``sleepFn`` to simulate
      the adapter waking up.

    The ``connectAttempts`` counter is observable for the BUG-1
    discriminator: pre-US-301, the heartbeat function did not exist so
    no connect calls would have been driven on the PENDING-state path.
    """

    def __init__(self, *, rpmValue: float) -> None:
        self.adapterAvailable: bool = False
        self._isConnected: bool = False
        self.connectAttempts: int = 0
        self.isConnectedCallCount: int = 0
        self.isSimulated: bool = False
        # Bypass the Mode-01 PID probe gate inside ObdDataLogger --
        # supportedPids=None means "skip the supported-set check".
        self.supportedPids: Any = None
        # python-obd OBD() shim: scripted query returns RPM=750 once
        # the adapter is up.
        self.obd = MagicMock()
        self.obd.query = _ScriptedObdQuery(rpmValue=rpmValue)

    def isConnected(self) -> bool:
        self.isConnectedCallCount += 1
        return self._isConnected

    def connect(self) -> bool:
        self.connectAttempts += 1
        if self.adapterAvailable:
            self._isConnected = True
            return True
        return False


class _ScriptedObdQuery:
    """Mock at the python-obd `OBD.query` boundary (the BT edge).

    Returns a python-obd-shaped Response object with a fixed numeric
    value.  Reused unchanged from US-286 patterns.
    """

    def __init__(self, rpmValue: float) -> None:
        self.rpmValue = rpmValue
        self.queryCount: int = 0

    def __call__(self, cmd: Any) -> Any:
        self.queryCount += 1
        response = MagicMock()
        response.is_null.return_value = False
        response.value = self.rpmValue
        return response


class _AdapterAwakenerSleepFn:
    """Sleep seam that flips the mock adapter to "available" after N calls.

    Heartbeat calls ``sleepFn(tickIntervalSec)`` between ticks.  Tick 1
    fails (adapter still down), then this seam flips the adapter to
    "available" so tick 2 finds a working adapter.  No real sleep
    happens -- the test runs in ~0 wall-clock.

    This is the FakeClock-style pattern Sprint 26 US-298 introduced for
    deterministic cadence tests, adapted for the heartbeat path.

    Args:
        connection: The :class:`_LateAdapterConnection` to flip.
        flipAfterCalls: 1-based call count after which the flip fires.
            Default 1: flip after the FIRST sleep so tick 2 succeeds.
    """

    def __init__(
        self,
        connection: _LateAdapterConnection,
        *,
        flipAfterCalls: int = 1,
    ) -> None:
        self._connection = connection
        self._flipAfterCalls = flipAfterCalls
        self._callCount: int = 0
        # Captures the seconds argument from each call so the test can
        # cross-check that the heartbeat is sleeping at the canonical
        # 10s cadence (HEARTBEAT_TICK_INTERVAL_SEC) without depending on
        # it directly.
        self.sleepDurations: list[float] = []

    def __call__(self, seconds: float) -> None:
        self._callCount += 1
        self.sleepDurations.append(seconds)
        if self._callCount == self._flipAfterCalls:
            self._connection.adapterAvailable = True


@pytest.fixture()
def lateAdapterDb(tmp_path: Path) -> ObdDatabase:
    """Persistent on-disk DB seeded with the 'daily' profile (US-286 pattern).

    ``realtime_data.profile_id`` carries a FK to ``profiles(id)``;
    without the seed the first ``logReading`` INSERT raises
    ``IntegrityError: FOREIGN KEY constraint failed``.  Production
    seeds via :class:`ProfileManager` at lifecycle init -- bypassed
    here because the orchestrator runs bare (no ``start()``).
    """
    db = ObdDatabase(str(tmp_path / "test_us303_late_adapter.db"), walMode=False)
    db.initialize()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO profiles (id, name) VALUES (?, ?)",
            ('daily', 'Daily Driving'),
        )
    yield db
    clearCurrentDriveId()


@pytest.fixture()
def lateAdapterHarness(lateAdapterDb: ObdDatabase) -> dict[str, Any]:
    """Wire the late-adapter engine-on path with real production classes.

    Initial state mirrors the post-_initializeConnection-timeout PENDING
    snapshot Spool's 2026-05-08 evidence captured: connection object
    exists, ``isConnected()`` returns False, data logger is not yet
    started.  The heartbeat path is the SOLE recovery vector under test.

    Real instances under test:

    * :class:`ApplicationOrchestrator` (``simulate=True`` -- bypasses
      real OBD-init that requires hardware on Windows dev boxes).
    * :class:`ObdDataLogger` (real -- exercises ``queryParameter`` +
      ``logReading``, the path that writes ``realtime_data``).
    * :func:`runReconnectHeartbeat` (real -- US-301 closure of BUG-1).
    * :meth:`_handleConnectionRestored` (real -- US-302 closure of BUG-2).

    Mock-only surfaces:

    * The connection (BT edge + adapter availability + isConnected
      reporting).  See :class:`_LateAdapterConnection`.
    * The outer data logger (so ``start`` is observable as a
      ``MagicMock`` -- the BUG-2 wiring discriminator).  Production
      composition is ``RealtimeDataLogger._dataLogger ->
      ObdDataLogger``; the inner is real and writes realtime_data when
      driven directly.
    """
    config = _baseConfig()
    orchestrator = ApplicationOrchestrator(config=config, simulate=True)
    orchestrator._database = lateAdapterDb

    # Mock connection at the BT edge: adapter starts unavailable so
    # connect() will return False until the test flips the knob between
    # heartbeat ticks.
    connection = _LateAdapterConnection(rpmValue=_RPM_ENGINE_ON)
    orchestrator._connection = connection

    # Outer data logger is a MagicMock with the inner ObdDataLogger
    # exposed at ``_dataLogger`` (matches production composition).
    # ``start`` is a MagicMock so the test can assert it was called
    # exactly once from _handleConnectionRestored (the BUG-2 wiring
    # discriminator).  ``stop`` is a no-op since the test never invokes
    # runLoop.
    innerLogger = ObdDataLogger(
        connection=connection,
        database=lateAdapterDb,
        profileId='daily',
        dataSource='real',
    )
    outerDataLogger = MagicMock()
    outerDataLogger._dataLogger = innerLogger
    outerDataLogger.start = MagicMock()
    outerDataLogger.stop = MagicMock()
    orchestrator._dataLogger = outerDataLogger

    return {
        "orchestrator": orchestrator,
        "connection": connection,
        "innerDataLogger": innerLogger,
        "outerDataLogger": outerDataLogger,
    }


def _readRealtimeDataRowCount(db: ObdDatabase) -> int:
    with db.connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM realtime_data"
        ).fetchone()[0]


def _readRealtimeDataRows(
    db: ObdDatabase,
) -> list[tuple[str, float, str | None]]:
    """Pull (parameter_name, value, data_source) rows.

    No drive_id filter -- the late-adapter flow does not exercise
    drive_start in this test (that's US-286's territory); rows land
    with drive_id NULL.
    """
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT parameter_name, value, data_source FROM realtime_data "
            "ORDER BY id ASC",
        ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


# ================================================================================
# Acceptance: full late-adapter capture pipeline
# ================================================================================


class TestEngineOnLateAdapterEndToEnd:
    """US-303 Spool Story C -- adapter-late-arrives engine-on harness.

    Single integration test that walks the production code paths from
    "no adapter present" through "row written to realtime_data".  Per-
    phase assertions surface the failing stage clearly so a regression
    names which step broke (heartbeat fires? connection-restored
    handler runs? data logger starts? row writes?).
    """

    def test_engineOn_lateAdapter_heartbeatTicks_dataLoggerRestarts_rowWritten(
        self,
        lateAdapterHarness: dict[str, Any],
        lateAdapterDb: ObdDatabase,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        orchestrator: ApplicationOrchestrator = lateAdapterHarness["orchestrator"]
        connection: _LateAdapterConnection = lateAdapterHarness["connection"]
        innerLogger: ObdDataLogger = lateAdapterHarness["innerDataLogger"]
        outerDataLogger: MagicMock = lateAdapterHarness["outerDataLogger"]

        # Wall-clock guard for the US-303 "test runtime under 30 sec"
        # acceptance.  Started before any production-path work runs;
        # asserted once at the test boundary.
        testStart = time.perf_counter()

        # Capture INFO + WARNING from the heartbeat module so the BUG-1
        # discriminator (canonical heartbeat log lines emitted) is
        # observable end-to-end.
        caplog.set_level(logging.INFO, logger='src.pi.obdii.reconnect_loop')

        # ============================================================
        # Phase 1: pre-heartbeat sanity.  No retries fired, adapter is
        # unavailable, connection.isConnected() returns False, data
        # logger has not been started.  Sanity gate that the harness
        # wiring itself does not produce false positives.
        # ============================================================
        assert connection.adapterAvailable is False
        assert connection.isConnected() is False, (
            "Phase 1 PENDING precondition not in place: connection must "
            "report disconnected before heartbeat fires"
        )
        assert connection.connectAttempts == 0
        assert outerDataLogger.start.call_count == 0, (
            "Phase 1: outer data logger MUST NOT have been started yet "
            "-- the late-adapter flow under test asks the heartbeat path "
            "to be the SOLE start trigger"
        )
        assert _readRealtimeDataRowCount(lateAdapterDb) == 0

        # ============================================================
        # Phase 2: drive runReconnectHeartbeat synchronously with the
        # adapter-awakener sleep seam.  The seam flips the adapter to
        # "available" between tick 1 and tick 2.  maxTicks=2 is the
        # safety net per US-303 stop condition (1) -- forces termination
        # even if a scaffolding bug prevents the success-branch from
        # firing.
        #
        # Discriminator (BUG-1): pre-US-301 ``runReconnectHeartbeat``
        # does not exist -- the import at the top of this file raises
        # ImportError and the test cannot run.
        # ============================================================
        sleepFn = _AdapterAwakenerSleepFn(connection, flipAfterCalls=1)
        ticks = runReconnectHeartbeat(
            connectFn=lambda: connection.connect(),
            isConnectedFn=lambda: connection.isConnected(),
            sleepFn=sleepFn,
            tickIntervalSec=10.0,
            attemptTimeoutSec=_TEST_HEARTBEAT_ATTEMPT_TIMEOUT_SEC,
            maxTicks=2,
        )

        # Heartbeat must have run exactly 2 ticks: tick 1 failed
        # (adapter down -> "failure" outcome -> WARNING + sleep that
        # flips the knob), tick 2 succeeded ("success" outcome ->
        # function returns).
        assert ticks == 2, (
            f"Phase 2 heartbeat tick count: expected exactly 2 ticks "
            f"(tick 1 fails -> sleepFn flips adapter -> tick 2 succeeds); "
            f"got {ticks}.  Discriminator: a tick count of 0 would mean "
            "the heartbeat never ran (BUG-1 regression)."
        )
        assert connection.connectAttempts == 2, (
            f"Phase 2 connect-attempt count: expected exactly 2 attempts "
            f"(one per tick); got {connection.connectAttempts}.  Pre-fix "
            "code logged ZERO retry attempts across 11 hours of PENDING "
            "(Spool 2026-05-08 BUG-1 evidence)."
        )
        # The sleep seam fired exactly once (between tick 1 and tick 2).
        # Tick 2 returned via the success branch BEFORE its post-attempt
        # sleep, so the sleep call count is 1 not 2.
        assert sleepFn.sleepDurations == [10.0], (
            f"Phase 2 sleep cadence: expected exactly one 10.0s sleep "
            f"(per CIO 2026-05-08 verbatim mandate); got "
            f"{sleepFn.sleepDurations}.  A different cadence here means "
            "the heartbeat is not honouring HEARTBEAT_TICK_INTERVAL_SEC."
        )
        # Connection state must reflect the successful tick-2 connect.
        assert connection.isConnected() is True, (
            "Phase 2 post-heartbeat connection state: connect() success "
            "must have flipped _isConnected to True (mirrors a real "
            "OBDLink LX completing its ELM327 + ECU handshake)."
        )

        # BUG-1 discriminator: the canonical heartbeat token must appear
        # in the captured INFO logs.  Pre-US-301 there was no heartbeat
        # function and no canonical token -- 11 hours of journal silence.
        heartbeatLogs = [
            r for r in caplog.records if HEARTBEAT_LOG_PREFIX in r.getMessage()
        ]
        assert len(heartbeatLogs) >= 2, (
            f"Phase 2 heartbeat INFO log: expected >= 2 'RECONNECT "
            f"HEARTBEAT' lines (one per tick); captured "
            f"{len(heartbeatLogs)}.  This is the canonical BUG-1 "
            "discriminator -- pre-US-301 production logged ZERO of "
            "these across 11 hours of PENDING."
        )

        # BUG-1 discriminator (loud-bail half): the V0.24.1 lesson
        # mandates a WARNING-level log on every non-success outcome.
        # Tick 1's failure must have produced one.
        warningLogs = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and 'Reconnect heartbeat tick' in r.getMessage()
        ]
        assert len(warningLogs) >= 1, (
            "Phase 2 loud-bail: expected at least one WARNING-level "
            "'Reconnect heartbeat tick' log on the failed tick 1 attempt "
            "(V0.24.1 anti-pattern lesson -- silent threads = saga); "
            f"captured {len(warningLogs)} WARNINGs."
        )

        # ============================================================
        # Phase 3: simulate the runLoop state-change detection that
        # observes the late-arriving CONNECTED state and fires
        # _handleConnectionRestored.  Production runLoop runs at
        # ``loopSleepInterval`` cadence (default 100 ms); the relevant
        # branch is ``if currentConnectionState != lastConnectionState
        # and currentConnectionState: self._handleConnectionRestored()``.
        # We invoke the handler directly here -- equivalent to one
        # iteration of the runLoop's state-change check after the
        # heartbeat success.
        #
        # Discriminator (BUG-2): pre-US-302 the handler updated display
        # + status fields but did not call
        # _restartDataLoggerOnConnectionRestored (which did not exist),
        # so the outer data logger's start was never invoked from this
        # path.
        # ============================================================
        # Pre-handler the outer logger has not been started.
        assert outerDataLogger.start.call_count == 0
        orchestrator._handleConnectionRestored()

        # BUG-2 discriminator: handler MUST have called the outer
        # data logger's start exactly once.  Pre-US-302 this assertion
        # fires because start was never called.
        assert outerDataLogger.start.call_count == 1, (
            f"Phase 3 BUG-2 wiring: outerDataLogger.start expected to be "
            f"called EXACTLY ONCE from _handleConnectionRestored "
            f"(US-302); was called {outerDataLogger.start.call_count} "
            "times.  Pre-fix code updated display + status but never "
            "(re-)started the data logger -- 8-second window of live "
            "OBD with zero realtime_data rows in production."
        )

        # ============================================================
        # Phase 4: drive one RPM=750 reading through the inner data
        # logger to prove the realtime_data write path is reachable now
        # that the connection is up.  The outer logger's polling thread
        # is NOT spawned in this test (start is the MagicMock); the
        # inner logger's queryParameter + logReading are real production
        # methods and write the row directly.  This mirrors the way
        # US-286 drives the data path without spawning the polling
        # thread (deterministic, no wall-clock dependency on
        # pollingIntervalMs).
        # ============================================================
        reading = innerLogger.queryParameter('RPM')
        innerLogger.logReading(reading)

        rtRows = _readRealtimeDataRows(lateAdapterDb)
        assert len(rtRows) == 1, (
            f"Phase 4 realtime_data write: expected exactly 1 RPM row "
            f"after the post-restoration tick; got {len(rtRows)} rows: "
            f"{rtRows}.  Discriminator: an empty result here would "
            "match the May 4 + May 5 + May 8 production failure mode "
            "(zero engine-on rows captured)."
        )
        paramName, value, dataSource = rtRows[0]
        assert paramName == 'RPM'
        assert value == _RPM_ENGINE_ON
        assert dataSource == 'real', (
            f"realtime_data.data_source must be 'real' for live OBD "
            f"path; got {dataSource!r} (US-212 hygiene)"
        )

        # ============================================================
        # Phase 5: wall-clock budget assertion (US-303 acceptance).
        # The full late-adapter capture pipeline must complete inside
        # the 30-sec test runtime budget.  Production target is 60 sec
        # boot-to-DriveDetector-operational; this synthetic harness
        # compresses that aggressively via FakeClock-style
        # _AdapterAwakenerSleepFn + maxTicks=2 + direct
        # _handleConnectionRestored invocation.
        # ============================================================
        elapsed = time.perf_counter() - testStart
        assert elapsed < _TEST_RUNTIME_BUDGET_SECONDS, (
            f"US-303 runtime budget violated: full late-adapter capture "
            f"pipeline took {elapsed:.2f}s; budget is "
            f"{_TEST_RUNTIME_BUDGET_SECONDS}s.  A regression here would "
            "indicate someone wired a real time.sleep into the heartbeat "
            "or restoration path -- exactly the kind of silent wall-"
            "clock dependence Spool's BUG-1 evidence (11h of silence) "
            "warned about."
        )
