################################################################################
# File Name: simulated_connection.py
# Purpose/Description: Simulated OBD-II connection for testing without hardware
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-034
# ================================================================================
################################################################################

"""
Simulated OBD-II connection module for testing without hardware.

Provides:
- SimulatedObdConnection class matching ObdConnection interface
- connect(), disconnect(), isConnected(), query(), getStatus() methods
- Simulated sensor values from SensorSimulator
- Configurable connection delay simulation

This module allows testing the full OBD-II data pipeline without requiring
actual vehicle hardware or Bluetooth connectivity.

Usage:
    from obd.simulator.simulated_connection import SimulatedObdConnection

    # Create simulated connection
    conn = SimulatedObdConnection(connectionDelaySeconds=0.0)

    # Connect (starts simulator engine)
    if conn.connect():
        # Query simulated values
        response = conn.obd.query("RPM")
        print(f"Simulated RPM: {response.value}")

    # Disconnect
    conn.disconnect()
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from ..obd_connection import ConnectionState, ConnectionStatus
from .sensor_simulator import SensorSimulator
from .vehicle_profile import VehicleProfile, getDefaultProfile

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# Default connection delay in seconds (simulates Bluetooth pairing time)
DEFAULT_CONNECTION_DELAY_SECONDS = 2.0

# Simulated MAC address prefix
SIMULATED_MAC_ADDRESS = "SIMULATED:00:11:22:33:44:55"

# Parameter unit mapping
PARAMETER_UNITS: Dict[str, str] = {
    "RPM": "rpm",
    "SPEED": "kph",
    "COOLANT_TEMP": "celsius",
    "THROTTLE_POS": "percent",
    "ENGINE_LOAD": "percent",
    "MAF": "gps",
    "INTAKE_TEMP": "celsius",
    "OIL_TEMP": "celsius",
    "INTAKE_PRESSURE": "kPa",
    "FUEL_PRESSURE": "kPa",
    "TIMING_ADVANCE": "degree",
    "O2_B1S1": "volt",
    "O2_B1S2": "volt",
    "O2_B2S1": "volt",
    "O2_B2S2": "volt",
    "SHORT_FUEL_TRIM_1": "percent",
    "LONG_FUEL_TRIM_1": "percent",
    "SHORT_FUEL_TRIM_2": "percent",
    "LONG_FUEL_TRIM_2": "percent",
    "RUN_TIME": "second",
    "CONTROL_MODULE_VOLTAGE": "volt",
    "BAROMETRIC_PRESSURE": "kPa",
    "AMBIANT_AIR_TEMP": "celsius",
    "FUEL_RATE": "lph",
    "COMMANDED_EQUIV_RATIO": "ratio",
    "RELATIVE_THROTTLE_POS": "percent",
    "THROTTLE_ACTUATOR": "percent",
    "ACCELERATOR_POS_D": "percent",
    "ACCELERATOR_POS_E": "percent",
    "ABS_LOAD": "percent",
    "COMMANDED_THROTTLE_ACTUATOR": "percent",
    "COMMANDED_EGR": "percent",
    "EGR_ERROR": "percent",
    "EVAPORATIVE_PURGE": "percent",
    "CATALYST_TEMP_B1S1": "celsius",
    "CATALYST_TEMP_B2S1": "celsius",
    "CATALYST_TEMP_B1S2": "celsius",
    "CATALYST_TEMP_B2S2": "celsius",
    "HYBRID_BATTERY_REMAINING": "percent",
    "ETHANOL_PERCENT": "percent",
}


# ================================================================================
# Simulated Response Classes
# ================================================================================

@dataclass
class SimulatedResponse:
    """
    Simulated OBD-II response matching python-OBD response interface.

    Attributes:
        value: The sensor value (or None if null)
        unit: Unit of measurement
        _isNull: Whether this is a null response
    """

    value: Optional[float] = None
    unit: Optional[str] = None
    _isNull: bool = False

    def is_null(self) -> bool:
        """Check if response is null (no data available)."""
        return self._isNull

    @classmethod
    def null(cls) -> "SimulatedResponse":
        """Create a null response."""
        return cls(value=None, unit=None, _isNull=True)


# ================================================================================
# SimulatedObd Class
# ================================================================================

class SimulatedObd:
    """
    Simulated OBD interface matching python-OBD OBD class interface.

    This class provides the same interface as obd.OBD but returns
    simulated values from the SensorSimulator.
    """

    def __init__(self, connection: "SimulatedObdConnection") -> None:
        """
        Initialize SimulatedObd.

        Args:
            connection: Parent SimulatedObdConnection instance
        """
        self._connection = connection

    def query(self, cmd: Any) -> SimulatedResponse:
        """
        Query a simulated OBD-II parameter.

        Args:
            cmd: OBD command object with .name attribute, or string parameter name

        Returns:
            SimulatedResponse with value and unit, or null response
        """
        # Check if connected
        if not self._connection.isConnected():
            logger.debug("Query failed: not connected")
            return SimulatedResponse.null()

        # Extract parameter name from command
        if isinstance(cmd, str):
            paramName = cmd.upper()
        elif hasattr(cmd, 'name'):
            paramName = cmd.name.upper()
        else:
            logger.warning(f"Unknown command type: {type(cmd)}")
            return SimulatedResponse.null()

        # Get value from simulator
        value = self._connection.simulator.getValue(paramName)

        if value is None:
            logger.debug(f"Parameter not supported: {paramName}")
            return SimulatedResponse.null()

        # Get unit for this parameter
        unit = PARAMETER_UNITS.get(paramName, "")

        logger.debug(f"Simulated query: {paramName} = {value} {unit}")

        return SimulatedResponse(value=value, unit=unit)

    def is_connected(self) -> bool:
        """Check if connected."""
        return self._connection.isConnected()

    def close(self) -> None:
        """Close the connection."""
        self._connection.disconnect()


# ================================================================================
# SimulatedObdConnection Class
# ================================================================================

class SimulatedObdConnection:
    """
    Simulated OBD-II connection for testing without hardware.

    Implements the same interface as ObdConnection but uses SensorSimulator
    to generate realistic sensor values without any actual Bluetooth or
    network connectivity.

    Attributes:
        simulator: SensorSimulator instance for generating values
        connectionDelaySeconds: Simulated connection delay time
        obd: SimulatedObd instance for query interface

    Example:
        conn = SimulatedObdConnection(connectionDelaySeconds=0.0)
        conn.connect()

        # Query simulated RPM
        response = conn.obd.query("RPM")
        print(f"RPM: {response.value}")

        conn.disconnect()
    """

    def __init__(
        self,
        profile: Optional[VehicleProfile] = None,
        simulator: Optional[SensorSimulator] = None,
        connectionDelaySeconds: float = DEFAULT_CONNECTION_DELAY_SECONDS,
        config: Optional[Dict[str, Any]] = None,
        database: Optional[Any] = None
    ) -> None:
        """
        Initialize SimulatedObdConnection.

        Args:
            profile: Vehicle profile for simulator (uses default if None)
            simulator: Existing SensorSimulator (creates new if None)
            connectionDelaySeconds: Simulated delay for connect() in seconds
            config: Optional configuration dictionary (for compatibility)
            database: Optional database instance (for compatibility, not used)
        """
        # Set up simulator
        if simulator is not None:
            self.simulator = simulator
        elif profile is not None:
            self.simulator = SensorSimulator(profile=profile)
        else:
            self.simulator = SensorSimulator()

        self.connectionDelaySeconds = connectionDelaySeconds
        self.config = config or {}
        self.database = database

        # Create simulated OBD interface
        self.obd = SimulatedObd(self)

        # Connection state tracking
        self._status = ConnectionStatus(
            state=ConnectionState.DISCONNECTED,
            macAddress=SIMULATED_MAC_ADDRESS,
            connected=False
        )

        logger.debug(
            f"SimulatedObdConnection initialized | "
            f"delay={connectionDelaySeconds}s | "
            f"profile={self.simulator.profile}"
        )

    def getStatus(self) -> ConnectionStatus:
        """
        Get current connection status.

        Returns:
            ConnectionStatus with current state information
        """
        return self._status

    def isConnected(self) -> bool:
        """
        Check if connection is active.

        Returns:
            True if connected, False otherwise
        """
        return self._status.connected

    def connect(self) -> bool:
        """
        Connect to simulated OBD-II (starts simulator engine).

        Simulates connection delay and starts the simulator engine.

        Returns:
            True (simulated connection always succeeds)
        """
        # Already connected
        if self._status.connected:
            logger.debug("Already connected")
            return True

        self._status.state = ConnectionState.CONNECTING
        logger.info(
            f"Connecting to simulated OBD-II | delay={self.connectionDelaySeconds}s"
        )

        # Simulate connection delay
        if self.connectionDelaySeconds > 0:
            time.sleep(self.connectionDelaySeconds)

        # Start simulator engine
        self.simulator.startEngine()

        # Update status
        self._status.state = ConnectionState.CONNECTED
        self._status.connected = True
        self._status.lastConnectTime = datetime.now()
        self._status.totalConnections += 1
        self._status.retryCount = 0

        logger.info("Connected to simulated OBD-II")
        return True

    def disconnect(self) -> None:
        """
        Disconnect from simulated OBD-II (stops simulator engine).
        """
        if not self._status.connected:
            logger.debug("Already disconnected")
            return

        logger.info("Disconnecting from simulated OBD-II")

        # Stop simulator engine
        self.simulator.stopEngine()

        # Update status
        self._status.state = ConnectionState.DISCONNECTED
        self._status.connected = False

        logger.info("Disconnected from simulated OBD-II")

    def reconnect(self) -> bool:
        """
        Reconnect to simulated OBD-II.

        Disconnects if connected, then connects again.

        Returns:
            True (simulated connection always succeeds)
        """
        logger.info("Reconnecting to simulated OBD-II")
        self._status.state = ConnectionState.RECONNECTING

        self.disconnect()
        return self.connect()

    def update(self, deltaSeconds: float) -> None:
        """
        Advance the simulation by a time delta.

        This should be called periodically to update simulated sensor values.

        Args:
            deltaSeconds: Time delta in seconds
        """
        if self._status.connected:
            self.simulator.update(deltaSeconds)


# ================================================================================
# Helper Functions
# ================================================================================

def createSimulatedConnectionFromConfig(
    config: Dict[str, Any],
    database: Optional[Any] = None
) -> SimulatedObdConnection:
    """
    Create a SimulatedObdConnection from configuration.

    Args:
        config: Configuration dictionary, may contain 'simulator' section
        database: Optional database instance (for compatibility)

    Returns:
        Configured SimulatedObdConnection instance

    Example:
        config = {
            "simulator": {
                "connectionDelaySeconds": 0.5,
                "profile": {"make": "Honda", "model": "Civic"}
            }
        }
        conn = createSimulatedConnectionFromConfig(config)
    """
    simConfig = config.get("simulator", {})

    # Get connection delay
    connectionDelay = simConfig.get(
        "connectionDelaySeconds",
        DEFAULT_CONNECTION_DELAY_SECONDS
    )

    # Get profile data if present
    profileData = simConfig.get("profile", {})
    profile = None
    if profileData:
        profile = VehicleProfile.fromDict(profileData)

    return SimulatedObdConnection(
        profile=profile,
        connectionDelaySeconds=connectionDelay,
        config=config,
        database=database
    )


def getDefaultSimulatedConnection() -> SimulatedObdConnection:
    """
    Get a default SimulatedObdConnection ready for use.

    Returns:
        SimulatedObdConnection with default settings
    """
    return SimulatedObdConnection()
