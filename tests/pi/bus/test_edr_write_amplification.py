################################################################################
# File Name: test_edr_write_amplification.py
# Purpose/Description: Regression guard for ARCH-030 -- the EDR persistence
#     subscriber must NOT open a fresh SQLite connection per persisted row.
#
#     Measured on chi-eclipse-01 2026-09-16 (idle, wall power, no OBD link):
#     connection-per-row made SQLite checkpoint a 2.9 GB database on every close
#     (the closing connection was always the LAST one), turning ~3.7 KB/s of EDR
#     rows into ~3.4 MB/s of physical SD writes -- ~900x amplification, ~85
#     fdatasync/s, ~294 GB/day. Holding ONE connection open cut total machine
#     I/O 9x with no code change, which is what this test locks in.
#
#     These tests assert CONNECTION COUNT and ROW VISIBILITY, because those are
#     the two properties that must hold together: the fix is only correct if it
#     also keeps every row durable and readable straight after the write (the
#     EDR is a black box -- a row that is not committed is a row that is lost).
# Author: Atlas (ARCH-030, CIO build override 2026-09-16)
# Creation Date: 2026-09-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""ARCH-030: EDR persistence must not open one SQLite connection per row."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pi.bus.edr_persistence_subscriber import EdrPersistenceSubscriber
from pi.bus.sample import Sample
from pi.obdii.database import ObdDatabase

_BURSTS = 10


class _ConnectCountingDatabase:
    """Wraps a real ObdDatabase and counts how many times connect() is called.

    Deliberately NOT a mock: every call is delegated to a real database, so the
    rows this test reads back were written by the real write path. The counter
    is the only thing added.
    """

    def __init__(self, inner: ObdDatabase) -> None:
        self._inner = inner
        self.connectCalls = 0

    def connect(self):  # noqa: ANN201 -- mirrors ObdDatabase.connect()
        self.connectCalls += 1
        return self._inner.connect()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.fixture()
def countingDb(tmp_path: Path) -> _ConnectCountingDatabase:
    """An initialized real database wrapped in a connect() counter."""
    inner = ObdDatabase(str(tmp_path / "test_edr_amplification.db"), walMode=False)
    inner.initialize()
    return _ConnectCountingDatabase(inner)


def _imu(field: str, value: Any, seq: int) -> Sample:
    """One raw.imu.<field> sample on burst `seq`."""
    return Sample(
        topic=f"raw.imu.{field}",
        source="imu",
        value=value,
        unit="x",
        tsUtc="2026-09-16T16:00:00Z",
        tsCapture=float(seq),
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _feedBurst(sub: EdrPersistenceSubscriber, seq: int) -> None:
    """Feed a complete IMU burst (accel+gyro+mag+temp) under one seq."""
    sub.handleSample(_imu("accel", (1.0, 2.0, 3.0), seq))
    sub.handleSample(_imu("gyro", (4.0, 5.0, 6.0), seq))
    sub.handleSample(_imu("mag", (7.0, 8.0, 9.0), seq))
    sub.handleSample(_imu("temp", 25.0, seq))


def _subscriber(db: Any) -> EdrPersistenceSubscriber:
    """A subscriber that persists every burst (no decimation)."""
    return EdrPersistenceSubscriber(None, db, imuSampleHz=50, imuPersistHz=50)


def _rowCount(db: _ConnectCountingDatabase) -> int:
    """Row count read through the INNER database, so it does not skew the counter."""
    with db._inner.connect() as conn:  # noqa: SLF001 -- reading past the counter is the point
        return int(conn.execute("SELECT COUNT(*) FROM edr_imu_sample").fetchone()[0])


def test_persistingManyBurstsDoesNotOpenAConnectionPerRow(
    countingDb: _ConnectCountingDatabase,
) -> None:
    """ARCH-030: N persisted rows must not cost N SQLite connections.

    Connection-per-row is what made every close the last close, so SQLite
    checkpointed the whole database once per row. One reused connection is the
    fix; the guard is simply that connections must not scale with rows.
    """
    sub = _subscriber(countingDb)

    for seq in range(_BURSTS):
        _feedBurst(sub, seq)
    sub.stop()

    assert _rowCount(countingDb) == _BURSTS, "every burst must still be persisted"
    assert countingDb.connectCalls < _BURSTS, (
        f"opened {countingDb.connectCalls} connections for {_BURSTS} rows -- "
        "connection-per-row makes SQLite checkpoint the whole DB on every close"
    )


def test_rowsAreReadableImmediatelyAfterTheBurstIsPersisted(
    countingDb: _ConnectCountingDatabase,
) -> None:
    """A persisted EDR row must be committed and visible without waiting.

    The EDR is a black box: a row buffered but not committed is a row lost at
    the power cut this subsystem exists to record. Reusing a connection must not
    become 'batch it and hope'.
    """
    sub = _subscriber(countingDb)

    _feedBurst(sub, 0)

    assert _rowCount(countingDb) == 1, "the burst must be committed, not buffered"
    sub.stop()
