################################################################################
# File Name: database.py
# Purpose/Description: SQLite database management for OBD-II data storage
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-002
# ================================================================================
################################################################################

"""
SQLite database management module for the Eclipse OBD-II system.

Provides:
- Database initialization with all required tables
- WAL mode configuration for better concurrent performance
- Connection management with context managers
- Schema creation with IF NOT EXISTS for idempotent setup

Tables:
- vehicle_info: VIN-decoded vehicle information
- static_data: One-time OBD-II parameters (VIN, fuel type, etc.)
- realtime_data: Timestamped OBD-II readings with profile association
- statistics: Calculated statistical summaries per parameter/profile
- ai_recommendations: AI-generated performance recommendations
- profiles: Tuning/driving mode profiles
- calibration_sessions: Calibration mode session tracking

Usage:
    from obd.database import ObdDatabase

    db = ObdDatabase('./data/obd.db')
    db.initialize()

    # Use context manager for connections
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM profiles')
"""

import logging
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ================================================================================
# Custom Exceptions
# ================================================================================

class DatabaseError(Exception):
    """Base exception for database-related errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class DatabaseConnectionError(DatabaseError):
    """Error connecting to the database."""
    pass


class DatabaseInitializationError(DatabaseError):
    """Error initializing the database schema."""
    pass


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

    -- JSON-encoded alert configuration
    alert_config_json TEXT,

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


# ================================================================================
# Database Class
# ================================================================================

class ObdDatabase:
    """
    SQLite database manager for OBD-II data storage.

    Provides connection management, schema initialization, and
    WAL mode configuration for optimal performance.

    Attributes:
        dbPath: Path to the SQLite database file
        walMode: Whether to use WAL (Write-Ahead Logging) mode

    Example:
        db = ObdDatabase('./data/obd.db', walMode=True)
        db.initialize()

        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM profiles')
            rows = cursor.fetchall()
    """

    def __init__(self, dbPath: str, walMode: bool = True):
        """
        Initialize database manager.

        Args:
            dbPath: Path to the SQLite database file
            walMode: Enable WAL mode for better concurrency (default: True)
        """
        self.dbPath = dbPath
        self.walMode = walMode
        self._initialized = False

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connections.

        Provides automatic connection cleanup and commit/rollback handling.

        Yields:
            sqlite3.Connection: Database connection

        Raises:
            DatabaseConnectionError: If connection fails

        Example:
            with db.connect() as conn:
                cursor = conn.cursor()
                cursor.execute('INSERT INTO profiles ...')
                # Auto-committed on successful exit
        """
        conn = None
        try:
            conn = self._getConnection()
            yield conn
            conn.commit()
        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            raise DatabaseConnectionError(
                f"Database connection error: {e}",
                details={'path': self.dbPath, 'error': str(e)}
            ) from e
        finally:
            if conn:
                conn.close()

    def _getConnection(self) -> sqlite3.Connection:
        """
        Get a new database connection.

        Returns:
            sqlite3.Connection: New connection with row factory configured

        Raises:
            DatabaseConnectionError: If connection fails
        """
        try:
            # Create parent directories if needed
            dbDir = os.path.dirname(self.dbPath)
            if dbDir:
                Path(dbDir).mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(
                self.dbPath,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                timeout=30.0
            )

            # Enable row factory for dict-like access
            conn.row_factory = sqlite3.Row

            # Enable foreign key support
            conn.execute('PRAGMA foreign_keys = ON')

            # Configure WAL mode if requested
            if self.walMode:
                conn.execute('PRAGMA journal_mode = WAL')
                conn.execute('PRAGMA synchronous = NORMAL')

            return conn

        except sqlite3.Error as e:
            raise DatabaseConnectionError(
                f"Failed to connect to database: {e}",
                details={'path': self.dbPath, 'error': str(e)}
            ) from e

    def initialize(self) -> bool:
        """
        Initialize the database schema.

        Creates all tables and indexes if they don't exist.
        Safe to call multiple times (idempotent).

        Returns:
            True if initialization succeeded

        Raises:
            DatabaseInitializationError: If schema creation fails
        """
        logger.info(f"Initializing database at {self.dbPath}")

        try:
            with self.connect() as conn:
                cursor = conn.cursor()

                # Create all tables
                for tableName, schema in ALL_SCHEMAS:
                    logger.debug(f"Creating table: {tableName}")
                    cursor.execute(schema)

                # Create all indexes
                for indexName, indexSql in ALL_INDEXES:
                    logger.debug(f"Creating index: {indexName}")
                    cursor.execute(indexSql)

                self._initialized = True
                logger.info("Database initialization complete")
                return True

        except sqlite3.Error as e:
            raise DatabaseInitializationError(
                f"Failed to initialize database: {e}",
                details={'path': self.dbPath, 'error': str(e)}
            ) from e

    def isInitialized(self) -> bool:
        """
        Check if database has been initialized.

        Returns:
            True if initialize() has been called successfully
        """
        return self._initialized

    def getTableNames(self) -> list[str]:
        """
        Get list of all tables in the database.

        Returns:
            List of table names

        Raises:
            DatabaseConnectionError: If query fails
        """
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            return [row[0] for row in cursor.fetchall()]

    def getTableInfo(self, tableName: str) -> list[dict[str, Any]]:
        """
        Get column information for a table.

        Args:
            tableName: Name of the table

        Returns:
            List of column info dictionaries with keys:
            - cid: Column ID
            - name: Column name
            - type: Column type
            - notnull: Whether NOT NULL constraint exists
            - dflt_value: Default value
            - pk: Whether this is primary key

        Raises:
            DatabaseConnectionError: If query fails
        """
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({tableName})")
            columns = ['cid', 'name', 'type', 'notnull', 'dflt_value', 'pk']
            return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]

    def getIndexNames(self) -> list[str]:
        """
        Get list of all indexes in the database.

        Returns:
            List of index names

        Raises:
            DatabaseConnectionError: If query fails
        """
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
            return [row[0] for row in cursor.fetchall()]

    def vacuum(self) -> None:
        """
        Vacuum the database to reclaim space.

        Should be called after large deletions.

        Raises:
            DatabaseConnectionError: If vacuum fails
        """
        logger.info("Vacuuming database")
        # Vacuum must be run outside a transaction
        conn = self._getConnection()
        try:
            conn.execute('VACUUM')
        finally:
            conn.close()

    def getStats(self) -> dict[str, Any]:
        """
        Get database statistics.

        Returns:
            Dictionary with database stats:
            - file_size_bytes: Size of database file
            - table_counts: Row count per table
            - wal_mode: Whether WAL mode is enabled

        Raises:
            DatabaseConnectionError: If query fails
        """
        stats = {
            'file_size_bytes': 0,
            'table_counts': {},
            'wal_mode': False
        }

        # Get file size
        if os.path.exists(self.dbPath):
            stats['file_size_bytes'] = os.path.getsize(self.dbPath)

        with self.connect() as conn:
            cursor = conn.cursor()

            # Check WAL mode
            cursor.execute('PRAGMA journal_mode')
            journalMode = cursor.fetchone()[0]
            stats['wal_mode'] = journalMode.lower() == 'wal'

            # Get row counts for each table
            for tableName, _ in ALL_SCHEMAS:
                try:
                    cursor.execute(f'SELECT COUNT(*) FROM {tableName}')
                    count = cursor.fetchone()[0]
                    stats['table_counts'][tableName] = count
                except sqlite3.Error:
                    stats['table_counts'][tableName] = -1

        return stats


# ================================================================================
# Helper Functions
# ================================================================================

def createDatabaseFromConfig(config: dict[str, Any]) -> ObdDatabase:
    """
    Create an ObdDatabase instance from configuration.

    Args:
        config: Configuration dictionary with 'database' section

    Returns:
        Configured ObdDatabase instance

    Example:
        config = {
            'database': {
                'path': './data/obd.db',
                'walMode': True
            }
        }
        db = createDatabaseFromConfig(config)
    """
    dbConfig = config.get('database', {})
    dbPath = dbConfig.get('path', './data/obd.db')
    walMode = dbConfig.get('walMode', True)

    return ObdDatabase(dbPath, walMode=walMode)


def initializeDatabase(config: dict[str, Any]) -> ObdDatabase:
    """
    Create and initialize an ObdDatabase from configuration.

    Convenience function that creates the database and initializes the schema.

    Args:
        config: Configuration dictionary with 'database' section

    Returns:
        Initialized ObdDatabase instance

    Raises:
        DatabaseInitializationError: If initialization fails

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
    """
    db = createDatabaseFromConfig(config)
    db.initialize()
    return db
