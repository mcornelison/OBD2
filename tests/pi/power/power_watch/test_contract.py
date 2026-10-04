################################################################################
# File Name: test_contract.py
# Purpose/Description: Contract tests: power_watch OutcomeKind + ShutdownTask
#                      protocol are the single source of truth.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T1 contract tests.
# 2026-05-19    | Plan SS-T6 | Rename PipelineTask -> ShutdownTask (the
#                              Protocol-name rename in SS-T6).
# 2026-10-01    | Rex (US-776-d) | Pin the six sync-outcome kinds.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T3: pin STALLED + RESERVE_FLOOR.
# ================================================================================
################################################################################
"""Contract: outcome kinds + shutdown-task protocol are the single source of truth."""
from src.pi.power.power_watch.contract import (
    RECORD_SCHEMA_VERSION,
    OutcomeKind,
    ShutdownTask,
)


def test_outcomeKinds_exact():
    assert {k.value for k in OutcomeKind} == {
        "server_unavailable", "sync_failed_after_retry", "real_error", "ok",
        # US-776-d: why the shutdown sync ended.
        "delivered", "away", "unknown_network", "at_home_joining_timeout",
        "at_home_server_down", "probe_misconfigured",
        # ARCH-065: the at-home sync runs to completion.
        "stalled", "reserve_floor",
    }
    assert {k.name for k in OutcomeKind} == {
        "OK", "SERVER_UNAVAILABLE", "SYNC_FAILED_AFTER_RETRY", "REAL_ERROR",
        "DELIVERED", "AWAY", "UNKNOWN_NETWORK", "AT_HOME_JOINING_TIMEOUT",
        "AT_HOME_SERVER_DOWN", "PROBE_MISCONFIGURED", "STALLED", "RESERVE_FLOOR",
    }


def test_shutdownTask_structuralConformance():
    """A minimal conforming task: has a str `name` and a `run()` returning an
    OutcomeKind. Locks the protocol shape for the importers. SS-T6: protocol
    is now @runtime_checkable so isinstance() works (the seam test in
    tests/.../test_task_seam.py uses it)."""

    class _DummyTask:
        name = "dummy"

        def run(self) -> OutcomeKind:
            return OutcomeKind.OK

    task: ShutdownTask = _DummyTask()  # static structural check (mypy/pyright)
    assert isinstance(task.name, str)
    assert isinstance(task.run(), OutcomeKind)
    # SS-T6: runtime-checkable membership (the new contract).
    assert isinstance(task, ShutdownTask)


def test_schema_version_is_int():
    assert isinstance(RECORD_SCHEMA_VERSION, int) and RECORD_SCHEMA_VERSION >= 1
