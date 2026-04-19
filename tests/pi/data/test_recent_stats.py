################################################################################
# File Name: test_recent_stats.py
# Purpose/Description: Unit tests for recent-drive min/max query helper (US-165)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-165
# ================================================================================
################################################################################
"""Unit tests for ``src/pi/data/recent_stats.py``."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from pi.data.recent_stats import queryRecentMinMax
from pi.display.screens.primary_screen_advanced import GaugeHistory


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """In-memory SQLite with just the statistics table shape we need."""
    c = sqlite3.connect(":memory:")
    c.execute(
        """
        CREATE TABLE statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parameter_name TEXT NOT NULL,
            analysis_date DATETIME NOT NULL,
            profile_id TEXT NOT NULL,
            max_value REAL,
            min_value REAL,
            avg_value REAL,
            mode_value REAL,
            std_1 REAL,
            std_2 REAL,
            outlier_min REAL,
            outlier_max REAL,
            sample_count INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    yield c
    c.close()


def _insertStats(
    conn: sqlite3.Connection,
    paramName: str,
    rows: list[tuple[float, float, datetime]],
) -> None:
    """Insert (min_value, max_value, analysis_date) rows for a parameter."""
    for minV, maxV, dt in rows:
        conn.execute(
            """
            INSERT INTO statistics(parameter_name, analysis_date, profile_id,
                                   min_value, max_value, sample_count)
            VALUES (?, ?, 'default', ?, ?, 100)
            """,
            (paramName, dt.isoformat(), minV, maxV),
        )
    conn.commit()


def _dt(offsetDays: int) -> datetime:
    """Return now - N days as a timezone-aware UTC datetime."""
    return datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC) - timedelta(days=offsetDays)


# ================================================================================
# Happy path
# ================================================================================


class TestQueryRecentMinMax:
    def test_queryRecentMinMax_singleParamSingleDrive_returnsMarker(
        self, conn: sqlite3.Connection
    ):
        _insertStats(conn, "RPM", [(800.0, 6200.0, _dt(0))])
        history = queryRecentMinMax(conn, paramNames=("RPM",), recentDriveWindow=5)
        assert isinstance(history, GaugeHistory)
        assert history.driveCount == 1
        assert history.markers["RPM"].minValue == 800.0
        assert history.markers["RPM"].maxValue == 6200.0

    def test_queryRecentMinMax_fiveDrives_reducesToOverallMinMax(
        self, conn: sqlite3.Connection
    ):
        _insertStats(
            conn,
            "RPM",
            [
                (780.0, 6200.0, _dt(0)),
                (820.0, 5900.0, _dt(1)),
                (790.0, 6400.0, _dt(2)),
                (810.0, 6100.0, _dt(3)),
                (800.0, 5800.0, _dt(4)),
            ],
        )
        history = queryRecentMinMax(conn, paramNames=("RPM",), recentDriveWindow=5)
        # Overall min across the 5 drives' per-drive mins
        assert history.markers["RPM"].minValue == 780.0
        # Overall max across the 5 drives' per-drive maxes
        assert history.markers["RPM"].maxValue == 6400.0
        assert history.driveCount == 5

    def test_queryRecentMinMax_windowLimitsToMostRecent(
        self, conn: sqlite3.Connection
    ):
        """Only the N most recent rows contribute; older drives are excluded."""
        _insertStats(
            conn,
            "RPM",
            [
                (100.0, 7500.0, _dt(10)),  # ancient outlier -- excluded by window=3
                (780.0, 6200.0, _dt(0)),
                (820.0, 5900.0, _dt(1)),
                (790.0, 6400.0, _dt(2)),
            ],
        )
        history = queryRecentMinMax(conn, paramNames=("RPM",), recentDriveWindow=3)
        assert history.markers["RPM"].minValue == 780.0
        # 7500 must NOT appear -- it's outside the 3-drive window
        assert history.markers["RPM"].maxValue == 6400.0

    def test_queryRecentMinMax_multipleParams_independentAggregation(
        self, conn: sqlite3.Connection
    ):
        _insertStats(conn, "RPM", [(800.0, 6200.0, _dt(0))])
        _insertStats(conn, "COOLANT_TEMP", [(150.0, 212.0, _dt(0))])
        history = queryRecentMinMax(
            conn, paramNames=("RPM", "COOLANT_TEMP"), recentDriveWindow=5
        )
        assert history.markers["RPM"].minValue == 800.0
        assert history.markers["COOLANT_TEMP"].maxValue == 212.0


# ================================================================================
# Edge cases
# ================================================================================


class TestQueryRecentMinMaxEdges:
    def test_queryRecentMinMax_noStatsRows_emptyHistory(
        self, conn: sqlite3.Connection
    ):
        history = queryRecentMinMax(
            conn, paramNames=("RPM", "COOLANT_TEMP"), recentDriveWindow=5
        )
        assert history.driveCount == 0
        assert history.markers == {}

    def test_queryRecentMinMax_onlySomeParamsHaveRows_othersOmitted(
        self, conn: sqlite3.Connection
    ):
        _insertStats(conn, "RPM", [(800.0, 6200.0, _dt(0))])
        history = queryRecentMinMax(
            conn,
            paramNames=("RPM", "COOLANT_TEMP", "BOOST"),
            recentDriveWindow=5,
        )
        assert "RPM" in history.markers
        # Missing from dict -> display layer renders placeholder
        assert "COOLANT_TEMP" not in history.markers
        assert "BOOST" not in history.markers

    def test_queryRecentMinMax_nullMinOrMax_skipsRow(
        self, conn: sqlite3.Connection
    ):
        """A legacy row with NULL min_value/max_value shouldn't poison the reduction."""
        _insertStats(conn, "RPM", [(800.0, 6200.0, _dt(0))])
        # Raw insert with NULL min
        conn.execute(
            """
            INSERT INTO statistics(parameter_name, analysis_date, profile_id,
                                   min_value, max_value, sample_count)
            VALUES ('RPM', ?, 'default', NULL, NULL, 100)
            """,
            (_dt(1).isoformat(),),
        )
        conn.commit()
        history = queryRecentMinMax(
            conn, paramNames=("RPM",), recentDriveWindow=5
        )
        assert history.markers["RPM"].minValue == 800.0
        assert history.markers["RPM"].maxValue == 6200.0

    def test_queryRecentMinMax_invalidWindow_raisesValueError(
        self, conn: sqlite3.Connection
    ):
        with pytest.raises(ValueError):
            queryRecentMinMax(conn, paramNames=("RPM",), recentDriveWindow=0)

    def test_queryRecentMinMax_driveCountReflectsHighestParamCount(
        self, conn: sqlite3.Connection
    ):
        """driveCount = max of per-param row counts (capped at window)."""
        _insertStats(conn, "RPM", [(800.0, 6200.0, _dt(0))])
        _insertStats(
            conn,
            "COOLANT_TEMP",
            [
                (150.0, 200.0, _dt(0)),
                (160.0, 205.0, _dt(1)),
                (155.0, 210.0, _dt(2)),
            ],
        )
        history = queryRecentMinMax(
            conn, paramNames=("RPM", "COOLANT_TEMP"), recentDriveWindow=5
        )
        assert history.driveCount == 3
