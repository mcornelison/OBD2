"""Contract tests: the stage vocabulary is one shared source of truth."""
from src.pi.diagnostics.boot_progress import Stage, MILESTONE_ORDER, CLEAN_COMPLETE_RUNG


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
