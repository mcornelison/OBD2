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
# 2026-04-14    | Ralph Agent  | Sweep 2b — drop alert_config_json column from SCHEMA_PROFILES
# 2026-04-23    | Rex (US-225) | TD-034 close: pi_state singleton migration
#                               (no_new_drives flag for US-216 WARNING stage).
# 2026-05-01    | Rex (US-252) | Wired ensurePowerLogVcellColumn idempotent
#                               migration into initialize() so pre-US-252
#                               databases gain the vcell column for
#                               staged-shutdown stage-transition rows.
# 2026-05-07    | Rex (US-289) | Wired ensureBatteryHealthLogVcellColumns
#                               idempotent migration into initialize() so
#                               pre-US-289 databases gain start_vcell_v +
#                               end_vcell_v columns on next boot.  Spool
#                               Sprint 26 Story 6 column rename.
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

from src.pi.power.battery_health import (
    ensureBatteryHealthLogTable,
    ensureBatteryHealthLogVcellColumns,
)
from src.pi.power.power_db import ensurePowerLogVcellColumn

from .data_source import ensureAllCaptureTables
from .database_schema import (
    ALL_INDEXES,
    ALL_SCHEMAS,
)
from .drive_id import ensureAllDriveIdColumns, ensureDriveCounter
from .drive_summary import ensureDriveSummaryTable
from .dtc_log_schema import ensureDtcLogTable
from .pi_state import ensurePiStateTable

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
# Database Class
# ================================================================================
# Schema and index definitions now live in database_schema.py and are imported
# at module top for backwards compatibility with `from pi.obdii.database import
# ALL_SCHEMAS, ALL_INDEXES` callers.

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

                # US-195 idempotent migration: back-fill data_source on any
                # pre-US-195 capture tables that pre-date the schema addition.
                # No-op on fresh databases (columns already present via DDL).
                migrated = ensureAllCaptureTables(conn)
                if migrated:
                    logger.info(
                        "Added data_source column to tables: %s",
                        ', '.join(migrated),
                    )

                # US-200 idempotent migration: back-fill drive_id on any
                # pre-US-200 capture tables.  Also creates the per-table
                # IX_<table>_drive_id index (idempotent CREATE INDEX IF
                # NOT EXISTS).  Existing rows remain NULL (Invariant #4:
                # do NOT retag Session 23 149 rows).
                migratedDriveId = ensureAllDriveIdColumns(conn)
                if migratedDriveId:
                    logger.info(
                        "Added drive_id column to tables: %s",
                        ', '.join(migratedDriveId),
                    )
                # Seed the drive_counter singleton.  INSERT OR IGNORE
                # preserves an existing counter on reboot.
                ensureDriveCounter(conn)

                # US-204 idempotent migration: dtc_log capture table for
                # Spool Data v2 Story 3.  Created with drive_id +
                # data_source already on the schema.  Pre-US-204 dbs get
                # the table here without disturbing the rest.
                if ensureDtcLogTable(conn):
                    logger.info("Created dtc_log table (US-204)")

                # US-206 idempotent migration: drive_summary capture
                # table for Spool Data v2 Story 4 (drive-start metadata
                # -- ambient IAT, starting battery, barometric).  One
                # row per drive, keyed by drive_id (the PK feeds both
                # the sync delta cursor and the UNIQUE-per-drive shape).
                if ensureDriveSummaryTable(conn):
                    logger.info("Created drive_summary table (US-206)")

                # US-217 idempotent migration: battery_health_log table
                # for UPS drain-event tracking (one row per drain event).
                # Backs CIO's monthly drain-test cadence (directive 3)
                # and US-216's staged shutdown ladder.  PK
                # drain_event_id feeds the sync delta cursor.
                if ensureBatteryHealthLogTable(conn):
                    logger.info("Created battery_health_log table (US-217)")

                # US-289 idempotent migration: add start_vcell_v +
                # end_vcell_v columns to battery_health_log.  The
                # legacy start_soc / end_soc columns hold VCELL volts
                # despite the name -- the new columns are the truth-
                # named replacements.  Caller (BatteryHealthRecorder)
                # populates BOTH old + new during the deprecation phase.
                if ensureBatteryHealthLogVcellColumns(conn):
                    logger.info(
                        "Added vcell_v columns to battery_health_log "
                        "(US-289)"
                    )

                # US-225 idempotent migration: pi_state singleton for
                # TD-034 stage-behavior flags (today: no_new_drives
                # for the US-216 WARNING stage gate on new drive_id
                # minting).  Seeds the singleton row with defaults on
                # first boot; preserves operator-set values on reboot.
                if ensurePiStateTable(conn):
                    logger.info("Created pi_state table (US-225)")

                # US-252 idempotent migration: add ``vcell`` column to
                # power_log so PowerDownOrchestrator stage-transition rows
                # carry the LiPo cell voltage at threshold crossing.
                # Pre-US-252 databases get the column here without
                # disturbing existing rows.
                if ensurePowerLogVcellColumn(conn):
                    logger.info("Added vcell column to power_log (US-252)")

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
    dbConfig = config.get('pi', {}).get('database', {})
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
