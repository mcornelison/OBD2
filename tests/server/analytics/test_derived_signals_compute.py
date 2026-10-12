################################################################################
# File Name: test_derived_signals_compute.py
# Purpose/Description: Tests for src/server/analytics/derived_signals_compute.py
#                      -- US-436 / F-106 server-side per-drive derived motion
#                      signals (acceleration + estimated distance) from the
#                      existing SPEED realtime_data stream.  Mirrors the US-350 /
#                      US-351 compute-test discipline (in-memory SQLite + real
#                      ORM + real INSERTs; NO seam mocks) so a false-pass writer
#                      class cannot recur.  Pure-compute tests drive canned
#                      speed/time series (the validationCriteria gate); DB tests
#                      verify the row is written + queryable + idempotent.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-02    | Rex (US-436) | Initial -- F-106 derived signals (accel +
#               |              | estimated distance), server-side per-drive.
# ================================================================================
################################################################################

"""US-436 / F-106 tests for the derived-signals compute path.

Two layers, both real-code (post-I-040 discipline -- no compute-seam mocks):

* Pure ``computeDerivedSignals`` over canned ``(timestamp, speed_kmh)`` series
  -- the validationCriteria gate ("run the server analytics compute against a
  canned speed/time series").  Covers the divide-by-zero (dt<=0) and time-gap
  (dt>threshold) guards the AC calls out.
* ``compute_drive_derived_signals`` against an in-memory-file SQLite DB seeded
  with real ``drive_summary`` + ``realtime_data`` rows -- verifies the row is
  written, keyed on the server-side ``drive_summary.id``, idempotent on re-run,
  and gracefully skips drives with <2 SPEED samples.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics.derived_signals_compute import (  # noqa: E402
    SPEED_PARAMETER_NAME,
    DerivedSignals,
    compute_drive_derived_signals,
    computeDerivedSignals,
)
from src.server.db.models import (  # noqa: E402
    Base,
    DriveDerivedSignal,
    DriveSummary,
    RealtimeData,
)

# =========================================================================
# Fixtures
# =========================================================================

BASE_TS = datetime(2026, 6, 1, 12, 0, 0)


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


def _series(pairs: list[tuple[float, float]]) -> list[tuple[datetime, float]]:
    """Build a (timestamp, speed_kmh) series from (offset_seconds, kmh)."""
    return [(BASE_TS + timedelta(seconds=off), kmh) for off, kmh in pairs]


def _seedDriveSummary(session: Session, *, driveId: int) -> int:
    row = DriveSummary(
        source_device="chi-eclipse-01",
        source_id=driveId,
        drive_id=driveId,
        data_source="real",
    )
    session.add(row)
    session.flush()
    return row.id


def _seedSpeed(
    session: Session, *, driveId: int, pairs: list[tuple[float, float]],
    parameter: str = SPEED_PARAMETER_NAME,
) -> None:
    cursor = driveId * 100_000
    for i, (off, kmh) in enumerate(pairs):
        session.add(
            RealtimeData(
                source_id=cursor + i,
                source_device="chi-eclipse-01",
                timestamp=BASE_TS + timedelta(seconds=off),
                parameter_name=parameter,
                value=float(kmh),
                drive_id=driveId,
                data_source="real",
            )
        )


# =========================================================================
# Pure compute -- canned speed/time series (validationCriteria gate)
# =========================================================================


class TestComputeDerivedSignals:
    def test_constantSpeed_distanceCorrect_zeroAccel(self):
        # 36 km/h for 30 s -> 36 * (30/3600) = 0.3 km; no accel.
        signals = computeDerivedSignals(
            _series([(0, 36.0), (10, 36.0), (20, 36.0), (30, 36.0)])
        )
        assert signals is not None
        assert signals.estimated_distance_km == pytest.approx(0.3)
        assert signals.peak_acceleration_ms2 == pytest.approx(0.0)
        assert signals.peak_deceleration_ms2 == pytest.approx(0.0)
        assert signals.sample_count == 4
        assert signals.segment_count == 3
        assert signals.gap_skipped_count == 0

    def test_linearAcceleration_peakAccelMatches(self):
        # 0 -> 36 km/h in 1 s.  36 km/h = 10 m/s, over 1 s -> 10 m/s^2.
        signals = computeDerivedSignals(_series([(0, 0.0), (1, 36.0)]))
        assert signals is not None
        assert signals.peak_acceleration_ms2 == pytest.approx(10.0)
        # Only positive segment -> peak_deceleration is the same segment's accel.
        assert signals.peak_deceleration_ms2 == pytest.approx(10.0)

    def test_deceleration_negativePeakDecel(self):
        # 36 -> 0 km/h in 1 s -> -10 m/s^2.
        signals = computeDerivedSignals(_series([(0, 36.0), (1, 0.0)]))
        assert signals is not None
        assert signals.peak_deceleration_ms2 == pytest.approx(-10.0)

    def test_accelThenDecel_peaksAreExtremes(self):
        # 0 -> 36 (accel +10) -> 0 (decel -10) each over 1 s.
        signals = computeDerivedSignals(
            _series([(0, 0.0), (1, 36.0), (2, 0.0)])
        )
        assert signals is not None
        assert signals.peak_acceleration_ms2 == pytest.approx(10.0)
        assert signals.peak_deceleration_ms2 == pytest.approx(-10.0)
        assert signals.segment_count == 2

    def test_zeroDt_guarded_noCrash(self):
        # Duplicate timestamp -> that segment is skipped (divide-by-zero guard),
        # but the remaining valid segment still computes.
        series = [
            (BASE_TS, 10.0),
            (BASE_TS, 20.0),               # same instant as previous
            (BASE_TS + timedelta(seconds=1), 20.0),
        ]
        signals = computeDerivedSignals(series)
        assert signals is not None
        assert signals.sample_count == 3
        assert signals.segment_count == 1   # only the 1 s segment counted
        # Distance from the single valid segment: (20+20)/2 * (1/3600) km.
        assert signals.estimated_distance_km == pytest.approx(20.0 / 3600.0)

    def test_timeGap_excludedFromDistance_counted(self):
        # A 10-minute gap (> 300 s threshold) must NOT accrue distance at the
        # last speed, and is tallied in gap_skipped_count.
        signals = computeDerivedSignals(
            _series([(0, 36.0), (10, 36.0), (610, 36.0)])
        )
        assert signals is not None
        # Only the first 10 s segment counts: 36 * (10/3600) = 0.1 km.
        assert signals.estimated_distance_km == pytest.approx(0.1)
        assert signals.gap_skipped_count == 1
        assert signals.segment_count == 1

    def test_fewerThanTwoSamples_returnsNone(self):
        assert computeDerivedSignals([]) is None
        assert computeDerivedSignals(_series([(0, 42.0)])) is None

    def test_unsortedInput_sortedByTimestamp(self):
        ordered = computeDerivedSignals(_series([(0, 0.0), (1, 36.0)]))
        reversed_ = computeDerivedSignals(_series([(1, 36.0), (0, 0.0)]))
        assert ordered is not None and reversed_ is not None
        assert reversed_.estimated_distance_km == pytest.approx(
            ordered.estimated_distance_km
        )
        assert reversed_.peak_acceleration_ms2 == pytest.approx(
            ordered.peak_acceleration_ms2
        )

    def test_allSegmentsSkipped_distanceZero_peaksNone(self):
        # Two samples separated by a single > threshold gap -> no valid segment.
        signals = computeDerivedSignals(_series([(0, 40.0), (600, 40.0)]))
        assert signals is not None
        assert signals.estimated_distance_km == pytest.approx(0.0)
        assert signals.peak_acceleration_ms2 is None
        assert signals.peak_deceleration_ms2 is None
        assert signals.segment_count == 0
        assert signals.gap_skipped_count == 1

    def test_resultCarriesUnitStrings(self):
        signals = computeDerivedSignals(_series([(0, 10.0), (1, 10.0)]))
        assert isinstance(signals, DerivedSignals)
        assert signals.speed_unit == "km/h"
        assert signals.distance_unit == "km"
        assert signals.accel_unit == "m/s^2"


# =========================================================================
# DB integration -- compute_drive_derived_signals
# =========================================================================


class TestComputeDriveDerivedSignals:
    def test_writesRow_keyedOnSummaryId(self, engine):
        with Session(engine) as session:
            summaryId = _seedDriveSummary(session, driveId=40)
            _seedSpeed(
                session, driveId=40,
                pairs=[(0, 36.0), (10, 36.0), (20, 36.0), (30, 36.0)],
            )
            session.commit()

            returned = compute_drive_derived_signals(session, 40)
            session.commit()

            assert returned == summaryId
            row = session.get(DriveDerivedSignal, summaryId)
            assert row is not None
            assert row.estimated_distance_km == pytest.approx(0.3)
            assert row.sample_count == 4
            assert row.segment_count == 3
            assert row.speed_unit == "km/h"

    def test_idempotent_reRunReplaces(self, engine):
        with Session(engine) as session:
            _seedDriveSummary(session, driveId=41)
            _seedSpeed(session, driveId=41, pairs=[(0, 0.0), (1, 36.0)])
            session.commit()

            compute_drive_derived_signals(session, 41)
            session.commit()
            compute_drive_derived_signals(session, 41)
            session.commit()

            rows = session.execute(select(DriveDerivedSignal)).scalars().all()
            assert len(rows) == 1
            assert rows[0].peak_acceleration_ms2 == pytest.approx(10.0)

    def test_noSpeedRows_returnsNone_writesNothing(self, engine):
        with Session(engine) as session:
            _seedDriveSummary(session, driveId=42)
            # Only RPM, no SPEED.
            _seedSpeed(
                session, driveId=42, pairs=[(0, 800.0), (1, 900.0)],
                parameter="RPM",
            )
            session.commit()

            returned = compute_drive_derived_signals(session, 42)
            session.commit()

            assert returned is None
            rows = session.execute(select(DriveDerivedSignal)).scalars().all()
            assert rows == []

    def test_singleSpeedSample_returnsNone(self, engine):
        with Session(engine) as session:
            _seedDriveSummary(session, driveId=43)
            _seedSpeed(session, driveId=43, pairs=[(0, 55.0)])
            session.commit()

            assert compute_drive_derived_signals(session, 43) is None

    def test_noDriveSummary_returnsNone(self, engine):
        with Session(engine) as session:
            _seedSpeed(session, driveId=44, pairs=[(0, 0.0), (1, 36.0)])
            session.commit()

            assert compute_drive_derived_signals(session, 44) is None


# =========================================================================
# CLI wiring -- recompute_drive_analytics fires the derived-signals compute
# =========================================================================


class TestRecomputeCliWiring:
    def _runCli(self, monkeypatch, dbPath: str, argv: list[str]) -> int:
        from src.server.cli import recompute_drive_analytics as cli

        monkeypatch.setattr(
            cli, "_resolveSyncDatabaseUrl", lambda: f"sqlite:///{dbPath}",
        )
        return cli.main(argv)

    def test_cliWritesDerivedSignalsRow(self, monkeypatch):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        eng = create_engine(f"sqlite:///{tmp.name}")
        Base.metadata.create_all(eng)
        summaryId: int
        with Session(eng) as session:
            summaryId = _seedDriveSummary(session, driveId=50)
            _seedSpeed(
                session, driveId=50,
                pairs=[(0, 0.0), (1, 36.0), (2, 72.0)],
            )
            session.commit()

        rc = self._runCli(monkeypatch, tmp.name, ["--drive-id", "50"])
        assert rc == 0

        with Session(eng) as session:
            row = session.get(DriveDerivedSignal, summaryId)
            assert row is not None
            assert row.peak_acceleration_ms2 == pytest.approx(10.0)
        eng.dispose()
        Path(tmp.name).unlink(missing_ok=True)
