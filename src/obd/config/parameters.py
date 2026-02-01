################################################################################
# File Name: parameters.py
# Purpose/Description: OBD-II parameter definitions organized by type
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation (US-002)
# ================================================================================
################################################################################

"""
OBD-II Parameter definitions.

Provides comprehensive definitions of all available OBD-II parameters
organized by type (static vs realtime). Parameter names correspond to
python-OBD library command names.

Usage:
    from src.obd.config.parameters import (
        STATIC_PARAMETERS,
        REALTIME_PARAMETERS,
        ALL_PARAMETERS
    )
"""


from .types import ParameterInfo

# =============================================================================
# Static Parameters - Queried once per VIN/vehicle
# =============================================================================

STATIC_PARAMETERS: dict[str, ParameterInfo] = {
    # Vehicle Identification
    'VIN': ParameterInfo(
        name='VIN',
        description='Vehicle Identification Number',
        unit=None,
        category='identification',
        isStatic=True,
        defaultLogData=True
    ),
    'CALIBRATION_ID': ParameterInfo(
        name='CALIBRATION_ID',
        description='ECU Calibration ID',
        unit=None,
        category='identification',
        isStatic=True,
        defaultLogData=True
    ),
    'CVN': ParameterInfo(
        name='CVN',
        description='Calibration Verification Number',
        unit=None,
        category='identification',
        isStatic=True,
        defaultLogData=True
    ),
    'ECU_NAME': ParameterInfo(
        name='ECU_NAME',
        description='ECU Name',
        unit=None,
        category='identification',
        isStatic=True,
        defaultLogData=True
    ),

    # Fuel System
    'FUEL_TYPE': ParameterInfo(
        name='FUEL_TYPE',
        description='Fuel Type (gasoline, diesel, etc.)',
        unit=None,
        category='fuel',
        isStatic=True,
        defaultLogData=True
    ),
    'FUEL_STATUS': ParameterInfo(
        name='FUEL_STATUS',
        description='Fuel System Status',
        unit=None,
        category='fuel',
        isStatic=True,
        defaultLogData=True
    ),

    # OBD System
    'OBD_COMPLIANCE': ParameterInfo(
        name='OBD_COMPLIANCE',
        description='OBD Standards Compliance',
        unit=None,
        category='system',
        isStatic=True,
        defaultLogData=True
    ),
    'PIDS_A': ParameterInfo(
        name='PIDS_A',
        description='Supported PIDs [01-20]',
        unit=None,
        category='system',
        isStatic=True,
        defaultLogData=False
    ),
    'PIDS_B': ParameterInfo(
        name='PIDS_B',
        description='Supported PIDs [21-40]',
        unit=None,
        category='system',
        isStatic=True,
        defaultLogData=False
    ),
    'PIDS_C': ParameterInfo(
        name='PIDS_C',
        description='Supported PIDs [41-60]',
        unit=None,
        category='system',
        isStatic=True,
        defaultLogData=False
    ),

    # Diagnostic Trouble Codes
    'STATUS': ParameterInfo(
        name='STATUS',
        description='Status since DTCs cleared',
        unit=None,
        category='diagnostics',
        isStatic=True,
        defaultLogData=True
    ),
    'FREEZE_DTC': ParameterInfo(
        name='FREEZE_DTC',
        description='Freeze DTC',
        unit=None,
        category='diagnostics',
        isStatic=True,
        defaultLogData=True
    ),
    'GET_DTC': ParameterInfo(
        name='GET_DTC',
        description='Get Diagnostic Trouble Codes',
        unit=None,
        category='diagnostics',
        isStatic=True,
        defaultLogData=True
    ),
    'GET_CURRENT_DTC': ParameterInfo(
        name='GET_CURRENT_DTC',
        description='Get Current Diagnostic Trouble Codes',
        unit=None,
        category='diagnostics',
        isStatic=True,
        defaultLogData=True
    ),
}


# =============================================================================
# Realtime Parameters - Continuously monitored
# =============================================================================

REALTIME_PARAMETERS: dict[str, ParameterInfo] = {
    # Engine Core
    'RPM': ParameterInfo(
        name='RPM',
        description='Engine RPM',
        unit='rpm',
        category='engine',
        isStatic=False,
        defaultLogData=True
    ),
    'SPEED': ParameterInfo(
        name='SPEED',
        description='Vehicle Speed',
        unit='km/h',
        category='engine',
        isStatic=False,
        defaultLogData=True
    ),
    'ENGINE_LOAD': ParameterInfo(
        name='ENGINE_LOAD',
        description='Calculated Engine Load',
        unit='%',
        category='engine',
        isStatic=False,
        defaultLogData=True
    ),
    'THROTTLE_POS': ParameterInfo(
        name='THROTTLE_POS',
        description='Throttle Position',
        unit='%',
        category='engine',
        isStatic=False,
        defaultLogData=True
    ),
    'THROTTLE_ACTUATOR': ParameterInfo(
        name='THROTTLE_ACTUATOR',
        description='Throttle Actuator Position',
        unit='%',
        category='engine',
        isStatic=False,
        defaultLogData=False
    ),
    'RELATIVE_THROTTLE_POS': ParameterInfo(
        name='RELATIVE_THROTTLE_POS',
        description='Relative Throttle Position',
        unit='%',
        category='engine',
        isStatic=False,
        defaultLogData=False
    ),
    'ACCELERATOR_POS_D': ParameterInfo(
        name='ACCELERATOR_POS_D',
        description='Accelerator Pedal Position D',
        unit='%',
        category='engine',
        isStatic=False,
        defaultLogData=False
    ),
    'ACCELERATOR_POS_E': ParameterInfo(
        name='ACCELERATOR_POS_E',
        description='Accelerator Pedal Position E',
        unit='%',
        category='engine',
        isStatic=False,
        defaultLogData=False
    ),
    'RUN_TIME': ParameterInfo(
        name='RUN_TIME',
        description='Engine Run Time',
        unit='seconds',
        category='engine',
        isStatic=False,
        defaultLogData=True
    ),

    # Temperature
    'COOLANT_TEMP': ParameterInfo(
        name='COOLANT_TEMP',
        description='Engine Coolant Temperature',
        unit='°C',
        category='temperature',
        isStatic=False,
        defaultLogData=True
    ),
    'INTAKE_TEMP': ParameterInfo(
        name='INTAKE_TEMP',
        description='Intake Air Temperature',
        unit='°C',
        category='temperature',
        isStatic=False,
        defaultLogData=True
    ),
    'AMBIANT_AIR_TEMP': ParameterInfo(
        name='AMBIANT_AIR_TEMP',
        description='Ambient Air Temperature',
        unit='°C',
        category='temperature',
        isStatic=False,
        defaultLogData=False
    ),
    'OIL_TEMP': ParameterInfo(
        name='OIL_TEMP',
        description='Engine Oil Temperature',
        unit='°C',
        category='temperature',
        isStatic=False,
        defaultLogData=True
    ),
    'CATALYST_TEMP_B1S1': ParameterInfo(
        name='CATALYST_TEMP_B1S1',
        description='Catalyst Temperature Bank 1 Sensor 1',
        unit='°C',
        category='temperature',
        isStatic=False,
        defaultLogData=False
    ),
    'CATALYST_TEMP_B2S1': ParameterInfo(
        name='CATALYST_TEMP_B2S1',
        description='Catalyst Temperature Bank 2 Sensor 1',
        unit='°C',
        category='temperature',
        isStatic=False,
        defaultLogData=False
    ),
    'CATALYST_TEMP_B1S2': ParameterInfo(
        name='CATALYST_TEMP_B1S2',
        description='Catalyst Temperature Bank 1 Sensor 2',
        unit='°C',
        category='temperature',
        isStatic=False,
        defaultLogData=False
    ),
    'CATALYST_TEMP_B2S2': ParameterInfo(
        name='CATALYST_TEMP_B2S2',
        description='Catalyst Temperature Bank 2 Sensor 2',
        unit='°C',
        category='temperature',
        isStatic=False,
        defaultLogData=False
    ),

    # Pressure
    'INTAKE_PRESSURE': ParameterInfo(
        name='INTAKE_PRESSURE',
        description='Intake Manifold Pressure',
        unit='kPa',
        category='pressure',
        isStatic=False,
        defaultLogData=True
    ),
    'BAROMETRIC_PRESSURE': ParameterInfo(
        name='BAROMETRIC_PRESSURE',
        description='Barometric Pressure',
        unit='kPa',
        category='pressure',
        isStatic=False,
        defaultLogData=False
    ),
    'FUEL_PRESSURE': ParameterInfo(
        name='FUEL_PRESSURE',
        description='Fuel Pressure',
        unit='kPa',
        category='pressure',
        isStatic=False,
        defaultLogData=True
    ),
    'FUEL_RAIL_PRESSURE_DIRECT': ParameterInfo(
        name='FUEL_RAIL_PRESSURE_DIRECT',
        description='Fuel Rail Pressure (direct inject)',
        unit='kPa',
        category='pressure',
        isStatic=False,
        defaultLogData=False
    ),
    'FUEL_RAIL_PRESSURE_VAC': ParameterInfo(
        name='FUEL_RAIL_PRESSURE_VAC',
        description='Fuel Rail Pressure (vacuum referenced)',
        unit='kPa',
        category='pressure',
        isStatic=False,
        defaultLogData=False
    ),
    'EVAP_VAPOR_PRESSURE': ParameterInfo(
        name='EVAP_VAPOR_PRESSURE',
        description='Evaporative System Vapor Pressure',
        unit='Pa',
        category='pressure',
        isStatic=False,
        defaultLogData=False
    ),
    'EVAP_VAPOR_PRESSURE_ALT': ParameterInfo(
        name='EVAP_VAPOR_PRESSURE_ALT',
        description='Evaporative System Vapor Pressure (Alt)',
        unit='Pa',
        category='pressure',
        isStatic=False,
        defaultLogData=False
    ),
    'EVAP_VAPOR_PRESSURE_ABS': ParameterInfo(
        name='EVAP_VAPOR_PRESSURE_ABS',
        description='Evaporative System Vapor Pressure (Abs)',
        unit='kPa',
        category='pressure',
        isStatic=False,
        defaultLogData=False
    ),

    # Air/Fuel
    'MAF': ParameterInfo(
        name='MAF',
        description='Mass Air Flow Rate',
        unit='g/s',
        category='airfuel',
        isStatic=False,
        defaultLogData=True
    ),
    'SHORT_FUEL_TRIM_1': ParameterInfo(
        name='SHORT_FUEL_TRIM_1',
        description='Short Term Fuel Trim Bank 1',
        unit='%',
        category='airfuel',
        isStatic=False,
        defaultLogData=True
    ),
    'LONG_FUEL_TRIM_1': ParameterInfo(
        name='LONG_FUEL_TRIM_1',
        description='Long Term Fuel Trim Bank 1',
        unit='%',
        category='airfuel',
        isStatic=False,
        defaultLogData=True
    ),
    'SHORT_FUEL_TRIM_2': ParameterInfo(
        name='SHORT_FUEL_TRIM_2',
        description='Short Term Fuel Trim Bank 2',
        unit='%',
        category='airfuel',
        isStatic=False,
        defaultLogData=False
    ),
    'LONG_FUEL_TRIM_2': ParameterInfo(
        name='LONG_FUEL_TRIM_2',
        description='Long Term Fuel Trim Bank 2',
        unit='%',
        category='airfuel',
        isStatic=False,
        defaultLogData=False
    ),
    'COMMANDED_EQUIV_RATIO': ParameterInfo(
        name='COMMANDED_EQUIV_RATIO',
        description='Commanded Equivalence Ratio (lambda)',
        unit='ratio',
        category='airfuel',
        isStatic=False,
        defaultLogData=True
    ),
    'FUEL_INJECT_TIMING': ParameterInfo(
        name='FUEL_INJECT_TIMING',
        description='Fuel Injection Timing',
        unit='°',
        category='airfuel',
        isStatic=False,
        defaultLogData=False
    ),
    'FUEL_RATE': ParameterInfo(
        name='FUEL_RATE',
        description='Engine Fuel Rate',
        unit='L/h',
        category='airfuel',
        isStatic=False,
        defaultLogData=True
    ),

    # Oxygen Sensors
    'O2_B1S1': ParameterInfo(
        name='O2_B1S1',
        description='O2 Sensor Bank 1 Sensor 1',
        unit='V',
        category='oxygen',
        isStatic=False,
        defaultLogData=True
    ),
    'O2_B1S2': ParameterInfo(
        name='O2_B1S2',
        description='O2 Sensor Bank 1 Sensor 2',
        unit='V',
        category='oxygen',
        isStatic=False,
        defaultLogData=False
    ),
    'O2_B1S3': ParameterInfo(
        name='O2_B1S3',
        description='O2 Sensor Bank 1 Sensor 3',
        unit='V',
        category='oxygen',
        isStatic=False,
        defaultLogData=False
    ),
    'O2_B1S4': ParameterInfo(
        name='O2_B1S4',
        description='O2 Sensor Bank 1 Sensor 4',
        unit='V',
        category='oxygen',
        isStatic=False,
        defaultLogData=False
    ),
    'O2_B2S1': ParameterInfo(
        name='O2_B2S1',
        description='O2 Sensor Bank 2 Sensor 1',
        unit='V',
        category='oxygen',
        isStatic=False,
        defaultLogData=False
    ),
    'O2_B2S2': ParameterInfo(
        name='O2_B2S2',
        description='O2 Sensor Bank 2 Sensor 2',
        unit='V',
        category='oxygen',
        isStatic=False,
        defaultLogData=False
    ),
    'O2_S1_WR_CURRENT': ParameterInfo(
        name='O2_S1_WR_CURRENT',
        description='O2 Sensor 1 Wide Range Current',
        unit='mA',
        category='oxygen',
        isStatic=False,
        defaultLogData=False
    ),
    'O2_S2_WR_CURRENT': ParameterInfo(
        name='O2_S2_WR_CURRENT',
        description='O2 Sensor 2 Wide Range Current',
        unit='mA',
        category='oxygen',
        isStatic=False,
        defaultLogData=False
    ),
    'O2_S1_WR_VOLTAGE': ParameterInfo(
        name='O2_S1_WR_VOLTAGE',
        description='O2 Sensor 1 Wide Range Voltage',
        unit='V',
        category='oxygen',
        isStatic=False,
        defaultLogData=False
    ),
    'O2_S2_WR_VOLTAGE': ParameterInfo(
        name='O2_S2_WR_VOLTAGE',
        description='O2 Sensor 2 Wide Range Voltage',
        unit='V',
        category='oxygen',
        isStatic=False,
        defaultLogData=False
    ),

    # Timing
    'TIMING_ADVANCE': ParameterInfo(
        name='TIMING_ADVANCE',
        description='Ignition Timing Advance',
        unit='°',
        category='timing',
        isStatic=False,
        defaultLogData=True
    ),

    # EGR (Exhaust Gas Recirculation)
    'COMMANDED_EGR': ParameterInfo(
        name='COMMANDED_EGR',
        description='Commanded EGR',
        unit='%',
        category='egr',
        isStatic=False,
        defaultLogData=False
    ),
    'EGR_ERROR': ParameterInfo(
        name='EGR_ERROR',
        description='EGR Error',
        unit='%',
        category='egr',
        isStatic=False,
        defaultLogData=False
    ),

    # EVAP System
    'EVAPORATIVE_PURGE': ParameterInfo(
        name='EVAPORATIVE_PURGE',
        description='Evaporative Purge',
        unit='%',
        category='evap',
        isStatic=False,
        defaultLogData=False
    ),

    # Distance
    'DISTANCE_SINCE_DTC_CLEAR': ParameterInfo(
        name='DISTANCE_SINCE_DTC_CLEAR',
        description='Distance Traveled Since DTCs Cleared',
        unit='km',
        category='distance',
        isStatic=False,
        defaultLogData=False
    ),
    'DISTANCE_W_MIL': ParameterInfo(
        name='DISTANCE_W_MIL',
        description='Distance Traveled With MIL On',
        unit='km',
        category='distance',
        isStatic=False,
        defaultLogData=False
    ),

    # Time
    'TIME_SINCE_DTC_CLEARED': ParameterInfo(
        name='TIME_SINCE_DTC_CLEARED',
        description='Time Since DTCs Cleared',
        unit='minutes',
        category='time',
        isStatic=False,
        defaultLogData=False
    ),
    'RUN_TIME_MIL': ParameterInfo(
        name='RUN_TIME_MIL',
        description='Run Time With MIL On',
        unit='minutes',
        category='time',
        isStatic=False,
        defaultLogData=False
    ),
    'WARMUPS_SINCE_DTC_CLEAR': ParameterInfo(
        name='WARMUPS_SINCE_DTC_CLEAR',
        description='Warm-Ups Since DTCs Cleared',
        unit='count',
        category='time',
        isStatic=False,
        defaultLogData=False
    ),

    # Battery/Electrical
    'CONTROL_MODULE_VOLTAGE': ParameterInfo(
        name='CONTROL_MODULE_VOLTAGE',
        description='Control Module Voltage',
        unit='V',
        category='electrical',
        isStatic=False,
        defaultLogData=True
    ),

    # Additional Engine Parameters
    'RELATIVE_ACCEL_POS': ParameterInfo(
        name='RELATIVE_ACCEL_POS',
        description='Relative Accelerator Pedal Position',
        unit='%',
        category='engine',
        isStatic=False,
        defaultLogData=False
    ),
    'HYBRID_BATTERY_REMAINING': ParameterInfo(
        name='HYBRID_BATTERY_REMAINING',
        description='Hybrid Battery Remaining',
        unit='%',
        category='electrical',
        isStatic=False,
        defaultLogData=False
    ),
    'ABS_LOAD': ParameterInfo(
        name='ABS_LOAD',
        description='Absolute Load Value',
        unit='%',
        category='engine',
        isStatic=False,
        defaultLogData=False
    ),
    'COMMANDED_THROTTLE_ACTUATOR': ParameterInfo(
        name='COMMANDED_THROTTLE_ACTUATOR',
        description='Commanded Throttle Actuator',
        unit='%',
        category='engine',
        isStatic=False,
        defaultLogData=False
    ),
    'ETHANOL_PERCENT': ParameterInfo(
        name='ETHANOL_PERCENT',
        description='Ethanol Fuel %',
        unit='%',
        category='fuel',
        isStatic=False,
        defaultLogData=False
    ),
}


# =============================================================================
# Combined parameter dictionary
# =============================================================================

ALL_PARAMETERS: dict[str, ParameterInfo] = {**STATIC_PARAMETERS, **REALTIME_PARAMETERS}
