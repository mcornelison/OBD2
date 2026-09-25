################################################################################
# File Name: sensor_schema.py
# Purpose/Description: Single-source, versioned DDL contract for the EDR raw-
#                      sensor tables (edr_imu_sample + edr_light_sample). Authored
#                      ONCE here in src/common/ so the Pi (SQLite, now) and the
#                      future server (MariaDB, F-115) derive their tables from the
#                      same module and cannot diverge (A-4 anti-divergence gate).
#                      Verbatim per the EDR sensor-reader ADR (2026-06-30) section
#                      2.2. Pi-local only this phase -- no server table is created.
# Author: Rex (US-408)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Rex (US-408) | Initial -- EDR versioned raw-sensor schema (F-114,
#                               ADR section 2.2). Forward-only migration shape
#                               (section 2.5); schema_version stamped every row.
# 2026-09-15    | Rex (US-764) | EDR_COLUMNS structured column list for the server
#                               DDL generator (server_ddl.py). DDL strings untouched
#                               (D8; SHA-256 pinned in tests/common/test_edr_contract.py).
# 2026-09-24    | Rex (US-810) | edr_imu_derived gains the five gyro RATE bias
#                               columns + ensureEdrImuDerivedGyroRateBiasColumns.
# ================================================================================
################################################################################
"""Versioned single-source DDL for the EDR raw-sensor tables (F-114).

The DDL below is the sole authority for the ``edr_imu_sample`` and
``edr_light_sample`` shapes. The Pi creates its SQLite tables from
:data:`EDR_SCHEMAS` / :data:`EDR_INDEXES` at startup; when server sync lands
(F-115) the MariaDB migration is generated from this same module, so neither
tier hand-writes its own DDL. This is the A-4 anti-divergence gate.

Conventions mirror ``src/pi/obdii/database_schema.py``: ``CREATE TABLE IF NOT
EXISTS`` (idempotent), snake_case columns, the ``data_source`` CHECK contract
(US-195/US-212), and ``INTEGER PRIMARY KEY AUTOINCREMENT``.
"""

from __future__ import annotations

import sqlite3

# Bare-int module constant, mirroring ``power_watch.RECORD_SCHEMA_VERSION``.
# Stamped into every row (DDL DEFAULT below + the persistence subscriber, US-410).
# Forward-only: bump when the contract changes (ADR section 2.5).
SCHEMA_VERSION: int = 1

# --- edr_imu_sample -----------------------------------------------------------
# One row per IMU burst (accel+gyro+mag+temp read together), keyed by ``seq``
# (per-poll producer counter). ADR section 2.2.
SCHEMA_EDR_IMU_SAMPLE = f"""
CREATE TABLE IF NOT EXISTS edr_imu_sample (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc        TEXT    NOT NULL,          -- ISO-8601 UTC wall-clock (Sample.tsUtc)
    ts_capture    REAL    NOT NULL,          -- monotonic seconds (Sample.tsCapture) for alignment
    seq           INTEGER NOT NULL,          -- per-poll producer counter; gap/drop detection
    accel_x REAL, accel_y REAL, accel_z REAL,   -- m/s^2 (gravity included)
    gyro_x  REAL, gyro_y  REAL, gyro_z  REAL,   -- rad/s
    mag_x   REAL, mag_y   REAL, mag_z   REAL,   -- uT (AK09916 magnetometer)
    temp_c  REAL,                               -- IMU die temperature, degC
    drive_id      INTEGER,                    -- NULL when no active RUNNING drive (stamped EXPLICITLY, section 2.4)
    data_source   TEXT    NOT NULL DEFAULT 'real'
                  CHECK (data_source IN ('real','replay','physics_sim','fixture')),
    schema_version INTEGER NOT NULL DEFAULT {SCHEMA_VERSION}
);
"""

# --- edr_light_sample ---------------------------------------------------------
# One row per light poll; lux is NULL when the sensor saturates (honest -- never
# inf/overflow), raw channel counts always recorded. ADR section 2.2.
SCHEMA_EDR_LIGHT_SAMPLE = f"""
CREATE TABLE IF NOT EXISTS edr_light_sample (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc        TEXT    NOT NULL,
    ts_capture    REAL    NOT NULL,
    seq           INTEGER NOT NULL,
    lux           REAL,                       -- NULL when the sensor saturates (honest)
    visible       INTEGER,                    -- raw channel counts (relative dimming, saturation check)
    infrared      INTEGER,
    full_spectrum INTEGER,
    gain          TEXT,                       -- 'low'|'med'|'high'|'max' -- the reading's gain context
    integration_ms INTEGER,                   -- integration time at read
    drive_id      INTEGER,
    data_source   TEXT    NOT NULL DEFAULT 'real'
                  CHECK (data_source IN ('real','replay','physics_sim','fixture')),
    schema_version INTEGER NOT NULL DEFAULT {SCHEMA_VERSION}
);
"""

# --- edr_imu_derived ----------------------------------------------------------
# US-805 (ARCH-045). The PitchFusion OUTPUTS, kept OUT of edr_imu_sample by CIO
# ruling 2026-09-22: a raw reading never changes, a computed value changes when
# the ALGORITHM changes. Mixed into one table, early and late rows would mean
# subtly different things with nothing marking where the maths moved.
#
# Written by imu_state_bridge -- the component that ALREADY HOLDS the values, so
# no new coupling -- decimated to imu.persistHz with the SAME keep-1-of-N factor
# edr_persistence_subscriber uses, so a row lands on the same sample index as its
# raw sibling and ts_capture matches EXACTLY rather than approximately. NOT the
# 4 Hz fusion rate: raw persists at 2 Hz, so a 4 Hz derived table would leave
# half its rows with no possible sibling and force interpolation of a fusion
# output against its own input.
#
# NO FOREIGN KEY to edr_imu_sample.id, deliberately: that id is the PI's id-space
# and arrives on the server as source_id (A-45 -- a row manually minted into it
# was silently overwritten by the Pi's own). The join is
# (source_device, ts_capture), which is why ts_capture is NOT NULL here.
SCHEMA_EDR_IMU_DERIVED = f"""
CREATE TABLE IF NOT EXISTS edr_imu_derived (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc        TEXT    NOT NULL,          -- EVENT time (ssot-design-pattern A-double-prime)
    ts_capture    REAL    NOT NULL,          -- monotonic seconds; THE join key to the raw sibling
    seq           INTEGER NOT NULL,          -- per-poll producer counter, as the raw table
    pitch_deg     REAL,                      -- NULL under gyro_implausible -- that null is a FINDING
    stop_count    INTEGER,                   -- confirmed ZUPT stops in the rolling bias window
    bias_rad      REAL,                      -- mount-tilt bias subtracted from the fused pitch
    fusion_version INTEGER NOT NULL,         -- WHICH algorithm produced the row; the point of the split
    drive_id      INTEGER,                   -- NULL when no active RUNNING drive, as the raw table
    data_source   TEXT    NOT NULL DEFAULT 'real'
                  CHECK (data_source IN ('real','replay','physics_sim','fixture')),
    schema_version INTEGER NOT NULL DEFAULT {SCHEMA_VERSION},
    gyro_bias_roll_rad_s  REAL,              -- learned gyro RATE bias, rad/s; NULL = unlearned this run
    gyro_bias_pitch_rad_s REAL,
    gyro_bias_yaw_rad_s   REAL,
    gyro_bias_stops       INTEGER,           -- accepted stops in the rate-bias window
    gyro_bias_rejected_stops INTEGER         -- stops refused as a latched rate (A-34) this run
);
"""

# --- edr_imu_derived gyro RATE bias (US-810) ----------------------------------
# PitchFusion's learned gyro RATE bias (rad/s, 3-vector) -- NOT bias_rad, which
# is the mount-tilt ANGLE. Appended LAST in the DDL above so a fresh table and
# one upgraded by ensureEdrImuDerivedGyroRateBiasColumns (ADD COLUMN appends)
# have the same column order. The three rate columns are NULL until a stop is
# accepted in this run: an unlearned bias and a measured zero never share a
# stored value. gyro_bias_rejected_stops is what tells "never learned" apart
# from "every stop rejected as a latch" -- both leave the rates NULL.
EDR_IMU_DERIVED_GYRO_RATE_BIAS_COLUMNS: tuple[tuple[str, str], ...] = (
    ("gyro_bias_roll_rad_s", "REAL"),
    ("gyro_bias_pitch_rad_s", "REAL"),
    ("gyro_bias_yaw_rad_s", "REAL"),
    ("gyro_bias_stops", "INTEGER"),
    ("gyro_bias_rejected_stops", "INTEGER"),
)


def ensureEdrImuDerivedGyroRateBiasColumns(conn: sqlite3.Connection) -> list[str]:
    """Add the US-810 gyro RATE bias columns to an existing ``edr_imu_derived``.

    Replay-safe per specs/design-patterns.md section 10: the Pi has no migration
    ledger, so this runs on EVERY boot. Each column is an explicit ADD COLUMN
    guarded by PRAGMA table_info, so a second run issues no ALTER at all and no
    row is read, copied or rewritten. Existing rows read NULL in every new
    column -- their bias was never recorded, and says so.

    A missing table is NOT treated as "nothing to do": the probe then reports
    every column absent and the ALTER raises ``no such table``. The caller
    creates the table first, so reaching that is a defect that must be loud.

    Args:
        conn: Open SQLite connection to the Pi database.

    Returns:
        The column names added by THIS call, in order; empty when all present.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(edr_imu_derived)")}
    added: list[str] = []
    for name, sqliteType in EDR_IMU_DERIVED_GYRO_RATE_BIAS_COLUMNS:
        if name in existing:
            continue
        conn.execute(f"ALTER TABLE edr_imu_derived ADD COLUMN {name} {sqliteType}")
        added.append(name)
    return added

# --- Indexes (drive_id + ts on both tables) -- ADR section 2.2 ----------------
INDEX_EDR_IMU_DERIVED_DRIVE_ID = (
    "CREATE INDEX IF NOT EXISTS ix_edr_imu_derived_drive_id "
    "ON edr_imu_derived(drive_id);"
)
INDEX_EDR_IMU_DERIVED_TS = (
    "CREATE INDEX IF NOT EXISTS ix_edr_imu_derived_ts ON edr_imu_derived(ts_utc);"
)
INDEX_EDR_IMU_SAMPLE_DRIVE_ID = (
    "CREATE INDEX IF NOT EXISTS ix_edr_imu_sample_drive_id "
    "ON edr_imu_sample(drive_id);"
)
INDEX_EDR_IMU_SAMPLE_TS = (
    "CREATE INDEX IF NOT EXISTS ix_edr_imu_sample_ts ON edr_imu_sample(ts_utc);"
)
INDEX_EDR_LIGHT_SAMPLE_DRIVE_ID = (
    "CREATE INDEX IF NOT EXISTS ix_edr_light_sample_drive_id "
    "ON edr_light_sample(drive_id);"
)
INDEX_EDR_LIGHT_SAMPLE_TS = (
    "CREATE INDEX IF NOT EXISTS ix_edr_light_sample_ts ON edr_light_sample(ts_utc);"
)

# Registration lists -- the Pi appends these onto its ALL_SCHEMAS / ALL_INDEXES
# so ObdDatabase.initialize() creates the tables idempotently at startup.
EDR_SCHEMAS: list[tuple[str, str]] = [
    ("edr_imu_sample", SCHEMA_EDR_IMU_SAMPLE),
    ("edr_light_sample", SCHEMA_EDR_LIGHT_SAMPLE),
    ("edr_imu_derived", SCHEMA_EDR_IMU_DERIVED),
]

EDR_INDEXES: list[tuple[str, str]] = [
    ("ix_edr_imu_sample_drive_id", INDEX_EDR_IMU_SAMPLE_DRIVE_ID),
    ("ix_edr_imu_sample_ts", INDEX_EDR_IMU_SAMPLE_TS),
    ("ix_edr_light_sample_drive_id", INDEX_EDR_LIGHT_SAMPLE_DRIVE_ID),
    ("ix_edr_light_sample_ts", INDEX_EDR_LIGHT_SAMPLE_TS),
    ("ix_edr_imu_derived_drive_id", INDEX_EDR_IMU_DERIVED_DRIVE_ID),
    ("ix_edr_imu_derived_ts", INDEX_EDR_IMU_DERIVED_TS),
]

# --- Structured column list (US-764) -------------------------------------------
# table -> ordered (name, kind, nullable). The server DDL generator
# (server_ddl.py) derives the MariaDB tables from THIS list, and
# tests/common/test_edr_contract.py pins it to the Pi DDL above (names, order,
# kind vs SQLite type, NOT NULL), so the two cannot drift silently. The Pi `id`
# PK is excluded: on the server it arrives as `source_id`.
# Kinds: iso_ts | monotonic_s | int | float | label.
EDR_COLUMNS: dict[str, tuple[tuple[str, str, bool], ...]] = {
    "edr_imu_sample": (
        ("ts_utc", "iso_ts", False),
        ("ts_capture", "monotonic_s", False),
        ("seq", "int", False),
        ("accel_x", "float", True),
        ("accel_y", "float", True),
        ("accel_z", "float", True),
        ("gyro_x", "float", True),
        ("gyro_y", "float", True),
        ("gyro_z", "float", True),
        ("mag_x", "float", True),
        ("mag_y", "float", True),
        ("mag_z", "float", True),
        ("temp_c", "float", True),
        ("drive_id", "int", True),
        ("data_source", "label", False),
        ("schema_version", "int", False),
    ),
    # US-805: PitchFusion OUTPUTS, deliberately NOT columns of edr_imu_sample.
    # `pitch_deg` is NULLABLE because pitchRad returns None under
    # gyro_implausible (US-749) and that null is the only evidence the guard
    # fired; `fusion_version` is NOT NULL because a derived table that cannot
    # say WHICH algorithm produced a row inherits the defect the split exists
    # to prevent.
    "edr_imu_derived": (
        ("ts_utc", "iso_ts", False),
        ("ts_capture", "monotonic_s", False),
        ("seq", "int", False),
        ("pitch_deg", "float", True),
        ("stop_count", "int", True),
        ("bias_rad", "float", True),
        ("fusion_version", "int", False),
        ("drive_id", "int", True),
        ("data_source", "label", False),
        ("schema_version", "int", False),
        # US-810: gyro RATE bias (rad/s), nullable -- NULL is the unlearned state.
        ("gyro_bias_roll_rad_s", "float", True),
        ("gyro_bias_pitch_rad_s", "float", True),
        ("gyro_bias_yaw_rad_s", "float", True),
        ("gyro_bias_stops", "int", True),
        ("gyro_bias_rejected_stops", "int", True),
    ),
    "edr_light_sample": (
        ("ts_utc", "iso_ts", False),
        ("ts_capture", "monotonic_s", False),
        ("seq", "int", False),
        ("lux", "float", True),
        ("visible", "int", True),
        ("infrared", "int", True),
        ("full_spectrum", "int", True),
        ("gain", "label", True),
        ("integration_ms", "int", True),
        ("drive_id", "int", True),
        ("data_source", "label", False),
        ("schema_version", "int", False),
    ),
}

__all__ = [
    "SCHEMA_VERSION",
    "SCHEMA_EDR_IMU_SAMPLE",
    "SCHEMA_EDR_LIGHT_SAMPLE",
    "SCHEMA_EDR_IMU_DERIVED",
    "INDEX_EDR_IMU_SAMPLE_DRIVE_ID",
    "INDEX_EDR_IMU_SAMPLE_TS",
    "INDEX_EDR_LIGHT_SAMPLE_DRIVE_ID",
    "INDEX_EDR_LIGHT_SAMPLE_TS",
    "INDEX_EDR_IMU_DERIVED_DRIVE_ID",
    "INDEX_EDR_IMU_DERIVED_TS",
    "EDR_SCHEMAS",
    "EDR_INDEXES",
    "EDR_COLUMNS",
    "EDR_IMU_DERIVED_GYRO_RATE_BIAS_COLUMNS",
    "ensureEdrImuDerivedGyroRateBiasColumns",
]
