################################################################################
# File Name: test_overlap.py
# Purpose/Description: Tests for src/server/analytics/overlap.py --
#                      US-362 / F-107 server-side detect_overlapping_drives
#                      helper.  Detects drive_ids whose realtime_data time
#                      window intersects a given drive's window (the
#                      V0.27.18 dual-attribution tripwire's SSOT detector).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-362) | Initial -- F-107 server-side overlap detector.
#               |              | Pure query helper over raw realtime_data (B-104
#               |              | Step 1 raw-signal authority); no DB writes.
# ================================================================================
################################################################################

"""US-362 / F-107 tests for ``detect_overlapping_drives``.

The helper is the SSOT overlap detector consumed by US-363's
``data_quality='attribution_anomaly'`` tripwire and US-364's backfill.
It reads each drive's ``[min(timestamp), max(timestamp)]`` window from
raw ``realtime_data`` (raw-signal authority per B-104 Step 1, never the
derived ``drive_summary`` rows) and returns the sorted set of other
``drive_id``s whose window intersects the target by any whole second.

Test discipline (post-I-040 lesson)
-----------------------------------

* No mocks of the helper's seams.  Tests use a real in-memory SQLite
  engine + the real ORM models + real INSERTs of synthetic
  ``realtime_data`` rows.
* The helper is exercised against the populated DB and the returned
  drive_id list is asserted directly.
* The V0.27.18 production overlap (drives 23+24, same physical leg) is
  replicated from F-107 description constants per US-362 conditionalOutcome
  (raw 23/24 telemetry not on the dev box).
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics.overlap import detect_overlapping_drives  # noqa: E402
from src.server.db.models import Base, RealtimeData  # noqa: E402

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def engine():
    """Temp-file SQLite engine carrying the full server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _seedDrive(
    session: Session,
    *,
    driveId: int | None,
    startTime: datetime,
    endTime: datetime,
    device: str = "chi-eclipse-01",
    pollIntervalSeconds: int = 1,
) -> int:
    """Seed ``realtime_data`` RPM rows for a drive across [start, end].

    Writes one RPM row per ``pollIntervalSeconds`` from ``startTime`` to
    ``endTime`` inclusive, so the drive's MIN/MAX ``timestamp`` window is
    exactly ``[startTime, endTime]``.  Returns the number of rows written.
    """
    total = 0
    # source_id must be unique; carve a per-drive numeric lane.
    lane = (driveId if driveId is not None else 9999) * 1_000_000
    sourceId = lane
    ts = startTime
    while ts <= endTime:
        session.add(
            RealtimeData(
                source_id=sourceId,
                source_device=device,
                timestamp=ts,
                parameter_name="RPM",
                value=2000.0,
                drive_id=driveId,
                data_source="real",
            )
        )
        sourceId += 1
        total += 1
        ts = ts + timedelta(seconds=pollIntervalSeconds)
    session.commit()
    return total


# =========================================================================
# Core: pairwise overlap, no-overlap, transitive (validationCriteria V-1..3)
# =========================================================================


class TestDetectOverlappingDrives:
    """detect_overlapping_drives returns the sorted set of intersecting ids."""

    def test_pairwiseOverlap_drives23and24_returns24(self, engine):
        """V-1: drives 23+24 (same physical leg, V0.27.18 dual-attribution).

        Replicates the F-107 overlap window: two drive_ids minted for one
        physical leg, their realtime_data windows heavily intersecting.
        """
        base = datetime(2026, 5, 22, 14, 43, 0)
        with Session(engine) as session:
            # Drive 23: 14:43:00 .. 14:45:00
            _seedDrive(
                session, driveId=23,
                startTime=base, endTime=base + timedelta(minutes=2),
            )
            # Drive 24: 14:44:00 .. 14:46:00 (overlaps 23 by ~1 minute)
            _seedDrive(
                session, driveId=24,
                startTime=base + timedelta(minutes=1),
                endTime=base + timedelta(minutes=3),
            )

            assert detect_overlapping_drives(session, 23) == [24]

    def test_noOverlap_drive25_returnsEmpty(self, engine):
        """V-2: drive 25 + a clearly-separated neighbor -> []."""
        base = datetime(2026, 5, 23, 15, 0, 0)
        with Session(engine) as session:
            # Drive 25: 15:00:00 .. 15:05:00
            _seedDrive(
                session, driveId=25,
                startTime=base, endTime=base + timedelta(minutes=5),
            )
            # Drive 26: 15:06:00 .. 15:10:00 (1-minute gap -- no shared second)
            _seedDrive(
                session, driveId=26,
                startTime=base + timedelta(minutes=6),
                endTime=base + timedelta(minutes=10),
            )

            assert detect_overlapping_drives(session, 25) == []

    def test_threeWayOverlap_isPairwiseAndSorted(self, engine):
        """V-3: 3-way overlap cluster (drives 30/31/32), order-insensitive.

        30: 12:00..12:10, 31: 12:05..12:15, 32: 12:08..12:20 -- every pair
        shares at least one second.
        """
        base = datetime(2026, 5, 24, 12, 0, 0)
        with Session(engine) as session:
            _seedDrive(
                session, driveId=30,
                startTime=base, endTime=base + timedelta(minutes=10),
            )
            _seedDrive(
                session, driveId=31,
                startTime=base + timedelta(minutes=5),
                endTime=base + timedelta(minutes=15),
            )
            _seedDrive(
                session, driveId=32,
                startTime=base + timedelta(minutes=8),
                endTime=base + timedelta(minutes=20),
            )

            assert detect_overlapping_drives(session, 30) == [31, 32]
            assert detect_overlapping_drives(session, 31) == [30, 32]
            assert detect_overlapping_drives(session, 32) == [30, 31]


# =========================================================================
# Boundary + degenerate cases
# =========================================================================


class TestDetectOverlappingDrivesBoundary:
    """Per-second semantics, missing data, and NULL drive_id handling."""

    def test_sharedBoundarySecond_countsAsOverlap(self, engine):
        """'any second of overlap = match': touching at one second -> overlap."""
        base = datetime(2026, 5, 24, 10, 0, 0)
        with Session(engine) as session:
            # Drive 40 ends exactly when drive 41 starts (10:05:00 shared).
            _seedDrive(
                session, driveId=40,
                startTime=base, endTime=base + timedelta(minutes=5),
            )
            _seedDrive(
                session, driveId=41,
                startTime=base + timedelta(minutes=5),
                endTime=base + timedelta(minutes=10),
            )

            assert detect_overlapping_drives(session, 40) == [41]

    def test_oneSecondGap_isNotOverlap(self, engine):
        """A 1-second gap means no shared second -> no overlap."""
        base = datetime(2026, 5, 24, 10, 0, 0)
        with Session(engine) as session:
            # Drive 42 ends 10:05:00; drive 43 starts 10:05:01.
            _seedDrive(
                session, driveId=42,
                startTime=base, endTime=base + timedelta(minutes=5),
            )
            _seedDrive(
                session, driveId=43,
                startTime=base + timedelta(minutes=5, seconds=1),
                endTime=base + timedelta(minutes=10),
            )

            assert detect_overlapping_drives(session, 42) == []

    def test_subSecondSameSecond_countsAsOverlap(self, engine):
        """Sub-second timestamps within the same whole second still overlap.

        Drive 50 last reading 10:05:00.200; drive 51 first reading
        10:05:00.800 -- a naive endpoint compare would miss it, but both
        fall in second 10:05:00, so per-second intersection matches.
        """
        base = datetime(2026, 5, 24, 10, 0, 0)
        with Session(engine) as session:
            session.add_all([
                RealtimeData(
                    source_id=50_000_001, source_device="chi-eclipse-01",
                    timestamp=base, parameter_name="RPM", value=2000.0,
                    drive_id=50, data_source="real",
                ),
                RealtimeData(
                    source_id=50_000_002, source_device="chi-eclipse-01",
                    timestamp=base.replace(minute=5, microsecond=200_000),
                    parameter_name="RPM", value=2000.0,
                    drive_id=50, data_source="real",
                ),
                RealtimeData(
                    source_id=51_000_001, source_device="chi-eclipse-01",
                    timestamp=base.replace(minute=5, microsecond=800_000),
                    parameter_name="RPM", value=2000.0,
                    drive_id=51, data_source="real",
                ),
                RealtimeData(
                    source_id=51_000_002, source_device="chi-eclipse-01",
                    timestamp=base.replace(minute=10), parameter_name="RPM",
                    value=2000.0, drive_id=51, data_source="real",
                ),
            ])
            session.commit()

            assert detect_overlapping_drives(session, 50) == [51]

    def test_targetDriveHasNoRows_returnsEmpty(self, engine):
        """Target drive with zero realtime_data rows -> [] (no window)."""
        base = datetime(2026, 5, 24, 9, 0, 0)
        with Session(engine) as session:
            _seedDrive(
                session, driveId=60,
                startTime=base, endTime=base + timedelta(minutes=5),
            )

            assert detect_overlapping_drives(session, 999) == []

    def test_nullDriveIdRows_areIgnored(self, engine):
        """Rows with NULL drive_id (pre-US-200 / outside a drive) are skipped."""
        base = datetime(2026, 5, 24, 8, 0, 0)
        with Session(engine) as session:
            _seedDrive(
                session, driveId=70,
                startTime=base, endTime=base + timedelta(minutes=5),
            )
            # NULL drive_id rows overlapping drive 70's window in wall time.
            _seedDrive(
                session, driveId=None,
                startTime=base, endTime=base + timedelta(minutes=5),
            )

            assert detect_overlapping_drives(session, 70) == []

    def test_isPureQuery_noDbWrites(self, engine):
        """Idempotency / purity: helper writes nothing (row count unchanged)."""
        base = datetime(2026, 5, 24, 7, 0, 0)
        with Session(engine) as session:
            before = _seedDrive(
                session, driveId=80,
                startTime=base, endTime=base + timedelta(minutes=2),
            )
            before += _seedDrive(
                session, driveId=81,
                startTime=base + timedelta(minutes=1),
                endTime=base + timedelta(minutes=3),
            )

            detect_overlapping_drives(session, 80)
            detect_overlapping_drives(session, 80)

            from sqlalchemy import func, select
            after = int(session.execute(
                select(func.count()).select_from(RealtimeData)
            ).scalar_one())
            assert after == before


# =========================================================================
# Docstring contract (validationCriteria V-4)
# =========================================================================


def test_docstring_statesPerSecondAndEpsilonZero():
    """V-4: docstring states strict per-second intersection + ε=0 default."""
    doc = detect_overlapping_drives.__doc__ or ""
    lowered = doc.lower()
    assert "second" in lowered
    # ε=0 default call-out present (accept the unicode or the spelled form).
    assert ("ε=0" in doc) or ("epsilon" in lowered and "0" in doc)
