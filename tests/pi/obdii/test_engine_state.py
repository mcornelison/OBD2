################################################################################
# File Name: test_engine_state.py
# Purpose/Description: TDD test suite for src.pi.obdii.engine_state --
#                      EngineState enum + EngineStateMachine transitions
#                      (US-200 Spool Data v2 Story 2).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Tests for the engine state machine.

Spool Priority 3 spec (via US-200):
    UNKNOWN -> CRANKING (RPM 0 -> >=250) -> RUNNING
    RUNNING -> KEY_OFF (RPM=0 AND speed=0 for 30s continuous OR explicit disconnect)
    On CRANKING transition -> generate new drive_id (monotonic).
    Write it to every subsequent row until KEY_OFF.
    Next CRANKING -> new drive_id.

Invariants honored:
    - Monotonic drive_id via injectable generator (no Pi wall-clock ms)
    - Debounced transitions -- brief RPM spikes don't falsely start drives
    - State machine is RPM/speed-driven; disconnect is one input, not primary
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.pi.obdii.engine_state import (
    EngineState,
    EngineStateMachine,
    EngineStateTransition,
)

# ================================================================================
# Test fixtures
# ================================================================================

class _MonotonicDriveIdGenerator:
    """Test-grade drive_id generator; starts at 1, increments on each call."""

    def __init__(self, start: int = 1) -> None:
        self._next = start
        self.calls = 0

    def __call__(self) -> int:
        value = self._next
        self._next += 1
        self.calls += 1
        return value


@pytest.fixture
def baseTime() -> datetime:
    return datetime(2026, 4, 19, 12, 0, 0)


@pytest.fixture
def driveIdGen() -> _MonotonicDriveIdGenerator:
    return _MonotonicDriveIdGenerator()


@pytest.fixture
def machine(driveIdGen: _MonotonicDriveIdGenerator) -> EngineStateMachine:
    return EngineStateMachine(
        crankingRpmThreshold=250.0,
        runningRpmThreshold=500.0,
        keyOffDurationSeconds=30.0,
        driveIdGenerator=driveIdGen,
    )


# ================================================================================
# Initial state
# ================================================================================

class TestInitialState:
    def test_startsInUnknownState(self, machine: EngineStateMachine) -> None:
        assert machine.state == EngineState.UNKNOWN

    def test_noActiveDriveIdInitially(self, machine: EngineStateMachine) -> None:
        assert machine.currentDriveId is None

    def test_zeroTransitionsInitially(self, machine: EngineStateMachine) -> None:
        assert machine.transitionCount == 0


# ================================================================================
# UNKNOWN -> CRANKING (RPM crosses crankingRpmThreshold)
# ================================================================================

class TestCrankingTransition:
    def test_rpmZeroStaysUnknown(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        machine.observeReading(rpm=0, speed=0, now=baseTime)
        assert machine.state == EngineState.UNKNOWN
        assert machine.currentDriveId is None

    def test_rpmBelowCrankingStaysUnknown(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        machine.observeReading(rpm=200, speed=0, now=baseTime)
        assert machine.state == EngineState.UNKNOWN

    def test_rpmAtCrankingThresholdTransitions(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        transition = machine.observeReading(rpm=250, speed=0, now=baseTime)
        assert machine.state == EngineState.CRANKING
        assert transition is not None
        assert transition.fromState == EngineState.UNKNOWN
        assert transition.toState == EngineState.CRANKING

    def test_rpmAboveCrankingAssignsDriveId(
        self,
        machine: EngineStateMachine,
        baseTime: datetime,
        driveIdGen: _MonotonicDriveIdGenerator,
    ) -> None:
        machine.observeReading(rpm=300, speed=0, now=baseTime)
        assert machine.currentDriveId == 1
        assert driveIdGen.calls == 1

    def test_crankTransitionCarriesDriveId(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        transition = machine.observeReading(rpm=300, speed=0, now=baseTime)
        assert transition is not None
        assert transition.driveId == 1

    def test_rpmNoneDoesNotTransition(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        transition = machine.observeReading(rpm=None, speed=None, now=baseTime)
        assert transition is None
        assert machine.state == EngineState.UNKNOWN


# ================================================================================
# CRANKING -> RUNNING (RPM climbs above runningRpmThreshold)
# ================================================================================

class TestRunningTransition:
    def test_rpmCrossesRunningThreshold(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        machine.observeReading(rpm=300, speed=0, now=baseTime)
        transition = machine.observeReading(
            rpm=800, speed=0, now=baseTime + timedelta(seconds=2)
        )
        assert machine.state == EngineState.RUNNING
        assert transition is not None
        assert transition.fromState == EngineState.CRANKING
        assert transition.toState == EngineState.RUNNING

    def test_driveIdPersistsAcrossCrankToRunning(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        machine.observeReading(rpm=300, speed=0, now=baseTime)
        machine.observeReading(rpm=800, speed=0, now=baseTime + timedelta(seconds=2))
        assert machine.currentDriveId == 1

    def test_runningTransitionEmitsNoNewDriveId(
        self,
        machine: EngineStateMachine,
        baseTime: datetime,
        driveIdGen: _MonotonicDriveIdGenerator,
    ) -> None:
        machine.observeReading(rpm=300, speed=0, now=baseTime)
        machine.observeReading(rpm=800, speed=0, now=baseTime + timedelta(seconds=2))
        # drive_id generator called exactly once -- on CRANKING entry
        assert driveIdGen.calls == 1


# ================================================================================
# RUNNING -> KEY_OFF (30-second debounce on RPM=0 AND speed=0)
# ================================================================================

class TestKeyOffDebounce:
    def _driveIntoRunning(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> datetime:
        machine.observeReading(rpm=300, speed=0, now=baseTime)
        lastTime = baseTime + timedelta(seconds=2)
        machine.observeReading(rpm=800, speed=0, now=lastTime)
        return lastTime

    def test_briefRpmZeroDoesNotTriggerKeyOff(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        lastTime = self._driveIntoRunning(machine, baseTime)
        # RPM drops to zero briefly (10 seconds)
        machine.observeReading(rpm=0, speed=0, now=lastTime + timedelta(seconds=10))
        assert machine.state == EngineState.RUNNING
        assert machine.currentDriveId == 1

    def test_rpmNonzeroResetsDebounce(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        lastTime = self._driveIntoRunning(machine, baseTime)
        # 20s of zeros, then a spike, then 20s more of zeros -- total 40s but not continuous
        machine.observeReading(rpm=0, speed=0, now=lastTime + timedelta(seconds=5))
        machine.observeReading(rpm=0, speed=0, now=lastTime + timedelta(seconds=20))
        machine.observeReading(rpm=800, speed=0, now=lastTime + timedelta(seconds=25))
        machine.observeReading(rpm=0, speed=0, now=lastTime + timedelta(seconds=30))
        machine.observeReading(rpm=0, speed=0, now=lastTime + timedelta(seconds=50))
        assert machine.state == EngineState.RUNNING

    def test_thirtySecondsOfZeroTriggersKeyOff(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        lastTime = self._driveIntoRunning(machine, baseTime)
        machine.observeReading(rpm=0, speed=0, now=lastTime + timedelta(seconds=5))
        transition = machine.observeReading(
            rpm=0, speed=0, now=lastTime + timedelta(seconds=36)
        )
        assert machine.state == EngineState.KEY_OFF
        assert transition is not None
        assert transition.fromState == EngineState.RUNNING
        assert transition.toState == EngineState.KEY_OFF

    def test_keyOffClearsDriveId(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        lastTime = self._driveIntoRunning(machine, baseTime)
        machine.observeReading(rpm=0, speed=0, now=lastTime + timedelta(seconds=5))
        machine.observeReading(rpm=0, speed=0, now=lastTime + timedelta(seconds=36))
        assert machine.currentDriveId is None

    def test_speedNonzeroBlocksKeyOff(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        """RPM=0 but vehicle still rolling (e.g. coasting downhill in neutral)."""
        lastTime = self._driveIntoRunning(machine, baseTime)
        # 60 seconds of rpm=0 but speed=10 -- should NOT transition to KEY_OFF
        for offset in range(0, 60, 5):
            machine.observeReading(
                rpm=0, speed=10, now=lastTime + timedelta(seconds=offset)
            )
        assert machine.state == EngineState.RUNNING

    def test_keyOffTransitionCarriesClosedDriveId(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        lastTime = self._driveIntoRunning(machine, baseTime)
        machine.observeReading(rpm=0, speed=0, now=lastTime + timedelta(seconds=5))
        transition = machine.observeReading(
            rpm=0, speed=0, now=lastTime + timedelta(seconds=36)
        )
        assert transition is not None
        # Transition carries the drive_id that was just CLOSED
        assert transition.driveId == 1


# ================================================================================
# Restart cycle -- each true engine-off = new drive_id
# ================================================================================

class TestRestartCycle:
    def test_secondCrankAssignsNewDriveId(
        self,
        machine: EngineStateMachine,
        baseTime: datetime,
        driveIdGen: _MonotonicDriveIdGenerator,
    ) -> None:
        # Drive 1: crank, run, key off
        machine.observeReading(rpm=300, speed=0, now=baseTime)
        machine.observeReading(rpm=800, speed=0, now=baseTime + timedelta(seconds=2))
        machine.observeReading(rpm=0, speed=0, now=baseTime + timedelta(seconds=100))
        machine.observeReading(rpm=0, speed=0, now=baseTime + timedelta(seconds=135))
        assert machine.state == EngineState.KEY_OFF
        # Drive 2: crank again
        machine.observeReading(
            rpm=300, speed=0, now=baseTime + timedelta(seconds=300)
        )
        assert machine.state == EngineState.CRANKING
        assert machine.currentDriveId == 2
        assert driveIdGen.calls == 2

    def test_stallMidDriveThenRestart(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        """Stall + restart within 30s still yields TWO drives per Spool spec.

        Actually per spec: 'each true engine-off event = new drive'. A stall
        that triggers KEY_OFF (30s of rpm=0 speed=0) is a true engine-off.
        A stall that doesn't (engine stops but CIO cranks again within
        30s) stays in the same drive because we never reached KEY_OFF.
        """
        machine.observeReading(rpm=300, speed=0, now=baseTime)
        machine.observeReading(rpm=800, speed=0, now=baseTime + timedelta(seconds=2))
        # Stall: rpm=0 for 15 seconds then crank restart
        machine.observeReading(rpm=0, speed=0, now=baseTime + timedelta(seconds=10))
        machine.observeReading(rpm=0, speed=0, now=baseTime + timedelta(seconds=15))
        machine.observeReading(rpm=300, speed=0, now=baseTime + timedelta(seconds=20))
        # We were still in RUNNING (never reached 30s debounce) -- same drive
        assert machine.currentDriveId == 1


# ================================================================================
# forceKeyOff (external disconnect signal)
# ================================================================================

class TestForceKeyOff:
    def test_forceKeyOffFromRunning(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        machine.observeReading(rpm=300, speed=0, now=baseTime)
        machine.observeReading(rpm=800, speed=0, now=baseTime + timedelta(seconds=2))
        transition = machine.forceKeyOff(baseTime + timedelta(seconds=10))
        assert machine.state == EngineState.KEY_OFF
        assert machine.currentDriveId is None
        assert transition is not None
        assert transition.toState == EngineState.KEY_OFF
        assert transition.driveId == 1

    def test_forceKeyOffFromCranking(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        machine.observeReading(rpm=300, speed=0, now=baseTime)
        assert machine.state == EngineState.CRANKING
        transition = machine.forceKeyOff(baseTime + timedelta(seconds=5))
        assert machine.state == EngineState.KEY_OFF
        assert machine.currentDriveId is None
        assert transition is not None

    def test_forceKeyOffFromUnknownIsNoop(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        transition = machine.forceKeyOff(baseTime)
        assert transition is None
        assert machine.state == EngineState.UNKNOWN

    def test_forceKeyOffFromKeyOffIsNoop(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        # Drive to KEY_OFF first
        machine.observeReading(rpm=300, speed=0, now=baseTime)
        machine.observeReading(rpm=800, speed=0, now=baseTime + timedelta(seconds=2))
        machine.observeReading(rpm=0, speed=0, now=baseTime + timedelta(seconds=50))
        machine.observeReading(rpm=0, speed=0, now=baseTime + timedelta(seconds=80))
        assert machine.state == EngineState.KEY_OFF
        transition = machine.forceKeyOff(baseTime + timedelta(seconds=90))
        assert transition is None


# ================================================================================
# Configuration
# ================================================================================

class TestConfiguration:
    def test_customCrankingThresholdRespected(
        self, driveIdGen: _MonotonicDriveIdGenerator, baseTime: datetime
    ) -> None:
        m = EngineStateMachine(
            crankingRpmThreshold=400.0,
            runningRpmThreshold=600.0,
            keyOffDurationSeconds=30.0,
            driveIdGenerator=driveIdGen,
        )
        # 300 RPM below our custom crank threshold of 400
        m.observeReading(rpm=300, speed=0, now=baseTime)
        assert m.state == EngineState.UNKNOWN
        m.observeReading(rpm=450, speed=0, now=baseTime + timedelta(seconds=1))
        assert m.state == EngineState.CRANKING

    def test_customKeyOffDurationRespected(
        self, driveIdGen: _MonotonicDriveIdGenerator, baseTime: datetime
    ) -> None:
        m = EngineStateMachine(
            crankingRpmThreshold=250.0,
            runningRpmThreshold=500.0,
            keyOffDurationSeconds=10.0,
            driveIdGenerator=driveIdGen,
        )
        m.observeReading(rpm=300, speed=0, now=baseTime)
        m.observeReading(rpm=800, speed=0, now=baseTime + timedelta(seconds=2))
        m.observeReading(rpm=0, speed=0, now=baseTime + timedelta(seconds=3))
        m.observeReading(rpm=0, speed=0, now=baseTime + timedelta(seconds=15))
        assert m.state == EngineState.KEY_OFF

    def test_defaultDriveIdGeneratorRaisesOnCrank(
        self, baseTime: datetime
    ) -> None:
        """No generator provided -> observe raises at drive_id assignment time."""
        m = EngineStateMachine(
            crankingRpmThreshold=250.0,
            runningRpmThreshold=500.0,
            keyOffDurationSeconds=30.0,
            driveIdGenerator=None,
        )
        with pytest.raises(RuntimeError, match="drive[_ ]id generator"):
            m.observeReading(rpm=300, speed=0, now=baseTime)


# ================================================================================
# Transition event contract
# ================================================================================

class TestTransitionEvent:
    def test_noTransitionReturnsNone(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        assert machine.observeReading(rpm=0, speed=0, now=baseTime) is None

    def test_stateChangeReturnsTransitionEvent(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        t = machine.observeReading(rpm=300, speed=0, now=baseTime)
        assert isinstance(t, EngineStateTransition)
        assert t.timestamp == baseTime

    def test_transitionCountIncrementsOnEachChange(
        self, machine: EngineStateMachine, baseTime: datetime
    ) -> None:
        machine.observeReading(rpm=300, speed=0, now=baseTime)
        machine.observeReading(rpm=800, speed=0, now=baseTime + timedelta(seconds=2))
        assert machine.transitionCount == 2
