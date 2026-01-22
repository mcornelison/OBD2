#!/usr/bin/env python3
################################################################################
# File Name: run_tests_drive_detector.py
# Purpose/Description: Manual test runner for drive detector tests
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""
Test suite for drive_detector module.

Tests:
- DriveState enum
- DetectorState enum
- DriveSession dataclass
- DetectorConfig dataclass
- DetectorStats dataclass
- DriveDetector class initialization
- DriveDetector lifecycle (start/stop)
- RPM threshold detection (drive start)
- RPM threshold detection (drive end)
- State transitions
- Duration timing
- Statistics engine integration
- Callback execution
- Database logging
- Helper functions
- Edge cases
"""

import os
import sys
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.drive_detector import (
    DriveDetector,
    DriveState,
    DetectorState,
    DriveSession,
    DetectorConfig,
    DetectorStats,
    DriveDetectorError,
    DriveDetectorConfigError,
    DriveDetectorStateError,
    createDriveDetectorFromConfig,
    isDriveDetectionEnabled,
    getDriveDetectionConfig,
    getDefaultDriveDetectionConfig,
    DEFAULT_DRIVE_START_RPM_THRESHOLD,
    DEFAULT_DRIVE_START_DURATION_SECONDS,
    DEFAULT_DRIVE_END_RPM_THRESHOLD,
    DEFAULT_DRIVE_END_DURATION_SECONDS,
    DRIVE_DETECTION_PARAMETERS,
)


# ================================================================================
# Test Fixtures
# ================================================================================

def createTestConfig(overrides=None):
    """Create test configuration dictionary."""
    config = {
        'analysis': {
            'triggerAfterDrive': True,
            'driveStartRpmThreshold': 500,
            'driveStartDurationSeconds': 10,
            'driveEndRpmThreshold': 0,
            'driveEndDurationSeconds': 60,
        },
        'profiles': {
            'activeProfile': 'daily',
            'availableProfiles': [
                {
                    'id': 'daily',
                    'name': 'Daily',
                }
            ]
        }
    }

    if overrides:
        for key, value in overrides.items():
            if '.' in key:
                # Handle nested keys like 'analysis.driveStartRpmThreshold'
                parts = key.split('.')
                d = config
                for part in parts[:-1]:
                    d = d.setdefault(part, {})
                d[parts[-1]] = value
            else:
                config[key] = value

    return config


def createTestDatabase():
    """Create an in-memory test database with required tables."""
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Create connection_log table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS connection_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            event_type TEXT,
            mac_address TEXT,
            success BOOLEAN,
            error_message TEXT
        )
    """)

    conn.commit()
    return conn


class MockDatabase:
    """Mock database class for testing."""

    def __init__(self, connection=None):
        self._conn = connection or createTestDatabase()

    def connect(self):
        """Return connection context manager."""
        return self._ConnContext(self._conn)

    class _ConnContext:
        def __init__(self, conn):
            self._conn = conn

        def __enter__(self):
            return self._conn

        def __exit__(self, exc_type, exc_val, exc_tb):
            self._conn.commit()


class MockStatisticsEngine:
    """Mock statistics engine for testing."""

    def __init__(self):
        self.scheduleAnalysisCalled = False
        self.lastProfileId = None
        self.lastDelaySeconds = None
        self.callCount = 0

    def scheduleAnalysis(self, profileId=None, delaySeconds=0, analysisWindow=None):
        self.scheduleAnalysisCalled = True
        self.lastProfileId = profileId
        self.lastDelaySeconds = delaySeconds
        self.callCount += 1
        return True


# ================================================================================
# Test Classes
# ================================================================================

class TestDriveStateEnum(unittest.TestCase):
    """Test DriveState enumeration."""

    def test_allStatesExist(self):
        """All expected states should exist."""
        self.assertEqual(DriveState.UNKNOWN.value, 'unknown')
        self.assertEqual(DriveState.STOPPED.value, 'stopped')
        self.assertEqual(DriveState.STARTING.value, 'starting')
        self.assertEqual(DriveState.RUNNING.value, 'running')
        self.assertEqual(DriveState.STOPPING.value, 'stopping')
        self.assertEqual(DriveState.ENDED.value, 'ended')

    def test_enumCount(self):
        """Should have expected number of states."""
        self.assertEqual(len(DriveState), 6)


class TestDetectorStateEnum(unittest.TestCase):
    """Test DetectorState enumeration."""

    def test_allStatesExist(self):
        """All expected states should exist."""
        self.assertEqual(DetectorState.IDLE.value, 'idle')
        self.assertEqual(DetectorState.MONITORING.value, 'monitoring')
        self.assertEqual(DetectorState.ERROR.value, 'error')


class TestDriveSession(unittest.TestCase):
    """Test DriveSession dataclass."""

    def test_createSession(self):
        """Should create session with defaults."""
        now = datetime.now()
        session = DriveSession(startTime=now)

        self.assertEqual(session.startTime, now)
        self.assertIsNone(session.endTime)
        self.assertIsNone(session.profileId)
        self.assertEqual(session.peakRpm, 0.0)
        self.assertEqual(session.peakSpeed, 0.0)
        self.assertEqual(session.duration, 0.0)
        self.assertFalse(session.analysisTriggered)

    def test_sessionIsActive(self):
        """Should correctly report if session is active."""
        session = DriveSession(startTime=datetime.now())
        self.assertTrue(session.isActive())

        session.endTime = datetime.now()
        self.assertFalse(session.isActive())

    def test_sessionGetDuration(self):
        """Should calculate duration correctly."""
        start = datetime.now()
        session = DriveSession(startTime=start)

        # Active session - duration is from start to now
        time.sleep(0.1)
        duration = session.getDuration()
        self.assertGreater(duration, 0)

        # Completed session - duration is end - start
        end = start + timedelta(seconds=30)
        session.endTime = end
        self.assertEqual(session.getDuration(), 30.0)

    def test_sessionToDict(self):
        """Should convert to dictionary correctly."""
        now = datetime.now()
        session = DriveSession(
            startTime=now,
            profileId='daily',
            peakRpm=5000,
            peakSpeed=65,
        )

        d = session.toDict()
        self.assertIn('startTime', d)
        self.assertIn('endTime', d)
        self.assertEqual(d['profileId'], 'daily')
        self.assertEqual(d['peakRpm'], 5000)
        self.assertEqual(d['peakSpeed'], 65)


class TestDetectorConfig(unittest.TestCase):
    """Test DetectorConfig dataclass."""

    def test_defaultValues(self):
        """Should have correct default values."""
        config = DetectorConfig()

        self.assertEqual(config.driveStartRpmThreshold, DEFAULT_DRIVE_START_RPM_THRESHOLD)
        self.assertEqual(config.driveStartDurationSeconds, DEFAULT_DRIVE_START_DURATION_SECONDS)
        self.assertEqual(config.driveEndRpmThreshold, DEFAULT_DRIVE_END_RPM_THRESHOLD)
        self.assertEqual(config.driveEndDurationSeconds, DEFAULT_DRIVE_END_DURATION_SECONDS)
        self.assertTrue(config.triggerAnalysisAfterDrive)
        self.assertIsNone(config.profileId)

    def test_customValues(self):
        """Should accept custom values."""
        config = DetectorConfig(
            driveStartRpmThreshold=600,
            driveStartDurationSeconds=15,
            driveEndRpmThreshold=100,
            driveEndDurationSeconds=45,
            triggerAnalysisAfterDrive=False,
            profileId='performance'
        )

        self.assertEqual(config.driveStartRpmThreshold, 600)
        self.assertEqual(config.driveStartDurationSeconds, 15)
        self.assertEqual(config.driveEndRpmThreshold, 100)
        self.assertEqual(config.driveEndDurationSeconds, 45)
        self.assertFalse(config.triggerAnalysisAfterDrive)
        self.assertEqual(config.profileId, 'performance')

    def test_configToDict(self):
        """Should convert to dictionary correctly."""
        config = DetectorConfig(profileId='daily')
        d = config.toDict()

        self.assertIn('driveStartRpmThreshold', d)
        self.assertIn('driveStartDurationSeconds', d)
        self.assertIn('driveEndRpmThreshold', d)
        self.assertIn('driveEndDurationSeconds', d)
        self.assertIn('triggerAnalysisAfterDrive', d)
        self.assertEqual(d['profileId'], 'daily')


class TestDetectorStats(unittest.TestCase):
    """Test DetectorStats dataclass."""

    def test_defaultValues(self):
        """Should have correct default values."""
        stats = DetectorStats()

        self.assertEqual(stats.valuesProcessed, 0)
        self.assertEqual(stats.drivesDetected, 0)
        self.assertEqual(stats.analysesTriggered, 0)
        self.assertIsNone(stats.lastDriveStart)
        self.assertIsNone(stats.lastDriveEnd)
        self.assertEqual(stats.currentDriveDuration, 0.0)

    def test_statsToDict(self):
        """Should convert to dictionary correctly."""
        now = datetime.now()
        stats = DetectorStats(
            valuesProcessed=100,
            drivesDetected=5,
            lastDriveStart=now
        )
        d = stats.toDict()

        self.assertEqual(d['valuesProcessed'], 100)
        self.assertEqual(d['drivesDetected'], 5)
        self.assertIn('lastDriveStart', d)


class TestConstants(unittest.TestCase):
    """Test module constants."""

    def test_defaultThresholds(self):
        """Default thresholds should be correct per PRD."""
        self.assertEqual(DEFAULT_DRIVE_START_RPM_THRESHOLD, 500)
        self.assertEqual(DEFAULT_DRIVE_START_DURATION_SECONDS, 10)
        self.assertEqual(DEFAULT_DRIVE_END_RPM_THRESHOLD, 0)
        self.assertEqual(DEFAULT_DRIVE_END_DURATION_SECONDS, 60)

    def test_driveDetectionParameters(self):
        """Should have correct parameters list."""
        self.assertIn('RPM', DRIVE_DETECTION_PARAMETERS)
        self.assertIn('SPEED', DRIVE_DETECTION_PARAMETERS)


class TestExceptions(unittest.TestCase):
    """Test custom exceptions."""

    def test_driveDetectorError(self):
        """Should create error with message and details."""
        error = DriveDetectorError("test error", details={'key': 'value'})
        self.assertEqual(error.message, "test error")
        self.assertEqual(error.details, {'key': 'value'})

    def test_configError(self):
        """ConfigError should be subclass of DriveDetectorError."""
        self.assertTrue(issubclass(DriveDetectorConfigError, DriveDetectorError))

    def test_stateError(self):
        """StateError should be subclass of DriveDetectorError."""
        self.assertTrue(issubclass(DriveDetectorStateError, DriveDetectorError))


class TestDriveDetectorInit(unittest.TestCase):
    """Test DriveDetector initialization."""

    def test_initWithDefaults(self):
        """Should initialize with default config."""
        config = createTestConfig()
        detector = DriveDetector(config)

        self.assertEqual(detector.getDriveState(), DriveState.UNKNOWN)
        self.assertEqual(detector.getDetectorState(), DetectorState.IDLE)
        self.assertIsNone(detector.getCurrentSession())
        self.assertFalse(detector.isDriving())

    def test_initWithStatisticsEngine(self):
        """Should accept statistics engine."""
        config = createTestConfig()
        engine = MockStatisticsEngine()
        detector = DriveDetector(config, statisticsEngine=engine)

        # Can't directly access private member, but can verify it works
        self.assertIsNotNone(detector)

    def test_initLoadsConfigValues(self):
        """Should load configuration values."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 600,
            'analysis.driveStartDurationSeconds': 15,
        })
        detector = DriveDetector(config)
        detectorConfig = detector.getConfig()

        self.assertEqual(detectorConfig.driveStartRpmThreshold, 600)
        self.assertEqual(detectorConfig.driveStartDurationSeconds, 15)

    def test_initWithProfileId(self):
        """Should load active profile from config."""
        config = createTestConfig()
        detector = DriveDetector(config)
        detectorConfig = detector.getConfig()

        self.assertEqual(detectorConfig.profileId, 'daily')


class TestDriveDetectorLifecycle(unittest.TestCase):
    """Test DriveDetector start/stop lifecycle."""

    def test_startDetector(self):
        """Should start detector."""
        config = createTestConfig()
        detector = DriveDetector(config)

        result = detector.start()

        self.assertTrue(result)
        self.assertTrue(detector.isMonitoring())
        self.assertEqual(detector.getDetectorState(), DetectorState.MONITORING)
        self.assertEqual(detector.getDriveState(), DriveState.STOPPED)

    def test_startWhenAlreadyRunning(self):
        """Should return True if already running."""
        config = createTestConfig()
        detector = DriveDetector(config)
        detector.start()

        result = detector.start()

        self.assertTrue(result)
        self.assertTrue(detector.isMonitoring())

    def test_stopDetector(self):
        """Should stop detector."""
        config = createTestConfig()
        detector = DriveDetector(config)
        detector.start()

        detector.stop()

        self.assertFalse(detector.isMonitoring())
        self.assertEqual(detector.getDetectorState(), DetectorState.IDLE)


class TestDriveStartDetection(unittest.TestCase):
    """Test drive start detection logic."""

    def test_rpmAboveThresholdTransitionsToStarting(self):
        """RPM above threshold should transition to STARTING state."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 1,
        })
        detector = DriveDetector(config)
        detector.start()

        # Process RPM above threshold
        detector.processValue('RPM', 600)

        self.assertEqual(detector.getDriveState(), DriveState.STARTING)

    def test_rpmBelowThresholdStaysInStopped(self):
        """RPM below threshold should stay in STOPPED state."""
        config = createTestConfig()
        detector = DriveDetector(config)
        detector.start()

        # Process RPM below threshold
        detector.processValue('RPM', 400)

        self.assertEqual(detector.getDriveState(), DriveState.STOPPED)

    def test_driveStartsAfterDuration(self):
        """Drive should start after RPM above threshold for duration."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,  # 100ms for fast testing
        })
        detector = DriveDetector(config)
        detector.start()

        # Process RPM above threshold
        detector.processValue('RPM', 600)
        self.assertEqual(detector.getDriveState(), DriveState.STARTING)

        # Wait for duration
        time.sleep(0.15)

        # Process another RPM above threshold
        detector.processValue('RPM', 650)

        self.assertEqual(detector.getDriveState(), DriveState.RUNNING)
        self.assertTrue(detector.isDriving())
        self.assertIsNotNone(detector.getCurrentSession())

    def test_driveDoesNotStartIfRpmDrops(self):
        """Drive should not start if RPM drops before duration."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 1.0,
        })
        detector = DriveDetector(config)
        detector.start()

        # Process RPM above threshold
        detector.processValue('RPM', 600)
        self.assertEqual(detector.getDriveState(), DriveState.STARTING)

        # RPM drops below threshold
        detector.processValue('RPM', 400)

        self.assertEqual(detector.getDriveState(), DriveState.STOPPED)
        self.assertFalse(detector.isDriving())


class TestDriveEndDetection(unittest.TestCase):
    """Test drive end detection logic."""

    def setUp(self):
        """Set up a detector with active drive."""
        self.config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
            'analysis.driveEndRpmThreshold': 0,
            'analysis.driveEndDurationSeconds': 0.1,
            'analysis.triggerAfterDrive': False,  # Disable for most tests
        })
        self.detector = DriveDetector(self.config)
        self.detector.start()

        # Start a drive
        self.detector.processValue('RPM', 600)
        time.sleep(0.15)
        self.detector.processValue('RPM', 650)

    def test_rpmAtZeroTransitionsToStopping(self):
        """RPM at 0 should transition to STOPPING state."""
        self.assertEqual(self.detector.getDriveState(), DriveState.RUNNING)

        # Process RPM at threshold
        self.detector.processValue('RPM', 0)

        self.assertEqual(self.detector.getDriveState(), DriveState.STOPPING)

    def test_driveEndsAfterDuration(self):
        """Drive should end after RPM at/below threshold for duration."""
        self.assertEqual(self.detector.getDriveState(), DriveState.RUNNING)

        # Process RPM at threshold
        self.detector.processValue('RPM', 0)
        self.assertEqual(self.detector.getDriveState(), DriveState.STOPPING)

        # Wait for duration
        time.sleep(0.15)

        # Process another RPM at threshold
        self.detector.processValue('RPM', 0)

        self.assertEqual(self.detector.getDriveState(), DriveState.STOPPED)
        self.assertFalse(self.detector.isDriving())
        self.assertIsNone(self.detector.getCurrentSession())

    def test_driveContinuesIfRpmGoesBackUp(self):
        """Drive should continue if RPM goes back up before duration."""
        self.assertEqual(self.detector.getDriveState(), DriveState.RUNNING)

        # Process RPM at threshold
        self.detector.processValue('RPM', 0)
        self.assertEqual(self.detector.getDriveState(), DriveState.STOPPING)

        # RPM goes back up
        self.detector.processValue('RPM', 1000)

        self.assertEqual(self.detector.getDriveState(), DriveState.RUNNING)
        self.assertTrue(self.detector.isDriving())


class TestStatisticsEngineIntegration(unittest.TestCase):
    """Test integration with StatisticsEngine."""

    def test_analysisTriggeredOnDriveEnd(self):
        """Analysis should be triggered when drive ends."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
            'analysis.driveEndRpmThreshold': 0,
            'analysis.driveEndDurationSeconds': 0.1,
            'analysis.triggerAfterDrive': True,
        })
        engine = MockStatisticsEngine()
        detector = DriveDetector(config, statisticsEngine=engine)
        detector.start()

        # Start a drive
        detector.processValue('RPM', 600)
        time.sleep(0.15)
        detector.processValue('RPM', 650)

        # End the drive
        detector.processValue('RPM', 0)
        time.sleep(0.15)
        detector.processValue('RPM', 0)

        self.assertTrue(engine.scheduleAnalysisCalled)
        self.assertEqual(engine.lastProfileId, 'daily')
        self.assertEqual(engine.lastDelaySeconds, 0)

    def test_analysisNotTriggeredIfDisabled(self):
        """Analysis should not trigger if disabled in config."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
            'analysis.driveEndRpmThreshold': 0,
            'analysis.driveEndDurationSeconds': 0.1,
            'analysis.triggerAfterDrive': False,
        })
        engine = MockStatisticsEngine()
        detector = DriveDetector(config, statisticsEngine=engine)
        detector.start()

        # Start and end a drive
        detector.processValue('RPM', 600)
        time.sleep(0.15)
        detector.processValue('RPM', 650)
        detector.processValue('RPM', 0)
        time.sleep(0.15)
        detector.processValue('RPM', 0)

        self.assertFalse(engine.scheduleAnalysisCalled)


class TestCallbacks(unittest.TestCase):
    """Test callback functionality."""

    def test_onDriveStartCallback(self):
        """onDriveStart callback should be called when drive starts."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
        })
        detector = DriveDetector(config)

        callback = MagicMock()
        detector.registerCallbacks(onDriveStart=callback)
        detector.start()

        # Start a drive
        detector.processValue('RPM', 600)
        time.sleep(0.15)
        detector.processValue('RPM', 650)

        callback.assert_called_once()
        # Verify it was called with a DriveSession
        args, _ = callback.call_args
        self.assertIsInstance(args[0], DriveSession)

    def test_onDriveEndCallback(self):
        """onDriveEnd callback should be called when drive ends."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
            'analysis.driveEndRpmThreshold': 0,
            'analysis.driveEndDurationSeconds': 0.1,
            'analysis.triggerAfterDrive': False,
        })
        detector = DriveDetector(config)

        callback = MagicMock()
        detector.registerCallbacks(onDriveEnd=callback)
        detector.start()

        # Start and end a drive
        detector.processValue('RPM', 600)
        time.sleep(0.15)
        detector.processValue('RPM', 650)
        detector.processValue('RPM', 0)
        time.sleep(0.15)
        detector.processValue('RPM', 0)

        callback.assert_called_once()
        args, _ = callback.call_args
        self.assertIsInstance(args[0], DriveSession)
        self.assertIsNotNone(args[0].endTime)

    def test_onStateChangeCallback(self):
        """onStateChange callback should be called on state transitions."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
        })
        detector = DriveDetector(config)

        callback = MagicMock()
        detector.registerCallbacks(onStateChange=callback)
        detector.start()

        # This transitions from UNKNOWN to STOPPED
        # Process RPM above threshold (transitions to STARTING)
        detector.processValue('RPM', 600)

        # Should have been called for UNKNOWN->STOPPED and STOPPED->STARTING
        self.assertGreaterEqual(callback.call_count, 1)


class TestDatabaseLogging(unittest.TestCase):
    """Test database logging functionality."""

    def test_driveStartLoggedToDatabase(self):
        """Drive start should be logged to database."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
        })
        mockDb = MockDatabase()
        detector = DriveDetector(config, database=mockDb)
        detector.start()

        # Start a drive
        detector.processValue('RPM', 600)
        time.sleep(0.15)
        detector.processValue('RPM', 650)

        # Check database
        cursor = mockDb._conn.cursor()
        cursor.execute("SELECT * FROM connection_log WHERE event_type = 'drive_start'")
        rows = cursor.fetchall()

        self.assertEqual(len(rows), 1)

    def test_driveEndLoggedToDatabase(self):
        """Drive end should be logged to database."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
            'analysis.driveEndRpmThreshold': 0,
            'analysis.driveEndDurationSeconds': 0.1,
            'analysis.triggerAfterDrive': False,
        })
        mockDb = MockDatabase()
        detector = DriveDetector(config, database=mockDb)
        detector.start()

        # Start and end a drive
        detector.processValue('RPM', 600)
        time.sleep(0.15)
        detector.processValue('RPM', 650)
        detector.processValue('RPM', 0)
        time.sleep(0.15)
        detector.processValue('RPM', 0)

        # Check database
        cursor = mockDb._conn.cursor()
        cursor.execute("SELECT * FROM connection_log WHERE event_type = 'drive_end'")
        rows = cursor.fetchall()

        self.assertEqual(len(rows), 1)


class TestStatistics(unittest.TestCase):
    """Test statistics tracking."""

    def test_valuesProcessedCounted(self):
        """Should count processed values."""
        config = createTestConfig()
        detector = DriveDetector(config)
        detector.start()

        detector.processValue('RPM', 1000)
        detector.processValue('RPM', 2000)
        detector.processValue('SPEED', 50)

        stats = detector.getStats()
        self.assertEqual(stats.valuesProcessed, 3)

    def test_drivesDetectedCounted(self):
        """Should count detected drives."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
        })
        detector = DriveDetector(config)
        detector.start()

        # Start a drive
        detector.processValue('RPM', 600)
        time.sleep(0.15)
        detector.processValue('RPM', 650)

        stats = detector.getStats()
        self.assertEqual(stats.drivesDetected, 1)

    def test_resetStats(self):
        """Should reset statistics."""
        config = createTestConfig()
        detector = DriveDetector(config)
        detector.start()

        detector.processValue('RPM', 1000)
        detector.processValue('RPM', 2000)

        detector.resetStats()

        stats = detector.getStats()
        self.assertEqual(stats.valuesProcessed, 0)
        self.assertEqual(stats.drivesDetected, 0)


class TestPeakTracking(unittest.TestCase):
    """Test peak value tracking during drive."""

    def test_peakRpmTracked(self):
        """Should track peak RPM during drive."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
        })
        detector = DriveDetector(config)
        detector.start()

        # Start a drive
        detector.processValue('RPM', 600)
        time.sleep(0.15)
        detector.processValue('RPM', 3000)
        detector.processValue('RPM', 5000)  # Peak
        detector.processValue('RPM', 4000)

        session = detector.getCurrentSession()
        self.assertEqual(session.peakRpm, 5000)

    def test_peakSpeedTracked(self):
        """Should track peak speed during drive."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
        })
        detector = DriveDetector(config)
        detector.start()

        # Start a drive
        detector.processValue('RPM', 600)
        time.sleep(0.15)
        detector.processValue('RPM', 3000)

        # Process speeds
        detector.processValue('SPEED', 30)
        detector.processValue('SPEED', 75)  # Peak
        detector.processValue('SPEED', 60)

        session = detector.getCurrentSession()
        self.assertEqual(session.peakSpeed, 75)


class TestHelperFunctions(unittest.TestCase):
    """Test helper functions."""

    def test_createDriveDetectorFromConfig(self):
        """Should create detector from config."""
        config = createTestConfig()
        detector = createDriveDetectorFromConfig(config)

        self.assertIsInstance(detector, DriveDetector)

    def test_isDriveDetectionEnabled(self):
        """Should check if drive detection is enabled."""
        config = createTestConfig({'analysis.triggerAfterDrive': True})
        self.assertTrue(isDriveDetectionEnabled(config))

        config = createTestConfig({'analysis.triggerAfterDrive': False})
        self.assertFalse(isDriveDetectionEnabled(config))

    def test_getDriveDetectionConfig(self):
        """Should extract drive detection config."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 600,
            'analysis.driveStartDurationSeconds': 15,
        })

        detectionConfig = getDriveDetectionConfig(config)

        self.assertEqual(detectionConfig['driveStartRpmThreshold'], 600)
        self.assertEqual(detectionConfig['driveStartDurationSeconds'], 15)
        self.assertIn('driveEndRpmThreshold', detectionConfig)
        self.assertIn('driveEndDurationSeconds', detectionConfig)

    def test_getDefaultDriveDetectionConfig(self):
        """Should return default config values."""
        defaults = getDefaultDriveDetectionConfig()

        self.assertEqual(defaults['driveStartRpmThreshold'], 500)
        self.assertEqual(defaults['driveStartDurationSeconds'], 10)
        self.assertEqual(defaults['driveEndRpmThreshold'], 0)
        self.assertEqual(defaults['driveEndDurationSeconds'], 60)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_processValueWhenNotMonitoring(self):
        """Should ignore values when not monitoring."""
        config = createTestConfig()
        detector = DriveDetector(config)

        # Don't start detector
        result = detector.processValue('RPM', 5000)

        self.assertEqual(result, DriveState.UNKNOWN)
        self.assertEqual(detector.getStats().valuesProcessed, 0)

    def test_processNonDriveParameter(self):
        """Should handle non-drive parameters gracefully."""
        config = createTestConfig()
        detector = DriveDetector(config)
        detector.start()

        # Process a parameter not in DRIVE_DETECTION_PARAMETERS
        detector.processValue('COOLANT_TEMP', 90)

        # Should still count it but not affect drive state
        stats = detector.getStats()
        self.assertEqual(stats.valuesProcessed, 1)

    def test_stopWhileDriving(self):
        """Should end drive when detector stops."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
            'analysis.triggerAfterDrive': False,
        })
        detector = DriveDetector(config)
        detector.start()

        # Start a drive
        detector.processValue('RPM', 600)
        time.sleep(0.15)
        detector.processValue('RPM', 650)

        self.assertTrue(detector.isDriving())

        # Stop detector
        detector.stop()

        # Drive should be ended
        self.assertFalse(detector.isDriving())

    def test_processMultipleValues(self):
        """Should process multiple values at once."""
        config = createTestConfig()
        detector = DriveDetector(config)
        detector.start()

        values = {'RPM': 3000, 'SPEED': 55, 'COOLANT_TEMP': 90}
        result = detector.processValues(values)

        self.assertIsInstance(result, DriveState)
        stats = detector.getStats()
        # Only RPM and SPEED are in DRIVE_DETECTION_PARAMETERS
        self.assertEqual(stats.valuesProcessed, 2)

    def test_resetDetector(self):
        """Should reset detector to initial state."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
        })
        detector = DriveDetector(config)
        detector.start()

        # Start a drive
        detector.processValue('RPM', 600)
        time.sleep(0.15)
        detector.processValue('RPM', 650)

        # Reset
        detector.reset()

        self.assertEqual(detector.getDriveState(), DriveState.STOPPED)
        self.assertIsNone(detector.getCurrentSession())

    def test_sessionHistoryMaintained(self):
        """Should maintain session history."""
        config = createTestConfig({
            'analysis.driveStartRpmThreshold': 500,
            'analysis.driveStartDurationSeconds': 0.1,
            'analysis.driveEndRpmThreshold': 0,
            'analysis.driveEndDurationSeconds': 0.1,
            'analysis.triggerAfterDrive': False,
        })
        detector = DriveDetector(config)
        detector.start()

        # Complete two drives
        for _ in range(2):
            detector.processValue('RPM', 600)
            time.sleep(0.15)
            detector.processValue('RPM', 650)
            detector.processValue('RPM', 0)
            time.sleep(0.15)
            detector.processValue('RPM', 0)

        history = detector.getSessionHistory()
        self.assertEqual(len(history), 2)

    def test_timingInfo(self):
        """Should provide timing information for debugging."""
        config = createTestConfig()
        detector = DriveDetector(config)
        detector.start()

        detector.processValue('RPM', 600)

        info = detector.getTimingInfo()

        self.assertIn('driveState', info)
        self.assertIn('lastRpm', info)
        self.assertIn('lastSpeed', info)
        self.assertEqual(info['lastRpm'], 600)


class TestConfigurationUpdates(unittest.TestCase):
    """Test runtime configuration updates."""

    def test_setThresholds(self):
        """Should update thresholds at runtime."""
        config = createTestConfig()
        detector = DriveDetector(config)

        detector.setThresholds(
            driveStartRpmThreshold=700,
            driveStartDurationSeconds=15
        )

        newConfig = detector.getConfig()
        self.assertEqual(newConfig.driveStartRpmThreshold, 700)
        self.assertEqual(newConfig.driveStartDurationSeconds, 15)

    def test_setTriggerAnalysis(self):
        """Should update analysis trigger setting."""
        config = createTestConfig()
        detector = DriveDetector(config)

        detector.setTriggerAnalysis(False)

        newConfig = detector.getConfig()
        self.assertFalse(newConfig.triggerAnalysisAfterDrive)

    def test_setProfileId(self):
        """Should update profile ID."""
        config = createTestConfig()
        detector = DriveDetector(config)

        detector.setProfileId('performance')

        newConfig = detector.getConfig()
        self.assertEqual(newConfig.profileId, 'performance')


# ================================================================================
# Main Test Runner
# ================================================================================

def runTests():
    """Run all tests and report results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    testClasses = [
        TestDriveStateEnum,
        TestDetectorStateEnum,
        TestDriveSession,
        TestDetectorConfig,
        TestDetectorStats,
        TestConstants,
        TestExceptions,
        TestDriveDetectorInit,
        TestDriveDetectorLifecycle,
        TestDriveStartDetection,
        TestDriveEndDetection,
        TestStatisticsEngineIntegration,
        TestCallbacks,
        TestDatabaseLogging,
        TestStatistics,
        TestPeakTracking,
        TestHelperFunctions,
        TestEdgeCases,
        TestConfigurationUpdates,
    ]

    for testClass in testClasses:
        tests = loader.loadTestsFromTestCase(testClass)
        suite.addTests(tests)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.failures:
        print("\nFailed tests:")
        for test, _ in result.failures:
            print(f"  - {test}")

    if result.errors:
        print("\nError tests:")
        for test, _ in result.errors:
            print(f"  - {test}")

    success = len(result.failures) == 0 and len(result.errors) == 0
    print(f"\nResult: {'PASSED' if success else 'FAILED'}")

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(runTests())
