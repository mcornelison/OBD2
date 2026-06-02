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
# 2026-05-21    | Rex (US-351) | B-104 Step 1b: DriveStatistic re-shaped to
#               |              | Atlas Q4 DDL -- composite PK (drive_id,
#               |              | parameter_name), FK drive_id -> drive_summary.id
#               |              | ON DELETE CASCADE, data_quality ENUM
#               |              | (full/sparse/below_threshold) enforced via
#               |              | CHECK constraint, computed_at gains onupdate=
#               |              | func.now() for observable idempotency, NOT NULL
#               |              | tightened on sample_count + parameter_name,
#               |              | INDEX idx_drive_statistics_quality added.
# 2026-05-28    | Rex (US-363) | F-107 attribution-anomaly tripwire: add
#               |              | data_quality column (+ CHECK + index) to
#               |              | DriveSummary and extend the DriveStatistic
#               |              | data_quality enum with 'attribution_anomaly'.
#               |              | Shared constant DATA_QUALITY_ATTRIBUTION_ANOMALY
#               |              | is the SSOT value both compute paths write when
#               |              | detect_overlapping_drives (US-362) finds overlap.
# 2026-05-28    | Rex (US-371) | F-076: rename DriveStatistic.drive_id ->
#               |              | summary_id (the column has always held a
#               |              | drive_summary.id FK, never a Pi drive_id).
#               |              | Complete rename, no alias; consumers updated.
# 2026-05-28    | Rex (US-365) | F-108: vehicle_info ECU lineage -- add
#               |              | ecu_signature/cal_signature/ecu_install_
#               |              | timestamp_utc/ecu_removal_timestamp_utc/notes
#               |              | + STORED ecu_active_marker generated column with
#               |              | UNIQUE index enforcing exactly-one-active-ECU
#               |              | (MariaDB lacks partial unique indexes).  Append-
#               |              | only invariant; server-only (Pi schema unchanged).
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
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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


# ==============================================================================
# vehicle_info ECU lineage (US-365 / F-108)
# ==============================================================================
#
# The server-side vehicle_info table carries an APPEND-ONLY ECU-lineage history
# so per-drive analytics can join a drive to the ECU active at the drive's time
# window (US-367 backfill; US-368 dtc_freeze_frame FK; US-370 speed calibration
# FK).
#
# **Append-only invariant.**  A row's ECU-identity columns (``ecu_signature``,
# ``ecu_install_timestamp_utc``) are immutable once written.  An ECU change is
# recorded by CLOSING the currently-active row (set ``ecu_removal_timestamp_utc``)
# and OPENING a new row -- never by UPDATEing identity columns in place, because
# dtc_freeze_frame (US-368) and per-drive joins reference a SPECIFIC row by FK /
# time-window and a mutated identity would silently rewrite history.  The
# sanctioned mutator is the ``stamp_ecu_swap`` writer path (US-366); there are no
# in-place identity UPDATEs anywhere in src/server/.
#
# **Exactly one currently-active ECU.**  At most one row may have
# ``ecu_removal_timestamp_utc IS NULL``.  MariaDB has no partial unique index and
# a plain UNIQUE on the timestamp would permit many NULLs, so the invariant is
# enforced at the DB layer (both SQLite + MariaDB) by a STORED generated marker
# column -- ``1`` when the row is active, ``NULL`` when closed -- carrying a
# UNIQUE index: the value ``1`` must be unique (=> <=1 active row) while ``NULL``
# repeats freely (closed rows are unconstrained).  Per US-365 conditionalOutcome
# this is the chosen mechanism over an app-layer-only check.
#
# ``ecu_signature`` for a legacy (pre-tracking) row backfilled by the v0010
# migration takes this honest sentinel rather than a fabricated ECU id; US-367's
# authoritative backfill (Spool-signed naming) overwrites it.
VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN: str = "PRE_TRACKING_UNKNOWN"
# US-368 AC#2: surfaced as a SQL table comment (DESCRIBE/SHOW CREATE TABLE) so the
# append-only invariant is visible to anyone touching the table directly, not just
# readers of this module's docstrings.  Ties the rule to the dtc_freeze_frame FK
# that depends on it (a mutated identity column would silently rewrite the ECU era
# a freeze-frame points to).
VEHICLE_INFO_APPEND_ONLY_COMMENT: str = (
    "ECU-lineage identity columns are append-only: correct an ECU/cal signature "
    "by CLOSING the prior row (set ecu_removal_timestamp_utc) and OPENING a new "
    "row, never by UPDATEing identity columns in place.  dtc_freeze_frame (US-368) "
    "and per-drive joins reference a SPECIFIC row by FK + time window, so a mutated "
    "identity would silently rewrite history.  Sanctioned mutator: stamp_ecu_swap "
    "(US-366) close+open.  ecu_id (US-376 / B-076) is an immutable per-lineage-row "
    "identity reference into the normalized ecu dimension; the transitional "
    "ecu_signature/cal_signature TEXT columns are a derived snapshot kept coherent "
    "with that row (deprecated-transitional, drop in a later B-076 slice)."
)
VEHICLE_INFO_SINGLE_ACTIVE_INDEX: str = "uq_vehicle_info_single_active"
VEHICLE_INFO_ACTIVE_MARKER_COLUMN: str = "ecu_active_marker"
# The marker's generated expression; shared as the SSOT between the ORM column
# and the v0010 migration's ADD COLUMN DDL so both environments are identical.
VEHICLE_INFO_ACTIVE_MARKER_EXPR: str = (
    "CASE WHEN ecu_removal_timestamp_utc IS NULL THEN 1 ELSE NULL END"
)


# ---- US-376 / B-076 first slice: normalized ECU identity dimension ----------
#
# ``ecu`` is a pure, immutable identity dimension keyed on the
# (ecu_signature, cal_signature) PAIR.  ``vehicle_info`` references a specific
# identity row by FK (``ecu_id``) instead of duplicating free-text signatures,
# so ECU identity is SSOT and a reflash is its OWN row (a new pair) rather than
# an in-place rewrite of one identity.  No lineage / timestamp columns live here
# -- the install/removal window stays on ``vehicle_info`` (the lineage table);
# ``ecu`` answers only "which ECU + calibration is this".
ECU_TABLE: str = "ecu"
ECU_SIGNATURE_LENGTH: int = 32
ECU_PAIR_UNIQUE: str = "uq_ecu_signature_cal_signature"
# The signature value used when an ECU's real calibration id is not yet known.
# Distinct from a reflash: a row may be resolved from this sentinel to the real
# CALID in place ONCE (the sanctioned carve-out below); a reflash is a new row.
ECU_CAL_SIGNATURE_UNKNOWN: str = "UNKCAL"
# Immutability carve-out (Atlas Rule 13 refinement, Spool Q5 edge): ecu identity
# columns are immutable EXCEPT the write-once UNKCAL -> real-CALID same-row
# resolution -- NOT absolute immutability.  Surfaced as a SQL table comment so
# the rule is visible to anyone touching the table directly.
ECU_IMMUTABILITY_COMMENT: str = (
    "ECU identity is immutable: an (ecu_signature, cal_signature) pair is a "
    "stable identity and a reflash is a NEW row, never an in-place edit.  SOLE "
    "sanctioned in-place mutation: resolving a write-once UNKCAL cal_signature "
    "to the real CALID once known (Spool Q5) -- this is distinct from a reflash "
    "(which is a new row).  vehicle_info.ecu_id references a SPECIFIC identity "
    "row; per-lineage-row identity is otherwise immutable."
)
# The three grounded seed identity rows (Spool-signed signatures 2026-06-01):
#   (MD346675, 6675)          -- prior STOCK factory ECU (drives <=24).
#   (MD335287, UNKCAL)        -- new modified-EPROM ECU; CALID not yet read.
#   (PRE_TRACKING_UNKNOWN, PRE_TRACKING_UNKNOWN) -- legacy pre-tracking sentinel
#       (its cal == its sig so a legacy vehicle_info row whose cal_signature is
#        NULL resolves cleanly via COALESCE(cal, sig) at v0011 backfill time).
ECU_SEED_PAIRS: tuple[tuple[str, str], ...] = (
    ("MD346675", "6675"),
    ("MD335287", ECU_CAL_SIGNATURE_UNKNOWN),
    (VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN, VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN),
)
# vehicle_info FK column name (SSOT shared with the v0011 migration).
VEHICLE_INFO_ECU_FK_COLUMN: str = "ecu_id"
VEHICLE_INFO_ECU_FK_NAME: str = "fk_vehicle_info_ecu"


class Ecu(Base):
    """Normalized, immutable ECU identity dimension (US-376 / B-076 first slice).

    One row per distinct ``(ecu_signature, cal_signature)`` identity.  This is
    a DIMENSION, not a lineage table: it carries no install/removal window
    (that stays on :class:`VehicleInfo`).  ``vehicle_info`` references a row
    here by FK so the identity is SSOT instead of duplicated free text, and a
    reflash is its own identity row (a new pair) rather than an in-place rewrite.

    Identity is immutable EXCEPT the sanctioned write-once UNKCAL -> real-CALID
    resolution (see :data:`ECU_IMMUTABILITY_COMMENT`); nothing in this slice
    builds that resolution path -- the carve-out is documentation honesty so the
    table comment does not overclaim absolute immutability.
    """

    __tablename__ = ECU_TABLE
    __table_args__ = (
        # Pair UNIQUE: identity is the (signature, cal) pair, so a reflash
        # (same ECU, new calibration) is a distinct, allowed row.
        UniqueConstraint(
            "ecu_signature", "cal_signature", name=ECU_PAIR_UNIQUE,
        ),
        {"comment": ECU_IMMUTABILITY_COMMENT},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ecu_signature: Mapped[str] = mapped_column(
        String(ECU_SIGNATURE_LENGTH), nullable=False,
    )
    cal_signature: Mapped[str] = mapped_column(
        String(ECU_SIGNATURE_LENGTH), nullable=False,
    )

    vehicle_infos: Mapped[list[VehicleInfo]] = relationship(
        back_populates="ecu",
    )


class VehicleInfo(Base):
    """Vehicle information decoded from VIN (mirrored from Pi) + ECU lineage.

    The VIN-decoded columns are Pi-sync mirrored.  The ECU-lineage columns
    (``ecu_signature``, ``cal_signature``, ``ecu_install_timestamp_utc``,
    ``ecu_removal_timestamp_utc``, ``notes``) are SERVER-ONLY (the Pi never
    sends them; ``sync.py::_PRESERVE_ON_UPDATE`` keeps them intact across
    re-syncs) and follow the append-only ECU-lineage invariant documented above
    this class.  See ``stamp_ecu_swap`` / ``show_ecu_lineage`` (US-366) for the
    writer + reader CLIs.
    """

    __tablename__ = "vehicle_info"
    __table_args__ = (
        UniqueConstraint("source_device", "source_id"),
        # US-365: enforce "exactly one currently-active ECU" via the generated
        # marker column (1 == active).  Name matches the v0010 migration's
        # ADD UNIQUE INDEX so SHOW CREATE TABLE is identical across environments.
        UniqueConstraint(
            VEHICLE_INFO_ACTIVE_MARKER_COLUMN,
            name=VEHICLE_INFO_SINGLE_ACTIVE_INDEX,
        ),
        # US-368 AC#2: append-only invariant surfaced as a SQL table comment.
        {"comment": VEHICLE_INFO_APPEND_ONLY_COMMENT},
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

    # ---- US-365 / F-108: server-only ECU lineage -----------------------------
    # Identity columns (immutable; corrections via close+open, never UPDATE):
    ecu_signature: Mapped[str] = mapped_column(Text, nullable=False)
    ecu_install_timestamp_utc: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
    )
    # Mutable / write-once / append-only columns:
    cal_signature: Mapped[str | None] = mapped_column(Text)
    # ecu_removal_timestamp_utc is write-once (NULL -> close timestamp).  NULL
    # marks the currently-active ECU.  Must be declared BEFORE the generated
    # marker that references it (SQLite generated-column ordering rule).
    ecu_removal_timestamp_utc: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    # Generated single-active marker (see class + section docstrings).  STORED so
    # it can carry a UNIQUE index on both SQLite (3.31+) and MariaDB (10.2+).
    ecu_active_marker: Mapped[int | None] = mapped_column(
        Integer,
        Computed(VEHICLE_INFO_ACTIVE_MARKER_EXPR, persisted=True),
    )
    # ---- US-376 / B-076: FK to the normalized ecu identity dimension ---------
    # NOT NULL: every lineage row references a specific immutable ecu identity
    # row (SSOT).  The transitional ``ecu_signature`` / ``cal_signature`` TEXT
    # columns above are KEPT this slice but must stay coherent with the joined
    # ecu row (see :mod:`src.server.db.vehicle_info_coherence`); the writer
    # (stamp_ecu_swap) DERIVES them from the ecu row.  They are deprecated-
    # transitional and drop in a later B-076 slice.
    ecu_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{ECU_TABLE}.id", name=VEHICLE_INFO_ECU_FK_NAME),
        nullable=False,
    )
    ecu: Mapped[Ecu] = relationship(back_populates="vehicle_infos")


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


class DtcFreezeFrame(Base):
    """Mode 02 freeze-frame snapshot captured when a DTC trips (US-368 / F-109).

    One row per freeze-frame: the 16-PID JSON snapshot of "what the engine was
    doing" at capture time, an FK to the ``dtc_log`` row it belongs to, and an FK
    to the ``vehicle_info`` row for the ECU active at capture time.  Pi captures
    the snapshot on a MIL_ON rising edge (Mode 02 enumeration); the server
    ``insertDtcFreezeFrame`` writer-path (``src/server/api/dtc_freeze_frame.py``)
    enforces the temporal invariant ``ecu_install <= captured_at <= ecu_removal``
    so the FK can only bind to the ECU era that was actually installed -- the Pi
    cannot enforce this because its ``vehicle_info`` schema carries no ECU lineage
    (server-only per US-365).

    Synced capture table: carries the standard ``(source_device, source_id)``
    upsert key so US-369 Pi->server sync mirrors rows like every other capture
    table.  ``vehicle_info`` is append-only (see its table comment) so this FK
    never points at a row whose identity was rewritten in place.

    ``pid_responses_json`` defaults to ``{}`` for the graceful-degradation case
    (DTC tripped but Mode 02 PIDs unavailable -- US-368 V-6).
    """

    __tablename__ = "dtc_freeze_frame"
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

    # FK to the DTC this freeze-frame belongs to.  Nullable: cross-tier id
    # resolution (Pi dtc_log id -> server dtc_log.id) is a US-369 sync concern;
    # a freeze-frame may land before its parent DTC mapping is resolved.
    dtc_log_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("dtc_log.id"), index=True,
    )
    captured_at_timestamp_utc: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
    )
    # 16-PID Mode 02 snapshot.  Generic JSON: MariaDB JSON column, SQLite TEXT.
    pid_responses_json: Mapped[dict | None] = mapped_column(JSON, default=dict)
    # FK to the ECU active at capture time; bound by the server writer-path's
    # temporal invariant.  Nullable at the DB layer (sync may deliver before
    # server-side resolution); the writer-path requires + validates it.
    vehicle_info_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("vehicle_info.id"), index=True,
    )
    # US-369 (F-109): operator-facing context for degraded captures (Mode 02
    # unavailable -> pid_responses_json={}).  Synced verbatim from the Pi row
    # so a post-mortem keeps the gap explanation, and show_dtc_freeze_frame can
    # surface it (conditionalOutcome 2).
    notes: Mapped[str | None] = mapped_column(Text)


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


# US-363 / F-107: shared value for the V0.27.18 dual-attribution tripwire.
# A drive whose raw realtime_data window overlaps another drive's window
# (detect_overlapping_drives, US-362) is stamped 'attribution_anomaly' on both
# drive_summary and drive_statistics so the dual-emission pattern is observable
# downstream as a per-row flag -- observability, never a hard refusal.  This is
# the single source of truth for the literal; both compute paths import it.
DATA_QUALITY_ATTRIBUTION_ANOMALY: str = "attribution_anomaly"


# US-377 / F-107: shared VARCHAR width for the data_quality columns on both
# drive_summary and drive_statistics.  Must stay >= the longest CHECK-permitted
# value ('attribution_anomaly', 19 chars).  The original VARCHAR(16) was too
# narrow: the V0.28.1 IRL drill hit MariaDB DataError 1406 ("Data too long")
# recomputing the dual-attribution drives 23+24 because SQLite never enforces
# VARCHAR width so the fresh-DB tests passed while production failed.  20 gives
# one char of headroom; the width-invariant guard
# (test_migration_0012_data_quality_widen) enforces "width >= longest value".
DATA_QUALITY_COLUMN_LENGTH: int = 20


# drive_summary.data_quality enum: the server compute path writes only 'full'
# (clean) or 'attribution_anomaly' (overlap detected).  drive_summary carries
# no sample-count notion, so the sparse / below_threshold buckets that apply to
# drive_statistics are deliberately NOT allowed here.
DRIVE_SUMMARY_DATA_QUALITY_DEFAULT: str = "full"
DRIVE_SUMMARY_DATA_QUALITY_VALUES: tuple[str, ...] = (
    DRIVE_SUMMARY_DATA_QUALITY_DEFAULT,
    DATA_QUALITY_ATTRIBUTION_ANOMALY,
)


# US-372 / F-076: the drive_summary.drive_id <-> source_id invariant.  The
# Pi-sync path maps the Pi drive_counter id onto ``source_id`` and the server
# writers mirror it onto ``drive_id``; legacy analytics-only rows carry neither.
# The CHECK forbids the silent-divergence smell (source_id set, drive_id NULL --
# the V0.27.x state that bit per-drive joins): a row is either fully
# un-attributed (both NULL) or the two columns agree.  Q1 ruling 2026-05-28:
# backfill + invariant; the SSOT-purist column drop is deferred to a later
# V0.28+ normalization.  The name matches the v0010 migration's ADD CONSTRAINT
# so SHOW CREATE TABLE is identical across environments.
DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME: str = "chk_drive_id_source_id"
# Both NULL, OR both NOT NULL and equal.  The NOT-NULL guards are load-bearing:
# under SQL three-valued logic a bare ``drive_id = source_id`` evaluates to NULL
# (not FALSE) when exactly one side is NULL, and a CHECK passes on NULL -- so the
# asymmetric smell row (source_id set, drive_id NULL) would slip through without
# them.
DRIVE_SUMMARY_DRIVE_ID_CHECK_CLAUSE: str = (
    "(drive_id IS NULL AND source_id IS NULL) OR "
    "(drive_id IS NOT NULL AND source_id IS NOT NULL AND drive_id = source_id)"
)


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
        # US-363: enforce the data_quality enum at the DB layer (SQLite +
        # MariaDB) so a bad value can never be persisted.  Name matches the
        # v0010 migration's ADD CONSTRAINT so SHOW CREATE TABLE is identical
        # across environments.
        CheckConstraint(
            f"data_quality IN "
            f"({','.join(repr(v) for v in DRIVE_SUMMARY_DATA_QUALITY_VALUES)})",
            name="ck_drive_summary_data_quality",
        ),
        Index("idx_drive_summary_data_quality", "data_quality"),
        # US-372 / F-076: drive_id and source_id never silently diverge.
        CheckConstraint(
            DRIVE_SUMMARY_DRIVE_ID_CHECK_CLAUSE,
            name=DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME,
        ),
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

    # US-363 / F-107: data_quality tripwire flag.  The server compute path
    # (compute_drive_summary) sets 'attribution_anomaly' when the drive's
    # realtime_data window overlaps another drive's window (the Drive 23/24
    # dual-emission pattern), else 'full'.  The Pi never sends this column, so
    # the payload-only sync upsert (sync.py, server-only columns untouched)
    # leaves an analytics-written value intact across re-syncs.
    data_quality: Mapped[str] = mapped_column(
        String(DATA_QUALITY_COLUMN_LENGTH),
        nullable=False,
        server_default=DRIVE_SUMMARY_DATA_QUALITY_DEFAULT,
    )


DRIVE_STATISTICS_DATA_QUALITY_VALUES: tuple[str, ...] = (
    "full", "sparse", "below_threshold", DATA_QUALITY_ATTRIBUTION_ANOMALY,
)
DRIVE_STATISTICS_DATA_QUALITY_DEFAULT: str = "full"


class DriveStatistic(Base):
    """Per-drive per-parameter statistics computed by the server analytics path.

    B-104 Step 1b (US-351): Atlas-specified DDL.  The natural upsert key is
    ``(summary_id, parameter_name)``; ``summary_id`` references the server-side
    ``drive_summary.id`` (server-minted autoincrement PK), so cascading the
    DriveSummary delete tears down its DriveStatistic children automatically.

    US-371 (F-076): the column was renamed ``drive_id`` -> ``summary_id``.  It
    never held a Pi-assigned drive_id -- it has always been a ``drive_summary.id``
    FK -- so the old name lied to readers.  The rename is COMPLETE (no alias).

    ``data_quality`` carries Atlas Refinement B's classification (computed by
    :func:`src.server.analytics.drive_statistics_compute.compute_drive_statistics`
    from ``sample_count``): ``below_threshold`` < 10, ``sparse`` 10-99,
    ``full`` >= 100.  ENUM is enforced via SQLite-compatible CHECK constraint.

    ``computed_at`` carries ``onupdate=func.now()`` so a re-run of the
    idempotent compute updates the timestamp (observable idempotency: same
    raw data + same logic = same column values, but ``computed_at`` advances).
    """

    __tablename__ = "drive_statistics"
    __table_args__ = (
        CheckConstraint(
            f"data_quality IN "
            f"({','.join(repr(v) for v in DRIVE_STATISTICS_DATA_QUALITY_VALUES)})",
            name="ck_drive_statistics_data_quality",
        ),
        Index("idx_drive_statistics_quality", "data_quality"),
    )

    summary_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("drive_summary.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    parameter_name: Mapped[str] = mapped_column(
        String(64), primary_key=True, nullable=False,
    )
    min_value: Mapped[float | None] = mapped_column(Float)
    max_value: Mapped[float | None] = mapped_column(Float)
    avg_value: Mapped[float | None] = mapped_column(Float)
    std_dev: Mapped[float | None] = mapped_column(Float)
    outlier_min: Mapped[float | None] = mapped_column(Float)
    outlier_max: Mapped[float | None] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    data_quality: Mapped[str] = mapped_column(
        String(DATA_QUALITY_COLUMN_LENGTH),
        nullable=False,
        server_default=DRIVE_STATISTICS_DATA_QUALITY_DEFAULT,
    )
    computed_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )


# US-370 / F-076: per-ECU SPEED-PID multiplicative correction.  The new
# modified-EPROM ECU reads ~2x actual ground speed (Spool 2026-05-22 OBD probe +
# Drive 26 telemetry); each ECU identity may carry its own VSS calibration, so
# analytics that aggregate SPEED multiply the OBD reading by this ECU's factor.
#
# US-374 re-key (2026-06-01, B-076 first slice): the v0010 build keyed this table
# on its OWN ``ecu_signature`` natural key (Atlas option-(c) 2026-05-29, a
# transitional shape).  Now that the normalized ``ecu`` identity dimension exists
# (US-376), the calibration references the SSOT identity by ``ecu_id`` FK ->
# ``ecu.id`` with UNIQUE(ecu_id) -- one calibration row per ecu identity.  Because
# ``ecu`` is pair-keyed on (ecu_signature, cal_signature), a reflash is its OWN
# ecu row and therefore gets its OWN calibration row (SPEED correction is
# per-tune-state, Spool Q5 2026-06-01).  The v0011 migration backfills ecu_id by
# matching each existing row's ecu_signature to its ecu row, then DROPs the
# transitional ecu_signature column + its UNIQUE key.
SPEED_PID_CALIBRATION_TABLE: str = "speed_pid_calibration"
# Transitional -- the v0010 CREATE DDL (forward-only, untouched) still uses these
# to build the option-(c) ecu_signature shape that v0011 re-keys away.  The ORM
# no longer carries an ecu_signature column.
SPEED_PID_CALIBRATION_ECU_SIGNATURE_LENGTH: int = 32
SPEED_PID_CALIBRATION_ECU_SIGNATURE_UNIQUE: str = (
    "uq_speed_pid_calibration_ecu_signature"
)
# US-374 FK shape SSOT names (shared with the v0011 re-key migration).
SPEED_PID_CALIBRATION_ECU_FK_COLUMN: str = "ecu_id"
SPEED_PID_CALIBRATION_ECU_FK_NAME: str = "fk_speed_pid_calibration_ecu"
SPEED_PID_CALIBRATION_ECU_ID_UNIQUE: str = "uq_speed_pid_calibration_ecu_id"
SPEED_PID_CALIBRATION_CAPTURE_METHOD_CHECK_NAME: str = (
    "ck_speed_pid_calibration_capture_method"
)
# F-076 §1 schema ENUM.  Realized as VARCHAR + CHECK (not a native MySQL ENUM)
# for cross-DB parity with SQLite -- the same pattern the data_quality enums use.
# Nullable: a CHECK ``IN (...)`` passes on NULL under SQL three-valued logic.
SPEED_PID_CALIBRATION_CAPTURE_METHOD_VALUES: tuple[str, ...] = (
    "gps_correlation", "gear_math", "vendor_spec", "default",
)
# Default factor = 1.0 (assume OEM calibration) until a per-ECU correction is
# captured (F-076 §1 "Default").
SPEED_PID_CALIBRATION_DEFAULT_FACTOR: float = 1.0
# Analytics prefix-gate (US-370 VC#9): only provenance values beginning with
# this prefix are treated as empirically-derived; rough-seed / gear-math seed
# rows are excluded from queries that demand empirical calibration.
SPEED_PID_CALIBRATION_EMPIRICAL_PROVENANCE_PREFIX: str = "empirical-"


class SpeedPidCalibration(Base):
    """Per-ECU multiplicative SPEED-PID correction factor (US-370 / US-374).

    One row per ``ecu`` identity.  ``correction_factor`` is multiplicative:
    ``OBD-reported SPEED x correction_factor = ground-truth speed``.  Analytics
    that integrate SPEED (distance, average speed, gear inference) resolve the
    drive's ECU identity (via ``vehicle_info`` for the drive's time window) and
    apply this factor before integrating.

    ``ecu_id`` is a NOT NULL FK -> :class:`Ecu` with ``UNIQUE(ecu_id)`` (US-374
    re-key, B-076 first slice).  This replaces the transitional v0010 option-(c)
    ``ecu_signature`` natural key: the calibration now references the SSOT ECU
    identity dimension instead of duplicating a free-text signature.  Because
    ``ecu`` is pair-keyed on (ecu_signature, cal_signature), a reflash is its own
    identity row and therefore gets its own calibration row -- SPEED correction
    is per-tune-state (Spool Q5 2026-06-01).

    ``provenance`` is NOT NULL and (via the
    :mod:`src.server.analytics.speed_pid_calibration` writer-path) non-empty:
    every factor must record how it was derived.  The empirical-prefix gate
    (``provenance LIKE 'empirical-%'``) separates measured calibrations from
    rough bootstrap seeds.
    """

    __tablename__ = SPEED_PID_CALIBRATION_TABLE
    __table_args__ = (
        # US-374: one calibration row per ecu identity (UNIQUE FK).  Name matches
        # the v0011 re-key migration's ADD CONSTRAINT so SHOW CREATE TABLE is
        # identical across environments.
        UniqueConstraint(
            SPEED_PID_CALIBRATION_ECU_FK_COLUMN,
            name=SPEED_PID_CALIBRATION_ECU_ID_UNIQUE,
        ),
        # capture_method enum enforced via CHECK (cross-DB; NULL allowed).
        CheckConstraint(
            f"capture_method IN ("
            f"{','.join(repr(v) for v in SPEED_PID_CALIBRATION_CAPTURE_METHOD_VALUES)})",
            name=SPEED_PID_CALIBRATION_CAPTURE_METHOD_CHECK_NAME,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ecu_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{ECU_TABLE}.id", name=SPEED_PID_CALIBRATION_ECU_FK_NAME),
        nullable=False,
    )
    correction_factor: Mapped[float] = mapped_column(Float, nullable=False)
    capture_method: Mapped[str | None] = mapped_column(String(32))
    captured_at_timestamp_utc: Mapped[datetime | None] = mapped_column(DateTime)
    captured_by: Mapped[str | None] = mapped_column(String(128))
    provenance: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    ecu: Mapped[Ecu] = relationship()


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


class DriveCounter(Base):
    """Server-side mirror of the Pi's :data:`drive_counter` singleton (US-314).

    Mirrors the Pi-local counter shipped in US-200.  A single row keyed on
    ``id=1`` (CHECK constraint enforced by the live MariaDB DDL in
    :mod:`scripts.apply_server_migrations`) carries ``last_drive_id`` --
    the high-water mark for the most recent drive minted on the Pi.

    Pre-fix B-064 / US-314: the server table was created via the US-200
    catch-up migration but no sync writer ever advanced it.  The field
    drifted (Pi at drive_id=10 vs server at last_drive_id=3) until US-314
    wired :func:`src.server.api.sync.runDriveCounterUpsert` into the
    POST /api/v1/sync handler.

    Schema parity:

    - Pi  (SQLite):  ``id INTEGER PK CHECK(id=1), last_drive_id INTEGER``
    - Srv (MariaDB): ``id INT PK CHECK(id=1), last_drive_id BIGINT``

    The CHECK(id=1) constraint is intentionally NOT modelled here -- the
    upsert path always passes id=1 and the test path uses SQLite which
    accepts the constraint as advisory.  The MariaDB DDL still enforces it.
    """

    __tablename__ = "drive_counter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_drive_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0"),
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
    "Ecu",
    "ECU_TABLE",
    "ECU_SIGNATURE_LENGTH",
    "ECU_PAIR_UNIQUE",
    "ECU_CAL_SIGNATURE_UNKNOWN",
    "ECU_IMMUTABILITY_COMMENT",
    "ECU_SEED_PAIRS",
    "VEHICLE_INFO_ECU_FK_COLUMN",
    "VEHICLE_INFO_ECU_FK_NAME",
    "AiRecommendation",
    "ConnectionLog",
    "AlertLog",
    "CalibrationSession",
    "DtcLog",
    "DtcFreezeFrame",
    "VEHICLE_INFO_APPEND_ONLY_COMMENT",
    # Server-only
    "SyncHistory",
    "AnalysisHistory",
    "AnalysisRecommendation",
    "Device",
    # Analytics
    "DriveSummary",
    "DriveStatistic",
    "DRIVE_STATISTICS_DATA_QUALITY_VALUES",
    "DRIVE_STATISTICS_DATA_QUALITY_DEFAULT",
    "DATA_QUALITY_COLUMN_LENGTH",
    "TrendSnapshot",
    "AnomalyLog",
    "Baseline",
    "DriveCounter",
]
