################################################################################
# File Name: test_battery_health_capacity_columns.py
# Purpose/Description: ARCH-065 capacity columns on battery_health_log -- the
#                      PRAGMA-probed adder, its idempotence, the drain_trigger
#                      CHECK, and the drain writer's cell_epoch stamp.
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a)  | Initial.
# ================================================================================
################################################################################

"""Tests for the ARCH-065 battery_health_log capacity columns."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest

from src.pi.power.battery_health import (
    BATTERY_HEALTH_CAPACITY_COLUMNS,
    DRAIN_TRIGGER_VALUES,
    ensureBatteryHealthLogCapacityColumns,
    ensureBatteryHealthLogTable,
)
from src.pi.power.drain_event_writer import DrainEventWriter

_LEGACY_DDL = (
    "CREATE TABLE battery_health_log (drain_event_id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "start_timestamp TEXT NOT NULL, end_timestamp TEXT, start_vcell_v REAL, end_vcell_v REAL, "
    "runtime_seconds INTEGER, load_class TEXT NOT NULL DEFAULT 'production')"
)


def _cols(conn: sqlite3.Connection) -> list[str]:
    return [r[1] for r in conn.execute("PRAGMA table_info(battery_health_log)")]


def test_legacyTable_gainsEveryCapacityColumn_andLegacyRowsReadKeyoff() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(_LEGACY_DDL)
    conn.execute("INSERT INTO battery_health_log (start_timestamp) VALUES ('2026-09-30T20:34:16Z')")
    added = ensureBatteryHealthLogCapacityColumns(conn)
    assert added == [name for name, _ in BATTERY_HEALTH_CAPACITY_COLUMNS]
    assert conn.execute("SELECT drain_trigger, cell_epoch FROM battery_health_log").fetchone() == ("keyoff", None)


def test_secondRun_isANoOp() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(_LEGACY_DDL)
    ensureBatteryHealthLogCapacityColumns(conn)
    before = _cols(conn)
    assert ensureBatteryHealthLogCapacityColumns(conn) == []
    assert _cols(conn) == before


def test_freshTable_alreadyHasThem_soNothingIsAdded() -> None:
    conn = sqlite3.connect(":memory:")
    ensureBatteryHealthLogTable(conn)
    assert ensureBatteryHealthLogCapacityColumns(conn) == []


def test_badTrigger_isRejectedByTheCheck() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(_LEGACY_DDL)
    ensureBatteryHealthLogCapacityColumns(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO battery_health_log (start_timestamp, drain_trigger) VALUES ('x', 'weekly')")
    assert DRAIN_TRIGGER_VALUES == ("keyoff", "monthly_test", "calibration")


def test_freshTable_rejectsBadTrigger_likeAMigratedOne() -> None:
    conn = sqlite3.connect(":memory:")
    ensureBatteryHealthLogTable(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO battery_health_log (start_timestamp, drain_trigger) VALUES ('x', 'weekly')")


class _FileDb:
    """Minimal DatabaseLike over a shared in-memory-or-file sqlite path."""

    def __init__(self, path: str) -> None:
        self._path = path

    @contextmanager
    def connect(self):  # noqa: ANN201
        conn = sqlite3.connect(self._path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _openWith(tmp_path, cellEpoch):  # noqa: ANN001, ANN202
    path = str(tmp_path / "obd.db")
    db = _FileDb(path)
    with db.connect() as conn:
        ensureBatteryHealthLogTable(conn)
    writer = DrainEventWriter(database=db, upsResolver=lambda: None, cellEpoch=cellEpoch)
    drainEventId = writer.openDrainEvent()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT cell_epoch FROM battery_health_log WHERE drain_event_id = ?", (drainEventId,)
        ).fetchone()
    return drainEventId, row


def test_openDrainEvent_stampsCellEpoch(tmp_path) -> None:  # noqa: ANN001
    drainEventId, row = _openWith(tmp_path, "2026-09-fresh")
    assert drainEventId is not None
    assert row == ("2026-09-fresh",)


def test_openDrainEvent_withoutCellEpoch_leavesItNull(tmp_path) -> None:  # noqa: ANN001
    drainEventId, row = _openWith(tmp_path, None)
    assert drainEventId is not None
    assert row == (None,)
