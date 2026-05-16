################################################################################
# File Name: boot_progress.py
# Purpose/Description: Crash-surviving boot-progress breadcrumb instrument.
#                      Replaces the journald-based boot canary (I-037). A
#                      dirty-by-default append-only file records the furthest
#                      milestone the shutdown sequence reached; the next boot
#                      derives a positive-proof-only verdict. Only the systemd
#                      shutdown-finalizer writes CLEAN_COMPLETE, so a hard crash
#                      can never forge 'clean'. See
#                      docs/superpowers/specs/2026-05-15-honest-boot-progress-instrument-design.md.
# Author: (implementation plan 2026-05-15)
# Creation Date: 2026-05-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-15    | Plan    | Initial -- Bug 2 honest instrument.
# ================================================================================
################################################################################
"""Crash-surviving boot-progress breadcrumb instrument (replaces I-037 canary)."""

from __future__ import annotations

import enum

__all__ = ["Stage", "MILESTONE_ORDER", "CLEAN_COMPLETE_RUNG"]


class Stage(enum.Enum):
    """Ordered shutdown-progress milestones. Single source of truth shared by
    the writer (orchestrator + shutdown_handler), the reader (arm), and the
    US-343 audit script. Making this config-mutable would re-create the
    US-308/US-342 silent-drift bug (spec sec 4.4)."""

    RUNNING = "RUNNING"
    WARNING = "WARNING"
    IMMINENT = "IMMINENT"
    TRIGGER = "TRIGGER"
    DRAIN_CLOSED = "DRAIN_CLOSED"
    TRIGGER_ROW_WRITTEN = "TRIGGER_ROW_WRITTEN"
    POWEROFF_INVOKED = "POWEROFF_INVOKED"
    POWEROFF_RC0 = "POWEROFF_RC0"
    CLEAN_COMPLETE = "CLEAN_COMPLETE"


#: The ladder in strict monotonic order. Index = rung height.
MILESTONE_ORDER: tuple[Stage, ...] = (
    Stage.RUNNING,
    Stage.WARNING,
    Stage.IMMINENT,
    Stage.TRIGGER,
    Stage.DRAIN_CLOSED,
    Stage.TRIGGER_ROW_WRITTEN,
    Stage.POWEROFF_INVOKED,
    Stage.POWEROFF_RC0,
    Stage.CLEAN_COMPLETE,
)

#: The ONLY rung that proves a graceful shutdown actually completed.
CLEAN_COMPLETE_RUNG: Stage = Stage.CLEAN_COMPLETE
