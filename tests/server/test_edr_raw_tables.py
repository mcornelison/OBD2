################################################################################
# File Name: test_edr_raw_tables.py
# Purpose/Description: US-765 (F-142) -- the server gets somewhere to PUT EDR
#                      samples. Guards the two raw-table models, the
#                      model-declared sync conflict columns (and that every
#                      pre-existing table's upsert is byte-identical after that
#                      seam lands), the v0026 migration's idempotency, and that
#                      the migration's DDL is GENERATED from the US-764 contract
#                      rather than restated.
# Author: Atlas (Architect)
# Creation Date: 2026-09-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-16    | Atlas        | Initial -- CIO-directed build (charter s2
#               |              | override recorded in board/wip/ARCH-029.md).
# ================================================================================
################################################################################

"""US-765 guards: the server EDR raw tables, their sync seam, and v0026.

Why this file leans so hard on "unchanged"
------------------------------------------

EDR is the first synced table whose natural key is NOT ``(source_device,
source_id)``.  The server PK is ``(source_device, source_id, ts_utc)``, because
MariaDB requires the partition column in every unique key and these tables are
RANGE-partitioned monthly on ``ts_utc``.  ``(source_device, source_id)`` is still
unique on its own -- ``source_id`` is the Pi's rowid -- so the third column
changes the DDL, not the identity.

That means ``_upsertBatch`` has to stop hardcoding its conflict target.  The risk
in that change is not EDR; it is the eleven tables already using it.  So the
load-bearing test here is not "EDR works", it is **"nothing else moved"**.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.common.edr.sensor_schema import EDR_COLUMNS
from src.common.edr.server_ddl import buildAllRawTableDdl, buildRawTableDdl
from src.common.edr.sync_contract import EDR_SYNC_TABLES
from src.pi.data.sync_log import DELTA_SYNC_TABLES, PK_COLUMN
from src.server.api.sync import (
    _DEFAULT_SYNC_CONFLICT_COLS,
    _TABLE_REGISTRY,
    ACCEPTED_TABLES,
    _syncConflictCols,
    runSyncUpsert,
)
from src.server.db.models import Base, EdrImuSample, EdrLightSample, PowerLog

EDR_MODELS = {
    "edr_imu_sample": EdrImuSample,
    "edr_light_sample": EdrLightSample,
}


def _newSession() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


# ================================================================================
# Model contract
# ================================================================================


class TestEdrModelContract:
    """The models mirror the US-764 contract and carry no surrogate id."""

    @pytest.mark.parametrize("tableName", sorted(EDR_SYNC_TABLES))
    def test_modelCarriesEveryContractColumn(self, tableName: str) -> None:
        cols = {c.name for c in EDR_MODELS[tableName].__table__.columns}
        expected = {name for name, _kind, _nullable in EDR_COLUMNS[tableName]}
        assert expected.issubset(cols), f"missing contract cols: {expected - cols}"

    @pytest.mark.parametrize("tableName", sorted(EDR_SYNC_TABLES))
    def test_modelHasNoSurrogateIdColumn(self, tableName: str) -> None:
        """A surrogate ``id`` is what loses the device dimension.

        ``drives.PRIMARY KEY`` is ``drive_id`` alone and will collide the moment a
        second vehicle reports.  These tables are keyed the way that one should
        have been, so an ``id`` here would be a regression, not a convenience.
        """
        cols = {c.name for c in EDR_MODELS[tableName].__table__.columns}
        assert "id" not in cols

    @pytest.mark.parametrize("tableName", sorted(EDR_SYNC_TABLES))
    def test_modelHasSyncColumns(self, tableName: str) -> None:
        cols = {c.name for c in EDR_MODELS[tableName].__table__.columns}
        sync = {"source_id", "source_device", "synced_at", "sync_batch_id"}
        assert sync.issubset(cols), f"missing sync cols: {sync - cols}"

    @pytest.mark.parametrize("tableName", sorted(EDR_SYNC_TABLES))
    def test_primaryKeyIsTheTriple(self, tableName: str) -> None:
        pk = tuple(c.name for c in EDR_MODELS[tableName].__table__.primary_key)
        assert set(pk) == {"source_device", "source_id", "ts_utc"}

    @pytest.mark.parametrize("tableName", sorted(EDR_SYNC_TABLES))
    def test_modelDeclaresSyncConflictCols(self, tableName: str) -> None:
        assert EDR_MODELS[tableName].__sync_conflict_cols__ == (
            "source_device",
            "source_id",
            "ts_utc",
        )


# ================================================================================
# The seam: conflict columns come from the model, default unchanged
# ================================================================================


class TestSyncConflictColumnSeam:
    """The change that could break eleven working tables."""

    def test_defaultIsTheHistoricPair(self) -> None:
        assert _DEFAULT_SYNC_CONFLICT_COLS == ("source_device", "source_id")

    def test_everyPreExistingModelResolvesToTheDefault(self) -> None:
        """No registered table except EDR may move off the historic pair.

        This is the regression guard for the seam.  If a future model acquires
        ``__sync_conflict_cols__`` by accident, its upsert target changes
        silently and rows start colliding -- or stop colliding -- with no other
        visible symptom.
        """
        moved = {
            name: _syncConflictCols(model)
            for name, (model, _renames) in _TABLE_REGISTRY.items()
            if name not in EDR_SYNC_TABLES
            and _syncConflictCols(model) != _DEFAULT_SYNC_CONFLICT_COLS
        }
        assert moved == {}, f"conflict target moved for: {moved}"

    def test_edrResolvesToTheTriple(self) -> None:
        assert _syncConflictCols(EdrImuSample) == (
            "source_device", "source_id", "ts_utc",
        )

    def test_modelWithoutTheAttributeStillWorks(self) -> None:
        """A model that never heard of the seam resolves to the default."""
        assert not hasattr(PowerLog, "__sync_conflict_cols__")
        assert _syncConflictCols(PowerLog) == _DEFAULT_SYNC_CONFLICT_COLS


# ================================================================================
# Sync registration
# ================================================================================


class TestSyncRegistration:
    """EDR is wired into both tiers' registries from ONE declaration."""

    @pytest.mark.parametrize("tableName", sorted(EDR_SYNC_TABLES))
    def test_inServerTableRegistry(self, tableName: str) -> None:
        assert tableName in _TABLE_REGISTRY

    @pytest.mark.parametrize("tableName", sorted(EDR_SYNC_TABLES))
    def test_inAcceptedTables(self, tableName: str) -> None:
        assert tableName in ACCEPTED_TABLES

    @pytest.mark.parametrize("tableName", sorted(EDR_SYNC_TABLES))
    def test_piSideRegisteredOnIdCursor(self, tableName: str) -> None:
        """US-766's half -- asserted here too because the pair must agree.

        A server table with no Pi registration is a destination nothing reaches;
        a Pi registration with no server table is a push that 404s every tick.
        """
        assert PK_COLUMN[tableName] == "id"
        assert tableName in DELTA_SYNC_TABLES


# ================================================================================
# Upsert behaviour
# ================================================================================


class TestRunSyncUpsertEdr:
    """Pi delta rows land keyed on the triple, idempotently."""

    def _imuRow(self, rowId: int, ts: str = "2026-09-16T00:00:01Z") -> dict:
        return {
            "id": rowId,
            "ts_utc": ts,
            "ts_capture": 1234.5,
            "seq": 7,
            "accel_x": 0.1, "accel_y": -0.2, "accel_z": 9.81,
            "gyro_x": 0.01, "gyro_y": 0.02, "gyro_z": 0.03,
            "mag_x": 1.0, "mag_y": 2.0, "mag_z": 3.0,
            "temp_c": 31.5,
            "drive_id": None,
            "data_source": "real",
            "schema_version": 1,
        }

    def test_landsNewRow(self) -> None:
        session = _newSession()
        result = runSyncUpsert(
            session,
            deviceId="chi-eclipse-01",
            batchId="b1",
            tables={"edr_imu_sample": {"rows": [self._imuRow(5)]}},
            syncHistoryId=42,
        )
        assert result["edr_imu_sample"] == {
            "inserted": 1, "updated": 0, "errors": 0,
        }
        row = session.query(EdrImuSample).one()
        assert row.source_id == 5
        assert row.source_device == "chi-eclipse-01"
        assert row.accel_z == pytest.approx(9.81)
        assert row.sync_batch_id == 42

    def test_driveIdNullIsPreservedNotFabricated(self) -> None:
        """An unattributed sample stays unattributed.

        ``drive_id`` is NULL by the A-9/KOEO latch rule whenever no drive is
        RUNNING.  Coercing it to a drive on the way in would manufacture an
        attribution the Pi deliberately withheld.
        """
        session = _newSession()
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b1",
            tables={"edr_imu_sample": {"rows": [self._imuRow(1)]}},
            syncHistoryId=1,
        )
        assert session.query(EdrImuSample).one().drive_id is None

    def test_resyncIsIdempotent(self) -> None:
        session = _newSession()
        row = self._imuRow(6)
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b1",
            tables={"edr_imu_sample": {"rows": [dict(row)]}},
            syncHistoryId=1,
        )
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b2",
            tables={"edr_imu_sample": {"rows": [dict(row)]}},
            syncHistoryId=2,
        )
        assert session.query(EdrImuSample).count() == 1

    def test_twoDevicesDoNotCollide(self) -> None:
        """The whole reason source_device is in the key."""
        session = _newSession()
        shared = self._imuRow(1)
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b1",
            tables={"edr_imu_sample": {"rows": [dict(shared)]}},
            syncHistoryId=1,
        )
        runSyncUpsert(
            session, deviceId="bmw-f30-01", batchId="b2",
            tables={"edr_imu_sample": {"rows": [dict(shared)]}},
            syncHistoryId=2,
        )
        assert session.query(EdrImuSample).count() == 2

    def test_lightSampleLandsToo(self) -> None:
        session = _newSession()
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b1",
            tables={"edr_light_sample": {"rows": [{
                "id": 3,
                "ts_utc": "2026-09-16T00:00:02Z",
                "ts_capture": 99.5,
                "seq": 2,
                "lux": None,
                "visible": 10, "infrared": 4, "full_spectrum": 14,
                "gain": "MED", "integration_ms": 100,
                "drive_id": None,
                "data_source": "real",
                "schema_version": 1,
            }]}},
            syncHistoryId=1,
        )
        row = session.query(EdrLightSample).one()
        assert row.source_id == 3
        # A saturated read is NULL, never 0 -- 0 lux reads as darkness.
        assert row.lux is None

    def test_preExistingTableStillUpsertsUnchanged(self) -> None:
        """PowerLog must behave exactly as it did before the seam landed."""
        session = _newSession()
        row = {
            "id": 6, "timestamp": "2026-09-16T00:00:00Z",
            "event_type": "AC_RESTORED", "power_source": "AC",
            "on_ac_power": 1, "vcell": 4.05,
        }
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b1",
            tables={"power_log": {"rows": [dict(row)]}}, syncHistoryId=1,
        )
        result = runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b2",
            tables={"power_log": {"rows": [dict(row)]}}, syncHistoryId=2,
        )
        assert result["power_log"] == {"inserted": 0, "updated": 1, "errors": 0}
        assert session.query(PowerLog).count() == 1


# ================================================================================
# v0026 migration
# ================================================================================


class TestV0026Migration:
    """The migration GENERATES its DDL; it never restates the shape."""

    def test_registeredInAllMigrations(self) -> None:
        from src.server.migrations import ALL_MIGRATIONS

        versions = [m.version for m in ALL_MIGRATIONS]
        assert "0026" in versions
        assert versions == sorted(versions), "registry must stay ascending"

    def test_versionIsUnique(self) -> None:
        from src.server.migrations import ALL_MIGRATIONS

        versions = [m.version for m in ALL_MIGRATIONS]
        assert len(versions) == len(set(versions)), (
            "two migrations sharing a version silently corrupts the ledger"
        )

    def test_ddlComesFromTheGenerator(self) -> None:
        """Compare against server_ddl.py rather than restating the shape.

        If this test restated the expected DDL it would pin a SECOND copy of the
        contract, which is the divergence A-4 exists to prevent.
        """
        from src.server.migrations.versions import v0026_us765_edr_raw_tables as mod

        expected = buildAllRawTableDdl(
            firstMonth=mod.FIRST_PARTITION_MONTH, months=mod.PARTITION_MONTHS,
        )
        assert mod.edrRawTableDdl() == expected

    def test_generatedDdlCarriesTheCompositeKeyAndNoSurrogateId(self) -> None:
        ddl = buildRawTableDdl(
            "edr_imu_sample", firstMonth=date(2026, 9, 1), months=2,
        )
        assert "PRIMARY KEY (source_device, source_id, ts_utc)" in ddl
        assert "AUTO_INCREMENT" not in ddl
        assert "PAGE_COMPRESSED=1" in ddl
        assert "PARTITION pmax VALUES LESS THAN (MAXVALUE)" in ddl
