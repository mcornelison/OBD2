################################################################################
# File Name: __init__.py
# Purpose/Description: Package re-exports for backward-compatible orchestrator
#                      imports (preserves the old monolith's public surface)
# Author: Ralph Agent
# Creation Date: 2026-04-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-14    | Ralph Agent  | Sweep 5 Task 2: package split of orchestrator.py
# ================================================================================
################################################################################

"""
Orchestrator package for Eclipse OBD-II Performance Monitoring System.

Re-exports the same public surface the original `orchestrator.py` module
provided so existing `from pi.obdii.orchestrator import ApplicationOrchestrator`
(and any `@patch('pi.obdii.orchestrator.createOrchestratorFromConfig')`) calls
keep working unchanged.

The class itself now lives in `core.py` and composes mixin classes from
the sibling modules:
    lifecycle.py, signal_handler.py, health_monitor.py,
    backup_coordinator.py, connection_recovery.py, event_router.py

Typed data and constants live in `types.py`.
"""

from .core import ApplicationOrchestrator, createOrchestratorFromConfig
from .types import (
    DEFAULT_CONNECTION_CHECK_INTERVAL,
    DEFAULT_DATA_RATE_LOG_INTERVAL,
    DEFAULT_HEALTH_CHECK_INTERVAL,
    DEFAULT_MAX_RECONNECT_ATTEMPTS,
    DEFAULT_RECONNECT_DELAYS,
    DEFAULT_SHUTDOWN_TIMEOUT,
    EXIT_CODE_CLEAN,
    EXIT_CODE_ERROR,
    EXIT_CODE_FORCED,
    ComponentInitializationError,
    ComponentStartError,
    ComponentStopError,
    HealthCheckStats,
    OrchestratorError,
    ShutdownState,
)

__all__ = [
    # Classes
    'ApplicationOrchestrator',
    'HealthCheckStats',
    # Enums
    'ShutdownState',
    # Exceptions
    'OrchestratorError',
    'ComponentInitializationError',
    'ComponentStartError',
    'ComponentStopError',
    # Constants
    'DEFAULT_SHUTDOWN_TIMEOUT',
    'DEFAULT_HEALTH_CHECK_INTERVAL',
    'DEFAULT_DATA_RATE_LOG_INTERVAL',
    'DEFAULT_CONNECTION_CHECK_INTERVAL',
    'DEFAULT_RECONNECT_DELAYS',
    'DEFAULT_MAX_RECONNECT_ATTEMPTS',
    'EXIT_CODE_CLEAN',
    'EXIT_CODE_FORCED',
    'EXIT_CODE_ERROR',
    # Factory functions
    'createOrchestratorFromConfig',
]
