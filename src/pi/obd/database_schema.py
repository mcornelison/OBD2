################################################################################
# File Name: database_schema.py
# Purpose/Description: SQL schema definitions and index statements for the OBD-II database
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-002
# 2026-04-14    | Ralph Agent  | Sweep 2b — drop alert_config_json column from SCHEMA_PROFILES
# 2026-04-14    | Sweep 5      | Extracted from database.py (task 4 split)
# ================================================================================
################################################################################

"""
SQL schema + index definitions for the OBD-II SQLite database.

Table schemas are defined as raw SQL strings with CREATE TABLE IF NOT EXISTS.
Indexes are defined separately (each CREATE INDEX IF NOT EXISTS). ALL_SCHEMAS
and ALL_INDEXES provide ordered lists consumed by ObdDatabase.initialize().

This module is pure data — no functions, no classes. Importing it is side-effect
free.
"""


# ================================================================================
# Schema Definitions
# ================================================================================

# Vehicle information decoded from VIN via NHTSA API
SCHEMA_VEHICLE_INFO = """
CREATE TABLE IF NOT EXISTS vehicle_info (
    -- Primary key
    vin TEXT PRIMARY KEY,

    -- NHTSA decoded fields
    make TEXT,
    model TEXT,
    year INTEGER,
    engine TEXT,
    fuel_type TEXT,
    transmission TEXT,
    drive_type TEXT,
    body_class TEXT,
    plant_city TEXT,
    plant_country TEXT,

    -- Raw API response for future reference
    raw_api_response TEXT,

    -- Audit columns
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# Profiles for different driving modes
SCHEMA_PROFILES = """
CREATE TABLE IF NOT EXISTS profiles (
    -- Primary key
    id TEXT PRIMARY KEY,

    -- Profile details
    name TEXT NOT NULL,
    description TEXT,

    -- Profile-specific polling interval
    polling_interval_ms INTEGER DEFAULT 1000,

    -- Audit columns
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# Static data queried once per VIN
SCHEMA_STATIC_DATA = """
CREATE TABLE IF NOT EXISTS static_data (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Foreign key to vehicle
    vin TEXT NOT NULL,

    -- Parameter data
    parameter_name TEXT NOT NULL,
    value TEXT,
    unit TEXT,

    -- When this was queried
    queried_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT FK_static_data_vehicle FOREIGN KEY (vin)
        REFERENCES vehicle_info(vin)
        ON DELETE CASCADE
);
"""

# Real-time OBD-II data with timestamp indexing
SCHEMA_REALTIME_DATA = """
CREATE TABLE IF NOT EXISTS realtime_data (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Timestamp with millisecond precision
    timestamp DATETIME NOT NULL,

    -- Parameter data
    parameter_name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,

    -- Profile association
    profile_id TEXT,

    -- Constraints
    CONSTRAINT FK_realtime_data_profile FOREIGN KEY (profile_id)
        REFERENCES profiles(id)
        ON DELETE SET NULL
);
"""

# Index on timestamp for efficient time-range queries
INDEX_REALTIME_TIMESTAMP = """
CREATE INDEX IF NOT EXISTS IX_realtime_data_timestamp
    ON realtime_data(timestamp);
"""

# Index on profile_id for profile-filtered queries
INDEX_REALTIME_PROFILE = """
CREATE INDEX IF NOT EXISTS IX_realtime_data_profile
    ON realtime_data(profile_id);
"""

# Compound index for common query pattern
INDEX_REALTIME_PARAM_TIMESTAMP = """
CREATE INDEX IF NOT EXISTS IX_realtime_data_param_timestamp
    ON realtime_data(parameter_name, timestamp);
"""

# Statistical summaries calculated post-drive
SCHEMA_STATISTICS = """
CREATE TABLE IF NOT EXISTS statistics (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Analysis identification
    parameter_name TEXT NOT NULL,
    analysis_date DATETIME NOT NULL,
    profile_id TEXT NOT NULL,

    -- Statistical calculations
    max_value REAL,
    min_value REAL,
    avg_value REAL,
    mode_value REAL,
    std_1 REAL,
    std_2 REAL,

    -- Outlier bounds (mean +/- 2*std)
    outlier_min REAL,
    outlier_max REAL,

    -- Record count for this analysis
    sample_count INTEGER,

    -- Audit column
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT FK_statistics_profile FOREIGN KEY (profile_id)
        REFERENCES profiles(id)
        ON DELETE CASCADE
);
"""

# Index on analysis_date for time-based queries
INDEX_STATISTICS_DATE = """
CREATE INDEX IF NOT EXISTS IX_statistics_analysis_date
    ON statistics(analysis_date);
"""

# Index on profile_id for profile-filtered queries
INDEX_STATISTICS_PROFILE = """
CREATE INDEX IF NOT EXISTS IX_statistics_profile
    ON statistics(profile_id);
"""

# AI-generated recommendations with deduplication
SCHEMA_AI_RECOMMENDATIONS = """
CREATE TABLE IF NOT EXISTS ai_recommendations (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Recommendation timestamp
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- AI-generated content
    recommendation TEXT NOT NULL,

    -- Priority ranking (1=highest, 5=lowest)
    priority_rank INTEGER DEFAULT 3
        CHECK (priority_rank >= 1 AND priority_rank <= 5),

    -- Deduplication: points to original if this is a duplicate
    is_duplicate_of INTEGER,

    -- Profile association
    profile_id TEXT,

    -- Audit column
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT FK_ai_recommendations_duplicate FOREIGN KEY (is_duplicate_of)
        REFERENCES ai_recommendations(id)
        ON DELETE SET NULL,
    CONSTRAINT FK_ai_recommendations_profile FOREIGN KEY (profile_id)
        REFERENCES profiles(id)
        ON DELETE SET NULL
);
"""

# Index for finding non-duplicate recommendations
INDEX_AI_RECOMMENDATIONS_DUPLICATE = """
CREATE INDEX IF NOT EXISTS IX_ai_recommendations_duplicate
    ON ai_recommendations(is_duplicate_of);
"""

# Calibration sessions for testing/tuning
SCHEMA_CALIBRATION_SESSIONS = """
CREATE TABLE IF NOT EXISTS calibration_sessions (
    -- Primary key
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Session timing
    start_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_time DATETIME,

    -- User notes for this session
    notes TEXT,

    -- Profile used during calibration (optional)
    profile_id TEXT,

    -- Audit column
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT FK_calibration_sessions_profile FOREIGN KEY (profile_id)
        REFERENCES profiles(id)
        ON DELETE SET NULL
);
"""

# Alert log for tracking threshold violations
SCHEMA_ALERT_LOG = """
CREATE TABLE IF NOT EXISTS alert_log (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Alert timestamp
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Alert details
    alert_type TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    value REAL NOT NULL,
    threshold REAL NOT NULL,

    -- Profile association
    profile_id TEXT,

    -- Constraints
    CONSTRAINT FK_alert_log_profile FOREIGN KEY (profile_id)
        REFERENCES profiles(id)
        ON DELETE SET NULL
);
"""

# Index on alert log profile for profile-based queries
INDEX_ALERT_LOG_PROFILE = """
CREATE INDEX IF NOT EXISTS IX_alert_log_profile
    ON alert_log(profile_id);
"""

# Index on alert log timestamp for time-based queries
INDEX_ALERT_LOG_TIMESTAMP = """
CREATE INDEX IF NOT EXISTS IX_alert_log_timestamp
    ON alert_log(timestamp);
"""

# Connection log for tracking OBD-II connection attempts
SCHEMA_CONNECTION_LOG = """
CREATE TABLE IF NOT EXISTS connection_log (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Event timestamp
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Connection details
    event_type TEXT NOT NULL,
    mac_address TEXT,
    success INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
);
"""

# Index on connection log event type for filtering
INDEX_CONNECTION_LOG_EVENT_TYPE = """
CREATE INDEX IF NOT EXISTS IX_connection_log_event_type
    ON connection_log(event_type);
"""

# Index on connection log timestamp for time-based queries
INDEX_CONNECTION_LOG_TIMESTAMP = """
CREATE INDEX IF NOT EXISTS IX_connection_log_timestamp
    ON connection_log(timestamp);
"""

# Battery voltage log for power monitoring
SCHEMA_BATTERY_LOG = """
CREATE TABLE IF NOT EXISTS battery_log (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Event timestamp
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Voltage reading
    event_type TEXT NOT NULL,
    voltage REAL NOT NULL,

    -- Thresholds at time of reading (for historical context)
    warning_threshold REAL,
    critical_threshold REAL
);
"""

# Index on battery log timestamp for time-based queries
INDEX_BATTERY_LOG_TIMESTAMP = """
CREATE INDEX IF NOT EXISTS IX_battery_log_timestamp
    ON battery_log(timestamp);
"""

# Index on battery log event type for filtering
INDEX_BATTERY_LOG_EVENT_TYPE = """
CREATE INDEX IF NOT EXISTS IX_battery_log_event_type
    ON battery_log(event_type);
"""

# Power source log for tracking AC/battery transitions
SCHEMA_POWER_LOG = """
CREATE TABLE IF NOT EXISTS power_log (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Event timestamp
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Power event details
    event_type TEXT NOT NULL,
    power_source TEXT NOT NULL,
    on_ac_power INTEGER NOT NULL DEFAULT 1
);
"""

# Index on power log timestamp for time-based queries
INDEX_POWER_LOG_TIMESTAMP = """
CREATE INDEX IF NOT EXISTS IX_power_log_timestamp
    ON power_log(timestamp);
"""

# Index on power log event type for filtering
INDEX_POWER_LOG_EVENT_TYPE = """
CREATE INDEX IF NOT EXISTS IX_power_log_event_type
    ON power_log(event_type);
"""

# All schema statements in order of dependency
ALL_SCHEMAS = [
    ('vehicle_info', SCHEMA_VEHICLE_INFO),
    ('profiles', SCHEMA_PROFILES),
    ('static_data', SCHEMA_STATIC_DATA),
    ('realtime_data', SCHEMA_REALTIME_DATA),
    ('statistics', SCHEMA_STATISTICS),
    ('ai_recommendations', SCHEMA_AI_RECOMMENDATIONS),
    ('calibration_sessions', SCHEMA_CALIBRATION_SESSIONS),
    ('alert_log', SCHEMA_ALERT_LOG),
    ('connection_log', SCHEMA_CONNECTION_LOG),
    ('battery_log', SCHEMA_BATTERY_LOG),
    ('power_log', SCHEMA_POWER_LOG),
]

# All index statements
ALL_INDEXES = [
    ('IX_realtime_data_timestamp', INDEX_REALTIME_TIMESTAMP),
    ('IX_realtime_data_profile', INDEX_REALTIME_PROFILE),
    ('IX_realtime_data_param_timestamp', INDEX_REALTIME_PARAM_TIMESTAMP),
    ('IX_statistics_analysis_date', INDEX_STATISTICS_DATE),
    ('IX_statistics_profile', INDEX_STATISTICS_PROFILE),
    ('IX_ai_recommendations_duplicate', INDEX_AI_RECOMMENDATIONS_DUPLICATE),
    ('IX_alert_log_profile', INDEX_ALERT_LOG_PROFILE),
    ('IX_alert_log_timestamp', INDEX_ALERT_LOG_TIMESTAMP),
    ('IX_connection_log_event_type', INDEX_CONNECTION_LOG_EVENT_TYPE),
    ('IX_connection_log_timestamp', INDEX_CONNECTION_LOG_TIMESTAMP),
    ('IX_battery_log_timestamp', INDEX_BATTERY_LOG_TIMESTAMP),
    ('IX_battery_log_event_type', INDEX_BATTERY_LOG_EVENT_TYPE),
    ('IX_power_log_timestamp', INDEX_POWER_LOG_TIMESTAMP),
    ('IX_power_log_event_type', INDEX_POWER_LOG_EVENT_TYPE),
]
