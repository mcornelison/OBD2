################################################################################
# File Name: test_boot_progress_integration.py
# Purpose/Description: Real-chain integration: real markMilestone rungs -> real
#                      on-disk trail -> real arm/reader -> real startup_log
#                      verdict.  Faking only the OS edges.  Institutionalizes
#                      the L9 lesson (only end-to-end real-path testing catches
#                      the I-037 false-positive class).
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-17    | Plan         | Initial -- T13 real-chain integration tests.
################################################################################
"""Real chain: real markMilestone rungs -> real on-disk trail -> real arm/
reader -> verdict. Only the OS edges (file path, db path) are tmp-faked.
Had this existed, US-308/330/342 would have failed at PR."""
import sqlite3

from src.pi.diagnostics.boot_progress import Stage, arm, markMilestone
from src.pi.obdii.database_schema import SCHEMA_STARTUP_LOG


def test_hardCrashAfterPoweroffInvoked_readsBackZero(tmp_path):
    f = str(tmp_path / "boot_progress")
    db = str(tmp_path / "obd.db")
    sqlite3.connect(db).executescript(SCHEMA_STARTUP_LOG)

    # Boot N: arm, then drive the real ladder rungs, then SIMULATE A HARD
    # CRASH right after POWEROFF_INVOKED (no CLEAN_COMPLETE ever written).
    markMilestone(Stage.RUNNING, vcell=None, filePath=f, bootId="N")
    for s, v in [(Stage.WARNING, 3.70), (Stage.IMMINENT, 3.55),
                 (Stage.TRIGGER, 3.45), (Stage.DRAIN_CLOSED, 3.45),
                 (Stage.TRIGGER_ROW_WRITTEN, 3.44),
                 (Stage.POWEROFF_INVOKED, 3.44)]:
        markMilestone(s, vcell=v, filePath=f, bootId="N")
    # <-- crash here: process dies, finalizer ExecStop never runs

    # Boot N+1: arm reads the prior trail
    arm(filePath=f, dbPath=db, bootId="N1",
        nasArchiveDir=str(tmp_path / "nas"), nasArchiveEnabled=False)

    row = sqlite3.connect(db).execute(
        "SELECT prior_boot_clean, prior_boot_last_stage, prior_boot_reason "
        "FROM startup_log WHERE boot_id='N1'").fetchone()
    assert row == (0, "POWEROFF_INVOKED", "poweroff_invoked_never_returned")


def test_gracefulShutdown_readsBackOne(tmp_path):
    f = str(tmp_path / "boot_progress")
    db = str(tmp_path / "obd.db")
    sqlite3.connect(db).executescript(SCHEMA_STARTUP_LOG)
    markMilestone(Stage.RUNNING, vcell=None, filePath=f, bootId="N")
    for s in [Stage.WARNING, Stage.IMMINENT, Stage.TRIGGER,
              Stage.DRAIN_CLOSED, Stage.TRIGGER_ROW_WRITTEN,
              Stage.POWEROFF_INVOKED, Stage.POWEROFF_RC0,
              Stage.CLEAN_COMPLETE]:
        markMilestone(s, vcell=3.4, filePath=f, bootId="N")
    arm(filePath=f, dbPath=db, bootId="N1",
        nasArchiveDir=str(tmp_path / "n"), nasArchiveEnabled=False)
    row = sqlite3.connect(db).execute(
        "SELECT prior_boot_clean, prior_boot_reason FROM startup_log "
        "WHERE boot_id='N1'").fetchone()
    assert row == (1, "graceful")
