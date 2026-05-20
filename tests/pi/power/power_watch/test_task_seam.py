################################################################################
# File Name: test_task_seam.py
# Purpose/Description: SS-T6 ShutdownTask Protocol + V1 single-task registry
#                      seam tests. Asserts (1) the renamed Protocol exists
#                      and SyncWithServerTask satisfies it; (2) the documented
#                      buildV1Tasks(syncTask) seam exists in __main__.py and
#                      returns exactly the one V1 task (Option A scope).
# Author: (shutdown-sequencer plan 2026-05-18, SS-T6)
# Creation Date: 2026-05-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-19    | Plan (SS-T6) | Initial -- the Protocol rename guard + single
#                                explicit registry-seam guard. The seam is the
#                                ONLY edit point for future plugin tasks.
# ================================================================================
################################################################################
"""SS-T6: ShutdownTask Protocol + V1 task-registry seam."""

from src.pi.power.power_watch.contract import ShutdownTask
from src.pi.power.power_watch.tasks.sync_with_server import SyncWithServerTask


def test_v1_hasExactlyOneShutdownTask_andSeamIsPluggable():
    """Plan Task 6 Step 1. SyncWithServerTask must satisfy the renamed
    ShutdownTask Protocol (`name` + `run()`), and the explicit single-point
    registry seam ``buildV1Tasks(syncTask)`` must exist in __main__.py."""
    t = SyncWithServerTask(
        serverReachable=lambda: False,
        runSync=lambda: None,
        writeRecord=lambda _x: None,
    )
    assert isinstance(t, ShutdownTask)  # satisfies the runtime-checkable protocol

    from src.pi.power.power_watch import __main__ as m
    assert hasattr(m, "buildV1Tasks"), "the documented registry seam"

    # V1 scope (Option A, locked): EXACTLY one task. Future tasks append here
    # -- this is the ONLY edit point; ShutdownSequencer + runPipeline are
    # untouched when new tasks land.
    result = m.buildV1Tasks(t)
    assert isinstance(result, list)
    assert len(result) == 1, (
        f"V1 has exactly one task (Option A); got {len(result)}"
    )
    assert result[0] is t
