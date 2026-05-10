################################################################################
# File Name: test_backfill_orphan_drive_id.py
# Purpose/Description: US-311 / I-019 -- unit tests for the orphan-drive-id
#                      backfill CLI.  Pins the dry-run preview shape, the
#                      --execute behavior, the RPM-filter narrowing, and the
#                      idempotency invariant.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex (US-311) | Initial -- 4 tests cover the helper functions
#               |              | + 1 end-to-end CLI test through main().
# ================================================================================
################################################################################

"""Tests for ``scripts/backfill_orphan_drive_id.py``."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.backfill_orphan_drive_id import (
    DRY_RUN_SENTINEL_NAME,
    BackfillPlan,
    OrphanRow,
    applyBackfill,
    main,
    narrowToRpmWindows,
    scanOrphansInWindow,
)


def _seedRealtimeData(
    conn: sqlite3.Connection, rows: list[tuple[str, str, float, int | None]],
) -> None:
    """Seed the schema-light realtime_data fixture.

    Each row is ``(timestamp, parameter_name, value, drive_id)`` -- the
    columns the backfill script actually touches.
    """
    conn.execute(
        """
        CREATE TABLE realtime_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            parameter_name TEXT,
            value REAL,
            drive_id INTEGER,
            data_source TEXT DEFAULT 'real'
        )
        """,
    )
    conn.executemany(
        "INSERT INTO realtime_data (timestamp, parameter_name, value, drive_id) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()


@pytest.fixture()
def seededDb(tmp_path: Path) -> Path:
    """A tiny realtime_data seed mirroring the I-019 orphan window shape."""
    dbPath = tmp_path / "obd.db"
    conn = sqlite3.connect(str(dbPath))
    try:
        _seedRealtimeData(
            conn,
            [
                # Pre-window row (NULL drive_id, must NOT be touched).
                ('2026-05-09T23:30:00Z', 'BATTERY_V', 12.7, None),
                # Inside-window engine-off baseline (NULL, NO RPM).
                ('2026-05-09T23:45:00Z', 'BATTERY_V', 12.7, None),
                ('2026-05-09T23:50:00Z', 'BATTERY_V', 12.7, None),
                # Around-the-block driving (NULL, RPM > 500).
                ('2026-05-09T23:55:00Z', 'RPM', 800.0, None),
                ('2026-05-09T23:55:00Z', 'BATTERY_V', 14.4, None),
                ('2026-05-09T23:56:00Z', 'RPM', 1200.0, None),
                # Drive 9 already-tagged (non-NULL drive_id, must NOT be touched).
                ('2026-05-10T00:20:00Z', 'RPM', 700.0, 9),
            ],
        )
    finally:
        conn.close()
    return dbPath


class TestScanOrphansInWindow:
    """Window selection ignores rows outside [start, end] AND non-NULL ids."""

    def test_scan_returnsOnlyOrphanRowsInsideWindow(
        self, seededDb: Path,
    ) -> None:
        conn = sqlite3.connect(str(seededDb))
        try:
            rows = scanOrphansInWindow(
                conn,
                windowStart='2026-05-09T23:40:00Z',
                windowEnd='2026-05-10T00:16:00Z',
            )
        finally:
            conn.close()
        # 5 rows: 2 BATTERY_V baseline + 2 RPM + 1 BATTERY_V at-cycle.
        # Pre-window row (23:30) excluded; tagged Drive 9 row (00:20) excluded.
        assert len(rows) == 5
        timestamps = sorted({r.timestamp for r in rows})
        assert timestamps == [
            '2026-05-09T23:45:00Z',
            '2026-05-09T23:50:00Z',
            '2026-05-09T23:55:00Z',
            '2026-05-09T23:56:00Z',
        ]


class TestNarrowToRpmWindows:
    """RPM-filter keeps rows close to RPM>500 anchors only."""

    def test_narrow_keepsOnlyRowsBracketedByRpmAnchors(self) -> None:
        rows = [
            OrphanRow(rowId=1, timestamp='2026-05-09T23:45:00Z',
                      parameterName='BATTERY_V', value=12.7),
            OrphanRow(rowId=2, timestamp='2026-05-09T23:55:00Z',
                      parameterName='RPM', value=800.0),
            OrphanRow(rowId=3, timestamp='2026-05-09T23:55:00Z',
                      parameterName='BATTERY_V', value=14.4),
            OrphanRow(rowId=4, timestamp='2026-05-09T23:56:00Z',
                      parameterName='RPM', value=1200.0),
        ]
        kept = narrowToRpmWindows(rows)
        # The 23:45 BATTERY_V is far from any RPM anchor (10 min away);
        # dropped.  The 23:55 BATTERY_V is at the same instant as an
        # RPM anchor; kept.  The two RPM rows are themselves anchors;
        # both kept.
        keptIds = sorted(r.rowId for r in kept)
        assert keptIds == [2, 3, 4]

    def test_narrow_emptyWhenNoRpmAnchorsInWindow(self) -> None:
        rows = [
            OrphanRow(rowId=1, timestamp='2026-05-09T23:45:00Z',
                      parameterName='BATTERY_V', value=12.7),
            OrphanRow(rowId=2, timestamp='2026-05-09T23:50:00Z',
                      parameterName='BATTERY_V', value=12.7),
        ]
        assert narrowToRpmWindows(rows) == []


class TestApplyBackfill:
    """The UPDATE applier is idempotent and bounded to rows in the plan."""

    def test_apply_updatesEveryRowInThePlan(self, seededDb: Path) -> None:
        conn = sqlite3.connect(str(seededDb))
        try:
            allRows = scanOrphansInWindow(
                conn,
                windowStart='2026-05-09T23:40:00Z',
                windowEnd='2026-05-10T00:16:00Z',
            )
            plan = BackfillPlan(
                targetDriveId=11,
                windowStart='2026-05-09T23:40:00Z',
                windowEnd='2026-05-10T00:16:00Z',
                rpmFilterUsed=False,
                rowsToTag=allRows,
            )
            updated = applyBackfill(conn, plan)
            conn.commit()
        finally:
            conn.close()
        assert updated == len(allRows)

        # Re-scan: the same rows are no longer NULL, so a second run is
        # a 0-row no-op (idempotency).
        conn = sqlite3.connect(str(seededDb))
        try:
            secondScan = scanOrphansInWindow(
                conn,
                windowStart='2026-05-09T23:40:00Z',
                windowEnd='2026-05-10T00:16:00Z',
            )
            assert secondScan == []
            taggedCount = conn.execute(
                "SELECT COUNT(*) FROM realtime_data WHERE drive_id = 11",
            ).fetchone()[0]
            assert taggedCount == updated
            # Pre-window + tagged-Drive-9 rows are still untouched.
            preserved = conn.execute(
                "SELECT timestamp, drive_id FROM realtime_data "
                "WHERE id IN (SELECT MIN(id) FROM realtime_data) "
                "OR drive_id = 9",
            ).fetchall()
            assert preserved == [
                ('2026-05-09T23:30:00Z', None),
                ('2026-05-10T00:20:00Z', 9),
            ]
        finally:
            conn.close()


class TestCliMain:
    """End-to-end CLI invocations against a tmp DB."""

    def test_dryRun_writesSentinelAndDoesNotMutate(
        self, seededDb: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main([
            '--db', str(seededDb),
            '--target-drive-id', '11',
            '--start', '2026-05-09T23:40:00Z',
            '--end', '2026-05-10T00:16:00Z',
            '--dry-run',
        ])
        assert rc == 0
        captured = capsys.readouterr()
        assert 'DRY RUN' in captured.out
        assert 'rows_to_tag=5' in captured.out
        sentinel = seededDb.parent / DRY_RUN_SENTINEL_NAME
        assert sentinel.exists()

        # Verify the DB was NOT mutated.
        conn = sqlite3.connect(str(seededDb))
        try:
            untagged = conn.execute(
                "SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NULL "
                "AND timestamp >= '2026-05-09T23:40:00Z' "
                "AND timestamp <= '2026-05-10T00:16:00Z'",
            ).fetchone()[0]
        finally:
            conn.close()
        assert untagged == 5

    def test_execute_requiresPriorDryRunSentinel(
        self, seededDb: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main([
            '--db', str(seededDb),
            '--target-drive-id', '11',
            '--execute',
        ])
        assert rc == 2
        captured = capsys.readouterr()
        assert 'requires a prior successful --dry-run' in captured.err
