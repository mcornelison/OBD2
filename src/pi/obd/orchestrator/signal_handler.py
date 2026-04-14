################################################################################
# File Name: signal_handler.py
# Purpose/Description: SIGINT/SIGTERM signal handling mixin for the orchestrator
# Author: Ralph Agent
# Creation Date: 2026-04-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-14    | Ralph Agent  | Sweep 5 Task 2: extracted from orchestrator.py
#               |              | (double-Ctrl+C pattern preserved per TD-003)
# ================================================================================
################################################################################

"""
Signal handling mixin for ApplicationOrchestrator.

Provides SIGINT/SIGTERM installation, restoration, and the double-signal
behavior where the first signal requests graceful shutdown and the second
signal forces immediate exit.
"""

import logging
import signal
import sys
from collections.abc import Callable
from typing import Any

from .types import EXIT_CODE_FORCED, ShutdownState

# Unified logger name matches the original monolith module so existing tests
# that filter caplog by logger name continue to work unchanged.
logger = logging.getLogger("pi.obd.orchestrator")


class SignalHandlerMixin:
    """
    Mixin providing signal handler installation and double-signal force-exit.

    Assumes the composing class has the following attributes (set by
    ApplicationOrchestrator.__init__):
        _originalSigintHandler: Callable | None
        _originalSigtermHandler: Callable | None
        _shutdownState: ShutdownState
        _exitCode: int
    """

    _originalSigintHandler: Callable[..., Any] | None
    _originalSigtermHandler: Callable[..., Any] | None
    _shutdownState: ShutdownState
    _exitCode: int

    def registerSignalHandlers(self) -> None:
        """
        Register signal handlers for graceful shutdown.

        Registers handlers for SIGINT (Ctrl+C) and SIGTERM (systemd stop).
        First signal initiates graceful shutdown, second signal forces immediate exit.
        """
        self._originalSigintHandler = signal.signal(
            signal.SIGINT, self._handleShutdownSignal
        )
        # SIGTERM is not available on Windows, only register if available
        if hasattr(signal, 'SIGTERM'):
            self._originalSigtermHandler = signal.signal(
                signal.SIGTERM, self._handleShutdownSignal
            )
        logger.debug("Signal handlers registered")

    def restoreSignalHandlers(self) -> None:
        """Restore the original signal handlers."""
        if self._originalSigintHandler is not None:
            signal.signal(signal.SIGINT, self._originalSigintHandler)
            self._originalSigintHandler = None
        if self._originalSigtermHandler is not None and hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, self._originalSigtermHandler)
            self._originalSigtermHandler = None
        logger.debug("Signal handlers restored")

    def _handleShutdownSignal(
        self, signum: int, frame: Any | None
    ) -> None:
        """
        Handle shutdown signals (SIGINT/SIGTERM).

        First signal: Request graceful shutdown
        Second signal: Force immediate exit

        Args:
            signum: Signal number received
            frame: Stack frame (unused)
        """
        signalName = signal.Signals(signum).name if signum in [s.value for s in signal.Signals] else str(signum)

        if self._shutdownState == ShutdownState.SHUTDOWN_REQUESTED:
            # Second signal - force exit
            logger.warning(
                f"Received second signal ({signalName}), forcing immediate exit"
            )
            self._shutdownState = ShutdownState.FORCE_EXIT
            self._exitCode = EXIT_CODE_FORCED
            # Force immediate exit
            sys.exit(EXIT_CODE_FORCED)
        else:
            # First signal - request graceful shutdown
            logger.info(f"Received signal {signalName}, initiating shutdown")
            self._shutdownState = ShutdownState.SHUTDOWN_REQUESTED


__all__ = ['SignalHandlerMixin']
