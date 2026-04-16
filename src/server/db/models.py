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
    """One row per detected drive — aggregated from connection_log events."""

    __tablename__ = "drive_summary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    profile_id: Mapped[str | None] = mapped_column(String(64))
    row_count: Mapped[int | None] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(),
    )


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
    # Server-only
    "SyncHistory",
    "AnalysisHistory",
    "Device",
    # Analytics
    "DriveSummary",
    "DriveStatistic",
    "TrendSnapshot",
    "AnomalyLog",
]
