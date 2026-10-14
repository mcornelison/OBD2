################################################################################
# File Name: fuel_since_reset.py
# Purpose/Description: US-881-c (F-159) the Pi-LOCAL one-row fuel_since_reset
#                      table: since-reset fuel, distance and open-loop seconds
#                      that survive a reboot. Never synced -- every fact behind
#                      it already syncs in realtime_data.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-881-c) | Initial -- read / accumulate / reset on a
#                                connection, plus the database-handle helpers
#                                the card emitter calls.
# ================================================================================
################################################################################

"""Accessors for the ``fuel_since_reset`` singleton (US-881-c, Atlas gap 3).

The table and its ensure step live in :mod:`pi.obdii.database_schema`
(``ensureFuelSinceResetTable``). The connection-level helpers here leave commit
to the caller; the ``...From`` helpers take the :class:`ObdDatabase` handle the
card emitter holds, because that module may not open a connection itself.
"""

from __future__ import annotations

import sqlite3
from typing import Any

__all__ = [
    "accumulate",
    "accumulateAndReadFrom",
    "read",
    "readFrom",
    "reset",
    "resetAndReadFrom",
]

_COLUMNS = ("id", "fuel_l", "distance_km", "open_loop_s", "reset_at_ts", "updated_at")


def read(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Return the singleton row as a column-name dict, or None before any row.

    Args:
        conn: Open sqlite3 connection.

    Returns:
        ``{id, fuel_l, distance_km, open_loop_s, reset_at_ts, updated_at}``,
        or None when nothing has been accumulated or reset yet.
    """
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM fuel_since_reset WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    return dict(zip(_COLUMNS, tuple(row), strict=True))


def accumulate(
    conn: sqlite3.Connection,
    fuelL: float,
    distanceKm: float,
    openLoopS: float,
    updatedAt: str,
) -> None:
    """Add deltas to the totals; the first use creates the row.

    A first-ever row starts its window at ``updatedAt`` (``reset_at_ts``).

    Args:
        conn: Open sqlite3 connection; the caller owns commit.
        fuelL: Litres to add.
        distanceKm: Kilometres to add.
        openLoopS: Open-loop seconds to add.
        updatedAt: Canonical UTC of this write.
    """
    conn.execute(
        "INSERT INTO fuel_since_reset "
        "(id, fuel_l, distance_km, open_loop_s, reset_at_ts, updated_at) "
        "VALUES (1, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "fuel_l = fuel_l + excluded.fuel_l, "
        "distance_km = distance_km + excluded.distance_km, "
        "open_loop_s = open_loop_s + excluded.open_loop_s, "
        "updated_at = excluded.updated_at",
        (float(fuelL), float(distanceKm), float(openLoopS), updatedAt, updatedAt),
    )


def reset(conn: sqlite3.Connection, resetAtTs: str) -> None:
    """Zero the totals and start a new window at ``resetAtTs``.

    Args:
        conn: Open sqlite3 connection; the caller owns commit.
        resetAtTs: Canonical UTC of the reset.
    """
    conn.execute(
        "INSERT INTO fuel_since_reset "
        "(id, fuel_l, distance_km, open_loop_s, reset_at_ts, updated_at) "
        "VALUES (1, 0.0, 0.0, 0.0, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "fuel_l = 0.0, distance_km = 0.0, open_loop_s = 0.0, "
        "reset_at_ts = excluded.reset_at_ts, updated_at = excluded.updated_at",
        (resetAtTs, resetAtTs),
    )


def readFrom(database: Any) -> dict[str, Any] | None:
    """:func:`read` through an ``ObdDatabase`` handle."""
    with database.connect() as conn:
        return read(conn)


def accumulateAndReadFrom(
    database: Any,
    fuelL: float,
    distanceKm: float,
    openLoopS: float,
    updatedAt: str,
) -> dict[str, Any] | None:
    """:func:`accumulate` then :func:`read` in one transaction.

    Returns:
        The row after the write.
    """
    with database.connect() as conn:
        accumulate(conn, fuelL, distanceKm, openLoopS, updatedAt)
        return read(conn)


def resetAndReadFrom(database: Any, resetAtTs: str) -> dict[str, Any] | None:
    """:func:`reset` then :func:`read` in one transaction.

    Returns:
        The row after the reset.
    """
    with database.connect() as conn:
        reset(conn, resetAtTs)
        return read(conn)
