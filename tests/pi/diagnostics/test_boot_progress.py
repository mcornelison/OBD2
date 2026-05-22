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
# 2026-05-21    | Rex     | US-353 -- maxTrailBytes auto-trim semantics (replaces
#                          refuse-to-write that blocked first post-deploy reboot).
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


def test_markMilestone_autoTrimsAtMaxTrailBytes(tmp_path):
    """US-353: maxTrailBytes auto-trim keeps the trail bounded across many
    writes. Replaces the prior refuse-to-write guard that Argus's drill
    found blocking the first post-deploy reboot when the trail had
    accumulated from the F-8-broken regime."""
    f = tmp_path / "boot_progress"
    for _ in range(50):
        markMilestone(Stage.RUNNING, vcell=3.9, filePath=str(f),
                      bootId="b", maxTrailBytes=120)
    size = f.stat().st_size
    # Bound: trim keeps remaining <= maxTrailBytes; one fresh line is
    # always appended (refusing to log a rung is the observability hole
    # we are closing). One line is ~80 bytes here.
    assert size <= 120 + 200
    # And the file MUST still hold the most recent rung -- the contract
    # we are now enforcing is "every rung lands on disk".
    lastLine = f.read_text(encoding="utf-8").splitlines()[-1]
    assert json.loads(lastLine)["stage"] == "RUNNING"


def test_markMilestone_autoTrim_dropsOldestNotNewest(tmp_path):
    """US-353: trim drops oldest complete lines; newest rung is always
    preserved. Important because deriveVerdict uses MAX(rank), but the
    MOST recent rung is the load-bearing signal for the verdict."""
    f = tmp_path / "boot_progress"
    # Seed with WARNING rungs that take the trail past the cap.
    for _ in range(10):
        markMilestone(Stage.WARNING, vcell=3.70, filePath=str(f),
                      bootId="seed", maxTrailBytes=120)
    # Now drop a distinctive high-rank rung; it must survive the trim
    # and be the last line on disk.
    markMilestone(Stage.POWEROFF_INVOKED, vcell=3.40, filePath=str(f),
                  bootId="newboot", maxTrailBytes=120)
    lines = f.read_text(encoding="utf-8").splitlines()
    lastRec = json.loads(lines[-1])
    assert lastRec["stage"] == "POWEROFF_INVOKED"
    assert lastRec["boot_id"] == "newboot"


def test_markMilestone_autoTrim_warnsWithTrimmedSize(tmp_path, caplog):
    """US-353: WARN log on auto-trim names was/trimmed_to/maxTrailBytes
    so operators can see when the guard fired and what it did. Silent
    truncation would mask the same observability hole from a different
    angle."""
    f = tmp_path / "boot_progress"
    # Pre-seed near the cap so a single subsequent write trips trim.
    f.write_bytes(b'{"stage":"RUNNING","ts":"t1"}\n' * 6)  # ~180 bytes
    caplog.clear()
    with caplog.at_level("WARNING", logger="src.pi.diagnostics.boot_progress"):
        markMilestone(Stage.TRIGGER, vcell=3.5, filePath=str(f),
                      bootId="b", maxTrailBytes=120)
    trimRecords = [r for r in caplog.records
                   if "trimmed" in r.message.lower()]
    assert trimRecords, "expected WARN log on auto-trim"
    msg = trimRecords[0].getMessage()
    assert "was" in msg.lower()
    assert "maxTrailBytes" in msg or "max_trail_bytes" in msg.lower()


def test_markMilestone_autoTrim_neverRefusesWrite(tmp_path):
    """US-353: contract test -- the new milestone ALWAYS lands on disk,
    even when the trail was already over the cap before the write.
    Argus's drill: pre-deploy trail accumulated past 65536 bytes; first
    post-deploy reboot tripped the refuse-to-write guard and the rung
    never made it to the file. That cannot happen anymore."""
    f = tmp_path / "boot_progress"
    # Pre-seed already past the cap.
    f.write_bytes(b'{"stage":"RUNNING","ts":"t"}\n' * 100)  # ~2900 bytes
    pre = f.stat().st_size
    assert pre > 200  # sanity: actually over cap
    markMilestone(Stage.DRAIN_CLOSED, vcell=3.4, filePath=str(f),
                  bootId="postdeploy", maxTrailBytes=200)
    lines = f.read_text(encoding="utf-8").splitlines()
    lastRec = json.loads(lines[-1])
    assert lastRec["stage"] == "DRAIN_CLOSED"
    assert lastRec["boot_id"] == "postdeploy"
    # And the trail stays bounded after the trim.
    assert f.stat().st_size <= 200 + 200


def test_markMilestone_threeConsecutiveCleanReboots_doNotTripTrim(
    tmp_path, caplog,
):
    """US-353 acceptance: 3 consecutive simulated clean-shutdown +
    reboot cycles produce 3 consecutive CLEAN_COMPLETE writes + no
    trim WARN across all 3 cycles. Trail size after each cycle stays
    bounded (post-F-8-fix arm() truncates between boots)."""
    f = tmp_path / "boot_progress"
    db = tmp_path / "obd.db"
    sqlite3.connect(db).executescript(SCHEMA_STARTUP_LOG)
    fullLadder = (
        Stage.RUNNING, Stage.WARNING, Stage.IMMINENT, Stage.TRIGGER,
        Stage.DRAIN_CLOSED, Stage.TRIGGER_ROW_WRITTEN,
        Stage.POWEROFF_INVOKED, Stage.POWEROFF_RC0, Stage.CLEAN_COMPLETE,
    )
    caplog.clear()
    with caplog.at_level("WARNING", logger="src.pi.diagnostics.boot_progress"):
        for cycle in range(3):
            for stage in fullLadder:
                markMilestone(stage, vcell=3.5, filePath=str(f),
                              bootId=f"boot{cycle}")
            arm(filePath=str(f), dbPath=str(db),
                bootId=f"boot{cycle+1}",
                nasArchiveDir=str(tmp_path / "nas"),
                nasArchiveEnabled=False)
    trimRecords = [r for r in caplog.records
                   if "trimmed" in r.message.lower()]
    assert trimRecords == [], f"unexpected trim WARN: {trimRecords}"
    # After 3 arm() cycles the file holds only the most recent RUNNING
    # rearm for cycle 3 -- bounded, fresh.
    lines = f.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["stage"] == "RUNNING"


def test_markMilestone_forcedLargeTrail_autoTrimsAndWarns(tmp_path, caplog):
    """US-353 conditional acceptance: pre-seed trail to ~95% of the cap
    and write one more rung. Auto-trim must fire, WARN must emit, the
    new rung must land on disk, and the bound must hold."""
    f = tmp_path / "boot_progress"
    cap = 1024
    seedLine = b'{"stage":"RUNNING","ts":"seed","vcell":3.9}\n'
    # ~95% of cap, line-boundary aligned.
    n = int((cap * 0.95) // len(seedLine))
    f.write_bytes(seedLine * n)
    preSize = f.stat().st_size
    caplog.clear()
    with caplog.at_level("WARNING", logger="src.pi.diagnostics.boot_progress"):
        for _ in range(10):
            markMilestone(Stage.TRIGGER, vcell=3.5, filePath=str(f),
                          bootId="forced", maxTrailBytes=cap)
    assert any("trimmed" in r.message.lower() for r in caplog.records)
    assert f.stat().st_size <= cap + 200
    lastRec = json.loads(f.read_text(encoding="utf-8").splitlines()[-1])
    assert lastRec["stage"] == "TRIGGER"
    assert lastRec["boot_id"] == "forced"
    assert preSize > 0  # sanity: seed actually wrote


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
