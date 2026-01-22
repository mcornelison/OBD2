################################################################################
# File Name: run_tests_failure_injector.py
# Purpose/Description: Unit tests for the FailureInjector class
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-038
# ================================================================================
################################################################################

"""
Unit tests for the FailureInjector class.

Tests cover:
- FailureType enum and string conversion
- FailureConfig dataclass validation
- Failure injection and clearing
- Scheduled failures
- Sensor failure checking
- Out-of-range value modification
- DTC codes
- Callbacks
- Helper functions
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path for imports
srcPath = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(srcPath))

from obd.simulator.failure_injector import (
    COMMON_DTC_CODES,
    DEFAULT_INTERMITTENT_PROBABILITY,
    DEFAULT_OUT_OF_RANGE_FACTOR,
    ActiveFailure,
    FailureConfig,
    FailureInjector,
    FailureState,
    FailureType,
    InjectorStatus,
    ScheduledFailure,
    createFailureInjectorFromConfig,
    getDefaultFailureInjector,
)


class TestFailureTypeEnum(unittest.TestCase):
    """Tests for FailureType enum."""

    def test_allFailureTypesExist(self):
        """
        Given: FailureType enum
        When: Checking available types
        Then: All required failure types should exist
        """
        # Verify all required types exist
        self.assertEqual(FailureType.CONNECTION_DROP.value, "connectionDrop")
        self.assertEqual(FailureType.SENSOR_FAILURE.value, "sensorFailure")
        self.assertEqual(FailureType.INTERMITTENT_SENSOR.value, "intermittentSensor")
        self.assertEqual(FailureType.OUT_OF_RANGE.value, "outOfRange")
        self.assertEqual(FailureType.DTC_CODES.value, "dtcCodes")

    def test_fromString_validCamelCase(self):
        """
        Given: A valid camelCase string
        When: Converting to FailureType
        Then: Should return correct enum value
        """
        result = FailureType.fromString("connectionDrop")
        self.assertEqual(result, FailureType.CONNECTION_DROP)

        result = FailureType.fromString("sensorFailure")
        self.assertEqual(result, FailureType.SENSOR_FAILURE)

    def test_fromString_validUpperCase(self):
        """
        Given: A valid uppercase string
        When: Converting to FailureType
        Then: Should return correct enum value
        """
        result = FailureType.fromString("CONNECTIONDROP")
        self.assertEqual(result, FailureType.CONNECTION_DROP)

    def test_fromString_validWithUnderscores(self):
        """
        Given: A valid string with underscores
        When: Converting to FailureType
        Then: Should normalize and return correct enum
        """
        result = FailureType.fromString("connection_drop")
        self.assertEqual(result, FailureType.CONNECTION_DROP)

    def test_fromString_invalidString(self):
        """
        Given: An invalid string
        When: Converting to FailureType
        Then: Should return None
        """
        result = FailureType.fromString("invalidType")
        self.assertIsNone(result)

    def test_fromString_emptyString(self):
        """
        Given: An empty string
        When: Converting to FailureType
        Then: Should return None
        """
        result = FailureType.fromString("")
        self.assertIsNone(result)


class TestFailureConfig(unittest.TestCase):
    """Tests for FailureConfig dataclass."""

    def test_defaultConfig(self):
        """
        Given: Default FailureConfig
        When: Created with no arguments
        Then: Should have default values
        """
        config = FailureConfig()

        self.assertEqual(config.sensorNames, [])
        self.assertEqual(config.probability, DEFAULT_INTERMITTENT_PROBABILITY)
        self.assertEqual(config.outOfRangeFactor, DEFAULT_OUT_OF_RANGE_FACTOR)
        self.assertEqual(config.outOfRangeDirection, "random")
        self.assertEqual(config.dtcCodes, [])
        self.assertIsNone(config.customValue)
        self.assertFalse(config.affectsAllSensors)

    def test_configWithSensorNames(self):
        """
        Given: FailureConfig with sensor names
        When: Created with lowercase names
        Then: Should normalize to uppercase
        """
        config = FailureConfig(sensorNames=["rpm", "coolant_temp"])

        self.assertEqual(config.sensorNames, ["RPM", "COOLANT_TEMP"])

    def test_configProbabilityClamping(self):
        """
        Given: FailureConfig with invalid probability
        When: Created with values outside 0-1 range
        Then: Should clamp to valid range
        """
        config = FailureConfig(probability=-0.5)
        self.assertEqual(config.probability, 0.0)

        config = FailureConfig(probability=1.5)
        self.assertEqual(config.probability, 1.0)

    def test_configOutOfRangeDirectionValidation(self):
        """
        Given: FailureConfig with invalid direction
        When: Created with invalid direction
        Then: Should default to 'random'
        """
        config = FailureConfig(outOfRangeDirection="invalid")
        self.assertEqual(config.outOfRangeDirection, "random")

    def test_configToDict(self):
        """
        Given: A FailureConfig
        When: Converting to dictionary
        Then: Should return all fields
        """
        config = FailureConfig(
            sensorNames=["RPM"],
            probability=0.5,
            outOfRangeFactor=2.0,
            dtcCodes=["P0300"],
        )

        result = config.toDict()

        self.assertEqual(result["sensorNames"], ["RPM"])
        self.assertEqual(result["probability"], 0.5)
        self.assertEqual(result["outOfRangeFactor"], 2.0)
        self.assertEqual(result["dtcCodes"], ["P0300"])

    def test_configFromDict(self):
        """
        Given: A dictionary with config data
        When: Creating FailureConfig from it
        Then: Should create correct config
        """
        data = {
            "sensorNames": ["SPEED"],
            "probability": 0.8,
            "outOfRangeFactor": 5.0,
            "dtcCodes": ["P0171"],
        }

        config = FailureConfig.fromDict(data)

        self.assertEqual(config.sensorNames, ["SPEED"])
        self.assertEqual(config.probability, 0.8)
        self.assertEqual(config.outOfRangeFactor, 5.0)
        self.assertEqual(config.dtcCodes, ["P0171"])


class TestScheduledFailure(unittest.TestCase):
    """Tests for ScheduledFailure dataclass."""

    def test_scheduledFailureCreation(self):
        """
        Given: ScheduledFailure parameters
        When: Creating a scheduled failure
        Then: Should set start and end times correctly
        """
        config = FailureConfig()
        startSeconds = 5.0
        durationSeconds = 10.0

        scheduled = ScheduledFailure(
            failureType=FailureType.CONNECTION_DROP,
            config=config,
            startSeconds=startSeconds,
            durationSeconds=durationSeconds,
        )

        self.assertEqual(scheduled.failureType, FailureType.CONNECTION_DROP)
        self.assertIsNotNone(scheduled.startTime)
        self.assertIsNotNone(scheduled.endTime)
        self.assertIsNotNone(scheduled.id)

    def test_scheduledFailureIsActive(self):
        """
        Given: A scheduled failure
        When: Checking if active at different times
        Then: Should return correct active status
        """
        config = FailureConfig()

        scheduled = ScheduledFailure(
            failureType=FailureType.CONNECTION_DROP,
            config=config,
            startSeconds=0,  # Starts immediately
            durationSeconds=10.0,
        )

        # Now must be captured after creating scheduled failure
        now = time.time()

        # Should be active now (startTime should be <= now)
        self.assertTrue(scheduled.isActive(now))

        # Should be active in 5 seconds
        self.assertTrue(scheduled.isActive(now + 5))

        # Should not be active in 15 seconds
        self.assertFalse(scheduled.isActive(now + 15))

    def test_scheduledFailureIsExpired(self):
        """
        Given: A scheduled failure with duration
        When: Checking if expired
        Then: Should return correct expired status
        """
        config = FailureConfig()
        now = time.time()

        scheduled = ScheduledFailure(
            failureType=FailureType.CONNECTION_DROP,
            config=config,
            startSeconds=0,
            durationSeconds=5.0,
        )

        # Should not be expired before end time
        self.assertFalse(scheduled.isExpired(now + 3))

        # Should be expired after end time
        self.assertTrue(scheduled.isExpired(now + 10))

    def test_scheduledFailurePermanent(self):
        """
        Given: A scheduled failure with no duration
        When: Checking if expired
        Then: Should never expire
        """
        config = FailureConfig()
        now = time.time()

        scheduled = ScheduledFailure(
            failureType=FailureType.CONNECTION_DROP,
            config=config,
            startSeconds=0,
            durationSeconds=None,  # Permanent
        )

        # Should never expire
        self.assertFalse(scheduled.isExpired(now + 1000000))


class TestFailureInjectorBasic(unittest.TestCase):
    """Basic tests for FailureInjector class."""

    def setUp(self):
        """Set up test fixtures."""
        self.injector = FailureInjector()

    def tearDown(self):
        """Clean up after tests."""
        self.injector.stopScheduler()

    def test_initialization(self):
        """
        Given: A new FailureInjector
        When: Initialized
        Then: Should have no active failures
        """
        status = self.injector.getStatus()

        self.assertFalse(status.isActive)
        self.assertEqual(status.activeFailures, [])
        self.assertEqual(status.scheduledFailures, 0)
        self.assertEqual(status.totalInjected, 0)

    def test_injectFailure_connectionDrop(self):
        """
        Given: A FailureInjector
        When: Injecting CONNECTION_DROP
        Then: Should activate the failure
        """
        result = self.injector.injectFailure(FailureType.CONNECTION_DROP)

        self.assertTrue(result)
        self.assertTrue(self.injector.isConnectionDropped)
        self.assertTrue(self.injector.isFailureActive(FailureType.CONNECTION_DROP))

    def test_injectFailure_duplicate(self):
        """
        Given: A FailureInjector with active failure
        When: Injecting the same failure again
        Then: Should return False
        """
        self.injector.injectFailure(FailureType.CONNECTION_DROP)
        result = self.injector.injectFailure(FailureType.CONNECTION_DROP)

        self.assertFalse(result)

    def test_injectFailure_withConfig(self):
        """
        Given: A FailureInjector
        When: Injecting with configuration
        Then: Should store the configuration
        """
        config = FailureConfig(sensorNames=["RPM", "SPEED"])

        self.injector.injectFailure(FailureType.SENSOR_FAILURE, config)

        storedConfig = self.injector.getActiveFailureConfig(FailureType.SENSOR_FAILURE)
        self.assertEqual(storedConfig.sensorNames, ["RPM", "SPEED"])

    def test_clearFailure(self):
        """
        Given: A FailureInjector with active failure
        When: Clearing the failure
        Then: Should deactivate the failure
        """
        self.injector.injectFailure(FailureType.CONNECTION_DROP)

        result = self.injector.clearFailure(FailureType.CONNECTION_DROP)

        self.assertTrue(result)
        self.assertFalse(self.injector.isConnectionDropped)

    def test_clearFailure_notActive(self):
        """
        Given: A FailureInjector
        When: Clearing a failure that is not active
        Then: Should return False
        """
        result = self.injector.clearFailure(FailureType.CONNECTION_DROP)

        self.assertFalse(result)

    def test_clearAllFailures(self):
        """
        Given: A FailureInjector with multiple failures
        When: Clearing all failures
        Then: Should clear all active failures
        """
        self.injector.injectFailure(FailureType.CONNECTION_DROP)
        self.injector.injectFailure(FailureType.SENSOR_FAILURE)
        self.injector.injectFailure(FailureType.DTC_CODES)

        count = self.injector.clearAllFailures()

        self.assertEqual(count, 3)
        self.assertFalse(self.injector.getStatus().isActive)


class TestFailureInjectorSensors(unittest.TestCase):
    """Tests for sensor-related failures."""

    def setUp(self):
        """Set up test fixtures."""
        self.injector = FailureInjector()

    def tearDown(self):
        """Clean up after tests."""
        self.injector.stopScheduler()

    def test_failedSensors_empty(self):
        """
        Given: No active sensor failures
        When: Getting failed sensors
        Then: Should return empty set
        """
        sensors = self.injector.failedSensors

        self.assertEqual(sensors, set())

    def test_failedSensors_specificSensors(self):
        """
        Given: Sensor failure for specific sensors
        When: Getting failed sensors
        Then: Should return those sensors
        """
        config = FailureConfig(sensorNames=["RPM", "SPEED"])
        self.injector.injectFailure(FailureType.SENSOR_FAILURE, config)

        sensors = self.injector.failedSensors

        self.assertEqual(sensors, {"RPM", "SPEED"})

    def test_failedSensors_allSensors(self):
        """
        Given: Sensor failure affecting all sensors
        When: Getting failed sensors
        Then: Should return wildcard marker
        """
        config = FailureConfig(affectsAllSensors=True)
        self.injector.injectFailure(FailureType.SENSOR_FAILURE, config)

        sensors = self.injector.failedSensors

        self.assertEqual(sensors, {"*"})

    def test_shouldSensorFail_permanent(self):
        """
        Given: Permanent sensor failure
        When: Checking if sensor should fail
        Then: Should return True for affected sensor
        """
        config = FailureConfig(sensorNames=["RPM"])
        self.injector.injectFailure(FailureType.SENSOR_FAILURE, config)

        self.assertTrue(self.injector.shouldSensorFail("RPM"))
        self.assertFalse(self.injector.shouldSensorFail("SPEED"))

    def test_shouldSensorFail_permanent_allSensors(self):
        """
        Given: Permanent sensor failure for all sensors
        When: Checking any sensor
        Then: Should return True
        """
        config = FailureConfig(affectsAllSensors=True)
        self.injector.injectFailure(FailureType.SENSOR_FAILURE, config)

        self.assertTrue(self.injector.shouldSensorFail("RPM"))
        self.assertTrue(self.injector.shouldSensorFail("SPEED"))
        self.assertTrue(self.injector.shouldSensorFail("COOLANT_TEMP"))

    def test_shouldSensorFail_caseInsensitive(self):
        """
        Given: Sensor failure for a sensor
        When: Checking with different case
        Then: Should match regardless of case
        """
        config = FailureConfig(sensorNames=["RPM"])
        self.injector.injectFailure(FailureType.SENSOR_FAILURE, config)

        self.assertTrue(self.injector.shouldSensorFail("rpm"))
        self.assertTrue(self.injector.shouldSensorFail("Rpm"))

    def test_shouldSensorFail_intermittent(self):
        """
        Given: Intermittent sensor failure with 100% probability
        When: Checking if sensor should fail
        Then: Should always return True
        """
        config = FailureConfig(
            sensorNames=["RPM"],
            probability=1.0,  # 100% failure rate
        )
        self.injector.injectFailure(FailureType.INTERMITTENT_SENSOR, config)

        # With 100% probability, should always fail
        for _ in range(10):
            self.assertTrue(self.injector.shouldSensorFail("RPM"))

    def test_shouldSensorFail_intermittentZeroProbability(self):
        """
        Given: Intermittent sensor failure with 0% probability
        When: Checking if sensor should fail
        Then: Should never return True
        """
        config = FailureConfig(
            sensorNames=["RPM"],
            probability=0.0,  # 0% failure rate
        )
        self.injector.injectFailure(FailureType.INTERMITTENT_SENSOR, config)

        # With 0% probability, should never fail
        for _ in range(10):
            self.assertFalse(self.injector.shouldSensorFail("RPM"))


class TestFailureInjectorOutOfRange(unittest.TestCase):
    """Tests for out-of-range failures."""

    def setUp(self):
        """Set up test fixtures."""
        self.injector = FailureInjector()

    def tearDown(self):
        """Clean up after tests."""
        self.injector.stopScheduler()

    def test_getModifiedValue_noFailure(self):
        """
        Given: No out-of-range failure
        When: Getting modified value
        Then: Should return None
        """
        result = self.injector.getModifiedValue("RPM", 3000.0)

        self.assertIsNone(result)

    def test_getModifiedValue_high(self):
        """
        Given: Out-of-range failure with 'high' direction
        When: Getting modified value
        Then: Should return value multiplied by factor
        """
        config = FailureConfig(
            sensorNames=["RPM"],
            outOfRangeFactor=2.0,
            outOfRangeDirection="high",
        )
        self.injector.injectFailure(FailureType.OUT_OF_RANGE, config)

        result = self.injector.getModifiedValue("RPM", 3000.0)

        self.assertEqual(result, 6000.0)

    def test_getModifiedValue_low(self):
        """
        Given: Out-of-range failure with 'low' direction
        When: Getting modified value
        Then: Should return value divided by factor
        """
        config = FailureConfig(
            sensorNames=["RPM"],
            outOfRangeFactor=2.0,
            outOfRangeDirection="low",
        )
        self.injector.injectFailure(FailureType.OUT_OF_RANGE, config)

        result = self.injector.getModifiedValue("RPM", 3000.0)

        self.assertEqual(result, 1500.0)

    def test_getModifiedValue_customValue(self):
        """
        Given: Out-of-range failure with custom value
        When: Getting modified value
        Then: Should return custom value
        """
        config = FailureConfig(
            sensorNames=["RPM"],
            customValue=9999.0,
        )
        self.injector.injectFailure(FailureType.OUT_OF_RANGE, config)

        result = self.injector.getModifiedValue("RPM", 3000.0)

        self.assertEqual(result, 9999.0)

    def test_getModifiedValue_unaffectedSensor(self):
        """
        Given: Out-of-range failure for specific sensor
        When: Getting modified value for different sensor
        Then: Should return None
        """
        config = FailureConfig(
            sensorNames=["RPM"],
            outOfRangeFactor=2.0,
            outOfRangeDirection="high",
        )
        self.injector.injectFailure(FailureType.OUT_OF_RANGE, config)

        result = self.injector.getModifiedValue("SPEED", 100.0)

        self.assertIsNone(result)


class TestFailureInjectorDtcCodes(unittest.TestCase):
    """Tests for DTC code failures."""

    def setUp(self):
        """Set up test fixtures."""
        self.injector = FailureInjector()

    def tearDown(self):
        """Clean up after tests."""
        self.injector.stopScheduler()

    def test_activeDtcCodes_empty(self):
        """
        Given: No DTC failure
        When: Getting active DTC codes
        Then: Should return empty list
        """
        codes = self.injector.activeDtcCodes

        self.assertEqual(codes, [])

    def test_activeDtcCodes_withCodes(self):
        """
        Given: DTC failure with specific codes
        When: Getting active DTC codes
        Then: Should return those codes
        """
        config = FailureConfig(dtcCodes=["P0300", "P0171"])
        self.injector.injectFailure(FailureType.DTC_CODES, config)

        codes = self.injector.activeDtcCodes

        self.assertEqual(codes, ["P0300", "P0171"])

    def test_activeDtcCodes_defaultCode(self):
        """
        Given: DTC failure with no specified codes
        When: Injecting the failure
        Then: Should use default DTC code
        """
        self.injector.injectFailure(FailureType.DTC_CODES)

        codes = self.injector.activeDtcCodes

        self.assertEqual(len(codes), 1)
        self.assertIn(codes[0], COMMON_DTC_CODES)


class TestFailureInjectorScheduled(unittest.TestCase):
    """Tests for scheduled failures."""

    def setUp(self):
        """Set up test fixtures."""
        self.injector = FailureInjector()

    def tearDown(self):
        """Clean up after tests."""
        self.injector.stopScheduler()

    def test_scheduleFailure_creation(self):
        """
        Given: A FailureInjector
        When: Scheduling a failure
        Then: Should create scheduled failure
        """
        scheduled = self.injector.scheduleFailure(
            FailureType.CONNECTION_DROP,
            startSeconds=5.0,
            durationSeconds=10.0,
        )

        self.assertIsNotNone(scheduled)
        self.assertEqual(scheduled.failureType, FailureType.CONNECTION_DROP)

        status = self.injector.getStatus()
        self.assertEqual(status.scheduledFailures, 1)

    def test_scheduleFailure_withConfig(self):
        """
        Given: A FailureInjector
        When: Scheduling with configuration
        Then: Should store the configuration
        """
        config = FailureConfig(sensorNames=["RPM"])

        scheduled = self.injector.scheduleFailure(
            FailureType.SENSOR_FAILURE,
            startSeconds=5.0,
            durationSeconds=10.0,
            config=config,
        )

        self.assertEqual(scheduled.config.sensorNames, ["RPM"])

    def test_scheduleFailure_immediateActivation(self):
        """
        Given: A scheduled failure with startSeconds=0
        When: Scheduler processes
        Then: Should activate immediately
        """
        self.injector.scheduleFailure(
            FailureType.CONNECTION_DROP,
            startSeconds=0,  # Start immediately
            durationSeconds=60.0,
        )

        # Wait for scheduler to process
        time.sleep(0.3)

        self.assertTrue(self.injector.isConnectionDropped)

    def test_scheduleFailure_expiration(self):
        """
        Given: A scheduled failure with short duration
        When: Duration expires
        Then: Should deactivate
        """
        self.injector.scheduleFailure(
            FailureType.CONNECTION_DROP,
            startSeconds=0,
            durationSeconds=0.2,  # Very short duration
        )

        # Wait for activation
        time.sleep(0.15)
        self.assertTrue(self.injector.isConnectionDropped)

        # Wait for expiration
        time.sleep(0.2)
        self.assertFalse(self.injector.isConnectionDropped)

    def test_cancelScheduledFailure(self):
        """
        Given: A scheduled failure
        When: Cancelling it
        Then: Should remove from schedule
        """
        scheduled = self.injector.scheduleFailure(
            FailureType.CONNECTION_DROP,
            startSeconds=60.0,  # Far future
            durationSeconds=10.0,
        )

        result = self.injector.cancelScheduledFailure(scheduled)

        self.assertTrue(result)
        self.assertEqual(self.injector.getStatus().scheduledFailures, 0)


class TestFailureInjectorCallbacks(unittest.TestCase):
    """Tests for callback functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.injector = FailureInjector()
        self.injectedCallbacks = []
        self.clearedCallbacks = []

    def tearDown(self):
        """Clean up after tests."""
        self.injector.stopScheduler()

    def test_onFailureInjectedCallback(self):
        """
        Given: A callback registered for failure injection
        When: Injecting a failure
        Then: Should trigger the callback
        """
        def callback(failureType, config):
            self.injectedCallbacks.append((failureType, config))

        self.injector.setOnFailureInjectedCallback(callback)
        self.injector.injectFailure(FailureType.CONNECTION_DROP)

        self.assertEqual(len(self.injectedCallbacks), 1)
        self.assertEqual(
            self.injectedCallbacks[0][0],
            FailureType.CONNECTION_DROP
        )

    def test_onFailureClearedCallback(self):
        """
        Given: A callback registered for failure clearing
        When: Clearing a failure
        Then: Should trigger the callback
        """
        def callback(failureType):
            self.clearedCallbacks.append(failureType)

        self.injector.setOnFailureClearedCallback(callback)
        self.injector.injectFailure(FailureType.CONNECTION_DROP)
        self.injector.clearFailure(FailureType.CONNECTION_DROP)

        self.assertEqual(len(self.clearedCallbacks), 1)
        self.assertEqual(self.clearedCallbacks[0], FailureType.CONNECTION_DROP)

    def test_callbackErrorHandling(self):
        """
        Given: A callback that raises an exception
        When: The callback is triggered
        Then: Should not crash the injector
        """
        def badCallback(failureType, config):
            raise ValueError("Test error")

        self.injector.setOnFailureInjectedCallback(badCallback)

        # Should not raise
        result = self.injector.injectFailure(FailureType.CONNECTION_DROP)
        self.assertTrue(result)


class TestFailureInjectorStatus(unittest.TestCase):
    """Tests for status reporting."""

    def setUp(self):
        """Set up test fixtures."""
        self.injector = FailureInjector()

    def tearDown(self):
        """Clean up after tests."""
        self.injector.stopScheduler()

    def test_getStatus_initial(self):
        """
        Given: A new FailureInjector
        When: Getting status
        Then: Should return inactive status
        """
        status = self.injector.getStatus()

        self.assertFalse(status.isActive)
        self.assertEqual(status.activeFailures, [])
        self.assertEqual(status.scheduledFailures, 0)
        self.assertEqual(status.totalInjected, 0)
        self.assertEqual(status.dtcCodes, [])

    def test_getStatus_afterInjection(self):
        """
        Given: A FailureInjector with active failures
        When: Getting status
        Then: Should reflect active state
        """
        self.injector.injectFailure(FailureType.CONNECTION_DROP)
        self.injector.injectFailure(
            FailureType.DTC_CODES,
            FailureConfig(dtcCodes=["P0300"])
        )

        status = self.injector.getStatus()

        self.assertTrue(status.isActive)
        self.assertIn("connectionDrop", status.activeFailures)
        self.assertIn("dtcCodes", status.activeFailures)
        self.assertEqual(status.totalInjected, 2)
        self.assertEqual(status.dtcCodes, ["P0300"])

    def test_getActiveFailures(self):
        """
        Given: Multiple active failures
        When: Getting active failures dict
        Then: Should return all active failures
        """
        self.injector.injectFailure(FailureType.CONNECTION_DROP)
        self.injector.injectFailure(FailureType.SENSOR_FAILURE)

        failures = self.injector.getActiveFailures()

        self.assertIn("connectionDrop", failures)
        self.assertIn("sensorFailure", failures)

    def test_getScheduledFailures(self):
        """
        Given: Scheduled failures
        When: Getting scheduled failures list
        Then: Should return all scheduled failures
        """
        self.injector.scheduleFailure(
            FailureType.CONNECTION_DROP,
            startSeconds=60.0,
            durationSeconds=10.0,
        )
        self.injector.scheduleFailure(
            FailureType.SENSOR_FAILURE,
            startSeconds=120.0,
            durationSeconds=20.0,
        )

        scheduled = self.injector.getScheduledFailures()

        self.assertEqual(len(scheduled), 2)


class TestFailureInjectorReset(unittest.TestCase):
    """Tests for reset functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.injector = FailureInjector()

    def tearDown(self):
        """Clean up after tests."""
        self.injector.stopScheduler()

    def test_reset(self):
        """
        Given: A FailureInjector with active failures
        When: Resetting
        Then: Should clear all state
        """
        self.injector.injectFailure(FailureType.CONNECTION_DROP)
        self.injector.scheduleFailure(
            FailureType.SENSOR_FAILURE,
            startSeconds=60.0,
            durationSeconds=10.0,
        )

        self.injector.reset()

        status = self.injector.getStatus()
        self.assertFalse(status.isActive)
        self.assertEqual(status.activeFailures, [])
        self.assertEqual(status.scheduledFailures, 0)
        self.assertEqual(status.totalInjected, 0)


class TestHelperFunctions(unittest.TestCase):
    """Tests for helper functions."""

    def test_createFailureInjectorFromConfig_empty(self):
        """
        Given: An empty config
        When: Creating FailureInjector from it
        Then: Should return injector with no active failures
        """
        config = {}
        injector = createFailureInjectorFromConfig(config)

        try:
            self.assertFalse(injector.getStatus().isActive)
        finally:
            injector.stopScheduler()

    def test_createFailureInjectorFromConfig_booleanFailure(self):
        """
        Given: Config with boolean failure flag
        When: Creating FailureInjector from it
        Then: Should activate if True
        """
        config = {
            "simulator": {
                "failures": {
                    "connectionDrop": True,
                }
            }
        }
        injector = createFailureInjectorFromConfig(config)

        try:
            self.assertTrue(injector.isConnectionDropped)
        finally:
            injector.stopScheduler()

    def test_createFailureInjectorFromConfig_dictFailure(self):
        """
        Given: Config with dict failure configuration
        When: Creating FailureInjector from it
        Then: Should activate with configuration
        """
        config = {
            "simulator": {
                "failures": {
                    "sensorFailure": {
                        "enabled": True,
                        "sensors": ["RPM", "SPEED"],
                    }
                }
            }
        }
        injector = createFailureInjectorFromConfig(config)

        try:
            self.assertTrue(
                injector.isFailureActive(FailureType.SENSOR_FAILURE)
            )
            self.assertEqual(
                injector.failedSensors,
                {"RPM", "SPEED"}
            )
        finally:
            injector.stopScheduler()

    def test_createFailureInjectorFromConfig_disabled(self):
        """
        Given: Config with disabled failure
        When: Creating FailureInjector from it
        Then: Should not activate
        """
        config = {
            "simulator": {
                "failures": {
                    "connectionDrop": False,
                    "sensorFailure": {
                        "enabled": False,
                    }
                }
            }
        }
        injector = createFailureInjectorFromConfig(config)

        try:
            self.assertFalse(injector.getStatus().isActive)
        finally:
            injector.stopScheduler()

    def test_getDefaultFailureInjector(self):
        """
        Given: Calling getDefaultFailureInjector
        When: Called
        Then: Should return clean injector
        """
        injector = getDefaultFailureInjector()

        try:
            self.assertFalse(injector.getStatus().isActive)
        finally:
            injector.stopScheduler()


class TestInjectorStatus(unittest.TestCase):
    """Tests for InjectorStatus dataclass."""

    def test_statusToDict(self):
        """
        Given: An InjectorStatus
        When: Converting to dictionary
        Then: Should include all fields
        """
        status = InjectorStatus(
            isActive=True,
            activeFailures=["connectionDrop"],
            scheduledFailures=2,
            totalInjected=5,
            dtcCodes=["P0300"],
        )

        result = status.toDict()

        self.assertTrue(result["isActive"])
        self.assertEqual(result["activeFailures"], ["connectionDrop"])
        self.assertEqual(result["scheduledFailures"], 2)
        self.assertEqual(result["totalInjected"], 5)
        self.assertEqual(result["dtcCodes"], ["P0300"])


class TestActiveFailure(unittest.TestCase):
    """Tests for ActiveFailure dataclass."""

    def test_activeFailureToDict(self):
        """
        Given: An ActiveFailure
        When: Converting to dictionary
        Then: Should include all fields
        """
        config = FailureConfig(sensorNames=["RPM"])
        active = ActiveFailure(
            failureType=FailureType.SENSOR_FAILURE,
            config=config,
        )

        result = active.toDict()

        self.assertEqual(result["failureType"], "sensorFailure")
        self.assertEqual(result["config"]["sensorNames"], ["RPM"])
        self.assertIsNotNone(result["activatedAt"])


if __name__ == "__main__":
    # Run tests
    unittest.main(verbosity=2)
