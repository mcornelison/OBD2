################################################################################
# File Name: contract.py
# Purpose/Description: Single source of truth for the Phase-2 power-watch
#                      instrument: the outcome-record kinds and the
#                      pipeline-task protocol, imported by the producer, the
#                      pipeline runner, the controller, and the sync task.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T1 OutcomeKind + PipelineTask protocol.
# 2026-05-19    | Plan SS-T6 | Hard rename PipelineTask -> ShutdownTask
#                              (Protocol body unchanged; +@runtime_checkable so
#                              consumers can verify membership at runtime --
#                              the plugin-seam exists exactly to admit new task
#                              classes, and a runtime-checkable contract makes
#                              that membership testable rather than aspirational).
# 2026-10-01    | Rex (US-776-d) | +DELIVERED, AWAY, UNKNOWN_NETWORK,
#                              AT_HOME_JOINING_TIMEOUT, AT_HOME_SERVER_DOWN,
#                              PROBE_MISCONFIGURED: why the shutdown sync ended.
# ================================================================================
################################################################################
"""Single source of truth: outcome kinds + shutdown-task protocol."""
from __future__ import annotations

import enum
from typing import Protocol, runtime_checkable

__all__ = ["OutcomeKind", "ShutdownTask", "RECORD_SCHEMA_VERSION"]

RECORD_SCHEMA_VERSION: int = 1


class OutcomeKind(enum.Enum):
    """Outcome of a pre-shutdown pipeline task. Single source of truth shared
    by the producer (outcome.py), the pipeline runner, the controller, and
    the sync task. A separate process consumes the records on next boot
    (out of scope).

    The sync task returns, and records, one of the US-776-d kinds -- why the
    shutdown sync ended -- or ``REAL_ERROR`` for a genuine fault.
    ``SERVER_UNAVAILABLE`` and ``SYNC_FAILED_AFTER_RETRY`` are what it
    produced before US-776-d; they stay so a record on disk from an older
    build still parses."""

    OK = "ok"
    SERVER_UNAVAILABLE = "server_unavailable"          # pre-US-776-d AWAY skip
    SYNC_FAILED_AFTER_RETRY = "sync_failed_after_retry"  # pre-US-776-d failure
    REAL_ERROR = "real_error"                          # a genuine fault -> record

    # US-776-d: why the shutdown sync ended (one record per shutdown).
    DELIVERED = "delivered"                            # a drain attempt succeeded
    AWAY = "away"                                      # positive AWAY: skipped
    UNKNOWN_NETWORK = "unknown_network"                # home unconfirmed; drain failed
    AT_HOME_JOINING_TIMEOUT = "at_home_joining_timeout"  # US-776-e: rejoin outlasted ceiling
    AT_HOME_SERVER_DOWN = "at_home_server_down"        # connection error, timeout, 5xx
    PROBE_MISCONFIGURED = "probe_misconfigured"        # probe 404/405/401/403


@runtime_checkable
class ShutdownTask(Protocol):
    """A pre-shutdown task (the V1 single-task seam in `__main__.buildV1Tasks`
    composes these into an ordered list for the bounded pipeline). ``run()``
    MUST NOT raise and MUST be interruption-safe (idempotent, no half-stateful
    side-effect) -- the process may be killed at the hard bound. Renamed from
    ``PipelineTask`` in SS-T6 to match the ShutdownSequencer vocabulary."""

    name: str

    def run(self) -> OutcomeKind: ...
