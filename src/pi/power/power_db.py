################################################################################
# File Name: power_db.py
# Purpose/Description: Database logging helpers for the power monitor
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-012
# 2026-04-14    | Sweep 5      | Extracted from power.py (task 4 split)
# 2026-04-19    | Rex (US-203) | TD-027 sweep: route every power_log INSERT
#                               through utcIsoNow so capture rows are canonical
#                               ISO-8601 UTC regardless of caller timestamp.
# ================================================================================
################################################################################

"""
Database logging helpers for PowerMonitor.

Module-level functions that write power log rows to the DB. Each takes
the database (or None) + the data to write; PowerMonitor keeps the state
and delegates row-writing here.
"""

import logging
from datetime import datetime
from typing import Any

from src.common.time.helper import utcIsoNow

from .types import PowerReading, PowerSource

logger = logging.getLogger(__name__)


def logPowerReading(
    database: Any | None,
    reading: PowerReading,
    eventType: str,
) -> None:
    """
    Log a power reading to the database.

    Args:
        database: ObdDatabase instance (or None)
        reading: The power reading to log
        eventType: Type of event (ac_power, battery_power)
    """
    if database is None:
        return

    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            # TD-027 / US-203: canonical ISO-8601 UTC at DB-write boundary.
            # The reading.timestamp field may be naive local-time (upstream
            # PowerReading default is naive datetime.now()); capture rows must
            # not inherit that drift.
            cursor.execute(
                """
                INSERT INTO power_log
                (timestamp, event_type, power_source, on_ac_power)
                VALUES (?, ?, ?, ?)
                """,
                (
                    utcIsoNow(),
                    eventType,
                    reading.powerSource.value,
                    1 if reading.onAcPower else 0,
                )
            )
            logger.debug(f"Logged power status to database | type={eventType}")
    except Exception as e:
        logger.error(f"Error logging power status to database: {e}")


def logPowerTransition(
    database: Any | None,
    eventType: str,
    timestamp: datetime,  # noqa: ARG001 -- kept for BC; DB row uses utcIsoNow at write-time
    currentSource: PowerSource,
) -> None:
    """
    Log a power transition event to the database.

    Args:
        database: ObdDatabase instance (or None)
        eventType: Type of transition event
        timestamp: Historical transition time (retained for API BC; the
            persisted row uses canonical write-time to satisfy TD-027)
        currentSource: Current power source after transition
    """
    if database is None:
        return

    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            # TD-027 / US-203: canonical ISO-8601 UTC at DB-write boundary.
            cursor.execute(
                """
                INSERT INTO power_log
                (timestamp, event_type, power_source, on_ac_power)
                VALUES (?, ?, ?, ?)
                """,
                (
                    utcIsoNow(),
                    eventType,
                    currentSource.value,
                    1 if currentSource == PowerSource.AC_POWER else 0,
                )
            )
            logger.debug(f"Logged power transition to database | type={eventType}")
    except Exception as e:
        logger.error(f"Error logging power transition to database: {e}")


def logPowerSavingEvent(
    database: Any | None,
    eventType: str,
    currentSource: PowerSource,
) -> None:
    """
    Log a power saving mode event to the database.

    Args:
        database: ObdDatabase instance (or None)
        eventType: Type of power saving event
        currentSource: Current power source when event occurred
    """
    if database is None:
        return

    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            # TD-027 / US-203: canonical ISO-8601 UTC via the shared helper.
            # Previously used naive datetime.now() -- produced America/Chicago
            # local-time strings, colliding with the schema DEFAULT's UTC form.
            cursor.execute(
                """
                INSERT INTO power_log
                (timestamp, event_type, power_source, on_ac_power)
                VALUES (?, ?, ?, ?)
                """,
                (
                    utcIsoNow(),
                    eventType,
                    currentSource.value,
                    1 if currentSource == PowerSource.AC_POWER else 0,
                )
            )
            logger.debug(f"Logged power saving event to database | type={eventType}")
    except Exception as e:
        logger.error(f"Error logging power saving event to database: {e}")


def getPowerHistory(
    database: Any | None,
    limit: int = 100,
    eventType: str | None = None,
) -> list[dict[str, Any]]:
    """
    Read power history from the database.

    Args:
        database: ObdDatabase instance (or None)
        limit: Maximum number of records to return
        eventType: Filter by event type (optional)

    Returns:
        List of power event records (empty if no database or on error)
    """
    if database is None:
        return []

    try:
        with database.connect() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM power_log WHERE 1=1"
            params: list[Any] = []

            if eventType:
                query += " AND event_type = ?"
                params.append(eventType)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [dict(row) for row in rows]

    except Exception as e:
        logger.error(f"Error getting power history: {e}")
        return []
