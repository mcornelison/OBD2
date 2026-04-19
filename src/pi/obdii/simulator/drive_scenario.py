################################################################################
# File Name: drive_scenario.py
# Purpose/Description: Backwards-compatible facade re-exporting the drive scenario system
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-037
# 2026-04-14    | Sweep 5       | Split into scenario_* modules; file is now a facade
# ================================================================================
################################################################################

"""
Drive scenario module facade (legacy import path).

The implementation now lives in sibling modules:
- scenario_types: exceptions, enum, DrivePhase, DriveScenario dataclasses
- scenario_runner: DriveScenarioRunner (execution engine)
- scenario_builtins: hard-coded scenario definitions
- scenario_loader: file I/O, built-in JSON materialization

This file remains as a compatibility shim so existing imports continue to work:

    from obd.simulator.drive_scenario import DriveScenario, DriveScenarioRunner

Prefer importing directly from the specific module in new code.
"""

from .scenario_builtins import (
    getCityDrivingScenario,
    getColdStartScenario,
    getDefaultScenario,
    getFullCycleScenario,
    getHighwayCruiseScenario,
)
from .scenario_loader import (
    createScenarioFromConfig,
    ensureScenariosDirectory,
    getBuiltInScenario,
    getScenariosDirectory,
    initializeBuiltInScenarios,
    listAvailableScenarios,
    loadScenario,
    saveScenario,
)
from .scenario_runner import DriveScenarioRunner
from .scenario_types import (
    DEFAULT_TRANSITION_RATE_RPM_PER_SEC,
    DEFAULT_TRANSITION_RATE_SPEED_PER_SEC,
    DEFAULT_TRANSITION_RATE_THROTTLE_PER_SEC,
    SCENARIOS_DIR_NAME,
    DrivePhase,
    DriveScenario,
    DriveScenarioError,
    ScenarioLoadError,
    ScenarioState,
    ScenarioValidationError,
)

__all__ = [
    "DEFAULT_TRANSITION_RATE_RPM_PER_SEC",
    "DEFAULT_TRANSITION_RATE_SPEED_PER_SEC",
    "DEFAULT_TRANSITION_RATE_THROTTLE_PER_SEC",
    "SCENARIOS_DIR_NAME",
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
]
