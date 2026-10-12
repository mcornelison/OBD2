################################################################################
# File Name: test_stop_timeout_exit_code.py
# Purpose/Description: US-780 -- a bounded force-stop of one component during
#     an orderly stop is not a failed stop.  Mechanism B (Atlas, 147 stops:
#     28/28 'connection did not stop within 5.0s' exited 1) must now log a
#     WARNING naming the component and its elapsed stop time and exit 0.  An
#     exception that escapes the stop sequence itself must still exit non-zero.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""US-780: component stop-timeout -> exit 0 + WARNING; escaped exception -> non-zero."""

import logging
import time
from unittest.mock import MagicMock, patch

import pytest

from pi.main import EXIT_SUCCESS, main
from pi.obdii.orchestrator import EXIT_CODE_CLEAN, ApplicationOrchestrator

_TIMEOUT_SEC = 0.1
_HANG_SEC = 1.0


def _hangingConnection() -> MagicMock:
    """A connection whose disconnect() overruns the shutdown timeout."""
    connection = MagicMock()
    connection.disconnect.side_effect = lambda: time.sleep(_HANG_SEC)
    return connection


def test_stop_connectionOverrunsTimeout_exitsCleanWithWarning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: a running orchestrator whose connection ignores stop for longer
           than the shutdown timeout (mechanism B)
    When: stop() runs the orderly stop sequence
    Then: it returns EXIT_CODE_CLEAN, and a WARNING names 'connection' and
          its elapsed stop time
    """
    # Arrange
    orchestrator = ApplicationOrchestrator(config={}, simulate=True)
    orchestrator._shutdownTimeout = _TIMEOUT_SEC
    orchestrator._connection = _hangingConnection()
    orchestrator._running = True

    # Act
    with caplog.at_level(logging.WARNING):
        exitCode = orchestrator.stop()

    # Assert
    assert exitCode == EXIT_CODE_CLEAN
    warnings = [
        r.getMessage() for r in caplog.records
        if r.levelno == logging.WARNING and 'connection' in r.getMessage()
    ]
    assert len(warnings) == 1, f"Expected one connection WARNING, got: {warnings}"
    assert 'force-stopping' in warnings[0]
    assert 'elapsed=' in warnings[0]


def test_stop_componentStopRaises_stillExitsClean() -> None:
    """
    Given: a component whose stop() raises
    When: stop() runs the orderly stop sequence
    Then: the error is swallowed with a WARNING and the exit code is
          unchanged (PM ruling 2026-09-30, option (a): no new non-zero path)
    """
    # Arrange
    orchestrator = ApplicationOrchestrator(config={}, simulate=True)
    connection = MagicMock()
    connection.disconnect.side_effect = RuntimeError("adapter gone")
    orchestrator._connection = connection
    orchestrator._running = True

    # Act
    exitCode = orchestrator.stop()

    # Assert
    assert exitCode == EXIT_CODE_CLEAN


@patch('pi.main.loadConfiguration', return_value={})
@patch('pi.main.setupLogging')
@patch('pi.obdii.orchestrator.createOrchestratorFromConfig')
def test_main_exceptionEscapesStopSequence_exitsNonZero(
    mockCreate: MagicMock,
    mockSetupLogging: MagicMock,
    mockLoadConfig: MagicMock,
) -> None:
    """
    Given: an orchestrator whose stop() itself raises
    When: main() runs the workflow to completion
    Then: the process exit code is non-zero, exactly as before US-780
    """
    # Arrange
    orchestrator = MagicMock()
    orchestrator.stop.side_effect = RuntimeError("stop sequence blew up")
    mockCreate.return_value = orchestrator

    # Act
    with patch('sys.argv', ['main.py']):
        exitCode = main()

    # Assert
    assert orchestrator.stop.called
    assert exitCode != EXIT_SUCCESS
