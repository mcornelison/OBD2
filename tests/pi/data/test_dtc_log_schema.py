################################################################################
# File Name: test_dtc_log_schema.py
# Purpose/Description: Tests for the Pi SQLite dtc_log schema + idempotent
#                      migration helper (US-204).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-204) | Initial -- dtc_log schema + migration.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.obdii.dtc_log_schema` + ``ObdDatabase`` migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.dtc_log_schema import (
    DTC_LOG_STATUS_VALUES,
    DTC_LOG_TABLE,
    SCHEMA_DTC_LOG,
    ensureDtcLogTable,
)

# ================================================================================
# Fixture: a fresh ObdDatabase file under tmp_path
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """An initialized, empty ObdDatabase backed by a new file."""
    db = ObdDatabase(str(tmp_path / "test_dtc.db"), walMode=False)
    db.initialize()
    return db


# ================================================================================
# Fresh-schema shape
# ================================================================================


class TestFreshSchema:
    """After initialize(), dtc_log has the expected 8-column shape."""

    def test_tableIsCreated(self, freshDb: ObdDatabase) -> None:
        assert DTC_LOG_TABLE in freshDb.getTableNames()

    def test_columnShape(self, freshDb: ObdDatabase) -> None:
        cols = {c['name']: c for c in freshDb.getTableInfo(DTC_LOG_TABLE)}
        # 8 columns: id + dtc_code + description + status + first_seen +
        # last_seen + drive_id + data_source
        expected = {
            'id',
            'dtc_code',
            'description',
            'status',
            'first_seen_timestamp',
            'last_seen_timestamp',
            'drive_id',
            'data_source',
        }
        assert set(cols.keys()) == expected

    def test_statusCheckConstraintEnforced(self, freshDb: ObdDatabase) -> None:
        """Invalid status value must fail at INSERT time via CHECK."""
        with freshDb.connect() as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    f"INSERT INTO {DTC_LOG_TABLE} "
                    "(dtc_code, description, status, drive_id) "
                    "VALUES (?, ?, ?, ?)",
                    ("P0171", "lean", "bogus", 1),
                )

    def test_statusValuesMatchesConstraint(self) -> None:
        assert DTC_LOG_STATUS_VALUES == ('stored', 'pending', 'cleared')

    def test_driveIdIsNullable(self, freshDb: ObdDatabase) -> None:
        """drive_id is nullable (pre-drive DTC captures allowed)."""
        cols = {c['name']: c for c in freshDb.getTableInfo(DTC_LOG_TABLE)}
        assert cols['drive_id']['notnull'] == 0

    def test_dtcCodeIsRequired(self, freshDb: ObdDatabase) -> None:
        cols = {c['name']: c for c in freshDb.getTableInfo(DTC_LOG_TABLE)}
        assert cols['dtc_code']['notnull'] == 1

    def test_dataSourceHasRealDefault(self, freshDb: ObdDatabase) -> None:
        cols = {c['name']: c for c in freshDb.getTableInfo(DTC_LOG_TABLE)}
        default = cols['data_source']['dflt_value']
        assert default is not None and "real" in default

    def test_timestampsHaveCanonicalDefault(self, freshDb: ObdDatabase) -> None:
        """US-202 invariant: timestamps default to ISO-8601 UTC strftime."""
        cols = {c['name']: c for c in freshDb.getTableInfo(DTC_LOG_TABLE)}
        for column in ('first_seen_timestamp', 'last_seen_timestamp'):
            default = cols[column]['dflt_value']
            assert default is not None
            assert 'strftime' in default
            assert 'Y-%m-%dT%H:%M:%SZ' in default


# ================================================================================
# Indexes
# ================================================================================


class TestIndexes:
    """drive_id + dtc_code indexes are created for analytics queries."""

    def test_indexesExist(self, freshDb: ObdDatabase) -> None:
        names = set(freshDb.getIndexNames())
        assert 'IX_dtc_log_drive_id' in names
        assert 'IX_dtc_log_dtc_code' in names


# ================================================================================
# Migration idempotency
# ================================================================================


class TestEnsureDtcLogTableIdempotent:
    """Running ensureDtcLogTable repeatedly is a safe no-op."""

    def test_noopWhenAlreadyPresent(self, tmp_path: Path) -> None:
        db = ObdDatabase(str(tmp_path / "rerun.db"), walMode=False)
        db.initialize()
        with db.connect() as conn:
            created = ensureDtcLogTable(conn)
        # After initialize() the table exists -> ensureDtcLogTable returns
        # False because it didn't need to create anything.
        assert created is False

    def test_createsOnLegacyDatabase(self, tmp_path: Path) -> None:
        """A database without dtc_log picks it up on the next migration."""
        dbPath = tmp_path / "legacy.db"
        # Simulate a pre-US-204 db with only realtime_data.
        conn = sqlite3.connect(str(dbPath))
        conn.execute(
            "CREATE TABLE realtime_data ("
            "id INTEGER PRIMARY KEY, parameter_name TEXT, value REAL)"
        )
        conn.commit()

        created = ensureDtcLogTable(conn)
        conn.commit()
        conn.close()

        assert created is True

        conn = sqlite3.connect(str(dbPath))
        names = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert DTC_LOG_TABLE in names


# ================================================================================
# Round-trip INSERT + SELECT
# ================================================================================


class TestRoundTrip:
    """Insert a valid row and read it back."""

    def test_insertSelectRoundTrip(self, freshDb: ObdDatabase) -> None:
        with freshDb.connect() as conn:
            conn.execute(
                f"INSERT INTO {DTC_LOG_TABLE} "
                "(dtc_code, description, status, drive_id) "
                "VALUES (?, ?, ?, ?)",
                ("P0171", "System Too Lean (Bank 1)", "stored", 42),
            )

        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT dtc_code, status, drive_id, data_source "
                f"FROM {DTC_LOG_TABLE}"
            ).fetchone()

        assert row['dtc_code'] == 'P0171'
        assert row['status'] == 'stored'
        assert row['drive_id'] == 42
        assert row['data_source'] == 'real'


# ================================================================================
# SCHEMA_DTC_LOG constant shape
# ================================================================================


class TestSchemaConstant:
    """The DDL constant is IF NOT EXISTS (idempotent)."""

    def test_schemaIsIfNotExists(self) -> None:
        assert "IF NOT EXISTS" in SCHEMA_DTC_LOG
        assert DTC_LOG_TABLE in SCHEMA_DTC_LOG
