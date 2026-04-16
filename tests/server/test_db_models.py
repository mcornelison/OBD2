################################################################################
# File Name: test_db_models.py
# Purpose/Description: Tests for server-side SQLAlchemy models (US-CMP-003)
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-CMP-003 — MariaDB
#               |              | schema models, connection, and setup script
# ================================================================================
################################################################################

"""
Tests for src/server/db — MariaDB schema models, async connection, and setup.

Validates:
    - All 15 tables defined as SQLAlchemy models
    - Synced tables carry source_id, source_device, UNIQUE constraint
    - Server-only and analytics tables have correct columns
    - Connection module provides async session factory
    - Setup script creates correct databases and grants
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Integer, String, UniqueConstraint

# ---- Helpers -----------------------------------------------------------------


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _getUniqueConstraintColumns(model):
    """Extract column sets from UniqueConstraints on a model's table."""
    constraints = []
    for constraint in model.__table__.constraints:
        if isinstance(constraint, UniqueConstraint):
            constraints.append(tuple(col.name for col in constraint.columns))
    return constraints


def _getColumnNames(model):
    """Get all column names for a model."""
    return [col.name for col in model.__table__.columns]


def _getColumn(model, name):
    """Get a specific column from a model's table."""
    return model.__table__.columns[name]


# ---- Model Import Tests ------------------------------------------------------


class TestModelImports:
    """Verify all 15 models can be imported."""

    def test_importSyncedModels(self):
        """All 8 synced table models are importable."""
        from src.server.db.models import (
            AiRecommendation,
            AlertLog,
            CalibrationSession,
            ConnectionLog,
            Profile,
            RealtimeData,
            Statistic,
            VehicleInfo,
        )

        assert RealtimeData is not None
        assert Statistic is not None
        assert Profile is not None
        assert VehicleInfo is not None
        assert AiRecommendation is not None
        assert ConnectionLog is not None
        assert AlertLog is not None
        assert CalibrationSession is not None

    def test_importServerOnlyModels(self):
        """All 3 server-only models are importable."""
        from src.server.db.models import (
            AnalysisHistory,
            Device,
            SyncHistory,
        )

        assert SyncHistory is not None
        assert AnalysisHistory is not None
        assert Device is not None

    def test_importAnalyticsModels(self):
        """All 4 analytics models are importable."""
        from src.server.db.models import (
            AnomalyLog,
            DriveStatistic,
            DriveSummary,
            TrendSnapshot,
        )

        assert DriveSummary is not None
        assert DriveStatistic is not None
        assert TrendSnapshot is not None
        assert AnomalyLog is not None

    def test_importBase(self):
        """DeclarativeBase is importable for engine.create_all()."""
        from src.server.db.models import Base

        assert Base is not None

    def test_importFromPackageInit(self):
        """Key symbols are re-exported from db package."""
        from src.server.db import Base, DriveSummary, RealtimeData

        assert Base is not None
        assert RealtimeData is not None
        assert DriveSummary is not None


# ---- Synced Table Pattern Tests -----------------------------------------------


SYNCED_MODELS = [
    "RealtimeData",
    "Statistic",
    "Profile",
    "VehicleInfo",
    "AiRecommendation",
    "ConnectionLog",
    "AlertLog",
    "CalibrationSession",
]


class TestSyncedTablePattern:
    """Every synced table must have id, source_id, source_device, UNIQUE."""

    @pytest.fixture(params=SYNCED_MODELS)
    def syncedModel(self, request):
        """Parametrized fixture providing each synced model class."""
        import src.server.db.models as models

        return getattr(models, request.param)

    def test_hasPrimaryKeyId(self, syncedModel):
        """
        Given: a synced table model
        When: inspecting columns
        Then: has 'id' column as autoincrement integer PK
        """
        col = _getColumn(syncedModel, "id")
        assert col.primary_key
        assert isinstance(col.type, Integer)
        assert col.autoincrement is not False  # True or "auto"

    def test_hasSourceIdColumn(self, syncedModel):
        """
        Given: a synced table model
        When: inspecting columns
        Then: has 'source_id' INT NOT NULL
        """
        col = _getColumn(syncedModel, "source_id")
        assert isinstance(col.type, Integer)
        assert col.nullable is False

    def test_hasSourceDeviceColumn(self, syncedModel):
        """
        Given: a synced table model
        When: inspecting columns
        Then: has 'source_device' VARCHAR(64) NOT NULL
        """
        col = _getColumn(syncedModel, "source_device")
        assert isinstance(col.type, String)
        assert col.type.length == 64
        assert col.nullable is False

    def test_hasUniqueConstraint(self, syncedModel):
        """
        Given: a synced table model
        When: inspecting constraints
        Then: has UNIQUE(source_device, source_id)
        """
        constraints = _getUniqueConstraintColumns(syncedModel)
        assert ("source_device", "source_id") in constraints


# ---- Synced Table Column Tests ------------------------------------------------


class TestRealtimeDataColumns:
    """Verify realtime_data mirrors Pi schema + server additions."""

    def test_hasExpectedColumns(self):
        from src.server.db.models import RealtimeData

        cols = _getColumnNames(RealtimeData)
        for expected in [
            "id", "timestamp", "parameter_name", "value", "unit",
            "profile_id", "source_id", "source_device", "synced_at",
            "sync_batch_id",
        ]:
            assert expected in cols, f"Missing column: {expected}"

    def test_tableName(self):
        from src.server.db.models import RealtimeData

        assert RealtimeData.__tablename__ == "realtime_data"


class TestStatisticColumns:
    """Verify statistics mirrors Pi schema + server additions."""

    def test_hasExpectedColumns(self):
        from src.server.db.models import Statistic

        cols = _getColumnNames(Statistic)
        for expected in [
            "id", "parameter_name", "analysis_date", "profile_id",
            "max_value", "min_value", "avg_value", "std_1", "std_2",
            "outlier_min", "outlier_max", "sample_count",
            "source_id", "source_device", "synced_at", "sync_batch_id",
        ]:
            assert expected in cols, f"Missing column: {expected}"


class TestConnectionLogColumns:
    """Verify connection_log mirrors Pi schema + server additions."""

    def test_hasExpectedColumns(self):
        from src.server.db.models import ConnectionLog

        cols = _getColumnNames(ConnectionLog)
        for expected in [
            "id", "timestamp", "event_type", "mac_address",
            "success", "error_message", "retry_count",
            "source_id", "source_device", "synced_at", "sync_batch_id",
        ]:
            assert expected in cols, f"Missing column: {expected}"


class TestAlertLogColumns:
    """Verify alert_log mirrors Pi schema + server additions."""

    def test_hasExpectedColumns(self):
        from src.server.db.models import AlertLog

        cols = _getColumnNames(AlertLog)
        for expected in [
            "id", "timestamp", "alert_type", "parameter_name",
            "value", "threshold", "profile_id",
            "source_id", "source_device", "synced_at", "sync_batch_id",
        ]:
            assert expected in cols, f"Missing column: {expected}"


# ---- Server-Only Table Tests --------------------------------------------------


class TestDeviceColumns:
    """Verify devices table has registration fields."""

    def test_hasExpectedColumns(self):
        from src.server.db.models import Device

        cols = _getColumnNames(Device)
        for expected in [
            "id", "device_id", "display_name", "last_seen",
            "api_key_hash", "created_at",
        ]:
            assert expected in cols, f"Missing column: {expected}"

    def test_tableName(self):
        from src.server.db.models import Device

        assert Device.__tablename__ == "devices"

    def test_deviceIdUnique(self):
        from src.server.db.models import Device

        col = _getColumn(Device, "device_id")
        assert col.unique is True


class TestSyncHistoryColumns:
    """Verify sync_history table tracks sync batches."""

    def test_hasExpectedColumns(self):
        from src.server.db.models import SyncHistory

        cols = _getColumnNames(SyncHistory)
        for expected in [
            "id", "device_id", "started_at", "completed_at",
            "rows_synced", "status",
        ]:
            assert expected in cols, f"Missing column: {expected}"

    def test_tableName(self):
        from src.server.db.models import SyncHistory

        assert SyncHistory.__tablename__ == "sync_history"


class TestAnalysisHistoryColumns:
    """Verify analysis_history table tracks AI runs."""

    def test_hasExpectedColumns(self):
        from src.server.db.models import AnalysisHistory

        cols = _getColumnNames(AnalysisHistory)
        for expected in [
            "id", "drive_id", "model_name", "started_at",
            "completed_at", "status",
        ]:
            assert expected in cols, f"Missing column: {expected}"


# ---- Analytics Table Tests ----------------------------------------------------


class TestDriveSummaryColumns:
    """Verify drive_summary has one-row-per-drive fields."""

    def test_hasExpectedColumns(self):
        from src.server.db.models import DriveSummary

        cols = _getColumnNames(DriveSummary)
        for expected in [
            "id", "device_id", "start_time", "end_time",
            "duration_seconds", "profile_id", "row_count",
        ]:
            assert expected in cols, f"Missing column: {expected}"

    def test_tableName(self):
        from src.server.db.models import DriveSummary

        assert DriveSummary.__tablename__ == "drive_summary"


class TestDriveStatisticColumns:
    """Verify drive_statistics has per-parameter stats."""

    def test_hasExpectedColumns(self):
        from src.server.db.models import DriveStatistic

        cols = _getColumnNames(DriveStatistic)
        for expected in [
            "id", "drive_id", "parameter_name",
            "min_value", "max_value", "avg_value", "std_dev",
            "outlier_min", "outlier_max", "sample_count",
        ]:
            assert expected in cols, f"Missing column: {expected}"

    def test_tableName(self):
        from src.server.db.models import DriveStatistic

        assert DriveStatistic.__tablename__ == "drive_statistics"


class TestTrendSnapshotColumns:
    """Verify trend_snapshots stores rolling trend calculations."""

    def test_hasExpectedColumns(self):
        from src.server.db.models import TrendSnapshot

        cols = _getColumnNames(TrendSnapshot)
        for expected in [
            "id", "parameter_name", "window_size",
            "direction", "slope", "avg_peak", "avg_mean",
            "computed_at",
        ]:
            assert expected in cols, f"Missing column: {expected}"

    def test_tableName(self):
        from src.server.db.models import TrendSnapshot

        assert TrendSnapshot.__tablename__ == "trend_snapshots"


class TestAnomalyLogColumns:
    """Verify anomaly_log stores flagged deviations."""

    def test_hasExpectedColumns(self):
        from src.server.db.models import AnomalyLog

        cols = _getColumnNames(AnomalyLog)
        for expected in [
            "id", "drive_id", "parameter_name",
            "observed_value", "expected_min", "expected_max",
            "deviation_sigma", "severity", "detected_at",
        ]:
            assert expected in cols, f"Missing column: {expected}"

    def test_tableName(self):
        from src.server.db.models import AnomalyLog

        assert AnomalyLog.__tablename__ == "anomaly_log"


# ---- Table Count Test ---------------------------------------------------------


class TestTableCount:
    """Verify we have exactly 15 tables defined."""

    def test_totalTableCount(self):
        """
        Given: the models module
        When: counting all model classes with __tablename__
        Then: there are exactly 15 tables
        """
        from src.server.db.models import Base

        tableNames = list(Base.metadata.tables.keys())
        assert len(tableNames) == 15, (
            f"Expected 15 tables, got {len(tableNames)}: {tableNames}"
        )


# ---- Connection Module Tests --------------------------------------------------


class TestConnectionModule:
    """Verify connection.py provides async session factory."""

    def test_importCreateAsyncEngine(self):
        """createAsyncEngine function is importable."""
        from src.server.db.connection import createAsyncEngine

        assert callable(createAsyncEngine)

    def test_importGetAsyncSession(self):
        """getAsyncSession function is importable."""
        from src.server.db.connection import getAsyncSession

        assert callable(getAsyncSession)

    def test_createAsyncEngineTakesDatabaseUrl(self):
        """createAsyncEngine accepts a database_url string parameter."""
        try:
            import aiomysql  # noqa: F401
        except ImportError:
            pytest.skip("aiomysql not installed — deferred to server deploy")

        import asyncio

        from src.server.db.connection import createAsyncEngine

        engine = createAsyncEngine("mysql+aiomysql://user:pass@localhost/testdb")
        assert engine is not None

        async def _dispose():
            await engine.dispose()

        try:
            asyncio.get_event_loop().run_until_complete(_dispose())
        except RuntimeError:
            asyncio.run(_dispose())


# ---- Setup Script Tests -------------------------------------------------------


class TestSetupMariadbScript:
    """Verify deploy/setup-mariadb.sh contents."""

    @pytest.fixture
    def scriptContent(self):
        """Read the setup script content."""
        scriptPath = PROJECT_ROOT / "deploy" / "setup-mariadb.sh"
        assert scriptPath.exists(), f"Script not found: {scriptPath}"
        return scriptPath.read_text(encoding="utf-8")

    def test_createsObd2dbDatabase(self, scriptContent):
        """Script creates the obd2db database."""
        assert "obd2db" in scriptContent

    def test_createsTestDatabase(self, scriptContent):
        """Script creates the obd2db_test database."""
        assert "obd2db_test" in scriptContent

    def test_grantsToObd2User(self, scriptContent):
        """Script grants privileges to 'obd2' user."""
        assert "obd2" in scriptContent

    def test_grantsFromSubnet(self, scriptContent):
        """Script grants access from 10.27.27.% subnet."""
        assert "10.27.27.%" in scriptContent

    def test_hasDryRunFlag(self, scriptContent):
        """Script supports --dry-run flag."""
        assert "--dry-run" in scriptContent

    def test_isExecutable(self):
        """Script has a shebang line."""
        scriptPath = PROJECT_ROOT / "deploy" / "setup-mariadb.sh"
        firstLine = scriptPath.read_text(encoding="utf-8").split("\n")[0]
        assert firstLine.startswith("#!/bin/bash")
