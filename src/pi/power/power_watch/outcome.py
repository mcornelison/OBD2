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
__all__ = ["writeOutcomeRecord"]


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
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")))
            fh.flush()
            _fdatasyncBestEffort(fh.fileno())
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001 -- producer must never block shutdown
        logger.warning("powerwatch outcome record write failed: %s", exc)
