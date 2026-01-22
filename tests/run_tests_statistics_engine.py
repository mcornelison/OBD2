#!/usr/bin/env python3
################################################################################
# File Name: run_tests_statistics_engine.py
# Purpose/Description: Manual test runner for statistics engine tests
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""
Manual test runner for statistics engine module tests.

Runs tests without requiring pytest installed.
Useful for environments where pytest is not available.

Usage:
    python tests/run_tests_statistics_engine.py
"""

import sys
import os
import time
import math
import traceback
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Add src to path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from obd.database import ObdDatabase
from obd.statistics_engine import (
    StatisticsEngine,
    ParameterStatistics,
    AnalysisResult,
    AnalysisState,
    EngineStats,
    StatisticsError,
    StatisticsCalculationError,
    StatisticsStorageError,
    InsufficientDataError,
    calculateMean,
    calculateMode,
    calculateStandardDeviation,
    calculateOutlierBounds,
    calculateParameterStatistics,
    createStatisticsEngineFromConfig,
    calculateStatisticsForDrive,
    getStatisticsSummary,
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


def insertTestData(db: ObdDatabase, parameterName: str, values: List[float],
                   profileId: str = 'daily') -> None:
    """Insert test data into realtime_data table."""
    # First ensure the profile exists to satisfy foreign key constraint
    ensureProfileExists(db, profileId)

    with db.connect() as conn:
        cursor = conn.cursor()
        for value in values:
            cursor.execute(
                """
                INSERT INTO realtime_data
                (timestamp, parameter_name, value, unit, profile_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (datetime.now(), parameterName, value, 'unit', profileId)
            )


# ================================================================================
# Calculate Mean Tests
# ================================================================================

def testCalculateMeanSimple():
    """Test calculateMean with simple values."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = calculateMean(values)
    assert result == 3.0


def testCalculateMeanSingleValue():
    """Test calculateMean with single value."""
    values = [42.0]
    result = calculateMean(values)
    assert result == 42.0


def testCalculateMeanEmpty():
    """Test calculateMean raises error for empty list."""
    try:
        calculateMean([])
        assert False, "Should have raised InsufficientDataError"
    except InsufficientDataError:
        pass


def testCalculateMeanFloat():
    """Test calculateMean with float values."""
    values = [1.5, 2.5, 3.5]
    result = calculateMean(values)
    assert result == 2.5


def testCalculateMeanNegative():
    """Test calculateMean with negative values."""
    values = [-10.0, 0.0, 10.0]
    result = calculateMean(values)
    assert result == 0.0


# ================================================================================
# Calculate Mode Tests
# ================================================================================

def testCalculateModeSimple():
    """Test calculateMode with clear mode."""
    values = [1.0, 2.0, 2.0, 3.0, 2.0]
    result = calculateMode(values)
    assert result == 2.0


def testCalculateModeSingleValue():
    """Test calculateMode with single value."""
    values = [5.0]
    result = calculateMode(values)
    assert result == 5.0


def testCalculateModeEmpty():
    """Test calculateMode with empty list."""
    result = calculateMode([])
    assert result is None


def testCalculateModePrecision():
    """Test calculateMode rounds values for comparison."""
    values = [1.001, 1.002, 1.003, 2.001]  # All ~1.00 after rounding
    result = calculateMode(values, precision=1)
    assert result == 1.0


def testCalculateModeWithFloats():
    """Test calculateMode with varying floats."""
    values = [3.14, 3.14, 2.71, 3.14]
    result = calculateMode(values)
    assert result == 3.14


# ================================================================================
# Calculate Standard Deviation Tests
# ================================================================================

def testCalculateStdSimple():
    """Test calculateStandardDeviation with simple values."""
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    result = calculateStandardDeviation(values)
    # Sample std dev of [2,4,4,4,5,5,7,9], mean = 5, sample std ≈ 2.138
    assert abs(result - 2.138) < 0.01


def testCalculateStdWithMean():
    """Test calculateStandardDeviation with pre-calculated mean."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    mean = 3.0
    result = calculateStandardDeviation(values, mean)
    # Sample std of [1,2,3,4,5] with mean 3 = sqrt(2.5) ≈ 1.58
    assert abs(result - 1.5811) < 0.001


def testCalculateStdSingleValue():
    """Test calculateStandardDeviation with single value raises error."""
    try:
        calculateStandardDeviation([5.0])
        assert False, "Should have raised InsufficientDataError"
    except InsufficientDataError:
        pass


def testCalculateStdTwoValues():
    """Test calculateStandardDeviation with two values."""
    values = [0.0, 10.0]
    result = calculateStandardDeviation(values)
    # Sample std with n-1: sqrt((25+25)/1) ≈ 7.07
    assert abs(result - 7.0711) < 0.001


def testCalculateStdEmpty():
    """Test calculateStandardDeviation with empty list raises error."""
    try:
        calculateStandardDeviation([])
        assert False, "Should have raised InsufficientDataError"
    except InsufficientDataError:
        pass


# ================================================================================
# Calculate Outlier Bounds Tests
# ================================================================================

def testCalculateOutlierBoundsDefault():
    """Test calculateOutlierBounds with default multiplier."""
    mean = 100.0
    stdDev = 10.0
    minBound, maxBound = calculateOutlierBounds(mean, stdDev)
    assert minBound == 80.0
    assert maxBound == 120.0


def testCalculateOutlierBoundsCustomMultiplier():
    """Test calculateOutlierBounds with custom multiplier."""
    mean = 50.0
    stdDev = 5.0
    minBound, maxBound = calculateOutlierBounds(mean, stdDev, multiplier=3.0)
    assert minBound == 35.0
    assert maxBound == 65.0


def testCalculateOutlierBoundsZeroStd():
    """Test calculateOutlierBounds with zero std deviation."""
    mean = 100.0
    stdDev = 0.0
    minBound, maxBound = calculateOutlierBounds(mean, stdDev)
    assert minBound == 100.0
    assert maxBound == 100.0


def testCalculateOutlierBoundsNegativeMean():
    """Test calculateOutlierBounds with negative mean."""
    mean = -50.0
    stdDev = 10.0
    minBound, maxBound = calculateOutlierBounds(mean, stdDev)
    assert minBound == -70.0
    assert maxBound == -30.0


# ================================================================================
# Parameter Statistics Dataclass Tests
# ================================================================================

def testParameterStatisticsDefaults():
    """Test ParameterStatistics with required fields only."""
    stats = ParameterStatistics(
        parameterName='RPM',
        analysisDate=datetime.now(),
        profileId='daily'
    )
    assert stats.parameterName == 'RPM'
    assert stats.profileId == 'daily'
    assert stats.maxValue is None
    assert stats.minValue is None
    assert stats.sampleCount == 0


def testParameterStatisticsAllFields():
    """Test ParameterStatistics with all fields."""
    now = datetime.now()
    stats = ParameterStatistics(
        parameterName='SPEED',
        analysisDate=now,
        profileId='performance',
        maxValue=120.0,
        minValue=0.0,
        avgValue=60.0,
        modeValue=50.0,
        std1=20.0,
        std2=40.0,
        outlierMin=20.0,
        outlierMax=100.0,
        sampleCount=1000
    )
    assert stats.maxValue == 120.0
    assert stats.minValue == 0.0
    assert stats.avgValue == 60.0
    assert stats.modeValue == 50.0
    assert stats.std1 == 20.0
    assert stats.std2 == 40.0
    assert stats.outlierMin == 20.0
    assert stats.outlierMax == 100.0
    assert stats.sampleCount == 1000


def testParameterStatisticsToDict():
    """Test ParameterStatistics.toDict() serialization."""
    now = datetime.now()
    stats = ParameterStatistics(
        parameterName='RPM',
        analysisDate=now,
        profileId='daily',
        maxValue=7000.0,
        minValue=800.0,
        avgValue=3500.0,
        sampleCount=500
    )
    result = stats.toDict()

    assert result['parameterName'] == 'RPM'
    assert result['profileId'] == 'daily'
    assert result['maxValue'] == 7000.0
    assert result['minValue'] == 800.0
    assert result['avgValue'] == 3500.0
    assert result['sampleCount'] == 500
    assert 'analysisDate' in result


# ================================================================================
# Analysis Result Dataclass Tests
# ================================================================================

def testAnalysisResultDefaults():
    """Test AnalysisResult with required fields only."""
    result = AnalysisResult(
        analysisDate=datetime.now(),
        profileId='daily'
    )
    assert result.profileId == 'daily'
    assert result.parameterStats == {}
    assert result.totalParameters == 0
    assert result.success is True


def testAnalysisResultWithStats():
    """Test AnalysisResult with parameter stats."""
    now = datetime.now()
    stats = ParameterStatistics(
        parameterName='RPM',
        analysisDate=now,
        profileId='daily',
        maxValue=7000.0,
        sampleCount=100
    )
    result = AnalysisResult(
        analysisDate=now,
        profileId='daily',
        parameterStats={'RPM': stats},
        totalParameters=1,
        totalSamples=100
    )
    assert 'RPM' in result.parameterStats
    assert result.totalParameters == 1
    assert result.totalSamples == 100


def testAnalysisResultToDict():
    """Test AnalysisResult.toDict() serialization."""
    now = datetime.now()
    result = AnalysisResult(
        analysisDate=now,
        profileId='daily',
        totalParameters=5,
        success=True,
        durationMs=123.45
    )
    dictResult = result.toDict()

    assert dictResult['profileId'] == 'daily'
    assert dictResult['totalParameters'] == 5
    assert dictResult['success'] is True
    assert dictResult['durationMs'] == 123.45


# ================================================================================
# Engine Stats Dataclass Tests
# ================================================================================

def testEngineStatsDefaults():
    """Test EngineStats defaults."""
    stats = EngineStats()
    assert stats.totalAnalysesRun == 0
    assert stats.lastAnalysisDate is None
    assert stats.totalParametersAnalyzed == 0


def testEngineStatsToDict():
    """Test EngineStats.toDict() serialization."""
    now = datetime.now()
    stats = EngineStats(
        totalAnalysesRun=5,
        lastAnalysisDate=now,
        lastAnalysisDurationMs=250.5,
        totalParametersAnalyzed=25,
        totalSamplesProcessed=5000
    )
    result = stats.toDict()

    assert result['totalAnalysesRun'] == 5
    assert result['lastAnalysisDurationMs'] == 250.5
    assert result['totalParametersAnalyzed'] == 25
    assert result['totalSamplesProcessed'] == 5000


# ================================================================================
# Exception Tests
# ================================================================================

def testStatisticsErrorMessage():
    """Test StatisticsError stores message."""
    error = StatisticsError("Test error")
    assert str(error) == "Test error"
    assert error.message == "Test error"


def testStatisticsErrorDetails():
    """Test StatisticsError stores details."""
    error = StatisticsError("Test", details={'key': 'value'})
    assert error.details == {'key': 'value'}


def testStatisticsCalculationErrorInheritance():
    """Test StatisticsCalculationError inheritance."""
    error = StatisticsCalculationError("Calculation failed")
    assert isinstance(error, StatisticsError)


def testStatisticsStorageErrorInheritance():
    """Test StatisticsStorageError inheritance."""
    error = StatisticsStorageError("Storage failed")
    assert isinstance(error, StatisticsError)


def testInsufficientDataErrorInheritance():
    """Test InsufficientDataError inheritance."""
    error = InsufficientDataError("Not enough data")
    assert isinstance(error, StatisticsError)


# ================================================================================
# Calculate Parameter Statistics Function Tests
# ================================================================================

def testCalculateParameterStatisticsBasic():
    """Test calculateParameterStatistics with basic data."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    stats = calculateParameterStatistics(
        values=values,
        parameterName='TEST',
        profileId='daily'
    )

    assert stats.parameterName == 'TEST'
    assert stats.profileId == 'daily'
    assert stats.maxValue == 5.0
    assert stats.minValue == 1.0
    assert stats.avgValue == 3.0
    assert stats.sampleCount == 5
    # std1 should be calculated
    assert stats.std1 is not None
    assert stats.std2 is not None
    assert stats.outlierMin is not None
    assert stats.outlierMax is not None


def testCalculateParameterStatisticsEmpty():
    """Test calculateParameterStatistics raises for empty values."""
    try:
        calculateParameterStatistics(
            values=[],
            parameterName='TEST',
            profileId='daily'
        )
        assert False, "Should have raised InsufficientDataError"
    except InsufficientDataError:
        pass


def testCalculateParameterStatisticsSingleValue():
    """Test calculateParameterStatistics with single value."""
    values = [100.0]
    stats = calculateParameterStatistics(
        values=values,
        parameterName='TEST',
        profileId='daily',
        minSamples=2
    )

    assert stats.maxValue == 100.0
    assert stats.minValue == 100.0
    assert stats.avgValue == 100.0
    assert stats.sampleCount == 1
    # With minSamples=2, std should be None for single value
    assert stats.std1 is None
    assert stats.std2 is None


def testCalculateParameterStatisticsWithDate():
    """Test calculateParameterStatistics with custom date."""
    customDate = datetime(2026, 1, 22, 12, 0, 0)
    values = [10.0, 20.0, 30.0]
    stats = calculateParameterStatistics(
        values=values,
        parameterName='TEST',
        profileId='daily',
        analysisDate=customDate
    )

    assert stats.analysisDate == customDate


# ================================================================================
# Statistics Engine Init Tests
# ================================================================================

def testStatisticsEngineInit():
    """Test StatisticsEngine initialization."""
    db, dbPath = createTestDatabase()
    try:
        config = {
            'analysis': {
                'calculateStatistics': ['max', 'min', 'avg']
            },
            'profiles': {
                'activeProfile': 'daily'
            }
        }
        engine = StatisticsEngine(db, config)

        assert engine.database == db
        assert engine.config == config
        assert engine.state == AnalysisState.IDLE
    finally:
        cleanupDatabase(dbPath)


def testStatisticsEngineInitMinSamples():
    """Test StatisticsEngine initialization with custom minSamples."""
    db, dbPath = createTestDatabase()
    try:
        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config, minSamples=5)

        assert engine.minSamples == 5
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Statistics Engine State Tests
# ================================================================================

def testStatisticsEngineStateIdle():
    """Test StatisticsEngine starts in IDLE state."""
    db, dbPath = createTestDatabase()
    try:
        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        assert engine.state == AnalysisState.IDLE
        assert not engine.isRunning
        assert not engine.isScheduled
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Statistics Engine Calculate Tests
# ================================================================================

def testStatisticsEngineCalculateNoData():
    """Test calculateStatistics with no data returns empty result."""
    db, dbPath = createTestDatabase()
    try:
        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        result = engine.calculateStatistics(profileId='daily')

        assert result.success is True
        assert result.totalParameters == 0
        assert result.errorMessage == "No data available for analysis"
    finally:
        cleanupDatabase(dbPath)


def testStatisticsEngineCalculateWithData():
    """Test calculateStatistics with data returns statistics."""
    db, dbPath = createTestDatabase()
    try:
        # Insert test data
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0, 4000.0, 5000.0], 'daily')
        insertTestData(db, 'SPEED', [20.0, 40.0, 60.0, 80.0, 100.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        result = engine.calculateStatistics(profileId='daily')

        assert result.success is True
        assert result.totalParameters == 2
        assert result.totalSamples == 10  # 5 + 5
        assert 'RPM' in result.parameterStats
        assert 'SPEED' in result.parameterStats

        rpmStats = result.parameterStats['RPM']
        assert rpmStats.maxValue == 5000.0
        assert rpmStats.minValue == 1000.0
        assert rpmStats.avgValue == 3000.0
        assert rpmStats.sampleCount == 5
    finally:
        cleanupDatabase(dbPath)


def testStatisticsEngineCalculateStoresResults():
    """Test calculateStatistics stores results in database."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        result = engine.calculateStatistics(profileId='daily', storeResults=True)

        # Verify data was stored
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM statistics WHERE profile_id = ?",
                ('daily',)
            )
            count = cursor.fetchone()[0]
            assert count >= 1

    finally:
        cleanupDatabase(dbPath)


def testStatisticsEngineCalculateNoStore():
    """Test calculateStatistics with storeResults=False."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        result = engine.calculateStatistics(profileId='daily', storeResults=False)

        assert result.success is True
        assert result.totalParameters == 1

        # Verify data was NOT stored
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM statistics")
            count = cursor.fetchone()[0]
            assert count == 0

    finally:
        cleanupDatabase(dbPath)


def testStatisticsEngineCalculateMultipleProfiles():
    """Test calculateStatistics respects profile filter."""
    db, dbPath = createTestDatabase()
    try:
        # Insert data for different profiles
        insertTestData(db, 'RPM', [1000.0, 2000.0], 'daily')
        insertTestData(db, 'RPM', [5000.0, 6000.0], 'performance')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        # Calculate for 'daily' profile only
        result = engine.calculateStatistics(profileId='daily')

        assert 'RPM' in result.parameterStats
        rpmStats = result.parameterStats['RPM']
        assert rpmStats.maxValue == 2000.0  # daily max, not performance max
        assert rpmStats.minValue == 1000.0
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Statistics Engine Retrieve Tests
# ================================================================================

def testStatisticsEngineGetParameterStats():
    """Test getParameterStatistics retrieves stored stats."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        # Calculate and store
        engine.calculateStatistics(profileId='daily', storeResults=True)

        # Retrieve
        stats = engine.getParameterStatistics('RPM', profileId='daily')

        assert len(stats) >= 1
        assert stats[0].parameterName == 'RPM'
        assert stats[0].profileId == 'daily'
    finally:
        cleanupDatabase(dbPath)


def testStatisticsEngineGetParameterStatsLimit():
    """Test getParameterStatistics respects limit parameter."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        # Calculate multiple times
        engine.calculateStatistics(profileId='daily', storeResults=True)
        time.sleep(0.01)  # Small delay to ensure different timestamps
        engine.calculateStatistics(profileId='daily', storeResults=True)

        # Get with limit=1
        stats = engine.getParameterStatistics('RPM', profileId='daily', limit=1)

        assert len(stats) == 1
    finally:
        cleanupDatabase(dbPath)


def testStatisticsEngineGetLatestResult():
    """Test getLatestAnalysisResult retrieves latest analysis."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')
        insertTestData(db, 'SPEED', [50.0, 60.0, 70.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        engine.calculateStatistics(profileId='daily', storeResults=True)

        result = engine.getLatestAnalysisResult(profileId='daily')

        assert result is not None
        assert result.profileId == 'daily'
        assert 'RPM' in result.parameterStats
        assert 'SPEED' in result.parameterStats
    finally:
        cleanupDatabase(dbPath)


def testStatisticsEngineGetLatestResultNoData():
    """Test getLatestAnalysisResult returns None when no data."""
    db, dbPath = createTestDatabase()
    try:
        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        result = engine.getLatestAnalysisResult(profileId='daily')

        assert result is None
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Statistics Engine Scheduling Tests
# ================================================================================

def testStatisticsEngineScheduleImmediate():
    """Test scheduleAnalysis with delay=0 runs immediately."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        result = engine.scheduleAnalysis(profileId='daily', delaySeconds=0)

        assert result is True
        # Wait briefly for thread to complete
        time.sleep(0.5)

        # Check state transitioned
        assert engine.state in (AnalysisState.COMPLETED, AnalysisState.RUNNING)
    finally:
        cleanupDatabase(dbPath)


def testStatisticsEngineCancelScheduled():
    """Test cancelScheduledAnalysis cancels pending analysis."""
    db, dbPath = createTestDatabase()
    try:
        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        # Schedule with delay
        engine.scheduleAnalysis(profileId='daily', delaySeconds=10)
        assert engine.state == AnalysisState.SCHEDULED

        # Cancel
        result = engine.cancelScheduledAnalysis()
        assert result is True
        assert engine.state == AnalysisState.IDLE
    finally:
        cleanupDatabase(dbPath)


def testStatisticsEngineCancelNoScheduled():
    """Test cancelScheduledAnalysis returns False when nothing scheduled."""
    db, dbPath = createTestDatabase()
    try:
        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        result = engine.cancelScheduledAnalysis()
        assert result is False
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Statistics Engine Callbacks Tests
# ================================================================================

def testStatisticsEngineCallbacks():
    """Test analysis callbacks are invoked."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        startCalled = [False]
        completeCalled = [False]

        def onStart(profileId):
            startCalled[0] = True

        def onComplete(result):
            completeCalled[0] = True

        engine.registerCallbacks(
            onAnalysisStart=onStart,
            onAnalysisComplete=onComplete
        )

        engine.calculateStatistics(profileId='daily')

        assert startCalled[0] is True
        assert completeCalled[0] is True
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Statistics Engine Stats Tests
# ================================================================================

def testStatisticsEngineGetEngineStats():
    """Test getEngineStats returns engine statistics."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        # Run analysis
        engine.calculateStatistics(profileId='daily')

        stats = engine.getEngineStats()

        assert stats.totalAnalysesRun == 1
        assert stats.lastAnalysisDate is not None
        assert stats.totalParametersAnalyzed >= 1
        assert stats.totalSamplesProcessed >= 3
    finally:
        cleanupDatabase(dbPath)


def testStatisticsEngineGetAnalysisCount():
    """Test getAnalysisCount returns correct count."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        # Initially 0
        assert engine.getAnalysisCount(profileId='daily') == 0

        # Run analysis
        engine.calculateStatistics(profileId='daily', storeResults=True)

        # Now 1
        assert engine.getAnalysisCount(profileId='daily') == 1
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Helper Functions Tests
# ================================================================================

def testCreateStatisticsEngineFromConfig():
    """Test createStatisticsEngineFromConfig helper function."""
    db, dbPath = createTestDatabase()
    try:
        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = createStatisticsEngineFromConfig(db, config)

        assert isinstance(engine, StatisticsEngine)
        assert engine.database == db
    finally:
        cleanupDatabase(dbPath)


def testCalculateStatisticsForDrive():
    """Test calculateStatisticsForDrive helper function."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}

        result = calculateStatisticsForDrive(
            database=db,
            config=config,
            profileId='daily'
        )

        assert result.success is True
        assert 'RPM' in result.parameterStats
    finally:
        cleanupDatabase(dbPath)


def testGetStatisticsSummary():
    """Test getStatisticsSummary helper function."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')
        insertTestData(db, 'SPEED', [50.0, 60.0, 70.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)
        engine.calculateStatistics(profileId='daily', storeResults=True)

        summary = getStatisticsSummary(db, profileId='daily')

        assert 'RPM' in summary
        assert 'SPEED' in summary
        assert 'max' in summary['RPM']
        assert 'min' in summary['RPM']
        assert 'avg' in summary['RPM']
    finally:
        cleanupDatabase(dbPath)


def testGetStatisticsSummaryFiltered():
    """Test getStatisticsSummary with parameter filter."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')
        insertTestData(db, 'SPEED', [50.0, 60.0, 70.0], 'daily')
        insertTestData(db, 'COOLANT_TEMP', [80.0, 85.0, 90.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)
        engine.calculateStatistics(profileId='daily', storeResults=True)

        summary = getStatisticsSummary(
            db,
            profileId='daily',
            parameterNames=['RPM', 'SPEED']
        )

        assert 'RPM' in summary
        assert 'SPEED' in summary
        assert 'COOLANT_TEMP' not in summary
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Analysis State Enum Tests
# ================================================================================

def testAnalysisStateValues():
    """Test AnalysisState enum values."""
    assert AnalysisState.IDLE.value == 'idle'
    assert AnalysisState.SCHEDULED.value == 'scheduled'
    assert AnalysisState.RUNNING.value == 'running'
    assert AnalysisState.COMPLETED.value == 'completed'
    assert AnalysisState.ERROR.value == 'error'


# ================================================================================
# Edge Case Tests
# ================================================================================

def testStatisticsWithIdenticalValues():
    """Test statistics with all identical values."""
    values = [100.0, 100.0, 100.0, 100.0, 100.0]
    stats = calculateParameterStatistics(
        values=values,
        parameterName='TEST',
        profileId='daily'
    )

    assert stats.maxValue == 100.0
    assert stats.minValue == 100.0
    assert stats.avgValue == 100.0
    assert stats.modeValue == 100.0
    # Standard deviation should be 0
    assert stats.std1 == 0.0
    assert stats.std2 == 0.0
    assert stats.outlierMin == 100.0
    assert stats.outlierMax == 100.0


def testStatisticsWithLargeDataset():
    """Test statistics with large dataset."""
    # Generate 1000 values
    values = [float(i) for i in range(1, 1001)]
    stats = calculateParameterStatistics(
        values=values,
        parameterName='TEST',
        profileId='daily'
    )

    assert stats.maxValue == 1000.0
    assert stats.minValue == 1.0
    assert stats.avgValue == 500.5
    assert stats.sampleCount == 1000


def testStatisticsWithNegativeValues():
    """Test statistics with negative values."""
    values = [-100.0, -50.0, 0.0, 50.0, 100.0]
    stats = calculateParameterStatistics(
        values=values,
        parameterName='TEST',
        profileId='daily'
    )

    assert stats.maxValue == 100.0
    assert stats.minValue == -100.0
    assert stats.avgValue == 0.0


def testStatisticsWithVerySmallValues():
    """Test statistics with very small decimal values."""
    values = [0.001, 0.002, 0.003, 0.004, 0.005]
    stats = calculateParameterStatistics(
        values=values,
        parameterName='TEST',
        profileId='daily'
    )

    assert abs(stats.avgValue - 0.003) < 0.0001
    assert stats.maxValue == 0.005
    assert stats.minValue == 0.001


def testStatisticsEngineDefaultProfile():
    """Test engine uses default profile when not specified."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000.0, 2000.0, 3000.0], 'daily')

        config = {'analysis': {}, 'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)

        # Don't specify profileId - should use 'daily' from config
        result = engine.calculateStatistics()

        assert result.profileId == 'daily'
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Main Test Runner
# ================================================================================

def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Statistics Engine Tests")
    print("=" * 60)

    result = TestResult()

    # Calculate Mean Tests
    print("\nCalculate Mean Tests:")
    runTest("testCalculateMeanSimple", testCalculateMeanSimple, result)
    runTest("testCalculateMeanSingleValue", testCalculateMeanSingleValue, result)
    runTest("testCalculateMeanEmpty", testCalculateMeanEmpty, result)
    runTest("testCalculateMeanFloat", testCalculateMeanFloat, result)
    runTest("testCalculateMeanNegative", testCalculateMeanNegative, result)

    # Calculate Mode Tests
    print("\nCalculate Mode Tests:")
    runTest("testCalculateModeSimple", testCalculateModeSimple, result)
    runTest("testCalculateModeSingleValue", testCalculateModeSingleValue, result)
    runTest("testCalculateModeEmpty", testCalculateModeEmpty, result)
    runTest("testCalculateModePrecision", testCalculateModePrecision, result)
    runTest("testCalculateModeWithFloats", testCalculateModeWithFloats, result)

    # Calculate Standard Deviation Tests
    print("\nCalculate Standard Deviation Tests:")
    runTest("testCalculateStdSimple", testCalculateStdSimple, result)
    runTest("testCalculateStdWithMean", testCalculateStdWithMean, result)
    runTest("testCalculateStdSingleValue", testCalculateStdSingleValue, result)
    runTest("testCalculateStdTwoValues", testCalculateStdTwoValues, result)
    runTest("testCalculateStdEmpty", testCalculateStdEmpty, result)

    # Calculate Outlier Bounds Tests
    print("\nCalculate Outlier Bounds Tests:")
    runTest("testCalculateOutlierBoundsDefault", testCalculateOutlierBoundsDefault, result)
    runTest("testCalculateOutlierBoundsCustomMultiplier", testCalculateOutlierBoundsCustomMultiplier, result)
    runTest("testCalculateOutlierBoundsZeroStd", testCalculateOutlierBoundsZeroStd, result)
    runTest("testCalculateOutlierBoundsNegativeMean", testCalculateOutlierBoundsNegativeMean, result)

    # Parameter Statistics Dataclass Tests
    print("\nParameter Statistics Dataclass Tests:")
    runTest("testParameterStatisticsDefaults", testParameterStatisticsDefaults, result)
    runTest("testParameterStatisticsAllFields", testParameterStatisticsAllFields, result)
    runTest("testParameterStatisticsToDict", testParameterStatisticsToDict, result)

    # Analysis Result Dataclass Tests
    print("\nAnalysis Result Dataclass Tests:")
    runTest("testAnalysisResultDefaults", testAnalysisResultDefaults, result)
    runTest("testAnalysisResultWithStats", testAnalysisResultWithStats, result)
    runTest("testAnalysisResultToDict", testAnalysisResultToDict, result)

    # Engine Stats Dataclass Tests
    print("\nEngine Stats Dataclass Tests:")
    runTest("testEngineStatsDefaults", testEngineStatsDefaults, result)
    runTest("testEngineStatsToDict", testEngineStatsToDict, result)

    # Exception Tests
    print("\nException Tests:")
    runTest("testStatisticsErrorMessage", testStatisticsErrorMessage, result)
    runTest("testStatisticsErrorDetails", testStatisticsErrorDetails, result)
    runTest("testStatisticsCalculationErrorInheritance", testStatisticsCalculationErrorInheritance, result)
    runTest("testStatisticsStorageErrorInheritance", testStatisticsStorageErrorInheritance, result)
    runTest("testInsufficientDataErrorInheritance", testInsufficientDataErrorInheritance, result)

    # Calculate Parameter Statistics Function Tests
    print("\nCalculate Parameter Statistics Function Tests:")
    runTest("testCalculateParameterStatisticsBasic", testCalculateParameterStatisticsBasic, result)
    runTest("testCalculateParameterStatisticsEmpty", testCalculateParameterStatisticsEmpty, result)
    runTest("testCalculateParameterStatisticsSingleValue", testCalculateParameterStatisticsSingleValue, result)
    runTest("testCalculateParameterStatisticsWithDate", testCalculateParameterStatisticsWithDate, result)

    # Statistics Engine Init Tests
    print("\nStatistics Engine Init Tests:")
    runTest("testStatisticsEngineInit", testStatisticsEngineInit, result)
    runTest("testStatisticsEngineInitMinSamples", testStatisticsEngineInitMinSamples, result)

    # Statistics Engine State Tests
    print("\nStatistics Engine State Tests:")
    runTest("testStatisticsEngineStateIdle", testStatisticsEngineStateIdle, result)

    # Statistics Engine Calculate Tests
    print("\nStatistics Engine Calculate Tests:")
    runTest("testStatisticsEngineCalculateNoData", testStatisticsEngineCalculateNoData, result)
    runTest("testStatisticsEngineCalculateWithData", testStatisticsEngineCalculateWithData, result)
    runTest("testStatisticsEngineCalculateStoresResults", testStatisticsEngineCalculateStoresResults, result)
    runTest("testStatisticsEngineCalculateNoStore", testStatisticsEngineCalculateNoStore, result)
    runTest("testStatisticsEngineCalculateMultipleProfiles", testStatisticsEngineCalculateMultipleProfiles, result)

    # Statistics Engine Retrieve Tests
    print("\nStatistics Engine Retrieve Tests:")
    runTest("testStatisticsEngineGetParameterStats", testStatisticsEngineGetParameterStats, result)
    runTest("testStatisticsEngineGetParameterStatsLimit", testStatisticsEngineGetParameterStatsLimit, result)
    runTest("testStatisticsEngineGetLatestResult", testStatisticsEngineGetLatestResult, result)
    runTest("testStatisticsEngineGetLatestResultNoData", testStatisticsEngineGetLatestResultNoData, result)

    # Statistics Engine Scheduling Tests
    print("\nStatistics Engine Scheduling Tests:")
    runTest("testStatisticsEngineScheduleImmediate", testStatisticsEngineScheduleImmediate, result)
    runTest("testStatisticsEngineCancelScheduled", testStatisticsEngineCancelScheduled, result)
    runTest("testStatisticsEngineCancelNoScheduled", testStatisticsEngineCancelNoScheduled, result)

    # Statistics Engine Callbacks Tests
    print("\nStatistics Engine Callbacks Tests:")
    runTest("testStatisticsEngineCallbacks", testStatisticsEngineCallbacks, result)

    # Statistics Engine Stats Tests
    print("\nStatistics Engine Stats Tests:")
    runTest("testStatisticsEngineGetEngineStats", testStatisticsEngineGetEngineStats, result)
    runTest("testStatisticsEngineGetAnalysisCount", testStatisticsEngineGetAnalysisCount, result)

    # Helper Functions Tests
    print("\nHelper Functions Tests:")
    runTest("testCreateStatisticsEngineFromConfig", testCreateStatisticsEngineFromConfig, result)
    runTest("testCalculateStatisticsForDrive", testCalculateStatisticsForDrive, result)
    runTest("testGetStatisticsSummary", testGetStatisticsSummary, result)
    runTest("testGetStatisticsSummaryFiltered", testGetStatisticsSummaryFiltered, result)

    # Analysis State Enum Tests
    print("\nAnalysis State Enum Tests:")
    runTest("testAnalysisStateValues", testAnalysisStateValues, result)

    # Edge Case Tests
    print("\nEdge Case Tests:")
    runTest("testStatisticsWithIdenticalValues", testStatisticsWithIdenticalValues, result)
    runTest("testStatisticsWithLargeDataset", testStatisticsWithLargeDataset, result)
    runTest("testStatisticsWithNegativeValues", testStatisticsWithNegativeValues, result)
    runTest("testStatisticsWithVerySmallValues", testStatisticsWithVerySmallValues, result)
    runTest("testStatisticsEngineDefaultProfile", testStatisticsEngineDefaultProfile, result)

    # Summary
    print("\n" + "=" * 60)
    print(f"Tests completed: {result.passed + result.failed}")
    print(f"Passed: {result.passed}")
    print(f"Failed: {result.failed}")
    print("=" * 60)

    if result.errors:
        print("\nFailed tests:")
        for error in result.errors:
            print(f"  - {error}")

    return 0 if result.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
