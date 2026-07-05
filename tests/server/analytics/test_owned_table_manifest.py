################################################################################
# File Name: test_owned_table_manifest.py
# Purpose/Description: US-449 / F-104 -- owned-table manifest + /analyze
#                      sole-writer proof.  Asserts (1) every persisted-analytics
#                      table is enumerated with one writer and analyze_writes
#                      False, and (2) the /analyze consumer path
#                      (_buildAnalyticsContext) writes NONE of them -- it reads
#                      harness drive_statistics and, on a miss, triggers the
#                      HARNESS compute; anomaly_log + trend_snapshots stay empty.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-449) | Initial -- BL-017 Atlas Option A: make the
#               |              | "harness is the sole writer / /analyze is a pure
#               |              | consumer" claim CHECKABLE (the bug was a second
#               |              | undetected live writer).  Behavioural proof +
#               |              | manifest structure + a source-scan of the
#               |              | /analyze context builder.
# ================================================================================
################################################################################

"""US-449 / F-104 -- owned-table manifest + /analyze sole-writer contract.

Two independent proofs that ``/analyze`` no longer dual-writes ``drive_statistics``
(the BL-017 bug) and writes no persisted-analytics table:

1. **Behavioural** -- seed a drive with drive-scoped raw ``realtime_data`` but
   NO pre-existing ``drive_statistics``; run ``_buildAnalyticsContext`` and
   assert the HARNESS populated ``drive_statistics`` (on-miss trigger) while
   ``anomaly_log`` + ``trend_snapshots`` stay EMPTY.
2. **Structural / source-scan** -- the manifest enumerates every table with one
   writer + ``analyze_writes=False``; the ``_buildAnalyticsContext`` source uses
   the harness compute + the pure evaluators, never the persisting writers.
"""

from __future__ import annotations

import inspect
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics.owned_tables import (  # noqa: E402
    ANALYZE_FORBIDDEN_WRITE_TABLES,
    PERSISTED_ANALYTICS_TABLES,
    harness_owned_tables,
    manifest_by_table,
)
from src.server.db.models import (  # noqa: E402
    AnomalyLog,
    Base,
    DriveStatistic,
    DriveSummary,
    RealtimeData,
    TrendSnapshot,
)
from src.server.services.analysis import _buildAnalyticsContext  # noqa: E402

# =========================================================================
# Fixtures + seeding
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


def _seedDriveScopedRaw(
    session: Session,
    *,
    driveId: int = 501,
    device: str = "chi-eclipse-01",
    sampleCount: int = 20,
) -> DriveSummary:
    """Seed a Pi-synced drive_summary + drive-scoped realtime_data (no stats)."""
    startTime = datetime(2026, 7, 4, 9, 0, 0)
    drive = DriveSummary(
        source_device=device,
        source_id=driveId,
        drive_id=driveId,
        device_id=device,
        data_source="real",
        start_time=startTime,
        end_time=startTime + timedelta(seconds=sampleCount),
        duration_seconds=sampleCount,
        row_count=sampleCount,
        is_real=True,
    )
    session.add(drive)
    session.flush()
    for i in range(sampleCount):
        session.add(
            RealtimeData(
                source_id=driveId * 1000 + i,
                source_device=device,
                timestamp=startTime + timedelta(seconds=i),
                parameter_name="RPM",
                value=2000.0 + i * 10.0,
                drive_id=driveId,
                data_source="real",
            )
        )
    session.commit()
    return drive


# =========================================================================
# Manifest structure
# =========================================================================


class TestOwnedTableManifest:
    """The manifest enumerates every persisted-analytics table honestly."""

    def test_everyTable_hasExactlyOneWriterField(self):
        for entry in PERSISTED_ANALYTICS_TABLES:
            assert entry.table
            assert entry.writer  # one writer identity per table
            assert entry.writer_ref

    def test_noTable_isWrittenByAnalyze(self):
        """The BL-017 contract: /analyze persists NONE of these tables."""
        for entry in PERSISTED_ANALYTICS_TABLES:
            assert entry.analyze_writes is False, (
                f"{entry.table} claims /analyze writes it -- BL-017 regression"
            )

    def test_forbiddenWriteTables_coverAllPersistedAnalytics(self):
        assert set(ANALYZE_FORBIDDEN_WRITE_TABLES) == {
            t.table for t in PERSISTED_ANALYTICS_TABLES
        }

    def test_harnessOwnsTheThreeComputeTables(self):
        assert set(harness_owned_tables()) == {
            "drive_summary",
            "drive_statistics",
            "drive_derived_signals",
        }

    def test_manifestTables_matchRealModelTablenames(self):
        """Grounding: every manifest table is a real ORM __tablename__."""
        realTables = set(Base.metadata.tables.keys())
        for table in manifest_by_table():
            assert table in realTables, (
                f"manifest names {table!r} but no ORM table has that name"
            )


# =========================================================================
# Behavioural sole-writer proof
# =========================================================================


class TestAnalyzeIsPureConsumer:
    """_buildAnalyticsContext reads harness stats + writes no owned table."""

    def test_onMiss_triggersHarness_populatesDriveStatistics(self, engine):
        with Session(engine) as session:
            drive = _seedDriveScopedRaw(session, driveId=501)

            # No drive_statistics exist yet.
            assert session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == drive.id
                )
            ).scalars().all() == []

            context = _buildAnalyticsContext(session, drive)
            session.commit()

            # The on-miss HARNESS compute populated drive_statistics.
            statRows = session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == drive.id
                )
            ).scalars().all()
            assert context is not None
            assert len(statRows) == 1
            assert statRows[0].parameter_name == "RPM"
            # data_quality is a harness-only column -- proves the HARNESS wrote
            # it (basic.computeDriveStatistics leaves data_quality NULL).
            assert statRows[0].data_quality is not None

    def test_analyze_writesNoAnomalyLogOrTrendSnapshots(self, engine):
        with Session(engine) as session:
            drive = _seedDriveScopedRaw(session, driveId=502)

            _buildAnalyticsContext(session, drive)
            session.commit()

            anomalies = session.execute(select(AnomalyLog)).scalars().all()
            snapshots = session.execute(select(TrendSnapshot)).scalars().all()
            assert anomalies == [], (
                "/analyze must not persist anomaly_log (uses evaluateAnomalies)"
            )
            assert snapshots == [], (
                "/analyze must not persist trend_snapshots (uses evaluateTrend)"
            )

    def test_noRealtime_shortCircuitsNoData_writesNothing(self, engine):
        """A drive with no raw rows → None (no data) and no owned-table writes."""
        with Session(engine) as session:
            startTime = datetime(2026, 7, 4, 9, 0, 0)
            drive = DriveSummary(
                source_device="chi-eclipse-01",
                source_id=777,
                drive_id=777,
                device_id="chi-eclipse-01",
                data_source="real",
                start_time=startTime,
                end_time=startTime,
                duration_seconds=0,
                row_count=0,
                is_real=False,
            )
            session.add(drive)
            session.commit()

            context = _buildAnalyticsContext(session, drive)
            session.commit()

            assert context is None
            assert session.execute(
                select(DriveStatistic)
            ).scalars().all() == []
            assert session.execute(select(AnomalyLog)).scalars().all() == []
            assert session.execute(select(TrendSnapshot)).scalars().all() == []


# =========================================================================
# Source-scan: the /analyze context builder uses the harness, not the writers
# =========================================================================


class TestAnalyzeContextBuilderSource:
    """Guardrail: the code shape can't silently regress to a dual-write."""

    def test_buildAnalyticsContext_usesHarnessAndPureEvaluators(self):
        src = inspect.getsource(_buildAnalyticsContext)
        # Triggers the harness compute on a miss + uses the pure evaluators.
        assert "compute_drive_statistics(" in src
        assert "evaluateAnomalies(" in src
        assert "evaluateTrend(" in src

    def test_buildAnalyticsContext_doesNotCallThePersistingWriters(self):
        src = inspect.getsource(_buildAnalyticsContext)
        # basic.computeDriveStatistics / detectAnomalies / computeTrends are the
        # persisting writers the BL-017 dual-write went through -- none may be
        # called from the /analyze context builder.
        assert "computeDriveStatistics(" not in src
        assert "detectAnomalies(" not in src
        assert "computeTrends(" not in src
