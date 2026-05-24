################################################################################
# File Name: test_pipeline.py
# Purpose/Description: Tests: power_watch bounded pipeline runner -- ordered,
#                      best-effort, per-task hard timeout, failure-isolated,
#                      never raises.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T3 pipeline runner tests.
# ================================================================================
################################################################################
import time

from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.pipeline import runPipeline


class _Task:
    def __init__(self, name, fn): self.name = name; self._fn = fn  # noqa: E702
    def run(self): return self._fn()


def test_runs_in_order_and_isolates_failure():
    seen = []
    def a(): seen.append("a"); return OutcomeKind.OK  # noqa: E702
    def b(): seen.append("b"); raise RuntimeError("explode")  # noqa: E702 -- contract says don't raise; runner still isolates
    def c(): seen.append("c"); return OutcomeKind.OK  # noqa: E702
    results = runPipeline([_Task("a", a), _Task("b", b), _Task("c", c)], perTaskTimeoutSec=1.0)
    assert seen == ["a", "b", "c"]                       # one failure never blocks the next
    assert results["a"] == OutcomeKind.OK
    assert results["b"] == OutcomeKind.REAL_ERROR        # raised -> real_error, isolated
    assert results["c"] == OutcomeKind.OK


def test_per_task_timeout_does_not_hang():
    def slow(): time.sleep(5); return OutcomeKind.OK  # noqa: E702
    t0 = time.monotonic()
    results = runPipeline([_Task("slow", slow)], perTaskTimeoutSec=0.5)
    assert time.monotonic() - t0 < 3.0                    # bounded, not 5s
    assert results["slow"] == OutcomeKind.REAL_ERROR      # timed out -> real_error
