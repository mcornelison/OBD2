################################################################################
# File Name: __init__.py
# Purpose/Description: OBD-II Simulator package initialization
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-035
# ================================================================================
################################################################################

"""
OBD-II Simulator Package.

This package provides simulation capabilities for testing the Eclipse OBD-II
system without actual vehicle hardware.

Modules:
- vehicle_profile: Vehicle configuration dataclass and loading functions
- sensor_simulator: Physics-based sensor value simulation
- simulated_connection: Simulated OBD-II connection matching real interface
- drive_scenario: Pre-defined drive scenarios for repeatable test cycles
- failure_injector: Failure injection system for testing error handling
- simulator_status: Simulator status display and monitoring

Usage:
    from obd.simulator import VehicleProfile, loadProfile, getDefaultProfile
    from obd.simulator import SensorSimulator, getDefaultSensorSimulator
    from obd.simulator import SimulatedObdConnection, getDefaultSimulatedConnection
    from obd.simulator import DriveScenario, DrivePhase, DriveScenarioRunner
    from obd.simulator import FailureInjector, FailureType, FailureConfig
    from obd.simulator import SimulatorStatus, getSimulatorStatus
"""

from .drive_scenario import (
    DrivePhase,
    DriveScenario,
    DriveScenarioError,
    DriveScenarioRunner,
    ScenarioLoadError,
    ScenarioState,
    ScenarioValidationError,
    createScenarioFromConfig,
    ensureScenariosDirectory,
    getBuiltInScenario,
    getCityDrivingScenario,
    getColdStartScenario,
    getDefaultScenario,
    getFullCycleScenario,
    getHighwayCruiseScenario,
    getScenariosDirectory,
    initializeBuiltInScenarios,
    listAvailableScenarios,
    loadScenario,
    saveScenario,
)
from .failure_injector import (
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
from .sensor_simulator import (
    EngineState,
    SensorSimulator,
    VehicleState,
    createSensorSimulatorFromConfig,
    getDefaultSensorSimulator,
)
from .simulated_connection import (
    DEFAULT_CONNECTION_DELAY_SECONDS,
    PARAMETER_UNITS,
    SimulatedObd,
    SimulatedObdConnection,
    SimulatedResponse,
    createSimulatedConnectionFromConfig,
    getDefaultSimulatedConnection,
)
from .simulated_vin_decoder import (
    SimulatedVinDecoder,
    SimulatedVinDecoderError,
    SimulatedVinDecodeResult,
    SimulatedVinStorageError,
    createSimulatedVinDecoderFromConfig,
    createVinDecoderForSimulation,
    isSimulatedDecodeResult,
)
from .simulator_cli import (
    COMMAND_CLEAR,
    COMMAND_FAILURE,
    COMMAND_HELP,
    COMMAND_PAUSE,
    COMMAND_QUIT,
    COMMAND_STATUS,
    VALID_COMMANDS,
    CliState,
    CommandResult,
    CommandType,
    SimulatorCli,
    createSimulatorCli,
    createSimulatorCliFromConfig,
)
from .simulator_status import (
    SimulatorStatus,
    SimulatorStatusProvider,
    createSimulatorStatusProvider,
    getSimulatorStatus,
)
from .vehicle_profile import (
    VALID_FUEL_TYPES,
    VehicleProfile,
    VehicleProfileError,
    VehicleProfileLoadError,
    VehicleProfileValidationError,
    createProfileFromConfig,
    getDefaultProfile,
    getDefaultProfilePath,
    getProfilesDirectory,
    listAvailableProfiles,
    loadDefaultProfileFromFile,
    loadProfile,
    saveProfile,
)

__all__ = [
    # Vehicle Profile
    "VehicleProfile",
    "VehicleProfileError",
    "VehicleProfileLoadError",
    "VehicleProfileValidationError",
    "loadProfile",
    "getDefaultProfile",
    "getProfilesDirectory",
    "getDefaultProfilePath",
    "loadDefaultProfileFromFile",
    "listAvailableProfiles",
    "saveProfile",
    "createProfileFromConfig",
    "VALID_FUEL_TYPES",
    # Sensor Simulator
    "SensorSimulator",
    "VehicleState",
    "EngineState",
    "createSensorSimulatorFromConfig",
    "getDefaultSensorSimulator",
    # Simulated Connection
    "SimulatedObdConnection",
    "SimulatedObd",
    "SimulatedResponse",
    "createSimulatedConnectionFromConfig",
    "getDefaultSimulatedConnection",
    "DEFAULT_CONNECTION_DELAY_SECONDS",
    "PARAMETER_UNITS",
    # Drive Scenario
    "DrivePhase",
    "DriveScenario",
    "DriveScenarioError",
    "DriveScenarioRunner",
    "ScenarioLoadError",
    "ScenarioState",
    "ScenarioValidationError",
    "createScenarioFromConfig",
    "ensureScenariosDirectory",
    "getBuiltInScenario",
    "getCityDrivingScenario",
    "getColdStartScenario",
    "getDefaultScenario",
    "getFullCycleScenario",
    "getHighwayCruiseScenario",
    "getScenariosDirectory",
    "initializeBuiltInScenarios",
    "listAvailableScenarios",
    "loadScenario",
    "saveScenario",
    # Failure Injector
    "ActiveFailure",
    "FailureConfig",
    "FailureInjector",
    "FailureState",
    "FailureType",
    "InjectorStatus",
    "ScheduledFailure",
    "createFailureInjectorFromConfig",
    "getDefaultFailureInjector",
    "COMMON_DTC_CODES",
    "DEFAULT_INTERMITTENT_PROBABILITY",
    "DEFAULT_OUT_OF_RANGE_FACTOR",
    # Simulator Status
    "SimulatorStatus",
    "SimulatorStatusProvider",
    "getSimulatorStatus",
    "createSimulatorStatusProvider",
    # Simulated VIN Decoder
    "SimulatedVinDecoder",
    "SimulatedVinDecodeResult",
    "SimulatedVinDecoderError",
    "SimulatedVinStorageError",
    "createSimulatedVinDecoderFromConfig",
    "createVinDecoderForSimulation",
    "isSimulatedDecodeResult",
    # Simulator CLI
    "SimulatorCli",
    "CliState",
    "CommandType",
    "CommandResult",
    "createSimulatorCli",
    "createSimulatorCliFromConfig",
    "COMMAND_PAUSE",
    "COMMAND_FAILURE",
    "COMMAND_CLEAR",
    "COMMAND_STATUS",
    "COMMAND_QUIT",
    "COMMAND_HELP",
    "VALID_COMMANDS",
]
