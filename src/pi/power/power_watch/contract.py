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
# ================================================================================
################################################################################
"""Single source of truth: outcome kinds + pipeline-task protocol."""
from __future__ import annotations

import enum
from typing import Protocol

__all__ = ["OutcomeKind", "PipelineTask", "RECORD_SCHEMA_VERSION"]

RECORD_SCHEMA_VERSION = 1


class OutcomeKind(enum.Enum):
    """Outcome of a pre-shutdown pipeline task. Single source of truth shared
    by the producer (outcome.py), the pipeline runner, the controller, and
    the sync task. A separate process consumes the records on next boot
    (out of scope)."""

    OK = "ok"
    SERVER_UNAVAILABLE = "server_unavailable"          # benign, expected
    SYNC_FAILED_AFTER_RETRY = "sync_failed_after_retry"
    REAL_ERROR = "real_error"                          # a genuine fault -> record


class PipelineTask(Protocol):
    """A pre-shutdown pipeline task. ``run()`` MUST NOT raise and MUST be
    interruption-safe (idempotent, no half-stateful side-effect) -- the
    process may be killed at the hard bound."""

    name: str

    def run(self) -> OutcomeKind: ...
