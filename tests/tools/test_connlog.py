################################################################################
# File Name: test_connlog.py
# Purpose/Description: US-808-d -- pin the rewritten connection_log export and
#                      gap-analysis tools to their own preserved output
#                      (data/us808-connection-log-export/, a GOLDEN FIXTURE).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-24    | Rex (US-808-d) | Initial -- golden reconciliation, per-type
#               |                | differences, read-only and read-back proofs.
# ================================================================================
################################################################################
"""Tests for tools/connlog (US-808-d).

The fixture directory is READ-ONLY input: it is the only surviving artefact of
US-808-a. Every test that writes does so under ``tmp_path``, and one test
hashes the fixture before and after running both tools.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tools.connlog import export_window as ew
from tools.connlog import gap_analysis as ga

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "data" / "us808-connection-log-export"
CONNLOG_DIR = REPO_ROOT / "tools" / "connlog"
WINDOW_END = "2026-06-01"
PI_CSV = FIXTURE / "pi_connection_log_before_2026-06-01.csv"
SERVER_CSV = FIXTURE / "server_connection_log_before_2026-06-01.csv"

#: The preserved README's per-event-type differences. Changing any of these is
#: the golden fixture failing, not a number to update.
GOLDEN_DIFFERENCES = {
    "connect_attempt": 21_891,
    "connect_failure": 3_638,
    "disconnect": 2_789,
    "connect_success": 0,
    "drive_start": 0,
    "drive_end": 0,
    "reconnect": 0,
}

_INTEGER_COLUMNS = {"id", "source_id", "sync_batch_id", "success", "retry_count", "drive_id"}


def _preservedManifest() -> dict:
    with open(FIXTURE / ew.MANIFEST_NAME, encoding="utf-8") as fh:
        return json.load(fh)


def _preservedEntry(tier: str) -> dict:
    return next(e for e in _preservedManifest()["exports"] if e["tier"] == tier)


def _dbFromCsv(csvPath: Path, dbPath: Path, nullToken: str | None) -> Path:
    """A SQLite copy of a preserved export, so the export tool can re-read it.

    ``nullToken`` cells are stored as SQL NULL; everything else verbatim.
    """
    with open(csvPath, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = [[None if c == nullToken else c for c in r] for r in reader]
    decl = ", ".join(
        f"{c} {'INTEGER' if c in _INTEGER_COLUMNS else 'TEXT'}" for c in header
    )
    conn = sqlite3.connect(dbPath)
    conn.execute(f"CREATE TABLE {ew.TABLE} ({decl})")
    conn.executemany(
        f"INSERT INTO {ew.TABLE} VALUES ({', '.join('?' * len(header))})", rows
    )
    conn.commit()
    conn.close()
    return dbPath


@pytest.fixture(scope="module")
def piDb(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _dbFromCsv(PI_CSV, tmp_path_factory.mktemp("pi") / "obd.db", ew.PI_NULL)


@pytest.fixture(scope="module")
def serverDb(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # The server renders NULL as the literal text NULL; keep it as text so the
    # export writes it back the way prod_db_query.sh prints it.
    return _dbFromCsv(SERVER_CSV, tmp_path_factory.mktemp("srv") / "obd2db.db", None)


def _serverSourceOver(db: Path) -> ew.TierSource:
    """The server tier backed by a SQLite copy (information_schema is MariaDB-only)."""
    return ew.TierSource("server", ew.sqliteReadOnlyRunner(db), ew.PI_COLUMNS_SQL)


# ---------------------------------------------------------------------------
# Golden fixture: the analysis reproduces the preserved evidence
# ---------------------------------------------------------------------------


class TestGoldenReconciliation:
    def test_reconciliation_reproduces28318(self) -> None:
        """
        Given: the preserved US-808-a export
        When: the gap analysis runs against it
        Then: 44,704 - 16,306 - 80 = 28,318, with every cross-check holding
        """
        a = ga.analyse(FIXTURE)

        assert a.pi.rows == 44_704
        assert a.serverRetryRows == 16_306
        assert a.explicitKeepsTotal == 80
        assert a.explicitKeeps == {
            "connect_success": 34, "drive_end": 16, "drive_start": 25, "reconnect": 5
        }
        assert a.gap == 28_318
        assert a.problems == []

    def test_perEventTypeDifferences_matchThePreservedValues(self) -> None:
        a = ga.analyse(FIXTURE)

        assert a.differences == GOLDEN_DIFFERENCES

    def test_missingIds_matchUS808bFindings(self) -> None:
        """US-808-b-findings.txt: 10 contiguous runs, largest 20277, 0 server orphans."""
        a = ga.analyse(FIXTURE)

        assert len(a.missingRuns) == 10
        assert a.largestRun == 20_277
        assert a.missingIds == 28_318
        assert a.serverOrphans == 0

    def test_mainPrintsEveryReadmeFigure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """
        Given: the preserved export
        When: the CLI runs
        Then: it exits 0 and prints every figure the README records
        """
        assert ga.main([str(FIXTURE)]) == 0
        out = capsys.readouterr().out

        for figure in ("44,704", "16,306", "80", "28,318", "16,386"):
            assert figure in out
        for t, diff in GOLDEN_DIFFERENCES.items():
            assert re.search(rf"{t}\s+[\d,]+\s+[\d,]+\s+{diff:,}\b", out), t
        assert out.count("no drift") == 3
        assert "10 contiguous run(s); largest 20,277" in out

    def test_aManifestThatNoLongerDescribesItsFiles_fails(self, tmp_path: Path) -> None:
        """
        Given: a copy of the export whose manifest overstates one count
        When: the analysis runs
        Then: it reports the disagreement instead of believing the manifest
        """
        for f in (PI_CSV, SERVER_CSV):
            (tmp_path / f.name).write_bytes(f.read_bytes())
        manifest = _preservedManifest()
        manifest["exports"][0]["perEventType"]["connect_attempt"] += 1
        (tmp_path / ew.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

        a = ga.analyse(tmp_path)

        assert a.problems == ["pi: manifest perEventType differs from the CSV"]
        assert ga.main([str(tmp_path)]) == 1

    def test_contiguousRuns_collapsesConsecutiveIds(self) -> None:
        assert ga.contiguousRuns([7, 3, 4, 5, 9, 10]) == [(3, 5), (7, 7), (9, 10)]
        assert ga.contiguousRuns([]) == []


# ---------------------------------------------------------------------------
# Export: manifest shape, read-back, read-only
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_reproducesThePreservedManifestFields(
        self, piDb: Path, serverDb: Path, tmp_path: Path
    ) -> None:
        """
        Given: SQLite copies of both preserved tiers
        When: the export runs into a new directory
        Then: the manifest carries every field the preserved one does, with the
              same counts, columns and last timestamp, and deletionPerformed false
        """
        out = tmp_path / "export"
        manifest, problems = ew.exportWindow(
            [ew.piSource(ew.sqliteReadOnlyRunner(piDb)), _serverSourceOver(serverDb)],
            out, WINDOW_END,
        )

        assert problems == []
        assert manifest["deletionPerformed"] is False
        assert manifest["liveCountsAtExport"] == {"pi": 44_704, "server": 16_386}
        assert manifest["retryEventTypes"] == _preservedManifest()["retryEventTypes"]
        for entry in manifest["exports"]:
            preserved = _preservedEntry(entry["tier"])
            assert set(preserved) <= set(entry)
            for key in ("columns", "perEventType", "rowsReported", "rowsReadBack",
                        "lastTimestamp", "sampled"):
                assert entry[key] == preserved[key], (entry["tier"], key)
        onDisk = json.loads((out / ew.MANIFEST_NAME).read_text(encoding="utf-8"))
        assert onDisk["deletionPerformed"] is False

    def test_exportedCsvs_analyseToTheSameGap(
        self, piDb: Path, serverDb: Path, tmp_path: Path
    ) -> None:
        """The two tools compose: export, then analyse, reproduces 28,318."""
        out = tmp_path / "export"
        ew.exportWindow(
            [ew.piSource(ew.sqliteReadOnlyRunner(piDb)), _serverSourceOver(serverDb)],
            out, WINDOW_END,
        )

        a = ga.analyse(out)

        assert a.gap == 28_318
        assert a.differences == GOLDEN_DIFFERENCES
        assert a.problems == []

    def test_firstTimestamp_isTheEarliestInstant_notTheSmallestString(
        self, piDb: Path, tmp_path: Path
    ) -> None:
        """
        Given: the Pi export, which mixes `2026-04-23 03:14:40` and
               `2026-04-23T03:12:39Z` renderings
        When: the export computes its span
        Then: firstTimestamp is 03:12:39. The preserved manifest's 03:14:40 is a
              raw string minimum -- every space-form value sorts ahead of every
              T-form one -- so the Pi's earliest row is NOT later than the server's.
        """
        entry, _ = ew.exportTier(ew.piSource(ew.sqliteReadOnlyRunner(piDb)), tmp_path, WINDOW_END)

        assert entry["firstTimestamp"] == "2026-04-23 03:12:39"
        assert _preservedEntry("pi")["firstTimestamp"] == "2026-04-23 03:14:40"

    def test_exportedPiRows_equalThePreservedRows(self, piDb: Path, tmp_path: Path) -> None:
        ew.exportTier(ew.piSource(ew.sqliteReadOnlyRunner(piDb)), tmp_path, WINDOW_END)

        assert ew.readBack(tmp_path / PI_CSV.name) == ew.readBack(PI_CSV)

    def test_truncatedExport_isReportedNotSilent(self, piDb: Path, tmp_path: Path) -> None:
        """
        Given: a source whose fetch returns one row fewer than its own count
        When: the export runs
        Then: rowsReported and rowsReadBack differ and a problem names both
        """
        real = ew.sqliteReadOnlyRunner(piDb)

        def truncating(sql: str) -> list[list[str]]:
            rows = real(sql)
            return rows[:-1] if "ORDER BY" in sql and "pragma" not in sql else rows

        entry, problems = ew.exportTier(ew.piSource(truncating), tmp_path, WINDOW_END)

        assert (entry["rowsReported"], entry["rowsReadBack"]) == (44_704, 44_703)
        assert problems == ["pi: source reported 44704 rows, file re-reads 44703"]

    def test_existingExport_isNeverOverwritten(self, piDb: Path, tmp_path: Path) -> None:
        existing = tmp_path / PI_CSV.name
        existing.write_text("evidence", encoding="utf-8")

        with pytest.raises(ew.ExportError, match="never overwrites"):
            ew.exportTier(ew.piSource(ew.sqliteReadOnlyRunner(piDb)), tmp_path, WINDOW_END)
        assert existing.read_text(encoding="utf-8") == "evidence"

    def test_windowEnd_excludesRowsOnOrAfterIt(self, tmp_path: Path) -> None:
        db = tmp_path / "w.db"
        conn = sqlite3.connect(db)
        conn.execute(f"CREATE TABLE {ew.TABLE} (id INTEGER, timestamp TEXT, event_type TEXT)")
        conn.executemany(f"INSERT INTO {ew.TABLE} VALUES (?, ?, ?)", [
            (1, "2026-05-31T23:59:59Z", "disconnect"),
            (2, "2026-05-31 23:59:59", "disconnect"),
            (3, "2026-06-01T00:00:00Z", "disconnect"),
            (4, "2026-06-01 00:00:00", "disconnect"),
        ])
        conn.commit()
        conn.close()

        entry, problems = ew.exportTier(
            ew.piSource(ew.sqliteReadOnlyRunner(db)), tmp_path / "o", WINDOW_END
        )

        assert entry["rowsReadBack"] == 2
        assert problems == []


class TestReadOnly:
    def test_noRemovalStatementAnywhereInToolsConnlog(self) -> None:
        """No DELETE or DROP appears in any file of the package, prose included."""
        files = [p for p in CONNLOG_DIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        assert files, "tools/connlog/ is empty -- the scan checked nothing"

        hits = [
            f"{p.relative_to(REPO_ROOT)}:{n}"
            for p in files
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if re.search(r"\b(DELETE|DROP)\b", line, re.IGNORECASE)
        ]

        assert hits == []

    @pytest.mark.parametrize("sql", [
        "DELETE FROM connection_log",
        "DROP TABLE connection_log",
        "UPDATE connection_log SET success = 0",
        "SELECT 1; DELETE FROM connection_log",
        "  pragma writable_schema = 1",
    ])
    def test_requireSelect_refusesEverythingButOneSelect(self, sql: str) -> None:
        with pytest.raises(ew.ExportError, match="read-only"):
            ew.requireSelect(sql)

    def test_requireSelect_admitsASelect(self) -> None:
        assert ew.requireSelect("SELECT COUNT(*) FROM connection_log;")

    def test_sqliteRunner_opensReadOnly(self, piDb: Path) -> None:
        """The mode=ro URI is load-bearing: the connection itself refuses writes."""
        conn = sqlite3.connect(f"{piDb.resolve().as_uri()}?mode=ro", uri=True)
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn.execute(f"UPDATE {ew.TABLE} SET success = 0")
        finally:
            conn.close()

    def test_sshPiRunner_opensTheDatabaseModeRo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[list[str]] = []

        def fakeRun(cmd: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, '[{"n":3}]', "")

        monkeypatch.setattr(ew.subprocess, "run", fakeRun)

        rows = ew.sshPiRunner("pi-host", "/data/obd.db")("SELECT COUNT(*) AS n FROM connection_log")

        assert rows == [["3"]]
        assert "'file:/data/obd.db?mode=ro'" in seen[0][-1]

    def test_serverRunner_keepsNullAndSplitsTabs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            ew.subprocess, "run",
            lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 0, "1\tNULL\treal\n", "(1 rows)"),
        )

        assert ew.serverRunner(REPO_ROOT)("SELECT 1") == [["1", "NULL", "real"]]


def _digest(directory: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir()) if p.is_file()
    }


def test_fixture_isByteIdenticalAfterBothToolsRun(
    piDb: Path, serverDb: Path, tmp_path: Path
) -> None:
    """
    Given: the golden fixture
    When: the analysis reads it and an export runs elsewhere
    Then: every fixture file is byte-identical to before
    """
    before = _digest(FIXTURE)

    ga.analyse(FIXTURE)
    ew.exportWindow(
        [ew.piSource(ew.sqliteReadOnlyRunner(piDb)), _serverSourceOver(serverDb)],
        tmp_path / "export", WINDOW_END,
    )

    assert _digest(FIXTURE) == before
