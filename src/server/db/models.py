################################################################################
# File Name: models.py
# Purpose/Description: SQLAlchemy ORM models for the server-side MariaDB schema.
#                      Mirrors Pi SQLite tables (with source tracking) plus
#                      server-only and analytics tables.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-CMP-003 — all 15
#               |              | MariaDB tables (8 synced, 3 server-only, 4
#               |              | analytics) per server spec §1.2
# 2026-04-19    | Rex (US-195) | Spool CR #4: add data_source column to every
#               |              | capture-table model that can receive non-real
#               |              | rows (RealtimeData, Statistic, ConnectionLog,
#               |              | CalibrationSession, Profile, DriveSummary).
# 2026-04-21    | Rex (US-217) | BatteryHealthLog model mirroring Pi's
#               |              | battery_health_log table (UPS drain events).
# ================================================================================
################################################################################

"""
SQLAlchemy ORM models for the Eclipse OBD-II server MariaDB database.

Three categories of tables:

1. **Synced** (8) — Mirror Pi SQLite tables with server additions:
   ``source_id``, ``source_device``, ``synced_at``, ``sync_batch_id``,
   and ``UNIQUE(source_device, source_id)`` for upsert.

2. **Server-only** (3) — ``sync_history``, ``analysis_history``, ``devices``.
   Track operational state that only exists on the server.

3. **Analytics** (4) — ``drive_summary``, ``drive_statistics``,
   ``trend_snapshots``, ``anomaly_log``. Computed by the analytics engine.

Usage::

    from src.server.db.models import Base, RealtimeData, DriveSummary

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ---- Base --------------------------------------------------------------------


class Base(DeclarativeBase):
    """Declarative base for all server models."""

    pass


# ==============================================================================
# data_source tagging (US-195 / Spool CR #4)
# ==============================================================================
#
# Every capture-table row carries a ``data_source`` tag identifying its
# origin.  Analytics and AI prompting filter to ``'real'`` so replay /
# physics_sim / fixture rows never contaminate baselines.  The live-OBD
# path picks up the default via ``server_default="real"`` on every model
# so forward-compatible inbound rows from pre-US-195 Pi code still land
# as 'real' (the sync API also coerces missing / None to 'real').
# ==============================================================================

DATA_SOURCE_VALUES: tuple[str, ...] = (
    'real', 'replay', 'physics_sim', 'fixture',
)
DATA_SOURCE_DEFAULT: str = 'real'
DATA_SOURCE_LENGTH: int = 16


# ==============================================================================
# Synced Tables — Pi mirror + source tracking
# ==============================================================================
#
# Every synced table has:
#   id            — MariaDB autoincrement PK (server-owned)
#   source_id     — INT NOT NULL  (original Pi row ID)
#   source_device — VARCHAR(64) NOT NULL
#   synced_at     — DATETIME (server sets on ingest)
#   sync_batch_id — INT (links to sync_history)
#   UNIQUE(source_device, source_id)
# ==============================================================================


class RealtimeData(Base):
    """Real-time OBD-II sensor readings, mirrored from Pi."""

    __tablename__ = "realtime_data"
    __table_args__ = (
        UniqueConstraint("source_device", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_device: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    sync_batch_id: Mapped[int | None] = mapped_column(Integer)

    # Pi-native columns
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    parameter_name: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))
    profile_id: Mapped[str | None] = mapped_column(String(64))
    data_source: Mapped[str | None] = mapped_column(
        String(DATA_SOURCE_LENGTH), server_default=DATA_SOURCE_DEFAULT,
    )
    # US-200: Pi-local drive_id from drive_counter.  Indexed for
    # per-drive analytics queries.  NULL = pre-US-200 row or row written
    # outside an active drive.
    drive_id: Mapped[int | None] = mapped_column(Integer, index=True)


class Statistic(Base):
    """Per-parameter statistical summaries, mirrored from Pi."""

    __tablename__ = "statistics"
    __table_args__ = (
        UniqueConstraint("source_device", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_device: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    sync_batch_id: Mapped[int | None] = mapped_column(Integer)

    # Pi-native columns
    parameter_name: Mapped[str] = mapped_column(String(128), nullable=False)
    analysis_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    max_value: Mapped[float | None] = mapped_column(Float)
    min_value: Mapped[float | None] = mapped_column(Float)
    avg_value: Mapped[float | None] = mapped_column(Float)
    mode_value: Mapped[float | None] = mapped_column(Float)
    std_1: Mapped[float | None] = mapped_column(Float)
    std_2: Mapped[float | None] = mapped_column(Float)
    outlier_min: Mapped[float | None] = mapped_column(Float)
    outlier_max: Mapped[float | None] = mapped_column(Float)
    sample_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    data_source: Mapped[str | None] = mapped_column(
        String(DATA_SOURCE_LENGTH), server_default=DATA_SOURCE_DEFAULT,
    )
    # US-200: Pi-local drive_id of the drive whose data produced this
    # statistic row.  NULL for multi-drive rollups or pre-US-200 rows.
    drive_id: Mapped[int | None] = mapped_column(Integer, index=True)


class Profile(Base):
    """Driving profiles / modes, mirrored from Pi."""

    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint("source_device", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_device: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )

    # Pi-native columns (Pi uses TEXT PK 'id', mapped to source_profile_id here)
    source_profile_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    polling_interval_ms: Mapped[int | None] = mapped_column(Integer, default=1000)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    data_source: Mapped[str | None] = mapped_column(
        String(DATA_SOURCE_LENGTH), server_default=DATA_SOURCE_DEFAULT,
    )


class VehicleInfo(Base):
    """Vehicle information decoded from VIN, mirrored from Pi."""

    __tablename__ = "vehicle_info"
    __table_args__ = (
        UniqueConstraint("source_device", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_device: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )

    # Pi-native columns (Pi uses VIN as TEXT PK)
    vin: Mapped[str | None] = mapped_column(String(17))
    make: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(64))
    year: Mapped[int | None] = mapped_column(Integer)
    engine: Mapped[str | None] = mapped_column(String(128))
    fuel_type: Mapped[str | None] = mapped_column(String(32))
    transmission: Mapped[str | None] = mapped_column(String(64))
    drive_type: Mapped[str | None] = mapped_column(String(32))
    body_class: Mapped[str | None] = mapped_column(String(64))
    plant_city: Mapped[str | None] = mapped_column(String(64))
    plant_country: Mapped[str | None] = mapped_column(String(64))
    raw_api_response: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )


class AiRecommendation(Base):
    """AI-generated tuning recommendations, mirrored from Pi."""

    __tablename__ = "ai_recommendations"
    __table_args__ = (
        UniqueConstraint("source_device", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_device: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    sync_batch_id: Mapped[int | None] = mapped_column(Integer)

    # Pi-native columns
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    priority_rank: Mapped[int | None] = mapped_column(Integer, default=3)
    is_duplicate_of: Mapped[int | None] = mapped_column(Integer)
    profile_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )


class ConnectionLog(Base):
    """OBD-II connection events, mirrored from Pi."""

    __tablename__ = "connection_log"
    __table_args__ = (
        UniqueConstraint("source_device", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_device: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    sync_batch_id: Mapped[int | None] = mapped_column(Integer)

    # Pi-native columns
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    mac_address: Mapped[str | None] = mapped_column(String(17))
    success: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int | None] = mapped_column(Integer, default=0)
    data_source: Mapped[str | None] = mapped_column(
        String(DATA_SOURCE_LENGTH), server_default=DATA_SOURCE_DEFAULT,
    )
    # US-200: Pi-local drive_id.  drive_start / drive_end events carry
    # the drive's id; pre-crank connection attempts remain NULL.
    drive_id: Mapped[int | None] = mapped_column(Integer, index=True)


class AlertLog(Base):
    """Threshold violation alerts, mirrored from Pi."""

    __tablename__ = "alert_log"
    __table_args__ = (
        UniqueConstraint("source_device", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_device: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    sync_batch_id: Mapped[int | None] = mapped_column(Integer)

    # Pi-native columns
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_name: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    profile_id: Mapped[str | None] = mapped_column(String(64))
    # US-200: Pi-local drive_id.  Mid-drive alerts carry the owning id;
    # pre-crank hardware alerts (BT probe failures) remain NULL.
    drive_id: Mapped[int | None] = mapped_column(Integer, index=True)


class DtcLog(Base):
    """Diagnostic Trouble Codes (DTCs) captured on the Pi, mirrored here.

    Pi populates this table from Mode 03 + Mode 07 at session start
    (US-204) and Mode 03 again on MIL rising-edge events.  Server
    mirrors with the same (source_device, source_id) upsert key as the
    other synced capture tables.

    See ``src/pi/obdii/dtc_log_schema.py`` for the Pi-side DDL.
    """

    __tablename__ = "dtc_log"
    __table_args__ = (
        UniqueConstraint("source_device", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_device: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    sync_batch_id: Mapped[int | None] = mapped_column(Integer)

    # Pi-native columns
    dtc_code: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    first_seen_timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    last_seen_timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    # US-200 drive scoping.
    drive_id: Mapped[int | None] = mapped_column(Integer, index=True)
    # US-195 origin tag.
    data_source: Mapped[str | None] = mapped_column(
        String(DATA_SOURCE_LENGTH), server_default=DATA_SOURCE_DEFAULT,
    )


class CalibrationSession(Base):
    """Calibration/tuning sessions, mirrored from Pi."""

    __tablename__ = "calibration_sessions"
    __table_args__ = (
        UniqueConstraint("source_device", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_device: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )

    # Pi-native columns
    start_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    profile_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    data_source: Mapped[str | None] = mapped_column(
        String(DATA_SOURCE_LENGTH), server_default=DATA_SOURCE_DEFAULT,
    )


class BatteryHealthLog(Base):
    """UPS drain-event records, mirrored from Pi (US-217 / Spool Session 6).

    One row per drain event (Pi lost wall power OR CIO ran a scheduled
    drill).  Opened at event-start with ``start_soc`` + ``load_class``;
    closed at event-end with ``end_soc`` + ``runtime_seconds``.  The
    Pi-side PK is ``drain_event_id`` -- renamed to ``id`` on the wire by
    the sync client so the server's ``source_id`` mapping stays uniform
    with every other synced capture table.

    Backs the monthly drain-test cadence (CIO directive 3, May-Sept
    driving season).  Analytics downstream (TBD story) will use
    run-length decay of ``runtime_seconds`` to flag batteries past
    their replacement threshold.
    """

    __tablename__ = "battery_health_log"
    __table_args__ = (
        UniqueConstraint("source_device", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_device: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    sync_batch_id: Mapped[int | None] = mapped_column(Integer)

    # Pi-native columns
    start_timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    end_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    start_soc: Mapped[float] = mapped_column(Float, nullable=False)
    end_soc: Mapped[float | None] = mapped_column(Float)
    runtime_seconds: Mapped[int | None] = mapped_column(Integer)
    ambient_temp_c: Mapped[float | None] = mapped_column(Float)
    load_class: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="production",
    )
    notes: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str | None] = mapped_column(
        String(DATA_SOURCE_LENGTH), server_default=DATA_SOURCE_DEFAULT,
    )


# ==============================================================================
# Server-Only Tables
# ==============================================================================


class SyncHistory(Base):
    """Log of sync batches received from Pi devices."""

    __tablename__ = "sync_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    rows_synced: Mapped[int | None] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="in_progress",
    )
    tables_synced: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)


class AnalysisHistory(Base):
    """Log of AI analysis runs on drive data."""

    __tablename__ = "analysis_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    drive_id: Mapped[int | None] = mapped_column(Integer)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="in_progress",
    )
    result_summary: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)


class AnalysisRecommendation(Base):
    """Ranked recommendations produced by a single AnalysisHistory run.

    Server-authored rows, one per recommendation returned by Ollama for the
    parent ``analysis_history`` row. Distinct from the Pi-mirror
    ``ai_recommendations`` table — that table stores Pi-side AI output and
    carries ``source_id``/``source_device``. Rows here are written only by
    the server's analysis service (US-CMP-005) and link to
    ``analysis_history.id`` via ``analysis_id``.
    """

    __tablename__ = "analysis_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )


class Device(Base):
    """Registered Pi devices that sync data to this server."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    api_key_hash: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )


# ==============================================================================
# Analytics Tables
# ==============================================================================


class DriveSummary(Base):
    """One row per detected drive -- reconciled single-writer table (US-214).

    **Reconciliation contract (US-214, Option 1 -- Pi writes first, analytics
    updates).**

    * Pi-sync path writes the row first with ``source_device`` +
      ``source_id`` (== drive_id) + ``drive_id`` + drive-start metadata
      (ambient IAT, starting battery, barometric). Analytics columns
      (``device_id``, ``start_time``, ``end_time``, ``duration_seconds``,
      ``row_count``, ``is_real``) stay NULL until analytics runs.
    * Analytics path (:func:`src.server.services.analysis._ensureDriveSummary`)
      runs at drive-end via the auto-analysis trigger. It finds the
      existing Pi-sync row by ``(source_device, drive_id)`` and UPDATEs
      the analytics fields in place -- no second row is created.
    * If Pi-sync hasn't landed yet when analytics runs (race or out-of-order
      sync), analytics INSERTs a fully-populated row. A later Pi-sync of
      the same (source_device, source_id) lands on the same row via the
      UNIQUE constraint and only overwrites its own columns (is_real and
      analytics fields are preserved per ``sync.py::_PRESERVE_ON_UPDATE``
      + the fact Pi doesn't send those columns).

    **Legacy path (pre-US-200, no drive_id in connection_log).** Analytics
    falls back to the historical ``(device_id, start_time)`` find-or-create
    so pre-US-200 replay / historical data still produces single rows.
    These rows leave ``source_device`` / ``source_id`` / ``drive_id`` NULL
    -- the UNIQUE constraint is unaffected because SQL treats NULL as
    distinct in UNIQUE.

    **Invariants** (enforced by :mod:`src.server.services.analysis` and
    the reconciliation migration ``scripts/reconcile_drive_summary.py``):

    * One row per ``(source_device, drive_id)`` for post-US-200 drives.
    * ``is_real`` stays ``TRUE`` only after analytics confirms at drive-end.
      Pi-sync-only rows pre-analytics have ``is_real = NULL``.
    * Pi-sync columns are authoritative for drive-start metadata.
      Analytics must not overwrite them.

    Pre-US-214 history: rows were written by two uncoordinated writers
    producing two rows per drive. The one-shot migration
    ``scripts/reconcile_drive_summary.py`` merges those dual rows on the
    live DB before the US-214 deploy. See ``offices/pm/inbox/
    2026-04-20-from-ralph-us206-drive-summary-reconciliation-note.md``
    for the historical context.
    """

    __tablename__ = "drive_summary"
    __table_args__ = (
        UniqueConstraint("source_device", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # device_id is the analytics-path natural-key column.  Pi-sync rows
    # populate source_device instead (see UNIQUE above); the sync
    # adapter in src.server.api.sync can optionally mirror
    # source_device into device_id but the NULL path keeps the Pi and
    # analytics writers fully decoupled until reconciliation lands.
    device_id: Mapped[str | None] = mapped_column(String(64))

    # Analytics-path columns (pre-US-206; nullable so the Pi-sync path
    # can leave them NULL without tripping NOT NULL).
    start_time: Mapped[datetime | None] = mapped_column(DateTime)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    profile_id: Mapped[str | None] = mapped_column(String(64))
    row_count: Mapped[int | None] = mapped_column(Integer, default=0)
    is_real: Mapped[bool | None] = mapped_column(
        Boolean, server_default="0",
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    # US-195: data_source on DriveSummary lets analytics filter by origin
    # without joining through realtime_data.  Inherits the dominant source
    # of the drive's rows; 'real' by default since is_real=False is already
    # distinct for pre-US-195 sim drives.
    data_source: Mapped[str | None] = mapped_column(
        String(DATA_SOURCE_LENGTH), server_default=DATA_SOURCE_DEFAULT,
    )

    # ---- US-206: Pi-sync columns ---------------------------------
    # source_id = Pi's drive_counter id for this drive.
    # source_device = Pi host id (e.g. "chi-eclipse-01").
    # The UNIQUE constraint above is the Pi-sync path's natural key.
    source_id: Mapped[int | None] = mapped_column(Integer)
    source_device: Mapped[str | None] = mapped_column(String(64))
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )
    sync_batch_id: Mapped[int | None] = mapped_column(Integer)

    # Pi-captured metadata (one snapshot per drive at CRANKING entry).
    drive_start_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    ambient_temp_at_start_c: Mapped[float | None] = mapped_column(Float)
    starting_battery_v: Mapped[float | None] = mapped_column(Float)
    barometric_kpa_at_start: Mapped[float | None] = mapped_column(Float)

    # drive_id is duplicated (alongside source_id) so per-drive joins
    # that don't know the source_device still work.  Indexed because
    # US-200 analytics queries filter on drive_id.
    drive_id: Mapped[int | None] = mapped_column(Integer, index=True)


class DriveStatistic(Base):
    """Per-drive per-parameter statistics computed by analytics engine."""

    __tablename__ = "drive_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    drive_id: Mapped[int] = mapped_column(Integer, nullable=False)
    parameter_name: Mapped[str] = mapped_column(String(128), nullable=False)
    min_value: Mapped[float | None] = mapped_column(Float)
    max_value: Mapped[float | None] = mapped_column(Float)
    avg_value: Mapped[float | None] = mapped_column(Float)
    std_dev: Mapped[float | None] = mapped_column(Float)
    outlier_min: Mapped[float | None] = mapped_column(Float)
    outlier_max: Mapped[float | None] = mapped_column(Float)
    sample_count: Mapped[int | None] = mapped_column(Integer)
    computed_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )


class TrendSnapshot(Base):
    """Rolling trend calculations across last N drives."""

    __tablename__ = "trend_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parameter_name: Mapped[str] = mapped_column(String(128), nullable=False)
    window_size: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    slope: Mapped[float | None] = mapped_column(Float)
    avg_peak: Mapped[float | None] = mapped_column(Float)
    avg_mean: Mapped[float | None] = mapped_column(Float)
    drift_pct: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )


class AnomalyLog(Base):
    """Flagged anomalies where parameters deviate from historical norms."""

    __tablename__ = "anomaly_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    drive_id: Mapped[int] = mapped_column(Integer, nullable=False)
    parameter_name: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_value: Mapped[float] = mapped_column(Float, nullable=False)
    expected_min: Mapped[float | None] = mapped_column(Float)
    expected_max: Mapped[float | None] = mapped_column(Float)
    deviation_sigma: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )


class Baseline(Base):
    """CIO-approved per-parameter baseline values from real drives.

    Written only by :mod:`src.server.analytics.calibration` under the
    ``--calibrate --apply`` CLI flow (US-162 / spec §3.3). The unique
    constraint on ``(device_id, parameter_name)`` keeps the table to one
    row per (device, parameter), and every apply either inserts a new
    row or updates the existing one (upsert-by-pair).
    """

    __tablename__ = "baselines"
    __table_args__ = (
        UniqueConstraint("device_id", "parameter_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_name: Mapped[str] = mapped_column(String(128), nullable=False)
    avg_value: Mapped[float] = mapped_column(Float, nullable=False)
    min_value: Mapped[float | None] = mapped_column(Float)
    max_value: Mapped[float | None] = mapped_column(Float)
    std_dev: Mapped[float | None] = mapped_column(Float)
    sample_count: Mapped[int | None] = mapped_column(Integer)
    established_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )


# ---- Public API --------------------------------------------------------------

__all__ = [
    "Base",
    # Synced
    "RealtimeData",
    "Statistic",
    "Profile",
    "VehicleInfo",
    "AiRecommendation",
    "ConnectionLog",
    "AlertLog",
    "CalibrationSession",
    "DtcLog",
    # Server-only
    "SyncHistory",
    "AnalysisHistory",
    "AnalysisRecommendation",
    "Device",
    # Analytics
    "DriveSummary",
    "DriveStatistic",
    "TrendSnapshot",
    "AnomalyLog",
    "Baseline",
]
