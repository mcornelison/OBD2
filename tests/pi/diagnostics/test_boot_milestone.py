################################################################################
# File Name: test_boot_milestone.py
# Purpose/Description: US-860-a -- the forward boot record.  The boot_milestone
#                      table, its first-write-wins writer, event-time uptime,
#                      the 'unknown' boot-id refusal, and the connect_success
#                      writer driven through a real ObdConnection.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-13    | Rex (US-860-a)| Initial.
# 2026-10-14    | Rex (US-860-b)| Integer id + UNIQUE rung; Sprint 98 DB rebuild.
################################################################################
"""US-860-a: each boot records its milestone ladder, kernel start to drive start."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.pi.diagnostics import boot_milestone as bm
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.obd_connection import ObdConnection

BOOT = "3f1c0000000000000000000000000001"
# The wall time the fake kernel came up, and how long ago it did.
KERNEL_UP = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path: Any) -> ObdDatabase:
    database = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    database.initialize()
    return database


@pytest.fixture(autouse=True)
def _resetUnknownLatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bm, "_unknownBootLogged", False)
    # Act as the Pi: the boot-id surface exists, readBootId is consulted.
    monkeypatch.setattr(bm, "_bootIdSurfacePresent", lambda: True)


def _rows(database: ObdDatabase, bootId: str = BOOT) -> dict[str, tuple[str, float]]:
    with database.connect() as conn:
        return {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                "SELECT milestone, ts_utc, uptime_s FROM boot_milestone WHERE boot_id = ?",
                (bootId,),
            )
        }


def _arm(database: ObdDatabase, *, bootId: str = BOOT) -> bool:
    """kernel_start, as the orchestrator writes it, 65 s after KERNEL_UP."""
    return bm.recordKernelStart(
        database,
        bootId=bootId,
        now=KERNEL_UP + timedelta(seconds=65),
        uptimeReader=lambda: 65.0,
    )


def _at(seconds: float) -> datetime:
    return KERNEL_UP + timedelta(seconds=seconds)


class _ConnectedObd:
    """A python-obd stand-in that is connected and answers nothing."""

    def is_connected(self) -> bool:
        return True

    def close(self) -> None:
        pass

    def query(self, *args: Any, **kwargs: Any) -> Any:
        return None

    def supports(self, *args: Any, **kwargs: Any) -> bool:
        return False


def _connection(database: ObdDatabase) -> ObdConnection:
    return ObdConnection(
        config={
            "pi": {
                "bluetooth": {
                    "macAddress": "/dev/rfcomm-test",
                    "retryDelays": [0],
                    "maxRetries": 0,
                    "connectionTimeoutSeconds": 1,
                },
            },
        },
        database=database,
        obdFactory=lambda port, timeout: _ConnectedObd(),
    )


# ================================================================================
# Table
# ================================================================================


def _uniqueIndexColumns(conn: sqlite3.Connection, table: str) -> list[list[str]]:
    """The column lists of every UNIQUE index on ``table``."""
    out = []
    for idx in conn.execute(f"PRAGMA index_list({table})").fetchall():
        if idx[2]:  # unique
            out.append([r[2] for r in conn.execute(f"PRAGMA index_info('{idx[1]}')")])
    return out


class TestTable:
    def test_initialize_createsBootMilestoneWithIntegerIdAndUniqueRung(
        self, db: ObdDatabase
    ) -> None:
        """US-860-b: id INTEGER PRIMARY KEY AUTOINCREMENT, UNIQUE(boot_id, milestone)."""
        with db.connect() as conn:
            info = conn.execute("PRAGMA table_info(boot_milestone)").fetchall()
            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='boot_milestone'"
            ).fetchone()[0]
            unique = _uniqueIndexColumns(conn, "boot_milestone")
        columns = {r[1]: (r[2], r[5]) for r in info}  # name -> (type, pk position)
        assert [r[1] for r in info] == ["id", "boot_id", "milestone", "ts_utc", "uptime_s"]
        assert columns["id"] == ("INTEGER", 1)
        assert all(pk == 0 for name, (_, pk) in columns.items() if name != "id")
        assert "AUTOINCREMENT" in ddl.upper()
        assert ["boot_id", "milestone"] in unique

    def test_initialize_existingDatabase_gainsTableWithoutDataLoss(self, tmp_path: Any) -> None:
        path = str(tmp_path / "legacy.db")
        legacy = sqlite3.connect(path)
        legacy.execute("CREATE TABLE startup_log (boot_id TEXT PRIMARY KEY, recorded_at TEXT)")
        legacy.execute("INSERT INTO startup_log VALUES ('old', '2026-10-01T00:00:00Z')")
        legacy.commit()
        legacy.close()

        database = ObdDatabase(path, walMode=False)
        database.initialize()

        with database.connect() as conn:
            assert [tuple(r) for r in conn.execute("SELECT boot_id FROM startup_log")] == [("old",)]
            assert conn.execute("SELECT COUNT(*) FROM boot_milestone").fetchone()[0] == 0

    def test_vocabulary_isTheSevenRungs(self) -> None:
        assert bm.MILESTONES == (
            "kernel_start",
            "obd_connected",
            "first_sample_obd",
            "first_sample_imu",
            "first_sample_light",
            "first_sample_ups",
            "drive_start",
        )


# ================================================================================
# US-860-b: the Sprint 98 table gains an integer id
# ================================================================================

# The table exactly as Sprint 98 (US-860-a) shipped it: composite PK, no id.
_SPRINT98_DDL = """
CREATE TABLE boot_milestone (
    boot_id TEXT NOT NULL,
    milestone TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    uptime_s REAL NOT NULL,
    PRIMARY KEY (boot_id, milestone)
)
"""

# Inserted out of ts_utc order, so the copy's ordering is what assigns the ids.
_SPRINT98_ROWS = [
    (BOOT, "drive_start", "2026-10-13T12:01:16Z", 76.0),
    (BOOT, "kernel_start", "2026-10-13T12:00:00Z", 0.0),
    (BOOT, "obd_connected", "2026-10-13T12:01:02Z", 62.0),
]


def _sprint98Database(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(_SPRINT98_DDL)
    conn.executemany("INSERT INTO boot_milestone VALUES (?, ?, ?, ?)", _SPRINT98_ROWS)
    conn.commit()
    conn.close()


def _allRows(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return [
        tuple(r)
        for r in conn.execute(
            "SELECT id, boot_id, milestone, ts_utc, uptime_s FROM boot_milestone ORDER BY id"
        )
    ]


def _traced(conn: sqlite3.Connection) -> list[str]:
    """Record every statement ``conn`` executes from now on."""
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    return statements


_WRITE_VERBS = ("CREATE", "INSERT", "DROP", "ALTER", "DELETE", "UPDATE")


class TestIntegerIdUpgrade:
    def test_sprint98Database_rebuilt_idsInTsOrder_valuesUnchanged(self, tmp_path: Any) -> None:
        from src.pi.obdii.database_schema import ensureBootMilestoneIntegerId

        path = str(tmp_path / "s98.db")
        _sprint98Database(path)
        conn = sqlite3.connect(path)
        try:
            assert ensureBootMilestoneIntegerId(conn) is True
            conn.commit()
            assert _allRows(conn) == [
                (1, BOOT, "kernel_start", "2026-10-13T12:00:00Z", 0.0),
                (2, BOOT, "obd_connected", "2026-10-13T12:01:02Z", 62.0),
                (3, BOOT, "drive_start", "2026-10-13T12:01:16Z", 76.0),
            ]
            assert ["boot_id", "milestone"] in _uniqueIndexColumns(conn, "boot_milestone")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
            assert "boot_milestone_new" not in tables
        finally:
            conn.close()

    def test_sameTsUtc_tieBrokenByMilestone(self, tmp_path: Any) -> None:
        from src.pi.obdii.database_schema import ensureBootMilestoneIntegerId

        path = str(tmp_path / "s98.db")
        conn = sqlite3.connect(path)
        conn.execute(_SPRINT98_DDL)
        conn.executemany(
            "INSERT INTO boot_milestone VALUES (?, ?, ?, ?)",
            [
                (BOOT, "obd_connected", "2026-10-13T12:01:02Z", 62.0),
                (BOOT, "first_sample_obd", "2026-10-13T12:01:02Z", 62.0),
            ],
        )
        conn.commit()
        try:
            ensureBootMilestoneIntegerId(conn)
            assert [r[2] for r in _allRows(conn)] == ["first_sample_obd", "obd_connected"]
        finally:
            conn.close()

    def test_secondRun_isNoOp_executesNoWrite(self, tmp_path: Any) -> None:
        from src.pi.obdii.database_schema import ensureBootMilestoneIntegerId

        path = str(tmp_path / "s98.db")
        _sprint98Database(path)
        conn = sqlite3.connect(path)
        try:
            ensureBootMilestoneIntegerId(conn)
            conn.commit()
            before = _allRows(conn)
            statements = _traced(conn)
            assert ensureBootMilestoneIntegerId(conn) is False
            conn.set_trace_callback(None)
            assert not [s for s in statements if s.lstrip().upper().startswith(_WRITE_VERBS)]
            assert _allRows(conn) == before
        finally:
            conn.close()

    def test_newShapeDatabase_isUntouched(self, db: ObdDatabase) -> None:
        from src.pi.obdii.database_schema import ensureBootMilestoneIntegerId

        _arm(db)
        with db.connect() as conn:
            statements = _traced(conn)
            assert ensureBootMilestoneIntegerId(conn) is False
            conn.set_trace_callback(None)
        assert not [s for s in statements if s.lstrip().upper().startswith(_WRITE_VERBS)]
        assert _rows(db) == {"kernel_start": ("2026-10-13T12:00:00Z", 0.0)}

    def test_noTable_isNoOp(self, tmp_path: Any) -> None:
        from src.pi.obdii.database_schema import ensureBootMilestoneIntegerId

        conn = sqlite3.connect(str(tmp_path / "empty.db"))
        try:
            assert ensureBootMilestoneIntegerId(conn) is False
            assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
        finally:
            conn.close()

    def test_failureMidRebuild_rollsBackWhole_oldTableAndRowsKept(self, tmp_path: Any) -> None:
        """ONE transaction: a failure after the copy leaves the Sprint 98 table as it was."""
        from src.pi.obdii.database_schema import ensureBootMilestoneIntegerId

        path = str(tmp_path / "s98.db")
        _sprint98Database(path)
        conn = sqlite3.connect(path)

        def _denyDrop(action: int, *args: Any) -> int:
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_DROP_TABLE else sqlite3.SQLITE_OK

        try:
            conn.set_authorizer(_denyDrop)
            with pytest.raises(sqlite3.Error):
                ensureBootMilestoneIntegerId(conn)
            conn.set_authorizer(None)
            conn.commit()
            names = [r[1] for r in conn.execute("PRAGMA table_info(boot_milestone)")]
            assert names == ["boot_id", "milestone", "ts_utc", "uptime_s"]
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
            assert "boot_milestone_new" not in tables
            rows = conn.execute("SELECT * FROM boot_milestone ORDER BY ts_utc").fetchall()
            assert rows == sorted(_SPRINT98_ROWS, key=lambda r: r[2])
        finally:
            conn.close()

    def test_initialize_upgradesSprint98Database_twice(self, tmp_path: Any) -> None:
        """Wired in ObdDatabase.initialize: every boot runs it; the second is a no-op."""
        path = str(tmp_path / "s98.db")
        _sprint98Database(path)

        database = ObdDatabase(path, walMode=False)
        database.initialize()
        with database.connect() as conn:
            first = _allRows(conn)
        database.initialize()
        with database.connect() as conn:
            second = _allRows(conn)
            names = [r[1] for r in conn.execute("PRAGMA table_info(boot_milestone)")]

        assert names == ["id", "boot_id", "milestone", "ts_utc", "uptime_s"]
        assert [r[0] for r in first] == [1, 2, 3]
        assert [r[2] for r in first] == ["kernel_start", "obd_connected", "drive_start"]
        assert second == first

    def test_upgradedDatabase_nextWriteContinuesIds_andStillFirstWriteWins(
        self, tmp_path: Any
    ) -> None:
        path = str(tmp_path / "s98.db")
        _sprint98Database(path)
        database = ObdDatabase(path, walMode=False)
        database.initialize()

        bm.recordMilestone(database, bm.FIRST_SAMPLE_IMU, _at(70), bootId=BOOT)
        bm.recordMilestone(database, bm.OBD_CONNECTED, _at(300), bootId=BOOT)

        with database.connect() as conn:
            rows = _allRows(conn)
        assert rows[-1] == (4, BOOT, "first_sample_imu", "2026-10-13T12:01:10Z", 70.0)
        assert len(rows) == 4
        assert _rows(database)["obd_connected"] == ("2026-10-13T12:01:02Z", 62.0)


# ================================================================================
# Writer
# ================================================================================


class TestKernelStart:
    def test_kernelStart_isWallMinusUptime_andUptimeZero(self, db: ObdDatabase) -> None:
        assert _arm(db) is True
        assert _rows(db) == {"kernel_start": ("2026-10-13T12:00:00Z", 0.0)}

    def test_kernelStart_secondWrite_ignored(self, db: ObdDatabase) -> None:
        _arm(db)
        bm.recordKernelStart(
            db, bootId=BOOT, now=_at(500), uptimeReader=lambda: 10.0
        )
        assert _rows(db)["kernel_start"] == ("2026-10-13T12:00:00Z", 0.0)

    def test_kernelStart_uptimeUnreadable_writesNothing(
        self, db: ObdDatabase, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            ok = bm.recordKernelStart(db, bootId=BOOT, now=_at(5), uptimeReader=lambda: None)
        assert ok is False
        assert _rows(db) == {}
        assert any("uptime" in r.message for r in caplog.records)


class TestMilestone:
    def test_uptime_isEventMinusKernelStart_notWriteTime(self, db: ObdDatabase) -> None:
        """Written 3 s after the reading: uptime is the reading's, not the write's."""
        _arm(db)
        readingTs = "2026-10-13T12:01:05Z"  # the reading's event time (65 s)
        bm.recordMilestone(db, bm.FIRST_SAMPLE_OBD, readingTs, bootId=BOOT)
        assert _rows(db)["first_sample_obd"] == (readingTs, 65.0)

    def test_firstWriteWins(self, db: ObdDatabase) -> None:
        _arm(db)
        bm.recordMilestone(db, bm.OBD_CONNECTED, _at(62), bootId=BOOT)
        bm.recordMilestone(db, bm.OBD_CONNECTED, _at(300), bootId=BOOT)
        assert _rows(db)["obd_connected"] == ("2026-10-13T12:01:02Z", 62.0)

    def test_secondWriteOfARung_allocatesNoRow_maxIdUnchanged(self, db: ObdDatabase) -> None:
        """US-860-b: the ignored write adds no row and leaves max(id) alone.

        SQLite's AUTOINCREMENT counter still advances on an ignored INSERT, so
        the next rung's id may skip one; the id cursor (``id > last``) only
        needs ids to rise, which this pins.
        """
        _arm(db)
        bm.recordMilestone(db, bm.OBD_CONNECTED, _at(62), bootId=BOOT)
        with db.connect() as conn:
            maxBefore = conn.execute("SELECT MAX(id) FROM boot_milestone").fetchone()[0]

        bm.recordMilestone(db, bm.OBD_CONNECTED, _at(300), bootId=BOOT)

        with db.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM boot_milestone WHERE milestone = 'obd_connected'"
            ).fetchone()[0]
            maxAfter = conn.execute("SELECT MAX(id) FROM boot_milestone").fetchone()[0]
        assert count == 1
        assert maxAfter == maxBefore
        assert _rows(db)["obd_connected"] == ("2026-10-13T12:01:02Z", 62.0)
        bm.recordMilestone(db, bm.DRIVE_START, _at(76), bootId=BOOT)
        with db.connect() as conn:
            nextId = conn.execute(
                "SELECT id FROM boot_milestone WHERE milestone = 'drive_start'"
            ).fetchone()[0]
        assert nextId > maxBefore

    def test_naiveLocalDatetime_isReadAsLocalTime(self, db: ObdDatabase) -> None:
        """DriveDetector hands a naive datetime.now(); it is local wall time."""
        _arm(db)
        naiveLocal = _at(76).astimezone().replace(tzinfo=None)
        bm.recordMilestone(db, bm.DRIVE_START, naiveLocal, bootId=BOOT)
        assert _rows(db)["drive_start"] == ("2026-10-13T12:01:16Z", 76.0)

    def test_noKernelStartRow_armsItFirst(self, db: ObdDatabase, monkeypatch: Any) -> None:
        """A rung written before the orchestrator armed still gets its base."""
        monkeypatch.setattr(bm, "readSystemUptimeSeconds", lambda: 30.0)
        monkeypatch.setattr(bm, "_utcNow", lambda: _at(30))
        bm.recordMilestone(db, bm.OBD_CONNECTED, _at(20), bootId=BOOT)
        assert _rows(db) == {
            "kernel_start": ("2026-10-13T12:00:00Z", 0.0),
            "obd_connected": ("2026-10-13T12:00:20Z", 20.0),
        }

    def test_noKernelStartAndUptimeUnreadable_writesNothing(
        self, db: ObdDatabase, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(bm, "readSystemUptimeSeconds", lambda: None)
        assert bm.recordMilestone(db, bm.OBD_CONNECTED, _at(20), bootId=BOOT) is False
        assert _rows(db) == {}

    def test_kernelStartThroughRecordMilestone_isRefused(self, db: ObdDatabase) -> None:
        with pytest.raises(ValueError):
            bm.recordMilestone(db, bm.KERNEL_START, _at(0), bootId=BOOT)

    def test_unknownMilestone_isRefused(self, db: ObdDatabase) -> None:
        with pytest.raises(ValueError):
            bm.recordMilestone(db, "first_sample_gps", _at(0), bootId=BOOT)

    def test_unparseableEventTs_writesNothing(self, db: ObdDatabase) -> None:
        _arm(db)
        assert bm.recordMilestone(db, bm.FIRST_SAMPLE_IMU, "soon", bootId=BOOT) is False
        assert set(_rows(db)) == {"kernel_start"}

    def test_noDatabase_writesNothing(self) -> None:
        assert bm.recordMilestone(None, bm.OBD_CONNECTED, _at(1), bootId=BOOT) is False


class TestUnknownBootId:
    def test_unknownBootId_writesNothing_andLogsOneLine(
        self, db: ObdDatabase, monkeypatch: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(bm, "readBootId", lambda: "unknown")
        with caplog.at_level(logging.DEBUG, logger=bm.logger.name):
            assert bm.recordKernelStart(db, now=_at(65), uptimeReader=lambda: 65.0) is False
            assert bm.recordMilestone(db, bm.OBD_CONNECTED, _at(62)) is False
            assert bm.recordMilestone(db, bm.DRIVE_START, _at(76)) is False

        with db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM boot_milestone").fetchone()[0] == 0
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1
        assert "unknown" in warnings[0].message and "boot" in warnings[0].message

    def test_bootIdDefaultsToReadBootId(self, db: ObdDatabase, monkeypatch: Any) -> None:
        monkeypatch.setattr(bm, "readBootId", lambda: BOOT)
        bm.recordKernelStart(db, now=_at(65), uptimeReader=lambda: 65.0)
        assert set(_rows(db)) == {"kernel_start"}

    def test_noBootIdSurface_isUnknown_withoutCallingReadBootId(
        self, db: ObdDatabase, monkeypatch: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Off-Linux: no ERROR from boot_reason per tick, one WARNING, no row."""
        monkeypatch.setattr(bm, "_bootIdSurfacePresent", lambda: False)

        def _mustNotBeCalled() -> str:
            raise AssertionError("readBootId called with no boot-id surface")

        monkeypatch.setattr(bm, "readBootId", _mustNotBeCalled)
        with caplog.at_level(logging.DEBUG):
            assert bm.recordMilestone(db, bm.OBD_CONNECTED, _at(1)) is False
            assert bm.recordMilestone(db, bm.DRIVE_START, _at(2)) is False

        assert [r.levelname for r in caplog.records if r.levelno >= logging.WARNING] == [
            "WARNING"
        ]
        with db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM boot_milestone").fetchone()[0] == 0

    def test_readBootId_isBootProgressReader(self) -> None:
        from src.pi.diagnostics import boot_progress

        assert bm.readBootId is boot_progress.readBootId


# ================================================================================
# connect_success writer (src/pi/obdii/obd_connection.py)
# ================================================================================


class TestConnectSuccessWriter:
    def test_connect_writesObdConnected_firstConnectWins(
        self, db: ObdDatabase, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(bm, "readBootId", lambda: BOOT)
        _arm(db)
        connection = _connection(db)

        assert connection.connect() is True
        first = _rows(db)["obd_connected"]
        connection.disconnect()
        assert connection.connect() is True

        assert _rows(db)["obd_connected"] == first
        # Its uptime comes from its own ts, against kernel_start.
        ts = datetime.strptime(first[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert first[1] == (ts - KERNEL_UP).total_seconds()

    def test_connect_noDatabase_stillConnects(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(bm, "readBootId", lambda: BOOT)
        connection = ObdConnection(
            config={"pi": {"bluetooth": {"macAddress": "/dev/rfcomm-test",
                                         "retryDelays": [0], "maxRetries": 0}}},
            obdFactory=lambda port, timeout: _ConnectedObd(),
        )
        assert connection.connect() is True


# ================================================================================
# Validation criteria: simulated boots
# ================================================================================


class TestSimulatedBoot:
    def test_fullBoot_sevenRows_obdConnectedHoldsFirstConnect(self, db: ObdDatabase) -> None:
        _arm(db)
        bm.recordMilestone(db, bm.OBD_CONNECTED, _at(62), bootId=BOOT)
        for milestone, s in (
            (bm.FIRST_SAMPLE_OBD, 65), (bm.FIRST_SAMPLE_IMU, 22),
            (bm.FIRST_SAMPLE_LIGHT, 23), (bm.FIRST_SAMPLE_UPS, 24),
        ):
            bm.recordMilestone(db, milestone, _at(s), bootId=BOOT)
        bm.recordMilestone(db, bm.DRIVE_START, _at(76), bootId=BOOT)
        bm.recordMilestone(db, bm.OBD_CONNECTED, _at(400), bootId=BOOT)  # reconnect

        rows = _rows(db)
        assert set(rows) == set(bm.MILESTONES)
        assert rows["obd_connected"] == ("2026-10-13T12:01:02Z", 62.0)

    def test_engineNeverAnswers_noObdRungs(self, db: ObdDatabase) -> None:
        _arm(db)
        for milestone, s in (
            (bm.FIRST_SAMPLE_IMU, 22), (bm.FIRST_SAMPLE_LIGHT, 23), (bm.FIRST_SAMPLE_UPS, 24),
        ):
            bm.recordMilestone(db, milestone, _at(s), bootId=BOOT)

        assert set(_rows(db)) == {
            "kernel_start", "first_sample_imu", "first_sample_light", "first_sample_ups",
        }

    def test_twoBoots_doNotMerge(self, db: ObdDatabase) -> None:
        _arm(db, bootId="boot-a")
        _arm(db, bootId="boot-b")
        bm.recordMilestone(db, bm.OBD_CONNECTED, _at(10), bootId="boot-a")
        assert set(_rows(db, "boot-a")) == {"kernel_start", "obd_connected"}
        assert set(_rows(db, "boot-b")) == {"kernel_start"}


# ================================================================================
# Capture-health emit writer (card_state_emitter.py) -- the real mixins
# ================================================================================


class _Writer:
    def __init__(self, firstRowTs: str | None) -> None:
        self.firstRowTs = firstRowTs


class _RealtimeLogger:
    """The orchestrator's realtime logger: ``.dataLogger`` is the one writer."""

    def __init__(self, firstRowTs: str | None) -> None:
        self.dataLogger = _Writer(firstRowTs)
        self.lastRowWrittenSecondsAgo = 1.0 if firstRowTs else None


class _Bridge:
    def __init__(self, firstSampleTs: str | None) -> None:
        self.firstSampleTs = firstSampleTs
        self.lastSampleCapture = 0.0 if firstSampleTs else None


def _orchestrator(tmp_path: Any, database: ObdDatabase, **feeds: Any) -> Any:
    from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
    from pi.obdii.orchestrator.health_monitor import HealthMonitorMixin

    class _Orch(HealthMonitorMixin, CardStateEmitterMixin):  # production MRO order
        pass

    orch = _Orch()
    orch._config = {
        "pi": {
            "splash": {"statesDir": str(tmp_path / "states")},
            "captureHealth": {"enabled": True, "stallSeconds": 60.0},
        }
    }
    orch._connection = None
    orch._driveDetector = None
    orch._hardwareManager = None
    orch._powerSourceProvider = None
    orch._database = database
    orch._dataLogger = _RealtimeLogger(feeds.get("obd"))
    orch._imuStateBridge = _Bridge(feeds.get("imu"))
    orch._lightStateBridge = _Bridge(feeds.get("light"))
    orch._upsFirstSampleTs = feeds.get("ups")
    orch._upsLastSampleMonotonic = 0.0 if feeds.get("ups") else None
    orch._feedClock = lambda: 1.0
    orch._cardStateEmitEnabled = False
    orch._initializeCaptureHealthProducer(str(tmp_path / "states"))
    return orch


class TestCaptureHealthEmitWriter:
    def test_emit_writesFirstSampleRungs_fromPublishedFeeds(
        self, tmp_path: Any, db: ObdDatabase, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(bm, "readBootId", lambda: BOOT)
        _arm(db)
        orch = _orchestrator(
            tmp_path, db,
            obd="2026-10-13T12:01:05Z", imu="2026-10-13T12:00:22Z",
            light="2026-10-13T12:00:23Z", ups="2026-10-13T12:00:24Z",
        )

        orch._emitCaptureHealthState()

        published = json.loads((tmp_path / "states" / "capture-health").read_text())
        assert published["feeds"]["obd"]["firstSampleTs"] == "2026-10-13T12:01:05Z"
        assert _rows(db) == {
            "kernel_start": ("2026-10-13T12:00:00Z", 0.0),
            "first_sample_obd": ("2026-10-13T12:01:05Z", 65.0),
            "first_sample_imu": ("2026-10-13T12:00:22Z", 22.0),
            "first_sample_light": ("2026-10-13T12:00:23Z", 23.0),
            "first_sample_ups": ("2026-10-13T12:00:24Z", 24.0),
        }

    def test_emit_feedWithNoSample_hasNoRung_untilItArrives(
        self, tmp_path: Any, db: ObdDatabase, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(bm, "readBootId", lambda: BOOT)
        _arm(db)
        orch = _orchestrator(tmp_path, db, imu="2026-10-13T12:00:22Z")

        orch._emitCaptureHealthState()
        assert set(_rows(db)) == {"kernel_start", "first_sample_imu"}

        orch._dataLogger = _RealtimeLogger("2026-10-13T12:01:05Z")
        orch._emitCaptureHealthState()
        assert _rows(db)["first_sample_obd"] == ("2026-10-13T12:01:05Z", 65.0)

    def test_emit_writtenRung_isNotRewritten(
        self, tmp_path: Any, db: ObdDatabase, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(bm, "readBootId", lambda: BOOT)
        _arm(db)
        orch = _orchestrator(tmp_path, db, imu="2026-10-13T12:00:22Z")
        orch._emitCaptureHealthState()

        calls: list[str] = []
        real = bm.recordMilestone
        monkeypatch.setattr(
            bm, "recordMilestone",
            lambda database, milestone, ts, **kw: calls.append(milestone)
            or real(database, milestone, ts, **kw),
        )
        orch._emitCaptureHealthState()

        assert "first_sample_imu" not in calls

    def test_emit_unknownBootId_writesNothing_emitStillPublishes(
        self, tmp_path: Any, db: ObdDatabase, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(bm, "readBootId", lambda: "unknown")
        orch = _orchestrator(tmp_path, db, imu="2026-10-13T12:00:22Z")

        orch._emitCaptureHealthState()

        assert (tmp_path / "states" / "capture-health").exists()
        with db.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM boot_milestone").fetchone()[0] == 0

    def test_initializeCardStateEmitters_armsKernelStart_evenWithCardsOff(
        self, tmp_path: Any, db: ObdDatabase, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(bm, "readBootId", lambda: BOOT)
        monkeypatch.setattr(bm, "readSystemUptimeSeconds", lambda: 65.0)
        monkeypatch.setattr(bm, "_utcNow", lambda: _at(65))
        orch = _orchestrator(tmp_path, db)

        orch._initializeCardStateEmitters()

        assert _rows(db) == {"kernel_start": ("2026-10-13T12:00:00Z", 0.0)}
