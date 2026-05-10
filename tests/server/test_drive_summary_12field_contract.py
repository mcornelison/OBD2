################################################################################
# File Name: test_drive_summary_12field_contract.py
# Purpose/Description: US-310 / B-059 -- Spec 3 12-field drive_summary writer
#                      contract enforcement.  Spool's consumer-facing contract
#                      defines what fields 3-8 (start_time / end_time /
#                      duration_seconds / row_count / is_real / data_source)
#                      must hold post-analytics-run.  Tests would FAIL against
#                      pre-V0.27.3 _ensureDriveSummary which hardcoded
#                      is_real=True, used connection_log boundaries instead of
#                      realtime_data MIN/MAX, and never computed data_source.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex (US-310) | Initial -- TDD lock-in for Spec 3 12-field
#               |              | contract per B-059 + race / insufficient-data /
#               |              | stub-row semantics.
# ================================================================================
################################################################################

"""Spec 3 12-field drive_summary writer contract tests (US-310 / B-059).

Why this file exists
--------------------

Spool's 2026-05-09 Spec 3 freezes the 12-field drive_summary contract from
the tuner consumer's perspective.  Pi-sync writes fields 1+2+9-12 (key +
cold-start metadata).  The server analytics writer
(:func:`src.server.services.analysis._ensureDriveSummary`) is responsible
for fields 3-8 (start_time / end_time / duration_seconds / row_count /
is_real / data_source) -- derived from ``realtime_data``.

Pre-V0.27.3 production state (per Spool housekeeping Item 2 + drives 3+4+5
DB evidence) shows fields 3-8 sitting NULL on every Pi-sync-only row even
after analytics should have fired.  Drive 6+7 (post-V0.27.1) had no rows
at all because the broader US-304 regression blocked them; that's fixed.
This story closes the SECOND layer: the analytics writer itself.

The pre-fix ``_ensureDriveSummary`` hardcoded ``is_real=True`` regardless
of data quality, sourced ``start_time`` / ``end_time`` from the
``connection_log`` boundary timestamps (not ``realtime_data``), and never
computed ``data_source`` at all.  Each test below is a discriminator
against one of those pre-fix behaviors.

Test discriminators
-------------------

* :class:`TestRowCountThresholds` -- Spec 3's insufficient-data + stub-row
  semantics.  Pre-fix is_real=True regardless; post-fix follows the spec
  (row_count<100 -> NULL; row_count=0 -> FALSE stub).
* :class:`TestStartEndDerivation` -- Spec 3 says ``start_time`` is the
  MIN(realtime_data.timestamp) for the drive, not the connection_log
  drive_start.  Pre-fix sourced these from the connection_log boundary;
  post-fix derives from realtime_data.
* :class:`TestDataSourceMode` -- Spec 3's data_source = mode of
  realtime_data rows.  Pre-fix never wrote it.
* :class:`TestRaceSemantics` -- Pi-sync fields 9-12 must be preserved
  on analytics UPDATE.  Analytics-first INSERT must leave them NULL so
  later Pi-sync UPSERT lands on the same row.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.db.models import Base, DriveSummary, RealtimeData  # noqa: E402
from src.server.services.analysis import _ensureDriveSummary  # noqa: E402

# ==============================================================================
# Fixtures + helpers
# ==============================================================================


DEVICE = "chi-eclipse-01"
DRIVE_ID = 11
START = datetime(2026, 5, 11, 10, 0, 0)
END = datetime(2026, 5, 11, 10, 15, 0)


@pytest.fixture
def session() -> Session:
    """In-memory SQLite session with all server tables materialised."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()


def _insertPiSyncRow(
    session: Session,
    *,
    driveId: int = DRIVE_ID,
    deviceId: str = DEVICE,
    driveStartTs: datetime | None = START,
) -> int:
    """Mirror the Pi-sync first-write shape: fields 1+2+9-12 set, 3-8 NULL."""
    row = DriveSummary(
        source_device=deviceId,
        source_id=driveId,
        drive_id=driveId,
        drive_start_timestamp=driveStartTs,
        ambient_temp_at_start_c=18.5,
        starting_battery_v=12.7,
        barometric_kpa_at_start=100.2,
        data_source="real",
    )
    session.add(row)
    session.flush()
    return row.id


def _seedRealtime(
    session: Session,
    *,
    driveId: int,
    mix: dict[str, int],
    baseTs: datetime = START,
) -> int:
    """Seed realtime_data rows under the given (drive_id, data_source) mix.

    ``mix`` maps each data_source value to the number of rows to insert.
    Total row count is the sum across all keys.  Timestamps stride 1
    second so MIN/MAX derivations are deterministic and ``end_time -
    start_time == count - 1`` seconds.
    """
    counter = 0
    for src, n in mix.items():
        for _ in range(n):
            session.add(RealtimeData(
                source_device=DEVICE,
                source_id=counter + 1,
                timestamp=baseTs + timedelta(seconds=counter),
                parameter_name="RPM",
                value=2000.0 + counter,
                data_source=src,
                drive_id=driveId,
            ))
            counter += 1
    session.flush()
    return counter


# ==============================================================================
# Field 7 (is_real) + field 6 (row_count) -- Spec 3 thresholds
# ==============================================================================


class TestRowCountThresholds:
    """Spec 3: row_count<100 -> is_real=NULL; row_count=0 -> stub w/ is_real=FALSE."""

    def test_above100Rows_allReal_isRealTrue(self, session):
        """Happy path: >=100 rows, all 'real' -> is_real=TRUE."""
        _insertPiSyncRow(session)
        _seedRealtime(session, driveId=DRIVE_ID, mix={"real": 150})
        session.commit()

        _ensureDriveSummary(session, DEVICE, START, END, driveId=DRIVE_ID)
        session.commit()

        row = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == DRIVE_ID),
        ).scalar_one()
        assert row.row_count == 150
        assert row.is_real is True

    def test_below100Rows_isRealNull_perSpec(self, session):
        """Spec 3 insufficient-data: row_count<100 -> is_real=NULL.

        Pre-fix _ensureDriveSummary hardcoded is_real=True regardless;
        this test discriminates the spec change.  ``row_count<100 OR
        is_real IS NULL`` is Spool's grading-skip predicate.
        """
        _insertPiSyncRow(session)
        _seedRealtime(session, driveId=DRIVE_ID, mix={"real": 50})
        session.commit()

        _ensureDriveSummary(session, DEVICE, START, END, driveId=DRIVE_ID)
        session.commit()

        row = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == DRIVE_ID),
        ).scalar_one()
        assert row.row_count == 50
        # Spec 3: row_count<100 -> NULL ("skipped"), distinct from FALSE.
        assert row.is_real is None

    def test_zeroRealtime_stubRow_isRealFalse(self, session):
        """Spec 3 stub-row: no realtime_data -> is_real=FALSE, stats NULL.

        Pre-fix wrote start_time / end_time from the connection_log
        boundary regardless of realtime_data presence; post-fix derives
        from realtime_data and writes a stub row when none exists.
        """
        _insertPiSyncRow(session)
        session.commit()

        _ensureDriveSummary(session, DEVICE, START, END, driveId=DRIVE_ID)
        session.commit()

        row = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == DRIVE_ID),
        ).scalar_one()
        # Stub-row stats columns NULL (no realtime_data to derive from).
        assert row.start_time is None
        assert row.end_time is None
        assert row.duration_seconds is None
        assert row.row_count == 0
        # is_real=FALSE distinguishes "data capture failed, escalate"
        # from is_real=NULL ("skipped, ungradable").
        assert row.is_real is False
        # data_source NULL when no rows to derive mode from.
        assert row.data_source is None


# ==============================================================================
# Fields 3 + 4 + 5 -- start_time / end_time / duration_seconds derivation
# ==============================================================================


class TestStartEndDerivation:
    """Spec 3: start_time = MIN(realtime_data.timestamp); end_time = MAX."""

    def test_startEndDerivedFromRealtimeNotConnectionLog(self, session):
        """Pre-fix wrote connection_log boundaries; post-fix uses realtime MIN/MAX.

        The connection_log drive_start fires at cranking entry; the first
        actual realtime_data row arrives some milliseconds later when
        OBD polling kicks in.  Spec 3 frames start_time as "first
        realtime_data row" so analytics consumers can JOIN by drive_id
        and trust the boundary.
        """
        _insertPiSyncRow(session)
        # Realtime rows start 30s AFTER the connection_log drive_start
        # boundary -- pre-fix would write START; post-fix writes
        # START + 30s.
        realtimeStart = START + timedelta(seconds=30)
        _seedRealtime(
            session,
            driveId=DRIVE_ID,
            mix={"real": 100},
            baseTs=realtimeStart,
        )
        session.commit()

        _ensureDriveSummary(session, DEVICE, START, END, driveId=DRIVE_ID)
        session.commit()

        row = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == DRIVE_ID),
        ).scalar_one()
        assert row.start_time == realtimeStart
        assert row.end_time == realtimeStart + timedelta(seconds=99)
        # Duration is end - start (in seconds).
        assert row.duration_seconds == 99


# ==============================================================================
# Field 8 -- data_source mode
# ==============================================================================


class TestDataSourceMode:
    """Spec 3: data_source = dominant value across realtime_data rows."""

    def test_allReal_dataSourceMode_isReal(self, session):
        _insertPiSyncRow(session)
        _seedRealtime(session, driveId=DRIVE_ID, mix={"real": 100})
        session.commit()

        _ensureDriveSummary(session, DEVICE, START, END, driveId=DRIVE_ID)
        session.commit()

        row = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == DRIVE_ID),
        ).scalar_one()
        assert row.data_source == "real"

    def test_mixedMostlyReal_isRealTrue(self, session):
        """Spec 3: real_fraction > 95% -> is_real=TRUE; data_source = mode."""
        _insertPiSyncRow(session)
        _seedRealtime(
            session,
            driveId=DRIVE_ID,
            mix={"real": 96, "replay": 4},
        )
        session.commit()

        _ensureDriveSummary(session, DEVICE, START, END, driveId=DRIVE_ID)
        session.commit()

        row = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == DRIVE_ID),
        ).scalar_one()
        assert row.row_count == 100
        # 96/100 = 96% > 95% threshold -> TRUE.
        assert row.is_real is True
        # Mode is 'real' (96 vs 4).
        assert row.data_source == "real"

    def test_mixedMostlyReplay_isRealFalse_modeReplay(self, session):
        """Spec 3: real_fraction <= 95% -> is_real=FALSE; mode reflects majority."""
        _insertPiSyncRow(session)
        _seedRealtime(
            session,
            driveId=DRIVE_ID,
            mix={"real": 30, "replay": 70},
        )
        session.commit()

        _ensureDriveSummary(session, DEVICE, START, END, driveId=DRIVE_ID)
        session.commit()

        row = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == DRIVE_ID),
        ).scalar_one()
        assert row.row_count == 100
        assert row.is_real is False
        # Mode is 'replay' (70 vs 30).
        assert row.data_source == "replay"


# ==============================================================================
# Race semantics -- Pi-first / analytics-first / preserve-on-update
# ==============================================================================


class TestRaceSemantics:
    """Spec 3: Pi-sync columns are authoritative; analytics writes 3-8 only."""

    def test_piFirstUpdate_preservesFields9to12(self, session):
        """Analytics UPDATE must not clobber Pi-sync fields 9-12."""
        _insertPiSyncRow(session)
        _seedRealtime(session, driveId=DRIVE_ID, mix={"real": 100})
        session.commit()

        _ensureDriveSummary(session, DEVICE, START, END, driveId=DRIVE_ID)
        session.commit()

        row = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == DRIVE_ID),
        ).scalar_one()
        # Fields 9-12 untouched by analytics.
        assert row.drive_start_timestamp == START
        assert row.ambient_temp_at_start_c == pytest.approx(18.5)
        assert row.starting_battery_v == pytest.approx(12.7)
        assert row.barometric_kpa_at_start == pytest.approx(100.2)
        # Fields 3-8 derived from realtime.
        assert row.row_count == 100
        assert row.is_real is True

    def test_analyticsFirst_insertLeavesFields9to12Null(self, session):
        """Race: analytics fires before Pi-sync.  9-12 must stay NULL.

        Spec 3: analytics-first INSERT writes 1+2+3-8; later Pi-sync
        UPSERT by (source_device, source_id) lands on the same row and
        only overwrites NULLs in its own columns (9-12).
        """
        # No Pi-sync row yet.
        _seedRealtime(session, driveId=DRIVE_ID, mix={"real": 100})
        session.commit()

        _ensureDriveSummary(session, DEVICE, START, END, driveId=DRIVE_ID)
        session.commit()

        row = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == DRIVE_ID),
        ).scalar_one()
        # 1+2 set so the later Pi-sync upsert finds this row.
        assert row.source_device == DEVICE
        assert row.source_id == DRIVE_ID
        assert row.drive_id == DRIVE_ID
        # 3-8 derived from realtime.
        assert row.row_count == 100
        assert row.is_real is True
        # 9-12 NULL until Pi-sync arrives.
        assert row.drive_start_timestamp is None
        assert row.ambient_temp_at_start_c is None
        assert row.starting_battery_v is None
        assert row.barometric_kpa_at_start is None


# ==============================================================================
# Backfill script -- idempotent + dry-run preview
# ==============================================================================


class TestBackfillScript:
    """``scripts.backfill_drive_summary_analytics_fields.backfill`` populates 3-8."""

    def test_backfill_populatesFields3to8_forPiSyncOnlyRows(self, session):
        """Drives 3-10 use case: Pi-sync rows exist with NULL analytics cols."""
        from scripts.backfill_drive_summary_analytics_fields import backfill

        _insertPiSyncRow(session, driveId=3)
        _seedRealtime(session, driveId=3, mix={"real": 200})
        session.commit()

        # Pre-backfill: analytics cols NULL.
        row = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == 3),
        ).scalar_one()
        assert row.row_count is None or row.row_count == 0
        assert row.is_real is None or row.is_real is False

        stats = backfill(session, deviceId=DEVICE, dryRun=False)
        session.commit()

        assert stats.populated == 1
        row = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == 3),
        ).scalar_one()
        assert row.row_count == 200
        assert row.is_real is True

    def test_backfill_idempotent_doesNotTouchAlreadyPopulated(self, session):
        """Spec invariant: backfill must not modify rows with populated 3-8."""
        from scripts.backfill_drive_summary_analytics_fields import backfill

        _insertPiSyncRow(session, driveId=3)
        _seedRealtime(session, driveId=3, mix={"real": 200})
        session.commit()

        first = backfill(session, deviceId=DEVICE, dryRun=False)
        session.commit()
        second = backfill(session, deviceId=DEVICE, dryRun=False)
        session.commit()

        assert first.populated == 1
        assert second.populated == 0
        assert second.skipped >= 1

    def test_backfill_dryRun_makesNoChanges(self, session):
        from scripts.backfill_drive_summary_analytics_fields import backfill

        _insertPiSyncRow(session, driveId=3)
        _seedRealtime(session, driveId=3, mix={"real": 200})
        session.commit()

        before = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == 3),
        ).scalar_one()
        beforeRowCount = before.row_count

        stats = backfill(session, deviceId=DEVICE, dryRun=True)

        # Dry-run reports what WOULD happen but commits nothing.
        assert stats.populated == 1
        after = session.execute(
            select(DriveSummary).where(DriveSummary.drive_id == 3),
        ).scalar_one()
        assert after.row_count == beforeRowCount
