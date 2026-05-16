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
# 2026-05-15    | Plan    | T3 -- readPriorTrail + positive-proof deriveVerdict.
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
    "readPriorTrail",
    "deriveVerdict",
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


#: Verdict mapping -- ONLY CLEAN_COMPLETE => clean. Positive proof only.
_VERDICT_BY_STAGE: dict[Stage, tuple[int, str]] = {
    Stage.CLEAN_COMPLETE: (1, "graceful"),
    Stage.POWEROFF_RC0: (0, "poweroff_accepted_unfinalized"),
    Stage.POWEROFF_INVOKED: (0, "poweroff_invoked_never_returned"),
    Stage.TRIGGER_ROW_WRITTEN: (0, "wedged_before_poweroff"),
    Stage.DRAIN_CLOSED: (0, "wedged_before_poweroff"),
    Stage.TRIGGER: (0, "wedged_before_poweroff"),
    Stage.IMMINENT: (0, "died_mid_drain"),
    Stage.WARNING: (0, "died_mid_drain"),
    Stage.RUNNING: (0, "crashed_during_operation"),
}
_RANK: dict[Stage, int] = {s: i for i, s in enumerate(MILESTONE_ORDER)}


def readPriorTrail(filePath: str = DEFAULT_FILE_PATH) -> list[dict]:
    """Read the prior boot's breadcrumb trail into a list of records.

    Defensive by contract: a missing/empty file or any malformed line is
    NOT an error -- absence of a record is itself the signal the reader
    must classify (it must never be inferred clean). Malformed JSON lines
    and non-dict / stage-less records are skipped so a torn final write
    under the shutdown I/O storm cannot strand the whole trail.

    Args:
        filePath: Path of the append-only breadcrumb file. Defaults to
            :data:`DEFAULT_FILE_PATH`.

    Returns:
        List of decoded record dicts (each with a truthy ``stage`` key),
        in file order. ``[]`` if the file is missing, unreadable, empty,
        or contains no well-formed stage records.
    """
    try:
        with open(filePath, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return []
    records: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(rec, dict) and rec.get("stage"):
            records.append(rec)
    return records


def deriveVerdict(trail: list[dict]) -> tuple[int | None, str | None, str]:
    """Derive the prior-boot verdict using POSITIVE-PROOF-ONLY semantics.

    The highest rung reached in ``trail`` (by :data:`MILESTONE_ORDER`
    rank, so a lower rung logged after a higher one does not demote the
    result) decides the verdict. Clean (``1``) is returned ONLY when the
    finalizer-written :attr:`Stage.CLEAN_COMPLETE` rung is present; every
    other highest rung yields ``0`` with a specific reason. An empty or
    unreadable trail yields ``None`` -- never inferred clean (this is the
    bug the old journald canary had: it forged "clean" from the absence
    of a negative). The "Drain-26 shape" (trail ends at
    ``POWEROFF_INVOKED`` with no ``CLEAN_COMPLETE``) therefore returns
    ``0``, where the old canary wrongly returned ``1``.

    Args:
        trail: Record dicts as produced by :func:`readPriorTrail`. Each
            should carry a ``stage`` value; records whose ``stage`` is
            not a recognized :class:`Stage` member are ignored.

    Returns:
        A ``(priorClean, priorStage, priorReason)`` tuple:
            * ``priorClean``: ``1`` iff ``CLEAN_COMPLETE`` was reached,
              ``0`` for any other highest rung, ``None`` when the trail
              has no usable record.
            * ``priorStage``: The value of the highest rung reached, or
              ``None`` when there is no usable record.
            * ``priorReason``: Short reason code for the verdict
              (``"indeterminate_no_record"`` when the trail is empty).
    """
    highest: Stage | None = None
    for rec in trail:
        try:
            st = Stage(rec["stage"])
        except (ValueError, KeyError):
            continue
        if highest is None or _RANK[st] > _RANK[highest]:
            highest = st
    if highest is None:
        return (None, None, "indeterminate_no_record")
    clean, reason = _VERDICT_BY_STAGE[highest]
    return (clean, highest.value, reason)
