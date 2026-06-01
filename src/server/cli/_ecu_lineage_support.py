################################################################################
# File Name: _ecu_lineage_support.py
# Purpose/Description: Shared helpers for the F-108 ECU-lineage server CLIs
#                      (stamp_ecu_swap, show_ecu_lineage, add_ecu_note -- US-366).
#                      Centralises the sync DB-URL resolver, the pre-migration
#                      column-presence probe (so each CLI degrades gracefully on
#                      a pre-v0010 vehicle_info), the currently-active-row query,
#                      ISO-8601 timestamp parsing (normalised to naive UTC to
#                      match the *_utc DateTime columns), and the append-only
#                      notes formatter.  No DB writes happen here -- these are
#                      pure/query helpers the CLIs compose.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-366) | Initial -- shared ECU-lineage CLI support.
# ================================================================================
################################################################################

"""Shared helpers for the F-108 ECU-lineage CLIs (US-366)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.server.db.models import VehicleInfo

# Operator-facing message emitted when the vehicle_info table predates the
# v0010 ECU-lineage migration (no ecu_signature column).  All three CLIs share
# it so the remediation hint is identical everywhere.
PRE_MIGRATION_MESSAGE: str = (
    "vehicle_info has no ECU-lineage columns; run the v0010 migration "
    "before using the ECU-lineage CLIs"
)


def resolveSyncDatabaseUrl() -> str:
    """Resolve a SYNC SQLAlchemy URL from the server config.

    The production server uses an async URL (``mysql+aiomysql://``); these
    CLIs run synchronously, so the async driver is swapped for its sync
    counterpart.  An already-sync URL passes through unchanged.

    Returns:
        A synchronous SQLAlchemy database URL.
    """
    from src.server.config import Settings

    url = Settings().DATABASE_URL
    if "+aiomysql" in url:
        return url.replace("+aiomysql", "+pymysql")
    if "+aiosqlite" in url:
        return url.replace("+aiosqlite", "")
    return url


def ecuLineageColumnsPresent(engine: Engine) -> bool:
    """Return True when vehicle_info carries the v0010 ECU-lineage columns.

    Lets each CLI emit a graceful pre-migration error instead of crashing on
    a missing-column ``OperationalError`` when pointed at a pre-v0010 DB.

    Args:
        engine: An open SQLAlchemy engine bound to the target database.

    Returns:
        True if the ``ecu_signature`` column exists on ``vehicle_info``.
    """
    inspector = inspect(engine)
    if "vehicle_info" not in inspector.get_table_names():
        return False
    columns = {col["name"] for col in inspector.get_columns("vehicle_info")}
    return "ecu_signature" in columns


def getActiveVehicleInfo(session: Session) -> VehicleInfo | None:
    """Return the currently-active vehicle_info row, or None.

    The currently-active ECU is the single row whose
    ``ecu_removal_timestamp_utc IS NULL`` (the DB enforces at most one).

    Args:
        session: An open SQLAlchemy session.

    Returns:
        The active ``VehicleInfo`` row, or ``None`` when no ECU is active.
    """
    return session.execute(
        select(VehicleInfo).where(
            VehicleInfo.ecu_removal_timestamp_utc.is_(None)
        )
    ).scalar_one_or_none()


def nextSourceId(session: Session, sourceDevice: str) -> int:
    """Return the next free ``source_id`` within a ``source_device`` namespace.

    Server-authored ECU-lineage rows must satisfy the
    ``UNIQUE(source_device, source_id)`` constraint, so a swap's new row takes
    ``max(source_id) + 1`` among rows sharing its device (1 when none exist).

    Args:
        session: An open SQLAlchemy session.
        sourceDevice: The ``source_device`` namespace to allocate within.

    Returns:
        The next available ``source_id`` for that device.
    """
    current = session.execute(
        select(func.max(VehicleInfo.source_id)).where(
            VehicleInfo.source_device == sourceDevice
        )
    ).scalar_one_or_none()
    return (current or 0) + 1


def parseIsoTimestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into a naive UTC datetime.

    A trailing ``Z`` or explicit offset is accepted (Python 3.11
    ``fromisoformat``); offset-aware values are converted to UTC and the
    tzinfo dropped so the result is directly comparable to / storable in the
    naive-UTC ``*_utc`` DateTime columns.

    Args:
        value: An ISO-8601 timestamp string, e.g. ``2026-06-01T12:00:00Z``.

    Returns:
        A naive ``datetime`` in UTC.

    Raises:
        ValueError: If ``value`` is not a parseable ISO-8601 timestamp.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def appendNote(existing: str | None, text: str, *, now: datetime) -> str:
    """Append a timestamped line to a notes value, preserving prior content.

    The notes column is append-only by convention: each call adds one
    ``[<utc-iso>] <text>`` line below any existing lines; nothing is
    overwritten.

    Args:
        existing: The current notes value (may be ``None`` / empty).
        text: The note text to append.
        now: The timestamp to stamp the line with (UTC-aware preferred).

    Returns:
        The new notes value with the stamped line appended.
    """
    stamp = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{stamp}] {text}"
    if existing:
        return f"{existing}\n{line}"
    return line
