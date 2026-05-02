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
# 2026-05-01    | Rex (US-252) | Added ensurePowerLogVcellColumn idempotent
#                               migration helper + logShutdownStage writer for
#                               PowerDownOrchestrator stage-transition rows.
# 2026-05-02    | Rex (US-267) | Discriminator C: hardened logShutdownStage
#                               write-path for hard-crash durability.  PRAGMA
#                               synchronous=FULL on the write connection so
#                               SQLite fsyncs WAL on every commit; explicit
#                               conn.commit() before context-manager exit;
#                               os.fsync(database.dbPath) defense-in-depth at
#                               the kernel boundary; try/except now LOGs at
#                               ERROR + RE-RAISES instead of silently
#                               swallowing the exception.  Closes Spool's
#                               Sprint 22 Drain-7 truth-table hypothesis C.
# ================================================================================
################################################################################

"""
Database logging helpers for PowerMonitor.

Module-level functions that write power log rows to the DB. Each takes
the database (or None) + the data to write; PowerMonitor keeps the state
and delegates row-writing here.
"""

import logging
import os
import sqlite3
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


def logShutdownStage(
    database: Any | None,
    eventType: str,
    vcell: float,
) -> None:
    """Log a PowerDownOrchestrator stage-transition row to power_log (US-252).

    Mirrors :func:`logPowerTransition` shape but persists the LiPo cell
    voltage at threshold crossing in the ``vcell`` column added by US-252.
    ``power_source`` is hard-coded to ``battery`` and ``on_ac_power`` to 0
    because stage transitions only fire while the orchestrator is on
    battery power -- the orchestrator's :meth:`tick` short-circuits when
    ``currentSource != BATTERY``.

    US-267 (Discriminator C) durability chain
    -----------------------------------------
    Drain Test 6 produced a power_log with zero STAGE_* rows despite a
    21-min battery window.  Hypothesis C: the write path itself buffers
    rows (in WAL) such that a hard crash before checkpoint loses them.
    The chain hardened here:

    * ``PRAGMA synchronous = FULL`` on this write connection -- in WAL
      mode SQLite fsyncs the WAL on every commit; in rollback mode it
      fsyncs the main db file on commit.  Either way the row is
      durable at the SQLite layer.
    * Explicit ``conn.commit()`` before the context manager exits --
      removes the dependency on ``ObdDatabase.connect``'s implicit
      commit semantics for the durability sequence.
    * ``os.fsync(fd)`` on the database file after commit -- kernel-level
      defense in depth that catches any drift in SQLite's own fsync
      behavior.  Wrapped in its own try/except so an fsync failure
      does NOT roll back the row (which is already SQLite-durable per
      PRAGMA synchronous=FULL).
    * The outer try/except now LOGs at ERROR and **re-raises** any
      exception during INSERT -- the pre-US-267 swallow contract masked
      genuine write failures from the orchestrator.  The orchestrator's
      :func:`PowerDownOrchestrator._writePowerLogStage` (US-252) catches
      Exception around its own writer call so the safety ladder cannot
      be blocked by a re-raising forensics writer.

    Args:
        database: ObdDatabase instance (or None for no-op).
        eventType: One of POWER_LOG_EVENT_STAGE_WARNING /
            POWER_LOG_EVENT_STAGE_IMMINENT / POWER_LOG_EVENT_STAGE_TRIGGER.
        vcell: VCELL volts at the moment of stage transition.

    Raises:
        Exception: Any error raised by the INSERT or surrounding
            connection setup is logged at ERROR and re-raised.  Callers
            that need silent forensics (e.g. PowerDownOrchestrator)
            already wrap the writer call in their own try/except.
    """
    if database is None:
        return
    try:
        with database.connect() as conn:
            # US-267: WAL fsync on every commit; otherwise WAL-buffered
            # rows are lost on hard crash before checkpoint.
            conn.execute("PRAGMA synchronous = FULL")
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO power_log
                (timestamp, event_type, power_source, on_ac_power, vcell)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    utcIsoNow(),
                    eventType,
                    PowerSource.BATTERY.value,
                    0,
                    float(vcell),
                ),
            )
            # Explicit commit before context-manager exit; the outer
            # `with` would commit again on clean exit but the explicit
            # ordering pairs cleanly with the os.fsync below.
            conn.commit()
        # Defense-in-depth fsync at the kernel boundary AFTER commit.
        # PRAGMA synchronous=FULL has already fsynced via SQLite; this
        # catches any drift in SQLite's own fsync behavior.  fsync
        # errors are loud but DO NOT roll back the row.
        try:
            fd = os.open(database.dbPath, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as fsyncErr:
            logger.error(
                "Error fsyncing power_log database after stage write: %s",
                fsyncErr,
            )
        logger.debug(
            f"Logged shutdown stage to power_log | type={eventType} "
            f"vcell={vcell:.3f}V"
        )
    except Exception as e:
        # US-267: log AND re-raise.  Pre-fix code swallowed silently --
        # masking genuine write failures and conflating "row written"
        # with "row attempted but failed silently".
        logger.error(
            "Error logging shutdown stage to database: %s", e, exc_info=True
        )
        raise


def ensurePowerLogVcellColumn(conn: sqlite3.Connection) -> bool:
    """Add ``vcell`` column to ``power_log`` if not already present (US-252).

    Idempotent: PRAGMA table_info probe before ALTER. The new column is
    nullable so legacy rows (power-source transitions without a voltage
    reading) remain valid. The caller owns commit semantics; this matches
    the surrounding ``ObdDatabase.initialize`` transaction scope.

    Args:
        conn: Open sqlite3 connection.

    Returns:
        True if the ALTER TABLE ran, False if the column was already
        present or the table did not exist.
    """
    tableExists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        ('power_log',),
    ).fetchone() is not None
    if not tableExists:
        return False

    columns = conn.execute("PRAGMA table_info(power_log)").fetchall()
    if any(row[1] == 'vcell' for row in columns):
        return False

    conn.execute("ALTER TABLE power_log ADD COLUMN vcell REAL")
    return True


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
