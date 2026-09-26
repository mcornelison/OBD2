################################################################################
# File Name: test_custody_own_trajectory.py
# Purpose/Description: US-790 -- the rows this shutdown's own drain VCELL series
#                      writes are an OWN-ROWS SET (Atlas 2026-09-19, decision 2).
#                      Custody excludes exactly those ids and reports them beside
#                      the verdict under their own prefix (count, min, max);
#                      the drain's exit check excludes the same set, so rows
#                      landing every second can never keep the drain chasing
#                      backlog == 0.  A row that never landed is never excluded.
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
"""Custody and the drain treat this shutdown's own trajectory rows as own rows."""
from __future__ import annotations

import ast
import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.pi.data import sync_log
from src.pi.obdii.database import ObdDatabase
from src.pi.power.power_db import DrainVcellTrajectoryWriter
from src.pi.power.power_watch import __main__ as m
from src.pi.power.power_watch.sync_custody import (
    CUSTODY_RECORD_SCHEMA_VERSION,
    OWN_DRAIN_CLOSE_PREFIX,
    OWN_TRAJECTORY_PREFIX,
    OWN_TRAJECTORY_REASON,
    OWN_TRAJECTORY_TABLE,
    OwnTrajectoryRows,
    makeSyncCustodyHook,
)
from src.pi.power.types import DRAIN_TERMINATION_SHUTDOWN, DRAIN_VCELL_TRAJECTORY_TABLE
from src.pi.sync.backlog import BACKLOG_DELIVERED, BACKLOG_OUTSTANDING, countOutstandingRows

_TABLE = DRAIN_VCELL_TRAJECTORY_TABLE


def _makeDb(tmp_path: Path) -> str:
    """A real Pi database with every delta cursor past its seeded rows."""
    db = ObdDatabase(str(tmp_path / "custody.db"), walMode=False)
    db.initialize()
    conn = sqlite3.connect(db.dbPath)
    try:
        sync_log.initDb(conn)
        sync_log.ensureSyncModifiedAtSchema(conn)
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        for table in sync_log.DELTA_SYNC_TABLES:
            if table not in existing:
                continue
            pk = sync_log.PK_COLUMN[table]
            maxPk = conn.execute(f"SELECT MAX({pk}) FROM {table}").fetchone()[0]
            if maxPk is not None:
                sync_log.updateHighWaterMark(
                    conn, table, int(maxPk), "seed", "ok",
                    lastModifiedAt="9999-12-31T23:59:59Z",
                )
        conn.commit()
    finally:
        conn.close()
    return db.dbPath


def _writer(dbPath: str, own: OwnTrajectoryRows | None) -> DrainVcellTrajectoryWriter:
    return DrainVcellTrajectoryWriter(
        dbPath=dbPath,
        cellEpoch="2000mah-pouch",
        onRowWritten=own.add if own is not None else None,
    )


def _markPushed(dbPath: str) -> None:
    """What a successful push does: the id cursor moves past every row."""
    conn = sqlite3.connect(dbPath)
    try:
        maxId = conn.execute(f"SELECT MAX(id) FROM {_TABLE}").fetchone()[0]
        if maxId is not None:
            sync_log.updateHighWaterMark(conn, _TABLE, int(maxId), "push", "ok")
        conn.commit()
    finally:
        conn.close()


def _reader(dbPath: str):
    def _read(excludeRows=()):
        return countOutstandingRows(dbPath, excludeRows=excludeRows)

    return _read


def _custody(dbPath: str, recordPath: Path, own: OwnTrajectoryRows | None):
    return makeSyncCustodyHook(
        recordPath=str(recordPath), backlogReader=_reader(dbPath), ownTrajectoryRows=own,
    )


def _record(recordPath: Path) -> dict[str, Any]:
    return json.loads(recordPath.read_text(encoding="utf-8"))


class TestCustodyExcludesAndReportsTheSet:
    def test_onlyOwnRowsOutstanding_readsDelivered_andReportsCountMinMax(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        dbPath = _makeDb(tmp_path)
        own = OwnTrajectoryRows()
        writer = _writer(dbPath, own)
        for vcell in (3.95, 3.90):
            writer.record(vcell)
        writer.record(3.85, terminationReason=DRAIN_TERMINATION_SHUTDOWN)
        ids = sorted(e.pk for e in own.exclusions())
        recordPath = tmp_path / "custody.json"

        with caplog.at_level(logging.WARNING):
            _custody(dbPath, recordPath, own)()

        record = _record(recordPath)
        assert record["verdict"] == BACKLOG_DELIVERED
        assert record["ownTrajectoryExcluded"] == {
            "table": OWN_TRAJECTORY_TABLE,
            "reason": OWN_TRAJECTORY_REASON,
            "requestedRows": 3,
            "minId": ids[0],
            "maxId": ids[-1],
            "outstandingRows": 3,
        }
        beside = [r.getMessage() for r in caplog.records
                  if OWN_TRAJECTORY_PREFIX in r.getMessage()]
        assert len(beside) == 1
        assert f"min id={ids[0]}" in beside[0] and f"max id={ids[-1]}" in beside[0]
        assert not any(OWN_DRAIN_CLOSE_PREFIX in r.getMessage() for r in caplog.records)

    def test_withoutTheSet_theSameShutdownReadsOutstanding(self, tmp_path: Path) -> None:
        dbPath = _makeDb(tmp_path)
        writer = _writer(dbPath, OwnTrajectoryRows())
        writer.record(3.95)
        writer.record(3.85, terminationReason=DRAIN_TERMINATION_SHUTDOWN)
        recordPath = tmp_path / "custody.json"

        _custody(dbPath, recordPath, None)()

        record = _record(recordPath)
        assert record["verdict"] == BACKLOG_OUTSTANDING
        assert record["perTable"][_TABLE] == 2
        assert record["ownTrajectoryExcluded"] is None

    def test_aRowFromAnEarlierDrain_stillCounts(self, tmp_path: Path) -> None:
        dbPath = _makeDb(tmp_path)
        _writer(dbPath, None).record(3.70, terminationReason=DRAIN_TERMINATION_SHUTDOWN)
        own = OwnTrajectoryRows()
        _writer(dbPath, own).record(3.95)
        recordPath = tmp_path / "custody.json"

        _custody(dbPath, recordPath, own)()

        record = _record(recordPath)
        assert record["verdict"] == BACKLOG_OUTSTANDING
        assert record["perTable"][_TABLE] == 1
        assert record["ownTrajectoryExcluded"]["outstandingRows"] == 1

    def test_rowsAlreadyPushed_areReportedButMoveNothing(self, tmp_path: Path) -> None:
        dbPath = _makeDb(tmp_path)
        own = OwnTrajectoryRows()
        writer = _writer(dbPath, own)
        writer.record(3.95)
        writer.record(3.90)
        _markPushed(dbPath)
        recordPath = tmp_path / "custody.json"

        _custody(dbPath, recordPath, own)()

        field = _record(recordPath)["ownTrajectoryExcluded"]
        assert field["requestedRows"] == 2
        assert field["outstandingRows"] == 0

    def test_aWriterThatWroteNothing_excludesNothing(self, tmp_path: Path) -> None:
        dbPath = tmp_path / "no_table.db"
        sqlite3.connect(str(dbPath)).close()
        own = OwnTrajectoryRows()

        _writer(str(dbPath), own).record(3.95)

        assert own.exclusions() == ()

    def test_recordSchemaIsVersion2(self) -> None:
        """ownTrajectoryExcluded is a new field: a v1 consumer must not accept it."""
        assert CUSTODY_RECORD_SCHEMA_VERSION == 2


@dataclass
class _Summary:
    rowsPushed: int = 0
    tablesFailed: int = 0
    disabled: bool = False


class _PushWhileThePollWrites:
    """forcePush that delivers everything, while the 1 s poll lands one more row."""

    def __init__(self, dbPath: str, writer: DrainVcellTrajectoryWriter, maxPasses: int) -> None:
        self._dbPath = dbPath
        self._writer = writer
        self._maxPasses = maxPasses
        self.passes = 0

    def forcePush(self, *, excludeTables=()) -> _Summary:
        self.passes += 1
        _markPushed(self._dbPath)
        if self.passes < self._maxPasses:
            self._writer.record(3.90)  # a poll row lands after this pass pushed
        return _Summary(rowsPushed=1)


class TestTheDrainDoesNotChaseItsOwnRows:
    def _runDrain(self, dbPath: str, *, excludeOwn: bool) -> int:
        own = OwnTrajectoryRows()
        writer = _writer(dbPath, own)
        writer.record(4.00)
        client = _PushWhileThePollWrites(dbPath, writer, maxPasses=6)

        def _drainBacklog():
            rows = own.exclusions() if excludeOwn else ()
            return countOutstandingRows(dbPath, excludeRows=rows)

        m._buildRunSync(client, backlogReader=_drainBacklog)()  # noqa: SLF001
        return client.passes

    def test_withTheSet_oneRowPerPollNeverKeepsTheDrainAlive(self, tmp_path: Path) -> None:
        assert self._runDrain(_makeDb(tmp_path), excludeOwn=True) == 1

    def test_withoutTheSet_theDrainChasesUntilTheRowsStop(self, tmp_path: Path) -> None:
        assert self._runDrain(_makeDb(tmp_path), excludeOwn=False) == 6


class TestProductionWiring:
    def _mainCalls(self) -> dict[str, list[ast.Call]]:
        tree = ast.parse(Path(m.__file__).read_text(encoding="utf-8"))
        main = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        calls: dict[str, list[ast.Call]] = {}
        for node in ast.walk(main):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                calls.setdefault(node.func.id, []).append(node)
        return calls

    def _kw(self, call: ast.Call, name: str) -> ast.expr:
        return next(kw.value for kw in call.keywords if kw.arg == name)

    def test_theSequencerFeedsTheWriter(self) -> None:
        (sequencer,) = self._mainCalls()["ShutdownSequencer"]
        value = self._kw(sequencer, "drainSampleFn")
        assert ast.unparse(value).endswith(".record")

    def test_theWriterReportsIntoTheSetCustodyReads(self) -> None:
        calls = self._mainCalls()
        (writer,) = calls["DrainVcellTrajectoryWriter"]
        assert ast.unparse(self._kw(writer, "onRowWritten")) == "ownTrajectoryRows.add"
        assert ast.unparse(self._kw(writer, "cellEpoch")) == "cellEpoch"
        (custody,) = calls["makeSyncCustodyHook"]
        assert ast.unparse(self._kw(custody, "ownTrajectoryRows")) == "ownTrajectoryRows"

    def test_theDrainsExitCheckExcludesTheSameSet(self) -> None:
        source = Path(m.__file__).read_text(encoding="utf-8")
        assert "excludeRows=ownTrajectoryRows.exclusions()" in source
