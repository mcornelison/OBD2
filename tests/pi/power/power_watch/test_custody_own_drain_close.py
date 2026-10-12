################################################################################
# File Name: test_custody_own_drain_close.py
# Purpose/Description: US-789 -- the custody verdict excludes the ONE
#                      battery_health_log row this shutdown's own drain close
#                      just wrote (by drain_event_id), and reports it beside the
#                      verdict in ownDrainCloseExcluded. A row stranded by an
#                      EARLIER drain still counts; a failed close excludes
#                      nothing; the VCELL-floor fast path gets the same result.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-17    | Rex (US-789) | Initial -- own-drain-close custody exclusion.
# ================================================================================
################################################################################
"""US-789: custody stops counting the drain-close row the shutdown just wrote."""
from __future__ import annotations

import ast
import inspect
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.pi.data import sync_log
from src.pi.obdii.database import ObdDatabase
from src.pi.power.drain_event_writer import makeDrainEventWriterForPath
from src.pi.power.power_watch import __main__ as m
from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.power_watch.sync_custody import (
    OWN_DRAIN_CLOSE_PREFIX,
    OWN_DRAIN_CLOSE_TABLE,
    OwnDrainCloseSlot,
    makeSyncCustodyHook,
)
from src.pi.sync.backlog import (
    BACKLOG_DELIVERED,
    BACKLOG_OUTSTANDING,
    RowExclusion,
    countOutstandingRows,
)

_SETTLED_UPTIME_S = 9999.0


class FakeUps:
    """UpsMonitor-shaped double."""

    def __init__(self, *, vcell: float = 3.48, socPct: int = 7) -> None:
        self.vcell = vcell
        self.socPct = socPct

    def getVcell(self) -> float:
        return self.vcell

    def getBatteryPercentage(self) -> int:
        return self.socPct


def _makeDb(tmp_path: Path) -> str:
    """A real Pi database, fully synced -- nothing outstanding to start with.

    ``ObdDatabase.initialize`` seeds rows (e.g. ``pi_state``); every delta
    table's cursor is advanced past them so the only outstanding rows are the
    ones each test writes.
    """
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


def _writer(dbPath: str, *, vcell: float = 4.05):
    return makeDrainEventWriterForPath(
        dbPath=dbPath,
        upsResolver=lambda: FakeUps(vcell=vcell, socPct=50),
        uptimeReader=lambda: _SETTLED_UPTIME_S,
        busyTimeoutSec=5.0,
    )


def _openDrain(dbPath: str) -> int:
    """Open a production drain row, as the collector does at power loss."""
    return int(_writer(dbPath).openDrainEvent())


def _closeHook(dbPath: str, slot: OwnDrainCloseSlot):
    """The PRODUCTION close hook, built by __main__'s own factory."""
    hook = m.buildDrainCloseHook(
        config={
            "pi": {
                "database": {"path": dbPath},
                "powerWatch": {"perTaskTimeoutSec": 5.0},
                "hardware": {"upsMonitor": {"socColdStartWindowSeconds": 1.0}},
            },
        },
        upsResolver=lambda: FakeUps(vcell=3.47, socPct=5),
        uptimeReader=lambda: _SETTLED_UPTIME_S,
        ownDrainCloseSlot=slot,
    )
    assert hook is not None
    return hook


def _reader(dbPath: str):
    """The production reader shape: EDR excluded, excludeRows passed through."""

    def _read(excludeRows=()):
        return countOutstandingRows(dbPath, excludeRows=excludeRows)

    return _read


def _custodyHook(dbPath: str, slot: OwnDrainCloseSlot, recordPath: Path):
    return makeSyncCustodyHook(
        recordPath=str(recordPath),
        backlogReader=_reader(dbPath),
        ownDrainCloseSlot=slot,
    )


def _record(recordPath: Path) -> dict[str, Any]:
    return json.loads(recordPath.read_text(encoding="utf-8"))


# ================================================================================
# VC-1: only this shutdown's own close outstanding -> DELIVERED, row named beside
# ================================================================================


class TestOwnCloseIsExcludedAndReported:

    def test_ownCloseOnly_readsDelivered_andNamesTheRowBesideTheVerdict(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Given: a backlog empty apart from the drain row this shutdown closes
        When:  the composed pre-poweroff hooks run (close, then custody)
        Then:  custody reads DELIVERED, and ownDrainCloseExcluded names the row
        """
        # Arrange
        dbPath = _makeDb(tmp_path)
        drainId = _openDrain(dbPath)
        slot = OwnDrainCloseSlot()
        recordPath = tmp_path / "custody.json"
        hooks = m.composePrePowerOffHooks(
            _closeHook(dbPath, slot), _custodyHook(dbPath, slot, recordPath),
        )

        # Act
        with caplog.at_level(logging.WARNING):
            hooks()

        # Assert
        record = _record(recordPath)
        assert record["verdict"] == BACKLOG_DELIVERED
        assert record["outstandingRows"] == 0
        assert record["ownDrainCloseExcluded"] == {
            "table": OWN_DRAIN_CLOSE_TABLE,
            "drain_event_id": drainId,
            "reason": "written by this shutdown's own drain close",
            "wasOutstanding": True,
        }
        beside = [r.getMessage() for r in caplog.records
                  if OWN_DRAIN_CLOSE_PREFIX in r.getMessage()]
        assert len(beside) == 1
        assert f"drain_event_id={drainId}" in beside[0]

    def test_withoutTheExclusion_theSameShutdownWouldReadOutstanding(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: the same shutdown, but custody wired WITHOUT the slot
        When:  the hooks run
        Then:  it reads OUTSTANDING on battery_health_log -- the defect this
               story removes, proving the DELIVERED above is the exclusion's
               doing and not an empty fixture.
        """
        dbPath = _makeDb(tmp_path)
        _openDrain(dbPath)
        slot = OwnDrainCloseSlot()
        recordPath = tmp_path / "custody.json"
        hooks = m.composePrePowerOffHooks(
            _closeHook(dbPath, slot),
            makeSyncCustodyHook(
                recordPath=str(recordPath), backlogReader=_reader(dbPath),
            ),
        )

        hooks()

        record = _record(recordPath)
        assert record["verdict"] == BACKLOG_OUTSTANDING
        assert record["perTable"][OWN_DRAIN_CLOSE_TABLE] == 1
        assert record["ownDrainCloseExcluded"] is None


# ================================================================================
# VC-2: ONE primary key, never a table -- an earlier stranded row still counts
# ================================================================================


class TestAnEarlierStrandedRowStillCounts:

    def test_strandedRowFromAnEarlierDrain_readsOutstanding_andIsNamed(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: a battery_health_log row left unsynced by an EARLIER drain, and
               this shutdown's own drain row
        When:  the hooks run
        Then:  custody reads OUTSTANDING with battery_health_log=1 -- the
               earlier row -- and only this shutdown's row is excluded
        """
        # Arrange -- an earlier drain, opened and closed, never synced
        dbPath = _makeDb(tmp_path)
        earlierId = _openDrain(dbPath)
        assert _writer(dbPath).closeOpenDrainEvent(reason="power_restored")
        ownId = _openDrain(dbPath)
        assert ownId != earlierId
        slot = OwnDrainCloseSlot()
        recordPath = tmp_path / "custody.json"
        hooks = m.composePrePowerOffHooks(
            _closeHook(dbPath, slot), _custodyHook(dbPath, slot, recordPath),
        )

        # Act
        hooks()

        # Assert
        record = _record(recordPath)
        assert record["verdict"] == BACKLOG_OUTSTANDING
        assert record["perTable"][OWN_DRAIN_CLOSE_TABLE] == 1
        assert record["ownDrainCloseExcluded"]["drain_event_id"] == ownId
        # The stranded row is not the excluded one.
        backlog = countOutstandingRows(
            dbPath,
            excludeRows=(RowExclusion(OWN_DRAIN_CLOSE_TABLE, ownId, "own"),),
        )
        assert [e.pk for e in backlog.excludedRows] == [ownId]
        assert backlog.perTable[OWN_DRAIN_CLOSE_TABLE] == 1

    def test_excludingOneRow_neverExcludesTheTable(self, tmp_path: Path) -> None:
        """
        Given: three outstanding battery_health_log rows
        When:  one of them is excluded by primary key
        Then:  exactly two still count
        """
        dbPath = _makeDb(tmp_path)
        ids = []
        for _ in range(3):
            ids.append(_openDrain(dbPath))
            _writer(dbPath).closeOpenDrainEvent(reason="power_restored")

        backlog = countOutstandingRows(
            dbPath,
            excludeRows=(RowExclusion(OWN_DRAIN_CLOSE_TABLE, ids[1], "own"),),
        )

        assert backlog.perTable[OWN_DRAIN_CLOSE_TABLE] == 2
        assert backlog.verdict == BACKLOG_OUTSTANDING

    def test_excludingARowThatIsNotOutstanding_changesNothing(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: an exclusion for a primary key that is already delivered
        When:  the backlog is read
        Then:  the count is untouched and excludedRows does not claim it
        """
        dbPath = _makeDb(tmp_path)
        _openDrain(dbPath)
        _writer(dbPath).closeOpenDrainEvent(reason="power_restored")

        backlog = countOutstandingRows(
            dbPath,
            excludeRows=(RowExclusion(OWN_DRAIN_CLOSE_TABLE, 999, "own"),),
        )

        assert backlog.perTable[OWN_DRAIN_CLOSE_TABLE] == 1
        assert backlog.excludedRows == ()


# ================================================================================
# The close failed or wrote nothing -> custody counts normally
# ================================================================================


class _FakeWriter:
    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour

    def closeOpenDrainEvent(self, *, reason: str):
        if self.behaviour == "raise":
            raise RuntimeError("injected close fault")
        return None


class TestFailedCloseExcludesNothing:

    @pytest.mark.parametrize("behaviour", ["none", "raise"])
    def test_failedClose_custodyCountsEveryRow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, behaviour: str,
    ) -> None:
        """
        Given: an outstanding drain row, a slot holding a STALE id for it, and
               a close that fails (returns nothing, or raises)
        When:  the composed hooks run
        Then:  the close cleared the slot, so custody excludes nothing and
               reads OUTSTANDING -- it never excludes a row this close did not
               write, and it does not depend on the close succeeding
        """
        # Arrange
        dbPath = _makeDb(tmp_path)
        staleId = _openDrain(dbPath)
        slot = OwnDrainCloseSlot()
        slot.record(staleId)
        monkeypatch.setattr(
            m, "makeDrainEventWriterForPath",
            lambda **_kw: _FakeWriter(behaviour),
        )
        recordPath = tmp_path / "custody.json"
        hooks = m.composePrePowerOffHooks(
            _closeHook(dbPath, slot), _custodyHook(dbPath, slot, recordPath),
        )

        # Act
        hooks()

        # Assert
        assert slot.drainEventId is None
        record = _record(recordPath)
        assert record["verdict"] == BACKLOG_OUTSTANDING
        assert record["perTable"][OWN_DRAIN_CLOSE_TABLE] == 1
        assert record["ownDrainCloseExcluded"] is None

    def test_noOpenDrainRow_slotStaysEmpty(self, tmp_path: Path) -> None:
        """
        Given: no open drain row (the close has nothing to write)
        When:  the close hook runs
        Then:  the slot stays empty
        """
        dbPath = _makeDb(tmp_path)
        slot = OwnDrainCloseSlot()

        _closeHook(dbPath, slot)()

        assert slot.drainEventId is None
        assert slot.exclusion() is None


# ================================================================================
# VC-3: the VCELL-floor fast path gets the same exclusion
# ================================================================================


class TestVcellFloorFastPath:

    def test_fastPath_ownCloseOnly_readsDelivered(self, tmp_path: Path) -> None:
        """
        Given: a real sequencer whose VCELL is at the floor (run-to-cutoff) and
               only this shutdown's own drain row outstanding
        When:  handleOnBattery skips the pipeline and powers off
        Then:  custody reads DELIVERED there too, with the row named beside it
        """
        # Arrange
        dbPath = _makeDb(tmp_path)
        drainId = _openDrain(dbPath)
        slot = OwnDrainCloseSlot()
        recordPath = tmp_path / "custody.json"
        calls: list[str] = []
        sequencer = ShutdownSequencer(
            isOnBattery=lambda: True,
            vcell=lambda: 3.40,
            runPipelineFn=lambda: calls.append("pipeline"),
            powerOffFn=lambda: calls.append("poweroff"),
            vcellFloor=3.45,
            totalCapSec=5.0,
            smoothingSec=0.0,
            smoothingPollSec=0.0,
            sleepFn=lambda _s: None,
            prePowerOffFn=m.composePrePowerOffHooks(
                _closeHook(dbPath, slot),
                _custodyHook(dbPath, slot, recordPath),
            ),
        )

        # Act
        sequencer.handleOnBattery()

        # Assert
        assert calls == ["poweroff"]
        record = _record(recordPath)
        assert record["verdict"] == BACKLOG_DELIVERED
        assert record["ownDrainCloseExcluded"]["drain_event_id"] == drainId
        assert record["ownDrainCloseExcluded"]["wasOutstanding"] is True


# ================================================================================
# The close keeps its position and its close-time depth
# ================================================================================


class TestTheCloseDoesNotMove:

    def test_close_stillRecordsItsCloseTimeDepth(self, tmp_path: Path) -> None:
        """
        Given: the production close hook with a slot wired
        When:  it runs
        Then:  end_vcell_v is the UPS reading at close time, unchanged
        """
        dbPath = _makeDb(tmp_path)
        _openDrain(dbPath)
        slot = OwnDrainCloseSlot()

        _closeHook(dbPath, slot)()

        conn = sqlite3.connect(dbPath)
        try:
            endVcell = conn.execute(
                "SELECT end_vcell_v FROM battery_health_log"
            ).fetchone()[0]
        finally:
            conn.close()
        assert endVcell == pytest.approx(3.47)

    def test_main_composesTheCloseBeforeCustody_andSharesOneSlot(self) -> None:
        """
        Given: the production entrypoint
        When:  its source is parsed
        Then:  the close still runs first, and ONE slot is handed to both the
               close factory and the custody hook
        """
        tree = ast.parse(inspect.getsource(m.main))
        calls: dict[str, ast.Call] = {}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in (
                        "buildDrainCloseHook", "makeSyncCustodyHook",
                        "composePrePowerOffHooks",
                    )):
                # First occurrence: the pre-poweroff composition, not the
                # loss-observed one nested inside the sequencer's arguments.
                calls.setdefault(node.func.id, node)
        for name in ("buildDrainCloseHook", "makeSyncCustodyHook"):
            slotArg = [kw.value for kw in calls[name].keywords
                       if kw.arg == "ownDrainCloseSlot"]
            assert slotArg, f"{name} is not given the slot"
            assert isinstance(slotArg[0], ast.Name)
            assert slotArg[0].id == "ownDrainCloseSlot"
        composed = [a.id for a in calls["composePrePowerOffHooks"].args
                    if isinstance(a, ast.Name)]
        assert composed[:2] == ["drainCloseFn", "custodyFn"]
