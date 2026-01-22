#!/usr/bin/env python3
################################################################################
# File Name: run_tests_profile_statistics.py
# Purpose/Description: Tests for profile-specific statistics and analysis (US-026)
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""
Manual test runner for profile-specific statistics module tests.

Tests profile filtering, cross-profile comparison, and report generation
functionality for the Eclipse OBD-II Performance Monitoring System.

Usage:
    python tests/run_tests_profile_statistics.py
"""

import sys
import os
import time
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
    calculateParameterStatistics,
    getStatisticsSummary,
)
from obd.profile_statistics import (
    ProfileStatisticsManager,
    ProfileComparison,
    ProfileComparisonResult,
    ParameterComparison,
    ProfileStatisticsReport,
    ProfileStatisticsError,
    createProfileStatisticsManager,
    compareProfiles,
    generateProfileReport,
    getProfileStatisticsSummary,
    getAllProfilesStatistics,
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


def insertStatistics(db: ObdDatabase, parameterName: str, profileId: str,
                     maxVal: float, minVal: float, avgVal: float,
                     sampleCount: int = 100) -> None:
    """Insert test statistics directly into statistics table."""
    ensureProfileExists(db, profileId)

    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO statistics
            (parameter_name, analysis_date, profile_id, max_value, min_value,
             avg_value, mode_value, std_1, std_2, outlier_min, outlier_max,
             sample_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (parameterName, datetime.now(), profileId, maxVal, minVal,
             avgVal, avgVal, 10.0, 20.0, minVal - 20.0, maxVal + 20.0,
             sampleCount)
        )


# ================================================================================
# ProfileStatisticsManager Init Tests
# ================================================================================

def testProfileStatisticsManagerInit():
    """Test ProfileStatisticsManager initialization."""
    db, dbPath = createTestDatabase()
    try:
        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        assert manager.database == db
        assert manager.config == config
    finally:
        cleanupDatabase(dbPath)


def testProfileStatisticsManagerInitWithStatisticsEngine():
    """Test ProfileStatisticsManager with custom StatisticsEngine."""
    db, dbPath = createTestDatabase()
    try:
        config = {'profiles': {'activeProfile': 'daily'}}
        engine = StatisticsEngine(db, config)
        manager = ProfileStatisticsManager(db, config, statisticsEngine=engine)

        assert manager.statisticsEngine == engine
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Profile Statistics Filtering Tests
# ================================================================================

def testProfileStatisticsGetByProfileId():
    """Test getting statistics filtered by profile ID."""
    db, dbPath = createTestDatabase()
    try:
        # Insert statistics for different profiles
        insertStatistics(db, 'RPM', 'daily', 6000.0, 800.0, 2500.0)
        insertStatistics(db, 'RPM', 'performance', 7500.0, 1000.0, 4000.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        # Get daily profile stats only
        stats = manager.getStatisticsForProfile('daily')

        assert 'RPM' in stats
        assert stats['RPM']['max'] == 6000.0  # Not 7500 from performance
        assert stats['RPM']['avg'] == 2500.0
    finally:
        cleanupDatabase(dbPath)


def testProfileStatisticsMultipleParameters():
    """Test getting multiple parameter statistics for a profile."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 6000.0, 800.0, 2500.0)
        insertStatistics(db, 'SPEED', 'daily', 120.0, 0.0, 45.0)
        insertStatistics(db, 'COOLANT_TEMP', 'daily', 95.0, 70.0, 85.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        stats = manager.getStatisticsForProfile('daily')

        assert len(stats) == 3
        assert 'RPM' in stats
        assert 'SPEED' in stats
        assert 'COOLANT_TEMP' in stats
    finally:
        cleanupDatabase(dbPath)


def testProfileStatisticsNoData():
    """Test getting statistics for profile with no data."""
    db, dbPath = createTestDatabase()
    try:
        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        stats = manager.getStatisticsForProfile('daily')

        assert stats == {}
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Profile Comparison Tests
# ================================================================================

def testCompareProfilesBasic():
    """Test basic comparison between two profiles."""
    db, dbPath = createTestDatabase()
    try:
        # Daily profile: conservative driving
        insertStatistics(db, 'RPM', 'daily', 5500.0, 700.0, 2200.0)
        insertStatistics(db, 'SPEED', 'daily', 100.0, 0.0, 40.0)

        # Performance profile: aggressive driving
        insertStatistics(db, 'RPM', 'performance', 7200.0, 1200.0, 4500.0)
        insertStatistics(db, 'SPEED', 'performance', 180.0, 0.0, 90.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        comparison = manager.compareProfiles('daily', 'performance')

        assert comparison is not None
        assert comparison.profileId1 == 'daily'
        assert comparison.profileId2 == 'performance'
        assert 'RPM' in comparison.parameterComparisons
        assert 'SPEED' in comparison.parameterComparisons
    finally:
        cleanupDatabase(dbPath)


def testCompareProfilesVariance():
    """Test variance calculation in profile comparison."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 5000.0, 1000.0, 2500.0)
        insertStatistics(db, 'RPM', 'performance', 7500.0, 1500.0, 5000.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        comparison = manager.compareProfiles('daily', 'performance')

        rpmComp = comparison.parameterComparisons['RPM']
        # Average variance: (5000 - 2500) / 2500 = 1.0 = 100%
        assert rpmComp.avgVariancePercent == 100.0
        # Max variance: (7500 - 5000) / 5000 = 0.5 = 50%
        assert rpmComp.maxVariancePercent == 50.0
    finally:
        cleanupDatabase(dbPath)


def testCompareProfilesSignificantDifference():
    """Test detection of significant differences (>10%)."""
    db, dbPath = createTestDatabase()
    try:
        # Small difference - less than 10%
        insertStatistics(db, 'COOLANT_TEMP', 'daily', 90.0, 70.0, 82.0)
        insertStatistics(db, 'COOLANT_TEMP', 'performance', 92.0, 72.0, 85.0)

        # Large difference - more than 10%
        insertStatistics(db, 'RPM', 'daily', 5000.0, 800.0, 2000.0)
        insertStatistics(db, 'RPM', 'performance', 7500.0, 1200.0, 4000.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        comparison = manager.compareProfiles('daily', 'performance')

        # COOLANT_TEMP variance < 10%
        assert not comparison.parameterComparisons['COOLANT_TEMP'].isSignificant
        # RPM variance > 10%
        assert comparison.parameterComparisons['RPM'].isSignificant
    finally:
        cleanupDatabase(dbPath)


def testCompareProfilesNonOverlappingParameters():
    """Test comparison when profiles have different parameters."""
    db, dbPath = createTestDatabase()
    try:
        # Daily has RPM and SPEED
        insertStatistics(db, 'RPM', 'daily', 5000.0, 800.0, 2000.0)
        insertStatistics(db, 'SPEED', 'daily', 100.0, 0.0, 40.0)

        # Performance has RPM and BOOST_PRESSURE
        insertStatistics(db, 'RPM', 'performance', 7000.0, 1000.0, 4000.0)
        insertStatistics(db, 'BOOST_PRESSURE', 'performance', 15.0, 0.0, 8.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        comparison = manager.compareProfiles('daily', 'performance')

        # Should only compare common parameters
        assert 'RPM' in comparison.parameterComparisons
        assert 'SPEED' not in comparison.parameterComparisons
        assert 'BOOST_PRESSURE' not in comparison.parameterComparisons
        assert comparison.commonParameters == ['RPM']
    finally:
        cleanupDatabase(dbPath)


def testCompareProfilesNoCommonParameters():
    """Test comparison when profiles have no common parameters."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 5000.0, 800.0, 2000.0)
        insertStatistics(db, 'BOOST_PRESSURE', 'performance', 15.0, 0.0, 8.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        comparison = manager.compareProfiles('daily', 'performance')

        assert comparison is not None
        assert len(comparison.parameterComparisons) == 0
        assert comparison.commonParameters == []
    finally:
        cleanupDatabase(dbPath)


def testCompareMultipleProfiles():
    """Test comparison across more than 2 profiles."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 5000.0, 800.0, 2000.0)
        insertStatistics(db, 'RPM', 'performance', 7500.0, 1200.0, 4500.0)
        insertStatistics(db, 'RPM', 'economy', 4500.0, 700.0, 1800.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        results = manager.compareMultipleProfiles(['daily', 'performance', 'economy'])

        assert len(results) == 3  # C(3,2) = 3 pairs
        # Check all pairs exist
        profilePairs = [(r.profileId1, r.profileId2) for r in results]
        assert ('daily', 'performance') in profilePairs
        assert ('daily', 'economy') in profilePairs
        assert ('performance', 'economy') in profilePairs
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Profile Statistics Report Tests
# ================================================================================

def testGenerateReportSingleProfile():
    """Test generating report for a single profile."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 6000.0, 800.0, 2500.0, 500)
        insertStatistics(db, 'SPEED', 'daily', 120.0, 0.0, 55.0, 500)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        report = manager.generateReport(profileIds=['daily'])

        assert report is not None
        assert 'daily' in report.profileStatistics
        assert report.profileStatistics['daily']['RPM']['max'] == 6000.0
        assert report.totalSamples >= 1000
    finally:
        cleanupDatabase(dbPath)


def testGenerateReportMultipleProfiles():
    """Test generating report with multiple profiles."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 6000.0, 800.0, 2500.0)
        insertStatistics(db, 'RPM', 'performance', 7500.0, 1000.0, 4000.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        report = manager.generateReport(profileIds=['daily', 'performance'])

        assert 'daily' in report.profileStatistics
        assert 'performance' in report.profileStatistics
        assert len(report.comparisons) == 1  # One comparison pair
    finally:
        cleanupDatabase(dbPath)


def testReportIncludesSignificantDifferences():
    """Test report highlights significant differences."""
    db, dbPath = createTestDatabase()
    try:
        # Significant difference in RPM
        insertStatistics(db, 'RPM', 'daily', 5000.0, 800.0, 2000.0)
        insertStatistics(db, 'RPM', 'performance', 7500.0, 1200.0, 4500.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        report = manager.generateReport(profileIds=['daily', 'performance'])

        assert len(report.significantDifferences) > 0
        # RPM should be in significant differences
        rpmDiff = next(
            (d for d in report.significantDifferences if d.parameterName == 'RPM'),
            None
        )
        assert rpmDiff is not None
    finally:
        cleanupDatabase(dbPath)


def testReportToDict():
    """Test report serialization to dictionary."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 6000.0, 800.0, 2500.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        report = manager.generateReport(profileIds=['daily'])
        reportDict = report.toDict()

        assert 'reportDate' in reportDict
        assert 'profileStatistics' in reportDict
        assert 'comparisons' in reportDict
        assert 'significantDifferences' in reportDict
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# ParameterComparison Dataclass Tests
# ================================================================================

def testParameterComparisonDefaults():
    """Test ParameterComparison with required fields."""
    comp = ParameterComparison(
        parameterName='RPM',
        profile1Value=2500.0,
        profile2Value=4500.0
    )

    assert comp.parameterName == 'RPM'
    assert comp.profile1Value == 2500.0
    assert comp.profile2Value == 4500.0


def testParameterComparisonVariance():
    """Test ParameterComparison variance calculation."""
    comp = ParameterComparison(
        parameterName='RPM',
        profile1Value=2500.0,
        profile2Value=5000.0,
        avgVariancePercent=100.0,
        maxVariancePercent=50.0,
        isSignificant=True
    )

    assert comp.avgVariancePercent == 100.0
    assert comp.maxVariancePercent == 50.0
    assert comp.isSignificant is True


def testParameterComparisonToDict():
    """Test ParameterComparison serialization."""
    comp = ParameterComparison(
        parameterName='RPM',
        profile1Value=2500.0,
        profile2Value=4500.0,
        avgVariancePercent=80.0,
        isSignificant=True
    )

    result = comp.toDict()

    assert result['parameterName'] == 'RPM'
    assert result['profile1Value'] == 2500.0
    assert result['profile2Value'] == 4500.0
    assert result['avgVariancePercent'] == 80.0
    assert result['isSignificant'] is True


# ================================================================================
# ProfileComparison Dataclass Tests
# ================================================================================

def testProfileComparisonDefaults():
    """Test ProfileComparison with required fields."""
    comparison = ProfileComparison(
        profileId1='daily',
        profileId2='performance',
        comparisonDate=datetime.now()
    )

    assert comparison.profileId1 == 'daily'
    assert comparison.profileId2 == 'performance'
    assert comparison.parameterComparisons == {}


def testProfileComparisonWithParameters():
    """Test ProfileComparison with parameter comparisons."""
    paramComp = ParameterComparison(
        parameterName='RPM',
        profile1Value=2500.0,
        profile2Value=4500.0
    )

    comparison = ProfileComparison(
        profileId1='daily',
        profileId2='performance',
        comparisonDate=datetime.now(),
        parameterComparisons={'RPM': paramComp},
        commonParameters=['RPM']
    )

    assert 'RPM' in comparison.parameterComparisons
    assert comparison.commonParameters == ['RPM']


def testProfileComparisonToDict():
    """Test ProfileComparison serialization."""
    comparison = ProfileComparison(
        profileId1='daily',
        profileId2='performance',
        comparisonDate=datetime.now(),
        commonParameters=['RPM', 'SPEED']
    )

    result = comparison.toDict()

    assert result['profileId1'] == 'daily'
    assert result['profileId2'] == 'performance'
    assert result['commonParameters'] == ['RPM', 'SPEED']


# ================================================================================
# ProfileStatisticsReport Dataclass Tests
# ================================================================================

def testProfileStatisticsReportDefaults():
    """Test ProfileStatisticsReport with required fields."""
    report = ProfileStatisticsReport(
        reportDate=datetime.now(),
        profileIds=['daily']
    )

    assert report.profileIds == ['daily']
    assert report.profileStatistics == {}
    assert report.comparisons == []


def testProfileStatisticsReportToDict():
    """Test ProfileStatisticsReport serialization."""
    now = datetime.now()
    report = ProfileStatisticsReport(
        reportDate=now,
        profileIds=['daily', 'performance'],
        totalSamples=1500,
        totalParameters=10
    )

    result = report.toDict()

    assert result['profileIds'] == ['daily', 'performance']
    assert result['totalSamples'] == 1500
    assert result['totalParameters'] == 10


# ================================================================================
# Helper Functions Tests
# ================================================================================

def testCreateProfileStatisticsManager():
    """Test createProfileStatisticsManager helper function."""
    db, dbPath = createTestDatabase()
    try:
        config = {'profiles': {'activeProfile': 'daily'}}
        manager = createProfileStatisticsManager(db, config)

        assert isinstance(manager, ProfileStatisticsManager)
        assert manager.database == db
    finally:
        cleanupDatabase(dbPath)


def testCompareProfilesHelper():
    """Test compareProfiles helper function."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 5000.0, 800.0, 2000.0)
        insertStatistics(db, 'RPM', 'performance', 7500.0, 1200.0, 4500.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        comparison = compareProfiles(db, config, 'daily', 'performance')

        assert comparison.profileId1 == 'daily'
        assert comparison.profileId2 == 'performance'
    finally:
        cleanupDatabase(dbPath)


def testGenerateProfileReportHelper():
    """Test generateProfileReport helper function."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 6000.0, 800.0, 2500.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        report = generateProfileReport(db, config, profileIds=['daily'])

        assert 'daily' in report.profileStatistics
    finally:
        cleanupDatabase(dbPath)


def testGetProfileStatisticsSummaryHelper():
    """Test getProfileStatisticsSummary helper function."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 6000.0, 800.0, 2500.0)
        insertStatistics(db, 'SPEED', 'daily', 120.0, 0.0, 55.0)

        summary = getProfileStatisticsSummary(db, 'daily')

        assert 'RPM' in summary
        assert 'SPEED' in summary
    finally:
        cleanupDatabase(dbPath)


def testGetAllProfilesStatisticsHelper():
    """Test getAllProfilesStatistics helper function."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 6000.0, 800.0, 2500.0)
        insertStatistics(db, 'RPM', 'performance', 7500.0, 1000.0, 4000.0)

        allStats = getAllProfilesStatistics(db)

        assert 'daily' in allStats
        assert 'performance' in allStats
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Exception Tests
# ================================================================================

def testProfileStatisticsErrorMessage():
    """Test ProfileStatisticsError stores message."""
    error = ProfileStatisticsError("Test error")
    assert str(error) == "Test error"
    assert error.message == "Test error"


def testProfileStatisticsErrorDetails():
    """Test ProfileStatisticsError stores details."""
    error = ProfileStatisticsError("Test", details={'key': 'value'})
    assert error.details == {'key': 'value'}


def testCompareNonExistentProfile():
    """Test comparing with non-existent profile returns empty comparison."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 6000.0, 800.0, 2500.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        comparison = manager.compareProfiles('daily', 'nonexistent')

        assert comparison is not None
        assert len(comparison.parameterComparisons) == 0
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Integration Tests
# ================================================================================

def testFullWorkflowCalculateAndCompare():
    """Test full workflow: calculate statistics, then compare profiles."""
    db, dbPath = createTestDatabase()
    try:
        # Insert raw data for two profiles
        insertTestData(db, 'RPM', [2000.0, 2500.0, 3000.0, 2200.0, 2800.0], 'daily')
        insertTestData(db, 'RPM', [4000.0, 4500.0, 5000.0, 5500.0, 6000.0], 'performance')

        config = {'profiles': {'activeProfile': 'daily'}, 'analysis': {}}

        # Calculate statistics for both profiles
        engine = StatisticsEngine(db, config)
        engine.calculateStatistics(profileId='daily', storeResults=True)
        engine.calculateStatistics(profileId='performance', storeResults=True)

        # Now compare
        manager = ProfileStatisticsManager(db, config, statisticsEngine=engine)
        comparison = manager.compareProfiles('daily', 'performance')

        assert 'RPM' in comparison.parameterComparisons
        rpmComp = comparison.parameterComparisons['RPM']
        # Performance avg should be significantly higher
        assert rpmComp.isSignificant is True
    finally:
        cleanupDatabase(dbPath)


def testFullWorkflowGenerateComprehensiveReport():
    """Test generating comprehensive report with all features."""
    db, dbPath = createTestDatabase()
    try:
        # Insert data for multiple profiles
        insertStatistics(db, 'RPM', 'daily', 5500.0, 700.0, 2200.0, 1000)
        insertStatistics(db, 'SPEED', 'daily', 100.0, 0.0, 35.0, 1000)
        insertStatistics(db, 'RPM', 'performance', 7200.0, 1200.0, 4500.0, 500)
        insertStatistics(db, 'SPEED', 'performance', 180.0, 0.0, 90.0, 500)
        insertStatistics(db, 'RPM', 'economy', 4500.0, 600.0, 1800.0, 800)
        insertStatistics(db, 'SPEED', 'economy', 80.0, 0.0, 30.0, 800)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        report = manager.generateReport(
            profileIds=['daily', 'performance', 'economy']
        )

        # Check report structure
        assert len(report.profileStatistics) == 3
        assert len(report.comparisons) == 3  # C(3,2) = 3 pairs
        # daily: 1000+1000, performance: 500+500, economy: 800+800 = 4600
        assert report.totalSamples == 2000 + 1000 + 1600  # 4600
        assert len(report.significantDifferences) > 0

        # Verify serialization works
        reportDict = report.toDict()
        assert isinstance(reportDict, dict)
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Edge Case Tests
# ================================================================================

def testCompareProfilesZeroBaseValue():
    """Test comparison when base value is zero (avoid division by zero)."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'SPEED', 'daily', 100.0, 0.0, 0.0)  # avg = 0
        insertStatistics(db, 'SPEED', 'performance', 180.0, 0.0, 90.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        # Should not raise division by zero
        comparison = manager.compareProfiles('daily', 'performance')

        assert 'SPEED' in comparison.parameterComparisons
    finally:
        cleanupDatabase(dbPath)


def testCompareProfilesNegativeValues():
    """Test comparison with negative values."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'TIMING_ADV', 'daily', 20.0, -10.0, 5.0)
        insertStatistics(db, 'TIMING_ADV', 'performance', 30.0, -5.0, 15.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        comparison = manager.compareProfiles('daily', 'performance')

        assert 'TIMING_ADV' in comparison.parameterComparisons
    finally:
        cleanupDatabase(dbPath)


def testEmptyProfileIdsList():
    """Test report generation with empty profile IDs list."""
    db, dbPath = createTestDatabase()
    try:
        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        report = manager.generateReport(profileIds=[])

        assert report.profileIds == []
        assert report.profileStatistics == {}
    finally:
        cleanupDatabase(dbPath)


def testSingleProfileComparison():
    """Test that single profile doesn't generate comparisons."""
    db, dbPath = createTestDatabase()
    try:
        insertStatistics(db, 'RPM', 'daily', 6000.0, 800.0, 2500.0)

        config = {'profiles': {'activeProfile': 'daily'}}
        manager = ProfileStatisticsManager(db, config)

        report = manager.generateReport(profileIds=['daily'])

        assert len(report.comparisons) == 0
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Main Test Runner
# ================================================================================

def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Profile Statistics Tests (US-026)")
    print("=" * 60)

    result = TestResult()

    # ProfileStatisticsManager Init Tests
    print("\nProfileStatisticsManager Init Tests:")
    runTest("testProfileStatisticsManagerInit", testProfileStatisticsManagerInit, result)
    runTest("testProfileStatisticsManagerInitWithStatisticsEngine",
            testProfileStatisticsManagerInitWithStatisticsEngine, result)

    # Profile Statistics Filtering Tests
    print("\nProfile Statistics Filtering Tests:")
    runTest("testProfileStatisticsGetByProfileId", testProfileStatisticsGetByProfileId, result)
    runTest("testProfileStatisticsMultipleParameters",
            testProfileStatisticsMultipleParameters, result)
    runTest("testProfileStatisticsNoData", testProfileStatisticsNoData, result)

    # Profile Comparison Tests
    print("\nProfile Comparison Tests:")
    runTest("testCompareProfilesBasic", testCompareProfilesBasic, result)
    runTest("testCompareProfilesVariance", testCompareProfilesVariance, result)
    runTest("testCompareProfilesSignificantDifference",
            testCompareProfilesSignificantDifference, result)
    runTest("testCompareProfilesNonOverlappingParameters",
            testCompareProfilesNonOverlappingParameters, result)
    runTest("testCompareProfilesNoCommonParameters",
            testCompareProfilesNoCommonParameters, result)
    runTest("testCompareMultipleProfiles", testCompareMultipleProfiles, result)

    # Profile Statistics Report Tests
    print("\nProfile Statistics Report Tests:")
    runTest("testGenerateReportSingleProfile", testGenerateReportSingleProfile, result)
    runTest("testGenerateReportMultipleProfiles", testGenerateReportMultipleProfiles, result)
    runTest("testReportIncludesSignificantDifferences",
            testReportIncludesSignificantDifferences, result)
    runTest("testReportToDict", testReportToDict, result)

    # ParameterComparison Dataclass Tests
    print("\nParameterComparison Dataclass Tests:")
    runTest("testParameterComparisonDefaults", testParameterComparisonDefaults, result)
    runTest("testParameterComparisonVariance", testParameterComparisonVariance, result)
    runTest("testParameterComparisonToDict", testParameterComparisonToDict, result)

    # ProfileComparison Dataclass Tests
    print("\nProfileComparison Dataclass Tests:")
    runTest("testProfileComparisonDefaults", testProfileComparisonDefaults, result)
    runTest("testProfileComparisonWithParameters", testProfileComparisonWithParameters, result)
    runTest("testProfileComparisonToDict", testProfileComparisonToDict, result)

    # ProfileStatisticsReport Dataclass Tests
    print("\nProfileStatisticsReport Dataclass Tests:")
    runTest("testProfileStatisticsReportDefaults", testProfileStatisticsReportDefaults, result)
    runTest("testProfileStatisticsReportToDict", testProfileStatisticsReportToDict, result)

    # Helper Functions Tests
    print("\nHelper Functions Tests:")
    runTest("testCreateProfileStatisticsManager", testCreateProfileStatisticsManager, result)
    runTest("testCompareProfilesHelper", testCompareProfilesHelper, result)
    runTest("testGenerateProfileReportHelper", testGenerateProfileReportHelper, result)
    runTest("testGetProfileStatisticsSummaryHelper",
            testGetProfileStatisticsSummaryHelper, result)
    runTest("testGetAllProfilesStatisticsHelper", testGetAllProfilesStatisticsHelper, result)

    # Exception Tests
    print("\nException Tests:")
    runTest("testProfileStatisticsErrorMessage", testProfileStatisticsErrorMessage, result)
    runTest("testProfileStatisticsErrorDetails", testProfileStatisticsErrorDetails, result)
    runTest("testCompareNonExistentProfile", testCompareNonExistentProfile, result)

    # Integration Tests
    print("\nIntegration Tests:")
    runTest("testFullWorkflowCalculateAndCompare",
            testFullWorkflowCalculateAndCompare, result)
    runTest("testFullWorkflowGenerateComprehensiveReport",
            testFullWorkflowGenerateComprehensiveReport, result)

    # Edge Case Tests
    print("\nEdge Case Tests:")
    runTest("testCompareProfilesZeroBaseValue", testCompareProfilesZeroBaseValue, result)
    runTest("testCompareProfilesNegativeValues", testCompareProfilesNegativeValues, result)
    runTest("testEmptyProfileIdsList", testEmptyProfileIdsList, result)
    runTest("testSingleProfileComparison", testSingleProfileComparison, result)

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
