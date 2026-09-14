################################################################################
# File Name: test_prior_shutdown_summary.py
# Purpose/Description: US-728 -- the operator surface for the prior-shutdown
#   verdict ``boot_progress.arm`` has written to ``startup_log`` every boot since
#   2026-08-25 and nothing displayed. Pins: clean / ungraceful / first-boot are
#   three distinguishable renders; the end time is a TYPED ABSENCE (the writer
#   stores NULL by construction); the next boot's ``recorded_at`` appears only
#   labelled as an upper bound; the dominant live verdict renders as "ended
#   without a recorded shutdown", never "crashed"; every ``_VERDICT_BY_STAGE``
#   reason has its own operator text (no clean/unclean collapse); and the reader
#   is READ-ONLY -- no second producer, no new table.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-13    | Ralph (Rex)  | Initial -- US-728 prior-shutdown surface.
# ================================================================================
################################################################################
"""US-728: surface the existing startup_log prior-shutdown verdict."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from src.pi.diagnostics import boot_progress
from src.pi.diagnostics.prior_shutdown_summary import (
    END_TIME_ABSENT,
    VERDICT_CLEAN,
    VERDICT_NO_RECORD,
    VERDICT_UNGRACEFUL,
    computePriorShutdownSummary,
    formatPriorShutdownLine,
    main,
    readPriorShutdownSummaryFromPath,
)
from src.pi.obdii.database_schema import SCHEMA_STARTUP_LOG

_NEXT_BOOT = "2026-09-11T22:11:25Z"


def _row(**overrides: object) -> dict:
    row: dict = {
        "boot_id": "abc123",
        "prior_boot_clean": 0,
        "prior_last_entry_ts": None,
        "prior_boot_last_stage": "RUNNING",
        "prior_boot_reason": "crashed_during_operation",
        "recorded_at": _NEXT_BOOT,
        "data_quality": "full",
    }
    row.update(overrides)
    return row


def _makeDb(tmp_path: Path, rows: list[dict]) -> str:
    dbPath = str(tmp_path / "obd.db")
    conn = sqlite3.connect(dbPath)
    try:
        conn.executescript(SCHEMA_STARTUP_LOG)
        for r in rows:
            conn.execute(
                "INSERT INTO startup_log (boot_id, prior_boot_clean, "
                "prior_last_entry_ts, prior_boot_last_stage, prior_boot_reason, "
                "recorded_at, data_quality) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (r["boot_id"], r["prior_boot_clean"], r["prior_last_entry_ts"],
                 r["prior_boot_last_stage"], r["prior_boot_reason"],
                 r["recorded_at"], r["data_quality"]),
            )
        conn.commit()
    finally:
        conn.close()
    return dbPath


# --------------------------------------------------------------------------------
# The three verdicts (validationCriteria 1-3)
# --------------------------------------------------------------------------------


def test_render_priorBootClean1_reportsCleanNamingItsTime():
    """
    Given: a startup_log row with prior_boot_clean = 1
    When: the surface is rendered
    Then: it reports CLEAN and names a time -- the next boot's recorded_at,
          labelled as an upper bound (the only time the record holds)
    """
    summary = computePriorShutdownSummary(
        _row(prior_boot_clean=1, prior_boot_last_stage="CLEAN_COMPLETE",
             prior_boot_reason="graceful")
    )

    assert summary.verdict == VERDICT_CLEAN
    line = formatPriorShutdownLine(summary)
    assert "CLEAN" in line
    assert _NEXT_BOOT in line
    assert "upper bound" in line
    assert "UNGRACEFUL" not in line


def test_render_priorBootClean0_reportsUngraceful():
    """
    Given: a row with prior_boot_clean = 0 (the live RUNNING verdict)
    When: the surface is rendered
    Then: it reports UNGRACEFUL
    """
    summary = computePriorShutdownSummary(_row())

    assert summary.verdict == VERDICT_UNGRACEFUL
    assert "UNGRACEFUL" in formatPriorShutdownLine(summary)


def test_render_priorBootCleanNull_reportsNoRecord_distinctFromUngraceful():
    """
    Given: a row with prior_boot_clean NULL (first boot / no trail)
    When: the surface is rendered
    Then: it reports NO RECORD -- never collapsed into ungraceful (or clean)
    """
    summary = computePriorShutdownSummary(
        _row(prior_boot_clean=None, prior_boot_last_stage=None,
             prior_boot_reason="indeterminate_no_record")
    )

    assert summary.verdict == VERDICT_NO_RECORD
    line = formatPriorShutdownLine(summary)
    assert "NO RECORD" in line
    assert "UNGRACEFUL" not in line
    assert "CLEAN" not in line


# --------------------------------------------------------------------------------
# WHEN is a typed absence (validationCriterion 4 -- the live condition)
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("emptyTs", [None, "", "   ", "1970-01-01T00:00:00Z"])
def test_render_priorLastEntryTsEmpty_isTypedAbsence(emptyTs):
    """
    Given: prior_last_entry_ts NULL / blank / epoch-zero
    When: the surface is rendered
    Then: the end time is the typed absence "end time not recorded" -- never a
          blank, never an epoch-zero timestamp, never rendered as "died at"
    """
    summary = computePriorShutdownSummary(_row(prior_last_entry_ts=emptyTs))

    assert summary.endedAtTs is None
    payload = summary.toStatePayload()
    assert payload["endedAtTs"] is None
    assert payload["endedAtAbsence"] == END_TIME_ABSENT
    line = formatPriorShutdownLine(summary)
    assert END_TIME_ABSENT in line
    assert "1970" not in line
    assert "died at" not in line.lower()


def test_render_recordedAt_isLabelledUpperBound_neverAnEndTime():
    """
    Given: the live shape (end time NULL, next boot recorded_at present)
    When: the payload is built
    Then: recorded_at travels ONLY as notAfterTs -- an upper bound -- and is
          not placed in endedAtTs (that would manufacture a time)
    """
    payload = computePriorShutdownSummary(_row()).toStatePayload()

    assert payload["endedAtTs"] is None
    assert payload["notAfterTs"] == _NEXT_BOOT


# --------------------------------------------------------------------------------
# Wording -- what the verdict proves, and nothing it does not
# --------------------------------------------------------------------------------


def test_render_runningVerdict_saysEndedWithoutRecordedShutdown_notCrashed():
    """
    Given: the dominant live verdict (RUNNING -> crashed_during_operation)
    When: rendered
    Then: the text is "ended without a recorded shutdown" -- a hard cut at
          key-off is not a crash, and the surface must not claim WHERE it ended
    """
    line = formatPriorShutdownLine(computePriorShutdownSummary(_row()))

    assert "ended without a recorded shutdown" in line
    assert "crash" not in line.lower()


def test_render_ungraceful_carriesTheTrueLimitation():
    """
    Given: an ungraceful verdict
    When: the payload is built
    Then: it carries the real caveat -- a graceful poweroff whose CLEAN_COMPLETE
          write did not land also reads this way -- and never a journal caveat
    """
    payload = computePriorShutdownSummary(_row()).toStatePayload()

    assert "CLEAN_COMPLETE" in payload["caveat"]
    assert "journal" not in payload["caveat"].lower()


def test_operatorText_everyVerdictByStageReason_hasDistinctText():
    """
    Given: every reason code boot_progress can write (_VERDICT_BY_STAGE)
    When: each is rendered
    Then: each has its own operator text -- no collapse to clean/unclean
    """
    reasons = sorted({r for _, r in boot_progress._VERDICT_BY_STAGE.values()})
    labels = set()
    for reason in reasons:
        clean = 1 if reason == "graceful" else 0
        summary = computePriorShutdownSummary(
            _row(prior_boot_clean=clean, prior_boot_reason=reason)
        )
        assert reason not in summary.label, f"{reason} has no operator text"
        labels.add(summary.label)

    assert len(labels) == len(reasons)


def test_render_unknownReasonCode_keepsCodeVerbatim_neverCollapses():
    """
    Given: a historical/future reason code this module has no wording for
    When: rendered
    Then: the verdict still follows prior_boot_clean and the code travels
          verbatim -- it is not silently merged into a known reason's text
    """
    summary = computePriorShutdownSummary(_row(prior_boot_reason="new_code_x"))

    assert summary.verdict == VERDICT_UNGRACEFUL
    assert "new_code_x" in summary.label


# --------------------------------------------------------------------------------
# Reader -- newest row, honest unknown, read-only
# --------------------------------------------------------------------------------


def test_read_picksNewestInsertedRow_notRecordedAtOrder(tmp_path):
    """
    Given: two rows where the newer boot has an EARLIER recorded_at (a dead-RTC
           clock_unsynced boot)
    When: read
    Then: the most recently INSERTED row wins -- wall-clock order is not trusted
    """
    dbPath = _makeDb(tmp_path, [
        _row(boot_id="old", prior_boot_clean=1, prior_boot_reason="graceful",
             recorded_at="2026-09-11T10:00:00Z"),
        _row(boot_id="new", recorded_at="1999-01-01T00:00:00Z",
             data_quality="clock_unsynced"),
    ])

    summary = readPriorShutdownSummaryFromPath(dbPath)

    assert summary is not None
    assert summary.bootId == "new"
    assert summary.verdict == VERDICT_UNGRACEFUL


def test_read_missingDbOrEmptyTable_returnsNone(tmp_path):
    """
    Given: no DB file / an empty startup_log
    When: read
    Then: None (not read) -- distinct from a NO RECORD row, never a fabricated verdict
    """
    assert readPriorShutdownSummaryFromPath(str(tmp_path / "absent.db")) is None
    assert readPriorShutdownSummaryFromPath(_makeDb(tmp_path, [])) is None
    assert not (tmp_path / "absent.db").exists()


def test_read_doesNotModifyTheDatabase(tmp_path):
    """
    Given: a populated startup_log
    When: read
    Then: the DB bytes are unchanged -- this story reads, it does not write
    """
    dbPath = _makeDb(tmp_path, [_row()])
    before = Path(dbPath).read_bytes()

    readPriorShutdownSummaryFromPath(dbPath)

    assert Path(dbPath).read_bytes() == before


def test_cli_printsTheVerdictLine(tmp_path, capsys):
    """
    Given: a populated DB
    When: the CLI runs against it
    Then: it prints the rendered line and exits 0
    """
    dbPath = _makeDb(tmp_path, [_row()])

    rc = main(["--db", dbPath])

    assert rc == 0
    assert "UNGRACEFUL" in capsys.readouterr().out


def test_cli_unreadableDb_printsNotRead(tmp_path, capsys):
    """
    Given: no DB
    When: the CLI runs
    Then: it says the record could not be read -- not a verdict
    """
    rc = main(["--db", str(tmp_path / "absent.db")])

    out = capsys.readouterr().out
    assert rc == 0
    assert "not read" in out
    assert "CLEAN" not in out and "UNGRACEFUL" not in out


# --------------------------------------------------------------------------------
# No second producer, no new table (validationCriterion 5)
# --------------------------------------------------------------------------------


def test_module_isReadOnly_noWriterNoNewTable():
    """
    Given: the new module's source
    When: scanned for SQL writes / DDL / breadcrumb writes
    Then: zero -- boot_progress.py and startup_log are read, not duplicated
    """
    src = (
        Path(__file__).resolve().parents[3]
        / "src/pi/diagnostics/prior_shutdown_summary.py"
    ).read_text(encoding="utf-8")

    for pattern in (r"\bINSERT\b", r"\bUPDATE\b", r"\bCREATE\s+TABLE\b",
                    r"\bALTER\b", r"markMilestone", r"CLEAN_COMPLETE\s*\)"):
        assert not re.search(pattern, src), pattern
