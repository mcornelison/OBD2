#!/usr/bin/env python3
################################################################################
# File Name: run_tests_data_exporter.py
# Purpose/Description: Manual test runner for data export tests
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""
Manual test runner for data export module tests.

Runs tests without requiring pytest installed.
Useful for environments where pytest is not available.

Usage:
    python tests/run_tests_data_exporter.py
"""

import csv
import json
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Add src to path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from obd.database import ObdDatabase
from obd.data_exporter import (
    DataExporter,
    ExportResult,
    SummaryExportResult,
    ExportFormat,
    DataExportError,
    InvalidDateRangeError,
    ExportDirectoryError,
    createExporterFromConfig,
    exportRealtimeDataToCsv,
    exportRealtimeDataToJson,
    exportSummaryReport,
)


# Test utilities
class TestResult:
    """Stores test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors: List[str] = []


def runTest(name: str, testFunc: Callable, result: TestResult) -> None:
    """Run a single test and record result."""
    try:
        testFunc()
        result.passed += 1
        print(f"  [PASS] {name}")
    except AssertionError as e:
        result.failed += 1
        result.errors.append(f"{name}: {e}")
        print(f"  [FAIL] {name}: {e}")
    except Exception as e:
        result.failed += 1
        result.errors.append(f"{name}: {e}")
        print(f"  [ERROR] {name}: {e}")
        traceback.print_exc()


def createTestDatabase() -> tuple:
    """Create a temporary test database and return (database, path)."""
    tmpFile = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmpFile.close()
    db = ObdDatabase(tmpFile.name)
    db.initialize()
    return db, tmpFile.name


def cleanupDatabase(dbPath: str) -> None:
    """Clean up temporary database file."""
    try:
        if os.path.exists(dbPath):
            os.remove(dbPath)
        walPath = dbPath + '-wal'
        shmPath = dbPath + '-shm'
        if os.path.exists(walPath):
            os.remove(walPath)
        if os.path.exists(shmPath):
            os.remove(shmPath)
    except Exception:
        pass


def createTestExportDir() -> str:
    """Create a temporary export directory."""
    return tempfile.mkdtemp(prefix='obd_export_')


def cleanupExportDir(dirPath: str) -> None:
    """Clean up temporary export directory."""
    try:
        if os.path.exists(dirPath):
            shutil.rmtree(dirPath)
    except Exception:
        pass


def ensureProfileExists(db: ObdDatabase, profileId: str) -> None:
    """Ensure a profile exists in the profiles table."""
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO profiles (id, name, description)
            VALUES (?, ?, ?)
            """,
            (profileId, profileId.capitalize(), f'Test profile {profileId}')
        )


def insertTestData(
    db: ObdDatabase,
    parameterName: str,
    values: List[float],
    profileId: str = 'daily',
    daysAgo: int = 0,
    unit: str = 'unit'
) -> None:
    """Insert test data into realtime_data table with specific age."""
    ensureProfileExists(db, profileId)

    baseTimestamp = datetime.now() - timedelta(days=daysAgo)

    with db.connect() as conn:
        cursor = conn.cursor()
        for i, value in enumerate(values):
            timestamp = baseTimestamp - timedelta(seconds=i)
            cursor.execute(
                """
                INSERT INTO realtime_data
                (timestamp, parameter_name, value, unit, profile_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (timestamp, parameterName, value, unit, profileId)
            )


def getDefaultConfig() -> Dict[str, Any]:
    """Get default configuration for testing."""
    return {
        'export': {
            'directory': './exports/',
            'defaultFormat': 'csv'
        }
    }


def insertStatistics(
    db: ObdDatabase,
    parameterName: str,
    profileId: str = 'daily',
    maxVal: float = 100.0,
    minVal: float = 0.0,
    avgVal: float = 50.0
) -> None:
    """Insert test statistics into statistics table."""
    ensureProfileExists(db, profileId)

    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO statistics
            (parameter_name, analysis_date, profile_id, max_value, min_value,
             avg_value, mode_value, std_1, std_2, outlier_min, outlier_max, sample_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (parameterName, datetime.now(), profileId, maxVal, minVal,
             avgVal, avgVal, 10.0, 20.0, minVal - 20, maxVal + 20, 100)
        )


def insertRecommendation(
    db: ObdDatabase,
    recommendation: str,
    profileId: str = 'daily',
    priorityRank: int = 3,
    isDuplicateOf: Optional[int] = None
) -> int:
    """Insert test AI recommendation and return its ID."""
    ensureProfileExists(db, profileId)

    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ai_recommendations
            (timestamp, recommendation, priority_rank, is_duplicate_of, profile_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (datetime.now(), recommendation, priorityRank, isDuplicateOf, profileId)
        )
        return cursor.lastrowid


def insertAlert(
    db: ObdDatabase,
    alertType: str,
    parameterName: str,
    value: float,
    threshold: float,
    profileId: str = 'daily'
) -> None:
    """Insert test alert into alert_log table."""
    ensureProfileExists(db, profileId)

    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO alert_log
            (timestamp, alert_type, parameter_name, value, threshold, profile_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (datetime.now(), alertType, parameterName, value, threshold, profileId)
        )


# ================================================================================
# ExportResult Tests
# ================================================================================

def testExportResultSuccess():
    """Test ExportResult with successful export."""
    result = ExportResult(
        success=True,
        filePath='/path/to/file.csv',
        recordCount=100,
        format=ExportFormat.CSV,
        executionTimeMs=500
    )
    assert result.success is True
    assert result.filePath == '/path/to/file.csv'
    assert result.recordCount == 100
    assert result.format == ExportFormat.CSV
    assert result.executionTimeMs == 500
    assert result.errorMessage is None


def testExportResultFailure():
    """Test ExportResult with failed export."""
    result = ExportResult(
        success=False,
        recordCount=0,
        errorMessage="Export failed"
    )
    assert result.success is False
    assert result.recordCount == 0
    assert result.errorMessage == "Export failed"


def testExportResultToDict():
    """Test ExportResult toDict serialization."""
    now = datetime.now()
    result = ExportResult(
        success=True,
        filePath='/path/to/export.csv',
        recordCount=50,
        format=ExportFormat.CSV,
        startDate=now - timedelta(days=7),
        endDate=now,
        profileId='daily',
        parameters=['RPM', 'SPEED'],
        executionTimeMs=100
    )
    d = result.toDict()
    assert d['success'] is True
    assert d['filePath'] == '/path/to/export.csv'
    assert d['recordCount'] == 50
    assert d['format'] == 'csv'
    assert d['profileId'] == 'daily'
    assert d['parameters'] == ['RPM', 'SPEED']


def testExportResultToDictNullValues():
    """Test ExportResult toDict with null values."""
    result = ExportResult(success=True, recordCount=0)
    d = result.toDict()
    assert d['filePath'] is None
    assert d['startDate'] is None
    assert d['endDate'] is None
    assert d['profileId'] is None
    assert d['parameters'] is None


def testExportFormatEnum():
    """Test ExportFormat enum values."""
    assert ExportFormat.CSV.value == 'csv'
    assert ExportFormat.fromString('csv') == ExportFormat.CSV
    assert ExportFormat.fromString('CSV') == ExportFormat.CSV


def testExportFormatEnumJson():
    """Test ExportFormat enum JSON value."""
    assert ExportFormat.JSON.value == 'json'
    assert ExportFormat.fromString('json') == ExportFormat.JSON
    assert ExportFormat.fromString('JSON') == ExportFormat.JSON


# ================================================================================
# DataExporter Initialization Tests
# ================================================================================

def testExporterInitWithConfig():
    """Test exporter initialization with configuration."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {
            'export': {
                'directory': exportDir
            }
        }
        exporter = DataExporter(db, config)

        assert exporter.exportDirectory == exportDir
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExporterInitWithDefaultConfig():
    """Test exporter uses defaults with empty config."""
    db, dbPath = createTestDatabase()
    try:
        config = {}
        exporter = DataExporter(db, config)

        assert exporter.exportDirectory == './exports/'
    finally:
        cleanupDatabase(dbPath)


def testExporterInitCreatesExportDirectory():
    """Test exporter creates export directory if not exists."""
    db, dbPath = createTestDatabase()
    tmpDir = tempfile.mkdtemp()
    exportDir = os.path.join(tmpDir, 'new_exports')
    try:
        config = {
            'export': {
                'directory': exportDir
            }
        }
        exporter = DataExporter(db, config)
        exporter.ensureExportDirectory()

        assert os.path.exists(exportDir)
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(tmpDir)


# ================================================================================
# exportToCsv Tests
# ================================================================================

def testExportToCsvNoData():
    """Test CSV export with no data in database."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(startDate, endDate)

        assert result.success is True
        assert result.recordCount == 0
        assert result.format == ExportFormat.CSV
        # File should still be created with header
        assert result.filePath is not None
        assert os.path.exists(result.filePath)
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToCsvWithData():
    """Test CSV export with data."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000, 1100, 1200], daysAgo=3, unit='rpm')
        insertTestData(db, 'SPEED', [50, 60, 70], daysAgo=3, unit='km/h')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(startDate, endDate)

        assert result.success is True
        assert result.recordCount == 6
        assert os.path.exists(result.filePath)

        # Verify CSV content
        with open(result.filePath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
            # Header + 6 data rows
            assert len(rows) == 7
            # Check header
            assert rows[0] == ['timestamp', 'parameter_name', 'value', 'unit']
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToCsvFilename():
    """Test CSV export generates correct filename."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime(2026, 1, 15)
        endDate = datetime(2026, 1, 22)

        result = exporter.exportToCsv(startDate, endDate)

        assert result.success is True
        expectedFilename = 'obd_export_2026-01-15_to_2026-01-22.csv'
        assert os.path.basename(result.filePath) == expectedFilename
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToCsvDateRange():
    """Test CSV export respects date range."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        # Insert data at different ages
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=10)  # Outside range
        insertTestData(db, 'RPM', [2000, 2100, 2200], daysAgo=3)  # Inside range

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(startDate, endDate)

        assert result.success is True
        assert result.recordCount == 3  # Only data within range
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToCsvWithProfileId():
    """Test CSV export filters by profile ID."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000, 1100], profileId='daily', daysAgo=3)
        insertTestData(db, 'RPM', [2000, 2100], profileId='performance', daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(startDate, endDate, profileId='daily')

        assert result.success is True
        assert result.recordCount == 2  # Only daily profile data
        assert result.profileId == 'daily'
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToCsvWithParameters():
    """Test CSV export filters by parameters."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=3)
        insertTestData(db, 'SPEED', [50, 60], daysAgo=3)
        insertTestData(db, 'COOLANT_TEMP', [80, 85], daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(
            startDate, endDate,
            parameters=['RPM', 'SPEED']
        )

        assert result.success is True
        assert result.recordCount == 4  # Only RPM and SPEED
        assert result.parameters == ['RPM', 'SPEED']
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToCsvCombinedFilters():
    """Test CSV export with profile and parameters filter."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], profileId='daily', daysAgo=3)
        insertTestData(db, 'SPEED', [50], profileId='daily', daysAgo=3)
        insertTestData(db, 'RPM', [2000], profileId='performance', daysAgo=3)
        insertTestData(db, 'COOLANT_TEMP', [80], profileId='daily', daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(
            startDate, endDate,
            profileId='daily',
            parameters=['RPM', 'SPEED']
        )

        assert result.success is True
        assert result.recordCount == 2  # RPM and SPEED from daily only
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToCsvHeader():
    """Test CSV export includes proper header."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], daysAgo=3, unit='rpm')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(startDate, endDate)

        with open(result.filePath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == ['timestamp', 'parameter_name', 'value', 'unit']
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToCsvDataFormat():
    """Test CSV export data is properly formatted."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        # Insert specific data
        ensureProfileExists(db, 'daily')
        timestamp = datetime(2026, 1, 20, 10, 30, 45, 123456)
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO realtime_data
                (timestamp, parameter_name, value, unit, profile_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (timestamp, 'RPM', 3500.5, 'rpm', 'daily')
            )

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime(2026, 1, 1)
        endDate = datetime(2026, 1, 31)

        result = exporter.exportToCsv(startDate, endDate)

        with open(result.filePath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            row = next(reader)
            assert row[1] == 'RPM'  # parameter_name
            assert float(row[2]) == 3500.5  # value
            assert row[3] == 'rpm'  # unit
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToCsvEmptyWithHeaderOnly():
    """Test CSV export with no matching data still creates header."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(startDate, endDate)

        assert result.success is True
        assert result.recordCount == 0

        with open(result.filePath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == ['timestamp', 'parameter_name', 'value', 'unit']
            # No more rows
            try:
                next(reader)
                assert False, "Expected no data rows"
            except StopIteration:
                pass
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToCsvCustomFilename():
    """Test CSV export with custom filename."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(
            startDate, endDate,
            filename='custom_export.csv'
        )

        assert result.success is True
        assert os.path.basename(result.filePath) == 'custom_export.csv'
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


# ================================================================================
# Date Validation Tests
# ================================================================================

def testExportInvalidDateRange():
    """Test export fails with end date before start date."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now()
        endDate = datetime.now() - timedelta(days=7)  # End before start

        try:
            exporter.exportToCsv(startDate, endDate)
            assert False, "Expected InvalidDateRangeError"
        except InvalidDateRangeError as e:
            assert 'end date' in str(e).lower()
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportSameDayRange():
    """Test export with same start and end date."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        # Insert data today
        ensureProfileExists(db, 'daily')
        now = datetime.now()
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO realtime_data
                (timestamp, parameter_name, value, unit, profile_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now, 'RPM', 1000, 'rpm', 'daily')
            )

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportToCsv(
            now.replace(hour=0, minute=0, second=0, microsecond=0),
            now.replace(hour=23, minute=59, second=59, microsecond=999999)
        )

        assert result.success is True
        assert result.recordCount >= 1
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


# ================================================================================
# Directory Tests
# ================================================================================

def testExportCreatesDirectoryIfNotExists():
    """Test export creates directory if it doesn't exist."""
    db, dbPath = createTestDatabase()
    tmpDir = tempfile.mkdtemp()
    exportDir = os.path.join(tmpDir, 'subdir', 'exports')
    try:
        assert not os.path.exists(exportDir)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(startDate, endDate)

        assert result.success is True
        assert os.path.exists(exportDir)
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(tmpDir)


# ================================================================================
# Helper Function Tests
# ================================================================================

def testCreateExporterFromConfig():
    """Test createExporterFromConfig helper."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {'export': {'directory': exportDir}}
        exporter = createExporterFromConfig(db, config)

        assert isinstance(exporter, DataExporter)
        assert exporter.exportDirectory == exportDir
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportRealtimeDataToCsvHelper():
    """Test exportRealtimeDataToCsv helper function."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=3)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exportRealtimeDataToCsv(
            db, startDate, endDate,
            exportDirectory=exportDir
        )

        assert result.success is True
        assert result.recordCount == 2
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportRealtimeDataToCsvHelperWithFilters():
    """Test exportRealtimeDataToCsv helper with filters."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], profileId='daily', daysAgo=3)
        insertTestData(db, 'SPEED', [50], profileId='daily', daysAgo=3)
        insertTestData(db, 'RPM', [2000], profileId='performance', daysAgo=3)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exportRealtimeDataToCsv(
            db, startDate, endDate,
            profileId='daily',
            parameters=['RPM'],
            exportDirectory=exportDir
        )

        assert result.success is True
        assert result.recordCount == 1  # Only daily RPM
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


# ================================================================================
# Edge Cases Tests
# ================================================================================

def testExportLargeDataset():
    """Test export handles larger datasets."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        ensureProfileExists(db, 'daily')
        baseTimestamp = datetime.now() - timedelta(days=3)

        with db.connect() as conn:
            cursor = conn.cursor()
            for i in range(1000):
                cursor.execute(
                    """
                    INSERT INTO realtime_data
                    (timestamp, parameter_name, value, unit, profile_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (baseTimestamp - timedelta(seconds=i), 'RPM', 1000 + i, 'rpm', 'daily')
                )

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(startDate, endDate)

        assert result.success is True
        assert result.recordCount == 1000
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportMultipleParameters():
    """Test export with many different parameters."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        parameters = ['RPM', 'SPEED', 'COOLANT_TEMP', 'THROTTLE_POS', 'MAF']
        for param in parameters:
            insertTestData(db, param, [1000, 1100], daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(startDate, endDate)

        assert result.success is True
        assert result.recordCount == 10  # 5 params * 2 values each
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportNonExistentProfile():
    """Test export with non-existent profile returns empty."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], profileId='daily', daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(
            startDate, endDate,
            profileId='nonexistent'
        )

        assert result.success is True
        assert result.recordCount == 0
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportNonExistentParameter():
    """Test export with non-existent parameter returns empty for that param."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(
            startDate, endDate,
            parameters=['NONEXISTENT']
        )

        assert result.success is True
        assert result.recordCount == 0
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportSpecialCharactersInData():
    """Test export handles special characters in data."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        # Insert data with a parameter that might have special chars
        ensureProfileExists(db, 'daily')
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO realtime_data
                (timestamp, parameter_name, value, unit, profile_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (datetime.now(), 'TEST_PARAM', 100.5, 'km/h, "quoted"', 'daily')
            )

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=1)
        endDate = datetime.now() + timedelta(days=1)

        result = exporter.exportToCsv(startDate, endDate)

        assert result.success is True
        assert result.recordCount == 1

        # Verify CSV can be read back correctly
        with open(result.filePath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            row = next(reader)
            assert row[3] == 'km/h, "quoted"'
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportGeneratesResultMetadata():
    """Test export result contains all metadata."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], profileId='daily', daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToCsv(
            startDate, endDate,
            profileId='daily',
            parameters=['RPM']
        )

        assert result.success is True
        assert result.startDate == startDate
        assert result.endDate == endDate
        assert result.profileId == 'daily'
        assert result.parameters == ['RPM']
        assert result.executionTimeMs >= 0
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportOrderedByTimestamp():
    """Test export data is ordered by timestamp."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        ensureProfileExists(db, 'daily')
        # Insert out of order
        timestamps = [
            datetime(2026, 1, 20, 12, 0, 0),
            datetime(2026, 1, 20, 10, 0, 0),
            datetime(2026, 1, 20, 14, 0, 0),
            datetime(2026, 1, 20, 8, 0, 0),
        ]
        with db.connect() as conn:
            cursor = conn.cursor()
            for i, ts in enumerate(timestamps):
                cursor.execute(
                    """
                    INSERT INTO realtime_data
                    (timestamp, parameter_name, value, unit, profile_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (ts, 'RPM', 1000 + i, 'rpm', 'daily')
                )

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportToCsv(
            datetime(2026, 1, 1),
            datetime(2026, 1, 31)
        )

        with open(result.filePath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            rows = list(reader)

            # Verify rows are ordered by timestamp
            prevTs = None
            for row in rows:
                ts = row[0]
                if prevTs:
                    assert ts >= prevTs, "Rows not ordered by timestamp"
                prevTs = ts
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


# ================================================================================
# JSON Export Tests
# ================================================================================

def testExportToJsonNoData():
    """Test JSON export with no data in database."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToJson(startDate, endDate)

        assert result.success is True
        assert result.recordCount == 0
        assert result.format == ExportFormat.JSON
        assert result.filePath is not None
        assert os.path.exists(result.filePath)

        # Verify JSON structure
        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert 'metadata' in data
            assert 'data' in data
            assert data['metadata']['record_count'] == 0
            assert data['data'] == []
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonWithData():
    """Test JSON export with data."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000, 1100, 1200], daysAgo=3, unit='rpm')
        insertTestData(db, 'SPEED', [50, 60, 70], daysAgo=3, unit='km/h')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToJson(startDate, endDate)

        assert result.success is True
        assert result.recordCount == 6
        assert os.path.exists(result.filePath)

        # Verify JSON content
        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert data['metadata']['record_count'] == 6
            assert len(data['data']) == 6
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonFilename():
    """Test JSON export generates correct filename."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime(2026, 1, 15)
        endDate = datetime(2026, 1, 22)

        result = exporter.exportToJson(startDate, endDate)

        assert result.success is True
        expectedFilename = 'obd_export_2026-01-15_to_2026-01-22.json'
        assert os.path.basename(result.filePath) == expectedFilename
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonMetadata():
    """Test JSON export metadata structure."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], profileId='daily', daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime(2026, 1, 15)
        endDate = datetime(2026, 1, 22)

        result = exporter.exportToJson(startDate, endDate, profileId='daily')

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            metadata = data['metadata']

            assert 'export_date' in metadata
            assert metadata['profile'] == 'daily'
            assert 'date_range' in metadata
            assert metadata['date_range']['start'] == startDate.isoformat()
            assert metadata['date_range']['end'] == endDate.isoformat()
            assert 'record_count' in metadata
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonDataStructure():
    """Test JSON export data record structure."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        ensureProfileExists(db, 'daily')
        timestamp = datetime(2026, 1, 20, 10, 30, 45, 123456)
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO realtime_data
                (timestamp, parameter_name, value, unit, profile_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (timestamp, 'RPM', 3500.5, 'rpm', 'daily')
            )

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime(2026, 1, 1)
        endDate = datetime(2026, 1, 31)

        result = exporter.exportToJson(startDate, endDate)

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert len(data['data']) == 1
            record = data['data'][0]

            assert 'timestamp' in record
            assert 'parameter' in record
            assert 'value' in record
            assert 'unit' in record
            assert record['parameter'] == 'RPM'
            assert record['value'] == 3500.5
            assert record['unit'] == 'rpm'
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonDateRange():
    """Test JSON export respects date range."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        # Insert data at different ages
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=10)  # Outside range
        insertTestData(db, 'RPM', [2000, 2100, 2200], daysAgo=3)  # Inside range

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToJson(startDate, endDate)

        assert result.success is True
        assert result.recordCount == 3  # Only data within range
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonWithProfileId():
    """Test JSON export filters by profile ID."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000, 1100], profileId='daily', daysAgo=3)
        insertTestData(db, 'RPM', [2000, 2100], profileId='performance', daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToJson(startDate, endDate, profileId='daily')

        assert result.success is True
        assert result.recordCount == 2  # Only daily profile data
        assert result.profileId == 'daily'

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert data['metadata']['profile'] == 'daily'
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonWithParameters():
    """Test JSON export filters by parameters."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=3)
        insertTestData(db, 'SPEED', [50, 60], daysAgo=3)
        insertTestData(db, 'COOLANT_TEMP', [80, 85], daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToJson(
            startDate, endDate,
            parameters=['RPM', 'SPEED']
        )

        assert result.success is True
        assert result.recordCount == 4  # Only RPM and SPEED
        assert result.parameters == ['RPM', 'SPEED']
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonCombinedFilters():
    """Test JSON export with profile and parameters filter."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], profileId='daily', daysAgo=3)
        insertTestData(db, 'SPEED', [50], profileId='daily', daysAgo=3)
        insertTestData(db, 'RPM', [2000], profileId='performance', daysAgo=3)
        insertTestData(db, 'COOLANT_TEMP', [80], profileId='daily', daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToJson(
            startDate, endDate,
            profileId='daily',
            parameters=['RPM', 'SPEED']
        )

        assert result.success is True
        assert result.recordCount == 2  # RPM and SPEED from daily only
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonCustomFilename():
    """Test JSON export with custom filename."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToJson(
            startDate, endDate,
            filename='custom_export.json'
        )

        assert result.success is True
        assert os.path.basename(result.filePath) == 'custom_export.json'
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonInvalidDateRange():
    """Test JSON export fails with end date before start date."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now()
        endDate = datetime.now() - timedelta(days=7)  # End before start

        try:
            exporter.exportToJson(startDate, endDate)
            assert False, "Expected InvalidDateRangeError"
        except InvalidDateRangeError as e:
            assert 'end date' in str(e).lower()
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonCreatesDirectory():
    """Test JSON export creates directory if it doesn't exist."""
    db, dbPath = createTestDatabase()
    tmpDir = tempfile.mkdtemp()
    exportDir = os.path.join(tmpDir, 'subdir', 'json_exports')
    try:
        assert not os.path.exists(exportDir)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToJson(startDate, endDate)

        assert result.success is True
        assert os.path.exists(exportDir)
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(tmpDir)


def testExportToJsonNullProfile():
    """Test JSON export with null profile in metadata."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], daysAgo=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToJson(startDate, endDate)  # No profile filter

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert data['metadata']['profile'] is None
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonOrderedByTimestamp():
    """Test JSON export data is ordered by timestamp."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        ensureProfileExists(db, 'daily')
        # Insert out of order
        timestamps = [
            datetime(2026, 1, 20, 12, 0, 0),
            datetime(2026, 1, 20, 10, 0, 0),
            datetime(2026, 1, 20, 14, 0, 0),
            datetime(2026, 1, 20, 8, 0, 0),
        ]
        with db.connect() as conn:
            cursor = conn.cursor()
            for i, ts in enumerate(timestamps):
                cursor.execute(
                    """
                    INSERT INTO realtime_data
                    (timestamp, parameter_name, value, unit, profile_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (ts, 'RPM', 1000 + i, 'rpm', 'daily')
                )

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportToJson(
            datetime(2026, 1, 1),
            datetime(2026, 1, 31)
        )

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            records = data['data']

            # Verify rows are ordered by timestamp
            prevTs = None
            for record in records:
                ts = record['timestamp']
                if prevTs:
                    assert ts >= prevTs, "Records not ordered by timestamp"
                prevTs = ts
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportToJsonLargeDataset():
    """Test JSON export handles larger datasets."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        ensureProfileExists(db, 'daily')
        baseTimestamp = datetime.now() - timedelta(days=3)

        with db.connect() as conn:
            cursor = conn.cursor()
            for i in range(500):
                cursor.execute(
                    """
                    INSERT INTO realtime_data
                    (timestamp, parameter_name, value, unit, profile_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (baseTimestamp - timedelta(seconds=i), 'RPM', 1000 + i, 'rpm', 'daily')
                )

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exporter.exportToJson(startDate, endDate)

        assert result.success is True
        assert result.recordCount == 500

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert len(data['data']) == 500
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


# ================================================================================
# JSON Export Helper Function Tests
# ================================================================================

def testExportRealtimeDataToJsonHelper():
    """Test exportRealtimeDataToJson helper function."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=3)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exportRealtimeDataToJson(
            db, startDate, endDate,
            exportDirectory=exportDir
        )

        assert result.success is True
        assert result.recordCount == 2
        assert result.format == ExportFormat.JSON
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportRealtimeDataToJsonHelperWithFilters():
    """Test exportRealtimeDataToJson helper with filters."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], profileId='daily', daysAgo=3)
        insertTestData(db, 'SPEED', [50], profileId='daily', daysAgo=3)
        insertTestData(db, 'RPM', [2000], profileId='performance', daysAgo=3)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exportRealtimeDataToJson(
            db, startDate, endDate,
            profileId='daily',
            parameters=['RPM'],
            exportDirectory=exportDir
        )

        assert result.success is True
        assert result.recordCount == 1  # Only daily RPM
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportRealtimeDataToJsonHelperCustomFilename():
    """Test exportRealtimeDataToJson helper with custom filename."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertTestData(db, 'RPM', [1000], daysAgo=3)

        startDate = datetime.now() - timedelta(days=7)
        endDate = datetime.now()

        result = exportRealtimeDataToJson(
            db, startDate, endDate,
            exportDirectory=exportDir,
            filename='my_custom.json'
        )

        assert result.success is True
        assert os.path.basename(result.filePath) == 'my_custom.json'
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


# ================================================================================
# SummaryExportResult Tests
# ================================================================================

def testSummaryExportResultSuccess():
    """Test SummaryExportResult with successful export."""
    result = SummaryExportResult(
        success=True,
        filePath='/path/to/summary.json',
        format=ExportFormat.JSON,
        exportDate=datetime(2026, 1, 22),
        profileIds=['daily', 'performance'],
        statisticsCount=50,
        recommendationsCount=10,
        alertsCount=5,
        executionTimeMs=500
    )
    assert result.success is True
    assert result.filePath == '/path/to/summary.json'
    assert result.statisticsCount == 50
    assert result.recommendationsCount == 10
    assert result.alertsCount == 5
    assert result.totalRecordCount == 65


def testSummaryExportResultToDict():
    """Test SummaryExportResult toDict serialization."""
    exportDate = datetime(2026, 1, 22)
    result = SummaryExportResult(
        success=True,
        filePath='/path/to/summary.csv',
        format=ExportFormat.CSV,
        exportDate=exportDate,
        profileIds=['daily'],
        statisticsCount=20,
        recommendationsCount=5,
        alertsCount=3
    )
    d = result.toDict()
    assert d['success'] is True
    assert d['filePath'] == '/path/to/summary.csv'
    assert d['format'] == 'csv'
    assert d['exportDate'] == exportDate.isoformat()
    assert d['profileIds'] == ['daily']
    assert d['statisticsCount'] == 20
    assert d['recommendationsCount'] == 5
    assert d['alertsCount'] == 3


def testSummaryExportResultFailure():
    """Test SummaryExportResult with failed export."""
    result = SummaryExportResult(
        success=False,
        errorMessage="Export failed"
    )
    assert result.success is False
    assert result.errorMessage == "Export failed"
    assert result.totalRecordCount == 0


# ================================================================================
# Summary CSV Export Tests
# ================================================================================

def testSummaryExportToCsvNoData():
    """Test CSV summary export with no data in database."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToCsv()

        assert result.success is True
        assert result.statisticsCount == 0
        assert result.recommendationsCount == 0
        assert result.alertsCount == 0
        assert result.format == ExportFormat.CSV
        assert result.filePath is not None
        assert os.path.exists(result.filePath)
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToCsvWithStatistics():
    """Test CSV summary export with statistics data."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily', maxVal=6000, minVal=800, avgVal=2500)
        insertStatistics(db, 'SPEED', 'daily', maxVal=120, minVal=0, avgVal=60)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToCsv()

        assert result.success is True
        assert result.statisticsCount == 2
        assert os.path.exists(result.filePath)

        # Verify CSV content has statistics section
        with open(result.filePath, 'r', newline='', encoding='utf-8') as f:
            content = f.read()
            assert '# STATISTICS SUMMARY' in content
            assert 'RPM' in content
            assert 'SPEED' in content
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToCsvWithRecommendations():
    """Test CSV summary export with AI recommendations."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertRecommendation(db, 'Check air filter', 'daily', priorityRank=2)
        insertRecommendation(db, 'Monitor fuel trim', 'daily', priorityRank=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToCsv()

        assert result.success is True
        assert result.recommendationsCount == 2

        # Verify CSV content has recommendations section
        with open(result.filePath, 'r', newline='', encoding='utf-8') as f:
            content = f.read()
            assert '# AI RECOMMENDATIONS' in content
            assert 'Check air filter' in content
            assert 'Monitor fuel trim' in content
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToCsvWithAlerts():
    """Test CSV summary export with alert history."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertAlert(db, 'RPM_REDLINE', 'RPM', 7200, 7000, 'daily')
        insertAlert(db, 'COOLANT_HIGH', 'COOLANT_TEMP', 115, 110, 'daily')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToCsv()

        assert result.success is True
        assert result.alertsCount == 2

        # Verify CSV content has alerts section
        with open(result.filePath, 'r', newline='', encoding='utf-8') as f:
            content = f.read()
            assert '# ALERT HISTORY' in content
            assert 'RPM_REDLINE' in content
            assert 'COOLANT_HIGH' in content
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToCsvCombinedData():
    """Test CSV summary export with all data types."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily')
        insertRecommendation(db, 'Check air filter', 'daily')
        insertAlert(db, 'RPM_REDLINE', 'RPM', 7200, 7000, 'daily')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToCsv()

        assert result.success is True
        assert result.statisticsCount == 1
        assert result.recommendationsCount == 1
        assert result.alertsCount == 1
        assert result.totalRecordCount == 3
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToCsvFilename():
    """Test CSV summary export generates correct filename."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        exportDate = datetime(2026, 1, 22)
        result = exporter.exportSummaryToCsv(exportDate=exportDate)

        assert result.success is True
        expectedFilename = 'obd_summary_2026-01-22.csv'
        assert os.path.basename(result.filePath) == expectedFilename
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToCsvCustomFilename():
    """Test CSV summary export with custom filename."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToCsv(filename='my_summary.csv')

        assert result.success is True
        assert os.path.basename(result.filePath) == 'my_summary.csv'
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToCsvFilterByProfile():
    """Test CSV summary export filters by profile ID."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily')
        insertStatistics(db, 'RPM', 'performance')
        insertRecommendation(db, 'Rec 1', 'daily')
        insertRecommendation(db, 'Rec 2', 'performance')
        insertAlert(db, 'ALERT1', 'RPM', 7000, 7000, 'daily')
        insertAlert(db, 'ALERT2', 'RPM', 8000, 7500, 'performance')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToCsv(profileIds=['daily'])

        assert result.success is True
        assert result.statisticsCount == 1
        assert result.recommendationsCount == 1
        assert result.alertsCount == 1
        assert result.profileIds == ['daily']
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToCsvMultipleProfiles():
    """Test CSV summary export with multiple profiles."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily')
        insertStatistics(db, 'RPM', 'performance')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToCsv(profileIds=['daily', 'performance'])

        assert result.success is True
        assert result.statisticsCount == 2
        assert result.profileIds == ['daily', 'performance']
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToCsvExcludesDuplicateRecommendations():
    """Test CSV summary export excludes duplicate recommendations."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        originalId = insertRecommendation(db, 'Original rec', 'daily')
        insertRecommendation(db, 'Duplicate rec', 'daily', isDuplicateOf=originalId)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToCsv()

        assert result.success is True
        # Should only include non-duplicate recommendations
        assert result.recommendationsCount == 1
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


# ================================================================================
# Summary JSON Export Tests
# ================================================================================

def testSummaryExportToJsonNoData():
    """Test JSON summary export with no data in database."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToJson()

        assert result.success is True
        assert result.statisticsCount == 0
        assert result.recommendationsCount == 0
        assert result.alertsCount == 0
        assert result.format == ExportFormat.JSON
        assert os.path.exists(result.filePath)

        # Verify JSON structure
        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert 'metadata' in data
            assert 'statistics' in data
            assert 'recommendations' in data
            assert 'alerts' in data
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToJsonWithData():
    """Test JSON summary export with all data types."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily', maxVal=6000, minVal=800, avgVal=2500)
        insertRecommendation(db, 'Check air filter', 'daily', priorityRank=2)
        insertAlert(db, 'RPM_REDLINE', 'RPM', 7200, 7000, 'daily')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToJson()

        assert result.success is True
        assert result.statisticsCount == 1
        assert result.recommendationsCount == 1
        assert result.alertsCount == 1

        # Verify JSON content
        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert data['metadata']['counts']['statistics'] == 1
            assert data['metadata']['counts']['recommendations'] == 1
            assert data['metadata']['counts']['alerts'] == 1
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToJsonFilename():
    """Test JSON summary export generates correct filename."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        exportDate = datetime(2026, 1, 22)
        result = exporter.exportSummaryToJson(exportDate=exportDate)

        assert result.success is True
        expectedFilename = 'obd_summary_2026-01-22.json'
        assert os.path.basename(result.filePath) == expectedFilename
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToJsonMetadata():
    """Test JSON summary export metadata structure."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        exportDate = datetime(2026, 1, 22)
        result = exporter.exportSummaryToJson(
            exportDate=exportDate,
            profileIds=['daily']
        )

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            metadata = data['metadata']

            assert 'export_date' in metadata
            assert 'summary_date' in metadata
            assert metadata['summary_date'] == exportDate.isoformat()
            assert metadata['profiles'] == ['daily']
            assert 'counts' in metadata
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToJsonGroupsByProfile():
    """Test JSON summary export groups by profile when multiple profiles selected."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily')
        insertStatistics(db, 'RPM', 'performance')
        insertRecommendation(db, 'Rec daily', 'daily')
        insertRecommendation(db, 'Rec perf', 'performance')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToJson(profileIds=['daily', 'performance'])

        assert result.success is True

        # Verify data is grouped by profile
        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)

            # When multiple profiles, data should be grouped
            assert 'daily' in data['statistics']
            assert 'performance' in data['statistics']
            assert 'daily' in data['recommendations']
            assert 'performance' in data['recommendations']
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToJsonSingleProfileNoGrouping():
    """Test JSON summary export doesn't group when single profile or no filter."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily')
        insertStatistics(db, 'SPEED', 'daily')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        # Single profile - should be flat list
        result = exporter.exportSummaryToJson(profileIds=['daily'])

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)

            # With single profile, should be flat array not grouped dict
            assert isinstance(data['statistics'], list)
            assert len(data['statistics']) == 2
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToJsonFilterByProfile():
    """Test JSON summary export filters by profile ID."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily')
        insertStatistics(db, 'RPM', 'performance')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToJson(profileIds=['daily'])

        assert result.success is True
        assert result.statisticsCount == 1
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToJsonCustomFilename():
    """Test JSON summary export with custom filename."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToJson(filename='custom_summary.json')

        assert result.success is True
        assert os.path.basename(result.filePath) == 'custom_summary.json'
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToJsonRecommendationsSortedByPriority():
    """Test JSON summary export sorts recommendations by priority."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        # Insert in reverse priority order
        insertRecommendation(db, 'Low priority', 'daily', priorityRank=5)
        insertRecommendation(db, 'High priority', 'daily', priorityRank=1)
        insertRecommendation(db, 'Medium priority', 'daily', priorityRank=3)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToJson(profileIds=['daily'])

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            recs = data['recommendations']

            # Should be sorted by priority_rank ascending (1=highest)
            priorities = [r['priority_rank'] for r in recs]
            assert priorities == sorted(priorities)
            assert priorities[0] == 1
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportToJsonExcludesDuplicates():
    """Test JSON summary export excludes duplicate recommendations."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        originalId = insertRecommendation(db, 'Original', 'daily')
        insertRecommendation(db, 'Duplicate', 'daily', isDuplicateOf=originalId)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToJson()

        assert result.recommendationsCount == 1
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


# ================================================================================
# exportSummary Convenience Method Tests
# ================================================================================

def testExportSummaryMethodCsv():
    """Test exportSummary method with CSV format."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummary(format=ExportFormat.CSV)

        assert result.success is True
        assert result.format == ExportFormat.CSV
        assert result.filePath.endswith('.csv')
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportSummaryMethodJson():
    """Test exportSummary method with JSON format (default)."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily')

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummary()

        assert result.success is True
        assert result.format == ExportFormat.JSON
        assert result.filePath.endswith('.json')
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


# ================================================================================
# Summary Export Helper Function Tests
# ================================================================================

def testExportSummaryReportHelper():
    """Test exportSummaryReport helper function."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily')
        insertRecommendation(db, 'Check filters', 'daily')
        insertAlert(db, 'HIGH_RPM', 'RPM', 7000, 6500, 'daily')

        result = exportSummaryReport(
            db,
            exportDirectory=exportDir
        )

        assert result.success is True
        assert result.statisticsCount == 1
        assert result.recommendationsCount == 1
        assert result.alertsCount == 1
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportSummaryReportHelperWithCsv():
    """Test exportSummaryReport helper with CSV format."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily')

        result = exportSummaryReport(
            db,
            format=ExportFormat.CSV,
            exportDirectory=exportDir
        )

        assert result.success is True
        assert result.format == ExportFormat.CSV
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportSummaryReportHelperWithProfiles():
    """Test exportSummaryReport helper with profile filter."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        insertStatistics(db, 'RPM', 'daily')
        insertStatistics(db, 'RPM', 'performance')

        result = exportSummaryReport(
            db,
            profileIds=['daily'],
            exportDirectory=exportDir
        )

        assert result.success is True
        assert result.statisticsCount == 1
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testExportSummaryReportHelperCustomFilename():
    """Test exportSummaryReport helper with custom filename."""
    db, dbPath = createTestDatabase()
    exportDir = createTestExportDir()
    try:
        result = exportSummaryReport(
            db,
            filename='my_report.json',
            exportDirectory=exportDir
        )

        assert result.success is True
        assert os.path.basename(result.filePath) == 'my_report.json'
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(exportDir)


def testSummaryExportCreatesDirectory():
    """Test summary export creates directory if it doesn't exist."""
    db, dbPath = createTestDatabase()
    tmpDir = tempfile.mkdtemp()
    exportDir = os.path.join(tmpDir, 'subdir', 'summary_exports')
    try:
        assert not os.path.exists(exportDir)

        config = {'export': {'directory': exportDir}}
        exporter = DataExporter(db, config)

        result = exporter.exportSummaryToJson()

        assert result.success is True
        assert os.path.exists(exportDir)
    finally:
        cleanupDatabase(dbPath)
        cleanupExportDir(tmpDir)


# ================================================================================
# Main Test Runner
# ================================================================================

def main():
    """Run all tests."""
    print("=" * 60)
    print("Data Exporter Module Tests")
    print("=" * 60)

    result = TestResult()

    # ExportResult tests
    print("\nExportResult Tests:")
    runTest("testExportResultSuccess", testExportResultSuccess, result)
    runTest("testExportResultFailure", testExportResultFailure, result)
    runTest("testExportResultToDict", testExportResultToDict, result)
    runTest("testExportResultToDictNullValues", testExportResultToDictNullValues, result)
    runTest("testExportFormatEnum", testExportFormatEnum, result)
    runTest("testExportFormatEnumJson", testExportFormatEnumJson, result)

    # Initialization tests
    print("\nDataExporter Initialization Tests:")
    runTest("testExporterInitWithConfig", testExporterInitWithConfig, result)
    runTest("testExporterInitWithDefaultConfig", testExporterInitWithDefaultConfig, result)
    runTest("testExporterInitCreatesExportDirectory", testExporterInitCreatesExportDirectory, result)

    # exportToCsv tests
    print("\nexportToCsv Tests:")
    runTest("testExportToCsvNoData", testExportToCsvNoData, result)
    runTest("testExportToCsvWithData", testExportToCsvWithData, result)
    runTest("testExportToCsvFilename", testExportToCsvFilename, result)
    runTest("testExportToCsvDateRange", testExportToCsvDateRange, result)
    runTest("testExportToCsvWithProfileId", testExportToCsvWithProfileId, result)
    runTest("testExportToCsvWithParameters", testExportToCsvWithParameters, result)
    runTest("testExportToCsvCombinedFilters", testExportToCsvCombinedFilters, result)
    runTest("testExportToCsvHeader", testExportToCsvHeader, result)
    runTest("testExportToCsvDataFormat", testExportToCsvDataFormat, result)
    runTest("testExportToCsvEmptyWithHeaderOnly", testExportToCsvEmptyWithHeaderOnly, result)
    runTest("testExportToCsvCustomFilename", testExportToCsvCustomFilename, result)

    # Date validation tests
    print("\nDate Validation Tests:")
    runTest("testExportInvalidDateRange", testExportInvalidDateRange, result)
    runTest("testExportSameDayRange", testExportSameDayRange, result)

    # Directory tests
    print("\nDirectory Tests:")
    runTest("testExportCreatesDirectoryIfNotExists", testExportCreatesDirectoryIfNotExists, result)

    # CSV Helper function tests
    print("\nCSV Helper Function Tests:")
    runTest("testCreateExporterFromConfig", testCreateExporterFromConfig, result)
    runTest("testExportRealtimeDataToCsvHelper", testExportRealtimeDataToCsvHelper, result)
    runTest("testExportRealtimeDataToCsvHelperWithFilters", testExportRealtimeDataToCsvHelperWithFilters, result)

    # Edge cases
    print("\nEdge Cases Tests:")
    runTest("testExportLargeDataset", testExportLargeDataset, result)
    runTest("testExportMultipleParameters", testExportMultipleParameters, result)
    runTest("testExportNonExistentProfile", testExportNonExistentProfile, result)
    runTest("testExportNonExistentParameter", testExportNonExistentParameter, result)
    runTest("testExportSpecialCharactersInData", testExportSpecialCharactersInData, result)
    runTest("testExportGeneratesResultMetadata", testExportGeneratesResultMetadata, result)
    runTest("testExportOrderedByTimestamp", testExportOrderedByTimestamp, result)

    # JSON export tests
    print("\nexportToJson Tests:")
    runTest("testExportToJsonNoData", testExportToJsonNoData, result)
    runTest("testExportToJsonWithData", testExportToJsonWithData, result)
    runTest("testExportToJsonFilename", testExportToJsonFilename, result)
    runTest("testExportToJsonMetadata", testExportToJsonMetadata, result)
    runTest("testExportToJsonDataStructure", testExportToJsonDataStructure, result)
    runTest("testExportToJsonDateRange", testExportToJsonDateRange, result)
    runTest("testExportToJsonWithProfileId", testExportToJsonWithProfileId, result)
    runTest("testExportToJsonWithParameters", testExportToJsonWithParameters, result)
    runTest("testExportToJsonCombinedFilters", testExportToJsonCombinedFilters, result)
    runTest("testExportToJsonCustomFilename", testExportToJsonCustomFilename, result)
    runTest("testExportToJsonInvalidDateRange", testExportToJsonInvalidDateRange, result)
    runTest("testExportToJsonCreatesDirectory", testExportToJsonCreatesDirectory, result)
    runTest("testExportToJsonNullProfile", testExportToJsonNullProfile, result)
    runTest("testExportToJsonOrderedByTimestamp", testExportToJsonOrderedByTimestamp, result)
    runTest("testExportToJsonLargeDataset", testExportToJsonLargeDataset, result)

    # JSON Helper function tests
    print("\nJSON Helper Function Tests:")
    runTest("testExportRealtimeDataToJsonHelper", testExportRealtimeDataToJsonHelper, result)
    runTest("testExportRealtimeDataToJsonHelperWithFilters", testExportRealtimeDataToJsonHelperWithFilters, result)
    runTest("testExportRealtimeDataToJsonHelperCustomFilename", testExportRealtimeDataToJsonHelperCustomFilename, result)

    # SummaryExportResult tests
    print("\nSummaryExportResult Tests:")
    runTest("testSummaryExportResultSuccess", testSummaryExportResultSuccess, result)
    runTest("testSummaryExportResultToDict", testSummaryExportResultToDict, result)
    runTest("testSummaryExportResultFailure", testSummaryExportResultFailure, result)

    # Summary CSV export tests
    print("\nSummary CSV Export Tests:")
    runTest("testSummaryExportToCsvNoData", testSummaryExportToCsvNoData, result)
    runTest("testSummaryExportToCsvWithStatistics", testSummaryExportToCsvWithStatistics, result)
    runTest("testSummaryExportToCsvWithRecommendations", testSummaryExportToCsvWithRecommendations, result)
    runTest("testSummaryExportToCsvWithAlerts", testSummaryExportToCsvWithAlerts, result)
    runTest("testSummaryExportToCsvCombinedData", testSummaryExportToCsvCombinedData, result)
    runTest("testSummaryExportToCsvFilename", testSummaryExportToCsvFilename, result)
    runTest("testSummaryExportToCsvCustomFilename", testSummaryExportToCsvCustomFilename, result)
    runTest("testSummaryExportToCsvFilterByProfile", testSummaryExportToCsvFilterByProfile, result)
    runTest("testSummaryExportToCsvMultipleProfiles", testSummaryExportToCsvMultipleProfiles, result)
    runTest("testSummaryExportToCsvExcludesDuplicateRecommendations", testSummaryExportToCsvExcludesDuplicateRecommendations, result)

    # Summary JSON export tests
    print("\nSummary JSON Export Tests:")
    runTest("testSummaryExportToJsonNoData", testSummaryExportToJsonNoData, result)
    runTest("testSummaryExportToJsonWithData", testSummaryExportToJsonWithData, result)
    runTest("testSummaryExportToJsonFilename", testSummaryExportToJsonFilename, result)
    runTest("testSummaryExportToJsonMetadata", testSummaryExportToJsonMetadata, result)
    runTest("testSummaryExportToJsonGroupsByProfile", testSummaryExportToJsonGroupsByProfile, result)
    runTest("testSummaryExportToJsonSingleProfileNoGrouping", testSummaryExportToJsonSingleProfileNoGrouping, result)
    runTest("testSummaryExportToJsonFilterByProfile", testSummaryExportToJsonFilterByProfile, result)
    runTest("testSummaryExportToJsonCustomFilename", testSummaryExportToJsonCustomFilename, result)
    runTest("testSummaryExportToJsonRecommendationsSortedByPriority", testSummaryExportToJsonRecommendationsSortedByPriority, result)
    runTest("testSummaryExportToJsonExcludesDuplicates", testSummaryExportToJsonExcludesDuplicates, result)

    # exportSummary convenience method tests
    print("\nexportSummary Method Tests:")
    runTest("testExportSummaryMethodCsv", testExportSummaryMethodCsv, result)
    runTest("testExportSummaryMethodJson", testExportSummaryMethodJson, result)

    # Summary export helper function tests
    print("\nSummary Export Helper Function Tests:")
    runTest("testExportSummaryReportHelper", testExportSummaryReportHelper, result)
    runTest("testExportSummaryReportHelperWithCsv", testExportSummaryReportHelperWithCsv, result)
    runTest("testExportSummaryReportHelperWithProfiles", testExportSummaryReportHelperWithProfiles, result)
    runTest("testExportSummaryReportHelperCustomFilename", testExportSummaryReportHelperCustomFilename, result)
    runTest("testSummaryExportCreatesDirectory", testSummaryExportCreatesDirectory, result)

    # Summary
    print("\n" + "=" * 60)
    print(f"SUMMARY: {result.passed} passed, {result.failed} failed")
    print("=" * 60)

    if result.errors:
        print("\nFailures:")
        for error in result.errors:
            print(f"  - {error}")

    return 0 if result.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
