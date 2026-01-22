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
    ExportFormat,
    DataExportError,
    InvalidDateRangeError,
    ExportDirectoryError,
    createExporterFromConfig,
    exportRealtimeDataToCsv,
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

    # Helper function tests
    print("\nHelper Function Tests:")
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
