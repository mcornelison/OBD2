################################################################################
# File Name: run_tests_calibration_manager.py
# Purpose/Description: Tests for CalibrationManager class
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-030
# ================================================================================
################################################################################

"""
Test suite for CalibrationManager.

Tests calibration mode functionality including:
- Enabling/disabling calibration mode
- Session lifecycle (start/end)
- Logging all parameters when enabled
- Display indicator integration
- Session data retrieval
"""

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.calibration_manager import (
    CalibrationError,
    CalibrationExportResult,
    CalibrationManager,
    CalibrationNotEnabledError,
    CalibrationReading,
    CalibrationSession,
    CalibrationSessionError,
    CalibrationState,
    CalibrationStats,
    createCalibrationManagerFromConfig,
    exportCalibrationSession,
    getCalibrationConfig,
    isCalibrationModeEnabled,
)
from obd.database import ObdDatabase


class TestCalibrationManagerInit(unittest.TestCase):
    """Test CalibrationManager initialization."""

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

    def test_init_defaultConfig_disabledState(self):
        """
        Given: No config provided
        When: CalibrationManager is created
        Then: State should be DISABLED
        """
        manager = CalibrationManager(database=self.database)

        self.assertEqual(manager.state, CalibrationState.DISABLED)
        self.assertFalse(manager.isEnabled)
        self.assertIsNone(manager.currentSession)

    def test_init_calibrationModeTrue_enabledState(self):
        """
        Given: Config with calibration.mode = true
        When: CalibrationManager is created
        Then: State should be ENABLED
        """
        config = {'calibration': {'mode': True}}
        manager = CalibrationManager(database=self.database, config=config)

        self.assertEqual(manager.state, CalibrationState.ENABLED)
        self.assertTrue(manager.isEnabled)

    def test_init_createsCalibrationDataTable(self):
        """
        Given: Database without calibration_data table
        When: CalibrationManager is created
        Then: calibration_data table should exist
        """
        manager = CalibrationManager(database=self.database)

        # Check table exists
        with self.database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='calibration_data'"
            )
            result = cursor.fetchone()

        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'calibration_data')


class TestCalibrationManagerEnableDisable(unittest.TestCase):
    """Test enabling and disabling calibration mode."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        self.manager = CalibrationManager(database=self.database)

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

    def test_enable_fromDisabled_becomesEnabled(self):
        """
        Given: Manager in DISABLED state
        When: enable() is called
        Then: State becomes ENABLED
        """
        self.assertEqual(self.manager.state, CalibrationState.DISABLED)

        self.manager.enable()

        self.assertEqual(self.manager.state, CalibrationState.ENABLED)
        self.assertTrue(self.manager.isEnabled)

    def test_disable_fromEnabled_becomesDisabled(self):
        """
        Given: Manager in ENABLED state
        When: disable() is called
        Then: State becomes DISABLED
        """
        self.manager.enable()
        self.assertEqual(self.manager.state, CalibrationState.ENABLED)

        self.manager.disable()

        self.assertEqual(self.manager.state, CalibrationState.DISABLED)
        self.assertFalse(self.manager.isEnabled)

    def test_disable_withActiveSession_endsSession(self):
        """
        Given: Manager with active session
        When: disable() is called
        Then: Session is ended and state becomes DISABLED
        """
        self.manager.enable()
        session = self.manager.startSession(notes="Test")

        self.manager.disable()

        self.assertEqual(self.manager.state, CalibrationState.DISABLED)
        self.assertIsNone(self.manager.currentSession)

    def test_enable_triggersCallback(self):
        """
        Given: Callback registered for state change
        When: enable() is called
        Then: Callback is triggered with new state
        """
        callbackStates = []
        self.manager.onStateChange(lambda state: callbackStates.append(state))

        self.manager.enable()

        self.assertEqual(len(callbackStates), 1)
        self.assertEqual(callbackStates[0], CalibrationState.ENABLED)

    def test_enable_withDisplayManager_showsIndicator(self):
        """
        Given: DisplayManager connected
        When: enable() is called
        Then: CALIBRATION MODE indicator is shown
        """
        mockDisplay = MagicMock()
        self.manager._displayManager = mockDisplay

        self.manager.enable()

        mockDisplay.showAlert.assert_called_once()
        args, kwargs = mockDisplay.showAlert.call_args
        self.assertIn('CALIBRATION', kwargs.get('message', ''))


class TestCalibrationSessionLifecycle(unittest.TestCase):
    """Test calibration session start/end lifecycle."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        config = {'calibration': {'mode': True}}
        self.manager = CalibrationManager(database=self.database, config=config)

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

    def test_startSession_enabled_createsSession(self):
        """
        Given: Manager is enabled
        When: startSession() is called
        Then: A new session is created and returned
        """
        session = self.manager.startSession(notes="Test session")

        self.assertIsNotNone(session)
        self.assertIsInstance(session, CalibrationSession)
        self.assertIsNotNone(session.sessionId)
        self.assertIsNotNone(session.startTime)
        self.assertIsNone(session.endTime)
        self.assertEqual(session.notes, "Test session")
        self.assertTrue(session.isActive)

    def test_startSession_disabled_raisesError(self):
        """
        Given: Manager is disabled
        When: startSession() is called
        Then: CalibrationNotEnabledError is raised
        """
        self.manager.disable()

        with self.assertRaises(CalibrationNotEnabledError) as ctx:
            self.manager.startSession()

        self.assertIn("not enabled", str(ctx.exception))

    def test_startSession_withNotes_storesNotes(self):
        """
        Given: Manager is enabled
        When: startSession() is called with notes
        Then: Notes are stored in session
        """
        session = self.manager.startSession(notes="Sensor calibration run #1")

        self.assertEqual(session.notes, "Sensor calibration run #1")

        # Verify in database
        retrievedSession = self.manager.getSession(session.sessionId)
        self.assertEqual(retrievedSession.notes, "Sensor calibration run #1")

    def test_startSession_withProfileId_storesProfileId(self):
        """
        Given: Manager is enabled and profile exists
        When: startSession() is called with profileId
        Then: profileId is stored in session
        """
        # First create a profile in the database
        with self.database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO profiles (id, name) VALUES (?, ?)",
                ("performance", "Performance")
            )

        session = self.manager.startSession(profileId="performance")

        self.assertEqual(session.profileId, "performance")

    def test_startSession_notesRequired_raisesWithoutNotes(self):
        """
        Given: Config requires session notes
        When: startSession() is called without notes
        Then: CalibrationSessionError is raised
        """
        config = {
            'calibration': {
                'mode': True,
                'sessionNotesRequired': True
            }
        }
        manager = CalibrationManager(database=self.database, config=config)

        with self.assertRaises(CalibrationSessionError) as ctx:
            manager.startSession()

        self.assertIn("notes are required", str(ctx.exception))

    def test_startSession_activeSessionExists_raisesError(self):
        """
        Given: Manager has active session
        When: startSession() is called again
        Then: CalibrationSessionError is raised
        """
        self.manager.startSession(notes="First session")

        with self.assertRaises(CalibrationSessionError) as ctx:
            self.manager.startSession(notes="Second session")

        self.assertIn("already active", str(ctx.exception))

    def test_startSession_updatesState(self):
        """
        Given: Manager in ENABLED state
        When: startSession() is called
        Then: State becomes SESSION_ACTIVE
        """
        self.manager.startSession()

        self.assertEqual(self.manager.state, CalibrationState.SESSION_ACTIVE)
        self.assertTrue(self.manager.hasActiveSession)

    def test_startSession_triggersCallback(self):
        """
        Given: Callback registered for session start
        When: startSession() is called
        Then: Callback is triggered with session
        """
        sessions = []
        self.manager.onSessionStart(lambda s: sessions.append(s))

        session = self.manager.startSession()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].sessionId, session.sessionId)

    def test_endSession_activeSession_endsSession(self):
        """
        Given: Active session exists
        When: endSession() is called
        Then: Session is ended with end_time set
        """
        session = self.manager.startSession()
        sessionId = session.sessionId

        endedSession = self.manager.endSession()

        self.assertIsNotNone(endedSession)
        self.assertIsNotNone(endedSession.endTime)
        self.assertFalse(endedSession.isActive)
        self.assertIsNone(self.manager.currentSession)

    def test_endSession_noActiveSession_returnsNone(self):
        """
        Given: No active session
        When: endSession() is called
        Then: None is returned
        """
        result = self.manager.endSession()

        self.assertIsNone(result)

    def test_endSession_storesInDatabase(self):
        """
        Given: Active session exists
        When: endSession() is called
        Then: End time is stored in database
        """
        session = self.manager.startSession()
        sessionId = session.sessionId

        self.manager.endSession()

        # Verify in database
        with self.database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT end_time FROM calibration_sessions WHERE session_id = ?",
                (sessionId,)
            )
            row = cursor.fetchone()

        self.assertIsNotNone(row['end_time'])

    def test_endSession_triggersCallback(self):
        """
        Given: Callback registered for session end
        When: endSession() is called
        Then: Callback is triggered with ended session
        """
        sessions = []
        self.manager.onSessionEnd(lambda s: sessions.append(s))

        self.manager.startSession()
        self.manager.endSession()

        self.assertEqual(len(sessions), 1)
        self.assertIsNotNone(sessions[0].endTime)

    def test_endSession_calculatesDuration(self):
        """
        Given: Session has been running
        When: endSession() is called
        Then: Duration is calculated
        """
        session = self.manager.startSession()
        time.sleep(0.1)  # Small delay

        endedSession = self.manager.endSession()

        self.assertIsNotNone(endedSession.durationSeconds)
        self.assertGreater(endedSession.durationSeconds, 0)


class TestCalibrationReadings(unittest.TestCase):
    """Test logging calibration readings."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        config = {'calibration': {'mode': True}}
        self.manager = CalibrationManager(database=self.database, config=config)
        self.manager.startSession(notes="Test session")

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

    def test_logCalibrationReading_activeSession_logsReading(self):
        """
        Given: Active calibration session
        When: logCalibrationReading() is called
        Then: Reading is logged and returned
        """
        reading = self.manager.logCalibrationReading(
            parameterName="RPM",
            value=2500.0,
            unit="rpm"
        )

        self.assertIsInstance(reading, CalibrationReading)
        self.assertEqual(reading.parameterName, "RPM")
        self.assertEqual(reading.value, 2500.0)
        self.assertEqual(reading.unit, "rpm")
        self.assertIsNotNone(reading.timestamp)

    def test_logCalibrationReading_noActiveSession_raisesError(self):
        """
        Given: No active session
        When: logCalibrationReading() is called
        Then: CalibrationSessionError is raised
        """
        self.manager.endSession()

        with self.assertRaises(CalibrationSessionError) as ctx:
            self.manager.logCalibrationReading("RPM", 2500.0)

        self.assertIn("no active", str(ctx.exception))

    def test_logCalibrationReading_storesInDatabase(self):
        """
        Given: Active calibration session
        When: logCalibrationReading() is called
        Then: Reading is stored in calibration_data table
        """
        sessionId = self.manager.currentSession.sessionId
        self.manager.logCalibrationReading("RPM", 2500.0, "rpm")

        with self.database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM calibration_data WHERE session_id = ?",
                (sessionId,)
            )
            row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row['parameter_name'], "RPM")
        self.assertEqual(row['value'], 2500.0)
        self.assertEqual(row['unit'], "rpm")

    def test_logCalibrationReading_multipleReadings_allStored(self):
        """
        Given: Active calibration session
        When: Multiple readings are logged
        Then: All readings are stored
        """
        sessionId = self.manager.currentSession.sessionId

        self.manager.logCalibrationReading("RPM", 2500.0, "rpm")
        self.manager.logCalibrationReading("COOLANT_TEMP", 85.0, "°C")
        self.manager.logCalibrationReading("SPEED", 60.0, "km/h")

        with self.database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM calibration_data WHERE session_id = ?",
                (sessionId,)
            )
            count = cursor.fetchone()[0]

        self.assertEqual(count, 3)

    def test_logCalibrationReading_withRawValue_storesRawValue(self):
        """
        Given: Active calibration session
        When: logCalibrationReading() is called with rawValue
        Then: Raw value is stored
        """
        reading = self.manager.logCalibrationReading(
            parameterName="VIN",
            value=None,
            rawValue="1G1YY22G965104385"
        )

        self.assertEqual(reading.rawValue, "1G1YY22G965104385")
        self.assertIsNone(reading.value)

    def test_logCalibrationReading_withCustomTimestamp_usesProvidedTime(self):
        """
        Given: Active calibration session
        When: logCalibrationReading() is called with timestamp
        Then: Provided timestamp is used
        """
        customTime = datetime(2026, 1, 1, 12, 0, 0)

        reading = self.manager.logCalibrationReading(
            parameterName="RPM",
            value=2500.0,
            timestamp=customTime
        )

        self.assertEqual(reading.timestamp, customTime)


class TestCalibrationDataRetrieval(unittest.TestCase):
    """Test retrieving calibration session data."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        config = {'calibration': {'mode': True}}
        self.manager = CalibrationManager(database=self.database, config=config)

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

    def test_getSession_existingSession_returnsSession(self):
        """
        Given: Session exists in database
        When: getSession() is called
        Then: Session is returned
        """
        session = self.manager.startSession(notes="Test")
        sessionId = session.sessionId
        self.manager.endSession()

        retrieved = self.manager.getSession(sessionId)

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.sessionId, sessionId)
        self.assertEqual(retrieved.notes, "Test")

    def test_getSession_nonExistentSession_returnsNone(self):
        """
        Given: Session does not exist
        When: getSession() is called
        Then: None is returned
        """
        result = self.manager.getSession(9999)

        self.assertIsNone(result)

    def test_getSession_includesReadingCount(self):
        """
        Given: Session has readings
        When: getSession() is called
        Then: Reading count is included
        """
        session = self.manager.startSession()
        self.manager.logCalibrationReading("RPM", 2500.0)
        self.manager.logCalibrationReading("SPEED", 60.0)
        self.manager.endSession()

        retrieved = self.manager.getSession(session.sessionId)

        self.assertEqual(retrieved.readingCount, 2)

    def test_listSessions_multipleSessions_returnsAll(self):
        """
        Given: Multiple sessions exist
        When: listSessions() is called
        Then: All sessions are returned
        """
        self.manager.startSession(notes="Session 1")
        self.manager.endSession()
        self.manager.startSession(notes="Session 2")
        self.manager.endSession()
        self.manager.startSession(notes="Session 3")
        self.manager.endSession()

        sessions = self.manager.listSessions()

        self.assertEqual(len(sessions), 3)

    def test_listSessions_orderedByStartTimeDesc(self):
        """
        Given: Multiple sessions exist
        When: listSessions() is called
        Then: Sessions are ordered by start_time DESC (newest first)
        """
        self.manager.startSession(notes="First")
        self.manager.endSession()
        time.sleep(0.1)
        self.manager.startSession(notes="Second")
        self.manager.endSession()
        time.sleep(0.1)
        self.manager.startSession(notes="Third")
        self.manager.endSession()

        sessions = self.manager.listSessions()

        self.assertEqual(sessions[0].notes, "Third")
        self.assertEqual(sessions[2].notes, "First")

    def test_listSessions_excludeActive_onlyCompleted(self):
        """
        Given: Active and completed sessions exist
        When: listSessions(includeActive=False) is called
        Then: Only completed sessions are returned
        """
        self.manager.startSession(notes="Completed")
        self.manager.endSession()
        self.manager.startSession(notes="Active")  # Don't end

        sessions = self.manager.listSessions(includeActive=False)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].notes, "Completed")

    def test_listSessions_limit_respectsLimit(self):
        """
        Given: Many sessions exist
        When: listSessions(limit=2) is called
        Then: Only 2 sessions are returned
        """
        for i in range(5):
            self.manager.startSession(notes=f"Session {i}")
            self.manager.endSession()

        sessions = self.manager.listSessions(limit=2)

        self.assertEqual(len(sessions), 2)

    def test_getSessionReadings_existingSession_returnsReadings(self):
        """
        Given: Session has readings
        When: getSessionReadings() is called
        Then: All readings are returned
        """
        session = self.manager.startSession()
        self.manager.logCalibrationReading("RPM", 2500.0, "rpm")
        self.manager.logCalibrationReading("SPEED", 60.0, "km/h")
        self.manager.endSession()

        readings = self.manager.getSessionReadings(session.sessionId)

        self.assertEqual(len(readings), 2)
        self.assertIsInstance(readings[0], CalibrationReading)

    def test_getSessionReadings_filterByParameter(self):
        """
        Given: Session has readings for multiple parameters
        When: getSessionReadings(parameterName=...) is called
        Then: Only readings for that parameter are returned
        """
        session = self.manager.startSession()
        self.manager.logCalibrationReading("RPM", 2500.0)
        self.manager.logCalibrationReading("RPM", 2600.0)
        self.manager.logCalibrationReading("SPEED", 60.0)
        self.manager.endSession()

        readings = self.manager.getSessionReadings(
            session.sessionId,
            parameterName="RPM"
        )

        self.assertEqual(len(readings), 2)
        for reading in readings:
            self.assertEqual(reading.parameterName, "RPM")


class TestCalibrationParameterList(unittest.TestCase):
    """Test getting parameters to log during calibration."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()

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

    def test_getParametersToLog_logAllTrue_returnsAllParameters(self):
        """
        Given: logAllParameters is True (default)
        When: getParametersToLog() is called
        Then: All OBD-II parameters are returned
        """
        config = {'calibration': {'mode': True, 'logAllParameters': True}}
        manager = CalibrationManager(database=self.database, config=config)

        params = manager.getParametersToLog()

        # Should return many parameters
        self.assertGreater(len(params), 50)
        self.assertIn('RPM', params)
        self.assertIn('SPEED', params)
        self.assertIn('VIN', params)

    def test_getParametersToLog_logAllFalse_returnsConfiguredOnly(self):
        """
        Given: logAllParameters is False
        When: getParametersToLog() is called
        Then: Only configured parameters are returned
        """
        config = {
            'calibration': {
                'mode': True,
                'logAllParameters': False
            },
            'realtimeData': {
                'parameters': [
                    {'name': 'RPM', 'logData': True},
                    {'name': 'SPEED', 'logData': True}
                ]
            }
        }
        manager = CalibrationManager(database=self.database, config=config)

        params = manager.getParametersToLog()

        self.assertEqual(len(params), 2)
        self.assertIn('RPM', params)
        self.assertIn('SPEED', params)


class TestCalibrationStats(unittest.TestCase):
    """Test calibration statistics."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        config = {'calibration': {'mode': True}}
        self.manager = CalibrationManager(database=self.database, config=config)

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

    def test_getStats_emptyDatabase_returnsZeros(self):
        """
        Given: No sessions or readings
        When: getStats() is called
        Then: All counts are 0
        """
        stats = self.manager.getStats()

        self.assertIsInstance(stats, CalibrationStats)
        self.assertEqual(stats.totalSessions, 0)
        self.assertEqual(stats.activeSessions, 0)
        self.assertEqual(stats.totalReadings, 0)

    def test_getStats_withSessions_countsSessions(self):
        """
        Given: Sessions exist
        When: getStats() is called
        Then: Sessions are counted correctly
        """
        self.manager.startSession(notes="Session 1")
        self.manager.endSession()
        self.manager.startSession(notes="Session 2")
        # Don't end - active session

        stats = self.manager.getStats()

        self.assertEqual(stats.totalSessions, 2)
        self.assertEqual(stats.activeSessions, 1)

    def test_getStats_withReadings_countsReadings(self):
        """
        Given: Readings exist
        When: getStats() is called
        Then: Readings are counted correctly
        """
        self.manager.startSession()
        self.manager.logCalibrationReading("RPM", 2500.0)
        self.manager.logCalibrationReading("SPEED", 60.0)
        self.manager.endSession()

        stats = self.manager.getStats()

        self.assertEqual(stats.totalReadings, 2)

    def test_getStats_includesCurrentState(self):
        """
        Given: Manager in specific state
        When: getStats() is called
        Then: Current state is included
        """
        self.manager.startSession()

        stats = self.manager.getStats()

        self.assertEqual(stats.state, CalibrationState.SESSION_ACTIVE)
        self.assertIsNotNone(stats.currentSessionId)


class TestCalibrationHelperFunctions(unittest.TestCase):
    """Test helper functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()

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

    def test_createCalibrationManagerFromConfig(self):
        """
        Given: Config dictionary
        When: createCalibrationManagerFromConfig() is called
        Then: CalibrationManager is created
        """
        config = {'calibration': {'mode': True}}

        manager = createCalibrationManagerFromConfig(
            database=self.database,
            config=config
        )

        self.assertIsInstance(manager, CalibrationManager)
        self.assertTrue(manager.isEnabled)

    def test_isCalibrationModeEnabled_true(self):
        """
        Given: Config with calibration.mode = true
        When: isCalibrationModeEnabled() is called
        Then: True is returned
        """
        config = {'calibration': {'mode': True}}

        result = isCalibrationModeEnabled(config)

        self.assertTrue(result)

    def test_isCalibrationModeEnabled_false(self):
        """
        Given: Config with calibration.mode = false
        When: isCalibrationModeEnabled() is called
        Then: False is returned
        """
        config = {'calibration': {'mode': False}}

        result = isCalibrationModeEnabled(config)

        self.assertFalse(result)

    def test_isCalibrationModeEnabled_missing(self):
        """
        Given: Config without calibration section
        When: isCalibrationModeEnabled() is called
        Then: False is returned (default)
        """
        config = {}

        result = isCalibrationModeEnabled(config)

        self.assertFalse(result)

    def test_getCalibrationConfig_withAllFields(self):
        """
        Given: Config with all calibration fields
        When: getCalibrationConfig() is called
        Then: All fields are returned
        """
        config = {
            'calibration': {
                'mode': True,
                'logAllParameters': False,
                'sessionNotesRequired': True
            }
        }

        result = getCalibrationConfig(config)

        self.assertEqual(result['mode'], True)
        self.assertEqual(result['logAllParameters'], False)
        self.assertEqual(result['sessionNotesRequired'], True)

    def test_getCalibrationConfig_withDefaults(self):
        """
        Given: Config without calibration section
        When: getCalibrationConfig() is called
        Then: Defaults are returned
        """
        config = {}

        result = getCalibrationConfig(config)

        self.assertEqual(result['mode'], False)
        self.assertEqual(result['logAllParameters'], True)
        self.assertEqual(result['sessionNotesRequired'], False)


class TestCalibrationSessionDataclass(unittest.TestCase):
    """Test CalibrationSession dataclass methods."""

    def test_toDict_includesAllFields(self):
        """
        Given: CalibrationSession with all fields
        When: toDict() is called
        Then: All fields are in dictionary
        """
        session = CalibrationSession(
            sessionId=1,
            startTime=datetime(2026, 1, 22, 10, 0, 0),
            endTime=datetime(2026, 1, 22, 10, 30, 0),
            notes="Test notes",
            profileId="daily",
            readingCount=100
        )

        result = session.toDict()

        self.assertEqual(result['sessionId'], 1)
        self.assertEqual(result['notes'], "Test notes")
        self.assertEqual(result['profileId'], "daily")
        self.assertEqual(result['readingCount'], 100)
        self.assertIn('startTime', result)
        self.assertIn('endTime', result)
        self.assertIn('durationSeconds', result)

    def test_durationSeconds_completedSession(self):
        """
        Given: Session with start and end time
        When: durationSeconds is accessed
        Then: Correct duration is calculated
        """
        session = CalibrationSession(
            sessionId=1,
            startTime=datetime(2026, 1, 22, 10, 0, 0),
            endTime=datetime(2026, 1, 22, 10, 30, 0)
        )

        duration = session.durationSeconds

        self.assertEqual(duration, 1800.0)  # 30 minutes = 1800 seconds

    def test_isActive_noEndTime_true(self):
        """
        Given: Session without end time
        When: isActive is accessed
        Then: True is returned
        """
        session = CalibrationSession(
            sessionId=1,
            startTime=datetime(2026, 1, 22, 10, 0, 0)
        )

        self.assertTrue(session.isActive)

    def test_isActive_withEndTime_false(self):
        """
        Given: Session with end time
        When: isActive is accessed
        Then: False is returned
        """
        session = CalibrationSession(
            sessionId=1,
            startTime=datetime(2026, 1, 22, 10, 0, 0),
            endTime=datetime(2026, 1, 22, 10, 30, 0)
        )

        self.assertFalse(session.isActive)


class TestCalibrationReadingDataclass(unittest.TestCase):
    """Test CalibrationReading dataclass methods."""

    def test_toDict_includesAllFields(self):
        """
        Given: CalibrationReading with all fields
        When: toDict() is called
        Then: All fields are in dictionary
        """
        reading = CalibrationReading(
            parameterName="RPM",
            value=2500.0,
            unit="rpm",
            timestamp=datetime(2026, 1, 22, 10, 0, 0),
            sessionId=1,
            rawValue="2500"
        )

        result = reading.toDict()

        self.assertEqual(result['parameterName'], "RPM")
        self.assertEqual(result['value'], 2500.0)
        self.assertEqual(result['unit'], "rpm")
        self.assertEqual(result['sessionId'], 1)
        self.assertEqual(result['rawValue'], "2500")
        self.assertIn('timestamp', result)


class TestCalibrationDisplayIntegration(unittest.TestCase):
    """Test display integration for CALIBRATION MODE indicator."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        self.mockDisplay = MagicMock()

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

    def test_calibrationModeEnabled_showsIndicator(self):
        """
        Given: DisplayManager is connected
        When: Calibration mode is enabled
        Then: CALIBRATION MODE indicator is shown on display
        """
        manager = CalibrationManager(
            database=self.database,
            displayManager=self.mockDisplay
        )

        manager.enable()

        self.mockDisplay.showAlert.assert_called_once()
        args, kwargs = self.mockDisplay.showAlert.call_args
        self.assertIn('CALIBRATION', kwargs.get('message', ''))
        self.assertEqual(kwargs.get('priority'), 2)  # High priority

    def test_calibrationModeEnabledFromConfig_showsIndicator(self):
        """
        Given: Config with calibration.mode = true and DisplayManager
        When: CalibrationManager is created
        Then: Display is NOT updated (only on explicit enable)
        """
        # Note: We don't show indicator on init from config
        # Only when enable() is explicitly called
        config = {'calibration': {'mode': True}}
        manager = CalibrationManager(
            database=self.database,
            config=config,
            displayManager=self.mockDisplay
        )

        # Indicator not shown on init
        self.mockDisplay.showAlert.assert_not_called()


class TestCalibrationSessionExport(unittest.TestCase):
    """Test exporting calibration session data to CSV/JSON."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        config = {'calibration': {'mode': True}}
        self.manager = CalibrationManager(database=self.database, config=config)
        self.exportDir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        if os.path.exists(self.tempDbFile):
            os.remove(self.tempDbFile)
        walFile = self.tempDbFile + '-wal'
        shmFile = self.tempDbFile + '-shm'
        if os.path.exists(walFile):
            os.remove(walFile)
        if os.path.exists(shmFile):
            os.remove(shmFile)
        if os.path.exists(self.exportDir):
            shutil.rmtree(self.exportDir)

    def test_exportSession_toCsv_createsFile(self):
        """
        Given: Session with readings exists
        When: exportSession() is called with CSV format
        Then: CSV file is created with session data
        """
        session = self.manager.startSession(notes="Export test")
        self.manager.logCalibrationReading("RPM", 2500.0, "rpm")
        self.manager.logCalibrationReading("SPEED", 60.0, "km/h")
        self.manager.endSession()

        result = self.manager.exportSession(
            sessionId=session.sessionId,
            format='csv',
            exportDirectory=self.exportDir
        )

        self.assertTrue(result.success)
        self.assertIsNotNone(result.filePath)
        self.assertTrue(os.path.exists(result.filePath))
        self.assertEqual(result.recordCount, 2)

    def test_exportSession_toCsv_correctContent(self):
        """
        Given: Session with readings exists
        When: exportSession() is called with CSV format
        Then: CSV contains correct headers and data
        """
        import csv

        session = self.manager.startSession(notes="Content test")
        self.manager.logCalibrationReading("RPM", 2500.0, "rpm")
        self.manager.endSession()

        result = self.manager.exportSession(
            sessionId=session.sessionId,
            format='csv',
            exportDirectory=self.exportDir
        )

        with open(result.filePath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Check header
        self.assertEqual(rows[0], ['timestamp', 'parameter_name', 'value', 'unit'])
        # Check data row
        self.assertEqual(rows[1][1], 'RPM')
        self.assertEqual(float(rows[1][2]), 2500.0)
        self.assertEqual(rows[1][3], 'rpm')

    def test_exportSession_toJson_createsFile(self):
        """
        Given: Session with readings exists
        When: exportSession() is called with JSON format
        Then: JSON file is created with session data
        """
        session = self.manager.startSession(notes="JSON export test")
        self.manager.logCalibrationReading("RPM", 2500.0, "rpm")
        self.manager.logCalibrationReading("SPEED", 60.0, "km/h")
        self.manager.endSession()

        result = self.manager.exportSession(
            sessionId=session.sessionId,
            format='json',
            exportDirectory=self.exportDir
        )

        self.assertTrue(result.success)
        self.assertIsNotNone(result.filePath)
        self.assertTrue(os.path.exists(result.filePath))
        self.assertEqual(result.recordCount, 2)

    def test_exportSession_toJson_correctStructure(self):
        """
        Given: Session with readings exists
        When: exportSession() is called with JSON format
        Then: JSON contains metadata and data arrays
        """
        import json

        session = self.manager.startSession(notes="Structure test")
        self.manager.logCalibrationReading("RPM", 2500.0, "rpm")
        self.manager.endSession()

        result = self.manager.exportSession(
            sessionId=session.sessionId,
            format='json',
            exportDirectory=self.exportDir
        )

        with open(result.filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Check metadata
        self.assertIn('metadata', data)
        self.assertIn('session_id', data['metadata'])
        self.assertIn('export_date', data['metadata'])
        self.assertIn('notes', data['metadata'])
        self.assertIn('record_count', data['metadata'])
        self.assertIn('duration_seconds', data['metadata'])

        # Check data array
        self.assertIn('data', data)
        self.assertEqual(len(data['data']), 1)
        self.assertEqual(data['data'][0]['parameter'], 'RPM')

    def test_exportSession_nonExistent_returnsFailed(self):
        """
        Given: Session does not exist
        When: exportSession() is called
        Then: Failed result is returned
        """
        result = self.manager.exportSession(
            sessionId=9999,
            format='csv',
            exportDirectory=self.exportDir
        )

        self.assertFalse(result.success)
        self.assertIsNotNone(result.errorMessage)

    def test_exportSession_filenameFormat(self):
        """
        Given: Session exists
        When: exportSession() is called
        Then: Filename includes session ID and date
        """
        session = self.manager.startSession(notes="Filename test")
        self.manager.endSession()

        result = self.manager.exportSession(
            sessionId=session.sessionId,
            format='csv',
            exportDirectory=self.exportDir
        )

        filename = os.path.basename(result.filePath)
        self.assertIn(f'session_{session.sessionId}', filename)
        self.assertTrue(filename.endswith('.csv'))

    def test_exportSession_customFilename(self):
        """
        Given: Session exists
        When: exportSession() is called with custom filename
        Then: Custom filename is used
        """
        session = self.manager.startSession()
        self.manager.endSession()

        result = self.manager.exportSession(
            sessionId=session.sessionId,
            format='csv',
            exportDirectory=self.exportDir,
            filename='my_custom_export.csv'
        )

        self.assertTrue(result.filePath.endswith('my_custom_export.csv'))


class TestCalibrationSessionDelete(unittest.TestCase):
    """Test deleting calibration sessions."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        config = {'calibration': {'mode': True}}
        self.manager = CalibrationManager(database=self.database, config=config)

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

    def test_deleteSession_existingSession_removesSession(self):
        """
        Given: Session exists
        When: deleteSession() is called
        Then: Session is removed from database
        """
        session = self.manager.startSession(notes="Delete me")
        sessionId = session.sessionId
        self.manager.endSession()

        result = self.manager.deleteSession(sessionId)

        self.assertTrue(result)
        self.assertIsNone(self.manager.getSession(sessionId))

    def test_deleteSession_cascadesDeleteReadings(self):
        """
        Given: Session with readings exists
        When: deleteSession() is called
        Then: Session and all readings are deleted
        """
        session = self.manager.startSession()
        sessionId = session.sessionId
        self.manager.logCalibrationReading("RPM", 2500.0, "rpm")
        self.manager.logCalibrationReading("SPEED", 60.0, "km/h")
        self.manager.endSession()

        self.manager.deleteSession(sessionId)

        # Verify readings are deleted
        with self.database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM calibration_data WHERE session_id = ?",
                (sessionId,)
            )
            count = cursor.fetchone()[0]

        self.assertEqual(count, 0)

    def test_deleteSession_nonExistent_returnsFalse(self):
        """
        Given: Session does not exist
        When: deleteSession() is called
        Then: False is returned
        """
        result = self.manager.deleteSession(9999)

        self.assertFalse(result)

    def test_deleteSession_activeSession_raisesError(self):
        """
        Given: Active session (not ended)
        When: deleteSession() is called
        Then: CalibrationSessionError is raised
        """
        session = self.manager.startSession()
        # Don't end session

        with self.assertRaises(CalibrationSessionError) as ctx:
            self.manager.deleteSession(session.sessionId)

        self.assertIn("active", str(ctx.exception).lower())

    def test_deleteSession_allowsForceDeleteActive(self):
        """
        Given: Active session
        When: deleteSession(force=True) is called
        Then: Session is deleted anyway
        """
        session = self.manager.startSession()
        sessionId = session.sessionId
        # Don't end session

        result = self.manager.deleteSession(sessionId, force=True)

        self.assertTrue(result)
        self.assertIsNone(self.manager.getSession(sessionId))
        self.assertIsNone(self.manager.currentSession)

    def test_deleteSession_multipleExists_deletesOnlySpecified(self):
        """
        Given: Multiple sessions exist
        When: deleteSession() is called for one
        Then: Only that session is deleted
        """
        session1 = self.manager.startSession(notes="Session 1")
        self.manager.endSession()
        session2 = self.manager.startSession(notes="Session 2")
        self.manager.endSession()
        session3 = self.manager.startSession(notes="Session 3")
        self.manager.endSession()

        self.manager.deleteSession(session2.sessionId)

        # session1 and session3 should still exist
        self.assertIsNotNone(self.manager.getSession(session1.sessionId))
        self.assertIsNone(self.manager.getSession(session2.sessionId))
        self.assertIsNotNone(self.manager.getSession(session3.sessionId))


class TestCalibrationSessionExportHelper(unittest.TestCase):
    """Test helper function for exporting calibration sessions."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempDbFile = tempfile.mktemp(suffix='.db')
        self.database = ObdDatabase(self.tempDbFile)
        self.database.initialize()
        self.exportDir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        if os.path.exists(self.tempDbFile):
            os.remove(self.tempDbFile)
        walFile = self.tempDbFile + '-wal'
        shmFile = self.tempDbFile + '-shm'
        if os.path.exists(walFile):
            os.remove(walFile)
        if os.path.exists(shmFile):
            os.remove(shmFile)
        if os.path.exists(self.exportDir):
            shutil.rmtree(self.exportDir)

    def test_exportCalibrationSession_helperFunction(self):
        """
        Given: Session exists
        When: exportCalibrationSession() helper is called
        Then: Session is exported successfully
        """
        from obd.calibration_manager import exportCalibrationSession

        config = {'calibration': {'mode': True}}
        manager = CalibrationManager(database=self.database, config=config)
        session = manager.startSession()
        manager.logCalibrationReading("RPM", 2500.0, "rpm")
        manager.endSession()

        result = exportCalibrationSession(
            database=self.database,
            sessionId=session.sessionId,
            format='csv',
            exportDirectory=self.exportDir
        )

        self.assertTrue(result.success)
        self.assertTrue(os.path.exists(result.filePath))


if __name__ == '__main__':
    # Run tests
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
