################################################################################
# File Name: test_edr_persist_utc_grid.py
# Purpose/Description: ARCH-064d -- IMU rows are persisted on a WALL-CLOCK UTC
#     grid of 1/persistHz seconds, not as every Nth burst. Keep-1-of-N made the
#     stored rate depend on the read loop's real speed: MEASURED on drive 96
#     (2026-09-30) at 1.62 Hz against a configured persistHz 2, because the loop
#     ran at 40.5 Hz, not 50. A grid also makes each stored row line up with the
#     whole-second ECU rows in realtime_data (CIO 2026-09-30: "easily matchable
#     or linked up to the ECM data"; record at 4, 2 or 1 Hz).
# Author: Atlas (ARCH-064d, CIO-directed build)
# Creation Date: 2026-09-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Persisted IMU cadence is exactly persistHz and aligned to UTC grid boundaries."""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

import pytest

from pi.bus.edr_persistence_subscriber import EdrPersistenceSubscriber
from pi.bus.sample import Sample
from pi.obdii.database import ObdDatabase

# A realistic, deliberately non-integer mono->UTC offset (boot happened at an
# arbitrary wall-clock instant), so a grid anchored to BOOT would be off-phase.
OFFSET_S = 1_790_800_000.3137


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "grid.db"), walMode=False)
    db.initialize()
    return db


def _burst(sub: EdrPersistenceSubscriber, seq: int, tsCapture: float) -> None:
    for field, value in (("accel", (0.0, 0.0, 9.8)), ("gyro", (0.0, 0.0, 0.0)),
                         ("mag", (1.0, 2.0, 3.0)), ("temp", 25.0)):
        sub.handleSample(Sample(
            topic=f"raw.imu.{field}", source="imu", value=value, unit="x",
            tsUtc="2026-09-30T20:28:08Z", tsCapture=tsCapture, driveId=None,
            dataSource="real", seq=seq,
        ))


def _stream(sub: EdrPersistenceSubscriber, periodS: float, seconds: float, t0: float = 90.0) -> None:
    n = int(seconds / periodS)
    for i in range(n):
        _burst(sub, seq=i + 1, tsCapture=t0 + i * periodS)
    sub.flushPending()


def _rows(db: ObdDatabase) -> list[tuple]:
    with db.connect() as conn:
        return conn.execute(
            "SELECT seq, ts_capture, accel_x, gyro_x, mag_x, temp_c FROM edr_imu_sample ORDER BY seq"
        ).fetchall()


def _sub(db: ObdDatabase, sampleHz: float, persistHz: float, **kw) -> EdrPersistenceSubscriber:
    return EdrPersistenceSubscriber(
        None, db, imuSampleHz=sampleHz, imuPersistHz=persistHz,
        wallClockOffsetFn=lambda: OFFSET_S, **kw,
    )


def _perUtcSecond(rows: list[tuple]) -> Counter:
    return Counter(math.floor(r[1] + OFFSET_S) for r in rows)


@pytest.mark.parametrize("persistHz", [1, 2, 4])
def test_exactlyPersistHzRowsInEveryFullUtcSecond(freshDb: ObdDatabase, persistHz: int) -> None:
    sub = _sub(freshDb, sampleHz=50, persistHz=persistHz)
    _stream(sub, periodS=0.020, seconds=12.0)
    counts = _perUtcSecond(_rows(freshDb))
    full = sorted(counts)[1:-1]  # drop the partial first/last seconds of the stream
    assert full and all(counts[s] == persistHz for s in full)


def test_slowLoopStillStoresExactlyPersistHz_theDrive96Case(freshDb: ObdDatabase) -> None:
    """At the MEASURED 24.72 ms loop, keep-1-of-25 stored 1.62 Hz. The grid stores 2."""
    sub = _sub(freshDb, sampleHz=50, persistHz=2)
    _stream(sub, periodS=0.02472, seconds=20.0)
    counts = _perUtcSecond(_rows(freshDb))
    full = sorted(counts)[1:-1]
    assert all(counts[s] == 2 for s in full)
    # the old rule on the same stream, for contrast (this is what the car did):
    assert 1.0 / (25 * 0.02472) == pytest.approx(1.618, abs=0.001)


def test_rowsSitOnTheUtcGrid_withinOneReadPeriod(freshDb: ObdDatabase) -> None:
    sub = _sub(freshDb, sampleHz=50, persistHz=2)
    _stream(sub, periodS=0.020, seconds=10.0)
    for _, tsCapture, *_ in _rows(freshDb)[1:]:  # the very first row may land mid-slot
        phase = (tsCapture + OFFSET_S) % 0.5
        assert phase < 0.020 + 1e-9  # the first read at/after each .0/.5 boundary


def test_wholeBurstIsKept_neverAPartialRow(freshDb: ObdDatabase) -> None:
    sub = _sub(freshDb, sampleHz=50, persistHz=2)
    _stream(sub, periodS=0.020, seconds=5.0)
    rows = _rows(freshDb)
    assert rows and all(None not in r for r in rows)


def test_persistAtOrAboveSampleRateKeepsEveryBurst(freshDb: ObdDatabase) -> None:
    sub = _sub(freshDb, sampleHz=4, persistHz=4)
    _stream(sub, periodS=0.25, seconds=3.0)
    assert len(_rows(freshDb)) == 12


def test_wallClockStepBackwards_losesNoRows(freshDb: ObdDatabase) -> None:
    """An NTP step moves the grid; it must never silence persistence."""
    offsets = iter([OFFSET_S] * 60 + [OFFSET_S - 30.0] * 60)
    sub = EdrPersistenceSubscriber(
        None, freshDb, imuSampleHz=50, imuPersistHz=2,
        wallClockOffsetFn=lambda: next(offsets),
    )
    for i in range(120):
        _burst(sub, seq=i + 1, tsCapture=90.0 + i * 0.02)
    sub.flushPending()
    assert len(_rows(freshDb)) >= 4  # both sides of the step still persisted


def test_derivedSiblingStaysOneToOneWithRaw(freshDb: ObdDatabase) -> None:
    snap = {"tsUtc": "2026-09-30T20:28:08Z", "tsCapture": 1.0, "seq": 1, "pitchDeg": 0.1,
            "stopCount": 0, "biasRad": 0.0, "fusionVersion": "t"}
    sub = _sub(freshDb, sampleHz=50, persistHz=2, derivedSnapshotFn=lambda: snap)
    _stream(sub, periodS=0.020, seconds=6.0)
    with freshDb.connect() as conn:
        raw = conn.execute("SELECT COUNT(*) FROM edr_imu_sample").fetchone()[0]
        derived = conn.execute("SELECT COUNT(*) FROM edr_imu_derived").fetchone()[0]
    assert raw == derived and raw > 0


def test_defaultOffsetMapsMonotonicToWallClock() -> None:
    import time

    from pi.bus.edr_persistence_subscriber import _wallClockOffsetS

    assert _wallClockOffsetS() == pytest.approx(time.time() - time.monotonic(), abs=0.05)
