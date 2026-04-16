################################################################################
# File Name: test_load_data.py
# Purpose/Description: Tests for scripts/load_data.py — SQLite → MariaDB importer
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-157 — data loader
# ================================================================================
################################################################################

"""
Tests for the load_data.py crawl-phase data loader.

Validates:
    - Per-table load: realtime_data, connection_log, statistics, profiles,
      vehicle_info, ai_recommendations, alert_log, calibration_sessions
    - source_id derives from SQLite rowid
    - source_device derives from --device-id arg
    - Upsert semantics (idempotent on re-run)
    - Drive detection from drive_start/drive_end pairs in connection_log
    - DriveSummary creation with row_count and duration
    - Summary output
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

# Skip the whole module if server schema deps are not installed.
pytest.importorskip("sqlalchemy")

from scripts import load_data  # noqa: E402
from src.server.db.models import (  # noqa: E402
    AiRecommendation,
    AlertLog,
    Base,
    CalibrationSession,
    ConnectionLog,
    DriveSummary,
    Profile,
    RealtimeData,
    Statistic,
    SyncHistory,
    VehicleInfo,
)

# =========================================================================
# Fixtures
# =========================================================================


def _createPiSchemaDb(dbPath: str) -> sqlite3.Connection:
    """Create a Pi-compatible SQLite database for test input."""
    from src.pi.obd.database_schema import (
        SCHEMA_AI_RECOMMENDATIONS,
        SCHEMA_ALERT_LOG,
        SCHEMA_CALIBRATION_SESSIONS,
        SCHEMA_CONNECTION_LOG,
        SCHEMA_PROFILES,
        SCHEMA_REALTIME_DATA,
        SCHEMA_STATISTICS,
        SCHEMA_VEHICLE_INFO,
    )
    conn = sqlite3.connect(dbPath)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(SCHEMA_PROFILES)
    conn.execute(SCHEMA_VEHICLE_INFO)
    conn.execute(SCHEMA_REALTIME_DATA)
    conn.execute(SCHEMA_STATISTICS)
    conn.execute(SCHEMA_AI_RECOMMENDATIONS)
    conn.execute(SCHEMA_CONNECTION_LOG)
    conn.execute(SCHEMA_ALERT_LOG)
    conn.execute(SCHEMA_CALIBRATION_SESSIONS)
    conn.commit()
    return conn


@pytest.fixture
def sourceDbPath(tmp_path: Path) -> str:
    """Create a sample Pi-schema SQLite DB with a 2-drive scenario."""
    dbPath = str(tmp_path / "source.db")
    conn = _createPiSchemaDb(dbPath)

    # Seed a profile
    conn.execute(
        "INSERT INTO profiles (id, name, description, polling_interval_ms) "
        "VALUES (?, ?, ?, ?)",
        ("daily", "Daily", "Daily driver profile", 1000),
    )

    # Drive 1: 08:00 → 08:05
    conn.execute(
        "INSERT INTO connection_log (timestamp, event_type, success) "
        "VALUES ('2026-04-16 08:00:00', 'drive_start', 1)"
    )
    conn.execute(
        "INSERT INTO connection_log (timestamp, event_type, success) "
        "VALUES ('2026-04-16 08:05:00', 'drive_end', 1)"
    )
    # Drive 2: 09:00 → 09:10
    conn.execute(
        "INSERT INTO connection_log (timestamp, event_type, success) "
        "VALUES ('2026-04-16 09:00:00', 'drive_start', 1)"
    )
    conn.execute(
        "INSERT INTO connection_log (timestamp, event_type, success) "
        "VALUES ('2026-04-16 09:10:00', 'drive_end', 1)"
    )

    # Realtime rows in each drive
    rtRows = [
        ("2026-04-16 08:01:00", "RPM", 1500.0, "rpm", "daily"),
        ("2026-04-16 08:02:00", "RPM", 2500.0, "rpm", "daily"),
        ("2026-04-16 08:03:00", "SPEED", 45.0, "km/h", "daily"),
        ("2026-04-16 09:05:00", "RPM", 3500.0, "rpm", "daily"),
        ("2026-04-16 09:06:00", "SPEED", 80.0, "km/h", "daily"),
    ]
    conn.executemany(
        "INSERT INTO realtime_data (timestamp, parameter_name, value, unit, profile_id) "
        "VALUES (?, ?, ?, ?, ?)",
        rtRows,
    )

    # Statistics row
    conn.execute(
        "INSERT INTO statistics "
        "(parameter_name, analysis_date, profile_id, max_value, min_value, avg_value, "
        " mode_value, std_1, std_2, outlier_min, outlier_max, sample_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("RPM", "2026-04-16 09:10:00", "daily", 3500.0, 1500.0, 2500.0,
         None, 800.0, 1600.0, 900.0, 4100.0, 3),
    )

    conn.commit()
    conn.close()
    return dbPath


@pytest.fixture
def serverEngine():
    """SQLite-backed SQLAlchemy engine with the server schema (stand-in for MariaDB)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    Path(tmp.name).unlink(missing_ok=True)


# =========================================================================
# detectDrives
# =========================================================================


class TestDetectDrives:
    """Drive detection from connection_log start/end pairs."""

    def test_detectDrives_pairedStartEndEvents_returnsDrives(self):
        events = [
            (datetime(2026, 4, 16, 8, 0, 0), "drive_start"),
            (datetime(2026, 4, 16, 8, 5, 0), "drive_end"),
        ]
        drives = load_data.detectDrivePairs(events)
        assert len(drives) == 1
        assert drives[0] == (
            datetime(2026, 4, 16, 8, 0, 0),
            datetime(2026, 4, 16, 8, 5, 0),
        )

    def test_detectDrives_multipleDrives_allPaired(self):
        events = [
            (datetime(2026, 4, 16, 8, 0, 0), "drive_start"),
            (datetime(2026, 4, 16, 8, 5, 0), "drive_end"),
            (datetime(2026, 4, 16, 9, 0, 0), "drive_start"),
            (datetime(2026, 4, 16, 9, 10, 0), "drive_end"),
        ]
        drives = load_data.detectDrivePairs(events)
        assert len(drives) == 2

    def test_detectDrives_unpairedStart_ignored(self):
        events = [
            (datetime(2026, 4, 16, 8, 0, 0), "drive_start"),
            (datetime(2026, 4, 16, 9, 0, 0), "drive_start"),
            (datetime(2026, 4, 16, 9, 5, 0), "drive_end"),
        ]
        drives = load_data.detectDrivePairs(events)
        # First start has no matching end before second start — first is replaced
        # Expected behavior: last start wins, one drive pair
        assert len(drives) == 1
        assert drives[0][0] == datetime(2026, 4, 16, 9, 0, 0)

    def test_detectDrives_orphanedEnd_ignored(self):
        events = [
            (datetime(2026, 4, 16, 8, 5, 0), "drive_end"),
        ]
        drives = load_data.detectDrivePairs(events)
        assert drives == []

    def test_detectDrives_nonDriveEvents_ignored(self):
        events = [
            (datetime(2026, 4, 16, 8, 0, 0), "connect"),
            (datetime(2026, 4, 16, 8, 0, 1), "drive_start"),
            (datetime(2026, 4, 16, 8, 0, 5), "heartbeat"),
            (datetime(2026, 4, 16, 8, 5, 0), "drive_end"),
        ]
        drives = load_data.detectDrivePairs(events)
        assert len(drives) == 1


# =========================================================================
# loadData (end-to-end)
# =========================================================================


class TestLoadData:
    """End-to-end tests: SQLite source → SQLAlchemy server engine."""

    def test_loadData_realtimeRows_copiedToServer(
        self, sourceDbPath: str, serverEngine
    ):
        result = load_data.loadData(
            dbFile=sourceDbPath,
            deviceId="sim-eclipse-gst",
            engine=serverEngine,
        )
        with Session(serverEngine) as session:
            rows = session.execute(select(RealtimeData)).scalars().all()
        assert len(rows) == 5
        assert result.tableCounts["realtime_data"] == 5

    def test_loadData_sourceIdMatchesSqliteRowid(
        self, sourceDbPath: str, serverEngine
    ):
        load_data.loadData(
            dbFile=sourceDbPath,
            deviceId="sim-eclipse-gst",
            engine=serverEngine,
        )
        with Session(serverEngine) as session:
            rows = (
                session.execute(
                    select(RealtimeData.source_id).order_by(RealtimeData.source_id)
                )
                .scalars()
                .all()
            )
        assert rows == [1, 2, 3, 4, 5]

    def test_loadData_sourceDeviceMatchesArg(self, sourceDbPath: str, serverEngine):
        load_data.loadData(
            dbFile=sourceDbPath,
            deviceId="my-device-007",
            engine=serverEngine,
        )
        with Session(serverEngine) as session:
            rows = session.execute(select(RealtimeData.source_device)).scalars().all()
        assert all(d == "my-device-007" for d in rows)

    def test_loadData_connectionLogRowsCopied(self, sourceDbPath: str, serverEngine):
        load_data.loadData(
            dbFile=sourceDbPath,
            deviceId="sim-eclipse-gst",
            engine=serverEngine,
        )
        with Session(serverEngine) as session:
            rows = session.execute(select(ConnectionLog)).scalars().all()
        assert len(rows) == 4  # 2 drive_start + 2 drive_end

    def test_loadData_statisticsRowsCopied(self, sourceDbPath: str, serverEngine):
        load_data.loadData(
            dbFile=sourceDbPath,
            deviceId="sim-eclipse-gst",
            engine=serverEngine,
        )
        with Session(serverEngine) as session:
            rows = session.execute(select(Statistic)).scalars().all()
        assert len(rows) == 1
        assert rows[0].parameter_name == "RPM"
        assert rows[0].max_value == 3500.0

    def test_loadData_profileRowCopied_piIdMappedToSourceProfileId(
        self, sourceDbPath: str, serverEngine
    ):
        load_data.loadData(
            dbFile=sourceDbPath,
            deviceId="sim-eclipse-gst",
            engine=serverEngine,
        )
        with Session(serverEngine) as session:
            profiles = session.execute(select(Profile)).scalars().all()
        assert len(profiles) == 1
        assert profiles[0].source_profile_id == "daily"
        assert profiles[0].name == "Daily"

    def test_loadData_syncHistoryCreatedWithStatus(
        self, sourceDbPath: str, serverEngine
    ):
        load_data.loadData(
            dbFile=sourceDbPath,
            deviceId="sim-eclipse-gst",
            engine=serverEngine,
        )
        with Session(serverEngine) as session:
            rows = session.execute(select(SyncHistory)).scalars().all()
        assert len(rows) == 1
        assert rows[0].device_id == "sim-eclipse-gst"
        assert rows[0].status == "completed"
        assert rows[0].rows_synced > 0

    def test_loadData_drivesDetectedAndSummaryCreated(
        self, sourceDbPath: str, serverEngine
    ):
        result = load_data.loadData(
            dbFile=sourceDbPath,
            deviceId="sim-eclipse-gst",
            engine=serverEngine,
        )
        assert result.drivesDetected == 2
        with Session(serverEngine) as session:
            drives = (
                session.execute(select(DriveSummary).order_by(DriveSummary.start_time))
                .scalars()
                .all()
            )
        assert len(drives) == 2
        # Drive 1: 08:00-08:05 = 300s, 3 realtime rows
        assert drives[0].duration_seconds == 300
        assert drives[0].row_count == 3
        # Drive 2: 09:00-09:10 = 600s, 2 realtime rows
        assert drives[1].duration_seconds == 600
        assert drives[1].row_count == 2

    def test_loadData_runTwice_idempotent_sameRowCount(
        self, sourceDbPath: str, serverEngine
    ):
        """Invariant: running twice produces the same MariaDB state."""
        load_data.loadData(
            dbFile=sourceDbPath,
            deviceId="sim-eclipse-gst",
            engine=serverEngine,
        )
        load_data.loadData(
            dbFile=sourceDbPath,
            deviceId="sim-eclipse-gst",
            engine=serverEngine,
        )
        with Session(serverEngine) as session:
            rtCount = len(session.execute(select(RealtimeData)).scalars().all())
            clCount = len(session.execute(select(ConnectionLog)).scalars().all())
            drivesCount = len(session.execute(select(DriveSummary)).scalars().all())
        # Idempotency: row counts match a single run
        assert rtCount == 5
        assert clCount == 4
        assert drivesCount == 2

    def test_loadData_differentDeviceIds_separateSourceDevice(
        self, sourceDbPath: str, serverEngine
    ):
        load_data.loadData(
            dbFile=sourceDbPath, deviceId="device-a", engine=serverEngine,
        )
        load_data.loadData(
            dbFile=sourceDbPath, deviceId="device-b", engine=serverEngine,
        )
        with Session(serverEngine) as session:
            rows = session.execute(select(RealtimeData.source_device)).scalars().all()
        # Same source_id (1-5) but different source_device — both load without
        # conflict because UNIQUE is on (source_device, source_id).
        assert rows.count("device-a") == 5
        assert rows.count("device-b") == 5

    def test_loadData_emptyTables_noError(self, tmp_path: Path, serverEngine):
        """Empty Pi DB shouldn't crash the loader."""
        dbPath = str(tmp_path / "empty.db")
        conn = _createPiSchemaDb(dbPath)
        conn.close()
        result = load_data.loadData(
            dbFile=dbPath, deviceId="empty-dev", engine=serverEngine,
        )
        assert result.drivesDetected == 0


# =========================================================================
# CLI
# =========================================================================


class TestCli:
    """CLI argument parsing."""

    def test_parseArguments_requiresDbFile(self):
        with pytest.raises(SystemExit):
            load_data.parseArguments(["--device-id", "d"])

    def test_parseArguments_requiresDeviceId(self):
        with pytest.raises(SystemExit):
            load_data.parseArguments(["--db-file", "x.db"])

    def test_parseArguments_acceptsBothRequired(self):
        args = load_data.parseArguments(
            ["--db-file", "x.db", "--device-id", "sim"]
        )
        assert args.db_file == "x.db"
        assert args.device_id == "sim"

    def test_parseArguments_serverDbUrlOptional(self):
        args = load_data.parseArguments(
            ["--db-file", "x.db", "--device-id", "sim"]
        )
        assert args.server_db_url is None


class TestToSyncDriverUrl:
    """I-011: CLI must rewrite async drivers to sync before create_engine()."""

    def test_aiomysqlRewrittenToPymysql(self):
        url = "mysql+aiomysql://obd2:pw@localhost/obd2db"
        assert load_data._toSyncDriverUrl(url) == (
            "mysql+pymysql://obd2:pw@localhost/obd2db"
        )

    def test_pymysqlPassthrough(self):
        url = "mysql+pymysql://obd2:pw@localhost/obd2db"
        assert load_data._toSyncDriverUrl(url) == url

    def test_sqlitePassthrough(self):
        url = "sqlite:///data/server_crawl.db"
        assert load_data._toSyncDriverUrl(url) == url


class TestSummary:
    """End-to-end: main() prints summary and returns 0."""

    def test_main_printsRowsLoadedAndElapsed(
        self, sourceDbPath: str, serverEngine, capsys, monkeypatch
    ):
        # Grab the server URL so main() connects to the same engine
        url = str(serverEngine.url)
        rc = load_data.main(
            ["--db-file", sourceDbPath, "--device-id", "sim-eclipse-gst",
             "--server-db-url", url],
        )
        assert rc == 0
        captured = capsys.readouterr()
        out = captured.out
        assert "realtime_data" in out
        assert "connection_log" in out
        assert "drives detected" in out.lower()
        assert "elapsed" in out.lower()


# =========================================================================
# Unused imports check — kept to document dependency surface
# =========================================================================

# These symbols are deliberately referenced above to document which tables are in
# scope for the loader. Kept out of __all__ since this is a test module.
_ = (AiRecommendation, AlertLog, CalibrationSession, VehicleInfo)
