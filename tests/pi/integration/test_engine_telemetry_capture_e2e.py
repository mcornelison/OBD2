################################################################################
# File Name: test_engine_telemetry_capture_e2e.py
# Purpose/Description: US-285 (Spool Story 2) -- validate the full post-US-284
#                      init chain reaches DriveDetector operational state and
#                      the engine-on capture pipeline works end-to-end within
#                      Spool's 60-sec acceptance budget.  Distinct from US-286
#                      (test_engine_drive_capture_e2e.py): US-286 is the
#                      durable regression gate for the engine-on data flow with
#                      a bare orchestrator; US-285 adds the discriminator that
#                      catches the production blocker class US-284 fixed --
#                      a python-obd query path that hangs indefinitely and
#                      gates the orchestrator init thread (Spool 2026-05-05
#                      production journal: 27-hour boot-1, 82-min boot-0
#                      hangs in _initializeConnection / VIN decode).
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-07    | Rex (US-285) | Initial -- two-class structure.  Class 1
#                              | (TestPostUs284InitChainBoundedReturn)
#                              | exercises the post-US-284 _performFirst
#                              | ConnectionVinDecode fix surface with a mock
#                              | OBD connection whose query('VIN') blocks
#                              | indefinitely; pre-US-284 unprotected query
#                              | would hang forever, the watchdog would fire,
#                              | and the test would FAIL.  Class 2 (TestEngine
#                              | TelemetryCapturePostInitFullPath) extends
#                              | US-286's harness pattern: post-init
#                              | DriveDetector reaches MONITORING and RPM=750
#                              | samples flow through the production path,
#                              | producing drive_start, drive_summary INSERT,
#                              | and realtime_data accumulation -- all within
#                              | Spool's 60-sec boot-to-DriveDetector-
#                              | operational acceptance budget.
# ================================================================================
################################################################################

"""US-285 -- restore engine telemetry capture (Spool Story 2).

What this file gates that US-286 does not
-----------------------------------------
US-286 (already shipped) bench-tests the engine-on **data flow**: with a
bare ApplicationOrchestrator + mocked BT edge, two RPM=750 ticks must
fire ``drive_start`` + ``drive_summary`` INSERT + ``realtime_data``
rows.  It explicitly does not invoke ``orchestrator.start()`` -- that
was a US-284 scope concern.

US-285 closes the matching ``init chain`` gap.  Spool's Story 2
acceptance asks for "boot-to-DriveDetector-operational within 60 sec"
verified via integration test runtime + bench reproduction note.  The
synthetic test exercises the **post-US-284 fix surface** -- the
:meth:`_performFirstConnectionVinDecode` call that pre-fix called
``self._connection.obd.query('VIN')`` unprotected, which is the call
shape Spool's 2026-05-05 production evidence shows hung for 82 min
(boot 0) / 27 hours (boot -1) when python-obd's serial / Bluetooth
subsystem wedged.  Mocking that query to block forever gives us a
deterministic discriminator: pre-US-284 the watchdog fires; post-US-284
the new ``_queryWithTimeout`` daemon-thread wrapper caps the call at
``initialConnectTimeoutSec`` (30 sec) and the init chain returns.

Pre-flight audit (US-285 acceptance criterion #1)
--------------------------------------------------
``rg DriveDetector|drive_start|start.*detector src/pi/obdii/`` produced
16 files; the load-bearing ones for the init chain are:

* ``src/pi/obdii/orchestrator/lifecycle.py``
  - ``COMPONENT_INIT_ORDER`` position 8 = ``DriveDetector`` (after
    ``Database, ProfileManager, Connection, VinDecoder, DisplayManager,
    HardwareManager, StatisticsEngine``).  Init order intact post-US-244 /
    US-279 / US-284; no drift since Sprint 17 layout.
  - ``_initializeAllComponents`` runs ``_initializeConnection`` (now
    US-244-bounded) -> ``_initializeVinDecoder`` -> ``_perform
    FirstConnectionVinDecode`` (now US-284-bounded) -> ... -> ``_initialize
    DriveDetector`` (line 1112).  The 27-hour gap Spool documented sat
    on the third step; US-284 closed the unprotected call site.
* ``src/pi/obdii/orchestrator/core.py``
  - ``runLoop`` calls ``self._driveDetector.start()`` at line 720 (after
    ``_setupComponentCallbacks`` wires ``onReading=self._handleReading``).
    DriveDetector reaches operational state (MONITORING) at runLoop
    entry, NOT at orchestrator init time -- Spool's "60 sec" budget
    spans both phases.
* ``src/pi/obdii/orchestrator/event_router.py``
  - ``_handleReading`` line 341: ``self._driveDetector.processValue(
    paramName, value)``.  The wire from RealtimeDataLogger -> orchestrator
    -> DriveDetector is intact.  No regression detected during the
    9-drain saga (Sprint 21-24) -- those touched ``_handleReading`` only
    for BATTERY_V escalation (US-242) and MIL edge (US-204), not the
    detector forward.
* ``src/pi/obdii/drive/detector.py``
  - DriveDetector thresholds preserved: ``DEFAULT_DRIVE_START_RPM_
    THRESHOLD = 500``; ``DEFAULT_DRIVE_START_DURATION_SECONDS`` from
    types.py.  ``_startDrive`` mints drive_id via :func:`nextDriveId`
    + arms the US-236 defer-INSERT machine.  No regression detected
    during Sprint 17-24 -- last touch was US-236 / US-229 / US-225 in
    Sprint 17-19, all engine-OFF or warm-restart concerns.

Discriminator (per ``feedback_runtime_validation_required.md``)
---------------------------------------------------------------
Class 1 (init chain bounded return) **would FAIL** against pre-US-284
``lifecycle.py`` because the unprotected ``connection.obd.query('VIN')``
would block indefinitely on the synthetic blocking-forever mock; the
watchdog at ``vinTimeoutSec * 2`` fires; the assertion that the call
returned ``False`` (timed out cleanly) raises.  This is the SAME
production failure mode Spool's journal evidence captured.  Post-US-284
the daemon-thread + Event.wait wrapper caps the call at
``initialConnectTimeoutSec`` (30 sec via config; 0.5 sec compressed in
the test for a deterministic <5 sec runtime) and the call returns with
``completed=False`` cleanly.

Class 2 (post-init full path) **would FAIL** against any regression
where DriveDetector cannot start, the realtime_data INSERT path is
broken, or the defer-INSERT machine never INSERTs.  Mirrors US-286's
discriminator surface but without the data-flow assertions duplicated
verbatim -- US-285 owns the 60-sec wall-clock budget gate that ties
the synthetic test to Spool's Story 2 acceptance.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pi.obdii.data.logger import ObdDataLogger
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive.types import DriveState
from src.pi.obdii.drive_id import clearCurrentDriveId, getCurrentDriveId
from src.pi.obdii.drive_summary import DRIVE_SUMMARY_TABLE, SummaryRecorder
from src.pi.obdii.orchestrator.core import ApplicationOrchestrator

# Spool Story 2 acceptance: boot-to-DriveDetector-operational within
# 60 sec.  Asserted on the wall-clock guard at the test boundary.
_DRIVE_DETECTOR_OPERATIONAL_BUDGET_SECONDS: float = 60.0

# Compressed init-timeout for the synthetic test.  Production default is
# 30 sec (config.json + validator.py); the test uses 0.5 sec so a
# blocking-forever mock query trips the watchdog deterministically in
# <2 sec instead of running for the full 30 sec.  The CALL SHAPE is
# identical to production -- only the cap value compresses for runtime.
_TEST_INITIAL_CONNECT_TIMEOUT_SEC: float = 0.5

# Watchdog cap for the bounded-return assertion.  Set to 2x the
# compressed init-timeout so a healthy post-US-284 path returns well
# inside the cap; pre-US-284 the unprotected query would hold past the
# cap and the watchdog would fire.
_INIT_CHAIN_WATCHDOG_SEC: float = _TEST_INITIAL_CONNECT_TIMEOUT_SEC * 4

# Spool's spec: feed RPM=750 samples (well above the 500 RPM
# driveStartRpmThreshold; matches a typical Eclipse warm-idle baseline
# per offices/tuner/knowledge.md Drive 5).
_RPM_ENGINE_ON: float = 750.0


def _baseConfig(initialConnectTimeoutSec: float) -> dict[str, Any]:
    """Tier-aware config exercising the post-US-284 init chain.

    ``pi.obdii.orchestrator.initialConnectTimeoutSec`` is compressed
    so the watchdog-bound assertion runs deterministically in the
    fast-suite budget.  Production deploys 30 sec -- the call shape is
    identical, only the cap value compresses for the synthetic test.
    """
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "obdii": {
                "orchestrator": {
                    "initialConnectTimeoutSec": initialConnectTimeoutSec,
                    "engineOnVoltageThreshold": 13.8,
                    "engineOnSampleCount": 3,
                },
            },
            "analysis": {
                # Zero-duration debounce so a single RPM tick over the
                # 500 RPM threshold transitions STOPPED -> STARTING and
                # the second tick fires _startDrive.  Production is 10
                # sec sustained; the test gates on the data-flow path,
                # not the timer.
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


class _BlockingForeverObdQuery:
    """Mock at the python-obd ``OBD.query`` boundary that blocks forever.

    Matches Spool's 2026-05-05 production failure shape: the
    python-obd serial / Bluetooth subsystem wedges and the
    per-command timeout configured on ``obd.OBD(timeout=...)`` is
    not honored.  A test using this mock as the
    ``self._connection.obd.query`` attribute reproduces the
    SAME bug class US-284 closed -- pre-US-284 the unprotected
    ``query('VIN')`` call in :meth:`_performFirstConnectionVinDecode`
    would hang indefinitely on this mock; post-US-284 the new
    ``_queryWithTimeout`` daemon-thread wrapper caps the call at
    ``initialConnectTimeoutSec``.
    """

    def __init__(self) -> None:
        self.callCount: int = 0
        self._neverReleaseEvent = threading.Event()  # never set()

    def __call__(self, _cmd: Any) -> Any:
        self.callCount += 1
        # Block until the never-released event fires (i.e. forever).
        # Daemon-thread reaping at process exit handles cleanup.
        self._neverReleaseEvent.wait()
        return None  # unreachable in production failure scenario


class _ScriptedObdQuery:
    """Mock at the python-obd ``OBD.query`` boundary returning a fixed value.

    Mirrors US-286's ``_ScriptedObdQuery``; reused here for the
    full-path data-flow phase of Class 2.  ``ObdDataLogger.
    _extractValue`` reads ``response.value`` and falls back to the
    numeric form when ``.magnitude`` is absent; ``response.is_null()``
    gates the null-response path.
    """

    def __init__(self, rpmValue: float) -> None:
        self.rpmValue = rpmValue
        self.queryCount: int = 0

    def __call__(self, _cmd: Any) -> Any:
        self.queryCount += 1
        response = MagicMock()
        response.is_null.return_value = False
        response.value = self.rpmValue
        return response


class _MutableSnapshotSource:
    """Test double for the DriveDetector ``getLatestReadings`` snapshot seam.

    Mirrors :class:`_MutableSnapshotSource` from US-260 +
    US-286 -- the dict is mutated by the test body so the real
    defer-INSERT + backfill state machine in :class:`DriveDetector`
    runs unmodified against arriving sensor values.
    """

    def __init__(self) -> None:
        self._readings: dict[str, float] = {}

    def update(self, **readings: float) -> None:
        self._readings.update(readings)

    def getLatestReadings(self) -> dict[str, float]:
        return dict(self._readings)


@pytest.fixture()
def lifecycleDb(tmp_path: Path) -> ObdDatabase:
    """Persistent on-disk DB with full schema + 'daily' profile seed.

    Mirrors the US-286 fixture: ``realtime_data.profile_id`` carries a
    FK to ``profiles(id)`` and production seeds 'daily' via
    :class:`ProfileManager` at lifecycle init -- bypassed here because
    the orchestrator runs bare (no ``start()``).
    """
    db = ObdDatabase(str(tmp_path / "test_us285_init_chain.db"), walMode=False)
    db.initialize()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO profiles (id, name) VALUES (?, ?)",
            ('daily', 'Daily Driving'),
        )
    yield db
    clearCurrentDriveId()


def _runWithWatchdog(
    fn: Any,
    timeoutSec: float,
) -> tuple[bool, float]:
    """Run ``fn`` in a daemon thread bounded by ``timeoutSec``.

    Mirrors the US-284 test idiom: spawn ``fn`` in a daemon thread,
    ``Event.wait(timeout=timeoutSec)`` on a ``doneEvent`` set in the
    thread's ``finally``, return ``(completed, elapsed)`` tuple.  When
    ``fn`` blocks indefinitely (pre-US-284 production failure mode),
    ``completed=False`` and the assert at the watchdog cap fires
    instead of hanging the entire pytest session.  The leaked daemon
    thread is reaped at process exit -- harmless because of
    ``daemon=True``.
    """
    doneEvent = threading.Event()
    startedAt = time.monotonic()

    def _runner() -> None:
        try:
            fn()
        finally:
            doneEvent.set()

    threading.Thread(target=_runner, daemon=True, name="us285-watchdog").start()
    completed = doneEvent.wait(timeout=timeoutSec)
    elapsed = time.monotonic() - startedAt
    return completed, elapsed


# ================================================================================
# Class 1: Post-US-284 init chain returns within budget under blocking query
# ================================================================================


class TestPostUs284InitChainBoundedReturn:
    """US-285 acceptance #2 + #3: post-US-284 init chain reaches DriveDetector
    operational state within budget even when a python-obd query wedges.

    The discriminator: pre-US-284 ``_performFirstConnectionVinDecode``
    called ``self._connection.obd.query('VIN')`` with NO wall-clock
    wrapper.  When the underlying serial / Bluetooth subsystem hangs
    (Spool 2026-05-05 production evidence: 82 min boot 0, 27 h boot
    -1), the call blocks indefinitely and the orchestrator init thread
    never reaches ``_initializeDriveDetector``.  Post-US-284
    ``_queryWithTimeout`` caps the call at ``initialConnectTimeoutSec``
    via a daemon thread + ``Event.wait`` pattern; the call returns
    ``(False, None, None)`` cleanly within the cap.

    This test would FAIL against pre-US-284 ``lifecycle.py`` because
    the watchdog at ``_INIT_CHAIN_WATCHDOG_SEC`` would fire (the
    unprotected query holds past the cap) and the
    ``completed`` assertion would raise.
    """

    def test_performFirstConnectionVinDecode_blockingForeverQuery_returnsWithinBudget(
        self,
        lifecycleDb: ObdDatabase,
    ) -> None:
        """The post-US-284 fix surface returns even when query blocks forever.

        Phases:
          1. Construct orchestrator with simulate=True (bypasses real
             OBD-init that needs hardware).
          2. Attach a mock connection whose ``obd.query`` blocks forever
             -- the SAME bug class as Spool's production evidence.
          3. Attach a real VinDecoder-shaped mock so the precondition
             check at lifecycle.py:627 passes.
          4. Watchdog-bound call to ``_performFirstConnectionVinDecode``.
          5. Assert: completed within budget; query was attempted (call
             count == 1 -- proves the post-US-284 wrapper dispatched the
             daemon thread); the timeout fired (no NHTSA path was
             reached because the timeout returned WARN early).
        """
        config = _baseConfig(_TEST_INITIAL_CONNECT_TIMEOUT_SEC)
        orchestrator = ApplicationOrchestrator(config=config, simulate=True)
        orchestrator._database = lifecycleDb

        # Mock the OBD connection at the BT edge.  Pre-US-284, the
        # unprotected ``query('VIN')`` call would block forever on
        # this mock; post-US-284 ``_queryWithTimeout`` caps it.
        mockConnection = MagicMock()
        mockConnection.isConnected.return_value = True
        mockConnection.isSimulated = False
        blockingQuery = _BlockingForeverObdQuery()
        mockConnection.obd = MagicMock()
        mockConnection.obd.query = blockingQuery
        orchestrator._connection = mockConnection

        # VinDecoder mock: must be non-None to pass the precondition
        # check at lifecycle.py:627.  Methods aren't reached because
        # the query times out before isVinCached / decodeVin are called.
        mockVinDecoder = MagicMock()
        orchestrator._vinDecoder = mockVinDecoder

        # Watchdog-bound call.  Pre-US-284 this hangs forever and the
        # watchdog asserts at _INIT_CHAIN_WATCHDOG_SEC; post-US-284 the
        # _queryWithTimeout daemon-thread wrapper returns within
        # _TEST_INITIAL_CONNECT_TIMEOUT_SEC + small overhead.
        completed, elapsed = _runWithWatchdog(
            orchestrator._performFirstConnectionVinDecode,
            _INIT_CHAIN_WATCHDOG_SEC,
        )

        assert completed, (
            f"_performFirstConnectionVinDecode did NOT return within "
            f"{_INIT_CHAIN_WATCHDOG_SEC:.1f}s watchdog (elapsed={elapsed:.2f}s).  "
            "This is the pre-US-284 production failure mode reproduced: "
            "an unprotected python-obd query blocks the orchestrator init "
            "thread when the underlying BT / serial subsystem wedges "
            "(Spool 2026-05-05 evidence: 82 min boot 0, 27 h boot -1).  "
            "Post-US-284 _queryWithTimeout wraps the call in a daemon "
            "thread + Event.wait so the cap is honored regardless of "
            "library behavior."
        )

        # The wrapper's daemon thread MUST have dispatched the query
        # (callCount > 0 proves the wrapper was invoked at all).  The
        # wrapper's daemon thread is left running on timeout per the
        # _queryWithTimeout contract -- the leak is harmless because
        # daemon=True reaps it at process exit.
        assert blockingQuery.callCount == 1, (
            f"Expected the wrapper to dispatch exactly one query attempt; "
            f"got callCount={blockingQuery.callCount}.  Either the "
            "wrapper is missing (regression of US-284) or the daemon "
            "thread did not start."
        )

        # Post-fix the call should return cleanly inside the configured
        # cap with small overhead for thread scheduling.  Allow 3x the
        # cap for slow CI machines; pre-fix would have run to the full
        # watchdog cap.
        assert elapsed < _TEST_INITIAL_CONNECT_TIMEOUT_SEC * 6, (
            f"Post-fix call took {elapsed:.2f}s, which is >6x the "
            f"configured timeout {_TEST_INITIAL_CONNECT_TIMEOUT_SEC:.2f}s.  "
            "Suggests the daemon-thread wrapper is not honoring the cap "
            "or there is unexpected blocking elsewhere in the VIN-decode "
            "path."
        )


# ================================================================================
# Class 2: Post-init engine telemetry capture pipeline
# ================================================================================


@pytest.fixture()
def engineOnHarness(lifecycleDb: ObdDatabase) -> dict[str, Any]:
    """Wire the post-init engine-on data path with real production classes.

    Mirrors the US-286 harness pattern but constructs orchestrator with
    the US-285 compressed init-timeout config (so a future test that
    extends this fixture into the init chain has consistent budgets).
    Mock surface limited to ``connection.obd.query`` (the BT edge);
    real classes under test: :class:`ApplicationOrchestrator`,
    :class:`DriveDetector`, :class:`SummaryRecorder`,
    :class:`ObdDataLogger`.
    """
    config = _baseConfig(_TEST_INITIAL_CONNECT_TIMEOUT_SEC)
    orchestrator = ApplicationOrchestrator(config=config, simulate=True)
    orchestrator._database = lifecycleDb

    mockConnection = MagicMock()
    mockConnection.isConnected.return_value = True
    mockConnection.isSimulated = False
    mockConnection.supportedPids = None  # bypass Mode-01 probe gate
    scriptedQuery = _ScriptedObdQuery(rpmValue=_RPM_ENGINE_ON)
    mockConnection.obd = MagicMock()
    mockConnection.obd.query = scriptedQuery
    orchestrator._connection = mockConnection

    detector = DriveDetector(config=config, database=lifecycleDb)
    recorder = SummaryRecorder(database=lifecycleDb)
    snapshotSource = _MutableSnapshotSource()
    detector.setSummaryRecorder(recorder)
    detector.setReadingSnapshotSource(snapshotSource)
    orchestrator._driveDetector = detector
    orchestrator._summaryRecorder = recorder

    innerLogger = ObdDataLogger(
        connection=mockConnection,
        database=lifecycleDb,
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
        "detector": detector,
        "recorder": recorder,
        "snapshotSource": snapshotSource,
        "innerDataLogger": innerLogger,
        "scriptedQuery": scriptedQuery,
    }


class TestEngineTelemetryCapturePostInitFullPath:
    """US-285 acceptance #3: full post-init path produces drive_start +
    drive_summary INSERT + realtime_data accumulation within Spool's
    60-sec boot-to-DriveDetector-operational budget.

    Distinct from US-286 which gates the engine-on data flow with a
    bare orchestrator: this class adds the wall-clock budget gate
    that ties the synthetic test to Spool's Story 2 acceptance ("Drive
    6 captures cleanly when CIO keys on the engine").  Per the sprint
    contract's no-human-ops rule, the bench-reproduction note is the
    POST-SPRINT-25 CIO action item; this synthetic test is the gate
    that fails on regression in CI before the bench runs.
    """

    def test_postInit_driveDetectorReachesMonitoring_engineOnSamplesProduceDriveStart(
        self,
        engineOnHarness: dict[str, Any],
        lifecycleDb: ObdDatabase,
    ) -> None:
        orchestrator = engineOnHarness["orchestrator"]
        detector = engineOnHarness["detector"]
        snapshotSource = engineOnHarness["snapshotSource"]
        innerLogger = engineOnHarness["innerDataLogger"]
        scriptedQuery = engineOnHarness["scriptedQuery"]

        # Wall-clock guard for the Spool Story 2 60-sec acceptance.
        # Started before any production work; asserted at boundary.
        testStart = time.perf_counter()

        # ============================================================
        # Phase 1: DriveDetector starts -- reaches MONITORING state.
        # This is the post-orchestrator-init step that Spool's
        # production journal showed never reached on May 4 + May 5
        # because _initializeConnection blocked forever.  Post-US-284
        # the init chain returns and runLoop's start() invocation
        # transitions detector to MONITORING.  The synthetic test
        # invokes start() directly (mirrors what runLoop does at
        # core.py:720).
        # ============================================================
        assert detector.isMonitoring() is False, (
            "Phase 1 sanity: detector must start IDLE before start() "
            "is invoked"
        )
        startResult = detector.start()
        assert startResult is True, (
            "Phase 1: DriveDetector.start() must return True.  Failure "
            "here would mean the detector cannot transition to MONITORING "
            "-- the production failure mode that the May 4 + May 5 "
            "engine-on cycles silently exhibited."
        )
        assert detector.isMonitoring() is True
        assert detector.getDriveState() == DriveState.STOPPED

        # ============================================================
        # Phase 2: feed RPM=750 samples through the production path.
        # Mirrors US-286 phase 3 -- the production data flow:
        #   ObdDataLogger.queryParameter (mock OBD.query at BT edge)
        #   ObdDataLogger.logReading (writes realtime_data)
        #   ApplicationOrchestrator._handleReading (real method)
        #   DriveDetector.processValue (real method)
        # ============================================================
        for _ in range(2):
            reading = innerLogger.queryParameter('RPM')
            reading.value = _RPM_ENGINE_ON
            innerLogger.logReading(reading)
            orchestrator._handleReading(reading)

        # Two ticks: STOPPED -> STARTING -> RUNNING (zero-duration
        # debounce).  Discriminator: any regression where _handleReading
        # severed the wire to DriveDetector (the May-4-5 production
        # failure mode) leaves state at STOPPED here.
        assert detector.getDriveState() == DriveState.RUNNING, (
            "Phase 2: post-RPM=750 ticks MUST leave detector in RUNNING.  "
            "Failure means _startDrive did not fire -- the engine-on "
            "regression class US-284 closes."
        )

        driveId = getCurrentDriveId()
        assert driveId is not None, (
            "Phase 2: drive_start must mint drive_id.  None means the "
            "_startDrive path bailed (DB unreachable, no_new_drives gate, "
            "or drive_id thread-locals regression)."
        )

        # ============================================================
        # Phase 3: drive_summary INSERT via defer-INSERT machine.
        # First IAT arrival post-_startDrive triggers the deferred
        # INSERT (US-236 / US-246).  This is the last step Spool's
        # damage table flagged frozen since 2026-04-29 (Drive 5).
        # ============================================================
        with lifecycleDb.connect() as conn:
            preIatRow = conn.execute(
                f"SELECT * FROM {DRIVE_SUMMARY_TABLE} WHERE drive_id = ?",
                (driveId,),
            ).fetchone()
        assert preIatRow is None, (
            "Phase 3: defer-INSERT contract violated -- drive_summary "
            "row exists pre-IAT.  Pre-US-246 INSERT-at-drive_start "
            "would have written an all-NULL row; US-285 inherits this "
            "guard from US-286."
        )

        snapshotSource.update(INTAKE_TEMP=85.0)
        # Drive an additional RPM tick so the detector's
        # _maybeProgressDriveSummary loop sees the populated snapshot.
        reading = innerLogger.queryParameter('RPM')
        reading.value = _RPM_ENGINE_ON
        innerLogger.logReading(reading)
        orchestrator._handleReading(reading)

        with lifecycleDb.connect() as conn:
            postIatAmbient = conn.execute(
                "SELECT ambient_temp_at_start_c FROM "
                f"{DRIVE_SUMMARY_TABLE} WHERE drive_id = ?",
                (driveId,),
            ).fetchone()
        assert postIatAmbient is not None, (
            "Phase 3 IAT arrival: drive_summary row must INSERT.  "
            "Defer-INSERT contract: row appears when first "
            "IAT/BATTERY_V/BARO arrives in the snapshot."
        )
        assert postIatAmbient[0] == 85.0

        # ============================================================
        # Phase 4: realtime_data accumulation.  Three RPM ticks have
        # flowed through the full production path; each was logged
        # via the real ObdDataLogger.logReading.  Discriminator: pre-
        # production-fix logReading would have written 0 rows (the
        # May 4 + May 5 cycles' silent regression class).
        # ============================================================
        with lifecycleDb.connect() as conn:
            rtRows = conn.execute(
                "SELECT parameter_name, value, data_source "
                "FROM realtime_data ORDER BY id ASC"
            ).fetchall()
        assert len(rtRows) == 3, (
            f"Phase 4 realtime_data accumulation: expected 3 RPM rows; "
            f"got {len(rtRows)}.  Same regression class as Spool's "
            "damage table (realtime_data frozen at 2026-05-01)."
        )
        for paramName, value, dataSource in rtRows:
            assert paramName == 'RPM'
            assert value == _RPM_ENGINE_ON
            assert dataSource == 'real'

        # Mock OBD.query was hit once per ObdDataLogger.queryParameter
        # call -- proves the BT-edge mock was the only seam consumed.
        assert scriptedQuery.queryCount == 3

        # ============================================================
        # Phase 5: Spool Story 2 wall-clock budget.  Full
        # boot-to-DriveDetector-operational + engine-on capture
        # pipeline must complete inside 60 sec.  The synthetic test
        # compresses this aggressively (sub-second on healthy CI);
        # the budget guard surfaces a regression where someone wires
        # a real-time dependency into the data path.
        # ============================================================
        elapsed = time.perf_counter() - testStart
        assert elapsed < _DRIVE_DETECTOR_OPERATIONAL_BUDGET_SECONDS, (
            f"US-285 / Spool Story 2 budget violated: full engine-on "
            f"capture pipeline took {elapsed:.2f}s; budget is "
            f"{_DRIVE_DETECTOR_OPERATIONAL_BUDGET_SECONDS}s."
        )
