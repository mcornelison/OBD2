################################################################################
# File Name: recent_stats.py
# Purpose/Description: Aggregate per-parameter min/max across recent drives (US-165)
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
"""
Recent-drive min/max query helper for the advanced-tier display (US-165).

The advanced-tier primary screen shows a ``[min / max]`` bracket per gauge,
aggregated from the last N drives. This module encapsulates that SQL query
against the Pi's local ``statistics`` table so the display layer stays pure.

Data source
-----------
The ``statistics`` table (see ``src/pi/obdii/database_schema.py``) stores one
row per (parameter_name, analysis_date) with pre-computed ``min_value`` and
``max_value`` columns. Each row corresponds to a completed drive.

"Recent drives" is operationalized as the last N rows per parameter ordered
by ``analysis_date DESC`` -- NOT a global last-N rows across all params,
because a single drive contributes one row per observed parameter. Taking
the last N drives globally would produce asymmetric coverage when different
drives exercise different parameter sets.

Usage
-----
The callsite (Pi orchestrator or test harness) owns the sqlite3.Connection.
This module does no connection management.

    history = queryRecentMinMax(
        conn,
        paramNames=('RPM', 'COOLANT_TEMP', 'BOOST', 'AFR', 'SPEED',
                    'BATTERY_VOLTAGE'),
        recentDriveWindow=5,
    )

    # history.driveCount == min(actual rows, 5) for each param (reported as
    #                       the max across params)
    # history.markers['RPM'] is MinMaxMarker(minValue=780.0, maxValue=6200.0)
    # Missing params (zero statistics rows) are absent from the dict --
    # the display layer renders placeholders for them.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from pi.display.screens.primary_screen_advanced import GaugeHistory, MinMaxMarker

__all__ = [
    "queryRecentMinMax",
]


def queryRecentMinMax(
    conn: sqlite3.Connection,
    paramNames: Iterable[str],
    recentDriveWindow: int = 5,
) -> GaugeHistory:
    """Aggregate min/max per parameter across the last N drives.

    For each parameter in ``paramNames``, pulls the last ``recentDriveWindow``
    rows from the ``statistics`` table ordered by ``analysis_date DESC`` and
    reduces to a single (min, max) pair:

        minValue = min of per-drive min_value
        maxValue = max of per-drive max_value

    Parameters with zero rows are omitted from the returned markers dict.
    The advanced-tier display renders ``[--- / ---]`` for missing entries.

    Args:
        conn: Open sqlite3.Connection to the Pi's OBD DB. Must have the
            ``statistics`` table defined by ``database_schema.py``.
        paramNames: Iterable of parameter names to aggregate (e.g.
            ``BASIC_TIER_DISPLAY_ORDER``).
        recentDriveWindow: How many most-recent drives to fold into the
            min/max reduction. Must be >= 1.

    Returns:
        ``GaugeHistory`` with populated ``markers`` and a ``driveCount`` equal
        to the largest per-parameter row count (capped at
        ``recentDriveWindow``). If every parameter has zero rows,
        driveCount == 0 and markers == {}.

    Raises:
        ValueError: If ``recentDriveWindow < 1``.
    """
    if recentDriveWindow < 1:
        raise ValueError("recentDriveWindow must be >= 1")

    markers: dict[str, MinMaxMarker] = {}
    maxRowCount = 0

    for paramName in paramNames:
        rows = _fetchRecentStatsRows(conn, paramName, recentDriveWindow)
        if not rows:
            continue
        maxRowCount = max(maxRowCount, len(rows))
        validMins = [r[0] for r in rows if r[0] is not None]
        validMaxs = [r[1] for r in rows if r[1] is not None]
        if not validMins or not validMaxs:
            continue
        markers[paramName] = MinMaxMarker(
            minValue=float(min(validMins)),
            maxValue=float(max(validMaxs)),
        )

    return GaugeHistory(driveCount=maxRowCount, markers=markers)


def _fetchRecentStatsRows(
    conn: sqlite3.Connection,
    paramName: str,
    limit: int,
) -> list[tuple[float | None, float | None]]:
    """Fetch ``(min_value, max_value)`` for the last ``limit`` stats rows.

    Kept separate from ``queryRecentMinMax`` so the SQL is easy to inspect
    and so tests can swap the fetch behaviour if needed without mocking the
    outer reduction.
    """
    cursor = conn.execute(
        """
        SELECT min_value, max_value
          FROM statistics
         WHERE parameter_name = ?
         ORDER BY analysis_date DESC
         LIMIT ?
        """,
        (paramName, limit),
    )
    return list(cursor.fetchall())
