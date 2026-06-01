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
# 2026-04-17    | Ralph Agent  | US-CMP-006 — wire auto-analysis trigger into
#               |              | postSync; autoAnalysisTriggered reflects whether
#               |              | a background task was actually enqueued.
# 2026-04-19    | Rex (US-195) | Spool CR #4: coerce missing / None data_source
#               |              | to 'real' on inbound rows so pre-US-195 Pi code
#               |              | still lands tagged.  Runs only on models that
#               |              | declare the column.
# 2026-04-21    | Rex (US-217) | Register battery_health_log in _TABLE_REGISTRY
#               |              | so Pi UPS drain events sync to MariaDB.
# 2026-05-10    | Rex (US-315) | B-065 leverage note: the existing
#               |              | _upsertBatch path (on_duplicate_key_update
#               |              | for MariaDB / on_conflict_do_update for
#               |              | SQLite, keyed on (source_device, source_id))
#               |              | already supports UPDATE propagation for the
#               |              | three opt-in tables (battery_health_log,
#               |              | drive_summary, dtc_log).  No server-side
#               |              | code change is needed -- the bug under
#               |              | B-065 was purely Pi-side cursor mechanics.
#               |              | _PRESERVE_ON_UPDATE keeps source-key columns
#               |              | + synced_at; payload-only columns are upserted
#               |              | (server-side analytics columns the Pi never
#               |              | sends are untouched, satisfying Spool Spec 3
#               |              | for drive_summary).
# 2026-05-12    | Ralph(US-333)| B-079 / TD-027: _createSyncHistoryRow now sets
#               |              | started_at explicitly from datetime.now(UTC)
#               |              | instead of leaning on the model's
#               |              | server_default=func.now() (MariaDB local time)
#               |              | -- both started_at and completed_at now use the
#               |              | same UTC clock so the sync-duration metric is
#               |              | real (seconds) rather than a fixed ~18000s.
# 2026-05-21    | Rex (US-348) | I-040 false-pass redo: _tryAutoAnalysisTrigger
#               |              | now feeds both trigger seams to
#               |              | enqueueAutoAnalysisForSync -- the existing
#               |              | connection_log path AND a new drive_summary
#               |              | payload path.  Empirical from I-040: real Pi
#               |              | syncs deliver drive_summary rows via the table-
#               |              | upsert path but the corresponding connection_log
#               |              | drive_start/drive_end events are absent (or
#               |              | arrive in a different sync batch), so the
#               |              | original seam never fired and analytics fields
#               |              | stayed NULL across drives 11-18.  The trigger
#               |              | now early-returns only when BOTH seams have no
#               |              | drive data.
# 2026-05-21    | Rex (US-350) | B-104 Step 1a (V0.27.17) -- retire the
#               |              | _tryAutoAnalysisTrigger seam entirely.  Drive
#               |              | analytics is now computed server-side from raw
#               |              | realtime_data via the dedicated compute path
#               |              | src.server.analytics.drive_summary_compute -- no
#               |              | path from sync receipt to compute.  US-326 +
#               |              | US-348 were the V0.27.7 + V0.27.16 trigger-seam
#               |              | rewrites; third-cycle false-pass (Argus 2026-
#               |              | 05-21) confirmed the writer-redo class cannot
#               |              | be made empirically reliable on a Pi-side
#               |              | drive-end signal that does not fire on
#               |              | sequencer-driven termination.  Removed:
#               |              | _tryAutoAnalysisTrigger function + its call
#               |              | site + the enqueueAutoAnalysisForSync import.
#               |              | autoAnalysisTriggered stays in SyncResponse for
#               |              | Pi-side wire-format compatibility but is always
#               |              | False (server compute runs out-of-band).
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
from sqlalchemy import func as sa_func
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from src.server.db.connection import getAsyncSession
from src.server.db.models import (
    AiRecommendation,
    AlertLog,
    BatteryHealthLog,
    CalibrationSession,
    ConnectionLog,
    DriveCounter,
    DriveSummary,
    DtcFreezeFrame,
    DtcLog,
    Profile,
    RealtimeData,
    Statistic,
    SyncHistory,
    VehicleInfo,
)

# US-350 / B-104 Step 1a (V0.27.17): enqueueAutoAnalysisForSync import retired.
# Drive analytics is now computed server-side from raw realtime_data via
# src.server.analytics.drive_summary_compute, invoked on a server-side trigger
# (overnight batch + on-demand CLI) that does NOT depend on a Pi-side drive-end
# signal or any sync-receipt seam.

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
    # US-204: DTC capture table.  Append-only, US-194 delta-sync pattern;
    # see src/pi/data/sync_log.py for the Pi-side PK_COLUMN entry.
    "dtc_log": (DtcLog, ()),
    # US-206: drive_summary Pi-sync path (one row per drive, keyed by
    # drive_id -> renamed to 'id' -> mapped to source_id).  The server
    # model is shared with analytics but the Pi-sync natural key is
    # (source_device, source_id); see DriveSummary docstring for the
    # dual-writer contract.
    "drive_summary": (DriveSummary, ()),
    # US-217: battery_health_log capture table.  drain_event_id is the
    # Pi-side PK -> renamed to 'id' on the wire by the sync client
    # -> mapped to source_id by runSyncUpsert, matching every other
    # synced capture table.  One row per UPS drain event.
    "battery_health_log": (BatteryHealthLog, ()),
}

# US-369 (F-109): dtc_freeze_frame is a synced capture table but is NOT a
# generic registry table -- its Pi rows carry a cross-tier shape (vehicle_info_vin
# TEXT + Pi-local dtc_log_id + a JSON-string pid_responses_json) that the
# column-copy upsert path cannot map.  It is accepted at the payload boundary
# here and routed through the dedicated resolver _syncDtcFreezeFrameRows.
DTC_FREEZE_FRAME_TABLE: str = "dtc_freeze_frame"

ACCEPTED_TABLES: frozenset[str] = (
    frozenset(_TABLE_REGISTRY.keys()) | {DTC_FREEZE_FRAME_TABLE}
)

# Columns never overwritten on upsert conflict.
#
# The first four are the server-owned sync bookkeeping columns.  The
# vehicle_info ECU-lineage columns (US-365 / F-108) are SERVER-ONLY: the Pi's
# vehicle_info schema carries only VIN-decoded columns and never sends these,
# so under normal operation the payload-only ``on_duplicate_key_update`` already
# leaves them intact.  They are listed here as a defensive belt-and-braces fix
# (US-365 conditionalOutcome): if a future regression ever put an ECU column in
# a Pi payload, this set still excludes it from the upsert SET clause, so the
# server-authored append-only ECU lineage can never be clobbered -- the same
# guarantee drive_summary's analytics columns rely on (architecture.md §10.7).
# ``ecu_active_marker`` is a generated column (not directly writable) but is
# listed for completeness so no code path attempts to set it.
_PRESERVE_ON_UPDATE = frozenset({
    "id", "source_id", "source_device", "synced_at",
    # US-365 vehicle_info ECU lineage (server-only):
    "ecu_signature", "cal_signature", "ecu_install_timestamp_utc",
    "ecu_removal_timestamp_utc", "notes", "ecu_active_marker",
})


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


class DriveCounterData(BaseModel):
    """Top-level singleton field carrying the Pi's current ``drive_counter``.

    US-314: drive_counter is a single-row state mirror, not an append-only
    delta table.  It rides on the sync request as a sibling of ``tables``
    so the natural-key contract on ``(source_device, source_id)`` does not
    apply (a process-wide counter has no source_id).
    """

    model_config = ConfigDict(extra="forbid")

    lastDriveId: int = Field(
        ..., gt=0,
        description="Pi-local high-water mark for drive_id; must be positive.",  # b044-exempt: pydantic Field description
    )


class SyncRequest(BaseModel):
    """Top-level sync request body."""

    model_config = ConfigDict(extra="forbid")

    deviceId: str = Field(
        ..., min_length=1, description="Source device identifier (e.g. chi-eclipse-01).",  # b044-exempt: pydantic Field description
    )
    batchId: str = Field(
        ..., min_length=1, description="Pi-assigned batch identifier.",
    )
    tables: dict[str, TableData] = Field(
        ..., description="Per-table delta payload keyed by accepted table name.",
    )
    driveCounter: DriveCounterData | None = Field(
        default=None,
        description="Optional Pi drive_counter singleton snapshot (US-314).",  # b044-exempt: pydantic Field description
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
        # US-369: dtc_freeze_frame needs cross-tier FK resolution; it is
        # processed AFTER the generic loop so any dtc_log / vehicle_info rows
        # in this same batch are already upserted and resolvable.
        if tableName == DTC_FREEZE_FRAME_TABLE:
            continue
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
            # US-372 (F-076): mirror the Pi drive id onto drive_id.  The Pi
            # sends only ``id`` (-> source_id) for drive_summary; without this
            # the drive_id mirror would insert NULL and violate the
            # chk_drive_id_source_id invariant.  conditionalOutcome 1: a writer
            # that knows one column writes (drive_id = source_id) so the
            # invariant holds.
            if tableName == "drive_summary" and serverRow.get("drive_id") is None:
                serverRow["drive_id"] = serverRow.get("source_id")
            columnNames = {c.name for c in model.__table__.columns}
            if "sync_batch_id" in columnNames:
                serverRow["sync_batch_id"] = syncHistoryId
            serverRow["synced_at"] = datetime.now(UTC).replace(tzinfo=None)
            # US-195 (Spool CR #4): coerce missing / None data_source to
            # 'real' so pre-US-195 Pi rows don't land as NULL.  Only applies
            # to models that declare the column.
            if "data_source" in columnNames:
                if serverRow.get("data_source") is None:
                    serverRow["data_source"] = "real"
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

    # US-369 (F-109): dtc_freeze_frame last -- its FK resolution reads the
    # dtc_log / vehicle_info rows just upserted above.
    if DTC_FREEZE_FRAME_TABLE in tables:
        payload = tables[DTC_FREEZE_FRAME_TABLE]
        ffRows = payload["rows"] if isinstance(payload, dict) else payload.rows
        result[DTC_FREEZE_FRAME_TABLE] = _syncDtcFreezeFrameRows(
            session, deviceId, ffRows, syncHistoryId,
        )

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
# dtc_freeze_frame cross-tier sync (US-369 / F-109)
# ==============================================================================
#
# The Pi vehicle_info PK is ``vin`` (TEXT); the server PK is an integer ``id``
# (US-368 cross-tier design).  A Pi freeze-frame row therefore references the
# active vehicle by ``vehicle_info_vin``, a Pi-local ``dtc_log_id``, and a
# JSON-string ``pid_responses_json``.  This resolver maps that shape onto the
# server schema:
#
#   * ``vehicle_info_vin`` -> integer ``vehicle_info_id`` of the ECU era whose
#     ``[ecu_install, ecu_removal]`` window contains ``captured_at`` (the Q4
#     temporal join).  An unresolvable vin FAILS LOUDLY -- no silent re-resolve
#     (US-369 conditionalOutcome 1): a freeze-frame must bind to a real ECU era.
#   * Pi-local ``dtc_log_id`` -> server ``dtc_log.id`` via (source_device,
#     source_id).  Left NULL with a WARNING if the parent DTC has not synced.
#   * ``pid_responses_json`` JSON string -> dict for the JSON column.
#
# This binds the FK once, at sync time, by capture-time window; later
# stamp_ecu_swap rows never re-point an existing freeze-frame (V-3).  The direct
# (non-sync) insert SSOT remains ``insertDtcFreezeFrame``; sync uses the
# idempotent (source_device, source_id) upsert so a cursor-reset re-sync does
# not duplicate, and the whole batch stays in one transaction.


def _coercePidResponses(value: Any) -> dict:
    """Coerce a Pi ``pid_responses_json`` value into a dict for the JSON column.

    The Pi stores it as a TEXT JSON string; ``{}`` (the graceful-degradation
    case) and an already-decoded dict both pass through.  Anything unparseable
    degrades to ``{}`` rather than failing the whole sync batch.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _resolveVehicleInfoIdForCapture(
    session: Session, vin: str | None, capturedAt: datetime,
) -> int | None:
    """Resolve a Pi ``vehicle_info_vin`` to the server ``vehicle_info.id``.

    Returns the id of the ECU-lineage row whose ``[ecu_install, ecu_removal]``
    window contains ``capturedAt`` (removal NULL = currently-active/open).

    Args:
        session: Open SQLAlchemy session.
        vin: The Pi-side active-vehicle VIN (``None`` when VIN decode had not
            landed at capture time -- the FK is then left NULL).
        capturedAt: When the freeze-frame was captured (UTC).

    Returns:
        The matching ``vehicle_info.id``, or ``None`` when ``vin`` is ``None``.

    Raises:
        ValueError: If ``vin`` is given but no -- or more than one -- ECU era
            window contains ``capturedAt`` (fail loudly; no silent re-resolve).
    """
    if vin is None:
        return None
    ids = session.execute(
        select(VehicleInfo.id).where(
            VehicleInfo.vin == vin,
            VehicleInfo.ecu_install_timestamp_utc <= capturedAt,
            or_(
                VehicleInfo.ecu_removal_timestamp_utc.is_(None),
                VehicleInfo.ecu_removal_timestamp_utc >= capturedAt,
            ),
        ),
    ).scalars().all()
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise ValueError(
            f"dtc_freeze_frame sync: no vehicle_info row for vin {vin!r} "
            f"active at {capturedAt.isoformat()}; cross-tier FK resolution "
            f"failed (no silent re-resolve)",
        )
    raise ValueError(
        f"dtc_freeze_frame sync: {len(ids)} vehicle_info rows for vin {vin!r} "
        f"active at {capturedAt.isoformat()}; ECU-lineage windows overlap "
        f"(append-only single-active invariant violated)",
    )


def _resolveServerDtcLogId(
    session: Session, deviceId: str, piDtcLogId: int | None,
) -> int | None:
    """Map a Pi-local ``dtc_log_id`` to the server ``dtc_log.id``.

    Resolution is by the sync natural key (``source_device``, ``source_id``).
    Returns ``None`` (with a WARNING) when the parent DTC has not synced yet --
    the freeze-frame still lands; the FK fills in on a later resync.
    """
    if piDtcLogId is None:
        return None
    serverId = session.execute(
        select(DtcLog.id).where(
            DtcLog.source_device == deviceId,
            DtcLog.source_id == piDtcLogId,
        ),
    ).scalar_one_or_none()
    if serverId is None:
        logger.warning(
            "dtc_freeze_frame sync: Pi dtc_log_id %s (device %s) not yet "
            "synced; freeze-frame dtc_log_id left NULL",
            piDtcLogId, deviceId,
        )
    return serverId


def _syncDtcFreezeFrameRows(
    session: Session,
    deviceId: str,
    rows: list[dict[str, Any]],
    syncHistoryId: int,
) -> dict[str, int]:
    """Upsert Pi freeze-frame rows onto the server schema with FK resolution.

    See the section header above for the cross-tier mapping contract.
    """
    if not rows:
        return {"inserted": 0, "updated": 0, "errors": 0}

    prepared: list[dict[str, Any]] = []
    sourceIds: list[int] = []
    for piRow in rows:
        sourceId = piRow["id"]
        capturedAt = _parseDateTime(piRow.get("captured_at_timestamp_utc"))
        vehicleInfoId = _resolveVehicleInfoIdForCapture(
            session, piRow.get("vehicle_info_vin"), capturedAt,
        )
        dtcLogId = _resolveServerDtcLogId(
            session, deviceId, piRow.get("dtc_log_id"),
        )
        prepared.append({
            "source_id": sourceId,
            "source_device": deviceId,
            "sync_batch_id": syncHistoryId,
            "synced_at": datetime.now(UTC).replace(tzinfo=None),
            "dtc_log_id": dtcLogId,
            "captured_at_timestamp_utc": capturedAt,
            "pid_responses_json": _coercePidResponses(
                piRow.get("pid_responses_json"),
            ),
            "vehicle_info_id": vehicleInfoId,
            "notes": piRow.get("notes"),
        })
        sourceIds.append(sourceId)

    existing = session.execute(
        select(DtcFreezeFrame.source_id).where(
            DtcFreezeFrame.source_device == deviceId,
            DtcFreezeFrame.source_id.in_(sourceIds),
        ),
    ).scalars().all()
    existingSet = set(existing)
    inserted = sum(1 for sid in sourceIds if sid not in existingSet)
    updated = len(sourceIds) - inserted

    _upsertBatch(session, DtcFreezeFrame, prepared)
    return {"inserted": inserted, "updated": updated, "errors": 0}


# ==============================================================================
# drive_counter singleton upsert (US-314 / B-064)
# ==============================================================================


def runDriveCounterUpsert(session: Session, lastDriveId: int) -> None:
    """Upsert the singleton ``drive_counter`` row, never rewinding.

    The server table is single-row (CHECK ``id=1``) and tracks the Pi's
    most recent ``drive_id``.  This helper writes the value via a
    monotonic upsert: if the existing row already holds a value greater
    than ``lastDriveId`` (e.g., a stale sync arriving after a fresher
    one), the existing value is preserved.  Forward-only is the
    invariant -- analytics joins on ``drive_id`` corrupt silently if
    the counter rewinds.

    Args:
        session: Caller-owned SQLAlchemy session; commit is the caller's
            responsibility (matches :func:`runSyncUpsert`'s contract so
            both writes share one transaction).
        lastDriveId: Pi-local ``last_drive_id`` from the request payload.
            Must be positive (Pydantic enforces ``gt=0`` upstream).

    Raises:
        ValueError: If ``lastDriveId`` is not a positive integer (defence
            in depth -- callers route through Pydantic which already
            rejects this case).
    """
    if not isinstance(lastDriveId, int) or lastDriveId <= 0:
        raise ValueError(
            f"lastDriveId must be a positive integer, got {lastDriveId!r}",
        )

    table = DriveCounter.__table__
    dialectName = session.bind.dialect.name  # type: ignore[union-attr]

    if dialectName in {"mysql", "mariadb"}:
        stmt = mysql_insert(table).values(id=1, last_drive_id=lastDriveId)
        # GREATEST(existing, incoming) keeps the row monotonic even if
        # an out-of-order sync delivers a stale lastDriveId.
        stmt = stmt.on_duplicate_key_update(
            last_drive_id=sa_func.greatest(
                table.c.last_drive_id, stmt.inserted.last_drive_id,
            ),
        )
    elif dialectName == "sqlite":
        stmt = sqlite_insert(table).values(id=1, last_drive_id=lastDriveId)
        # SQLite has no GREATEST; CASE expresses the same semantics.
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "last_drive_id": sa_func.max(
                    table.c.last_drive_id, stmt.excluded.last_drive_id,
                ),
            },
        )
    else:
        raise ValueError(
            f"Unsupported dialect for upsert: {dialectName!r}. "
            "Expected mysql, mariadb, or sqlite.",
        )

    session.execute(stmt)


# ==============================================================================
# sync_history helpers (async)
# ==============================================================================


async def _createSyncHistoryRow(engine: Any, deviceId: str) -> int:
    """Create a sync_history row with status=in_progress; return its id.

    ``started_at`` is set explicitly from the same UTC clock that stamps
    ``completed_at`` (see :func:`_completeSyncHistoryRow`).  The model still
    declares ``server_default=func.now()`` as a belt-and-braces fallback, but on
    MariaDB ``NOW()`` returns the server's *local* time — pairing that with the
    UTC ``completed_at`` made ``completed_at - started_at`` a fixed ~18000s
    (the America/Chicago offset) instead of a real sync duration.  Writing both
    columns from ``datetime.now(UTC)`` here is the TD-027 / B-079 fix.
    """
    factory = getAsyncSession(engine)
    async with factory() as session:
        row = SyncHistory(
            device_id=deviceId,
            status="in_progress",
            rows_synced=0,
            started_at=datetime.now(UTC).replace(tzinfo=None),
        )
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
    driveCounter = syncRequest.driveCounter
    try:
        factory = getAsyncSession(engine)
        async with factory() as session:
            def _runAllUpserts(s: Session) -> dict[str, dict[str, int]]:
                processed = runSyncUpsert(
                    s,
                    deviceId=syncRequest.deviceId,
                    batchId=syncRequest.batchId,
                    tables=tablesForCore,
                    syncHistoryId=historyId,
                )
                # US-314: Pi drive_counter snapshot rides on the same
                # transaction so a partial failure rolls back BOTH the
                # table upserts and the counter advance.
                if driveCounter is not None:
                    runDriveCounterUpsert(s, driveCounter.lastDriveId)
                return processed

            tablesProcessed = await session.run_sync(_runAllUpserts)
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

    # 7) US-350 / B-104 Step 1a (V0.27.17): the V0.27.7-V0.27.16
    #    auto-analysis trigger is retired.  Server-side drive analytics now
    #    run via the out-of-band compute path (overnight systemd timer +
    #    on-demand CLI in src.server.cli.recompute_drive_analytics) which
    #    reads raw realtime_data directly -- no dependency on a Pi-side
    #    drive-end marker.  ``autoAnalysisTriggered`` stays in the response
    #    shape for Pi-side wire-format compatibility but is always False.
    driveDataReceived = detectDriveDataReceived(tablesForCore)
    autoAnalysisTriggered = False

    # 8) Build response.
    return SyncResponse(
        status="ok",
        batchId=syncRequest.batchId,
        tablesProcessed={
            name: TableResult(**counts) for name, counts in tablesProcessed.items()
        },
        syncedAt=syncedAt.isoformat(),
        driveDataReceived=driveDataReceived,
        autoAnalysisTriggered=autoAnalysisTriggered,
    )


# US-350 / B-104 Step 1a (V0.27.17): _tryAutoAnalysisTrigger DELETED.
#
# The V0.27.7-V0.27.16 sync-receipt trigger seam (paired-event extraction +
# drive_summary-payload extraction -> enqueueAutoAnalysisForSync ->
# _ensureDriveSummary writer) is retired entirely.  Drive analytics now run
# server-side via src.server.analytics.drive_summary_compute, invoked by
# the nightly systemd timer (deploy/server-analytics-batch.timer) and the
# on-demand CLI (src.server.cli.recompute_drive_analytics).  Both read raw
# realtime_data MIN/MAX/COUNT directly and do not depend on any Pi-side
# drive-end signal.  Argus 2026-05-21 RCA: the writer-redo class shipped
# three times (US-326 / US-348) because the Pi-side trigger (DriveDetector
# drive-end signal) does not fire on sequencer-driven termination -- the
# server compute path is structurally invariant to that defect.
#
# Re-introducing a sync-receipt trigger here is an architectural regression
# (B-104 Step 1a).  If a future story needs to nudge the recompute path on
# sync receipt, invoke the compute module directly (src.server.analytics.
# drive_summary_compute.compute_drive_summary) on a deliberate seam --
# never resurrect this private trigger helper.


# ==============================================================================
# Public API
# ==============================================================================

__all__ = [
    "ACCEPTED_TABLES",
    "DriveCounterData",
    "SyncRequest",
    "SyncResponse",
    "TableData",
    "TableResult",
    "detectDriveDataReceived",
    "router",
    "runDriveCounterUpsert",
    "runSyncUpsert",
]
