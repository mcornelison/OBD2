################################################################################
# File Name: test_drive_summary_writer_e2e.py
# Purpose/Description: US-304 (Sprint 28) -- regression gate for the
#                      drive_summary writer wiring.  Drives 6+7 (2026-05-08)
#                      fired DRIVE STARTED + DRIVE ENDED journal events with
#                      full payloads but ZERO drive_summary rows landed.  Last
#                      good write was drive_id=5 from 2026-04-29.  This test
#                      exercises the REAL RealtimeDataLogger -> DriveDetector
#                      wiring (US-286's harness mocks the snapshot source, so
#                      it cannot catch this bug class).  Pre-fix the
#                      lifecycle.py hasattr(self._dataLogger,
#                      'getLatestReadings') check returns False because
#                      RealtimeDataLogger does NOT expose getLatestReadings
#                      (only the inner ObdDataLogger does).  setReadingSnapshot
#                      Source is silently skipped, the detector's
#                      _readingSnapshotSource stays None, and the defer-INSERT
#                      machinery short-circuits at _armDriveSummaryDeferInsert
#                      (detector.py:884) flagging _driveSummaryBackfillComplete
#                      = True with no row written.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-09
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-09    | Rex (US-304) | Initial -- two-class structure.  Class 1
#                              | (TestRealtimeDataLoggerExposesSnapshot) pins
#                              | RealtimeDataLogger.getLatestReadings as a
#                              | first-class delegating method and verifies
#                              | the hasattr() probe lifecycle.py uses to wire
#                              | the snapshot source returns True post-fix.
#                              | Class 2 (TestDriveSummaryWriterEndToEnd) is
#                              | the full drive_start -> realtime data ->
#                              | drive_end gate: real RealtimeDataLogger,
#                              | real DriveDetector, real SummaryRecorder, the
#                              | snapshot source resolved through the real
#                              | wiring path.  Pre-fix the snapshot returns
#                              | empty dict + the defer-INSERT row never
#                              | appears; post-fix the row INSERTs with all
#                              | three metadata columns populated.
# ================================================================================
################################################################################

"""US-304 -- drive_summary writer regression gate (Sprint 28).

The bug class this gate catches
-------------------------------
US-286 (Sprint 25) shipped a bench harness for the engine-on data path,
but it mocks the snapshot source via ``_MutableSnapshotSource`` -- a
test double that exposes ``getLatestReadings`` directly.  Production
wires :class:`RealtimeDataLogger` (the OUTER component held on
``ApplicationOrchestrator._dataLogger``) into the detector's snapshot
seam.  The OUTER class did not expose ``getLatestReadings``; only the
INNER :class:`ObdDataLogger` (held privately on
``RealtimeDataLogger._dataLogger``) did.  The ``hasattr(self._dataLogger,
'getLatestReadings')`` gate at ``lifecycle.py`` therefore silently
returned False on every Pi boot, ``setReadingSnapshotSource`` was never
called, and the detector's defer-INSERT machinery short-circuited the
moment a drive started.

Drives 6+7 on 2026-05-08 produced engine-on telemetry for the first time
since Drive 5 (2026-04-29) -- they exposed the dormant regression in
production.  Sprint 25 - 27 each masked the bug behind upstream blockers
(US-244 / US-284 connect hangs + US-301 stacking-connect bug); V0.27.1
unblocked the engine-on data flow and the silent-fail surfaced.

What this file gates that US-286 does not
-----------------------------------------
US-286's harness uses a mocked snapshot source so it cannot catch a
regression where the snapshot source is never wired.  US-304 (this
file) drops the mock.  The test wires the production
:class:`RealtimeDataLogger` instance through the same code path
:meth:`_initializeSummaryRecorder` uses (verifying ``hasattr`` resolves
True), then drives RPM ticks + simulated metadata reads and asserts the
drive_summary row INSERTs with non-NULL ambient/battery/baro.

Pre-fix RED / post-fix GREEN behavior
-------------------------------------
* **Class 1**: ``hasattr(RealtimeDataLogger(), 'getLatestReadings')``
  must return True; calling it returns the inner ``ObdDataLogger``'s
  cached snapshot.  Pre-fix the attribute does not exist (RED -- the
  hasattr probe returns False).
* **Class 2**: full drive_start -> realtime data -> drive_end pipeline
  asserts ``drive_summary`` has a row for the minted ``drive_id`` with
  ``ambient_temp_at_start_c IS NOT NULL`` AND ``starting_battery_v IS
  NOT NULL`` AND ``barometric_kpa_at_start IS NOT NULL`` within 30s.
  Pre-fix the row never appears (RED -- the snapshot source is None;
  defer-INSERT short-circuits with ``_driveSummaryBackfillComplete=True``
  on the very first tick).

Discriminator (per ``feedback_runtime_validation_required.md``)
---------------------------------------------------------------
Pre-fix RED is verified by reverting (a) the new ``RealtimeDataLogger.
getLatestReadings`` method.  Without that delegation, the lifecycle
wiring's ``hasattr`` check returns False, the snapshot source stays
None, and the defer-INSERT machinery never fires the INSERT.  Class 2's
final assertion ``rowAfterDeadline is not None`` fails.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pi.obdii.data.realtime import RealtimeDataLogger
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive.types import DriveState
from src.pi.obdii.drive_id import clearCurrentDriveId, getCurrentDriveId
from src.pi.obdii.drive_summary import DRIVE_SUMMARY_TABLE, SummaryRecorder

# Eclipse warm-idle baseline (per offices/tuner/knowledge.md Drive 5).
_RPM_ENGINE_ON: float = 750.0

# Test-side compressed defer-INSERT window.  Production is 60 sec; the
# test compresses to 1 sec so a deadline-expired branch can be exercised
# deterministically without leaning on real-time waits.
_DEFER_INSERT_WINDOW_SECONDS: float = 60.0


def _baseConfig(driveSummaryWindow: float = _DEFER_INSERT_WINDOW_SECONDS) -> dict[str, Any]:
    """Tier-aware config exercising the production wiring path."""
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
                },
            },
            "analysis": {
                "driveStartRpmThreshold": 500,
                "driveStartDurationSeconds": 0.0,
                "driveEndRpmThreshold": 0,
                "driveEndDurationSeconds": 0.0,
                "triggerAfterDrive": False,
                "driveSummaryBackfillSeconds": driveSummaryWindow,
            },
            "realtimeData": {
                "pollingIntervalMs": 100,
                "parameters": [
                    {"name": "RPM", "logData": True,
                     "displayOnDashboard": False},
                    {"name": "INTAKE_TEMP", "logData": True,
                     "displayOnDashboard": False},
                    {"name": "BATTERY_V", "logData": True,
                     "displayOnDashboard": False},
                    {"name": "BAROMETRIC_KPA", "logData": True,
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


@pytest.fixture()
def lifecycleDb(tmp_path: Path) -> ObdDatabase:
    """Persistent on-disk DB seeded with the 'daily' profile FK target."""
    db = ObdDatabase(str(tmp_path / "test_us304_drive_summary_writer.db"),
                     walMode=False)
    db.initialize()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO profiles (id, name) VALUES (?, ?)",
            ('daily', 'Daily Driving'),
        )
    yield db
    clearCurrentDriveId()


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


# ================================================================================
# Class 1: RealtimeDataLogger exposes getLatestReadings (the lifecycle hasattr probe)
# ================================================================================


class TestRealtimeDataLoggerExposesSnapshot:
    """US-304 -- the production component held on
    ``ApplicationOrchestrator._dataLogger`` MUST expose
    ``getLatestReadings`` so :meth:`lifecycle._initializeSummaryRecorder`'s
    ``hasattr`` gate evaluates True and the detector receives the
    snapshot wire.

    Pre-fix the gate evaluates False (only the inner
    :class:`ObdDataLogger` exposes the method) and the wiring is
    silently skipped.  This class is the load-bearing pin: without
    this method the rest of the defer-INSERT machinery never sees a
    snapshot.
    """

    def test_realtimeDataLogger_hasGetLatestReadings_method(
        self,
        lifecycleDb: ObdDatabase,
    ) -> None:
        """The hasattr probe lifecycle.py uses MUST return True."""
        config = _baseConfig()
        mockConnection = MagicMock()
        mockConnection.isConnected.return_value = True
        mockConnection.isSimulated = False
        outerLogger = RealtimeDataLogger(
            config=config,
            connection=mockConnection,
            database=lifecycleDb,
            profileId='daily',
        )
        assert hasattr(outerLogger, 'getLatestReadings'), (
            "RealtimeDataLogger MUST expose getLatestReadings -- "
            "lifecycle.py:1615-1618 uses hasattr() to gate the snapshot "
            "source wiring; pre-fix this gate returns False because the "
            "method only existed on the inner ObdDataLogger."
        )

    def test_realtimeDataLogger_getLatestReadings_delegatesToInner(
        self,
        lifecycleDb: ObdDatabase,
    ) -> None:
        """Outer.getLatestReadings reflects writes on the inner logger."""
        config = _baseConfig()
        mockConnection = MagicMock()
        mockConnection.isConnected.return_value = True
        mockConnection.isSimulated = False
        outerLogger = RealtimeDataLogger(
            config=config,
            connection=mockConnection,
            database=lifecycleDb,
            profileId='daily',
        )
        # Empty before any reading is recorded.
        assert outerLogger.getLatestReadings() == {}

        # Drive a value through the inner logger's _recordLatest
        # (the same code path queryParameter uses on every successful
        # ECU response).
        innerLogger = outerLogger._dataLogger
        innerLogger._recordLatest('INTAKE_TEMP', 25.5)
        innerLogger._recordLatest('BATTERY_V', 13.7)
        innerLogger._recordLatest('BAROMETRIC_KPA', 101.3)

        snapshot = outerLogger.getLatestReadings()
        assert snapshot == {
            'INTAKE_TEMP': 25.5,
            'BATTERY_V': 13.7,
            'BAROMETRIC_KPA': 101.3,
        }

    def test_realtimeDataLogger_getLatestReadings_returnsCopy(
        self,
        lifecycleDb: ObdDatabase,
    ) -> None:
        """Mutation of the returned dict MUST NOT bleed into the snapshot."""
        config = _baseConfig()
        mockConnection = MagicMock()
        mockConnection.isConnected.return_value = True
        outerLogger = RealtimeDataLogger(
            config=config,
            connection=mockConnection,
            database=lifecycleDb,
            profileId='daily',
        )
        outerLogger._dataLogger._recordLatest('INTAKE_TEMP', 25.5)
        snapshot = outerLogger.getLatestReadings()
        snapshot['INTAKE_TEMP'] = -999.0
        # Original snapshot is unaffected.
        assert outerLogger.getLatestReadings()['INTAKE_TEMP'] == 25.5


# ================================================================================
# Class 2: full drive_start -> realtime data -> drive_end pipeline
# ================================================================================


class TestDriveSummaryWriterEndToEnd:
    """US-304 -- end-to-end gate for drive_summary INSERT via the production
    wiring path (RealtimeDataLogger -> DriveDetector snapshot seam).

    Mirrors the regression class US-286 cannot catch (its harness mocks
    the snapshot source).  Pre-fix the snapshot stays None on the
    detector and the defer-INSERT machinery short-circuits with
    ``_driveSummaryBackfillComplete=True`` on the very first tick;
    post-fix the snapshot delegates through the real
    :meth:`RealtimeDataLogger.getLatestReadings` and the row appears
    when the first metadata reading lands.
    """

    def test_driveStart_realtimeData_driveEnd_producesDriveSummaryRow(
        self,
        lifecycleDb: ObdDatabase,
    ) -> None:
        """Full pipeline produces drive_summary row with all 3 columns set."""
        config = _baseConfig()
        mockConnection = MagicMock()
        mockConnection.isConnected.return_value = True
        mockConnection.isSimulated = False
        mockConnection.supportedPids = None  # bypass Mode-01 probe gate

        outerLogger = RealtimeDataLogger(
            config=config,
            connection=mockConnection,
            database=lifecycleDb,
            profileId='daily',
        )

        detector = DriveDetector(config=config, database=lifecycleDb)
        detector.start()

        recorder = SummaryRecorder(database=lifecycleDb)
        detector.setSummaryRecorder(recorder)

        # Wire the snapshot seam through the production gate the same
        # way :meth:`_initializeSummaryRecorder` does.  Pre-fix the
        # hasattr() check returns False and this branch is silently
        # skipped -- the detector's _readingSnapshotSource stays None.
        if hasattr(outerLogger, 'getLatestReadings'):
            detector.setReadingSnapshotSource(outerLogger)

        # Phase 1: pre-engine baseline.  No drive_summary rows yet.
        assert detector.getDriveState() == DriveState.STOPPED

        # Phase 2: feed RPM ticks via the real ObdDataLogger.processValue
        # path so _startDrive fires after the zero-duration debounce.
        # First tick: STOPPED -> STARTING.
        detector.processValue('RPM', _RPM_ENGINE_ON)
        assert detector.getDriveState() == DriveState.STARTING
        # Second tick: STARTING -> RUNNING (drive_id minted; defer-INSERT
        # machinery armed).
        detector.processValue('RPM', _RPM_ENGINE_ON)
        assert detector.getDriveState() == DriveState.RUNNING

        driveId = getCurrentDriveId()
        assert driveId is not None

        # Phase 3: pre-metadata snapshot.  The defer-INSERT path
        # short-circuits when the snapshot is empty.  Row MUST NOT
        # exist yet.
        assert _readSummaryRow(lifecycleDb, driveId) is None

        # Phase 4: simulate realtime data flowing through the inner
        # ObdDataLogger (production path: queryParameter ->
        # _recordLatest).  Use _recordLatest directly to bypass the
        # python-obd query mock -- queryParameter exercises code paths
        # outside US-304's scope (PID probe, decoder pipeline) and
        # the snapshot seam is what this test gates.
        innerLogger = outerLogger._dataLogger
        innerLogger._recordLatest('INTAKE_TEMP', 25.0)
        innerLogger._recordLatest('BATTERY_V', 13.7)
        innerLogger._recordLatest('BAROMETRIC_KPA', 101.3)

        # Phase 5: a third RPM tick drives _maybeProgressDriveSummary
        # which reads the snapshot via the (now-wired) source and
        # INSERTs the drive_summary row.  Pre-fix the source is None
        # and this tick is a no-op; post-fix the row appears.
        detector.processValue('RPM', _RPM_ENGINE_ON)

        rowAfterMetadata = _readSummaryRow(lifecycleDb, driveId)
        assert rowAfterMetadata is not None, (
            f"US-304 pre-fix RED gate: drive_summary row for drive_id="
            f"{driveId} MUST exist after metadata snapshot arrives.  "
            "None means RealtimeDataLogger.getLatestReadings is missing "
            "OR the lifecycle wiring's hasattr() gate evaluates False -- "
            "the SAME bug class that produced Drives 6+7's missing rows."
        )
        ambient, battery, baro = rowAfterMetadata
        assert ambient == 25.0, (
            f"Phase 5 ambient_temp_at_start_c expected 25.0; got {ambient!r}.  "
            "Cold-start rule: first drive since Pi boot has fromState=UNKNOWN; "
            "IAT is captured into the ambient column."
        )
        assert battery == 13.7
        assert baro == 101.3

        # Phase 6: drive_end fires the post-drive analysis hook.  The
        # drive_summary row must remain populated -- _endDrive disarms
        # the defer-INSERT window but MUST NOT clobber the existing row.
        detector.processValue('RPM', 0.0)
        # Force end via direct call (zero-duration debounce path is
        # already in flight -- this is the deterministic end signal).
        detector._endDrive()
        assert detector.getDriveState() == DriveState.STOPPED

        rowAfterEnd = _readSummaryRow(lifecycleDb, driveId)
        assert rowAfterEnd == (25.0, 13.7, 101.3), (
            "Phase 6: drive_end MUST NOT modify the drive_summary row.  "
            "_endDrive disarms the defer-INSERT window but the row stays."
        )

    def test_driveStart_emptySnapshotPlusDeadline_forcesInsert(
        self,
        lifecycleDb: ObdDatabase,
    ) -> None:
        """Deadline expiry triggers force-INSERT even with empty snapshot.

        Defer-INSERT machinery: if no IAT/BATTERY_V/BARO arrives within
        ``driveSummaryBackfillSeconds``, the next tick passes
        ``forceInsert=True`` so the row appears with NULLs and the
        operator-visible reason ``no_readings_within_timeout``.  This
        gate proves the wiring carries the deadline path through too.
        """
        # Compress the window so the deadline branch fires on the second
        # tick after _startDrive.
        config = _baseConfig(driveSummaryWindow=0.001)
        mockConnection = MagicMock()
        mockConnection.isConnected.return_value = True

        outerLogger = RealtimeDataLogger(
            config=config,
            connection=mockConnection,
            database=lifecycleDb,
            profileId='daily',
        )

        detector = DriveDetector(config=config, database=lifecycleDb)
        detector.start()
        detector.setSummaryRecorder(SummaryRecorder(database=lifecycleDb))

        if hasattr(outerLogger, 'getLatestReadings'):
            detector.setReadingSnapshotSource(outerLogger)

        # _startDrive after two ticks.
        detector.processValue('RPM', _RPM_ENGINE_ON)
        detector.processValue('RPM', _RPM_ENGINE_ON)
        driveId = getCurrentDriveId()
        assert driveId is not None

        # Sleep past the 0.001s deadline so the next tick crosses it.
        # Also force the deadline via direct attribute manipulation --
        # the 1ms sleep is fragile on Windows.
        from datetime import datetime
        detector._driveSummaryBackfillDeadline = (
            datetime.now() - timedelta(seconds=1)
        )

        # Tick again with empty snapshot -> deadline expired ->
        # forceInsert=True -> row appears with NULL columns.
        detector.processValue('RPM', _RPM_ENGINE_ON)

        row = _readSummaryRow(lifecycleDb, driveId)
        assert row is not None, (
            "Deadline-expiry force-INSERT path: row MUST exist after "
            "the deadline crosses, even with an empty snapshot."
        )
        # All three columns are NULL because the snapshot was empty.
        assert row == (None, None, None)
