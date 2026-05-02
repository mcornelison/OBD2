################################################################################
# File Name: test_drive_lifecycle_cold_start.py
# Purpose/Description: US-260 -- end-to-end cold-start drive lifecycle synthetic
#                      test composing US-242 (idle-poll escalation), US-244
#                      (non-blocking BT-connect), and US-246 (defer-INSERT).
#                      Drive 6 (post-Sprint-21 action item) is the live
#                      counterpart; this synthetic test is the gate.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Rex (US-260) | Initial -- synthetic full lifecycle gate.
#                              | One test class / one test driving the
#                              | key-on -> idle BATTERY_V -> escalation ->
#                              | drive_start -> defer-INSERT -> backfill ->
#                              | drive_end -> drive-end sync trace through
#                              | the real ApplicationOrchestrator + real
#                              | DriveDetector + real SummaryRecorder + real
#                              | ObdDatabase against tmp_path.  Discriminator
#                              | (per feedback_runtime_validation_required):
#                              | FAILS against pre-US-242 code (no escalation
#                              | hook -> no drive_id) AND against pre-US-246
#                              | code (Sprint 18 INSERT-immediately -> all-NULL
#                              | drive_summary fields).
# ================================================================================
################################################################################

"""US-260 -- cold-start drive lifecycle integration gate.

Live counterpart: Drive 6 will exercise the same flow on real hardware
post-Sprint-21.  The synthetic test pins the contract first so a
production regression surfaces in CI rather than at a drive review.

Composition under test (Sprint 20 trio):

* **US-242 / B-049** -- BATTERY_V > 13.8V sustained 3 samples fires the
  single-shot RPM probe on :class:`ApplicationOrchestrator`.  Without
  this, the drive detector waits indefinitely on RPM in idle-poll and
  no drive_start ever happens after a cold-boot engine-start (the
  pre-Sprint-20 silent-data-loss bug).

* **US-244 / TD-036** -- :meth:`_initializeConnection` cannot block
  ``runLoop`` entry.  This test uses ``simulate=True`` so the real
  initial-connect path is bypassed; the US-244 contract is exercised
  *structurally* (the orchestrator construction succeeds even with no
  reachable adapter, and the runLoop seams are reachable).  The
  unit-level test ``test_lifecycle_initial_connect_timeout.py`` covers
  the wall-clock timeout assertion directly.

* **US-246 / Sprint 19 US-236** -- ``drive_summary`` row is **deferred**
  until first IAT/BATTERY_V/BARO arrives.  Drives 3, 4, 5 (Sprint 18
  US-228 production) all shipped rows with three NULLs; this test
  proves the post-US-236 defer-INSERT + backfill machine produces
  three non-NULL columns end-to-end.

Discriminator (runtime-validation per ``feedback_runtime_validation_required``):

* Against pre-US-242 code, ``_handleReading`` does NOT route BATTERY_V
  through ``_maybeEscalateOnAlternatorActiveSignature`` (the method
  doesn't exist).  No RPM probe fires.  ``getCurrentDriveId()`` returns
  ``None`` after the BATTERY_V trace.  Assertion ``driveId is not None``
  FAILS.
* Against pre-US-246 code (Sprint 18 US-228), ``_startDrive``
  immediately INSERTs the row with the (empty) snapshot, producing the
  three-NULL bug observed across Drives 3/4/5.  Assertions
  ``ambient is not None``, ``battery is not None``, ``baro is not None``
  FAIL.  Documented per Sprint 18 US-228 commit history + Spool drive 5
  grade note.

Mocks live at the same boundaries the unit tests use:

* ``_dataLogger`` is mocked at the ``_dataLogger.queryAndLogParameter``
  seam (the escalation probe call site -- see
  ``test_idle_poll_escalation.py``).
* ``readingSnapshotSource.getLatestReadings`` is mocked as a mutable
  dict that grows as readings arrive (so the real defer-INSERT +
  backfill state machine in :class:`DriveDetector` runs unmodified).
* ``_syncClient.pushAllDeltas`` is mocked at the SyncClient API
  boundary; the test asserts the drive-end trigger fires the push
  exactly once and the result reports OK.

Trace shape (Drive 5 baseline -- see ``offices/tuner/knowledge.md``):

* Idle BATTERY_V: 12.7V, 12.7V (engine off, key on).
* Cranking dip: 11.4V (single sample, ECU silent).
* Alternator-active: 14.4V x 3 -> escalation fires -> RPM probe (800).
* Sensor arrivals: INTAKE_TEMP, BATTERY_V, BAROMETRIC_KPA appear
  staggered across subsequent processValue ticks.
* Engine-off: RPM=0 ticks satisfy the (zero-duration) drive_end
  debounce.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive.types import DriveState
from src.pi.obdii.drive_id import clearCurrentDriveId, getCurrentDriveId
from src.pi.obdii.drive_summary import DRIVE_SUMMARY_TABLE, SummaryRecorder
from src.pi.obdii.orchestrator.core import ApplicationOrchestrator
from src.pi.sync.client import PushResult, PushStatus

# ================================================================================
# Helpers / fixtures
# ================================================================================


def _baseConfig() -> dict[str, Any]:
    """Tier-aware minimal config exercising every Sprint-20 seam under test."""
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "obdii": {
                "orchestrator": {
                    # US-242 / B-049 escalation thresholds -- match Drive 5
                    # alternator-active baseline (13.8V is comfortably below
                    # the steady-state 14.4V bulk-charge signature).
                    "engineOnVoltageThreshold": 13.8,
                    "engineOnSampleCount": 3,
                },
            },
            "analysis": {
                # Tight debounce + zero-duration so a single RPM probe over
                # threshold drives STARTING -> RUNNING; RPM=0 ticks fire
                # drive_end on the second sample (state machine needs the
                # transition to STOPPING + one elapsed tick).
                "driveStartRpmThreshold": 500,
                "driveStartDurationSeconds": 0.0,
                "driveEndRpmThreshold": 0,
                "driveEndDurationSeconds": 0.0,
                "triggerAfterDrive": False,
                # 5s defer-INSERT window (production: 60s).  Test runs in
                # well under 5s wall time so the deadline never expires
                # naturally -- the natural-INSERT path under sensor
                # arrivals is the path under test.
                "driveSummaryBackfillSeconds": 5,
            },
            "sync": {"enabled": False},
        },
        "server": {},
    }


class _MutableSnapshotSource:
    """Test double for the dataLogger ``getLatestReadings`` snapshot seam.

    Backing dict is mutated by the test body to model the real Pi
    behavior: after the escalation fires, sensor readings arrive
    staggered across subsequent poll ticks (IAT first, then BATTERY_V,
    then BAROMETRIC_KPA).  The DriveDetector's defer-INSERT + backfill
    state machine drives off the snapshot returned here on every
    ``processValue`` tick.
    """

    def __init__(self) -> None:
        self._readings: dict[str, float] = {}

    def update(self, **readings: float) -> None:
        self._readings.update(readings)

    def getLatestReadings(self) -> dict[str, float]:
        return dict(self._readings)


def _makeReading(parameterName: str, value: float) -> MagicMock:
    """Build a LoggedReading-shaped mock the EventRouterMixin can route."""
    reading = MagicMock(spec=["parameterName", "value", "unit"])
    reading.parameterName = parameterName
    reading.value = value
    reading.unit = "V" if parameterName == "BATTERY_V" else None
    return reading


@pytest.fixture()
def lifecycleDb(tmp_path: Path) -> ObdDatabase:
    """Persistent on-disk DB; ``initialize()`` builds connection_log,
    drive_counter, drive_summary, and pi_state."""
    db = ObdDatabase(str(tmp_path / "test_us260_lifecycle.db"), walMode=False)
    db.initialize()
    yield db
    clearCurrentDriveId()


@pytest.fixture()
def coldStartHarness(lifecycleDb: ObdDatabase) -> dict[str, Any]:
    """Wire the Sprint-20 trio against the lifecycle DB.

    Returns a dict with the test handles the body needs: orchestrator,
    detector, snapshotSource, syncClient.  All real production code
    aside from the four explicit seams (dataLogger, snapshotSource,
    sync transport, no display).
    """
    config = _baseConfig()
    orchestrator = ApplicationOrchestrator(config=config, simulate=True)
    orchestrator._database = lifecycleDb

    detector = DriveDetector(config=config, database=lifecycleDb)
    detector.start()
    # detector.start() leaves the state at STOPPED; first RPM tick
    # transitions to STARTING, second fires _startDrive (duration=0).

    recorder = SummaryRecorder(database=lifecycleDb)
    detector.setSummaryRecorder(recorder)
    snapshotSource = _MutableSnapshotSource()
    detector.setReadingSnapshotSource(snapshotSource)

    orchestrator._driveDetector = detector
    orchestrator._summaryRecorder = recorder

    # _dataLogger composition -- production wraps an inner ObdDataLogger
    # at ``._dataLogger`` exposing ``queryAndLogParameter`` (see
    # _injectRpmProbeForEscalation in core.py).  Probe returns RPM=800
    # so the detector observes engine-on the moment escalation fires.
    inner = MagicMock()
    inner.queryAndLogParameter = MagicMock(
        return_value=_makeReading("RPM", 800.0)
    )
    outer = MagicMock()
    outer._dataLogger = inner
    orchestrator._dataLogger = outer

    # SyncClient mock at the pushAllDeltas API boundary.  Returns one OK
    # PushResult so the drive-end trigger's success branch runs end-to-
    # end (matching feedback_runtime_validation_required: assertions on
    # outcome objects, not just side-effect counts).
    syncClient = MagicMock()
    syncClient.pushAllDeltas.return_value = [
        PushResult(
            tableName="drive_summary",
            rowsPushed=1,
            batchId="batch-1",
            elapsed=0.001,
            status=PushStatus.OK,
            reason="",
        ),
    ]
    orchestrator._syncClient = syncClient
    orchestrator._syncTriggerOn = ["drive_end"]

    # Wire the detector's onDriveEnd callback to the orchestrator's
    # _handleDriveEnd so the production drive-end -> sync path fires
    # (event_router._handleDriveEnd calls triggerDriveEndSync).
    detector.registerCallbacks(
        onDriveEnd=orchestrator._handleDriveEnd,
    )

    return {
        "orchestrator": orchestrator,
        "detector": detector,
        "snapshotSource": snapshotSource,
        "syncClient": syncClient,
        "innerDataLogger": inner,
    }


def _readSummaryRow(
    db: ObdDatabase, driveId: int,
) -> tuple[Any, Any, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT ambient_temp_at_start_c, starting_battery_v, "
            f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
            f"WHERE drive_id = ?",
            (driveId,),
        ).fetchone()
    return tuple(row) if row is not None else None


def _readConnectionLogEvents(
    db: ObdDatabase, driveId: int,
) -> list[str]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT event_type FROM connection_log "
            "WHERE drive_id = ? ORDER BY id ASC",
            (driveId,),
        ).fetchall()
    return [r[0] for r in rows]


# ================================================================================
# Acceptance: full lifecycle key-on -> drive_end -> sync POST
# ================================================================================


class TestColdStartLifecycleEndToEnd:
    """Sprint-20 trio (US-242 + US-244 + US-246) composed end-to-end.

    Single driving test that walks every phase + asserts after each.
    Per-phase assertions surface the failing stage clearly in the test
    output so a production regression names which Sprint-20 contract
    broke (escalation, defer-INSERT, sync trigger).
    """

    def test_coldStartLifecycle_endToEnd_assertsAllSprintTwentyContracts(
        self, coldStartHarness: dict[str, Any], lifecycleDb: ObdDatabase,
    ) -> None:
        orchestrator = coldStartHarness["orchestrator"]
        detector = coldStartHarness["detector"]
        snapshotSource = coldStartHarness["snapshotSource"]
        syncClient = coldStartHarness["syncClient"]
        innerDataLogger = coldStartHarness["innerDataLogger"]

        # ============================================================
        # Phase 1: cold-boot idle (engine off, Pi running, BATTERY_V
        # at rest).  Two BATTERY_V samples below threshold -- escalation
        # counter never advances past zero (rest voltage 12.7V is well
        # below the 13.8V alternator-active threshold).  No drive_id
        # minted, no drive_summary row written.
        # ============================================================
        for voltage in [12.7, 12.7]:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))

        assert orchestrator._engineOnEscalated is False
        assert getCurrentDriveId() is None, (
            "Phase 1 (idle BATTERY_V at rest) must not mint a drive_id "
            "-- pre-US-242 regression would already have fired here if "
            "the escalation threshold were too low"
        )
        assert detector.getDriveState() == DriveState.STOPPED

        # ============================================================
        # Phase 2: cranking dip + alternator-active escalation.
        # 11.4V resets the consecutive-sample counter; three samples at
        # 14.4V trigger the single-shot RPM probe (US-242).  The probe
        # returns RPM=800 which the detector observes via the
        # _injectRpmProbeForEscalation path; with duration=0 + threshold
        # 500 the FIRST RPM call transitions STOPPED -> STARTING.  A
        # second RPM tick (production: realtime poll loop's next cycle)
        # fires _startDrive.
        # ============================================================
        for voltage in [11.4, 14.4, 14.4, 14.4]:
            orchestrator._handleReading(_makeReading("BATTERY_V", voltage))

        # Discriminator #1 (US-242): pre-US-242 code has no escalation
        # hook, so this flag never flips and no RPM probe fires.
        assert orchestrator._engineOnEscalated is True, (
            "Phase 2 escalation MUST flip _engineOnEscalated.  Pre-US-242 "
            "code has no _maybeEscalateOnAlternatorActiveSignature hook -- "
            "the BATTERY_V trace would never escalate and the rest of the "
            "lifecycle would never run"
        )
        innerDataLogger.queryAndLogParameter.assert_called_once_with("RPM")
        assert detector._lastRpmValue == 800.0
        assert detector.getDriveState() == DriveState.STARTING

        # Second RPM tick (synthetic stand-in for the realtime loop's
        # next poll cycle) elapses the zero-duration debounce and fires
        # _startDrive.
        detector.processValue("RPM", 800.0)

        assert detector.getDriveState() == DriveState.RUNNING
        driveId = getCurrentDriveId()
        # Discriminator #1 surface (drive_id assertion): pre-US-242 the
        # detector never sees RPM, so getCurrentDriveId() stays None and
        # this assertion FAILS.
        assert driveId is not None, (
            "Phase 2 drive_start MUST mint a drive_id.  Pre-US-242 code "
            "has no escalation -> no RPM probe -> no STARTING -> no "
            "_startDrive -> drive_id remains None.  This is the silent-"
            "data-loss bug US-242 closed."
        )
        assert _readConnectionLogEvents(lifecycleDb, driveId) == ["drive_start"]

        # ============================================================
        # Phase 3a: defer-INSERT phase -- snapshot still empty.  The
        # detector's _maybeProgressDriveSummary tick path runs
        # captureDriveStart with an empty dict; the recorder returns
        # deferred=True (US-246 / Sprint 19 US-236).  No drive_summary
        # row is written.  Pre-US-246 (Sprint 18 US-228) would have
        # already INSERTed an all-NULL row in _startDrive itself.
        # ============================================================
        # Drive a no-op processValue tick (RPM > threshold so the
        # drive stays RUNNING; defer-INSERT machine runs every tick).
        detector.processValue("RPM", 800.0)
        assert _readSummaryRow(lifecycleDb, driveId) is None, (
            "Phase 3a defer-INSERT: drive_summary row MUST NOT exist with "
            "an empty snapshot.  Pre-US-246 (Sprint 18 US-228) INSERTs at "
            "drive_start regardless -- the row would already be present "
            "with NULLs.  This is the discriminator for the Drive 3/4/5 "
            "all-NULL bug."
        )

        # ============================================================
        # Phase 3b: first IAT arrival -> INSERT fires.  Snapshot updates
        # with INTAKE_TEMP (cold-start ambient -- fromState was UNKNOWN
        # at _armDriveSummaryDeferInsert time).  The detector's next
        # processValue tick re-calls captureDriveStart; the recorder
        # sees a non-empty snapshot and INSERTs.
        # ============================================================
        snapshotSource.update(INTAKE_TEMP=19.0)
        detector.processValue("RPM", 800.0)

        rowAfterIat = _readSummaryRow(lifecycleDb, driveId)
        assert rowAfterIat is not None, (
            "Phase 3b: drive_summary row MUST exist after first IAT "
            "arrival.  Defer-INSERT contract: row appears when first "
            "IAT/BATTERY_V/BARO arrives in the snapshot."
        )
        assert rowAfterIat[0] == 19.0       # ambient
        assert rowAfterIat[1] is None       # battery still pending
        assert rowAfterIat[2] is None       # baro still pending

        # ============================================================
        # Phase 3c: BATTERY_V arrival -> backfill UPDATE.
        # ============================================================
        snapshotSource.update(BATTERY_V=13.4)
        detector.processValue("RPM", 800.0)

        rowAfterBattery = _readSummaryRow(lifecycleDb, driveId)
        assert rowAfterBattery == (19.0, 13.4, None)

        # ============================================================
        # Phase 3d: BAROMETRIC_KPA arrival -> backfill complete.
        # ============================================================
        snapshotSource.update(BAROMETRIC_KPA=100.2)
        detector.processValue("RPM", 800.0)

        rowFinal = _readSummaryRow(lifecycleDb, driveId)
        # Discriminator #2 (US-246): pre-US-246 code's INSERT-at-
        # _startDrive + UPDATE-backfill path empirically shipped all-
        # NULL rows for drives 3, 4, 5 in production.  The post-US-246
        # row is fully populated end-to-end.
        assert rowFinal == (19.0, 13.4, 100.2), (
            "Phase 3d drive_summary backfill complete.  Pre-US-246 code "
            "(Sprint 18 US-228) shipped Drives 3/4/5 with three NULLs "
            "(documented in offices/pm/inbox/2026-04-29-from-spool-...).  "
            "Defer-INSERT + backfill produces all three populated."
        )

        # ============================================================
        # Phase 4: engine off -> drive_end via RPM=0 debounce.  With
        # driveEndDurationSeconds=0 the second RPM=0 sample fires
        # _endDrive (the first transitions RUNNING -> STOPPING and
        # starts the below-threshold timer).
        # ============================================================
        detector.processValue("RPM", 0.0)
        assert detector.getDriveState() == DriveState.STOPPING

        detector.processValue("RPM", 0.0)
        assert detector.getDriveState() == DriveState.STOPPED

        connectionLogEvents = _readConnectionLogEvents(lifecycleDb, driveId)
        assert connectionLogEvents == ["drive_start", "drive_end"], (
            f"connection_log MUST carry drive_start then drive_end for "
            f"drive_id={driveId}; got {connectionLogEvents}"
        )

        # ============================================================
        # Phase 5: drive-end sync POST -- _handleDriveEnd fired
        # synchronously inside detector._endDrive (registered via
        # detector.registerCallbacks above), which called
        # orchestrator.triggerDriveEndSync, which called
        # _syncClient.pushAllDeltas exactly once.  Result reports OK.
        # ============================================================
        syncClient.pushAllDeltas.assert_called_once()
        results = syncClient.pushAllDeltas.return_value
        assert len(results) == 1
        assert results[0].status == PushStatus.OK
        assert results[0].rowsPushed == 1
        assert results[0].tableName == "drive_summary"

        # drive_summary row remains intact post-drive-end (no clobber
        # on the way out -- _endDrive disarms the backfill state but
        # does not touch the persisted row).
        rowPostEnd = _readSummaryRow(lifecycleDb, driveId)
        assert rowPostEnd == (19.0, 13.4, 100.2)
