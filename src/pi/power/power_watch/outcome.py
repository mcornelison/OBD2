################################################################################
# File Name: outcome.py
# Purpose/Description: Producer-only typed durable outcome record for the
#                      Phase-2 power-watch pre-shutdown pipeline: atomic
#                      write-temp+rename+fdatasync, never raises (a draining-Pi
#                      failure must not block shutdown). The consumer (next
#                      boot, separate process) is out of scope.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T2 atomic fail-safe outcome producer.
# 2026-08-29    | Rex (US-621) | Extracted the atomic write-temp+rename+
#                               fdatasync body into writeAtomicJson so the new
#                               pre-poweroff sync-custody record shares ONE
#                               durability implementation instead of growing a
#                               second, subtly different copy. writeOutcomeRecord
#                               is behaviourally unchanged, including its
#                               "powerwatch outcome record write failed" line --
#                               the shared writer takes a `what` label precisely
#                               so a shared failure message can never name the
#                               wrong record type.
# ================================================================================
################################################################################
"""Producer-only typed durable outcome record (atomic, never raises)."""
from __future__ import annotations

import json
import logging
import os

from src.common.time.helper import utcIsoNow
from src.pi.diagnostics.boot_progress import _fdatasyncBestEffort  # proven helper
from src.pi.power.power_watch.contract import RECORD_SCHEMA_VERSION, OutcomeKind

logger = logging.getLogger(__name__)
__all__ = ["writeAtomicJson", "writeOutcomeRecord"]


def writeAtomicJson(path: str, payload: dict, *, what: str = "record") -> bool:
    """Atomically persist ``payload`` as JSON. Never raises.

    write-temp + flush + fdatasync + rename, so a poweroff mid-write can leave
    the previous record or the new one, never a torn one.

    Extracted in US-621 so the pre-shutdown sync-custody record shares ONE
    durability implementation with the outcome record rather than growing a
    second, subtly different copy. Behaviour is byte-identical to the inline
    version this replaced.

    Args:
        path: Destination JSON path.
        payload: JSON-serialisable record body.
        what: Record-type label used in the failure log, so a shared writer
            never reports the wrong record type (the existing "powerwatch
            outcome record write failed" line stays exactly that).

    Returns:
        True if the record reached disk, False if it could not be written
        (already logged). Callers on the poweroff path must not act on a
        False by raising -- a draining Pi must never be held up by
        bookkeeping.
    """
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, separators=(",", ":")))
            fh.flush()
            _fdatasyncBestEffort(fh.fileno())
        os.replace(tmp, path)
        return True
    except Exception as exc:  # noqa: BLE001 -- producer must never block shutdown
        logger.warning(
            "powerwatch %s record write failed (%s): %s", what, path, exc
        )
        return False


def writeOutcomeRecord(path: str, kind: OutcomeKind, *, detail: str, task: str) -> None:
    """Producer ONLY. Atomic write-temp+rename+fdatasync; never raises
    (a draining-Pi failure must not block shutdown). The consumer (next
    boot, separate process) is out of scope.

    Args:
        path: Destination JSON path.
        kind: The typed OutcomeKind for this record.
        detail: Free-text fault detail.
        task: Name of the pipeline task that produced this record.
    """
    try:
        rec = {
            "schema": RECORD_SCHEMA_VERSION,
            "kind": kind.value,
            "detail": detail,
            "task": task,
            "ts": utcIsoNow(),
        }
    except Exception as exc:  # noqa: BLE001 -- producer must never block shutdown
        logger.warning("powerwatch outcome record build failed: %s", exc)
        return
    writeAtomicJson(path, rec, what="outcome")
