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
# 2026-05-15    | Plan    | T3-T4 -- verdict + startup_log schema migrator tests.
# 2026-05-15    | Plan    | T5 -- arm reader tests (verdict -> startup_log -> re-arm).
# ================================================================================
################################################################################
"""Failure-shape + behavior tests for the honest boot-progress instrument."""
import json
import sqlite3

import pytest

from src.pi.diagnostics.boot_progress import (
    Stage,
    arm,
    deriveVerdict,
    markMilestone,
    readPriorTrail,
)
from src.pi.obdii.database_schema import (
    SCHEMA_STARTUP_LOG,
    ensureStartupLogForensicColumns,
)


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


def _writeTrail(path, stages):
    import json as _j
    path.write_text(
        "".join(_j.dumps({"boot_id": "b", "stage": s, "ts": "t",
                           "vcell": 3.5}) + "\n" for s in stages),
        encoding="utf-8",
    )


@pytest.mark.parametrize("stages,clean,reason", [
    (["RUNNING", "WARNING", "IMMINENT", "TRIGGER", "DRAIN_CLOSED",
      "TRIGGER_ROW_WRITTEN", "POWEROFF_INVOKED", "POWEROFF_RC0",
      "CLEAN_COMPLETE"], 1, "graceful"),
    (["RUNNING", "WARNING", "IMMINENT", "TRIGGER", "DRAIN_CLOSED",
      "TRIGGER_ROW_WRITTEN", "POWEROFF_INVOKED", "POWEROFF_RC0"],
     0, "poweroff_accepted_unfinalized"),
    (["RUNNING", "WARNING", "IMMINENT", "TRIGGER", "DRAIN_CLOSED",
      "TRIGGER_ROW_WRITTEN", "POWEROFF_INVOKED"],
     0, "poweroff_invoked_never_returned"),
    (["RUNNING", "WARNING", "IMMINENT", "TRIGGER"],
     0, "wedged_before_poweroff"),
    (["RUNNING", "WARNING", "IMMINENT"], 0, "died_mid_drain"),
    (["RUNNING"], 0, "crashed_during_operation"),
])
def test_deriveVerdict_positiveProofOnly(tmp_path, stages, clean, reason):
    f = tmp_path / "boot_progress"
    _writeTrail(f, stages)
    trail = readPriorTrail(str(f))
    priorClean, priorStage, priorReason = deriveVerdict(trail)
    assert priorClean == clean
    assert priorReason == reason
    assert priorStage == stages[-1]


def test_deriveVerdict_missingFileIsNullNotClean(tmp_path):
    trail = readPriorTrail(str(tmp_path / "nope"))
    priorClean, priorStage, priorReason = deriveVerdict(trail)
    assert priorClean is None
    assert priorReason == "indeterminate_no_record"


def test_deriveVerdict_corruptLinesIgnored_highestStillWins(tmp_path):
    f = tmp_path / "boot_progress"
    f.write_text('{"stage":"TRIGGER"}\nGARBAGE NOT JSON\n'
                 '{"stage":"POWEROFF_INVOKED"}\n', encoding="utf-8")
    priorClean, priorStage, priorReason = deriveVerdict(readPriorTrail(str(f)))
    assert priorClean == 0
    assert priorStage == "POWEROFF_INVOKED"


def test_deriveVerdict_lowerRungAfterHigherIsIgnored(tmp_path):
    f = tmp_path / "boot_progress"
    _writeTrail(f, ["RUNNING", "TRIGGER", "WARNING"])
    priorClean, priorStage, _ = deriveVerdict(readPriorTrail(str(f)))
    assert priorStage == "TRIGGER"


def test_ensureStartupLogForensicColumns_addsColumnsOnLegacyDb(tmp_path):
    db = tmp_path / "obd.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE startup_log (
        boot_id TEXT PRIMARY KEY, prior_boot_clean INTEGER,
        prior_last_entry_ts TEXT, current_boot_first_entry_ts TEXT,
        recorded_at TEXT NOT NULL DEFAULT '')""")
    conn.commit()
    ensureStartupLogForensicColumns(conn)
    ensureStartupLogForensicColumns(conn)  # idempotent
    cols = {r[1] for r in conn.execute("PRAGMA table_info(startup_log)")}
    assert "prior_boot_last_stage" in cols
    assert "prior_boot_reason" in cols
    conn.close()


def test_schemaStartupLog_freshDbHasForensicColumns(tmp_path):
    conn = sqlite3.connect(tmp_path / "fresh.db")
    conn.executescript(SCHEMA_STARTUP_LOG)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(startup_log)")}
    assert {"prior_boot_last_stage", "prior_boot_reason"} <= cols
    conn.close()


def test_arm_writesVerdictRow_thenReArmsRunning(tmp_path):
    f = tmp_path / "boot_progress"
    _writeTrail(f, ["RUNNING", "WARNING", "IMMINENT", "TRIGGER",
                    "POWEROFF_INVOKED"])  # Drain-26 shape
    db = tmp_path / "obd.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_STARTUP_LOG)
    conn.close()

    arm(filePath=str(f), dbPath=str(db), bootId="newboot1",
        nasArchiveDir=str(tmp_path / "nas"), nasArchiveEnabled=True)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT prior_boot_clean, prior_boot_last_stage, prior_boot_reason "
        "FROM startup_log WHERE boot_id='newboot1'").fetchone()
    conn.close()
    assert row == (0, "POWEROFF_INVOKED", "poweroff_invoked_never_returned")
    lines = f.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["stage"] == "RUNNING"
    assert json.loads(lines[0])["boot_id"] == "newboot1"
    assert any((tmp_path / "nas").iterdir())


def test_arm_idempotentInsertOrIgnore(tmp_path):
    f = tmp_path / "boot_progress"
    _writeTrail(f, ["RUNNING"])
    db = tmp_path / "obd.db"
    sqlite3.connect(db).executescript(SCHEMA_STARTUP_LOG)
    arm(filePath=str(f), dbPath=str(db), bootId="dup",
        nasArchiveDir=str(tmp_path / "n"), nasArchiveEnabled=False)
    _writeTrail(f, ["RUNNING", "WARNING"])
    arm(filePath=str(f), dbPath=str(db), bootId="dup",
        nasArchiveDir=str(tmp_path / "n"), nasArchiveEnabled=False)
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM startup_log WHERE boot_id='dup'").fetchone()[0]
    conn.close()
    assert n == 1


def test_arm_stillReArmsWhenDbWriteFails(tmp_path):
    f = tmp_path / "boot_progress"
    _writeTrail(f, ["RUNNING", "TRIGGER"])
    arm(filePath=str(f), dbPath="/proc/cannot/write.db", bootId="x",
        nasArchiveDir=str(tmp_path / "n"), nasArchiveEnabled=False)
    lines = f.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["stage"] == "RUNNING"
