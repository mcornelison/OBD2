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
# 2026-09-17    | Rex (US-776-a) | sequencerBoundedTasks: a task named there is
#                           joined WITHOUT perTaskTimeoutSec, so it is never
#                           abandoned mid-drain. Its bound is the sequencer's
#                           VCELL-floor poll. Default () = every task bounded,
#                           exactly as before -- future plugin tasks included.
# ================================================================================
################################################################################
"""Bounded best-effort pre-shutdown pipeline runner."""
from __future__ import annotations

import logging
import threading
from collections.abc import Collection

from src.pi.power.power_watch.contract import OutcomeKind, ShutdownTask

logger = logging.getLogger(__name__)
__all__ = ["runPipeline"]


def runPipeline(
    tasks: list[ShutdownTask],
    *,
    perTaskTimeoutSec: float,
    sequencerBoundedTasks: Collection[str] = (),
) -> dict[str, OutcomeKind]:
    """Run tasks in order, best-effort, each hard-bounded by
    perTaskTimeoutSec. A task that raises OR times out -> REAL_ERROR for
    that task; never blocks the next task; never raises out of here.

    US-776-a: the timeout does not CANCEL a task, it ABANDONS it -- the daemon
    thread keeps running (calling forcePush, writing SQLite) while the pipeline
    moves on and ``systemctl poweroff`` starts. For the shutdown drain that is
    the wrong bound twice over: it cuts a drain the battery could still fund,
    and it leaves the drain running unobserved. A task named in
    ``sequencerBoundedTasks`` is therefore joined with no timeout. Its bound is
    the ShutdownSequencer's poll, which re-reads the VCELL floor on a fixed
    cadence and powers off from its own thread whatever this one is doing.

    Args:
        tasks: Ordered ShutdownTask list.
        perTaskTimeoutSec: Hard per-task wall-clock bound (seconds) for every
            task NOT named in ``sequencerBoundedTasks``.
        sequencerBoundedTasks: Names of tasks whose bound is the sequencer's
            floor poll rather than ``perTaskTimeoutSec``. Default empty: every
            task keeps the per-task bound, so a plugin task appended to
            ``buildV1Tasks`` is bounded unless its wiring says otherwise.

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
        if task.name in sequencerBoundedTasks:
            th.join()  # bounded by the sequencer's floor poll, not by a timer
        else:
            th.join(timeout=perTaskTimeoutSec)
        if th.is_alive():
            logger.error("powerwatch task %s exceeded %.1fs -- abandoning (shutdown imminent)",
                         task.name, perTaskTimeoutSec)
            results[task.name] = OutcomeKind.REAL_ERROR
        else:
            results[task.name] = box.get("r", OutcomeKind.REAL_ERROR)
    return results
