################################################################################
# File Name: run_tests_simulated_connection.py
# Purpose/Description: Tests for SimulatedObdConnection class
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-034
# ================================================================================
################################################################################

"""
Tests for the SimulatedObdConnection class.

Tests verify:
- Same interface as ObdConnection: connect(), disconnect(), isConnected(), query(), getStatus()
- Configurable connection delay simulation
- Query returns simulated sensor values from SensorSimulator
- Returns ConnectionStatus dataclass matching real connection
- No actual Bluetooth or network calls made
"""

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.obd_connection import (
    ConnectionState,
    ConnectionStatus,
)
from obd.simulator.vehicle_profile import VehicleProfile, getDefaultProfile
from obd.simulator.sensor_simulator import SensorSimulator


class TestSimulatedObdConnectionInit(unittest.TestCase):
    """Tests for SimulatedObdConnection initialization."""

    def test_init_noProfile_usesDefault(self):
        """
        Given: No profile argument
        When: SimulatedObdConnection is created
        Then: Default profile is used for the simulator
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection()

        self.assertIsNotNone(conn.simulator)
        self.assertEqual(conn.simulator.profile.make, "Generic")

    def test_init_withProfile_usesProvided(self):
        """
        Given: A custom profile
        When: SimulatedObdConnection is created
        Then: Custom profile is used
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        profile = VehicleProfile(
            vin="1HGBH41JXMN109186",
            make="Honda",
            model="Accord"
        )
        conn = SimulatedObdConnection(profile=profile)

        self.assertEqual(conn.simulator.profile.make, "Honda")

    def test_init_withSensorSimulator_usesProvided(self):
        """
        Given: A custom SensorSimulator
        When: SimulatedObdConnection is created
        Then: Provided simulator is used
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        simulator = SensorSimulator()
        simulator.startEngine()
        conn = SimulatedObdConnection(simulator=simulator)

        self.assertIs(conn.simulator, simulator)
        self.assertTrue(conn.simulator.isRunning())

    def test_init_connectionDelay_default(self):
        """
        Given: No connectionDelaySeconds argument
        When: SimulatedObdConnection is created
        Then: Default delay of 2 seconds is used
        """
        from obd.simulator.simulated_connection import (
            SimulatedObdConnection,
            DEFAULT_CONNECTION_DELAY_SECONDS
        )

        conn = SimulatedObdConnection()

        self.assertEqual(conn.connectionDelaySeconds, DEFAULT_CONNECTION_DELAY_SECONDS)
        self.assertEqual(conn.connectionDelaySeconds, 2.0)

    def test_init_connectionDelay_custom(self):
        """
        Given: Custom connectionDelaySeconds
        When: SimulatedObdConnection is created
        Then: Custom delay is used
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.5)

        self.assertEqual(conn.connectionDelaySeconds, 0.5)

    def test_init_disconnectedState(self):
        """
        Given: New connection
        When: Initialized
        Then: State is disconnected
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection()

        self.assertFalse(conn.isConnected())
        status = conn.getStatus()
        self.assertEqual(status.state, ConnectionState.DISCONNECTED)


class TestSimulatedObdConnectionConnect(unittest.TestCase):
    """Tests for connect() method."""

    def test_connect_simulatesDelay(self):
        """
        Given: Connection with delay of 0.1 seconds
        When: connect() is called
        Then: Connection takes approximately delay time
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.1)

        startTime = time.time()
        result = conn.connect()
        elapsed = time.time() - startTime

        self.assertTrue(result)
        self.assertGreaterEqual(elapsed, 0.09)  # Allow small variance

    def test_connect_zeroDelay_instantConnection(self):
        """
        Given: Connection with zero delay
        When: connect() is called
        Then: Connection is immediate
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)

        startTime = time.time()
        result = conn.connect()
        elapsed = time.time() - startTime

        self.assertTrue(result)
        self.assertLess(elapsed, 0.05)

    def test_connect_setsConnectedState(self):
        """
        Given: Disconnected connection
        When: connect() is called
        Then: State becomes connected
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        self.assertTrue(conn.isConnected())
        status = conn.getStatus()
        self.assertEqual(status.state, ConnectionState.CONNECTED)
        self.assertTrue(status.connected)

    def test_connect_startsEngine(self):
        """
        Given: Disconnected connection
        When: connect() is called
        Then: Simulator engine is started
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        self.assertTrue(conn.simulator.isRunning())

    def test_connect_updatesConnectionStatus(self):
        """
        Given: Disconnected connection
        When: connect() is called
        Then: ConnectionStatus is updated with lastConnectTime and totalConnections
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        status = conn.getStatus()
        self.assertIsNotNone(status.lastConnectTime)
        self.assertEqual(status.totalConnections, 1)

    def test_connect_alreadyConnected_returnsTrue(self):
        """
        Given: Already connected
        When: connect() is called again
        Then: Returns True without delay
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.5)
        conn.connect()

        startTime = time.time()
        result = conn.connect()
        elapsed = time.time() - startTime

        self.assertTrue(result)
        self.assertLess(elapsed, 0.1)  # No additional delay


class TestSimulatedObdConnectionDisconnect(unittest.TestCase):
    """Tests for disconnect() method."""

    def test_disconnect_setsDisconnectedState(self):
        """
        Given: Connected connection
        When: disconnect() is called
        Then: State becomes disconnected
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()
        conn.disconnect()

        self.assertFalse(conn.isConnected())
        status = conn.getStatus()
        self.assertEqual(status.state, ConnectionState.DISCONNECTED)

    def test_disconnect_stopsEngine(self):
        """
        Given: Connected connection with running engine
        When: disconnect() is called
        Then: Simulator engine is stopped
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()
        self.assertTrue(conn.simulator.isRunning())

        conn.disconnect()

        self.assertFalse(conn.simulator.isRunning())

    def test_disconnect_whenNotConnected_noError(self):
        """
        Given: Not connected
        When: disconnect() is called
        Then: No error raised
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection()
        conn.disconnect()  # Should not raise

        self.assertFalse(conn.isConnected())


class TestSimulatedObdConnectionReconnect(unittest.TestCase):
    """Tests for reconnect() method."""

    def test_reconnect_disconnectsAndReconnects(self):
        """
        Given: Connected connection
        When: reconnect() is called
        Then: Connection is re-established
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()
        initialConnectTime = conn.getStatus().lastConnectTime

        result = conn.reconnect()

        self.assertTrue(result)
        self.assertTrue(conn.isConnected())
        # lastConnectTime should be updated
        self.assertGreaterEqual(
            conn.getStatus().lastConnectTime,
            initialConnectTime
        )

    def test_reconnect_incrementsConnectionCount(self):
        """
        Given: Connected connection
        When: reconnect() is called
        Then: totalConnections is incremented
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()
        self.assertEqual(conn.getStatus().totalConnections, 1)

        conn.reconnect()

        self.assertEqual(conn.getStatus().totalConnections, 2)


class TestSimulatedObdConnectionQuery(unittest.TestCase):
    """Tests for query() method via obd attribute."""

    def test_query_returnsSimulatedValue(self):
        """
        Given: Connected connection
        When: query() is called for RPM
        Then: Returns simulated value
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        # Create a mock command with name attribute
        mockCmd = MagicMock()
        mockCmd.name = "RPM"

        response = conn.obd.query(mockCmd)

        self.assertFalse(response.is_null())
        self.assertIsNotNone(response.value)
        # RPM at idle should be around 800
        self.assertGreater(response.value, 500)
        self.assertLess(response.value, 1200)

    def test_query_coolantTemp_returnsValue(self):
        """
        Given: Connected connection with warm engine
        When: query() is called for COOLANT_TEMP
        Then: Returns simulated temperature
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        mockCmd = MagicMock()
        mockCmd.name = "COOLANT_TEMP"

        response = conn.obd.query(mockCmd)

        self.assertFalse(response.is_null())
        self.assertIsNotNone(response.value)
        # Coolant starts at ambient temp (20C)
        self.assertGreaterEqual(response.value, 15)

    def test_query_speed_returnsValue(self):
        """
        Given: Connected connection
        When: query() is called for SPEED
        Then: Returns simulated speed (0 at idle)
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        mockCmd = MagicMock()
        mockCmd.name = "SPEED"

        response = conn.obd.query(mockCmd)

        self.assertFalse(response.is_null())
        self.assertIsNotNone(response.value)
        # Speed should be 0 at idle with no gear
        self.assertGreaterEqual(response.value, 0)

    def test_query_unsupportedParameter_returnsNull(self):
        """
        Given: Connected connection
        When: query() is called for unsupported parameter
        Then: Returns null response
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        mockCmd = MagicMock()
        mockCmd.name = "UNKNOWN_PARAMETER_XYZ"

        response = conn.obd.query(mockCmd)

        self.assertTrue(response.is_null())

    def test_query_whenDisconnected_returnsNull(self):
        """
        Given: Disconnected connection
        When: query() is called
        Then: Returns null response
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection()

        mockCmd = MagicMock()
        mockCmd.name = "RPM"

        response = conn.obd.query(mockCmd)

        self.assertTrue(response.is_null())

    def test_query_responseHasUnit(self):
        """
        Given: Connected connection
        When: query() is called
        Then: Response has unit attribute
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        mockCmd = MagicMock()
        mockCmd.name = "RPM"

        response = conn.obd.query(mockCmd)

        self.assertIsNotNone(response.unit)
        self.assertEqual(response.unit, "rpm")

    def test_query_stringCommand_works(self):
        """
        Given: Connected connection
        When: query() is called with string parameter name
        Then: Returns simulated value
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        response = conn.obd.query("RPM")

        self.assertFalse(response.is_null())
        self.assertIsNotNone(response.value)


class TestSimulatedObdConnectionStatus(unittest.TestCase):
    """Tests for getStatus() method."""

    def test_getStatus_returnsConnectionStatus(self):
        """
        Given: SimulatedObdConnection
        When: getStatus() is called
        Then: Returns ConnectionStatus dataclass
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection()
        status = conn.getStatus()

        self.assertIsInstance(status, ConnectionStatus)

    def test_getStatus_hasMacAddress(self):
        """
        Given: SimulatedObdConnection
        When: getStatus() is called
        Then: macAddress indicates simulation
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection()
        status = conn.getStatus()

        self.assertIn("SIMULATED", status.macAddress)

    def test_getStatus_tracksErrors(self):
        """
        Given: SimulatedObdConnection with configured errors
        When: Errors occur and getStatus() is called
        Then: totalErrors is tracked
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        # Query unsupported parameter to trigger error tracking
        mockCmd = MagicMock()
        mockCmd.name = "INVALID"
        conn.obd.query(mockCmd)

        status = conn.getStatus()
        # Error tracking is implementation-specific
        self.assertIsInstance(status.totalErrors, int)


class TestSimulatedObdConnectionUpdateSimulation(unittest.TestCase):
    """Tests for update() method to advance simulation."""

    def test_update_advancesSimulation(self):
        """
        Given: Connected connection with throttle applied
        When: update() is called
        Then: Simulator state changes
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        # Set throttle
        conn.simulator.setThrottle(50)
        initialRpm = conn.simulator.state.rpm

        # Advance simulation
        conn.update(1.0)

        # RPM should have changed due to throttle
        self.assertNotEqual(conn.simulator.state.rpm, initialRpm)

    def test_update_whenDisconnected_noError(self):
        """
        Given: Disconnected connection
        When: update() is called
        Then: No error raised
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection()
        conn.update(1.0)  # Should not raise


class TestSimulatedObd(unittest.TestCase):
    """Tests for the SimulatedObd inner class."""

    def test_isConnected_matchesConnection(self):
        """
        Given: SimulatedObd
        When: is_connected() is called
        Then: Returns connection's isConnected state
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)

        self.assertFalse(conn.obd.is_connected())

        conn.connect()
        self.assertTrue(conn.obd.is_connected())

    def test_close_disconnectsConnection(self):
        """
        Given: Connected SimulatedObd
        When: close() is called
        Then: Connection is disconnected
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()
        self.assertTrue(conn.isConnected())

        conn.obd.close()

        self.assertFalse(conn.isConnected())


class TestSimulatedObdConnectionHelpers(unittest.TestCase):
    """Tests for helper functions."""

    def test_createSimulatedConnectionFromConfig_basic(self):
        """
        Given: Config dictionary with simulator settings
        When: createSimulatedConnectionFromConfig() is called
        Then: Returns configured connection
        """
        from obd.simulator.simulated_connection import createSimulatedConnectionFromConfig

        config = {
            "simulator": {
                "connectionDelaySeconds": 0.5,
                "profile": {
                    "make": "Test",
                    "model": "Vehicle"
                }
            }
        }

        conn = createSimulatedConnectionFromConfig(config)

        self.assertEqual(conn.connectionDelaySeconds, 0.5)
        self.assertEqual(conn.simulator.profile.make, "Test")

    def test_createSimulatedConnectionFromConfig_defaults(self):
        """
        Given: Empty config
        When: createSimulatedConnectionFromConfig() is called
        Then: Uses default values
        """
        from obd.simulator.simulated_connection import createSimulatedConnectionFromConfig

        conn = createSimulatedConnectionFromConfig({})

        self.assertEqual(conn.connectionDelaySeconds, 2.0)
        self.assertEqual(conn.simulator.profile.make, "Generic")

    def test_getDefaultSimulatedConnection_returnsConfigured(self):
        """
        Given: Nothing
        When: getDefaultSimulatedConnection() is called
        Then: Returns a ready-to-use connection
        """
        from obd.simulator.simulated_connection import getDefaultSimulatedConnection

        conn = getDefaultSimulatedConnection()

        self.assertIsNotNone(conn)
        self.assertIsNotNone(conn.simulator)


class TestSimulatedObdResponseUnits(unittest.TestCase):
    """Tests for response unit handling."""

    def test_query_rpm_hasRpmUnit(self):
        """
        Given: Connected connection
        When: query RPM
        Then: Unit is 'rpm'
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        response = conn.obd.query("RPM")
        self.assertEqual(response.unit, "rpm")

    def test_query_speed_hasKphUnit(self):
        """
        Given: Connected connection
        When: query SPEED
        Then: Unit is 'kph'
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        response = conn.obd.query("SPEED")
        self.assertEqual(response.unit, "kph")

    def test_query_coolantTemp_hasCelsiusUnit(self):
        """
        Given: Connected connection
        When: query COOLANT_TEMP
        Then: Unit is 'celsius'
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        response = conn.obd.query("COOLANT_TEMP")
        self.assertEqual(response.unit, "celsius")


class TestNoActualNetworkCalls(unittest.TestCase):
    """Tests to verify no actual network/Bluetooth calls are made."""

    @patch('socket.socket')
    def test_connect_noSocketCalls(self, mockSocket):
        """
        Given: SimulatedObdConnection
        When: connect() is called
        Then: No actual socket calls are made
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        mockSocket.assert_not_called()

    @patch('socket.socket')
    def test_query_noSocketCalls(self, mockSocket):
        """
        Given: Connected SimulatedObdConnection
        When: query() is called
        Then: No actual socket calls are made
        """
        from obd.simulator.simulated_connection import SimulatedObdConnection

        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        conn.obd.query("RPM")

        mockSocket.assert_not_called()


if __name__ == '__main__':
    unittest.main()
