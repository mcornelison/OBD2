################################################################################
# File Name: test_drive_summary_sync_update_propagation.py
# Purpose/Description: Sprint 33 US-326 / I-026 regression test -- the server-side
#                      analytics writer (_ensureDriveSummary) must reconcile a
#                      Pi-synced drive_summary row in place, populating Spec 3
#                      fields 3-8 (start_time / end_time / duration_seconds /
#                      row_count / is_real / data_source) and healing the
#                      drive_id mirror column.  Pre-fix the writer looked the
#                      existing row up by drive_id -- a column the Pi-sync wire
#                      protocol never populates (it renames the Pi PK drive_id
#                      -> id -> source_id) -- so the lookup always missed a
#                      Pi-sync row, the writer fell into the INSERT branch, and
#                      it tripped UNIQUE(source_device, source_id), rolling the
#                      whole auto-analysis transaction back so the analytics
#                      fields stayed NULL (exactly the Drive 11 server row 15
#                      state PM observed 2026-05-12).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-12    | Rex (US-326) | Initial -- I-026 root-cause lock-in.
# ================================================================================
################################################################################

"""drive_summary sync-UPDATE / analytics-reconcile regression test (US-326 / I-026).

Why this exists
---------------

Drive 11 captured cleanly Pi-side (10,839 ``realtime_data`` rows) and the
Pi-sync pushed the ``drive_summary`` row to the server (``id=15``,
``source_id=11``).  But the server-side analytics fields stayed NULL:

    id=15, source_id=11, drive_id=NULL,
    start_time=NULL, end_time=NULL, duration_seconds=NULL,
    row_count=0, is_real=0,
    data_source='real', ambient_temp_at_start_c=18, starting_battery_v=14.5

Pre-flight (code archaeology -- server journalctl is a CIO/PM follow-up)
ruled out the "sync UPDATE not extended to drive_summary" hypothesis:
``drive_summary`` *is* in :data:`src.pi.data.sync_log.SYNC_UPDATE_TABLES_PK`
and the server's ``_upsertBatch`` already does ``on_duplicate_key_update``.
The real defect is in :func:`src.server.services.analysis._ensureDriveSummary`:
it looked the existing Pi-sync row up by ``drive_id``, but the Pi-sync wire
protocol renames the Pi PK ``drive_id`` -> ``id`` -> ``source_id`` (see
:func:`src.pi.sync.client._renamePkToId` + ``src.server.api.sync.runSyncUpsert``),
so a Pi-sync ``drive_summary`` row arrives with ``source_id=N`` and
``drive_id=NULL``.  The lookup-by-``drive_id`` therefore never found a Pi-sync
row, the writer took the INSERT branch, and the INSERT tripped
``UNIQUE(source_device, source_id)`` -> ``IntegrityError`` -> the auto-analysis
transaction rolled back -> analytics fields 3-8 stayed NULL.

The fix matches on the actual natural key (``source_id``, ``OR drive_id`` so
analytics-first INSERTed rows -- which set both -- are still found) and heals
the ``drive_id`` mirror column on the UPDATE path.

Discriminator
-------------

:meth:`TestEnsureDriveSummaryReconcilesPiSyncRow
.test_piSyncRowPresent_thenAnalyticsWriter_updatesFieldsInPlace` is RED against
pre-fix code (``IntegrityError`` on the duplicate-key INSERT) and GREEN once the
lookup matches ``source_id``.  If the lookup ever regresses to ``drive_id``-only
this test fires loudly.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.server.api.sync import runSyncUpsert
from src.server.db.models import Base, DriveSummary
from src.server.services.analysis import (
    SPEC3_MIN_ROWS_FOR_IS_REAL,
    _ensureDriveSummary,
)

# ================================================================================
# Fixtures / builders
# ================================================================================

_DEVICE = "chi-eclipse-01"
_DRIVE_ID = 11
_DRIVE_START = datetime(2026, 5, 12, 1, 0, 0)
# Enough realtime rows that the Spec 3 is_real ladder resolves to TRUE
# (>= SPEC3_MIN_ROWS_FOR_IS_REAL rows AND every row data_source='real').
_REALTIME_ROW_COUNT = SPEC3_MIN_ROWS_FOR_IS_REAL + 10
_REALTIME_STEP_SECONDS = 3
_DRIVE_END = _DRIVE_START + timedelta(
    seconds=(_REALTIME_ROW_COUNT - 1) * _REALTIME_STEP_SECONDS,
)


def _newServerEngine():
    """In-memory SQLite engine with the modern ORM-driven server schema."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _piRealtimeRows(driveId: int, *, count: int = _REALTIME_ROW_COUNT) -> list[dict]:
    """Pi-shape realtime_data rows for ``driveId``, spanning a contiguous window.

    Mirrors what ``SyncClient`` sends: each row carries the Pi-native ``id``
    (-> ``source_id`` server-side), an ISO ``timestamp``, ``drive_id`` (the
    column ``_computeDriveAnalytics`` joins on), and ``data_source='real'``.
    """
    rows: list[dict] = []
    for i in range(count):
        ts = _DRIVE_START + timedelta(seconds=i * _REALTIME_STEP_SECONDS)
        rows.append(
            {
                "id": i + 1,
                "timestamp": ts.isoformat(),
                "parameter_name": "RPM",
                "value": 2000.0 + i,
                "unit": "rpm",
                "profile_id": "daily",
                "drive_id": driveId,
                "data_source": "real",
            }
        )
    return rows


def _piDriveSummaryRow(driveId: int) -> dict:
    """Pi-shape drive_summary sync row -- the 6-column Pi schema on the wire.

    The Pi PK column ``drive_id`` is renamed to ``id`` by ``_renamePkToId``
    before transmission, so the wire row carries ``id`` (not ``drive_id``);
    ``runSyncUpsert`` maps that to ``source_id``.  The result server-side is
    ``source_id=driveId`` with the ``drive_id`` mirror column left NULL --
    the exact state that broke the analytics-writer lookup.
    """
    return {
        "id": driveId,
        "drive_start_timestamp": _DRIVE_START.isoformat() + "Z",
        "ambient_temp_at_start_c": 18.0,
        "starting_battery_v": 14.5,
        "barometric_kpa_at_start": 100.0,
        "data_source": "real",
    }


def _seedPiSync(
    session: Session,
    *,
    includeDriveSummary: bool,
    syncHistoryId: int = 1,
) -> None:
    """Run the real sync upsert with realtime_data (+ optional drive_summary)."""
    tables: dict[str, dict] = {
        "realtime_data": {"rows": _piRealtimeRows(_DRIVE_ID)},
    }
    if includeDriveSummary:
        tables["drive_summary"] = {"rows": [_piDriveSummaryRow(_DRIVE_ID)]}
    runSyncUpsert(
        session,
        deviceId=_DEVICE,
        batchId=f"batch-{syncHistoryId}",
        tables=tables,
        syncHistoryId=syncHistoryId,
    )


def _driveSummaryRows(session: Session) -> list[DriveSummary]:
    return list(session.execute(select(DriveSummary)).scalars().all())


def _runAnalyticsWriter(session: Session) -> int:
    """Invoke the analytics writer the way the auto-analysis trigger does."""
    return _ensureDriveSummary(
        session, _DEVICE, _DRIVE_START, _DRIVE_END, driveId=_DRIVE_ID,
    )


# ================================================================================
# 1) The I-026 bug: analytics writer must reconcile the Pi-sync row in place
# ================================================================================


class TestEnsureDriveSummaryReconcilesPiSyncRow:
    """``_ensureDriveSummary`` finds the Pi-sync row by ``source_id`` and UPDATEs it.

    Pre-fix the lookup used ``drive_id`` (NULL on Pi-sync rows) and the writer
    INSERTed a duplicate, tripping ``UNIQUE(source_device, source_id)``.
    """

    def test_piSyncRowPresent_thenAnalyticsWriter_updatesFieldsInPlace(self) -> None:
        engine = _newServerEngine()
        with Session(engine) as session:
            _seedPiSync(session, includeDriveSummary=True)
            session.commit()

        # Pre-condition: Pi-sync row exists with source_id set + analytics
        # fields NULL.  US-372: the sync path now mirrors source_id onto the
        # drive_id column (the pre-US-372 Drive-11 smell was drive_id NULL
        # here; that asymmetric state is now structurally impossible).
        with Session(engine) as session:
            rows = _driveSummaryRows(session)
            assert len(rows) == 1
            assert rows[0].source_id == _DRIVE_ID
            assert rows[0].drive_id == _DRIVE_ID
            assert rows[0].start_time is None
            assert rows[0].row_count in (None, 0)

        # Run the analytics writer (auto-analysis trigger's writer step).
        with Session(engine) as session:
            summaryId = _runAnalyticsWriter(session)
            session.commit()

        # Post-fix: the SAME row carries the analytics fields + a healed
        # drive_id, and the Pi-captured metadata is preserved (no second row).
        with Session(engine) as session:
            rows = _driveSummaryRows(session)
            assert len(rows) == 1, "analytics must UPDATE the Pi-sync row, not INSERT"
            row = rows[0]
            assert row.id == summaryId
            assert row.source_id == _DRIVE_ID
            assert row.drive_id == _DRIVE_ID, "drive_id mirror must be healed"
            assert row.start_time == _DRIVE_START
            assert row.end_time == _DRIVE_END
            assert row.duration_seconds == int(
                (_DRIVE_END - _DRIVE_START).total_seconds()
            )
            assert row.row_count == _REALTIME_ROW_COUNT
            assert row.is_real is True
            assert row.data_source == "real"
            assert row.device_id == _DEVICE
            # Pi-sync columns 9-12 untouched.
            assert row.ambient_temp_at_start_c == pytest.approx(18.0)
            assert row.starting_battery_v == pytest.approx(14.5)
            assert row.barometric_kpa_at_start == pytest.approx(100.0)

    def test_analyticsWriter_isIdempotentOnReRun(self) -> None:
        """Re-running the writer converges -- one row, same analytics values."""
        engine = _newServerEngine()
        with Session(engine) as session:
            _seedPiSync(session, includeDriveSummary=True)
            session.commit()

        with Session(engine) as session:
            firstId = _runAnalyticsWriter(session)
            session.commit()
        with Session(engine) as session:
            secondId = _runAnalyticsWriter(session)
            session.commit()

        assert firstId == secondId
        with Session(engine) as session:
            rows = _driveSummaryRows(session)
            assert len(rows) == 1
            row = rows[0]
            assert row.drive_id == _DRIVE_ID
            assert row.start_time == _DRIVE_START
            assert row.row_count == _REALTIME_ROW_COUNT
            assert row.is_real is True


# ================================================================================
# 2) Lock-in: the reverse order (analytics first, Pi-sync after) keeps working
# ================================================================================


class TestAnalyticsFirstThenPiSyncUpsert:
    """Analytics INSERTs the row; a later Pi-sync upserts onto it, preserving 3-8."""

    def test_analyticsFirst_thenPiSyncRow_analyticsPreserved(self) -> None:
        engine = _newServerEngine()

        # Analytics runs before the Pi-sync drive_summary row arrives (race /
        # out-of-order sync).  It INSERTs a fully-populated row keyed on
        # (source_device, source_id == drive_id).
        with Session(engine) as session:
            _seedPiSync(session, includeDriveSummary=False)  # realtime only
            session.commit()
        with Session(engine) as session:
            summaryId = _runAnalyticsWriter(session)
            session.commit()
        with Session(engine) as session:
            rows = _driveSummaryRows(session)
            assert len(rows) == 1
            assert rows[0].id == summaryId
            assert rows[0].source_id == _DRIVE_ID
            assert rows[0].drive_id == _DRIVE_ID
            assert rows[0].start_time == _DRIVE_START
            assert rows[0].ambient_temp_at_start_c is None  # not synced yet

        # Now the Pi-sync drive_summary row lands -- upserts onto the same row
        # via UNIQUE(source_device, source_id); analytics fields untouched.
        with Session(engine) as session:
            runSyncUpsert(
                session,
                deviceId=_DEVICE,
                batchId="batch-late-drive-summary",
                tables={"drive_summary": {"rows": [_piDriveSummaryRow(_DRIVE_ID)]}},
                syncHistoryId=2,
            )
            session.commit()

        with Session(engine) as session:
            rows = _driveSummaryRows(session)
            assert len(rows) == 1, "Pi-sync must land on the analytics row"
            row = rows[0]
            # Analytics fields 3-8 preserved.
            assert row.start_time == _DRIVE_START
            assert row.end_time == _DRIVE_END
            assert row.row_count == _REALTIME_ROW_COUNT
            assert row.is_real is True
            assert row.drive_id == _DRIVE_ID
            # Pi metadata now populated.
            assert row.ambient_temp_at_start_c == pytest.approx(18.0)
            assert row.starting_battery_v == pytest.approx(14.5)
