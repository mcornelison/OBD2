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

# --- Indexes (drive_id + ts on both tables) -- ADR section 2.2 ----------------
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
]

EDR_INDEXES: list[tuple[str, str]] = [
    ("ix_edr_imu_sample_drive_id", INDEX_EDR_IMU_SAMPLE_DRIVE_ID),
    ("ix_edr_imu_sample_ts", INDEX_EDR_IMU_SAMPLE_TS),
    ("ix_edr_light_sample_drive_id", INDEX_EDR_LIGHT_SAMPLE_DRIVE_ID),
    ("ix_edr_light_sample_ts", INDEX_EDR_LIGHT_SAMPLE_TS),
]

__all__ = [
    "SCHEMA_VERSION",
    "SCHEMA_EDR_IMU_SAMPLE",
    "SCHEMA_EDR_LIGHT_SAMPLE",
    "INDEX_EDR_IMU_SAMPLE_DRIVE_ID",
    "INDEX_EDR_IMU_SAMPLE_TS",
    "INDEX_EDR_LIGHT_SAMPLE_DRIVE_ID",
    "INDEX_EDR_LIGHT_SAMPLE_TS",
    "EDR_SCHEMAS",
    "EDR_INDEXES",
]
