################################################################################
# File Name: sync.py
# Purpose/Description: POST /api/v1/sync delta sync endpoint — accepts delta
#                      data from Pi devices, upserts it into MariaDB using
#                      (source_device, source_id) keys, and records the batch
#                      in sync_history.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-CMP-004 — router,
#               |              | Pydantic models, sync core, transaction handling
# ================================================================================
################################################################################

"""
Delta sync endpoint for the Eclipse OBD-II companion server.

Accepts a JSON payload of the shape::

    {
        "deviceId":  "chi-eclipse-01",
        "batchId":   "sync-2026-04-15T14:30:00",
        "tables": {
            "realtime_data": {"lastSyncedId": 3965, "rows": [...]},
            ...
        }
    }

Behaviour (server spec §2.2, sprint US-CMP-004):

* API key required (attached via ``Depends(requireApiKey)`` at router include
  time in ``src/server/api/app.py``).
* Payloads larger than ``MAX_SYNC_PAYLOAD_MB`` are rejected with 413 before
  any JSON parsing or DB work.
* Only the eight synced tables are accepted — any other key in ``tables``
  fails Pydantic validation with 422.
* Rows are upserted with ``(source_device, source_id)`` as the natural key;
  the Pi-native ``id`` field maps to ``source_id``. Server sets ``synced_at``,
  ``source_device``, and ``sync_batch_id`` on every row.
* All table upserts run inside a single SQLAlchemy transaction — any error
  rolls the entire batch back.
* ``sync_history`` row is created (status=in_progress) in its own committed
  transaction so failures remain visible; it is updated to
  ``completed`` / ``failed`` after the upsert transaction settles.
* The response includes ``driveDataReceived=true`` when any connection_log
  row carries ``event_type=drive_end`` — a signal for US-CMP-006 run-phase
  auto-analysis (stubbed to ``autoAnalysisTriggered=false`` here).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from src.server.db.connection import getAsyncSession
from src.server.db.models import (
    AiRecommendation,
    AlertLog,
    CalibrationSession,
    ConnectionLog,
    Profile,
    RealtimeData,
    Statistic,
    SyncHistory,
    VehicleInfo,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Table registry
# ==============================================================================

# Map accepted table name → (model class, renames Pi→server column).
# Only profiles carries a column rename (Pi uses TEXT id as PK, mirrored as
# ``source_profile_id`` because server source_id is Integer).
_TABLE_REGISTRY: dict[str, tuple[type, tuple[tuple[str, str], ...]]] = {
    "realtime_data": (RealtimeData, ()),
    "statistics": (Statistic, ()),
    "profiles": (Profile, (("id", "source_profile_id"),)),
    "vehicle_info": (VehicleInfo, ()),
    "ai_recommendations": (AiRecommendation, ()),
    "connection_log": (ConnectionLog, ()),
    "alert_log": (AlertLog, ()),
    "calibration_sessions": (CalibrationSession, ()),
}

ACCEPTED_TABLES: frozenset[str] = frozenset(_TABLE_REGISTRY.keys())

# Columns never overwritten on upsert conflict.
_PRESERVE_ON_UPDATE = frozenset({"id", "source_id", "source_device", "synced_at"})


# ==============================================================================
# Pydantic request / response models
# ==============================================================================


class TableData(BaseModel):
    """Per-table section of a sync request body."""

    model_config = ConfigDict(extra="forbid")

    lastSyncedId: int = Field(
        default=0,
        description="Pi's last-synced rowid for this table (informational).",
    )
    rows: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Delta rows, each including a Pi-native ``id`` field.",
    )


class SyncRequest(BaseModel):
    """Top-level sync request body."""

    model_config = ConfigDict(extra="forbid")

    deviceId: str = Field(
        ..., min_length=1, description="Source device identifier (e.g. chi-eclipse-01).",
    )
    batchId: str = Field(
        ..., min_length=1, description="Pi-assigned batch identifier.",
    )
    tables: dict[str, TableData] = Field(
        ..., description="Per-table delta payload keyed by accepted table name.",
    )

    @field_validator("tables")
    @classmethod
    def _tablesMustBeAccepted(
        cls, value: dict[str, TableData],
    ) -> dict[str, TableData]:
        """Reject any table name not in ACCEPTED_TABLES."""
        unknown = set(value) - ACCEPTED_TABLES
        if unknown:
            raise ValueError(
                f"Unknown table name(s): {sorted(unknown)}. "
                f"Accepted: {sorted(ACCEPTED_TABLES)}.",
            )
        return value


class TableResult(BaseModel):
    """Per-table processing result in the response."""

    inserted: int = 0
    updated: int = 0
    errors: int = 0


class SyncResponse(BaseModel):
    """Response envelope for POST /sync (server spec §2.2)."""

    status: str
    batchId: str
    tablesProcessed: dict[str, TableResult]
    syncedAt: str
    driveDataReceived: bool
    autoAnalysisTriggered: bool


# ==============================================================================
# Pure helpers
# ==============================================================================


def detectDriveDataReceived(tables: dict[str, Any]) -> bool:
    """
    Return True when the payload contains a ``drive_end`` connection_log row.

    Accepts either raw dicts (from the request body) or :class:`TableData`
    instances so callers can pass either shape.
    """
    connLog = tables.get("connection_log")
    if connLog is None:
        return False
    rows = connLog["rows"] if isinstance(connLog, dict) else connLog.rows
    return any(row.get("event_type") == "drive_end" for row in rows)


def _parseDateTime(value: Any) -> Any:
    """Coerce ISO-format date strings to datetime; pass through everything else."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def _coerceRowColumns(model: type, row: dict[str, Any]) -> None:
    """In-place: parse DateTime column values into datetime objects."""
    from sqlalchemy import DateTime

    for col in model.__table__.columns:  # type: ignore[attr-defined]
        if isinstance(col.type, DateTime) and col.name in row:
            row[col.name] = _parseDateTime(row[col.name])


# ==============================================================================
# Sync core — sync function, called via AsyncSession.run_sync() in prod
# ==============================================================================


def runSyncUpsert(
    session: Session,
    deviceId: str,
    batchId: str,
    tables: dict[str, Any],
    syncHistoryId: int,
) -> dict[str, dict[str, int]]:
    """
    Upsert every accepted table's delta rows inside a single DB transaction.

    Args:
        session: SQLAlchemy sync Session bound to the target engine. Caller
            owns the commit/rollback — this function only issues statements.
        deviceId: Value stamped as ``source_device`` on every row.
        batchId: Unused by the DB writes (kept for symmetry with request
            logging). Actual ``sync_batch_id`` stamped on rows comes from
            ``syncHistoryId``.
        tables: Mapping of accepted-table-name → payload dict/model with a
            ``rows`` list of Pi-native rows (each including an ``id`` field).
        syncHistoryId: PK of the sync_history row that triggered this call;
            stamped into ``sync_batch_id`` on rows that carry that column.

    Returns:
        Mapping of table name → ``{"inserted": N, "updated": M, "errors": 0}``.
        Tables missing from ``tables`` are omitted from the result. Tables
        present with empty rows report zero counts.
    """
    result: dict[str, dict[str, int]] = {}

    for tableName, payload in tables.items():
        model, renames = _TABLE_REGISTRY[tableName]
        rows = payload["rows"] if isinstance(payload, dict) else payload.rows
        if not rows:
            result[tableName] = {"inserted": 0, "updated": 0, "errors": 0}
            continue

        # Shape Pi-native rows into server schema dicts.
        prepared: list[dict[str, Any]] = []
        sourceIds: list[int] = []
        for piRow in rows:
            serverRow: dict[str, Any] = {}
            for key, value in piRow.items():
                # Apply renames (profiles: Pi id → source_profile_id)
                renamedKey = next(
                    (srv for src, srv in renames if src == key),
                    key,
                )
                # The Pi-native id field always maps to source_id regardless
                # of renames — except when a rename has explicitly remapped
                # Pi id onto another column (profiles).
                if key == "id" and not any(src == "id" for src, _ in renames):
                    serverRow["source_id"] = value
                elif key == "id" and any(src == "id" for src, _ in renames):
                    # profiles: id → source_profile_id AND assign a numeric
                    # source_id derived from insertion order within this batch.
                    serverRow[renamedKey] = value
                    serverRow["source_id"] = len(prepared) + 1
                else:
                    serverRow[renamedKey] = value
            serverRow["source_device"] = deviceId
            if "sync_batch_id" in {c.name for c in model.__table__.columns}:
                serverRow["sync_batch_id"] = syncHistoryId
            serverRow["synced_at"] = datetime.now(UTC).replace(tzinfo=None)
            _coerceRowColumns(model, serverRow)
            prepared.append(serverRow)
            sourceIds.append(serverRow["source_id"])

        # Partition into inserts vs updates by checking existing (device, id).
        existing = session.execute(
            select(model.source_id).where(  # type: ignore[attr-defined]
                model.source_device == deviceId,  # type: ignore[attr-defined]
                model.source_id.in_(sourceIds),  # type: ignore[attr-defined]
            ),
        ).scalars().all()
        existingSet = set(existing)
        inserted = sum(1 for sid in sourceIds if sid not in existingSet)
        updated = len(sourceIds) - inserted

        _upsertBatch(session, model, prepared)
        result[tableName] = {
            "inserted": inserted,
            "updated": updated,
            "errors": 0,
        }

    return result


def _upsertBatch(
    session: Session,
    model: type,
    rows: list[dict[str, Any]],
) -> None:
    """Dialect-aware bulk upsert on ``(source_device, source_id)``."""
    if not rows:
        return

    table = model.__table__  # type: ignore[attr-defined]
    dialectName = session.bind.dialect.name  # type: ignore[union-attr]

    # Normalise keys — executemany needs identical columns on every row.
    allKeys: set[str] = set()
    for r in rows:
        allKeys.update(r.keys())
    for r in rows:
        for k in allKeys:
            r.setdefault(k, None)

    if dialectName in {"mysql", "mariadb"}:
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


# ==============================================================================
# sync_history helpers (async)
# ==============================================================================


async def _createSyncHistoryRow(engine: Any, deviceId: str) -> int:
    """Create a sync_history row with status=in_progress; return its id."""
    factory = getAsyncSession(engine)
    async with factory() as session:
        row = SyncHistory(device_id=deviceId, status="in_progress", rows_synced=0)
        session.add(row)
        await session.flush()
        rowId = row.id
        await session.commit()
    return rowId


async def _completeSyncHistoryRow(
    engine: Any,
    historyId: int,
    tablesProcessed: dict[str, dict[str, int]],
    syncedAt: datetime,
) -> None:
    """Mark the sync_history row completed with row counts + per-table summary."""
    totalRows = sum(c["inserted"] + c["updated"] for c in tablesProcessed.values())
    tablesSyncedBlob = json.dumps(tablesProcessed, sort_keys=True)
    factory = getAsyncSession(engine)
    async with factory() as session:
        await session.execute(
            update(SyncHistory)
            .where(SyncHistory.id == historyId)
            .values(
                status="completed",
                rows_synced=totalRows,
                tables_synced=tablesSyncedBlob,
                completed_at=syncedAt,
            ),
        )
        await session.commit()


async def _failSyncHistoryRow(
    engine: Any, historyId: int, message: str,
) -> None:
    """Mark the sync_history row failed (best-effort; swallow DB errors)."""
    try:
        factory = getAsyncSession(engine)
        async with factory() as session:
            await session.execute(
                update(SyncHistory)
                .where(SyncHistory.id == historyId)
                .values(
                    status="failed",
                    error_message=message[:1000],
                    completed_at=datetime.now(UTC).replace(tzinfo=None),
                ),
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — failure logger must not raise
        logger.warning("Failed to mark sync_history %d as failed: %s", historyId, exc)


# ==============================================================================
# Route
# ==============================================================================


router = APIRouter()


def _readMaxPayloadBytes(request: Request) -> int:
    """Return the configured max payload cap in bytes (default 10 MB)."""
    settings = getattr(request.app.state, "settings", None)
    maxMb = getattr(settings, "MAX_SYNC_PAYLOAD_MB", 10) if settings else 10
    return int(maxMb) * 1024 * 1024


@router.post("/sync", response_model=SyncResponse)
async def postSync(request: Request) -> SyncResponse:
    """Accept a Pi delta sync payload and upsert it into the server database."""
    # 1) Payload size cap (check before reading body / parsing JSON).
    maxBytes = _readMaxPayloadBytes(request)
    contentLength = request.headers.get("content-length")
    if contentLength is not None:
        try:
            if int(contentLength) > maxBytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=(
                        f"Payload exceeds max size of {maxBytes // (1024 * 1024)} MB"
                    ),
                )
        except ValueError:
            # Bad header; fall through and let body read enforce the cap.
            pass

    # 2) Parse + validate.
    rawBody = await request.body()
    if len(rawBody) > maxBytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Payload exceeds max size of {maxBytes // (1024 * 1024)} MB",
        )
    try:
        bodyJson = json.loads(rawBody) if rawBody else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid JSON body: {exc.msg}",
        ) from exc

    try:
        syncRequest = SyncRequest.model_validate(bodyJson)
    except Exception as exc:  # pydantic.ValidationError or TypeError
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # 3) Resolve the engine.
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database engine not configured",
        )

    # 4) Create sync_history row in its own transaction.
    historyId = await _createSyncHistoryRow(engine, syncRequest.deviceId)

    # 5) Upsert everything inside one transaction.
    tablesForCore = {
        name: {"rows": td.rows, "lastSyncedId": td.lastSyncedId}
        for name, td in syncRequest.tables.items()
    }
    try:
        factory = getAsyncSession(engine)
        async with factory() as session:
            tablesProcessed = await session.run_sync(
                lambda s: runSyncUpsert(
                    s,
                    deviceId=syncRequest.deviceId,
                    batchId=syncRequest.batchId,
                    tables=tablesForCore,
                    syncHistoryId=historyId,
                ),
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — any DB error → 500
        logger.error("Sync upsert failed for batch %s: %s", syncRequest.batchId, exc)
        await _failSyncHistoryRow(engine, historyId, str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {exc}",
        ) from exc

    # 6) Update sync_history to completed.
    syncedAt = datetime.now(UTC).replace(tzinfo=None)
    await _completeSyncHistoryRow(engine, historyId, tablesProcessed, syncedAt)

    # 7) Build response.
    driveDataReceived = detectDriveDataReceived(tablesForCore)
    return SyncResponse(
        status="ok",
        batchId=syncRequest.batchId,
        tablesProcessed={
            name: TableResult(**counts) for name, counts in tablesProcessed.items()
        },
        syncedAt=syncedAt.isoformat(),
        driveDataReceived=driveDataReceived,
        autoAnalysisTriggered=False,
    )


# ==============================================================================
# Public API
# ==============================================================================

__all__ = [
    "ACCEPTED_TABLES",
    "SyncRequest",
    "SyncResponse",
    "TableData",
    "TableResult",
    "detectDriveDataReceived",
    "router",
    "runSyncUpsert",
]
