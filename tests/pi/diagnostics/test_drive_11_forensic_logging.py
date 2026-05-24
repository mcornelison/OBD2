################################################################################
# File Name: test_drive_11_forensic_logging.py
# Purpose/Description: US-319 (B-071) -- forensic INFO log instrumentation
#                      across the four V0.27-chain validation surfaces:
#                      DriveDetector state transitions, Pi-side
#                      drive_summary writer entry, server-side
#                      _ensureDriveSummary entry, and sync client
#                      pushDelta UPDATE-cursor advance.  Each test asserts
#                      the journalctl-grep token (FORENSIC ...) fires with
#                      drive_id / table / state context so the post-V0.27.5
#                      Drive 11+ trail produces evidence for all 8 pending
#                      V0.27 bigDoD clauses in ONE drive.  Pure observability
#                      regression gate -- no behavior change anywhere.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex (US-319) | Initial -- B-071 forensic regression gate.
# ================================================================================
################################################################################

"""Regression gate for US-319: forensic INFO log instrumentation.

Each surface gets its own test class.  All tests would FAIL pre-fix
because the FORENSIC token strings do not exist in the current code
base; post-fix all log lines are present at INFO level with the
documented context fields.  See ``offices/pm/backlog/B-071-*.md`` for
the operator rationale (one drive captures evidence for the full
V0.27 chain bigDoD).
"""

from __future__ import annotations

import logging
import sqlite3
import time as _time
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive.types import DriveState
from src.pi.obdii.drive_id import setCurrentDriveId
from src.pi.obdii.drive_summary import SummaryRecorder
from src.pi.obdii.engine_state import EngineState

# ================================================================================
# Common fixtures
# ================================================================================


@pytest.fixture
def freshDb(tmp_path: Path) -> Generator[ObdDatabase, None, None]:
    db = ObdDatabase(str(tmp_path / "us319_forensic.db"), walMode=False)
    db.initialize()
    setCurrentDriveId(None)
    yield db
    setCurrentDriveId(None)


@pytest.fixture
def detectorConfig() -> dict[str, Any]:
    """Fast-debounce thresholds so processValue ticks drive the state machine."""
    return {
        'pi': {
            'analysis': {
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 0.01,
                'driveEndRpmThreshold': 200,
                'driveEndDurationSeconds': 0.01,
                'triggerAfterDrive': False,
            },
            'profiles': {'activeProfile': 'daily'},
        },
    }


# ================================================================================
# Surface 1 -- DriveDetector state transitions
# ================================================================================


class TestDriveDetectorForensicLogging:
    """Drive start/end checks emit FORENSIC tokens at INFO level."""

    def _driveUp(self, detector: DriveDetector) -> None:
        detector.processValue('RPM', 1000)
        _time.sleep(0.05)
        detector.processValue('RPM', 1200)

    def _driveDown(self, detector: DriveDetector) -> None:
        detector.processValue('RPM', 0)
        _time.sleep(0.05)
        detector.processValue('RPM', 0)

    def test_driveStartCheck_emitsForensicToken_withRpmAndState(
        self,
        detectorConfig: dict[str, Any],
        freshDb: ObdDatabase,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        detector = DriveDetector(
            detectorConfig, statisticsEngine=None, database=freshDb,
        )
        detector.start()
        with caplog.at_level(
            logging.INFO, logger="src.pi.obdii.drive.detector",
        ):
            self._driveUp(detector)
        forensicLines = [
            r.getMessage() for r in caplog.records
            if "FORENSIC drive_check" in r.getMessage()
        ]
        assert len(forensicLines) >= 1
        assert any("RPM=" in line for line in forensicLines)
        assert any("state=" in line for line in forensicLines)

    def test_stateTransition_emitsForensicToken_atInfoLevel(
        self,
        detectorConfig: dict[str, Any],
        freshDb: ObdDatabase,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        detector = DriveDetector(
            detectorConfig, statisticsEngine=None, database=freshDb,
        )
        detector.start()
        with caplog.at_level(
            logging.INFO, logger="src.pi.obdii.drive.detector",
        ):
            self._driveUp(detector)
            self._driveDown(detector)
        transitionLines = [
            r for r in caplog.records
            if "FORENSIC drive_state_transition" in r.getMessage()
        ]
        assert len(transitionLines) >= 2
        # All transition lines must be INFO so journalctl trails surface them.
        assert all(r.levelno == logging.INFO for r in transitionLines)
        # At least one transition must show the running state (drive started).
        # DriveState enum values are lowercase per types.py.
        assert any(
            "running" in r.getMessage() for r in transitionLines
        )

    def test_driveEndCheck_emitsForensicToken_withTimers(
        self,
        detectorConfig: dict[str, Any],
        freshDb: ObdDatabase,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        detector = DriveDetector(
            detectorConfig, statisticsEngine=None, database=freshDb,
        )
        detector.start()
        # Bring the drive up first so the end-check path is reachable.
        self._driveUp(detector)
        assert detector.getDriveState() == DriveState.RUNNING
        with caplog.at_level(
            logging.INFO, logger="src.pi.obdii.drive.detector",
        ):
            self._driveDown(detector)
        endCheckLines = [
            r.getMessage() for r in caplog.records
            if "FORENSIC drive_check" in r.getMessage()
        ]
        # End check must also emit forensic context (state context here is
        # RUNNING/STOPPING) -- the same drive_check token covers both
        # entry/exit paths so journal-grep is one stable string.
        assert len(endCheckLines) >= 1
        assert any("RPM=" in line for line in endCheckLines)


# ================================================================================
# Surface 2 -- Pi-side drive_summary writer entry
# ================================================================================


class TestDriveSummaryWriterForensicLogging:
    """SummaryRecorder.captureDriveStart emits FORENSIC entry token."""

    def test_writerEntry_emitsForensicToken_withDriveIdAndSnapshotKeys(
        self,
        freshDb: ObdDatabase,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        with caplog.at_level(
            logging.INFO, logger="src.pi.obdii.drive_summary",
        ):
            recorder.captureDriveStart(
                driveId=11,
                snapshot={'INTAKE_TEMP': 22.5, 'BATTERY_V': 12.7},
                fromState=EngineState.KEY_OFF,
                forceInsert=False,
            )
        entryLines = [
            r.getMessage() for r in caplog.records
            if "FORENSIC drive_summary_writer_entry" in r.getMessage()
        ]
        assert len(entryLines) == 1
        assert "drive_id=11" in entryLines[0]
        assert "from_state=" in entryLines[0]


# ================================================================================
# Surface 3 -- Server-side _ensureDriveSummary entry
# ================================================================================


class TestServerEnsureDriveSummaryForensicLogging:
    """_ensureDriveSummary emits FORENSIC token at entry with drive_id + device."""

    def test_ensureDriveSummary_emitsForensicToken_atEntry(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Patch the internal analytics computation so we don't need a real
        # SQLAlchemy session -- the forensic log line fires BEFORE the
        # session does any work so the patch is sufficient.
        from src.server.services import analysis as analysisModule

        startTime = datetime(2026, 5, 11, 8, 0, 0)
        endTime = datetime(2026, 5, 11, 8, 5, 0)
        fakeSession = MagicMock()
        # The function will call session.execute(...).scalar_one_or_none()
        # for the find-or-create lookup; return None so the INSERT path
        # would be taken.  We early-exit after the forensic log fires by
        # patching session.add to no-op + session.flush to set .id.
        existingResult = MagicMock()
        existingResult.scalar_one_or_none.return_value = None
        fakeSession.execute.return_value = existingResult

        def fakeAdd(obj: Any) -> None:
            obj.id = 999

        fakeSession.add.side_effect = fakeAdd
        fakeSession.flush = MagicMock()

        fakeAnalytics = analysisModule._DriveAnalytics(
            rowCount=0,
            startTime=None,
            endTime=None,
            durationSeconds=None,
            dataSource=None,
            isReal=False,
            profileId=None,
        )

        with patch.object(
            analysisModule, '_computeDriveAnalytics',
            return_value=fakeAnalytics,
        ), caplog.at_level(
            logging.INFO, logger="src.server.services.analysis",
        ):
            analysisModule._ensureDriveSummary(
                fakeSession, "chi-eclipse-01",
                startTime, endTime,
                driveId=11,
            )

        entryLines = [
            r.getMessage() for r in caplog.records
            if "FORENSIC ensureDriveSummary_entry" in r.getMessage()
        ]
        assert len(entryLines) == 1
        assert "drive_id=11" in entryLines[0]
        assert "device=chi-eclipse-01" in entryLines[0]


# ================================================================================
# Surface 4 -- Sync client UPDATE propagation per-table
# ================================================================================


class TestSyncClientForensicLogging:
    """SyncClient.pushDelta emits FORENSIC entry + cursor-advance tokens."""

    @pytest.fixture
    def syncDbPath(self, tmp_path: Path) -> str:
        # Minimal SQLite with a battery_health_log row + sync_log scaffolding
        # so pushDelta has something to push.
        from src.pi.data import sync_log

        dbPath = tmp_path / "us319_sync.db"
        with sqlite3.connect(str(dbPath)) as conn:
            sync_log.initDb(conn)
            # Real battery_health_log schema uses drain_event_id PK (US-217).
            conn.execute(
                "CREATE TABLE battery_health_log ("
                " drain_event_id INTEGER PRIMARY KEY,"
                " source_device TEXT,"
                " timestamp TEXT,"
                " start_vcell_v REAL"
                ")"
            )
            sync_log.ensureSyncModifiedAtSchema(conn)
            conn.execute(
                "INSERT INTO battery_health_log "
                "(drain_event_id, source_device, timestamp, start_vcell_v) "
                "VALUES (1, 'chi-eclipse-01', '2026-05-11T08:00:00Z', 3.7)"
            )
            conn.commit()
        return str(dbPath)

    def _makeClient(
        self, dbPath: str, monkeypatch: pytest.MonkeyPatch,
    ) -> Any:
        from src.pi.sync import client as clientModule

        config = {
            'deviceId': 'chi-eclipse-01',
            'pi': {
                'companionService': {
                    'enabled': True,
                    'baseUrl': 'http://test:8000',
                    'apiKeyEnv': 'TEST_API_KEY',
                    'syncTimeoutSeconds': 5,
                    'batchSize': 50,
                    'retryBackoffSeconds': [],
                    'retryMaxAttempts': 0,
                },
            },
        }
        monkeypatch.setenv('TEST_API_KEY', 'fake-key')
        return clientModule.SyncClient(config=config, dbPath=dbPath)

    def test_pushDelta_emitsForensicEntryToken_withTableName(
        self,
        syncDbPath: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = self._makeClient(syncDbPath, monkeypatch)
        # Stub the network so the test stays hermetic; the entry log fires
        # before _postBatchWithRetry runs.
        monkeypatch.setattr(
            client, '_postBatchWithRetry', lambda *a, **k: None,
        )
        with caplog.at_level(logging.INFO, logger="src.pi.sync.client"):
            client.pushDelta('battery_health_log')
        entryLines = [
            r.getMessage() for r in caplog.records
            if "FORENSIC sync_push_table_entry" in r.getMessage()
        ]
        assert len(entryLines) == 1
        assert "table=battery_health_log" in entryLines[0]
        assert "supports_update_sync=True" in entryLines[0]

    def test_pushDelta_emitsForensicCursorAdvanceToken_onSuccess(
        self,
        syncDbPath: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = self._makeClient(syncDbPath, monkeypatch)
        monkeypatch.setattr(
            client, '_postBatchWithRetry', lambda *a, **k: None,
        )
        with caplog.at_level(logging.INFO, logger="src.pi.sync.client"):
            client.pushDelta('battery_health_log')
        advanceLines = [
            r.getMessage() for r in caplog.records
            if "FORENSIC sync_push_table_advance" in r.getMessage()
        ]
        assert len(advanceLines) == 1
        assert "table=battery_health_log" in advanceLines[0]
        assert "new_id=" in advanceLines[0]

    def test_pushDriveCounter_emitsForensicToken_withLastDriveId(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from src.pi.data import sync_log

        dbPath = tmp_path / "us319_drive_counter.db"
        with sqlite3.connect(str(dbPath)) as conn:
            sync_log.initDb(conn)
            conn.execute(
                "CREATE TABLE drive_counter ("
                " id INTEGER PRIMARY KEY CHECK (id = 1),"
                " last_drive_id INTEGER NOT NULL"
                ")"
            )
            conn.execute(
                "INSERT INTO drive_counter (id, last_drive_id) VALUES (1, 11)"
            )
            conn.commit()
        client = self._makeClient(str(dbPath), monkeypatch)
        monkeypatch.setattr(
            client, '_postDriveCounterWithRetry', lambda *a, **k: None,
        )
        with caplog.at_level(logging.INFO, logger="src.pi.sync.client"):
            client.pushDriveCounter()
        counterLines = [
            r.getMessage() for r in caplog.records
            if "FORENSIC sync_push_drive_counter" in r.getMessage()
        ]
        assert len(counterLines) == 1
        assert "last_drive_id=11" in counterLines[0]
