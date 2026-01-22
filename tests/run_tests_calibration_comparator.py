################################################################################
# File Name: run_tests_calibration_comparator.py
# Purpose/Description: Tests for CalibrationComparator class
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-032
# ================================================================================
################################################################################

"""
Test suite for CalibrationComparator.

Tests calibration session comparison functionality including:
- Comparing 2+ calibration sessions
- Generating side-by-side statistics for each parameter
- Highlighting significant differences (>10% variance)
- Exporting comparison reports to CSV/JSON
"""

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.calibration_manager import (
    CalibrationManager,
    CalibrationSession,
    CalibrationState,
)
from obd.calibration_comparator import (
    CalibrationComparator,
    CalibrationComparisonError,
    CalibrationSessionComparison,
    ParameterSessionStats,
    SessionComparisonResult,
    SIGNIFICANCE_THRESHOLD,
    compareCalibrationSessions,
    createCalibrationComparatorFromConfig,
    exportComparisonReport,
)
from obd.database import ObdDatabase


class TestCalibrationComparatorInit(unittest.TestCase):
    """Test CalibrationComparator initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.tempDbFile):
            os.remove(self.tempDbFile)
        # Clean up WAL files
        walFile = self.tempDbFile + '-wal'
        shmFile = self.tempDbFile + '-shm'
        if os.path.exists(walFile):
            os.remove(walFile)
        if os.path.exists(shmFile):
            os.remove(shmFile)

    def test_init_withDatabase_createsInstance(self):
        """
        Given: Valid database
        When: CalibrationComparator is created
        Then: Instance should be created successfully
        """
        comparator = CalibrationComparator(database=self.database)

        self.assertIsNotNone(comparator)
        self.assertEqual(comparator.database, self.database)

    def test_init_withConfig_usesConfig(self):
        """
        Given: Database and config
        When: CalibrationComparator is created
        Then: Config should be stored
        """
        config = {'calibration': {'significanceThreshold': 15.0}}
        comparator = CalibrationComparator(database=self.database, config=config)

        self.assertEqual(comparator.config, config)


class TestParameterSessionStats(unittest.TestCase):
    """Test ParameterSessionStats dataclass."""

    def test_toDict_convertsAllFields(self):
        """
        Given: ParameterSessionStats with all fields
        When: toDict() is called
        Then: All fields should be in dictionary
        """
        stats = ParameterSessionStats(
            parameterName='RPM',
            sessionId=1,
            count=100,
            min=500.0,
            max=6000.0,
            avg=2500.0,
            stdDev=1200.0
        )

        result = stats.toDict()

        self.assertEqual(result['parameterName'], 'RPM')
        self.assertEqual(result['sessionId'], 1)
        self.assertEqual(result['count'], 100)
        self.assertEqual(result['min'], 500.0)
        self.assertEqual(result['max'], 6000.0)
        self.assertEqual(result['avg'], 2500.0)
        self.assertEqual(result['stdDev'], 1200.0)


class TestSessionComparisonResult(unittest.TestCase):
    """Test SessionComparisonResult dataclass."""

    def test_toDict_includesAllStats(self):
        """
        Given: SessionComparisonResult with session stats
        When: toDict() is called
        Then: All session stats should be serialized
        """
        stats1 = ParameterSessionStats(
            parameterName='RPM', sessionId=1, count=100,
            min=500.0, max=6000.0, avg=2500.0, stdDev=1200.0
        )
        stats2 = ParameterSessionStats(
            parameterName='RPM', sessionId=2, count=100,
            min=600.0, max=5800.0, avg=2800.0, stdDev=1100.0
        )

        result = SessionComparisonResult(
            parameterName='RPM',
            sessionStats={1: stats1, 2: stats2},
            variancePercent=12.0,
            isSignificant=True,
            description='RPM shows 12.0% variance'
        )

        dictResult = result.toDict()

        self.assertEqual(dictResult['parameterName'], 'RPM')
        self.assertEqual(len(dictResult['sessionStats']), 2)
        self.assertEqual(dictResult['variancePercent'], 12.0)
        self.assertTrue(dictResult['isSignificant'])


class TestCalibrationSessionComparison(unittest.TestCase):
    """Test CalibrationSessionComparison dataclass."""

    def test_toDict_includesMetadata(self):
        """
        Given: CalibrationSessionComparison with results
        When: toDict() is called
        Then: Metadata and results should be included
        """
        comparison = CalibrationSessionComparison(
            sessionIds=[1, 2, 3],
            comparisonDate=datetime(2026, 1, 22, 10, 0, 0),
            parameterResults={},
            significantCount=5,
            totalParameters=20,
            commonParameters=['RPM', 'COOLANT_TEMP']
        )

        result = comparison.toDict()

        self.assertEqual(result['sessionIds'], [1, 2, 3])
        self.assertEqual(result['significantCount'], 5)
        self.assertEqual(result['totalParameters'], 20)
        self.assertIn('RPM', result['commonParameters'])


class TestCompareSessions(unittest.TestCase):
    """Test session comparison functionality."""

    def setUp(self):
        """Set up test fixtures with sessions and readings."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()

        # Create CalibrationManager to set up sessions
        self.calibManager = CalibrationManager(database=self.database)
        self.calibManager.enable()

        # Create session 1 with specific RPM values
        self.session1 = self.calibManager.startSession(notes="Session 1")
        for i in range(10):
            self.calibManager.logCalibrationReading(
                parameterName='RPM',
                value=1000.0 + (i * 100),  # 1000-1900 avg=1450
                unit='rpm'
            )
            self.calibManager.logCalibrationReading(
                parameterName='COOLANT_TEMP',
                value=90.0 + (i * 1),  # 90-99 avg=94.5
                unit='C'
            )
        self.calibManager.endSession()

        # Create session 2 with different RPM values (>10% higher avg)
        self.session2 = self.calibManager.startSession(notes="Session 2")
        for i in range(10):
            self.calibManager.logCalibrationReading(
                parameterName='RPM',
                value=1200.0 + (i * 100),  # 1200-2100 avg=1650 (13.8% higher)
                unit='rpm'
            )
            self.calibManager.logCalibrationReading(
                parameterName='COOLANT_TEMP',
                value=91.0 + (i * 1),  # 91-100 avg=95.5 (1% higher)
                unit='C'
            )
        self.calibManager.endSession()

        self.comparator = CalibrationComparator(database=self.database)

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.tempDbFile):
            os.remove(self.tempDbFile)
        walFile = self.tempDbFile + '-wal'
        shmFile = self.tempDbFile + '-shm'
        if os.path.exists(walFile):
            os.remove(walFile)
        if os.path.exists(shmFile):
            os.remove(shmFile)

    def test_compareSessions_twoSessions_generatesComparison(self):
        """
        Given: Two calibration sessions
        When: compareSessions() is called
        Then: Comparison result should be generated
        """
        result = self.comparator.compareSessions([
            self.session1.sessionId,
            self.session2.sessionId
        ])

        self.assertIsNotNone(result)
        self.assertEqual(len(result.sessionIds), 2)
        self.assertIn('RPM', result.commonParameters)
        self.assertIn('COOLANT_TEMP', result.commonParameters)

    def test_compareSessions_detectsSignificantDifference(self):
        """
        Given: Sessions with >10% variance in RPM
        When: compareSessions() is called
        Then: RPM should be marked as significant
        """
        result = self.comparator.compareSessions([
            self.session1.sessionId,
            self.session2.sessionId
        ])

        rpmResult = result.parameterResults.get('RPM')
        self.assertIsNotNone(rpmResult)
        self.assertTrue(rpmResult.isSignificant)
        self.assertGreater(abs(rpmResult.variancePercent), 10.0)

    def test_compareSessions_detectsNonSignificantDifference(self):
        """
        Given: Sessions with <10% variance in COOLANT_TEMP
        When: compareSessions() is called
        Then: COOLANT_TEMP should NOT be marked as significant
        """
        result = self.comparator.compareSessions([
            self.session1.sessionId,
            self.session2.sessionId
        ])

        tempResult = result.parameterResults.get('COOLANT_TEMP')
        self.assertIsNotNone(tempResult)
        self.assertFalse(tempResult.isSignificant)

    def test_compareSessions_includesStatisticsForEachSession(self):
        """
        Given: Two sessions
        When: compareSessions() is called
        Then: Statistics should include data for both sessions
        """
        result = self.comparator.compareSessions([
            self.session1.sessionId,
            self.session2.sessionId
        ])

        rpmResult = result.parameterResults.get('RPM')
        self.assertIn(self.session1.sessionId, rpmResult.sessionStats)
        self.assertIn(self.session2.sessionId, rpmResult.sessionStats)

        # Check session 1 stats
        stats1 = rpmResult.sessionStats[self.session1.sessionId]
        self.assertEqual(stats1.count, 10)
        self.assertAlmostEqual(stats1.min, 1000.0, places=1)
        self.assertAlmostEqual(stats1.max, 1900.0, places=1)

    def test_compareSessions_countsSignificantParameters(self):
        """
        Given: Sessions with some significant differences
        When: compareSessions() is called
        Then: significantCount should reflect actual count
        """
        result = self.comparator.compareSessions([
            self.session1.sessionId,
            self.session2.sessionId
        ])

        # RPM has >10% variance, COOLANT_TEMP has <10% variance
        self.assertGreaterEqual(result.significantCount, 1)


class TestCompareThreeOrMoreSessions(unittest.TestCase):
    """Test comparison with three or more sessions."""

    def setUp(self):
        """Set up test fixtures with three sessions."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()

        self.calibManager = CalibrationManager(database=self.database)
        self.calibManager.enable()

        # Create three sessions with varying values
        self.sessionIds = []

        # Session 1: baseline
        session1 = self.calibManager.startSession(notes="Baseline")
        for i in range(5):
            self.calibManager.logCalibrationReading('RPM', 1000.0, 'rpm')
        self.calibManager.endSession()
        self.sessionIds.append(session1.sessionId)

        # Session 2: 15% higher
        session2 = self.calibManager.startSession(notes="Higher")
        for i in range(5):
            self.calibManager.logCalibrationReading('RPM', 1150.0, 'rpm')
        self.calibManager.endSession()
        self.sessionIds.append(session2.sessionId)

        # Session 3: 5% higher
        session3 = self.calibManager.startSession(notes="Slightly higher")
        for i in range(5):
            self.calibManager.logCalibrationReading('RPM', 1050.0, 'rpm')
        self.calibManager.endSession()
        self.sessionIds.append(session3.sessionId)

        self.comparator = CalibrationComparator(database=self.database)

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.tempDbFile):
            os.remove(self.tempDbFile)
        walFile = self.tempDbFile + '-wal'
        shmFile = self.tempDbFile + '-shm'
        if os.path.exists(walFile):
            os.remove(walFile)
        if os.path.exists(shmFile):
            os.remove(shmFile)

    def test_compareSessions_threeSessions_allIncluded(self):
        """
        Given: Three calibration sessions
        When: compareSessions() is called
        Then: All three sessions should be in result
        """
        result = self.comparator.compareSessions(self.sessionIds)

        self.assertEqual(len(result.sessionIds), 3)
        for sessionId in self.sessionIds:
            self.assertIn(sessionId, result.sessionIds)

    def test_compareSessions_threeSessions_statsForAll(self):
        """
        Given: Three calibration sessions
        When: compareSessions() is called
        Then: Statistics should exist for all sessions
        """
        result = self.comparator.compareSessions(self.sessionIds)

        rpmResult = result.parameterResults.get('RPM')
        for sessionId in self.sessionIds:
            self.assertIn(sessionId, rpmResult.sessionStats)


class TestCompareSessionsEdgeCases(unittest.TestCase):
    """Test edge cases for session comparison."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        self.comparator = CalibrationComparator(database=self.database)

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.tempDbFile):
            os.remove(self.tempDbFile)
        walFile = self.tempDbFile + '-wal'
        shmFile = self.tempDbFile + '-shm'
        if os.path.exists(walFile):
            os.remove(walFile)
        if os.path.exists(shmFile):
            os.remove(shmFile)

    def test_compareSessions_singleSession_raisesError(self):
        """
        Given: Only one session ID
        When: compareSessions() is called
        Then: CalibrationComparisonError should be raised
        """
        with self.assertRaises(CalibrationComparisonError) as ctx:
            self.comparator.compareSessions([1])

        self.assertIn('2', str(ctx.exception.message))

    def test_compareSessions_emptyList_raisesError(self):
        """
        Given: Empty session ID list
        When: compareSessions() is called
        Then: CalibrationComparisonError should be raised
        """
        with self.assertRaises(CalibrationComparisonError):
            self.comparator.compareSessions([])

    def test_compareSessions_nonexistentSession_raisesError(self):
        """
        Given: Session ID that doesn't exist
        When: compareSessions() is called
        Then: CalibrationComparisonError should be raised
        """
        with self.assertRaises(CalibrationComparisonError) as ctx:
            self.comparator.compareSessions([9999, 9998])

        self.assertIn('not found', str(ctx.exception.message).lower())


class TestVarianceCalculation(unittest.TestCase):
    """Test variance percentage calculation."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        self.comparator = CalibrationComparator(database=self.database)

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.tempDbFile):
            os.remove(self.tempDbFile)
        walFile = self.tempDbFile + '-wal'
        shmFile = self.tempDbFile + '-shm'
        if os.path.exists(walFile):
            os.remove(walFile)
        if os.path.exists(shmFile):
            os.remove(shmFile)

    def test_calculateMaxVariance_normalValues_returnsCorrect(self):
        """
        Given: List of average values [100, 110, 105]
        When: _calculateMaxVariance() is called
        Then: Should return variance based on max difference from mean
        """
        variance = self.comparator._calculateMaxVariance([100.0, 110.0, 105.0])

        # Mean is 105, max deviation is 5 (from 100 and 110), variance is ~4.76%
        self.assertIsNotNone(variance)
        self.assertGreater(variance, 0)

    def test_calculateMaxVariance_sameValues_returnsZero(self):
        """
        Given: List of identical values
        When: _calculateMaxVariance() is called
        Then: Should return 0
        """
        variance = self.comparator._calculateMaxVariance([100.0, 100.0, 100.0])

        self.assertEqual(variance, 0.0)

    def test_calculateMaxVariance_emptyList_returnsZero(self):
        """
        Given: Empty list
        When: _calculateMaxVariance() is called
        Then: Should return 0
        """
        variance = self.comparator._calculateMaxVariance([])

        self.assertEqual(variance, 0.0)


class TestExportComparisonToCsv(unittest.TestCase):
    """Test exporting comparison results to CSV."""

    def setUp(self):
        """Set up test fixtures with comparison data."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        self.exportDir = tempfile.mkdtemp()

        # Create sessions with data
        self.calibManager = CalibrationManager(database=self.database)
        self.calibManager.enable()

        session1 = self.calibManager.startSession(notes="Session 1")
        for i in range(5):
            self.calibManager.logCalibrationReading('RPM', 1000.0 + i * 100, 'rpm')
        self.calibManager.endSession()

        session2 = self.calibManager.startSession(notes="Session 2")
        for i in range(5):
            self.calibManager.logCalibrationReading('RPM', 1200.0 + i * 100, 'rpm')
        self.calibManager.endSession()

        self.sessionIds = [session1.sessionId, session2.sessionId]
        self.comparator = CalibrationComparator(database=self.database)

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.tempDbFile):
            os.remove(self.tempDbFile)
        walFile = self.tempDbFile + '-wal'
        shmFile = self.tempDbFile + '-shm'
        if os.path.exists(walFile):
            os.remove(walFile)
        if os.path.exists(shmFile):
            os.remove(shmFile)
        # Clean up export directory
        import shutil
        if os.path.exists(self.exportDir):
            shutil.rmtree(self.exportDir)

    def test_exportComparison_csv_createsFile(self):
        """
        Given: Comparison result
        When: exportComparison() is called with format='csv'
        Then: CSV file should be created
        """
        result = self.comparator.exportComparison(
            sessionIds=self.sessionIds,
            format='csv',
            exportDirectory=self.exportDir
        )

        self.assertTrue(result.success)
        self.assertTrue(os.path.exists(result.filePath))
        self.assertEqual(result.format, 'csv')

    def test_exportComparison_csv_hasHeaders(self):
        """
        Given: Exported CSV file
        When: File is read
        Then: Should have proper headers
        """
        result = self.comparator.exportComparison(
            sessionIds=self.sessionIds,
            format='csv',
            exportDirectory=self.exportDir
        )

        with open(result.filePath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)

        self.assertIn('parameter_name', headers)
        self.assertIn('variance_percent', headers)
        self.assertIn('is_significant', headers)

    def test_exportComparison_csv_includesSessionColumns(self):
        """
        Given: Comparison of two sessions
        When: CSV is exported
        Then: Should have columns for each session's stats
        """
        result = self.comparator.exportComparison(
            sessionIds=self.sessionIds,
            format='csv',
            exportDirectory=self.exportDir
        )

        with open(result.filePath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)

        # Should have session-specific columns like session_1_avg, session_2_avg
        sessionCols = [h for h in headers if h.startswith('session_')]
        self.assertGreater(len(sessionCols), 0)


class TestExportComparisonToJson(unittest.TestCase):
    """Test exporting comparison results to JSON."""

    def setUp(self):
        """Set up test fixtures with comparison data."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        self.exportDir = tempfile.mkdtemp()

        # Create sessions with data
        self.calibManager = CalibrationManager(database=self.database)
        self.calibManager.enable()

        session1 = self.calibManager.startSession(notes="Session 1")
        for i in range(5):
            self.calibManager.logCalibrationReading('RPM', 1000.0 + i * 100, 'rpm')
        self.calibManager.endSession()

        session2 = self.calibManager.startSession(notes="Session 2")
        for i in range(5):
            self.calibManager.logCalibrationReading('RPM', 1200.0 + i * 100, 'rpm')
        self.calibManager.endSession()

        self.sessionIds = [session1.sessionId, session2.sessionId]
        self.comparator = CalibrationComparator(database=self.database)

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.tempDbFile):
            os.remove(self.tempDbFile)
        walFile = self.tempDbFile + '-wal'
        shmFile = self.tempDbFile + '-shm'
        if os.path.exists(walFile):
            os.remove(walFile)
        if os.path.exists(shmFile):
            os.remove(shmFile)
        # Clean up export directory
        import shutil
        if os.path.exists(self.exportDir):
            shutil.rmtree(self.exportDir)

    def test_exportComparison_json_createsFile(self):
        """
        Given: Comparison result
        When: exportComparison() is called with format='json'
        Then: JSON file should be created
        """
        result = self.comparator.exportComparison(
            sessionIds=self.sessionIds,
            format='json',
            exportDirectory=self.exportDir
        )

        self.assertTrue(result.success)
        self.assertTrue(os.path.exists(result.filePath))
        self.assertEqual(result.format, 'json')

    def test_exportComparison_json_hasMetadata(self):
        """
        Given: Exported JSON file
        When: File is parsed
        Then: Should have metadata section
        """
        result = self.comparator.exportComparison(
            sessionIds=self.sessionIds,
            format='json',
            exportDirectory=self.exportDir
        )

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertIn('metadata', data)
        self.assertIn('sessionIds', data['metadata'])
        self.assertIn('comparisonDate', data['metadata'])
        self.assertIn('significantCount', data['metadata'])

    def test_exportComparison_json_hasResults(self):
        """
        Given: Exported JSON file
        When: File is parsed
        Then: Should have results section with parameter data
        """
        result = self.comparator.exportComparison(
            sessionIds=self.sessionIds,
            format='json',
            exportDirectory=self.exportDir
        )

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertIn('results', data)
        self.assertIsInstance(data['results'], list)
        # Should have RPM result
        paramNames = [r['parameterName'] for r in data['results']]
        self.assertIn('RPM', paramNames)

    def test_exportComparison_json_includesSignificantFlag(self):
        """
        Given: Comparison with significant difference
        When: JSON is exported
        Then: Results should include isSignificant flag
        """
        result = self.comparator.exportComparison(
            sessionIds=self.sessionIds,
            format='json',
            exportDirectory=self.exportDir
        )

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        rpmResult = next(
            (r for r in data['results'] if r['parameterName'] == 'RPM'),
            None
        )
        self.assertIsNotNone(rpmResult)
        self.assertIn('isSignificant', rpmResult)


class TestExportFilename(unittest.TestCase):
    """Test export filename generation."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        self.exportDir = tempfile.mkdtemp()

        # Create minimal sessions
        self.calibManager = CalibrationManager(database=self.database)
        self.calibManager.enable()

        session1 = self.calibManager.startSession(notes="S1")
        self.calibManager.logCalibrationReading('RPM', 1000.0, 'rpm')
        self.calibManager.endSession()

        session2 = self.calibManager.startSession(notes="S2")
        self.calibManager.logCalibrationReading('RPM', 1000.0, 'rpm')
        self.calibManager.endSession()

        self.sessionIds = [session1.sessionId, session2.sessionId]
        self.comparator = CalibrationComparator(database=self.database)

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.tempDbFile):
            os.remove(self.tempDbFile)
        walFile = self.tempDbFile + '-wal'
        shmFile = self.tempDbFile + '-shm'
        if os.path.exists(walFile):
            os.remove(walFile)
        if os.path.exists(shmFile):
            os.remove(shmFile)
        import shutil
        if os.path.exists(self.exportDir):
            shutil.rmtree(self.exportDir)

    def test_exportComparison_autoFilename_includesDate(self):
        """
        Given: No filename provided
        When: exportComparison() is called
        Then: Generated filename should include date
        """
        result = self.comparator.exportComparison(
            sessionIds=self.sessionIds,
            format='csv',
            exportDirectory=self.exportDir
        )

        filename = os.path.basename(result.filePath)
        today = datetime.now().strftime('%Y-%m-%d')
        self.assertIn(today, filename)

    def test_exportComparison_customFilename_usesProvided(self):
        """
        Given: Custom filename provided
        When: exportComparison() is called
        Then: Should use provided filename
        """
        result = self.comparator.exportComparison(
            sessionIds=self.sessionIds,
            format='csv',
            exportDirectory=self.exportDir,
            filename='my_comparison.csv'
        )

        self.assertTrue(result.filePath.endswith('my_comparison.csv'))


class TestHelperFunctions(unittest.TestCase):
    """Test helper functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        self.exportDir = tempfile.mkdtemp()

        # Create sessions
        self.calibManager = CalibrationManager(database=self.database)
        self.calibManager.enable()

        session1 = self.calibManager.startSession(notes="S1")
        self.calibManager.logCalibrationReading('RPM', 1000.0, 'rpm')
        self.calibManager.endSession()

        session2 = self.calibManager.startSession(notes="S2")
        self.calibManager.logCalibrationReading('RPM', 1200.0, 'rpm')
        self.calibManager.endSession()

        self.sessionIds = [session1.sessionId, session2.sessionId]

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.tempDbFile):
            os.remove(self.tempDbFile)
        walFile = self.tempDbFile + '-wal'
        shmFile = self.tempDbFile + '-shm'
        if os.path.exists(walFile):
            os.remove(walFile)
        if os.path.exists(shmFile):
            os.remove(shmFile)
        import shutil
        if os.path.exists(self.exportDir):
            shutil.rmtree(self.exportDir)

    def test_createCalibrationComparatorFromConfig_createsInstance(self):
        """
        Given: Database and config
        When: createCalibrationComparatorFromConfig() is called
        Then: CalibrationComparator instance should be returned
        """
        config = {'calibration': {'mode': True}}
        comparator = createCalibrationComparatorFromConfig(
            database=self.database,
            config=config
        )

        self.assertIsInstance(comparator, CalibrationComparator)

    def test_compareCalibrationSessions_convenienceFunction(self):
        """
        Given: Database and session IDs
        When: compareCalibrationSessions() is called
        Then: Comparison result should be returned
        """
        result = compareCalibrationSessions(
            database=self.database,
            sessionIds=self.sessionIds
        )

        self.assertIsInstance(result, CalibrationSessionComparison)
        self.assertEqual(len(result.sessionIds), 2)

    def test_exportComparisonReport_convenienceFunction(self):
        """
        Given: Database, session IDs, and export options
        When: exportComparisonReport() is called
        Then: Export result should be returned
        """
        from obd.calibration_comparator import ComparisonExportResult

        result = exportComparisonReport(
            database=self.database,
            sessionIds=self.sessionIds,
            format='json',
            exportDirectory=self.exportDir
        )

        self.assertIsInstance(result, ComparisonExportResult)
        self.assertTrue(result.success)


class TestSignificanceThreshold(unittest.TestCase):
    """Test significance threshold handling."""

    def test_defaultThreshold_is10Percent(self):
        """
        Given: Module imported
        When: SIGNIFICANCE_THRESHOLD is accessed
        Then: Should be 10.0
        """
        self.assertEqual(SIGNIFICANCE_THRESHOLD, 10.0)


class TestGetSessionStatistics(unittest.TestCase):
    """Test getting statistics for individual sessions."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()

        # Create session with known values
        self.calibManager = CalibrationManager(database=self.database)
        self.calibManager.enable()

        session = self.calibManager.startSession(notes="Stats test")
        # Values: 100, 200, 300, 400, 500 -> avg=300, min=100, max=500
        for value in [100.0, 200.0, 300.0, 400.0, 500.0]:
            self.calibManager.logCalibrationReading('TEST_PARAM', value, 'units')
        self.calibManager.endSession()

        self.sessionId = session.sessionId
        self.comparator = CalibrationComparator(database=self.database)

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.tempDbFile):
            os.remove(self.tempDbFile)
        walFile = self.tempDbFile + '-wal'
        shmFile = self.tempDbFile + '-shm'
        if os.path.exists(walFile):
            os.remove(walFile)
        if os.path.exists(shmFile):
            os.remove(shmFile)

    def test_getSessionStatistics_calculatesCorrectStats(self):
        """
        Given: Session with known values
        When: getSessionStatistics() is called
        Then: Statistics should be calculated correctly
        """
        stats = self.comparator.getSessionStatistics(self.sessionId)

        paramStats = stats.get('TEST_PARAM')
        self.assertIsNotNone(paramStats)
        self.assertEqual(paramStats.count, 5)
        self.assertAlmostEqual(paramStats.min, 100.0, places=1)
        self.assertAlmostEqual(paramStats.max, 500.0, places=1)
        self.assertAlmostEqual(paramStats.avg, 300.0, places=1)

    def test_getSessionStatistics_calculatesStdDev(self):
        """
        Given: Session with known values
        When: getSessionStatistics() is called
        Then: Standard deviation should be calculated
        """
        stats = self.comparator.getSessionStatistics(self.sessionId)

        paramStats = stats.get('TEST_PARAM')
        # stddev of [100,200,300,400,500] = ~158.11
        self.assertIsNotNone(paramStats.stdDev)
        self.assertGreater(paramStats.stdDev, 0)


if __name__ == '__main__':
    unittest.main()
