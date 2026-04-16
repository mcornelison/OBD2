################################################################################
# File Name: load_data.py
# Purpose/Description: Crawl-phase data loader — imports simulator-generated
#                      SQLite data into the server MariaDB (or compatible)
#                      schema with idempotent upserts.  Detects drives from
#                      connection_log events and creates drive_summary rows.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-157 (Sprint 7)
# ================================================================================
################################################################################

"""
Data loader for the Server Crawl phase.

Reads a portable SQLite file produced by scripts/seed_scenarios.py (or any Pi
database export) and upserts its rows into the server MariaDB schema.

Usage::

    python scripts/load_data.py \\
        --db-file data/sim_full_cycle.db \\
        --device-id sim-eclipse-gst

Behaviour:
    * Opens the SQLite file read-only.
    * For each sync-mirrored table, copies rows into MariaDB using
      INSERT ... ON DUPLICATE KEY UPDATE (MySQL) or INSERT ... ON CONFLICT
      DO UPDATE (SQLite) keyed on (source_device, source_id).
    * ``source_id`` is derived from SQLite ``rowid`` (aliases the integer PK
      where present, otherwise an implicit insertion-order ordinal).
    * Parses drive_start/drive_end pairs from connection_log and creates a
      drive_summary row per drive, populating duration_seconds and row_count.
    * Writes a sync_history row tracking the batch.
    * Idempotent — a second run on the same input produces the same state.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, Engine, create_engine, func, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Ensure project root is importable.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.server.db.models import (  # noqa: E402
    AiRecommendation,
    AlertLog,
    CalibrationSession,
    ConnectionLog,
    DriveSummary,
    Profile,
    RealtimeData,
    Statistic,
    SyncHistory,
    VehicleInfo,
)

logger = logging.getLogger(__name__)

# ================================================================================
# Table mapping
# ================================================================================
#
# Each entry describes how to copy a Pi SQLite table into the server schema:
#   piTable     — SQLite table name (== server table name)
#   model       — SQLAlchemy model class
#   columns     — Pi columns copied verbatim (names match on both sides)
#   renames     — Pi column → server column (for TEXT PK tables like profiles)
# ================================================================================


@dataclass(frozen=True)
class TableSpec:
    """Declarative mapping from a Pi SQLite table to a server model."""

    piTable: str
    model: type
    columns: tuple[str, ...]
    renames: tuple[tuple[str, str], ...] = ()


SYNC_TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "profiles",
        Profile,
        ("name", "description", "polling_interval_ms",
         "created_at", "updated_at"),
        renames=(("id", "source_profile_id"),),
    ),
    TableSpec(
        "vehicle_info",
        VehicleInfo,
        ("vin", "make", "model", "year", "engine",
         "fuel_type", "transmission", "drive_type", "body_class",
         "plant_city", "plant_country", "raw_api_response",
         "created_at", "updated_at"),
    ),
    TableSpec(
        "realtime_data",
        RealtimeData,
        ("timestamp", "parameter_name", "value", "unit", "profile_id"),
    ),
    TableSpec(
        "statistics",
        Statistic,
        ("parameter_name", "analysis_date", "profile_id",
         "max_value", "min_value", "avg_value", "mode_value",
         "std_1", "std_2", "outlier_min", "outlier_max",
         "sample_count", "created_at"),
    ),
    TableSpec(
        "ai_recommendations",
        AiRecommendation,
        ("timestamp", "recommendation", "priority_rank",
         "is_duplicate_of", "profile_id", "created_at"),
    ),
    TableSpec(
        "connection_log",
        ConnectionLog,
        ("timestamp", "event_type", "mac_address",
         "success", "error_message", "retry_count"),
    ),
    TableSpec(
        "alert_log",
        AlertLog,
        ("timestamp", "alert_type", "parameter_name",
         "value", "threshold", "profile_id"),
    ),
    TableSpec(
        "calibration_sessions",
        CalibrationSession,
        ("start_time", "end_time", "notes", "profile_id", "created_at"),
    ),
)

# Columns that must never be overwritten by ON DUPLICATE / ON CONFLICT UPDATE.
_PRESERVE_ON_UPDATE = frozenset(
    {"id", "source_id", "source_device", "synced_at"},
)


# ================================================================================
# Result envelope
# ================================================================================


@dataclass
class LoadResult:
    """Outcome of a load run — used for summary output and tests."""

    tableCounts: dict[str, int] = field(default_factory=dict)
    drivesDetected: int = 0
    newDrivesCreated: int = 0
    syncBatchId: int | None = None
    elapsedSeconds: float = 0.0


# ================================================================================
# Drive detection (pure)
# ================================================================================


def detectDrivePairs(
    events: list[tuple[datetime, str]],
) -> list[tuple[datetime, datetime]]:
    """
    Pair drive_start / drive_end events into (startTime, endTime) tuples.

    A drive_start is held pending until the next drive_end closes it.  If a
    second drive_start arrives before a drive_end, the first is dropped
    (treated as a false start).  Non-drive events are ignored.

    Args:
        events: List of (timestamp, event_type) tuples ordered by timestamp.

    Returns:
        List of (startTime, endTime) tuples, one per completed drive.
    """
    drives: list[tuple[datetime, datetime]] = []
    pendingStart: datetime | None = None
    for ts, eventType in events:
        if eventType == "drive_start":
            pendingStart = ts
        elif eventType == "drive_end" and pendingStart is not None:
            drives.append((pendingStart, ts))
            pendingStart = None
    return drives


# ================================================================================
# SQLite helpers
# ================================================================================


def _tableExists(conn: sqlite3.Connection, tableName: str) -> bool:
    """Return True if tableName is a table in the given SQLite connection."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (tableName,),
    ).fetchone()
    return row is not None


_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
)


def _parseDateTime(value: object) -> datetime | None:
    """Coerce a SQLite datetime string to a Python datetime.  Pass-through for
    datetime, None, or unparseable input."""
    if value is None or isinstance(value, datetime):
        return value  # type: ignore[return-value]
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _coerceDateTimeColumns(model: type, row: dict[str, object]) -> None:
    """In-place: convert string values in DateTime columns to datetime objects."""
    for col in model.__table__.columns:
        if isinstance(col.type, DateTime) and col.name in row:
            row[col.name] = _parseDateTime(row[col.name])


def _selectRows(
    conn: sqlite3.Connection, spec: TableSpec,
) -> list[dict[str, object]]:
    """
    Select all rows from a Pi table and shape them for upsert.

    Returns a list of dicts keyed by server column name.  Each dict carries
    a ``_rowid`` key — the SQLite rowid — that the caller maps to
    ``source_id``.
    """
    renameCols = [pi for pi, _ in spec.renames]
    selectCols = ["rowid", *spec.columns, *renameCols]
    # Build SQL from whitelisted spec — all names come from SYNC_TABLES constants
    sql = f"SELECT {', '.join(selectCols)} FROM {spec.piTable}"  # noqa: S608
    cursor = conn.execute(sql)

    rows: list[dict[str, object]] = []
    for raw in cursor.fetchall():
        rowid = raw[0]
        base = dict(zip(spec.columns, raw[1:1 + len(spec.columns)], strict=True))
        renamed = raw[1 + len(spec.columns):]
        for (_piCol, serverCol), value in zip(spec.renames, renamed, strict=True):
            base[serverCol] = value
        base["_rowid"] = rowid
        rows.append(base)
    return rows


# ================================================================================
# Upsert
# ================================================================================


def _upsertBatch(
    session: Session,
    model: type,
    rows: list[dict[str, object]],
) -> None:
    """
    Dialect-aware bulk upsert on (source_device, source_id).

    Uses MySQL ``ON DUPLICATE KEY UPDATE`` or SQLite ``ON CONFLICT DO UPDATE``
    depending on the engine dialect.  Columns in ``_PRESERVE_ON_UPDATE`` are
    kept as-is on conflict.
    """
    if not rows:
        return

    table = model.__table__
    dialectName = session.bind.dialect.name

    # Ensure every row has the same keys (critical for executemany batching).
    allKeys: set[str] = set()
    for r in rows:
        allKeys.update(r.keys())
    for r in rows:
        for k in allKeys:
            r.setdefault(k, None)

    if dialectName == "mysql" or dialectName == "mariadb":
        stmt = mysql_insert(table)
        updateCols = {
            c.name: stmt.inserted[c.name]
            for c in table.columns
            if c.name in allKeys and c.name not in _PRESERVE_ON_UPDATE
        }
        stmt = stmt.on_duplicate_key_update(**updateCols)
    elif dialectName == "sqlite":
        stmt = sqlite_insert(table)
        updateCols = {
            c.name: getattr(stmt.excluded, c.name)
            for c in table.columns
            if c.name in allKeys and c.name not in _PRESERVE_ON_UPDATE
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["source_device", "source_id"],
            set_=updateCols,
        )
    else:
        raise ValueError(
            f"Unsupported dialect for upsert: {dialectName!r}. "
            "Expected mysql, mariadb, or sqlite.",
        )

    session.execute(stmt, rows)


# ================================================================================
# Per-table load
# ================================================================================


def _loadTable(
    sqliteConn: sqlite3.Connection,
    session: Session,
    spec: TableSpec,
    deviceId: str,
    syncBatchId: int,
) -> int:
    """Load one Pi table into the server schema.  Returns rows loaded."""
    if not _tableExists(sqliteConn, spec.piTable):
        return 0

    rawRows = _selectRows(sqliteConn, spec)
    if not rawRows:
        return 0

    hasBatchId = "sync_batch_id" in {c.name for c in spec.model.__table__.columns}

    prepared: list[dict[str, object]] = []
    for r in rawRows:
        rowid = r.pop("_rowid")
        r["source_id"] = rowid
        r["source_device"] = deviceId
        if hasBatchId:
            r["sync_batch_id"] = syncBatchId
        _coerceDateTimeColumns(spec.model, r)
        prepared.append(r)

    _upsertBatch(session, spec.model, prepared)
    return len(prepared)


# ================================================================================
# Drive summary creation
# ================================================================================


def _createDriveSummaries(
    session: Session, deviceId: str,
) -> tuple[int, int]:
    """
    Detect drives for deviceId and create/update drive_summary rows.

    Returns:
        (drivesDetected, newDrivesCreated)
    """
    events = session.execute(
        select(ConnectionLog.timestamp, ConnectionLog.event_type)
        .where(ConnectionLog.source_device == deviceId)
        .order_by(ConnectionLog.timestamp, ConnectionLog.id),
    ).all()

    drives = detectDrivePairs([(row[0], row[1]) for row in events])

    newCount = 0
    for startTime, endTime in drives:
        duration = int((endTime - startTime).total_seconds())

        rowCount = session.execute(
            select(func.count())
            .select_from(RealtimeData)
            .where(RealtimeData.source_device == deviceId)
            .where(RealtimeData.timestamp >= startTime)
            .where(RealtimeData.timestamp <= endTime),
        ).scalar_one()

        profileIdRow = session.execute(
            select(RealtimeData.profile_id)
            .where(RealtimeData.source_device == deviceId)
            .where(RealtimeData.timestamp >= startTime)
            .where(RealtimeData.timestamp <= endTime)
            .limit(1),
        ).scalar_one_or_none()

        existingId = session.execute(
            select(DriveSummary.id)
            .where(DriveSummary.device_id == deviceId)
            .where(DriveSummary.start_time == startTime),
        ).scalar_one_or_none()

        if existingId is None:
            session.add(
                DriveSummary(
                    device_id=deviceId,
                    start_time=startTime,
                    end_time=endTime,
                    duration_seconds=duration,
                    row_count=int(rowCount),
                    profile_id=profileIdRow,
                ),
            )
            newCount += 1
        else:
            session.execute(
                update(DriveSummary)
                .where(DriveSummary.id == existingId)
                .values(
                    end_time=endTime,
                    duration_seconds=duration,
                    row_count=int(rowCount),
                    profile_id=profileIdRow,
                ),
            )
    return len(drives), newCount


# ================================================================================
# Public API
# ================================================================================


def loadData(
    dbFile: str,
    deviceId: str,
    engine: Engine,
) -> LoadResult:
    """
    Load a Pi SQLite export into the given server database.

    Args:
        dbFile: Path to a Pi-schema SQLite file.
        deviceId: Value to assign to ``source_device`` on all loaded rows.
        engine: SQLAlchemy Engine bound to the target server database.

    Returns:
        LoadResult with per-table counts, drives detected, and timing.
    """
    wallStart = time.monotonic()
    result = LoadResult()

    if not os.path.isfile(dbFile):
        raise FileNotFoundError(f"SQLite file not found: {dbFile}")

    # Open SQLite read-only (file: URI so PRAGMA journal does not mutate the file)
    sqliteUri = f"file:{dbFile}?mode=ro"
    sqliteConn = sqlite3.connect(sqliteUri, uri=True)
    sqliteConn.row_factory = sqlite3.Row

    try:
        with Session(engine) as session:
            # Create sync_history row
            syncHistory = SyncHistory(
                device_id=deviceId,
                status="in_progress",
                rows_synced=0,
            )
            session.add(syncHistory)
            session.flush()
            batchId = syncHistory.id
            result.syncBatchId = batchId

            # Load every sync table that exists
            for spec in SYNC_TABLES:
                count = _loadTable(
                    sqliteConn, session, spec, deviceId, batchId,
                )
                result.tableCounts[spec.piTable] = count

            # Detect drives and create drive_summary rows
            detected, created = _createDriveSummaries(session, deviceId)
            result.drivesDetected = detected
            result.newDrivesCreated = created

            # Complete sync_history
            totalRows = sum(result.tableCounts.values())
            tablesSynced = ",".join(
                t for t, c in result.tableCounts.items() if c > 0
            )
            session.execute(
                update(SyncHistory)
                .where(SyncHistory.id == batchId)
                .values(
                    completed_at=datetime.now(UTC).replace(tzinfo=None),
                    rows_synced=totalRows,
                    status="completed",
                    tables_synced=tablesSynced,
                ),
            )

            session.commit()
    finally:
        sqliteConn.close()

    result.elapsedSeconds = time.monotonic() - wallStart
    return result


# ================================================================================
# Summary output
# ================================================================================


def _printSummary(result: LoadResult, deviceId: str, dbFile: str) -> None:
    """Print a human-readable summary of a load run."""
    print(f"\nLoaded {dbFile} as device '{deviceId}'")
    print(f"  Sync batch ID: {result.syncBatchId}")
    print("  Rows loaded per table:")
    for tableName, count in result.tableCounts.items():
        if count > 0:
            print(f"    {tableName}: {count}")
    skipped = [t for t, c in result.tableCounts.items() if c == 0]
    if skipped:
        print(f"  Empty/missing tables: {', '.join(skipped)}")
    print(
        f"  Drives detected: {result.drivesDetected} "
        f"(new drive_summary rows: {result.newDrivesCreated})",
    )
    print(f"  Elapsed: {result.elapsedSeconds:.2f}s")


# ================================================================================
# CLI
# ================================================================================


def _toSyncDriverUrl(url: str) -> str:
    # Async drivers (aiomysql) raise MissingGreenlet under a sync engine.
    # The .env file uses the async URL for the FastAPI server; rewrite for CLI use.
    return url.replace("+aiomysql://", "+pymysql://", 1)


def parseArguments(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Args:
        argv: Optional argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Load a Pi SQLite export into the server MariaDB schema. "
            "Idempotent upsert on (source_device, source_id)."
        ),
    )
    parser.add_argument(
        "--db-file", required=True,
        help="Path to a Pi-schema SQLite file (produced by seed_scenarios.py).",
    )
    parser.add_argument(
        "--device-id", required=True,
        help="Value to assign to source_device on all loaded rows.",
    )
    parser.add_argument(
        "--server-db-url", default=None,
        help="SQLAlchemy URL for the target server DB. "
             "Defaults to the DATABASE_URL env var.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Entry point.

    Args:
        argv: Optional argument list (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 on success).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = parseArguments(argv)

    serverUrl = args.server_db_url or os.environ.get("DATABASE_URL")
    if not serverUrl:
        print(
            "ERROR: No server DB URL provided. "
            "Pass --server-db-url or set DATABASE_URL env var.",
            file=sys.stderr,
        )
        return 2

    engine = create_engine(_toSyncDriverUrl(serverUrl))
    try:
        result = loadData(
            dbFile=args.db_file,
            deviceId=args.device_id,
            engine=engine,
        )
    finally:
        engine.dispose()

    _printSummary(result, args.device_id, args.db_file)
    return 0


# ================================================================================
# Entry point
# ================================================================================

__all__ = [
    "LoadResult",
    "SYNC_TABLES",
    "TableSpec",
    "detectDrivePairs",
    "loadData",
    "main",
    "parseArguments",
]


if __name__ == "__main__":
    raise SystemExit(main())
