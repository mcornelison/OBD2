################################################################################
# File Name: test_power_down_tick_thread_health.py
# Purpose/Description: US-265 (Sprint 22) -- discriminator A test surface for the
#                      PowerDownOrchestrator tick-thread liveness health-check.
#                      Hypothesis A from Spool's discriminator truth-table:
#                      after Drain Test 6, the dedicated _powerDownTickThread
#                      may silently never start, or start but die immediately.
#                      US-265 ships an in-loop liveness probe that snapshots
#                      orchestrator.tickCount on a 60s cadence, logs ERROR +
#                      raises an alarm event when the count is unchanged
#                      while on BATTERY (the only state where ticks MUST
#                      advance), and stays silent on AC. These tests would
#                      FAIL against pre-US-265 code because the
#                      _checkTickThreadHealth helper, the
#                      tickHealthCheckIntervalS constructor parameter,
#                      and the tickHealthAlarmCount property did not exist.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-02    | Rex (US-265) | Initial -- discriminator A liveness tests.
#                              | Mocks at PowerDownOrchestrator.tick level per
#                              | Sprint 19 lesson (the right level).  Each test
#                              | is a runtime-validation gate: would FAIL
#                              | against pre-fix code per
#                              | feedback_runtime_validation_required.md.
# ================================================================================
################################################################################

"""US-265 PowerDownOrchestrator tick-thread liveness health-check tests.

Test fidelity per Sprint 19+ runtime-validation rule
----------------------------------------------------
After Drain 6 we know "fast suite green" is necessary-not-sufficient for
discharge-ladder fixes.  These tests are written so each one would FAIL
against the pre-US-265 HardwareManager:

* :meth:`HardwareManager._checkTickThreadHealth` does not exist pre-fix
  -> ``AttributeError``.
* The ``tickHealthCheckIntervalS`` constructor parameter does not exist
  pre-fix -> ``TypeError``.
* The ``tickHealthAlarmCount`` property does not exist pre-fix ->
  ``AttributeError``.

They map 1:1 to the discriminator-A row of Spool's truth-table: if
``pd_tick_count`` stays at 0 throughout Drain 7 the dedicated tick thread
never advanced.  The health-check would have caught that 60s into the
drain on the Pi instead of waiting for the post-mortem CSV inspection.
"""

from __future__ import annotations

import logging
import threading
import time
from unittest.mock import MagicMock

import pytest

from src.pi.hardware.hardware_manager import HardwareManager
from src.pi.hardware.ups_monitor import PowerSource

# ================================================================================
# Helper-method tests: drive _checkTickThreadHealth directly.
# ================================================================================


class TestCheckTickThreadHealthHelper:
    """Tests for the synchronous health-check helper.

    The helper is the discriminator surface: callers (the tick loop)
    pass in a snapshot of (currentTickCount, isBattery) and the helper
    decides whether the alarm fires.  Driving the helper directly keeps
    the tests deterministic and avoids sleeping the tick loop.
    """

    def _makeManagerWithSeed(
        self,
        *,
        intervalS: float,
        priorOnBattery: bool,
        priorTickCount: int,
        ageS: float,
    ) -> HardwareManager:
        """Construct a HardwareManager with the snapshot state pre-seeded.

        Args:
            intervalS: ``tickHealthCheckIntervalS`` to pass to the
                constructor (0.0 disables the throttle so the check
                always runs; 60.0 is the production default).
            priorOnBattery: Value of ``_lastTickHealthCheckOnBattery``
                at the start of the next check.  True simulates "we were
                on battery during the prior window."
            priorTickCount: Value of ``_lastTickHealthCheckCount`` at
                the start of the next check.
            ageS: Seconds to subtract from monotonic clock for the
                seed value of ``_lastTickHealthCheckMono``.  Larger
                than ``intervalS`` -> window has elapsed.
        """
        manager = HardwareManager(tickHealthCheckIntervalS=intervalS)
        manager._lastTickHealthCheckOnBattery = priorOnBattery
        manager._lastTickHealthCheckCount = priorTickCount
        manager._lastTickHealthCheckMono = time.monotonic() - ageS
        return manager

    def test_unchangedTickCountOnBattery_raisesAlarmAndLogsError(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Pre-fix code never logged this; this assertion would FAIL."""
        manager = self._makeManagerWithSeed(
            intervalS=0.0,
            priorOnBattery=True,
            priorTickCount=0,
            ageS=1.0,
        )

        with caplog.at_level(
            logging.ERROR, logger='src.pi.hardware.hardware_manager',
        ):
            alarmRaised = manager._checkTickThreadHealth(
                currentTickCount=0, isBattery=True,
            )

        assert alarmRaised is True
        assert manager.tickHealthAlarmCount == 1
        errorRecords = [
            r for r in caplog.records if r.levelno == logging.ERROR
        ]
        assert any(
            'liveness alarm' in r.message.lower()
            or 'tick liveness' in r.message.lower()
            for r in errorRecords
        ), f"expected ERROR liveness alarm in caplog; got {errorRecords!r}"

    def test_onAcAlways_noAlarmEvenWithStalledTickCount(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Invariant: health-check fires only on BATTERY (no AC false-positives)."""
        manager = self._makeManagerWithSeed(
            intervalS=0.0,
            priorOnBattery=False,
            priorTickCount=0,
            ageS=1.0,
        )

        with caplog.at_level(
            logging.ERROR, logger='src.pi.hardware.hardware_manager',
        ):
            alarmRaised = manager._checkTickThreadHealth(
                currentTickCount=0, isBattery=False,
            )

        assert alarmRaised is False
        assert manager.tickHealthAlarmCount == 0
        errorRecords = [
            r for r in caplog.records if r.levelno == logging.ERROR
        ]
        assert not errorRecords, (
            f"expected zero ERROR records on AC; got {errorRecords!r}"
        )

    def test_tickCountIncrementedOnBattery_noAlarmInfoOk(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Healthy path: tickCount advanced -> no alarm, INFO log of delta."""
        manager = self._makeManagerWithSeed(
            intervalS=0.0,
            priorOnBattery=True,
            priorTickCount=100,
            ageS=1.0,
        )

        with caplog.at_level(
            logging.INFO, logger='src.pi.hardware.hardware_manager',
        ):
            alarmRaised = manager._checkTickThreadHealth(
                currentTickCount=112, isBattery=True,
            )

        assert alarmRaised is False
        assert manager.tickHealthAlarmCount == 0
        assert any(
            'health' in r.message.lower() and r.levelno == logging.INFO
            for r in caplog.records
        )

    def test_priorWindowAcNowBattery_noAlarmFirstWindow(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Just-transitioned to BATTERY: the prior window was AC so we
        cannot compare; no alarm raised on the first BATTERY window."""
        manager = self._makeManagerWithSeed(
            intervalS=0.0,
            priorOnBattery=False,
            priorTickCount=0,
            ageS=1.0,
        )

        alarmRaised = manager._checkTickThreadHealth(
            currentTickCount=0, isBattery=True,
        )

        assert alarmRaised is False
        assert manager.tickHealthAlarmCount == 0
        # Snapshot was advanced so the next window is comparable.
        assert manager._lastTickHealthCheckOnBattery is True

    def test_windowNotElapsed_skipsCheckAndPreservesSnapshot(self) -> None:
        """Throttle: when the configured interval has not elapsed since
        the last snapshot, the check returns immediately without altering
        state and without raising an alarm."""
        manager = self._makeManagerWithSeed(
            intervalS=60.0,
            priorOnBattery=True,
            priorTickCount=42,
            ageS=0.0,
        )

        alarmRaised = manager._checkTickThreadHealth(
            currentTickCount=999, isBattery=True,
        )

        assert alarmRaised is False
        assert manager.tickHealthAlarmCount == 0
        # Snapshot count and on-battery flag preserved -- the check did
        # NOT advance the window.
        assert manager._lastTickHealthCheckCount == 42
        assert manager._lastTickHealthCheckOnBattery is True

    def test_alarmCountAccumulatesAcrossUnhealthyChecks(self) -> None:
        """Multiple consecutive unhealthy windows accumulate alarms."""
        manager = self._makeManagerWithSeed(
            intervalS=0.0,
            priorOnBattery=True,
            priorTickCount=0,
            ageS=1.0,
        )

        for _ in range(3):
            manager._checkTickThreadHealth(
                currentTickCount=0, isBattery=True,
            )

        assert manager.tickHealthAlarmCount == 3


# ================================================================================
# Property surface tests
# ================================================================================


class TestTickHealthAlarmCountProperty:
    """``tickHealthAlarmCount`` is a public read-only counter."""

    def test_propertyDefaultsToZero(self) -> None:
        manager = HardwareManager()
        assert manager.tickHealthAlarmCount == 0

    def test_propertyReflectsInternalCounter(self) -> None:
        manager = HardwareManager()
        manager._tickHealthAlarmCount = 7
        assert manager.tickHealthAlarmCount == 7


class TestTickHealthCheckIntervalSConstructorParam:
    """``tickHealthCheckIntervalS`` constructor parameter (US-265)."""

    def test_defaultIs60SecondsPerSpec(self) -> None:
        manager = HardwareManager()
        assert manager._tickHealthCheckIntervalS == pytest.approx(60.0)

    def test_overrideAcceptedAndStored(self) -> None:
        manager = HardwareManager(tickHealthCheckIntervalS=10.0)
        assert manager._tickHealthCheckIntervalS == pytest.approx(10.0)


# ================================================================================
# Tick-loop integration tests (full _powerDownTickLoop body)
# ================================================================================


class TestTickLoopHealthCheckIntegration:
    """Drive ``_powerDownTickLoop`` end-to-end with mocked UPS + orchestrator.

    Uses the existing pattern from
    ``tests/pi/power/test_staged_shutdown_actually_fires.py``: build the
    manager via ``__new__`` and stub only the attributes the loop reads.
    """

    def _runOneIterationLoop(
        self,
        *,
        powerSource: PowerSource,
        tickIsNoop: bool,
        intervalS: float = 0.0,
    ) -> HardwareManager:
        """Spin the loop briefly with a mocked UPS + orchestrator.

        Returns the manager so the caller can read ``tickHealthAlarmCount``.
        """
        mockUps = MagicMock()
        mockUps.getTelemetry.return_value = {
            'voltage': 3.80,
            'percentage': 50,
            'powerSource': powerSource,
            'chargeRatePctPerHr': -10.0,
        }

        mockOrch = MagicMock()
        if tickIsNoop:
            mockOrch.tick = MagicMock()  # no-op; counter never advances
            mockOrch.tickCount = 0
        else:
            tickCounter = {'n': 0}

            def realTick(**kwargs: object) -> None:
                tickCounter['n'] += 1

            mockOrch.tick.side_effect = realTick
            type(mockOrch).tickCount = property(
                lambda self: tickCounter['n']
            )

        manager = HardwareManager.__new__(HardwareManager)
        manager._upsMonitor = mockUps
        manager._powerDownOrchestrator = mockOrch
        manager._shutdownHandler = None
        manager._stopEvent = threading.Event()
        manager._pollInterval = 0.01
        manager._tickHealthCheckIntervalS = intervalS
        manager._lastTickHealthCheckMono = time.monotonic() - 1.0
        manager._lastTickHealthCheckCount = 0
        manager._lastTickHealthCheckOnBattery = (
            powerSource == PowerSource.BATTERY
        )
        manager._tickHealthAlarmCount = 0

        thread = threading.Thread(
            target=manager._powerDownTickLoop, daemon=True,
        )
        thread.start()
        time.sleep(0.05)
        manager._stopEvent.set()
        thread.join(timeout=1.0)
        return manager

    def test_loopTidLoggedAtEntryForJournalctlCorrelation(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Acceptance #2: loop entry logs ``tid=<id>`` so journalctl
        confirms the thread actually started.  Pre-fix code logged at
        DEBUG without a tid -- this assertion would FAIL."""
        manager = HardwareManager.__new__(HardwareManager)
        manager._upsMonitor = None
        manager._powerDownOrchestrator = None
        manager._shutdownHandler = None
        manager._stopEvent = threading.Event()
        manager._stopEvent.set()  # exit immediately after entry log
        manager._pollInterval = 0.01
        manager._tickHealthCheckIntervalS = 0.0
        manager._lastTickHealthCheckMono = time.monotonic()
        manager._lastTickHealthCheckCount = 0
        manager._lastTickHealthCheckOnBattery = False
        manager._tickHealthAlarmCount = 0

        with caplog.at_level(
            logging.INFO, logger='src.pi.hardware.hardware_manager',
        ):
            manager._powerDownTickLoop()

        assert any(
            'tid=' in r.message and 'tick thread started' in r.message.lower()
            for r in caplog.records
        ), (
            f"expected loop-entry tid log; got "
            f"{[(r.levelname, r.message) for r in caplog.records]!r}"
        )

    def test_loopOnBatteryWithNoopTick_raisesAlarm(self) -> None:
        """Discriminator-A scenario: tick is a no-op (counter never
        advances), system is on BATTERY -> health check fires alarm."""
        manager = self._runOneIterationLoop(
            powerSource=PowerSource.BATTERY,
            tickIsNoop=True,
        )

        assert manager.tickHealthAlarmCount >= 1, (
            "Expected at least one liveness alarm when tick is a no-op "
            "while on BATTERY (discriminator A); pre-US-265 the health "
            "check did not exist so this assertion would FAIL"
        )

    def test_loopOnAcWithNoopTick_noAlarm(self) -> None:
        """Invariant: AC operation -> no false-positive alarms.

        Even though tick is a no-op (counter stuck at 0), the loop must
        not raise any alarm because the discriminator only applies on
        BATTERY -- the production assumption is that ticks advance under
        UPS load, not under wall power.
        """
        manager = self._runOneIterationLoop(
            powerSource=PowerSource.EXTERNAL,
            tickIsNoop=True,
        )

        assert manager.tickHealthAlarmCount == 0

    def test_loopOnBatteryHealthyTick_noAlarm(self) -> None:
        """Healthy path: tick advances counter, on BATTERY -> no alarm."""
        manager = self._runOneIterationLoop(
            powerSource=PowerSource.BATTERY,
            tickIsNoop=False,
        )

        assert manager.tickHealthAlarmCount == 0

    def test_healthCheckRaisingDoesNotKillLoop(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Invariant: 'Health-check is non-blocking; failure to log
        MUST NOT halt tick loop'.  Force the helper to raise and prove
        the loop still iterates orchestrator.tick afterward.
        """
        mockUps = MagicMock()
        mockUps.getTelemetry.return_value = {
            'voltage': 3.80,
            'percentage': 50,
            'powerSource': PowerSource.BATTERY,
            'chargeRatePctPerHr': -10.0,
        }
        mockOrch = MagicMock()
        mockOrch.tickCount = 0

        manager = HardwareManager.__new__(HardwareManager)
        manager._upsMonitor = mockUps
        manager._powerDownOrchestrator = mockOrch
        manager._shutdownHandler = None
        manager._stopEvent = threading.Event()
        manager._pollInterval = 0.01
        manager._tickHealthCheckIntervalS = 0.0
        manager._lastTickHealthCheckMono = time.monotonic() - 1.0
        manager._lastTickHealthCheckCount = 0
        manager._lastTickHealthCheckOnBattery = True
        manager._tickHealthAlarmCount = 0

        # Replace the helper with one that always raises.
        def boom(*_a: object, **_k: object) -> bool:
            raise RuntimeError("synthetic health-check failure")
        manager._checkTickThreadHealth = boom  # type: ignore[assignment]

        thread = threading.Thread(
            target=manager._powerDownTickLoop, daemon=True,
        )
        with caplog.at_level(
            logging.ERROR, logger='src.pi.hardware.hardware_manager',
        ):
            thread.start()
            time.sleep(0.05)
            manager._stopEvent.set()
            thread.join(timeout=1.0)

        # Loop survived: orchestrator.tick was still invoked after the
        # health check raised on the prior iteration.
        assert mockOrch.tick.call_count >= 1
