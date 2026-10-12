################################################################################
# File Name: test_drain_vcell_trajectory.py
# Purpose/Description: US-790 -- the drain_vcell_trajectory table and its
#                      writer: a replay-safe schema step (run twice against a
#                      POPULATED database, asserted on executed statements),
#                      one row per drain poll with NULL for a failed read, one
#                      typed termination row per drain, a cell_epoch on every
#                      row, and sync membership that keeps it IN the drain.
# Author: Rex (US-790)
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-25    | Rex (US-790) | Initial.
# ================================================================================
################################################################################
"""drain_vcell_trajectory: schema step, writer and sync membership (US-790)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.common.edr.sync_contract import SHUTDOWN_DRAIN_EXCLUDED_TABLES
from src.pi.data import sync_log
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.database_schema import (
    DRAIN_VCELL_TRAJECTORY_TABLE,
    SCHEMA_DRAIN_VCELL_TRAJECTORY,
    ensureDrainVcellTrajectoryTable,
)
from src.pi.power import drain_event_writer
from src.pi.power.power_db import DrainVcellTrajectoryWriter
from src.pi.power.types import (
    DRAIN_TERMINATION_DRAIN_FLOOR,
    DRAIN_TERMINATION_POWER_RESTORED,
    DRAIN_TERMINATION_SHUTDOWN,
    DRAIN_TERMINATION_VALUES,
)

_TABLE = DRAIN_VCELL_TRAJECTORY_TABLE


def _populatedDb(path: Path) -> Path:
    """A database that already holds the table AND rows in it."""
    db = ObdDatabase(str(path), walMode=False)
    db.initialize()
    conn = sqlite3.connect(str(path))
    conn.executemany(
        f"INSERT INTO {_TABLE} (ts_utc, ts_capture, seq, vcell_v, "
        "termination_reason, cell_epoch) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("2026-09-25T18:00:00Z", 10.0, 0, 3.95, None, "2000mah-pouch"),
            ("2026-09-25T18:00:01Z", 11.0, 1, None, None, "2000mah-pouch"),
            ("2026-09-25T18:00:02Z", 12.0, 2, 3.60, "drain_floor", "2000mah-pouch"),
        ],
    )
    conn.commit()
    conn.close()
    return path


def _traced(path: Path) -> tuple[sqlite3.Connection, list[str]]:
    conn = sqlite3.connect(str(path))
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    return conn, statements


def _rows(path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(
            f"SELECT seq, vcell_v, termination_reason, cell_epoch FROM {_TABLE} "
            "ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


# ================================================================================
# Schema step -- specs/design-patterns.md section 10
# ================================================================================


class TestSchemaStep:
    def test_freshDatabase_createsTheTable_withTheAcceptanceColumns(self, tmp_path: Path) -> None:
        conn = sqlite3.connect(str(tmp_path / "fresh.db"))

        created = ensureDrainVcellTrajectoryTable(conn)

        assert created is True
        columns = {row[1]: row for row in conn.execute(f"PRAGMA table_info({_TABLE})")}
        assert {
            "id", "ts_utc", "ts_capture", "seq", "vcell_v",
            "termination_reason", "cell_epoch",
        } <= set(columns)
        assert columns["id"][5] == 1  # the PK is literally named id
        assert columns["vcell_v"][3] == 0  # nullable: NULL is a failed read
        assert columns["cell_epoch"][3] == 1  # NOT NULL: every row carries one
        assert "drive_id" not in columns
        assert "data_source" not in columns

    def test_runTwiceOnAPopulatedDatabase_secondRunIssuesNoCreateDropOrRename(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: a database that already holds drain_vcell_trajectory WITH rows
        When:  the schema step runs twice more, traced
        Then:  neither run issues CREATE, DROP or RENAME, and no row moves
        """
        path = _populatedDb(tmp_path / "car.db")
        before = _rows(path)

        for _ in range(2):
            conn, statements = _traced(path)
            assert ensureDrainVcellTrajectoryTable(conn) is False
            conn.close()
            ddl = [s for s in statements if any(
                word in s.upper() for word in ("CREATE", "DROP", "RENAME", "ALTER")
            )]
            assert ddl == []

        assert _rows(path) == before

    def test_theStepIsAnExplicitCreate_neverIfNotExists(self) -> None:
        """A bare IF NOT EXISTS would be relied on to decide; the probe decides."""
        assert "IF NOT EXISTS" not in SCHEMA_DRAIN_VCELL_TRAJECTORY.upper()

    def test_aQuotedStoredName_isStillRecognisedAsPresent(self, tmp_path: Path) -> None:
        """A table rebuilt once carries CREATE TABLE "name" in sqlite_master."""
        conn = sqlite3.connect(str(tmp_path / "quoted.db"))
        conn.execute(SCHEMA_DRAIN_VCELL_TRAJECTORY.replace(_TABLE, "tmp_x", 1))
        conn.execute(f'ALTER TABLE tmp_x RENAME TO "{_TABLE}"')
        assert '"' in conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?", (_TABLE,)
        ).fetchone()[0]

        assert ensureDrainVcellTrajectoryTable(conn) is False

    def test_initializeCreatesIt_andReInitializeIsANoOp(self, tmp_path: Path) -> None:
        path = _populatedDb(tmp_path / "init.db")
        before = _rows(path)

        ObdDatabase(str(path), walMode=False).initialize()

        assert _rows(path) == before

    def test_terminationReason_isTyped(self, tmp_path: Path) -> None:
        conn = sqlite3.connect(str(tmp_path / "typed.db"))
        ensureDrainVcellTrajectoryTable(conn)

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                f"INSERT INTO {_TABLE} (ts_utc, ts_capture, seq, vcell_v, "
                "termination_reason, cell_epoch) VALUES ('t', 1, 0, 3.9, 'died', 'unknown')"
            )


# ================================================================================
# Vocabulary
# ================================================================================


class TestTerminationVocabulary:
    def test_reusesTheDrainCloseSpellings(self) -> None:
        assert DRAIN_TERMINATION_SHUTDOWN == drain_event_writer.CLOSE_REASON_SHUTDOWN
        assert DRAIN_TERMINATION_POWER_RESTORED == (
            drain_event_writer.CLOSE_REASON_POWER_RESTORED
        )

    def test_everyValueFitsTheServerColumn(self) -> None:
        assert len(set(DRAIN_TERMINATION_VALUES)) == len(DRAIN_TERMINATION_VALUES)
        assert all(len(value) <= 32 for value in DRAIN_TERMINATION_VALUES)


# ================================================================================
# Sync membership
# ================================================================================


class TestSyncMembership:
    def test_isADeltaSyncTable_keyedOnId(self) -> None:
        assert sync_log.PK_COLUMN[_TABLE] == "id"
        assert _TABLE in sync_log.DELTA_SYNC_TABLES

    def test_isNotAnUpdateTable(self) -> None:
        """An UPDATE path would re-stamp delivered rows -- US-789 one layer up."""
        assert _TABLE not in sync_log.SYNC_UPDATE_TABLES_PK

    def test_isCarriedByTheShutdownDrain(self) -> None:
        """A dataset generated BY the drain must survive it."""
        assert _TABLE not in SHUTDOWN_DRAIN_EXCLUDED_TABLES


# ================================================================================
# Writer
# ================================================================================


def _writer(path: Path, *, epoch: str = "2000mah-pouch", written: list[int] | None = None,
            clock: list[float] | None = None) -> DrainVcellTrajectoryWriter:
    ticks = clock if clock is not None else [100.0]

    def _mono() -> float:
        ticks[0] += 1.0
        return ticks[0]

    return DrainVcellTrajectoryWriter(
        dbPath=str(path),
        cellEpoch=epoch,
        onRowWritten=(written.append if written is not None else None),
        monotonicFn=_mono,
        nowIsoFn=lambda: "2026-09-25T18:50:00Z",
    )


class TestWriter:
    def test_onePerPoll_thenOneTerminalRow_seqRestartsForTheNextDrain(
        self, tmp_path: Path,
    ) -> None:
        path = _populatedDb(tmp_path / "w.db")
        sqlite3.connect(str(path)).execute(f"DELETE FROM {_TABLE}").connection.commit()
        writer = _writer(path)

        writer.record(3.95)
        writer.record(None)
        writer.record(3.60, terminationReason=DRAIN_TERMINATION_DRAIN_FLOOR)
        writer.record(4.10, terminationReason=DRAIN_TERMINATION_POWER_RESTORED)

        assert _rows(path) == [
            (0, 3.95, None, "2000mah-pouch"),
            (1, None, None, "2000mah-pouch"),
            (2, 3.60, "drain_floor", "2000mah-pouch"),
            (0, 4.10, "power_restored", "2000mah-pouch"),
        ]

    def test_eventTimeAndMonotonicCapture_areStampedPerRow(self, tmp_path: Path) -> None:
        path = _populatedDb(tmp_path / "t.db")
        writer = _writer(path, clock=[500.0])

        writer.record(3.90)

        conn = sqlite3.connect(str(path))
        tsUtc, tsCapture = conn.execute(
            f"SELECT ts_utc, ts_capture FROM {_TABLE} ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert tsUtc == "2026-09-25T18:50:00Z"
        assert tsCapture == 501.0

    def test_cellEpoch_isStampedFromTheConfiguredValue(self, tmp_path: Path) -> None:
        path = _populatedDb(tmp_path / "e.db")

        _writer(path, epoch="unknown").record(3.9)

        assert _rows(path)[-1][3] == "unknown"

    def test_reportsOnlyIdsThatLanded(self, tmp_path: Path) -> None:
        path = _populatedDb(tmp_path / "ids.db")
        written: list[int] = []
        writer = _writer(path, written=written)

        writer.record(3.9)
        writer.record(3.8, terminationReason=DRAIN_TERMINATION_SHUTDOWN)

        conn = sqlite3.connect(str(path))
        assert written == [row[0] for row in conn.execute(
            f"SELECT id FROM {_TABLE} WHERE seq IN (0, 1) AND ts_capture > 100 ORDER BY id"
        )]

    def test_aRowThatFailsToLand_isNotReported_andNeverRaises(self, tmp_path: Path) -> None:
        path = tmp_path / "no_table.db"
        sqlite3.connect(str(path)).close()
        written: list[int] = []

        _writer(path, written=written).record(3.9)

        assert written == []

    def test_aMissingDatabase_isNeverCreated(self, tmp_path: Path) -> None:
        path = tmp_path / "absent.db"

        _writer(path).record(3.9)

        assert not path.exists()

    def test_aBadTerminationReason_isRefusedBeforeTheWrite(self, tmp_path: Path) -> None:
        path = _populatedDb(tmp_path / "bad.db")
        before = _rows(path)

        _writer(path).record(3.9, terminationReason="died")

        assert _rows(path) == before
