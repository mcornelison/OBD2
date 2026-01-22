################################################################################
# File Name: run_tests_profile_switcher.py
# Purpose/Description: Unit tests for ProfileSwitcher module
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial test suite for US-025
# ================================================================================
################################################################################

"""
Comprehensive test suite for the ProfileSwitcher module.

Tests cover:
- Profile switching when not driving (immediate activation)
- Profile switching while driving (pending until drive start)
- Config initialization
- Profile change logging to database
- Display integration
- Callback handling
- Error cases (profile not found, etc.)

Run with: python tests/run_tests_profile_switcher.py
"""

import os
import sys
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch, call

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.profile_switcher import (
    ProfileSwitcher,
    ProfileChangeEvent,
    SwitcherState,
    ProfileSwitchError,
    ProfileNotFoundError,
    ProfileSwitchPendingError,
    createProfileSwitcherFromConfig,
    getActiveProfileIdFromConfig,
    getAvailableProfilesFromConfig,
    isProfileInConfig,
    PROFILE_SWITCH_REQUESTED,
    PROFILE_SWITCH_ACTIVATED,
)


# ================================================================================
# Test Fixtures
# ================================================================================

def createMockDatabase():
    """Create a mock database with profile tables."""
    # Create temp database file
    dbFile = tempfile.mktemp(suffix='.db')
    conn = sqlite3.connect(dbFile)
    conn.row_factory = sqlite3.Row

    # Create required tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            alert_config_json TEXT,
            polling_interval_ms INTEGER DEFAULT 1000,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS connection_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP NOT NULL,
            event_type TEXT NOT NULL,
            mac_address TEXT,
            success INTEGER,
            error_message TEXT
        )
    """)

    # Insert test profiles
    conn.execute(
        "INSERT INTO profiles (id, name, description) VALUES (?, ?, ?)",
        ('daily', 'Daily', 'Normal daily driving')
    )
    conn.execute(
        "INSERT INTO profiles (id, name, description) VALUES (?, ?, ?)",
        ('performance', 'Performance', 'Track day profile')
    )
    conn.commit()
    conn.close()

    # Create mock database object
    mockDb = MagicMock()

    def connectFn():
        conn = sqlite3.connect(dbFile)
        conn.row_factory = sqlite3.Row
        return conn

    mockDb.connect.return_value.__enter__ = lambda s: connectFn()
    mockDb.connect.return_value.__exit__ = lambda s, *args: None
    mockDb._dbFile = dbFile

    return mockDb


def createMockProfileManager():
    """Create a mock profile manager."""
    mockManager = MagicMock()
    mockManager.profileExists.return_value = True

    # Mock profile objects
    dailyProfile = MagicMock()
    dailyProfile.id = 'daily'
    dailyProfile.name = 'Daily'

    performanceProfile = MagicMock()
    performanceProfile.id = 'performance'
    performanceProfile.name = 'Performance'

    def getProfileFn(profileId):
        if profileId == 'daily':
            return dailyProfile
        elif profileId == 'performance':
            return performanceProfile
        return None

    mockManager.getProfile.side_effect = getProfileFn

    return mockManager


def createMockDriveDetector(isDriving=False):
    """Create a mock drive detector."""
    mockDetector = MagicMock()
    mockDetector.isDriving.return_value = isDriving
    mockDetector.setProfileId = MagicMock()
    return mockDetector


def createMockDisplayManager():
    """Create a mock display manager."""
    return MagicMock()


def createTestConfig():
    """Create a test configuration dictionary."""
    return {
        'profiles': {
            'activeProfile': 'daily',
            'availableProfiles': [
                {
                    'id': 'daily',
                    'name': 'Daily',
                    'description': 'Normal daily driving',
                    'pollingIntervalMs': 1000,
                },
                {
                    'id': 'performance',
                    'name': 'Performance',
                    'description': 'Track day profile',
                    'pollingIntervalMs': 500,
                },
            ]
        }
    }


# ================================================================================
# Test Cases
# ================================================================================

class TestProfileSwitcherInit(unittest.TestCase):
    """Test ProfileSwitcher initialization."""

    def test_init_withNoDependencies_createsInstance(self):
        """
        Given: No dependencies provided
        When: ProfileSwitcher is created
        Then: Instance is created with default state
        """
        switcher = ProfileSwitcher()

        self.assertIsNone(switcher.getActiveProfileId())
        self.assertIsNone(switcher.getPendingProfileId())
        self.assertFalse(switcher.hasPendingSwitch())

    def test_init_withDependencies_storesDependencies(self):
        """
        Given: Dependencies provided
        When: ProfileSwitcher is created
        Then: Dependencies are stored and accessible
        """
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector()
        mockDisplay = createMockDisplayManager()

        switcher = ProfileSwitcher(
            profileManager=mockManager,
            driveDetector=mockDetector,
            displayManager=mockDisplay
        )

        self.assertIsNotNone(switcher._profileManager)
        self.assertIsNotNone(switcher._driveDetector)
        self.assertIsNotNone(switcher._displayManager)


class TestProfileSwitcherConfig(unittest.TestCase):
    """Test ProfileSwitcher configuration initialization."""

    def test_initializeFromConfig_validConfig_setsActiveProfile(self):
        """
        Given: Valid config with activeProfile
        When: initializeFromConfig is called
        Then: Active profile is set
        """
        config = createTestConfig()
        mockManager = createMockProfileManager()

        switcher = ProfileSwitcher(profileManager=mockManager)
        result = switcher.initializeFromConfig(config)

        self.assertTrue(result)
        self.assertEqual(switcher.getActiveProfileId(), 'daily')

    def test_initializeFromConfig_noActiveProfile_returnsFalse(self):
        """
        Given: Config without activeProfile
        When: initializeFromConfig is called
        Then: Returns False
        """
        config = {'profiles': {}}
        switcher = ProfileSwitcher()

        result = switcher.initializeFromConfig(config)

        self.assertFalse(result)

    def test_initializeFromConfig_profileNotFound_returnsFalse(self):
        """
        Given: Config with non-existent activeProfile
        When: initializeFromConfig is called
        Then: Returns False
        """
        config = {'profiles': {'activeProfile': 'nonexistent'}}
        mockManager = createMockProfileManager()
        mockManager.profileExists.return_value = False

        switcher = ProfileSwitcher(profileManager=mockManager)
        result = switcher.initializeFromConfig(config)

        self.assertFalse(result)

    def test_initializeFromConfig_updatesProfileManager(self):
        """
        Given: ProfileManager is connected
        When: initializeFromConfig is called
        Then: ProfileManager's active profile is updated
        """
        config = createTestConfig()
        mockManager = createMockProfileManager()

        switcher = ProfileSwitcher(profileManager=mockManager)
        switcher.initializeFromConfig(config)

        mockManager.setActiveProfile.assert_called_once_with('daily')


class TestProfileSwitchingNotDriving(unittest.TestCase):
    """Test profile switching when not driving (immediate switch)."""

    def test_requestProfileSwitch_notDriving_switchesImmediately(self):
        """
        Given: Not currently driving
        When: Profile switch is requested
        Then: Switch happens immediately
        """
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector(isDriving=False)

        switcher = ProfileSwitcher(
            profileManager=mockManager,
            driveDetector=mockDetector
        )
        switcher._state.activeProfileId = 'daily'

        result = switcher.requestProfileSwitch('performance')

        self.assertTrue(result)
        self.assertEqual(switcher.getActiveProfileId(), 'performance')
        self.assertIsNone(switcher.getPendingProfileId())

    def test_requestProfileSwitch_notDriving_updatesDriveDetector(self):
        """
        Given: Not driving and drive detector is connected
        When: Profile switch is requested
        Then: Drive detector's profile ID is updated
        """
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector(isDriving=False)

        switcher = ProfileSwitcher(
            profileManager=mockManager,
            driveDetector=mockDetector
        )
        switcher._state.activeProfileId = 'daily'

        switcher.requestProfileSwitch('performance')

        mockDetector.setProfileId.assert_called_once_with('performance')

    def test_requestProfileSwitch_sameProfile_returnsTrue(self):
        """
        Given: Profile is already active
        When: Switch to same profile is requested
        Then: Returns True without changes
        """
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector(isDriving=False)

        switcher = ProfileSwitcher(
            profileManager=mockManager,
            driveDetector=mockDetector
        )
        switcher._state.activeProfileId = 'daily'

        result = switcher.requestProfileSwitch('daily')

        self.assertTrue(result)
        self.assertEqual(switcher.getActiveProfileId(), 'daily')

    def test_requestProfileSwitch_profileNotFound_raisesError(self):
        """
        Given: Requested profile doesn't exist
        When: Profile switch is requested
        Then: ProfileNotFoundError is raised
        """
        mockManager = createMockProfileManager()
        mockManager.profileExists.return_value = False

        switcher = ProfileSwitcher(profileManager=mockManager)
        switcher._state.activeProfileId = 'daily'

        with self.assertRaises(ProfileNotFoundError) as ctx:
            switcher.requestProfileSwitch('nonexistent')

        self.assertIn('nonexistent', str(ctx.exception))


class TestProfileSwitchingWhileDriving(unittest.TestCase):
    """Test profile switching while driving (pending until drive start)."""

    def test_requestProfileSwitch_whileDriving_queuesPending(self):
        """
        Given: Currently driving
        When: Profile switch is requested
        Then: Switch is queued as pending
        """
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector(isDriving=True)

        switcher = ProfileSwitcher(
            profileManager=mockManager,
            driveDetector=mockDetector
        )
        switcher._state.activeProfileId = 'daily'

        result = switcher.requestProfileSwitch('performance')

        self.assertTrue(result)
        self.assertEqual(switcher.getActiveProfileId(), 'daily')  # Not changed
        self.assertEqual(switcher.getPendingProfileId(), 'performance')
        self.assertTrue(switcher.hasPendingSwitch())

    def test_requestProfileSwitch_whileDriving_samePending_returnsTrue(self):
        """
        Given: Currently driving with pending switch
        When: Same profile switch is requested again
        Then: Returns True without duplicate queue
        """
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector(isDriving=True)

        switcher = ProfileSwitcher(
            profileManager=mockManager,
            driveDetector=mockDetector
        )
        switcher._state.activeProfileId = 'daily'
        switcher._state.pendingProfileId = 'performance'

        result = switcher.requestProfileSwitch('performance')

        self.assertTrue(result)

    def test_pendingSwitchActivates_onDriveStart(self):
        """
        Given: Pending profile switch
        When: Drive starts
        Then: Pending switch is activated
        """
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector(isDriving=False)

        switcher = ProfileSwitcher(
            profileManager=mockManager,
            driveDetector=mockDetector
        )
        switcher._state.activeProfileId = 'daily'
        switcher._state.pendingProfileId = 'performance'

        # Simulate drive start callback
        mockDriveSession = MagicMock()
        switcher._onDriveStart(mockDriveSession)

        self.assertEqual(switcher.getActiveProfileId(), 'performance')
        self.assertIsNone(switcher.getPendingProfileId())
        self.assertFalse(switcher.hasPendingSwitch())

    def test_cancelPendingSwitch_removesPending(self):
        """
        Given: Pending profile switch
        When: Cancel is called
        Then: Pending switch is removed
        """
        switcher = ProfileSwitcher()
        switcher._state.pendingProfileId = 'performance'

        result = switcher.cancelPendingSwitch()

        self.assertTrue(result)
        self.assertIsNone(switcher.getPendingProfileId())

    def test_cancelPendingSwitch_noPending_returnsFalse(self):
        """
        Given: No pending switch
        When: Cancel is called
        Then: Returns False
        """
        switcher = ProfileSwitcher()

        result = switcher.cancelPendingSwitch()

        self.assertFalse(result)


class TestDatabaseLogging(unittest.TestCase):
    """Test profile change logging to database."""

    def setUp(self):
        """Set up test fixtures."""
        self.dbFile = tempfile.mktemp(suffix='.db')
        self.conn = sqlite3.connect(self.dbFile)
        self.conn.execute("""
            CREATE TABLE connection_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP,
                event_type TEXT,
                mac_address TEXT,
                success INTEGER,
                error_message TEXT
            )
        """)
        self.conn.commit()

    def tearDown(self):
        """Clean up test fixtures."""
        self.conn.close()
        try:
            if os.path.exists(self.dbFile):
                os.remove(self.dbFile)
        except PermissionError:
            pass  # Windows file locking, will be cleaned up later

    def _createRealDatabase(self):
        """Create a real database wrapper for tests."""
        dbFile = self.dbFile

        class RealDatabase:
            def connect(self):
                return _DbConnection(dbFile)

        class _DbConnection:
            def __init__(self, path):
                self.path = path
                self._conn = None

            def __enter__(self):
                self._conn = sqlite3.connect(self.path)
                self._conn.row_factory = sqlite3.Row
                return self._conn

            def __exit__(self, exc_type, exc_val, exc_tb):
                if self._conn:
                    self._conn.commit()
                    self._conn.close()
                return False

        return RealDatabase()

    def test_profileSwitch_logsToDatabase(self):
        """
        Given: Database is connected
        When: Profile switch is executed
        Then: Change is logged to database
        """
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector(isDriving=False)
        realDb = self._createRealDatabase()

        switcher = ProfileSwitcher(
            profileManager=mockManager,
            driveDetector=mockDetector,
            database=realDb
        )
        switcher._state.activeProfileId = 'daily'

        switcher.requestProfileSwitch('performance')

        # Check database
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM connection_log")
        rows = cursor.fetchall()

        self.assertEqual(len(rows), 1)
        self.assertIn('profile_switch_activated', rows[0][2])

    def test_pendingSwitch_logsRequestToDatabase(self):
        """
        Given: Database is connected and currently driving
        When: Profile switch is requested
        Then: Request is logged to database
        """
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector(isDriving=True)
        realDb = self._createRealDatabase()

        switcher = ProfileSwitcher(
            profileManager=mockManager,
            driveDetector=mockDetector,
            database=realDb
        )
        switcher._state.activeProfileId = 'daily'

        switcher.requestProfileSwitch('performance')

        # Check database
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM connection_log")
        rows = cursor.fetchall()

        self.assertEqual(len(rows), 1)
        self.assertIn('profile_switch_requested', rows[0][2])


class TestCallbacks(unittest.TestCase):
    """Test callback handling."""

    def test_onProfileChange_calledOnSwitch(self):
        """
        Given: Profile change callback registered
        When: Profile is switched
        Then: Callback is called with old and new profile IDs
        """
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector(isDriving=False)
        callbackMock = MagicMock()

        switcher = ProfileSwitcher(
            profileManager=mockManager,
            driveDetector=mockDetector
        )
        switcher._state.activeProfileId = 'daily'
        switcher.onProfileChange(callbackMock)

        switcher.requestProfileSwitch('performance')

        callbackMock.assert_called_once_with('daily', 'performance')

    def test_onPendingSwitch_calledWhenQueued(self):
        """
        Given: Pending switch callback registered
        When: Profile switch is queued (driving)
        Then: Callback is called with pending profile ID
        """
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector(isDriving=True)
        callbackMock = MagicMock()

        switcher = ProfileSwitcher(
            profileManager=mockManager,
            driveDetector=mockDetector
        )
        switcher._state.activeProfileId = 'daily'
        switcher.onPendingSwitch(callbackMock)

        switcher.requestProfileSwitch('performance')

        callbackMock.assert_called_once_with('performance')

    def test_callbackError_doesNotStopSwitch(self):
        """
        Given: Callback that raises exception
        When: Profile is switched
        Then: Switch still completes
        """
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector(isDriving=False)

        def failingCallback(old, new):
            raise Exception("Callback failed")

        switcher = ProfileSwitcher(
            profileManager=mockManager,
            driveDetector=mockDetector
        )
        switcher._state.activeProfileId = 'daily'
        switcher.onProfileChange(failingCallback)

        result = switcher.requestProfileSwitch('performance')

        self.assertTrue(result)
        self.assertEqual(switcher.getActiveProfileId(), 'performance')


class TestState(unittest.TestCase):
    """Test state tracking."""

    def test_getState_returnsCurrentState(self):
        """
        Given: ProfileSwitcher with active profile
        When: getState is called
        Then: Returns correct state
        """
        switcher = ProfileSwitcher()
        switcher._state.activeProfileId = 'daily'
        switcher._state.pendingProfileId = 'performance'
        switcher._state.isDriving = True
        switcher._state.changeCount = 5

        state = switcher.getState()

        self.assertEqual(state.activeProfileId, 'daily')
        self.assertEqual(state.pendingProfileId, 'performance')
        self.assertTrue(state.isDriving)
        self.assertEqual(state.changeCount, 5)

    def test_getChangeHistory_returnsRecentChanges(self):
        """
        Given: ProfileSwitcher with change history
        When: getChangeHistory is called
        Then: Returns recent changes (most recent first)
        """
        switcher = ProfileSwitcher()

        # Add some events
        event1 = ProfileChangeEvent(
            timestamp=datetime.now(),
            oldProfileId='daily',
            newProfileId='performance',
            eventType=PROFILE_SWITCH_ACTIVATED,
        )
        event2 = ProfileChangeEvent(
            timestamp=datetime.now(),
            oldProfileId='performance',
            newProfileId='daily',
            eventType=PROFILE_SWITCH_ACTIVATED,
        )
        switcher._changeHistory.append(event1)
        switcher._changeHistory.append(event2)

        history = switcher.getChangeHistory(limit=10)

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].newProfileId, 'daily')  # Most recent first
        self.assertEqual(history[1].newProfileId, 'performance')

    def test_getActiveProfile_returnsProfileObject(self):
        """
        Given: ProfileManager is connected
        When: getActiveProfile is called
        Then: Returns Profile object
        """
        mockManager = createMockProfileManager()

        switcher = ProfileSwitcher(profileManager=mockManager)
        switcher._state.activeProfileId = 'daily'

        profile = switcher.getActiveProfile()

        self.assertIsNotNone(profile)
        self.assertEqual(profile.id, 'daily')


class TestDriveDetectorIntegration(unittest.TestCase):
    """Test drive detector integration."""

    def test_driveDetector_registersCallbacks(self):
        """
        Given: DriveDetector is provided
        When: ProfileSwitcher is created
        Then: Callbacks are registered with drive detector
        """
        mockDetector = createMockDriveDetector()

        switcher = ProfileSwitcher(driveDetector=mockDetector)

        mockDetector.registerCallbacks.assert_called_once()

    def test_onDriveEnd_updatesIsDrivingState(self):
        """
        Given: ProfileSwitcher with isDriving=True
        When: Drive ends
        Then: isDriving is set to False
        """
        switcher = ProfileSwitcher()
        switcher._state.isDriving = True

        mockSession = MagicMock()
        switcher._onDriveEnd(mockSession)

        self.assertFalse(switcher._state.isDriving)


class TestDataClasses(unittest.TestCase):
    """Test data class functionality."""

    def test_profileChangeEvent_toDict(self):
        """
        Given: ProfileChangeEvent instance
        When: toDict is called
        Then: Returns dictionary representation
        """
        event = ProfileChangeEvent(
            timestamp=datetime(2026, 1, 22, 12, 0, 0),
            oldProfileId='daily',
            newProfileId='performance',
            eventType=PROFILE_SWITCH_ACTIVATED,
            triggeredBy='api',
            success=True,
        )

        result = event.toDict()

        self.assertEqual(result['oldProfileId'], 'daily')
        self.assertEqual(result['newProfileId'], 'performance')
        self.assertEqual(result['eventType'], PROFILE_SWITCH_ACTIVATED)
        self.assertTrue(result['success'])

    def test_switcherState_toDict(self):
        """
        Given: SwitcherState instance
        When: toDict is called
        Then: Returns dictionary representation
        """
        state = SwitcherState(
            activeProfileId='daily',
            pendingProfileId='performance',
            isDriving=True,
            changeCount=5
        )

        result = state.toDict()

        self.assertEqual(result['activeProfileId'], 'daily')
        self.assertEqual(result['pendingProfileId'], 'performance')
        self.assertTrue(result['isDriving'])
        self.assertEqual(result['changeCount'], 5)


class TestHelperFunctions(unittest.TestCase):
    """Test helper functions."""

    def test_getActiveProfileIdFromConfig_returnsId(self):
        """
        Given: Config with activeProfile
        When: getActiveProfileIdFromConfig is called
        Then: Returns profile ID
        """
        config = createTestConfig()

        result = getActiveProfileIdFromConfig(config)

        self.assertEqual(result, 'daily')

    def test_getActiveProfileIdFromConfig_noProfile_returnsNone(self):
        """
        Given: Config without activeProfile
        When: getActiveProfileIdFromConfig is called
        Then: Returns None
        """
        config = {}

        result = getActiveProfileIdFromConfig(config)

        self.assertIsNone(result)

    def test_getAvailableProfilesFromConfig_returnsList(self):
        """
        Given: Config with availableProfiles
        When: getAvailableProfilesFromConfig is called
        Then: Returns list of profiles
        """
        config = createTestConfig()

        result = getAvailableProfilesFromConfig(config)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['id'], 'daily')

    def test_isProfileInConfig_existingProfile_returnsTrue(self):
        """
        Given: Config with profile
        When: isProfileInConfig is called with existing profile
        Then: Returns True
        """
        config = createTestConfig()

        result = isProfileInConfig(config, 'daily')

        self.assertTrue(result)

    def test_isProfileInConfig_nonexistentProfile_returnsFalse(self):
        """
        Given: Config without profile
        When: isProfileInConfig is called with non-existent profile
        Then: Returns False
        """
        config = createTestConfig()

        result = isProfileInConfig(config, 'nonexistent')

        self.assertFalse(result)

    def test_createProfileSwitcherFromConfig_createsSwitcher(self):
        """
        Given: Valid config
        When: createProfileSwitcherFromConfig is called
        Then: Returns configured ProfileSwitcher
        """
        config = createTestConfig()
        mockManager = createMockProfileManager()

        switcher = createProfileSwitcherFromConfig(
            config,
            profileManager=mockManager
        )

        self.assertEqual(switcher.getActiveProfileId(), 'daily')


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_setDependencies_afterCreation(self):
        """
        Given: ProfileSwitcher created without dependencies
        When: Dependencies are set later
        Then: They are properly stored
        """
        switcher = ProfileSwitcher()
        mockManager = createMockProfileManager()
        mockDetector = createMockDriveDetector()
        mockDisplay = createMockDisplayManager()

        switcher.setProfileManager(mockManager)
        switcher.setDriveDetector(mockDetector)
        switcher.setDisplayManager(mockDisplay)

        self.assertIsNotNone(switcher._profileManager)
        self.assertIsNotNone(switcher._driveDetector)
        self.assertIsNotNone(switcher._displayManager)

    def test_switch_withoutProfileManager_assumesProfileExists(self):
        """
        Given: No profile manager
        When: Profile switch is requested
        Then: Switch proceeds (assumes profile exists)
        """
        switcher = ProfileSwitcher()
        switcher._state.activeProfileId = 'daily'

        result = switcher.requestProfileSwitch('performance')

        self.assertTrue(result)
        self.assertEqual(switcher.getActiveProfileId(), 'performance')

    def test_switch_withoutDriveDetector_switchesImmediately(self):
        """
        Given: No drive detector
        When: Profile switch is requested
        Then: Switch happens immediately (can't detect driving state)
        """
        switcher = ProfileSwitcher()
        switcher._state.activeProfileId = 'daily'

        result = switcher.requestProfileSwitch('performance')

        self.assertTrue(result)
        self.assertEqual(switcher.getActiveProfileId(), 'performance')

    def test_multipleCallbacks_allCalled(self):
        """
        Given: Multiple callbacks registered
        When: Profile is switched
        Then: All callbacks are called
        """
        mockDetector = createMockDriveDetector(isDriving=False)
        callback1 = MagicMock()
        callback2 = MagicMock()

        switcher = ProfileSwitcher(driveDetector=mockDetector)
        switcher._state.activeProfileId = 'daily'
        switcher.onProfileChange(callback1)
        switcher.onProfileChange(callback2)

        switcher.requestProfileSwitch('performance')

        callback1.assert_called_once()
        callback2.assert_called_once()


# ================================================================================
# Test Runner
# ================================================================================

def runTests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestProfileSwitcherInit))
    suite.addTests(loader.loadTestsFromTestCase(TestProfileSwitcherConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestProfileSwitchingNotDriving))
    suite.addTests(loader.loadTestsFromTestCase(TestProfileSwitchingWhileDriving))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseLogging))
    suite.addTests(loader.loadTestsFromTestCase(TestCallbacks))
    suite.addTests(loader.loadTestsFromTestCase(TestState))
    suite.addTests(loader.loadTestsFromTestCase(TestDriveDetectorIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestDataClasses))
    suite.addTests(loader.loadTestsFromTestCase(TestHelperFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.wasSuccessful():
        print("\nAll tests passed!")
        return 0
    else:
        print("\nSome tests failed!")
        for test, traceback in result.failures + result.errors:
            print(f"\nFailed: {test}")
            print(traceback)
        return 1


if __name__ == '__main__':
    sys.exit(runTests())
