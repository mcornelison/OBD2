################################################################################
# File Name: test_poll_tier_pause.py
# Purpose/Description: ApplicationOrchestrator.pausePolling / resumePolling
#                      tests -- US-216 IMMINENT-stage hook for halting OBD
#                      poll-tier dispatch without tearing down the connection.
#                      US-225 / TD-034 close.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Tests for the orchestrator pause/resume-polling hooks.

Invariants verified:

1. **pausePolling delegates to data logger stop** without any
   connection teardown (the connection object is untouched).
2. **Idempotency** -- a second pausePolling call is a no-op;
   resumePolling when not paused-for-power-down is a no-op.
3. **resumePolling restarts the logger** and clears the flag.
4. **No data-logger scenario** is a benign no-op (dev / test
   configurations may not have a realtime logger).
5. **Error in logger.stop** is logged but does not raise out to
   the stage callback (US-216 invariant: callbacks must not
   block stage escalation).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.pi.obdii.orchestrator.core import ApplicationOrchestrator

# ================================================================================
# Helpers
# ================================================================================


def _buildOrchestrator() -> ApplicationOrchestrator:
    """Construct an orchestrator without running any init -- we only
    test the pause/resume hooks + their flag state.
    """
    config = {
        'deviceId': 'test-device',
        'pi': {
            'bluetooth': {'retryDelays': [1, 2, 4], 'maxRetries': 3},
            'monitoring': {
                'healthCheckIntervalSeconds': 30,
                'connectionCheckIntervalSeconds': 30,
                'dataRateLogIntervalSeconds': 300,
            },
            'realtimeData': {'parameters': []},
            'shutdown': {'componentTimeout': 5},
        },
    }
    return ApplicationOrchestrator(config=config, simulate=True)


# ================================================================================
# pausePolling
# ================================================================================


class TestPausePolling:
    def test_pausePolling_callsStopOnDataLogger(self) -> None:
        orch = _buildOrchestrator()
        logger = MagicMock()
        logger.stop = MagicMock()
        orch._dataLogger = logger

        result = orch.pausePolling(reason='power_imminent')

        assert result is True
        logger.stop.assert_called_once()
        assert orch.pollingPausedForPowerDown is True

    def test_pausePolling_secondCallIsIdempotentNoop(self) -> None:
        orch = _buildOrchestrator()
        logger = MagicMock()
        logger.stop = MagicMock()
        orch._dataLogger = logger

        orch.pausePolling(reason='power_imminent')
        second = orch.pausePolling(reason='power_imminent')

        assert second is False
        logger.stop.assert_called_once()

    def test_pausePolling_noDataLogger_returnsFalse(self) -> None:
        orch = _buildOrchestrator()
        orch._dataLogger = None

        result = orch.pausePolling(reason='power_imminent')

        assert result is False
        assert orch.pollingPausedForPowerDown is False

    def test_pausePolling_loggerWithoutStopMethod_doesNotRaise(self) -> None:
        orch = _buildOrchestrator()
        # A logger object without a stop() method -- defensive path.
        class _NoStop:
            pass
        orch._dataLogger = _NoStop()

        # Should not raise.
        result = orch.pausePolling(reason='power_imminent')

        assert result is False

    def test_pausePolling_loggerStopRaises_swallowedAndNotFlaggedPaused(
        self,
    ) -> None:
        orch = _buildOrchestrator()
        logger = MagicMock()
        logger.stop = MagicMock(side_effect=RuntimeError("hardware gone"))
        orch._dataLogger = logger

        # Should not re-raise -- the stage callback must continue.
        result = orch.pausePolling(reason='power_imminent')

        assert result is False
        # Flag stays False so a retry is possible.
        assert orch.pollingPausedForPowerDown is False

    def test_pausePolling_doesNotTouchConnection(self) -> None:
        orch = _buildOrchestrator()
        connection = MagicMock()
        orch._connection = connection
        logger = MagicMock()
        logger.stop = MagicMock()
        orch._dataLogger = logger

        orch.pausePolling(reason='power_imminent')

        # Connection must stay attached -- pausePolling is NOT a
        # teardown.
        connection.close.assert_not_called()
        connection.disconnect.assert_not_called()


# ================================================================================
# resumePolling
# ================================================================================


class TestResumePolling:
    def test_resumePolling_afterPause_callsStartAndClearsFlag(self) -> None:
        orch = _buildOrchestrator()
        logger = MagicMock()
        logger.stop = MagicMock()
        logger.start = MagicMock()
        orch._dataLogger = logger

        orch.pausePolling(reason='power_imminent')
        result = orch.resumePolling(reason='power_restored')

        assert result is True
        logger.start.assert_called_once()
        assert orch.pollingPausedForPowerDown is False

    def test_resumePolling_notPaused_isNoop(self) -> None:
        orch = _buildOrchestrator()
        logger = MagicMock()
        logger.start = MagicMock()
        orch._dataLogger = logger

        # Resume without a prior pause.
        result = orch.resumePolling(reason='power_restored')

        assert result is False
        logger.start.assert_not_called()
        assert orch.pollingPausedForPowerDown is False

    def test_resumePolling_noDataLogger_clearsFlag(self) -> None:
        orch = _buildOrchestrator()
        orch._pollingPausedForPowerDown = True
        orch._dataLogger = None

        result = orch.resumePolling(reason='power_restored')

        assert result is False
        # Flag still cleared so AC-restore never leaves the system
        # stuck in "paused" forever.
        assert orch.pollingPausedForPowerDown is False

    def test_resumePolling_startRaises_flagNotCleared(self) -> None:
        orch = _buildOrchestrator()
        logger = MagicMock()
        logger.stop = MagicMock()
        logger.start = MagicMock(side_effect=RuntimeError("thread start failed"))
        orch._dataLogger = logger

        orch.pausePolling(reason='power_imminent')
        result = orch.resumePolling(reason='power_restored')

        assert result is False
        # Flag remains True so a subsequent retry path can attempt
        # again (AC might bounce).
        assert orch.pollingPausedForPowerDown is True


# ================================================================================
# End-to-end pause -> resume cycle
# ================================================================================


class TestPauseResumeCycle:
    def test_pauseResumeCycle_logsStopThenStart(self) -> None:
        orch = _buildOrchestrator()
        logger = MagicMock()
        callOrder: list[str] = []
        logger.stop = MagicMock(side_effect=lambda: callOrder.append('stop'))
        logger.start = MagicMock(side_effect=lambda: callOrder.append('start'))
        orch._dataLogger = logger

        orch.pausePolling(reason='power_imminent')
        orch.resumePolling(reason='power_restored')

        assert callOrder == ['stop', 'start']
        assert orch.pollingPausedForPowerDown is False

    def test_multiplePauseResumeCycles_areIdempotent(self) -> None:
        orch = _buildOrchestrator()
        logger = MagicMock()
        logger.stop = MagicMock()
        logger.start = MagicMock()
        orch._dataLogger = logger

        for _ in range(3):
            orch.pausePolling(reason='power_imminent')
            orch.resumePolling(reason='power_restored')

        assert logger.stop.call_count == 3
        assert logger.start.call_count == 3
        assert orch.pollingPausedForPowerDown is False
