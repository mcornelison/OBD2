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
# 2026-05-15    | Plan    | T2 -- add fail-safe markMilestone.
# ================================================================================
################################################################################
"""Crash-surviving boot-progress breadcrumb instrument (replaces I-037 canary)."""

from __future__ import annotations

import enum
import json
import logging
import os

from src.common.time.helper import utcIsoNow

logger = logging.getLogger(__name__)

__all__ = [
    "Stage",
    "MILESTONE_ORDER",
    "CLEAN_COMPLETE_RUNG",
    "markMilestone",
    "DEFAULT_FILE_PATH",
    "DEFAULT_MAX_TRAIL_BYTES",
]


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

#: Defaults mirror the config keys (later task wires config). These keep the
#: module usable standalone.
DEFAULT_FILE_PATH = "data/boot_progress"
DEFAULT_MAX_TRAIL_BYTES = 65536


def markMilestone(
    stage: Stage,
    *,
    vcell: float | None,
    filePath: str = DEFAULT_FILE_PATH,
    bootId: str,
    maxTrailBytes: int = DEFAULT_MAX_TRAIL_BYTES,
) -> None:
    """Append one milestone line and fdatasync it. FAIL-SAFE.

    Never raises into the caller: the orchestrator/shutdown path must keep
    trying to power off even if this write fails under the I/O storm. A lost
    breadcrumb only degrades fidelity; the no-false-clean invariant holds
    because only the finalizer writes CLEAN_COMPLETE.
    """
    try:
        if os.path.exists(filePath) and os.path.getsize(filePath) >= maxTrailBytes:
            logger.warning(
                "boot_progress trail at %s exceeds maxTrailBytes=%d -- "
                "not appending %s (restart-loop guard)",
                filePath, maxTrailBytes, stage.value,
            )
            return
        line = json.dumps(
            {"boot_id": bootId, "stage": stage.value,
             "ts": utcIsoNow(), "vcell": vcell},
            separators=(",", ":"),
        ) + "\n"
        fd = os.open(filePath, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fdatasync(fd)
        finally:
            os.close(fd)
    except Exception as exc:  # noqa: BLE001 -- fail-safe by contract
        logger.warning("boot_progress markMilestone(%s) failed: %s",
                        stage.value, exc)
