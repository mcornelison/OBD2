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
# 2026-05-15    | Plan    | T6 -- finalize verbatim-append + CLI ExecStop contract tests.
# ================================================================================
################################################################################
"""Contract tests: the stage vocabulary is one shared source of truth."""
import json
import subprocess
import sys

from src.pi.diagnostics.boot_progress import (
    CLEAN_COMPLETE_RUNG,
    MILESTONE_ORDER,
    Stage,
    finalize,
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


def test_finalize_appendsCleanCompleteVerbatim(tmp_path):
    f = tmp_path / "boot_progress"
    f.write_text('{"boot_id":"b","stage":"POWEROFF_RC0","ts":"t","vcell":3.4}\n',
                 encoding="utf-8")
    finalize(filePath=str(f), bootId="b")
    last = json.loads(f.read_text(encoding="utf-8").splitlines()[-1])
    assert last["stage"] == "CLEAN_COMPLETE"


def test_cli_finalize_invokedAsTheUnitInvokesIt(tmp_path):
    """Runs `python -m src.pi.diagnostics.boot_progress --finalize` exactly
    as boot-progress-finalize.service ExecStop does -- guards the US-277
    silent-import-failure class."""
    f = tmp_path / "boot_progress"
    f.write_text('{"boot_id":"b","stage":"POWEROFF_RC0","ts":"t","vcell":3}\n',
                 encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "src.pi.diagnostics.boot_progress",
         "--finalize", "--file", str(f), "--boot-id", "b"],
        capture_output=True, text=True, cwd=".",
    )
    assert r.returncode == 0, r.stderr
    assert "CLEAN_COMPLETE" in f.read_text(encoding="utf-8")
