################################################################################
# File Name: test_edr_tables_created.py
# Purpose/Description: Verifies the Pi's ObdDatabase.initialize() creates the EDR
#                      raw-sensor tables (edr_imu_sample + edr_light_sample) from
#                      the single-source src/common/edr contract, idempotently,
#                      with the ADR section 2.2 columns/indexes and no server
#                      table (Pi-local only, US-408).
# Author: Rex (US-408)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Rex (US-408) | Initial -- EDR tables created at Pi startup.
# ================================================================================
################################################################################
"""Pi startup creates the EDR raw-sensor tables from the src/common/edr contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.common.edr.sensor_schema import EDR_INDEXES, EDR_SCHEMAS
from src.pi.obdii import database_schema
from src.pi.obdii.database import ObdDatabase

EDR_TABLES = {"edr_imu_sample", "edr_light_sample"}


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """An initialized, empty ObdDatabase backed by a new file."""
    db = ObdDatabase(str(tmp_path / "test_edr.db"), walMode=False)
    db.initialize()
    return db


class TestEdrTablesCreatedAtStartup:
    def test_bothEdrTablesExistAfterInitialize(self, freshDb: ObdDatabase) -> None:
        """A fresh Pi DB initialize() creates both EDR sensor tables."""
        with freshDb.connect() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name LIKE 'edr_%'"
                )
            }
        assert EDR_TABLES <= tables

    def test_edrIndexesExistAfterInitialize(self, freshDb: ObdDatabase) -> None:
        """The 4 ADR section 2.2 EDR indexes are created at startup."""
        with freshDb.connect() as conn:
            names = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND name LIKE 'ix_edr_%'"
                )
            }
        assert names == {name for name, _ddl in EDR_INDEXES}

    def test_schemaVersionColumnDefaultsToOne(self, freshDb: ObdDatabase) -> None:
        """A row inserted with no schema_version defaults to 1 (contract stamp)."""
        with freshDb.connect() as conn:
            conn.execute(
                "INSERT INTO edr_imu_sample (ts_utc, ts_capture, seq) "
                "VALUES ('2026-06-30T00:00:00Z', 0.0, 1)"
            )
            row = conn.execute(
                "SELECT schema_version FROM edr_imu_sample"
            ).fetchone()
        assert row[0] == 1

    def test_secondInitializeIsIdempotent(self, freshDb: ObdDatabase) -> None:
        """initialize() twice does not raise or duplicate the EDR tables."""
        freshDb.initialize()  # second pass must be safe
        with freshDb.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name IN ('edr_imu_sample','edr_light_sample')"
            ).fetchone()[0]
        assert count == 2


class TestEdrRegisteredInSchemaLists:
    def test_edrSchemasAreInAllSchemas(self) -> None:
        """The EDR tables are wired into the Pi's ALL_SCHEMAS registry."""
        registered = {name for name, _ddl in database_schema.ALL_SCHEMAS}
        assert EDR_TABLES <= registered

    def test_edrIndexesAreInAllIndexes(self) -> None:
        """The EDR indexes are wired into the Pi's ALL_INDEXES registry."""
        registered = {name for name, _ddl in database_schema.ALL_INDEXES}
        assert {name for name, _ddl in EDR_INDEXES} <= registered

    def test_singleSourceContract_ddlNotHandCopied(self) -> None:
        """ALL_SCHEMAS carries the src/common/edr DDL verbatim (no divergent copy).

        Value equality, not identity: the project resolves ``common.edr`` and
        ``src.common.edr`` to separate module caches, so string identity would
        differ even though there is one authoring source. Equality proves the
        Pi did not hand-rewrite the columns.
        """
        allSchemas = dict(database_schema.ALL_SCHEMAS)
        for name, ddl in EDR_SCHEMAS:
            assert allSchemas[name] == ddl
