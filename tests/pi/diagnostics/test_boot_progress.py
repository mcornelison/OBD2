################################################################################
# File Name: test_boot_progress.py
# Purpose/Description: Failure-shape + behavior tests for the honest
#                      boot-progress instrument.
# Author: (implementation plan 2026-05-15)
# Creation Date: 2026-05-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-15    | Plan    | Initial -- Task 2 markMilestone tests.
# ================================================================================
################################################################################
"""Failure-shape + behavior tests for the honest boot-progress instrument."""
import json

from src.pi.diagnostics.boot_progress import Stage, markMilestone


def test_markMilestone_appendsOneJsonLineWithFields(tmp_path):
    f = tmp_path / "boot_progress"
    markMilestone(Stage.TRIGGER, vcell=3.446, filePath=str(f), bootId="abc123")
    lines = f.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["stage"] == "TRIGGER"
    assert rec["vcell"] == 3.446
    assert rec["boot_id"] == "abc123"
    assert "ts" in rec


def test_markMilestone_isAppendOnly(tmp_path):
    f = tmp_path / "boot_progress"
    markMilestone(Stage.WARNING, vcell=3.70, filePath=str(f), bootId="b")
    markMilestone(Stage.IMMINENT, vcell=3.55, filePath=str(f), bootId="b")
    assert len(f.read_text(encoding="utf-8").splitlines()) == 2


def test_markMilestone_neverRaisesOnUnwritablePath(caplog):
    bad = "/proc/cpuinfo/cannot/write/here"
    markMilestone(Stage.POWEROFF_INVOKED, vcell=3.4, filePath=bad, bootId="b")
    assert any("boot_progress" in r.message for r in caplog.records)


def test_markMilestone_stopsAtMaxTrailBytes(tmp_path, caplog):
    f = tmp_path / "boot_progress"
    for _ in range(50):
        markMilestone(Stage.RUNNING, vcell=3.9, filePath=str(f),
                      bootId="b", maxTrailBytes=120)
    assert f.stat().st_size <= 120 + 200
