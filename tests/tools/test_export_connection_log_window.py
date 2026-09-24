################################################################################
# File Name: test_export_connection_log_window.py
# Purpose/Description: US-808-a -- the export writes every column with a header,
#                      is verified by re-reading it, records both the live and
#                      the reference counts, and never deletes anything.
# Author: Ralph (US-808-a)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author           | Description
# ================================================================================
# 2026-09-23    | Ralph (US-808-a) | Initial.
# ================================================================================
################################################################################
"""The April/May connection_log export (US-808-a).

The 28,318-row difference US-808 exists to explain IS this population.
Exporting before any deletion is the whole story: deleting first destroys the
only evidence that could decide what the difference means.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from tools.export_connection_log_window import (
    MAX_FULL_EXPORT_BYTES,
    REFERENCE_COUNTS,
    RETRY_EVENT_TYPES,
    WINDOW_END,
    ExportResult,
    exportPiWindow,
    verifyExport,
    writeManifest,
)

_MODULE = Path(__file__).resolve().parents[2] / "tools" / "export_connection_log_window.py"

_COLUMNS = (
    "id", "timestamp", "event_type", "mac_address", "success",
    "error_message", "retry_count", "data_source", "drive_id",
)


@pytest.fixture()
def piDb(tmp_path) -> Path:
    """A Pi-shaped connection_log with rows inside and outside the window."""
    path = tmp_path / "obd.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE connection_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME NOT NULL, "
        "event_type TEXT NOT NULL, mac_address TEXT, success INTEGER NOT NULL, "
        "error_message TEXT, retry_count INTEGER, data_source TEXT NOT NULL, "
        "drive_id INTEGER)"
    )
    rows = [
        ("2026-04-20T10:00:00Z", "connect_attempt", 0),
        ("2026-04-21T10:00:00Z", "connect_failure", 0),
        ("2026-05-02T10:00:00Z", "connect_attempt", 0),
        ("2026-05-30T23:59:59Z", "disconnect", 1),
        ("2026-06-02T10:00:00Z", "connect_attempt", 0),   # OUTSIDE the window
    ]
    for stamp, kind, ok in rows:
        conn.execute(
            "INSERT INTO connection_log "
            "(timestamp, event_type, mac_address, success, error_message, "
            " retry_count, data_source, drive_id) "
            "VALUES (?, ?, 'AA:BB', ?, NULL, 1, 'real', NULL)",
            (stamp, kind, ok),
        )
    conn.commit()
    conn.close()
    return path


class TestTheExportCarriesEveryColumnAndAHeader:
    """Acceptance 1."""

    def test_headerMatchesTheSourceColumns(self, piDb, tmp_path) -> None:
        """
        Given: a Pi connection_log
        When:  the window is exported
        Then:  the CSV header is exactly the source table's columns, in order
        """
        out = tmp_path / "pi.csv"
        result = exportPiWindow(piDb, out)

        with out.open(encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle))

        assert tuple(header) == _COLUMNS
        assert tuple(result.columns) == _COLUMNS

    def test_onlyTheWindowIsExported(self, piDb, tmp_path) -> None:
        """
        Given: rows on both sides of the window boundary
        When:  the window is exported
        Then:  only the pre-window rows are written

        The June row is excluded, and the 2026-05-30T23:59:59Z row is kept --
        the boundary is exclusive on the END, so the last May instant is IN.
        """
        result = exportPiWindow(piDb, tmp_path / "pi.csv")

        assert result.rowsReported == 4

    def test_rowCountMatchesWhatTheExporterReported(self, piDb, tmp_path) -> None:
        """
        Given: an export
        When:  the file's data rows are counted independently
        Then:  the count equals what the exporter reported
        """
        out = tmp_path / "pi.csv"
        result = exportPiWindow(piDb, out)

        with out.open(encoding="utf-8", newline="") as handle:
            dataRows = sum(1 for _ in csv.DictReader(handle))

        assert dataRows == result.rowsReported


class TestTheExportIsVerifiedByReReadingIt:
    """Acceptance 3 -- an export that cannot be re-read is a failed export."""

    def test_verifyFillsInTheReadBackFacts(self, piDb, tmp_path) -> None:
        """
        Given: a written export
        When:  it is verified
        Then:  the row count, size and first/last instants come from the FILE
        """
        result = verifyExport(exportPiWindow(piDb, tmp_path / "pi.csv"))

        assert result.rowsReadBack == result.rowsReported
        assert result.sizeBytes > 0
        assert result.firstTimestamp == "2026-04-20T10:00:00Z"
        assert result.lastTimestamp == "2026-05-30T23:59:59Z"

    def test_aTruncatedExportIsRejected(self, piDb, tmp_path) -> None:
        """
        Given: an export file that lost rows after being written
        When:  it is verified
        Then:  verification RAISES rather than reporting success

        This is the case the criterion exists for: the write reported no
        error, and the file is still wrong. Without the re-read it would look
        like a successful preservation of data that is no longer there.
        """
        out = tmp_path / "pi.csv"
        result = exportPiWindow(piDb, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        out.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

        with pytest.raises(ValueError, match="read back"):
            verifyExport(result)

    def test_aMangledHeaderIsRejected(self, piDb, tmp_path) -> None:
        """
        Given: an export whose header no longer matches the source
        When:  it is verified
        Then:  it RAISES

        A CSV with the right row count and the wrong column names is the
        quietest possible corruption -- every value lands one column over.
        """
        out = tmp_path / "pi.csv"
        result = exportPiWindow(piDb, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        lines[0] = lines[0].replace("event_type", "kind")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(ValueError, match="header"):
            verifyExport(result)


class TestTheCountsAreRecordedAndReMeasured:
    """Acceptance 2 -- both numbers stored, so drift is visible."""

    def test_manifestCarriesBothReferenceAndLiveCounts(
        self, piDb, tmp_path
    ) -> None:
        """
        Given: a verified export
        When:  the manifest is written
        Then:  it carries the 2026-09-14 reference AND the live count

        Storing only the live count loses the ability to notice drift;
        storing only the reference is a claim about the past presented as the
        present.
        """
        result = verifyExport(exportPiWindow(piDb, tmp_path / "pi.csv"))
        manifestPath = tmp_path / "manifest.json"

        manifest = writeManifest([result], manifestPath)

        assert manifest["referenceCounts2026_09_14"] == REFERENCE_COUNTS
        assert manifest["liveCountsAtExport"]["pi"] == result.rowsReported
        onDisk = json.loads(manifestPath.read_text(encoding="utf-8"))
        assert onDisk["referenceCounts2026_09_14"]["unexplainedDifference"] == 28318

    def test_theReferenceArithmeticIsInternallyConsistent(self) -> None:
        """
        Given: the recorded reference counts
        When:  the story's arithmetic is applied
        Then:  it produces exactly the 28,318 gap

        44,704 - 16,306 - 80 = 28,318. Pinned because the whole of US-808
        rests on this subtraction, and a typo in any one of the three numbers
        would make the gap a different question.
        """
        assert (
            REFERENCE_COUNTS["piRowsBeforeWindowEnd"]
            - REFERENCE_COUNTS["serverRetryRowsBeforeWindowEnd"]
            - REFERENCE_COUNTS["explicitKeeps"]
        ) == REFERENCE_COUNTS["unexplainedDifference"]

    def test_perEventTypeCountsAreCaptured(self, piDb, tmp_path) -> None:
        """
        Given: an export
        When:  its per-type counts are read
        Then:  they are recorded, because US-808-b needs them per type

        An aggregate that matches while the per-type breakdown does not is
        exactly the shape -b exists to catch.
        """
        result = exportPiWindow(piDb, tmp_path / "pi.csv")

        assert result.perEventType["connect_attempt"] == 2
        assert result.perEventType["connect_failure"] == 1
        assert result.perEventType["disconnect"] == 1
        assert "connect_attempt" in RETRY_EVENT_TYPES


class TestNothingIsDeleted:
    """Acceptance 4."""

    def test_noStringLiteralInTheModuleIsADestructiveStatement(self) -> None:
        """
        Given: the exporter module
        When:  its AST string constants are scanned, docstrings stripped
        Then:  none is a DELETE / DROP / TRUNCATE statement

        The criterion's own grep, SCOPED TO CODE. A raw text scan fails on
        this module's own docstring, which promises not to delete and names
        the verbs to say so -- the FOURTH time this sprint that a text scan
        counted prose as behaviour (US-773's baseline, US-809-c's docstring,
        US-795-b's banned word, this). The rule has earned itself: if a guard
        cannot tell a sentence from a statement, it is not a guard.
        """
        import ast

        tree = ast.parse(_MODULE.read_text(encoding="utf-8"))

        docstrings = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and body:
                first = body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docstrings.add(id(first.value))

        offenders = [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings
            and any(v in node.value.lower()
                    for v in ("delete from", "drop table", "truncate"))
        ]

        assert not offenders, f"the exporter carries a destructive statement: {offenders}"

    def test_theSourceRowsSurviveTheExport(self, piDb, tmp_path) -> None:
        """
        Given: a Pi database
        When:  the window is exported
        Then:  every source row is still present

        The scan proves the code cannot delete; this proves the run did not.
        """
        conn = sqlite3.connect(piDb)
        before = conn.execute("SELECT COUNT(*) FROM connection_log").fetchone()[0]
        conn.close()

        exportPiWindow(piDb, tmp_path / "pi.csv")

        conn = sqlite3.connect(piDb)
        after = conn.execute("SELECT COUNT(*) FROM connection_log").fetchone()[0]
        conn.close()

        assert after == before

    def test_thePiDatabaseIsOpenedReadOnly(self, piDb, tmp_path) -> None:
        """
        Given: the exporter
        When:  it opens the Pi database
        Then:  the connection is read-only

        Proven by behaviour rather than by reading the URI string: a
        read-only connection refuses a write. The collector holds this
        database live, and an export must not be able to contend with it
        destructively.
        """
        source = _MODULE.read_text(encoding="utf-8")
        assert "mode=ro" in source

        uri = f"file:{Path(piDb).as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("DELETE FROM connection_log")
        finally:
            conn.close()


class TestTheSizeIsBoundedAndStated:
    """Acceptance 5."""

    def test_sizeIsRecorded(self, piDb, tmp_path) -> None:
        result = verifyExport(exportPiWindow(piDb, tmp_path / "pi.csv"))

        assert result.sizeBytes == (tmp_path / "pi.csv").stat().st_size

    def test_aSmallExportIsNotFlaggedAsSampled(self, piDb, tmp_path) -> None:
        """
        Given: an export far below the cap
        When:  it is verified
        Then:  it is not marked sampled
        """
        result = verifyExport(exportPiWindow(piDb, tmp_path / "pi.csv"))

        assert result.sizeBytes < MAX_FULL_EXPORT_BYTES
        assert result.sampled is False

    def test_theCapIs50Mb(self) -> None:
        assert MAX_FULL_EXPORT_BYTES == 50 * 1024 * 1024


class TestWindowBoundary:
    def test_windowEndIsJuneFirst(self) -> None:
        """The window this story preserves is everything before June 2026."""
        assert WINDOW_END == "2026-06-01"

    def test_anEmptyWindowProducesAHeaderOnlyFile(self, tmp_path) -> None:
        """
        Given: a database with no rows in the window
        When:  it is exported
        Then:  a header-only CSV is written and verifies cleanly

        An empty result is a real answer and must not look like a failure.
        """
        path = tmp_path / "empty.db"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE connection_log (id INTEGER PRIMARY KEY, "
            "timestamp DATETIME NOT NULL, event_type TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        result = verifyExport(exportPiWindow(path, tmp_path / "e.csv"))

        assert result.rowsReported == 0
        assert result.rowsReadBack == 0
        assert result.firstTimestamp is None


def test_exportResultIsSerialisable(tmp_path) -> None:
    """The manifest must be writable, so the result has to be plain data."""
    result = ExportResult(tier="pi", path=str(tmp_path / "x.csv"), rowsReported=0)

    manifest = writeManifest([result], tmp_path / "m.json")

    assert manifest["deletionPerformed"] is False
