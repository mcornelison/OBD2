#!/usr/bin/env python3
################################################################################
# File Name: run_tests_profile_manager.py
# Purpose/Description: Manual test runner for profile manager module tests
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-024
# ================================================================================
################################################################################

"""
Manual test runner for profile manager module tests.

Run with:
    python tests/run_tests_profile_manager.py
"""

import json
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

# Add src to path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from obd.database import ObdDatabase
from obd.profile_manager import (
    Profile,
    ProfileManager,
    ProfileError,
    ProfileNotFoundError,
    ProfileValidationError,
    createProfileManagerFromConfig,
    getDefaultProfile,
    DEFAULT_PROFILE_ID,
    DEFAULT_PROFILE_NAME,
)


class TestRunner:
    """Simple test runner for manual execution."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def runTest(self, testName: str, testFunc):
        """Run a single test and track results."""
        try:
            testFunc()
            self.passed += 1
            print(f"  [PASS] {testName}")
        except AssertionError as e:
            self.failed += 1
            self.errors.append((testName, str(e)))
            print(f"  [FAIL] {testName}: {e}")
        except Exception as e:
            self.failed += 1
            self.errors.append((testName, f"Error: {e}"))
            print(f"  [ERROR] {testName}: {e}")
            traceback.print_exc()

    def report(self):
        """Print final test report."""
        total = self.passed + self.failed
        print(f"\n{'=' * 60}")
        print(f"Results: {self.passed} passed, {self.failed} failed, {total} total")
        if self.errors:
            print("\nFailures:")
            for name, error in self.errors:
                print(f"  - {name}: {error}")
        return self.failed == 0


def getTempDbPath():
    """Get a temporary database path."""
    return tempfile.mktemp(suffix='.db')


def getTestDatabase():
    """Get an initialized test database."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()
    return db


def getSampleConfig():
    """Get a sample configuration."""
    return {
        'profiles': {
            'activeProfile': 'daily',
            'availableProfiles': [
                {
                    'id': 'daily',
                    'name': 'Daily',
                    'description': 'Normal daily driving profile',
                    'alertThresholds': {
                        'rpmRedline': 6500,
                        'coolantTempCritical': 110,
                        'oilPressureLow': 20
                    },
                    'pollingIntervalMs': 1000
                },
                {
                    'id': 'performance',
                    'name': 'Performance',
                    'description': 'Track day / spirited driving profile',
                    'alertThresholds': {
                        'rpmRedline': 7200,
                        'coolantTempCritical': 115,
                        'oilPressureLow': 25,
                        'boostPressureMax': 18
                    },
                    'pollingIntervalMs': 500
                }
            ]
        }
    }


# ================================================================================
# Profile Dataclass Tests
# ================================================================================

def test_profile_init_requiredFields():
    """Test Profile requires id and name."""
    profile = Profile(id='test', name='Test Profile')
    assert profile.id == 'test'
    assert profile.name == 'Test Profile'


def test_profile_init_defaultValues():
    """Test Profile default values."""
    profile = Profile(id='test', name='Test')
    assert profile.description is None
    assert profile.alertThresholds == {}
    assert profile.pollingIntervalMs == 1000
    assert profile.createdAt is None
    assert profile.updatedAt is None


def test_profile_init_customValues():
    """Test Profile with custom values."""
    thresholds = {'rpmRedline': 6500}
    profile = Profile(
        id='custom',
        name='Custom Profile',
        description='A custom profile',
        alertThresholds=thresholds,
        pollingIntervalMs=500
    )
    assert profile.id == 'custom'
    assert profile.name == 'Custom Profile'
    assert profile.description == 'A custom profile'
    assert profile.alertThresholds == thresholds
    assert profile.pollingIntervalMs == 500


def test_profile_toDict():
    """Test Profile toDict method."""
    profile = Profile(
        id='test',
        name='Test',
        description='Test desc',
        alertThresholds={'key': 1},
        pollingIntervalMs=500
    )
    result = profile.toDict()
    assert result['id'] == 'test'
    assert result['name'] == 'Test'
    assert result['description'] == 'Test desc'
    assert result['alertThresholds'] == {'key': 1}
    assert result['pollingIntervalMs'] == 500


def test_profile_fromDict():
    """Test Profile fromDict method."""
    data = {
        'id': 'test',
        'name': 'Test',
        'description': 'Test desc',
        'alertThresholds': {'key': 1},
        'pollingIntervalMs': 500
    }
    profile = Profile.fromDict(data)
    assert profile.id == 'test'
    assert profile.name == 'Test'
    assert profile.description == 'Test desc'
    assert profile.alertThresholds == {'key': 1}
    assert profile.pollingIntervalMs == 500


def test_profile_fromDict_minimalData():
    """Test Profile fromDict with minimal data."""
    data = {'id': 'test', 'name': 'Test'}
    profile = Profile.fromDict(data)
    assert profile.id == 'test'
    assert profile.name == 'Test'
    assert profile.alertThresholds == {}


def test_profile_fromConfigDict():
    """Test Profile fromConfigDict method."""
    configProfile = {
        'id': 'daily',
        'name': 'Daily',
        'description': 'Daily driving',
        'alertThresholds': {'rpmRedline': 6500},
        'pollingIntervalMs': 1000
    }
    profile = Profile.fromConfigDict(configProfile)
    assert profile.id == 'daily'
    assert profile.name == 'Daily'
    assert profile.alertThresholds == {'rpmRedline': 6500}


def test_profile_alertConfigJson():
    """Test Profile alert config JSON serialization."""
    thresholds = {'rpmRedline': 6500, 'coolantTempCritical': 110}
    profile = Profile(id='test', name='Test', alertThresholds=thresholds)
    jsonStr = profile.getAlertConfigJson()
    parsed = json.loads(jsonStr)
    assert parsed == thresholds


def test_profile_alertConfigJson_empty():
    """Test Profile alert config JSON with empty thresholds."""
    profile = Profile(id='test', name='Test')
    jsonStr = profile.getAlertConfigJson()
    assert jsonStr == '{}'


# ================================================================================
# ProfileError Tests
# ================================================================================

def test_profileError_init():
    """Test ProfileError initialization."""
    error = ProfileError("Test error", details={'key': 'value'})
    assert str(error) == "Test error"
    assert error.message == "Test error"
    assert error.details == {'key': 'value'}


def test_profileNotFoundError_inherits():
    """Test ProfileNotFoundError inherits from ProfileError."""
    error = ProfileNotFoundError("Not found", details={'id': 'test'})
    assert isinstance(error, ProfileError)


def test_profileValidationError_hasInvalidFields():
    """Test ProfileValidationError includes invalid fields."""
    error = ProfileValidationError(
        "Validation failed",
        invalidFields=['id', 'name']
    )
    assert error.invalidFields == ['id', 'name']


# ================================================================================
# ProfileManager Initialization Tests
# ================================================================================

def test_profileManager_init_withDatabase():
    """Test ProfileManager initializes with database."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)
    assert manager._database is db


def test_profileManager_init_withoutDatabase():
    """Test ProfileManager initializes without database."""
    manager = ProfileManager()
    assert manager._database is None


def test_profileManager_setDatabase():
    """Test ProfileManager setDatabase method."""
    manager = ProfileManager()
    db = getTestDatabase()
    manager.setDatabase(db)
    assert manager._database is db


# ================================================================================
# ProfileManager CRUD Tests
# ================================================================================

def test_profileManager_createProfile_success():
    """Test ProfileManager creates profile successfully."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    profile = Profile(id='test', name='Test Profile', description='Test')
    manager.createProfile(profile)

    # Verify in database
    retrieved = manager.getProfile('test')
    assert retrieved is not None
    assert retrieved.id == 'test'
    assert retrieved.name == 'Test Profile'


def test_profileManager_createProfile_withThresholds():
    """Test ProfileManager creates profile with alert thresholds."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    thresholds = {'rpmRedline': 6500, 'coolantTempCritical': 110}
    profile = Profile(id='test', name='Test', alertThresholds=thresholds)
    manager.createProfile(profile)

    retrieved = manager.getProfile('test')
    assert retrieved.alertThresholds == thresholds


def test_profileManager_createProfile_duplicate():
    """Test ProfileManager raises error for duplicate profile."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    profile = Profile(id='test', name='Test')
    manager.createProfile(profile)

    try:
        manager.createProfile(profile)
        assert False, "Should have raised ProfileError"
    except ProfileError as e:
        assert 'already exists' in str(e).lower() or 'duplicate' in str(e).lower()


def test_profileManager_createProfile_invalidId():
    """Test ProfileManager validates profile ID."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    try:
        profile = Profile(id='', name='Test')
        manager.createProfile(profile)
        assert False, "Should have raised ProfileValidationError"
    except ProfileValidationError as e:
        assert 'id' in e.invalidFields


def test_profileManager_createProfile_invalidName():
    """Test ProfileManager validates profile name."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    try:
        profile = Profile(id='test', name='')
        manager.createProfile(profile)
        assert False, "Should have raised ProfileValidationError"
    except ProfileValidationError as e:
        assert 'name' in e.invalidFields


def test_profileManager_getProfile_exists():
    """Test ProfileManager retrieves existing profile."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    profile = Profile(id='test', name='Test', pollingIntervalMs=500)
    manager.createProfile(profile)

    retrieved = manager.getProfile('test')
    assert retrieved is not None
    assert retrieved.id == 'test'
    assert retrieved.pollingIntervalMs == 500


def test_profileManager_getProfile_notFound():
    """Test ProfileManager returns None for non-existent profile."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    retrieved = manager.getProfile('nonexistent')
    assert retrieved is None


def test_profileManager_getAllProfiles_empty():
    """Test ProfileManager returns empty list when no profiles."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    profiles = manager.getAllProfiles()
    assert profiles == []


def test_profileManager_getAllProfiles_multiple():
    """Test ProfileManager returns all profiles."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    manager.createProfile(Profile(id='p1', name='Profile 1'))
    manager.createProfile(Profile(id='p2', name='Profile 2'))
    manager.createProfile(Profile(id='p3', name='Profile 3'))

    profiles = manager.getAllProfiles()
    assert len(profiles) == 3
    ids = [p.id for p in profiles]
    assert 'p1' in ids
    assert 'p2' in ids
    assert 'p3' in ids


def test_profileManager_updateProfile_success():
    """Test ProfileManager updates profile successfully."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    profile = Profile(id='test', name='Test', description='Original')
    manager.createProfile(profile)

    profile.description = 'Updated'
    profile.pollingIntervalMs = 750
    manager.updateProfile(profile)

    retrieved = manager.getProfile('test')
    assert retrieved.description == 'Updated'
    assert retrieved.pollingIntervalMs == 750


def test_profileManager_updateProfile_notFound():
    """Test ProfileManager raises error updating non-existent profile."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    profile = Profile(id='nonexistent', name='Test')
    try:
        manager.updateProfile(profile)
        assert False, "Should have raised ProfileNotFoundError"
    except ProfileNotFoundError:
        pass


def test_profileManager_deleteProfile_success():
    """Test ProfileManager deletes profile successfully."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    profile = Profile(id='test', name='Test')
    manager.createProfile(profile)

    manager.deleteProfile('test')

    retrieved = manager.getProfile('test')
    assert retrieved is None


def test_profileManager_deleteProfile_notFound():
    """Test ProfileManager raises error deleting non-existent profile."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    try:
        manager.deleteProfile('nonexistent')
        assert False, "Should have raised ProfileNotFoundError"
    except ProfileNotFoundError:
        pass


def test_profileManager_profileExists_true():
    """Test ProfileManager profileExists returns True for existing."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    manager.createProfile(Profile(id='test', name='Test'))

    assert manager.profileExists('test') is True


def test_profileManager_profileExists_false():
    """Test ProfileManager profileExists returns False for non-existing."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    assert manager.profileExists('nonexistent') is False


# ================================================================================
# Default Profile Tests
# ================================================================================

def test_profileManager_ensureDefaultProfile_creates():
    """Test ProfileManager creates default profile if not exists."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    manager.ensureDefaultProfile()

    profile = manager.getProfile(DEFAULT_PROFILE_ID)
    assert profile is not None
    assert profile.name == DEFAULT_PROFILE_NAME


def test_profileManager_ensureDefaultProfile_idempotent():
    """Test ProfileManager ensureDefaultProfile is idempotent."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    manager.ensureDefaultProfile()
    manager.ensureDefaultProfile()  # Should not raise

    profiles = manager.getAllProfiles()
    defaultProfiles = [p for p in profiles if p.id == DEFAULT_PROFILE_ID]
    assert len(defaultProfiles) == 1


def test_profileManager_ensureDefaultProfile_preservesExisting():
    """Test ProfileManager preserves existing default profile."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    # Create default with custom description
    profile = Profile(
        id=DEFAULT_PROFILE_ID,
        name=DEFAULT_PROFILE_NAME,
        description='Custom description'
    )
    manager.createProfile(profile)

    manager.ensureDefaultProfile()

    retrieved = manager.getProfile(DEFAULT_PROFILE_ID)
    assert retrieved.description == 'Custom description'


def test_getDefaultProfile_returnsProfile():
    """Test getDefaultProfile returns default profile object."""
    profile = getDefaultProfile()
    assert profile.id == DEFAULT_PROFILE_ID
    assert profile.name == DEFAULT_PROFILE_NAME
    assert profile.pollingIntervalMs == 1000


# ================================================================================
# Active Profile Tests
# ================================================================================

def test_profileManager_setActiveProfile():
    """Test ProfileManager sets active profile."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    manager.createProfile(Profile(id='test', name='Test'))
    manager.setActiveProfile('test')

    assert manager.getActiveProfileId() == 'test'


def test_profileManager_getActiveProfile():
    """Test ProfileManager gets active profile object."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    manager.createProfile(Profile(id='test', name='Test Profile'))
    manager.setActiveProfile('test')

    profile = manager.getActiveProfile()
    assert profile is not None
    assert profile.id == 'test'
    assert profile.name == 'Test Profile'


def test_profileManager_getActiveProfile_notSet():
    """Test ProfileManager returns None when no active profile."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    profile = manager.getActiveProfile()
    assert profile is None


def test_profileManager_setActiveProfile_notFound():
    """Test ProfileManager raises error for non-existent profile."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    try:
        manager.setActiveProfile('nonexistent')
        assert False, "Should have raised ProfileNotFoundError"
    except ProfileNotFoundError:
        pass


# ================================================================================
# Config Integration Tests
# ================================================================================

def test_createProfileManagerFromConfig_basic():
    """Test createProfileManagerFromConfig creates manager."""
    config = getSampleConfig()
    db = getTestDatabase()

    manager = createProfileManagerFromConfig(config, db)

    assert manager is not None
    assert manager._database is db


def test_createProfileManagerFromConfig_loadsProfiles():
    """Test createProfileManagerFromConfig loads profiles from config."""
    config = getSampleConfig()
    db = getTestDatabase()

    manager = createProfileManagerFromConfig(config, db)

    daily = manager.getProfile('daily')
    assert daily is not None
    assert daily.name == 'Daily'

    perf = manager.getProfile('performance')
    assert perf is not None
    assert perf.name == 'Performance'


def test_createProfileManagerFromConfig_setsActiveProfile():
    """Test createProfileManagerFromConfig sets active profile."""
    config = getSampleConfig()
    db = getTestDatabase()

    manager = createProfileManagerFromConfig(config, db)

    assert manager.getActiveProfileId() == 'daily'


def test_createProfileManagerFromConfig_preservesThresholds():
    """Test createProfileManagerFromConfig preserves alert thresholds."""
    config = getSampleConfig()
    db = getTestDatabase()

    manager = createProfileManagerFromConfig(config, db)

    daily = manager.getProfile('daily')
    assert daily.alertThresholds.get('rpmRedline') == 6500
    assert daily.alertThresholds.get('coolantTempCritical') == 110


def test_createProfileManagerFromConfig_preservesPollingInterval():
    """Test createProfileManagerFromConfig preserves polling interval."""
    config = getSampleConfig()
    db = getTestDatabase()

    manager = createProfileManagerFromConfig(config, db)

    daily = manager.getProfile('daily')
    assert daily.pollingIntervalMs == 1000

    perf = manager.getProfile('performance')
    assert perf.pollingIntervalMs == 500


def test_createProfileManagerFromConfig_emptyConfig():
    """Test createProfileManagerFromConfig with empty config."""
    config = {}
    db = getTestDatabase()

    manager = createProfileManagerFromConfig(config, db)

    # Should still work, with default profile created
    manager.ensureDefaultProfile()
    assert manager.getProfile(DEFAULT_PROFILE_ID) is not None


def test_createProfileManagerFromConfig_missingProfiles():
    """Test createProfileManagerFromConfig with missing profiles section."""
    config = {'otherSection': {}}
    db = getTestDatabase()

    manager = createProfileManagerFromConfig(config, db)

    profiles = manager.getAllProfiles()
    assert len(profiles) == 0


def test_createProfileManagerFromConfig_noDatabase():
    """Test createProfileManagerFromConfig without database."""
    config = getSampleConfig()

    manager = createProfileManagerFromConfig(config, database=None)

    assert manager is not None
    assert manager._database is None


# ================================================================================
# Profile Count and Stats Tests
# ================================================================================

def test_profileManager_getProfileCount_empty():
    """Test ProfileManager getProfileCount with no profiles."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    assert manager.getProfileCount() == 0


def test_profileManager_getProfileCount_withProfiles():
    """Test ProfileManager getProfileCount with profiles."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    manager.createProfile(Profile(id='p1', name='Profile 1'))
    manager.createProfile(Profile(id='p2', name='Profile 2'))

    assert manager.getProfileCount() == 2


def test_profileManager_getProfileIds():
    """Test ProfileManager getProfileIds method."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    manager.createProfile(Profile(id='alpha', name='Alpha'))
    manager.createProfile(Profile(id='beta', name='Beta'))

    ids = manager.getProfileIds()
    assert 'alpha' in ids
    assert 'beta' in ids


# ================================================================================
# Edge Case Tests
# ================================================================================

def test_profileManager_createProfile_specialCharacters():
    """Test ProfileManager handles special characters in name."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    profile = Profile(id='special', name="Test's Profile (v1.0)")
    manager.createProfile(profile)

    retrieved = manager.getProfile('special')
    assert retrieved.name == "Test's Profile (v1.0)"


def test_profileManager_createProfile_unicodeName():
    """Test ProfileManager handles unicode in name."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    profile = Profile(id='unicode', name='Perfil Español')
    manager.createProfile(profile)

    retrieved = manager.getProfile('unicode')
    assert retrieved.name == 'Perfil Español'


def test_profileManager_updateProfile_alertThresholds():
    """Test ProfileManager updates alert thresholds."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    profile = Profile(
        id='test',
        name='Test',
        alertThresholds={'rpmRedline': 6500}
    )
    manager.createProfile(profile)

    profile.alertThresholds = {'rpmRedline': 7000, 'coolantTempCritical': 115}
    manager.updateProfile(profile)

    retrieved = manager.getProfile('test')
    assert retrieved.alertThresholds['rpmRedline'] == 7000
    assert retrieved.alertThresholds['coolantTempCritical'] == 115


def test_profile_roundtrip_throughDatabase():
    """Test Profile survives database round-trip."""
    db = getTestDatabase()
    manager = ProfileManager(database=db)

    original = Profile(
        id='roundtrip',
        name='Round Trip Test',
        description='Testing database serialization',
        alertThresholds={
            'rpmRedline': 6500,
            'coolantTempCritical': 110,
            'oilPressureLow': 20
        },
        pollingIntervalMs=750
    )
    manager.createProfile(original)

    retrieved = manager.getProfile('roundtrip')
    assert retrieved.id == original.id
    assert retrieved.name == original.name
    assert retrieved.description == original.description
    assert retrieved.alertThresholds == original.alertThresholds
    assert retrieved.pollingIntervalMs == original.pollingIntervalMs


# ================================================================================
# Main Entry Point
# ================================================================================

def main():
    """Run all tests."""
    runner = TestRunner()

    print("Profile Dataclass Tests")
    print("-" * 40)
    runner.runTest("test_profile_init_requiredFields", test_profile_init_requiredFields)
    runner.runTest("test_profile_init_defaultValues", test_profile_init_defaultValues)
    runner.runTest("test_profile_init_customValues", test_profile_init_customValues)
    runner.runTest("test_profile_toDict", test_profile_toDict)
    runner.runTest("test_profile_fromDict", test_profile_fromDict)
    runner.runTest("test_profile_fromDict_minimalData", test_profile_fromDict_minimalData)
    runner.runTest("test_profile_fromConfigDict", test_profile_fromConfigDict)
    runner.runTest("test_profile_alertConfigJson", test_profile_alertConfigJson)
    runner.runTest("test_profile_alertConfigJson_empty", test_profile_alertConfigJson_empty)

    print("\nProfileError Tests")
    print("-" * 40)
    runner.runTest("test_profileError_init", test_profileError_init)
    runner.runTest("test_profileNotFoundError_inherits", test_profileNotFoundError_inherits)
    runner.runTest("test_profileValidationError_hasInvalidFields", test_profileValidationError_hasInvalidFields)

    print("\nProfileManager Initialization Tests")
    print("-" * 40)
    runner.runTest("test_profileManager_init_withDatabase", test_profileManager_init_withDatabase)
    runner.runTest("test_profileManager_init_withoutDatabase", test_profileManager_init_withoutDatabase)
    runner.runTest("test_profileManager_setDatabase", test_profileManager_setDatabase)

    print("\nProfileManager CRUD Tests")
    print("-" * 40)
    runner.runTest("test_profileManager_createProfile_success", test_profileManager_createProfile_success)
    runner.runTest("test_profileManager_createProfile_withThresholds", test_profileManager_createProfile_withThresholds)
    runner.runTest("test_profileManager_createProfile_duplicate", test_profileManager_createProfile_duplicate)
    runner.runTest("test_profileManager_createProfile_invalidId", test_profileManager_createProfile_invalidId)
    runner.runTest("test_profileManager_createProfile_invalidName", test_profileManager_createProfile_invalidName)
    runner.runTest("test_profileManager_getProfile_exists", test_profileManager_getProfile_exists)
    runner.runTest("test_profileManager_getProfile_notFound", test_profileManager_getProfile_notFound)
    runner.runTest("test_profileManager_getAllProfiles_empty", test_profileManager_getAllProfiles_empty)
    runner.runTest("test_profileManager_getAllProfiles_multiple", test_profileManager_getAllProfiles_multiple)
    runner.runTest("test_profileManager_updateProfile_success", test_profileManager_updateProfile_success)
    runner.runTest("test_profileManager_updateProfile_notFound", test_profileManager_updateProfile_notFound)
    runner.runTest("test_profileManager_deleteProfile_success", test_profileManager_deleteProfile_success)
    runner.runTest("test_profileManager_deleteProfile_notFound", test_profileManager_deleteProfile_notFound)
    runner.runTest("test_profileManager_profileExists_true", test_profileManager_profileExists_true)
    runner.runTest("test_profileManager_profileExists_false", test_profileManager_profileExists_false)

    print("\nDefault Profile Tests")
    print("-" * 40)
    runner.runTest("test_profileManager_ensureDefaultProfile_creates", test_profileManager_ensureDefaultProfile_creates)
    runner.runTest("test_profileManager_ensureDefaultProfile_idempotent", test_profileManager_ensureDefaultProfile_idempotent)
    runner.runTest("test_profileManager_ensureDefaultProfile_preservesExisting", test_profileManager_ensureDefaultProfile_preservesExisting)
    runner.runTest("test_getDefaultProfile_returnsProfile", test_getDefaultProfile_returnsProfile)

    print("\nActive Profile Tests")
    print("-" * 40)
    runner.runTest("test_profileManager_setActiveProfile", test_profileManager_setActiveProfile)
    runner.runTest("test_profileManager_getActiveProfile", test_profileManager_getActiveProfile)
    runner.runTest("test_profileManager_getActiveProfile_notSet", test_profileManager_getActiveProfile_notSet)
    runner.runTest("test_profileManager_setActiveProfile_notFound", test_profileManager_setActiveProfile_notFound)

    print("\nConfig Integration Tests")
    print("-" * 40)
    runner.runTest("test_createProfileManagerFromConfig_basic", test_createProfileManagerFromConfig_basic)
    runner.runTest("test_createProfileManagerFromConfig_loadsProfiles", test_createProfileManagerFromConfig_loadsProfiles)
    runner.runTest("test_createProfileManagerFromConfig_setsActiveProfile", test_createProfileManagerFromConfig_setsActiveProfile)
    runner.runTest("test_createProfileManagerFromConfig_preservesThresholds", test_createProfileManagerFromConfig_preservesThresholds)
    runner.runTest("test_createProfileManagerFromConfig_preservesPollingInterval", test_createProfileManagerFromConfig_preservesPollingInterval)
    runner.runTest("test_createProfileManagerFromConfig_emptyConfig", test_createProfileManagerFromConfig_emptyConfig)
    runner.runTest("test_createProfileManagerFromConfig_missingProfiles", test_createProfileManagerFromConfig_missingProfiles)
    runner.runTest("test_createProfileManagerFromConfig_noDatabase", test_createProfileManagerFromConfig_noDatabase)

    print("\nProfile Count and Stats Tests")
    print("-" * 40)
    runner.runTest("test_profileManager_getProfileCount_empty", test_profileManager_getProfileCount_empty)
    runner.runTest("test_profileManager_getProfileCount_withProfiles", test_profileManager_getProfileCount_withProfiles)
    runner.runTest("test_profileManager_getProfileIds", test_profileManager_getProfileIds)

    print("\nEdge Case Tests")
    print("-" * 40)
    runner.runTest("test_profileManager_createProfile_specialCharacters", test_profileManager_createProfile_specialCharacters)
    runner.runTest("test_profileManager_createProfile_unicodeName", test_profileManager_createProfile_unicodeName)
    runner.runTest("test_profileManager_updateProfile_alertThresholds", test_profileManager_updateProfile_alertThresholds)
    runner.runTest("test_profile_roundtrip_throughDatabase", test_profile_roundtrip_throughDatabase)

    success = runner.report()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
