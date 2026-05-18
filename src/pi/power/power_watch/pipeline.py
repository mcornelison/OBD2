################################################################################
# File Name: pipeline.py
# Purpose/Description: Bounded best-effort pre-shutdown pipeline runner for
#                      Phase-2 power-watch: runs tasks in order, each hard-bounded
#                      by a per-task timeout, failures isolated per task, never
#                      raises (the process is about to poweroff).
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T3 bounded per-task pipeline runner.
# ================================================================================
################################################################################
"""Bounded best-effort pre-shutdown pipeline runner."""
from __future__ import annotations

import logging
import threading

from src.pi.power.power_watch.contract import OutcomeKind, PipelineTask

logger = logging.getLogger(__name__)
__all__ = ["runPipeline"]


def runPipeline(tasks: list[PipelineTask], *, perTaskTimeoutSec: float) -> dict[str, OutcomeKind]:
    """Run tasks in order, best-effort, each hard-bounded by
    perTaskTimeoutSec. A task that raises OR times out -> REAL_ERROR for
    that task; never blocks the next task; never raises out of here.

    Args:
        tasks: Ordered PipelineTask list.
        perTaskTimeoutSec: Hard per-task wall-clock bound (seconds).

    Returns:
        Mapping of task name -> its OutcomeKind result.
    """
    results: dict[str, OutcomeKind] = {}
    for task in tasks:
        box: dict[str, OutcomeKind] = {}
        def _runner(t=task, b=box):
            try:
                b["r"] = t.run()
            except Exception as exc:  # noqa: BLE001 -- isolate per task
                logger.error("powerwatch task %s raised: %s", t.name, exc)
                b["r"] = OutcomeKind.REAL_ERROR
        th = threading.Thread(target=_runner, name=f"pw-{task.name}", daemon=True)
        th.start()
        th.join(timeout=perTaskTimeoutSec)
        if th.is_alive():
            logger.error("powerwatch task %s exceeded %.1fs -- abandoning (shutdown imminent)",
                         task.name, perTaskTimeoutSec)
            results[task.name] = OutcomeKind.REAL_ERROR
        else:
            results[task.name] = box.get("r", OutcomeKind.REAL_ERROR)
    return results
