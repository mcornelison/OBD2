################################################################################
# File Name: ceremony.py
# Purpose/Description: The shutdown CEREMONY -- the ordered steps a confirmed
#                      power loss runs before poweroff -- as ONE src constant
#                      (US-883-a, Atlas D1), plus the plan for each path and the
#                      progress tracker the ShutdownSequencer publishes as
#                      shutdown-state step {index, of, name}. Promoted from the
#                      ceremony guard test, which now imports it.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-23    | Rex (US-883-a) | Initial -- CEREMONY_ORDER promoted from
#                                  test_shutdown_ceremony_guard; ceremonySteps +
#                                  CeremonyProgress for the step publish.
# ================================================================================
################################################################################
"""The shutdown ceremony: one step list, the plan per path, and its progress.

Stdlib only: ``controller.py`` imports this, and ``pi.splash`` imports the
controller cheaply (no cycle, no heavy graph).
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

__all__ = [
    "CEREMONY_ORDER",
    "STEP_CUSTODY",
    "STEP_DRAIN",
    "STEP_DRAIN_CLOSE",
    "STEP_MONTHLY_TEST_HOLD",
    "STEP_POWEROFF",
    "STEP_SHED",
    "CeremonyProgress",
    "ceremonySteps",
]

STEP_SHED = "shed"
STEP_DRAIN = "drain"
STEP_DRAIN_CLOSE = "drain close"
STEP_CUSTODY = "custody"
STEP_POWEROFF = "poweroff"
#: The monthly capacity-test hold. The same string as MonthlyTestHoldTask.name
#: (the design spec's step word); a step only on a path where the hold is due.
STEP_MONTHLY_TEST_HOLD = "monthly_test_hold"

#: The ceremony, in the order it must happen. Backlog depth changes how long
#: the drain takes and nothing else on this list.
CEREMONY_ORDER = (STEP_SHED, STEP_DRAIN, STEP_DRAIN_CLOSE, STEP_CUSTODY, STEP_POWEROFF)

#: The VCELL fast path (a successful read at or below a floor) skips these.
_FAST_PATH_OMITS = frozenset({STEP_DRAIN, STEP_DRAIN_CLOSE})


def ceremonySteps(*, fastPath: bool, holdDue: bool) -> tuple[str, ...]:
    """The steps one path runs, in order.

    Args:
        fastPath: True for the VCELL fast path (no drain, no drain close).
        holdDue: True when the monthly hold will run. It runs inside the drain's
            pipeline, after the sync, so the fast path never has it.

    Returns:
        Normal: the 5 of ``CEREMONY_ORDER``, or 6 with the hold after the drain.
        Fast path: 3 (shed, custody, poweroff).
    """
    if fastPath:
        return tuple(s for s in CEREMONY_ORDER if s not in _FAST_PATH_OMITS)
    steps = list(CEREMONY_ORDER)
    if holdDue:
        steps.insert(steps.index(STEP_DRAIN) + 1, STEP_MONTHLY_TEST_HOLD)
    return tuple(steps)


class CeremonyProgress:
    """Which ceremony step this shutdown is on, out of how many.

    ``index`` is the 1-based position of the step last entered in the current
    plan; it only moves forward. A step not on the plan (or already behind the
    current one) is not entered. ``reroute`` keeps every step already entered
    and appends the new path's steps not yet entered, so after a path change
    ``of`` = steps entered + steps remaining on the new path, and ``index``
    never exceeds ``of``. Thread-safe: the pipeline thread enters the hold.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plan: tuple[str, ...] = ()
        self._pos = -1

    def reset(self) -> None:
        """No plan, no step (grace, cancelled, before any loss)."""
        with self._lock:
            self._plan = ()
            self._pos = -1

    def begin(self, plan: Sequence[str]) -> None:
        """Start a plan with no step entered yet."""
        with self._lock:
            self._plan = tuple(plan)
            self._pos = -1

    def reroute(self, plan: Sequence[str]) -> None:
        """Switch to another path mid-run, keeping the steps already entered."""
        with self._lock:
            entered = self._plan[: self._pos + 1]
            self._plan = entered + tuple(s for s in plan if s not in entered)

    def enter(self, name: str) -> bool:
        """Enter ``name`` when it lies ahead on the plan.

        Returns:
            True when the step was entered (the caller publishes it).
        """
        with self._lock:
            ahead = self._plan[self._pos + 1 :]
            if name not in ahead:
                return False
            self._pos += 1 + ahead.index(name)
            return True

    def step(self) -> dict | None:
        """``{index, of, name}`` for the step last entered, or None before one."""
        with self._lock:
            if self._pos < 0:
                return None
            return {"index": self._pos + 1, "of": len(self._plan), "name": self._plan[self._pos]}
