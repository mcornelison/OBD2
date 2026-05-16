################################################################################
# File Name: test_boot_progress_contract.py
# Purpose/Description: Contract tests for the shared boot_progress Stage
#                      vocabulary -- pins enum membership, ordering, and the
#                      single clean-proof rung so any drift fails at PR time.
# Author: (implementation plan 2026-05-15)
# Creation Date: 2026-05-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-15    | Plan    | Initial -- Task 1 contract tests.
# ================================================================================
################################################################################
"""Contract tests: the stage vocabulary is one shared source of truth."""
from src.pi.diagnostics.boot_progress import (
    CLEAN_COMPLETE_RUNG,
    MILESTONE_ORDER,
    Stage,
)


def test_milestoneOrder_isMonotonicAndComplete():
    names = [s.value for s in MILESTONE_ORDER]
    assert names == [
        "RUNNING", "WARNING", "IMMINENT", "TRIGGER", "DRAIN_CLOSED",
        "TRIGGER_ROW_WRITTEN", "POWEROFF_INVOKED", "POWEROFF_RC0",
        "CLEAN_COMPLETE",
    ]


def test_cleanCompleteRung_isTheOnlyCleanProof():
    assert CLEAN_COMPLETE_RUNG is Stage.CLEAN_COMPLETE
    assert MILESTONE_ORDER[-1] is Stage.CLEAN_COMPLETE
    assert MILESTONE_ORDER[0] is Stage.RUNNING
