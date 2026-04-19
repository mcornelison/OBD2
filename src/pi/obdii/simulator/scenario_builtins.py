################################################################################
# File Name: scenario_builtins.py
# Purpose/Description: Built-in drive scenario definitions (default/cold_start/city/highway/full_cycle)
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-037
# 2026-04-14    | Sweep 5       | Extracted from drive_scenario.py (task 4 split)
# ================================================================================
################################################################################

"""
Built-in scenario definitions used to generate the JSON scenario files.

Each function returns a fresh DriveScenario instance — callers may mutate
without affecting other callers.
"""

from .scenario_types import DrivePhase, DriveScenario


def getDefaultScenario() -> DriveScenario:
    """
    Get a simple default scenario.

    Returns:
        DriveScenario with basic warmup/idle/drive/stop phases
    """
    return DriveScenario(
        name="default",
        description="Simple default scenario for testing",
        phases=[
            DrivePhase(
                name="warmup",
                durationSeconds=30.0,
                targetRpm=800,
                targetThrottle=0,
                description="Engine warmup at idle"
            ),
            DrivePhase(
                name="drive",
                durationSeconds=60.0,
                targetRpm=2500,
                targetThrottle=30,
                targetGear=3,
                description="Light driving"
            ),
            DrivePhase(
                name="stop",
                durationSeconds=10.0,
                targetRpm=800,
                targetThrottle=0,
                targetGear=0,
                description="Return to idle"
            ),
        ],
        loopCount=0,
    )


def getColdStartScenario() -> DriveScenario:
    """Get cold start scenario definition."""
    return DriveScenario(
        name="cold_start",
        description="Simulates cold engine start and warmup cycle",
        phases=[
            DrivePhase(
                name="engine_start",
                durationSeconds=5.0,
                targetRpm=1200,
                targetThrottle=5,
                description="Initial startup with cold fast idle"
            ),
            DrivePhase(
                name="cold_idle",
                durationSeconds=60.0,
                targetRpm=1000,
                targetThrottle=0,
                description="Cold idle warmup - RPM slowly drops as engine warms"
            ),
            DrivePhase(
                name="warm_idle",
                durationSeconds=30.0,
                targetRpm=800,
                targetThrottle=0,
                description="Warmed up idle"
            ),
        ],
        loopCount=0,
    )


def getCityDrivingScenario() -> DriveScenario:
    """Get city driving scenario definition."""
    return DriveScenario(
        name="city_driving",
        description="Simulates typical city driving with stops and acceleration",
        phases=[
            DrivePhase(
                name="idle_start",
                durationSeconds=5.0,
                targetRpm=800,
                targetThrottle=0,
                targetGear=0,
                description="Stopped at traffic light"
            ),
            DrivePhase(
                name="accelerate_1st",
                durationSeconds=3.0,
                targetRpm=3000,
                targetThrottle=40,
                targetGear=1,
                description="Accelerate from stop in 1st gear"
            ),
            DrivePhase(
                name="shift_2nd",
                durationSeconds=4.0,
                targetRpm=2500,
                targetThrottle=35,
                targetGear=2,
                description="Shift to 2nd, continue accelerating"
            ),
            DrivePhase(
                name="shift_3rd",
                durationSeconds=5.0,
                targetRpm=2500,
                targetThrottle=30,
                targetGear=3,
                description="Shift to 3rd, cruise at city speed"
            ),
            DrivePhase(
                name="cruise",
                durationSeconds=15.0,
                targetRpm=2000,
                targetThrottle=25,
                targetGear=3,
                description="Cruise at ~50 km/h"
            ),
            DrivePhase(
                name="slow_down",
                durationSeconds=5.0,
                targetRpm=1500,
                targetThrottle=5,
                targetGear=2,
                description="Slow for traffic/light"
            ),
            DrivePhase(
                name="stop",
                durationSeconds=10.0,
                targetRpm=800,
                targetThrottle=0,
                targetGear=0,
                description="Stopped at traffic light"
            ),
        ],
        loopCount=3,  # Repeat 3 times
    )


def getHighwayCruiseScenario() -> DriveScenario:
    """Get highway cruise scenario definition."""
    return DriveScenario(
        name="highway_cruise",
        description="Simulates highway on-ramp and cruise",
        phases=[
            DrivePhase(
                name="on_ramp_entry",
                durationSeconds=5.0,
                targetRpm=3500,
                targetThrottle=60,
                targetGear=3,
                description="Entering on-ramp, accelerating"
            ),
            DrivePhase(
                name="on_ramp_merge",
                durationSeconds=8.0,
                targetRpm=5000,
                targetThrottle=80,
                targetGear=4,
                description="Accelerating to highway speed for merge"
            ),
            DrivePhase(
                name="merge_complete",
                durationSeconds=5.0,
                targetRpm=3500,
                targetThrottle=50,
                targetGear=5,
                description="Shift to 5th, settling into cruise"
            ),
            DrivePhase(
                name="highway_cruise",
                durationSeconds=120.0,
                targetRpm=3000,
                targetThrottle=35,
                targetGear=5,
                description="Steady highway cruise at ~120 km/h"
            ),
            DrivePhase(
                name="exit_decel",
                durationSeconds=10.0,
                targetRpm=2000,
                targetThrottle=10,
                targetGear=4,
                description="Exiting highway, decelerating"
            ),
            DrivePhase(
                name="exit_ramp",
                durationSeconds=8.0,
                targetRpm=1500,
                targetThrottle=15,
                targetGear=3,
                description="On exit ramp"
            ),
        ],
        loopCount=0,
    )


def getFullCycleScenario() -> DriveScenario:
    """Get full cycle scenario (cold start + city + highway)."""
    return DriveScenario(
        name="full_cycle",
        description="Complete drive cycle: cold start, city driving, highway cruise",
        phases=[
            # Cold start
            DrivePhase(
                name="engine_start",
                durationSeconds=5.0,
                targetRpm=1200,
                targetThrottle=5,
                description="Cold engine start"
            ),
            DrivePhase(
                name="cold_warmup",
                durationSeconds=45.0,
                targetRpm=1000,
                targetThrottle=0,
                description="Cold idle warmup"
            ),
            # City portion
            DrivePhase(
                name="city_start",
                durationSeconds=3.0,
                targetRpm=2500,
                targetThrottle=35,
                targetGear=1,
                description="Leave driveway"
            ),
            DrivePhase(
                name="neighborhood",
                durationSeconds=30.0,
                targetRpm=2000,
                targetThrottle=25,
                targetGear=2,
                description="Driving through neighborhood"
            ),
            DrivePhase(
                name="city_street",
                durationSeconds=45.0,
                targetRpm=2500,
                targetThrottle=30,
                targetGear=3,
                description="City street driving"
            ),
            DrivePhase(
                name="traffic_stop",
                durationSeconds=20.0,
                targetRpm=800,
                targetThrottle=0,
                targetGear=0,
                description="Stopped in traffic"
            ),
            # Highway portion
            DrivePhase(
                name="on_ramp",
                durationSeconds=10.0,
                targetRpm=4500,
                targetThrottle=70,
                targetGear=4,
                description="Highway on-ramp acceleration"
            ),
            DrivePhase(
                name="highway_merge",
                durationSeconds=5.0,
                targetRpm=3500,
                targetThrottle=45,
                targetGear=5,
                description="Merging onto highway"
            ),
            DrivePhase(
                name="highway_cruise",
                durationSeconds=180.0,
                targetRpm=3000,
                targetThrottle=35,
                targetGear=5,
                description="Highway cruise"
            ),
            DrivePhase(
                name="highway_exit",
                durationSeconds=15.0,
                targetRpm=1800,
                targetThrottle=15,
                targetGear=4,
                description="Exiting highway"
            ),
            # Return city portion
            DrivePhase(
                name="return_city",
                durationSeconds=30.0,
                targetRpm=2000,
                targetThrottle=25,
                targetGear=3,
                description="City driving back"
            ),
            DrivePhase(
                name="arrival",
                durationSeconds=15.0,
                targetRpm=1500,
                targetThrottle=15,
                targetGear=2,
                description="Arriving at destination"
            ),
            DrivePhase(
                name="park",
                durationSeconds=10.0,
                targetRpm=800,
                targetThrottle=0,
                targetGear=0,
                description="Parked, idling"
            ),
        ],
        loopCount=0,
    )
