################################################################################
# File Name: test_edr_contract.py
# Purpose/Description: US-764 -- the shared EDR contract. EDR_COLUMNS is pinned
#                      to the Pi DDL (names, order, kind, nullability) with a
#                      mutation proving the pin discriminates; the Pi EDR DDL is
#                      SHA-256 pinned byte-identical (D8); the sync contract and
#                      the generated MariaDB DDL are checked against the ruling.
# Author: Rex (US-764)
# Creation Date: 2026-09-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-15    | Rex (US-764) | Initial -- contract pin, mutation, D8 hashes,
#               |              | sync contract, server DDL generator.
# ================================================================================
################################################################################
"""Tests for the shared EDR contract (US-764)."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import date

import pytest

from src.common.edr.sensor_schema import (
    EDR_COLUMNS,
    EDR_INDEXES,
    EDR_SCHEMAS,
    SCHEMA_EDR_IMU_DERIVED,
    SCHEMA_EDR_IMU_SAMPLE,
    SCHEMA_EDR_LIGHT_SAMPLE,
)
from src.common.edr.server_ddl import (
    KIND_TYPES,
    buildAddPartitionSql,
    buildAllRawTableDdl,
    buildDropPartitionSql,
    buildRawTableDdl,
    main,
    monthStarts,
    partitionName,
)
from src.common.edr.sync_contract import EDR_SYNC_TABLES, SHUTDOWN_DRAIN_EXCLUDED_TABLES

PI_DDL: dict[str, str] = {
    "edr_imu_sample": SCHEMA_EDR_IMU_SAMPLE,
    "edr_light_sample": SCHEMA_EDR_LIGHT_SAMPLE,
    "edr_imu_derived": SCHEMA_EDR_IMU_DERIVED,   # US-805
}

# The SQLite declared type each ruled kind must carry on the Pi side.
KIND_SQLITE_TYPES: dict[str, str] = {
    "iso_ts": "TEXT",
    "monotonic_s": "REAL",
    "int": "INTEGER",
    "float": "REAL",
    "label": "TEXT",
}

# D8: sha256 of each string's UTF-8 as imported at the fork commit (dev 5d5022e2;
# sensor_schema.py unchanged since 21273b94). Values from the US-764 story.
D8_DDL_SHA256: dict[str, str] = {
    "edr_imu_sample": "00b602ddb8bb5b1a4f8422c2316773cb15f59c9c344cdd343414374cf9cffaf3",
    "edr_light_sample": "53a164de49b5dec23ddc3aa399bd4e7e253adc38e8212bf38158517b1fcfdffb",
    "ix_edr_imu_sample_drive_id": (
        "a9f8ae4dbb0cca6e7ee594e5d4edacceac8c5f47b6a7fccb40f3b442220dec10"
    ),
    "ix_edr_imu_sample_ts": "5ead89a54d84b29de1e279fdd29404498fafd760d0fe858ecb52a8ccb1d363ee",
    "ix_edr_light_sample_drive_id": (
        "8a0342edc6edc3f36183b95597db8f074d059ad904be0683a9228991a1da818b"
    ),
    "ix_edr_light_sample_ts": "8e450bc140a46d6452032f7662a025cd1d45712f6736cf284ffcf75ed4fa4ae9",
    # US-805 / ARCH-045, pinned 2026-09-22 at creation. Same purpose as the
    # D8 entries above: these strings may not drift silently once shipped.
    # US-810, re-pinned 2026-09-24: five gyro RATE bias columns appended
    # (was f7ac9b1f...eacf1). Existing Pi tables reach the same shape via
    # ensureEdrImuDerivedGyroRateBiasColumns, the server via v0031.
    "edr_imu_derived": "bcfb0d054e4ce57eec0f5927aee2664c8e129483183df27f15ba60e28d865c77",
    "ix_edr_imu_derived_drive_id": (
        "c20af6ef68e87fa568a87d36d10c709898df2f9fea69f2efa348470849d2b490"
    ),
    "ix_edr_imu_derived_ts": "2fa51a0d81ead089512c18fc4097fdf6e65b29a557f9f972bf3af5c809ef6214",
}

FIRST_MONTH = date(2026, 9, 1)


def _piColumns(tableName: str) -> list[tuple[str, str, bool]]:
    """(name, declared SQLite type, nullable) per Pi column, id PK excluded.

    Read from SQLite itself (PRAGMA table_info on the real DDL), not a regex.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(PI_DDL[tableName])
        rows = conn.execute(f"PRAGMA table_info({tableName})").fetchall()
    finally:
        conn.close()
    return [(name, colType, not notNull) for _, name, colType, notNull, _, pk in rows if not pk]


def _assertColumnsPinned(edrColumns: dict[str, tuple[tuple[str, str, bool], ...]]) -> None:
    """Fail naming every column where EDR_COLUMNS and the Pi DDL disagree."""
    assert set(edrColumns) == set(PI_DDL), f"tables differ: {sorted(set(edrColumns) ^ set(PI_DDL))}"
    for table, columns in edrColumns.items():
        pi = _piColumns(table)
        contractNames = [name for name, _, _ in columns]
        piNames = [name for name, _, _ in pi]
        assert contractNames == piNames, (
            f"{table}: column names/order differ; only in EDR_COLUMNS="
            f"{[n for n in contractNames if n not in piNames]}, only in Pi DDL="
            f"{[n for n in piNames if n not in contractNames]}, "
            f"EDR_COLUMNS={contractNames}, Pi={piNames}"
        )
        for (name, kind, nullable), (_, sqliteType, piNullable) in zip(columns, pi, strict=True):
            assert KIND_SQLITE_TYPES.get(kind) == sqliteType, (
                f"{table}.{name}: kind {kind!r} does not match Pi type {sqliteType!r}"
            )
            assert nullable == piNullable, (
                f"{table}.{name}: nullable={nullable} but Pi NOT NULL={not piNullable}"
            )


class TestEdrColumnsPin:
    def test_edrColumns_matchPiDdl_namesOrderKindAndNullability(self) -> None:
        _assertColumnsPinned(EDR_COLUMNS)

    def test_piColumns_excludeOnlyTheIdPk(self) -> None:
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(SCHEMA_EDR_IMU_SAMPLE)
            pks = [r[1] for r in conn.execute("PRAGMA table_info(edr_imu_sample)") if r[5]]
        finally:
            conn.close()
        assert pks == ["id"]

    # US-805 / ARCH-045: parametrized over EDR_COLUMNS itself, not a hardcoded
    # pair. A new table used to inherit the PIN without ever inheriting the
    # DEMONSTRATION that the pin discriminates for it -- the guard existed and
    # had never been shown to fail. Deriving the table LIST from the registry
    # is not circular: the mutation and the assertion are still independent,
    # and it makes mutation coverage self-extending (design-patterns.md SS7 --
    # pin the DIRECTION, not the MEMBERSHIP).
    @pytest.mark.parametrize("table", sorted(EDR_COLUMNS))
    def test_pin_columnAddedToEdrColumnsAlone_failsNamingTheColumn(self, table: str) -> None:
        mutated = dict(EDR_COLUMNS)
        mutated[table] = (*EDR_COLUMNS[table], ("mutant_col", "float", True))

        with pytest.raises(AssertionError, match="mutant_col"):
            _assertColumnsPinned(mutated)

    def test_pin_kindChangedAlone_fails(self) -> None:
        mutated = dict(EDR_COLUMNS)
        name, _, nullable = EDR_COLUMNS["edr_light_sample"][0]
        mutated["edr_light_sample"] = (
            (name, "float", nullable),
            *EDR_COLUMNS["edr_light_sample"][1:],
        )

        with pytest.raises(AssertionError, match=name):
            _assertColumnsPinned(mutated)

    def test_pin_nullabilityFlippedAlone_fails(self) -> None:
        mutated = dict(EDR_COLUMNS)
        name, kind, nullable = EDR_COLUMNS["edr_imu_sample"][0]
        mutated["edr_imu_sample"] = (
            (name, kind, not nullable),
            *EDR_COLUMNS["edr_imu_sample"][1:],
        )

        with pytest.raises(AssertionError, match=name):
            _assertColumnsPinned(mutated)

    def test_edrColumns_everyKindIsInTheRuledMap(self) -> None:
        for table, columns in EDR_COLUMNS.items():
            for name, kind, nullable in columns:
                assert kind in KIND_TYPES, (table, name, kind)
                assert isinstance(nullable, bool), (table, name)


class TestPiDdlByteIdentical:
    @pytest.mark.parametrize(("name", "ddl"), [*EDR_SCHEMAS, *EDR_INDEXES])
    def test_piEdrDdl_sha256_unchangedSinceFork(self, name: str, ddl: str) -> None:
        assert hashlib.sha256(ddl.encode("utf-8")).hexdigest() == D8_DDL_SHA256[name]

    def test_pinnedSet_coversEveryEdrDdlString(self) -> None:
        assert {n for n, _ in (*EDR_SCHEMAS, *EDR_INDEXES)} == set(D8_DDL_SHA256)


class TestSyncContract:
    def test_edrSyncTables_areTheTwoEdrTables(self) -> None:
        assert EDR_SYNC_TABLES == (
            "edr_imu_sample",
            "edr_light_sample",
            "edr_imu_derived",   # US-805
        )

    def test_shutdownDrainExcluded_containsEveryEdrTable(self) -> None:
        assert SHUTDOWN_DRAIN_EXCLUDED_TABLES == frozenset(EDR_SYNC_TABLES)

    def test_syncTables_matchContractTables(self) -> None:
        assert set(EDR_SYNC_TABLES) == set(EDR_COLUMNS)


def _columnDefs(ddl: str) -> dict[str, str]:
    """Column name -> the rest of its definition line, from generated DDL."""
    body = ddl[ddl.index("(\n") + 2 : ddl.index("\n)")]
    defs: dict[str, str] = {}
    for line in body.split(",\n"):
        name, _, rest = line.strip().partition(" ")
        if name not in {"PRIMARY", "KEY"}:
            defs[name] = rest
    return defs


class TestServerDdl:
    @pytest.mark.parametrize("table", ["edr_imu_sample", "edr_light_sample"])
    def test_rawDdl_columnsAreServerColumnsPlusContractInOrder(self, table: str) -> None:
        ddl = buildRawTableDdl(table, firstMonth=FIRST_MONTH, months=2)

        assert list(_columnDefs(ddl)) == [
            "source_device",
            "source_id",
            *(name for name, _, _ in EDR_COLUMNS[table]),
            "synced_at",
            "sync_batch_id",
        ]

    @pytest.mark.parametrize("table", ["edr_imu_sample", "edr_light_sample"])
    def test_rawDdl_typesFollowKindMapAndNullability(self, table: str) -> None:
        defs = _columnDefs(buildRawTableDdl(table, firstMonth=FIRST_MONTH, months=1))

        assert defs["source_device"] == "VARCHAR(64) NOT NULL"
        assert defs["source_id"] == "BIGINT NOT NULL"
        assert defs["synced_at"] == "DATETIME"
        assert defs["sync_batch_id"] == "INT"
        for name, kind, nullable in EDR_COLUMNS[table]:
            assert defs[name] == KIND_TYPES[kind] + ("" if nullable else " NOT NULL"), name

    def test_kindTypes_areTheRuledMap(self) -> None:
        assert KIND_TYPES == {
            "iso_ts": "DATETIME",
            "monotonic_s": "DOUBLE",
            "int": "INT",
            "float": "FLOAT",
            "label": "VARCHAR(16)",
        }

    @pytest.mark.parametrize("table", ["edr_imu_sample", "edr_light_sample"])
    def test_rawDdl_keysPartitionsCompression(self, table: str) -> None:
        ddl = buildRawTableDdl(table, firstMonth=date(2026, 11, 17), months=3)

        assert "PRIMARY KEY (source_device, source_id, ts_utc)" in ddl
        assert re.search(r"\n  KEY \w+ \(source_device, ts_utc\)\n", ddl)
        assert "PAGE_COMPRESSED=1" in ddl
        assert "PARTITION BY RANGE COLUMNS(ts_utc) (" in ddl
        assert re.findall(r"PARTITION (\w+) VALUES LESS THAN \(([^)]*)\)", ddl) == [
            ("p202611", "'2026-12-01'"),
            ("p202612", "'2027-01-01'"),
            ("p202701", "'2027-02-01'"),
            ("pmax", "MAXVALUE"),
        ]

    @pytest.mark.parametrize("ddl", buildAllRawTableDdl(firstMonth=FIRST_MONTH, months=2))
    def test_rawDdl_noCheckNoIdNoAutoIncrement(self, ddl: str) -> None:
        assert "CHECK" not in ddl
        assert "AUTO_INCREMENT" not in ddl
        assert "id" not in _columnDefs(ddl)
        assert not re.search(r"\bid\b", ddl)

    def test_allRawTableDdl_oneTablePerSyncTable(self) -> None:
        statements = buildAllRawTableDdl(firstMonth=FIRST_MONTH, months=1)

        assert [re.match(r"CREATE TABLE IF NOT EXISTS (\w+) \(", s).group(1) for s in statements] == (
            list(EDR_SYNC_TABLES)
        )

    def test_rawDdl_unknownTable_raises(self) -> None:
        with pytest.raises(ValueError, match="realtime_data"):
            buildRawTableDdl("realtime_data", firstMonth=FIRST_MONTH, months=1)

    def test_rawDdl_kindOutsideRuledMap_raisesNamingColumn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mutated = dict(EDR_COLUMNS)
        mutated["edr_light_sample"] = (*EDR_COLUMNS["edr_light_sample"], ("blob_col", "blob", True))
        monkeypatch.setattr("src.common.edr.server_ddl.EDR_COLUMNS", mutated)

        with pytest.raises(ValueError, match="blob_col"):
            buildRawTableDdl("edr_light_sample", firstMonth=FIRST_MONTH, months=1)

    def test_addPartition_reorganizesPmax(self) -> None:
        assert buildAddPartitionSql("edr_imu_sample", date(2026, 12, 1)) == (
            "ALTER TABLE edr_imu_sample REORGANIZE PARTITION pmax INTO ("
            "PARTITION p202612 VALUES LESS THAN ('2027-01-01'), "
            "PARTITION pmax VALUES LESS THAN (MAXVALUE));"
        )

    def test_dropPartition_dropsTheMonth(self) -> None:
        assert buildDropPartitionSql("edr_light_sample", date(2024, 9, 30)) == (
            "ALTER TABLE edr_light_sample DROP PARTITION p202409;"
        )

    def test_partitionSql_unknownTable_raises(self) -> None:
        with pytest.raises(ValueError):
            buildAddPartitionSql("drive_summary", FIRST_MONTH)
        with pytest.raises(ValueError):
            buildDropPartitionSql("drive_summary", FIRST_MONTH)

    def test_monthStarts_crossesYearAndRejectsNegative(self) -> None:
        assert monthStarts(date(2026, 11, 20), 3) == [
            date(2026, 11, 1),
            date(2026, 12, 1),
            date(2027, 1, 1),
        ]
        assert monthStarts(FIRST_MONTH, 0) == []
        with pytest.raises(ValueError):
            monthStarts(FIRST_MONTH, -1)

    def test_partitionName_isYearMonth(self) -> None:
        assert partitionName(date(2026, 9, 15)) == "p202609"


class TestCli:
    def test_create_printsEveryTable(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["create", "--first-month", "2026-09", "--months", "2"]) == 0

        out = capsys.readouterr().out
        assert out.strip() == "\n\n".join(buildAllRawTableDdl(firstMonth=FIRST_MONTH, months=2))

    def test_addAndDropPartition_print(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["add-partition", "--table", "edr_imu_sample", "--month", "2026-12"]) == 0
        assert main(["drop-partition", "--table", "edr_imu_sample", "--month", "2024-09"]) == 0

        out = capsys.readouterr().out
        assert buildAddPartitionSql("edr_imu_sample", date(2026, 12, 1)) in out
        assert buildDropPartitionSql("edr_imu_sample", date(2024, 9, 1)) in out

    def test_unknownTable_exitsTwo(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["drop-partition", "--table", "nope", "--month", "2024-09"]) == 2
        assert "nope" in capsys.readouterr().err


# --- US-805 / ARCH-045: the derived-values sibling table -----------------------
# Atlas, 2026-09-22, under CIO override (see board/wip/ARCH-045.md). The CIO
# ruled a SEPARATE TABLE: a raw reading never changes, a computed value changes
# when the ALGORITHM changes, so mixing them leaves early and late rows meaning
# subtly different things with nothing marking where the maths moved.
DERIVED_TABLE = "edr_imu_derived"

#: The ruled column list, in order. Kept here as a LITERAL rather than read from
#: EDR_COLUMNS: a test that derives its expectation from the thing under test
#: cannot fail. (design-patterns.md SS6 -- the inert guard.)
_RULED_DERIVED_COLUMNS: tuple[tuple[str, str, bool], ...] = (
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
    # US-810: the gyro RATE bias (rad/s) and its stop counts, all nullable.
    ("gyro_bias_roll_rad_s", "float", True),
    ("gyro_bias_pitch_rad_s", "float", True),
    ("gyro_bias_yaw_rad_s", "float", True),
    ("gyro_bias_stops", "int", True),
    ("gyro_bias_rejected_stops", "int", True),
)


class TestEdrImuDerivedContract:
    """US-805: the derived table joins the contract on the same terms as raw."""

    def test_derivedTable_isRegisteredInEdrColumns(self) -> None:
        assert DERIVED_TABLE in EDR_COLUMNS

    def test_derivedColumns_matchTheRuling_namesOrderKindAndNullability(self) -> None:
        assert EDR_COLUMNS[DERIVED_TABLE] == _RULED_DERIVED_COLUMNS

    def test_fusionVersion_isNotNull(self) -> None:
        """Without it the table cannot say WHICH algorithm produced a row.

        That is the defect the separate table exists to prevent, so a nullable
        fusion_version would buy a second table and nothing else.
        """
        kinds = {name: (kind, nullable) for name, kind, nullable in EDR_COLUMNS[DERIVED_TABLE]}
        assert kinds["fusion_version"] == ("int", False)

    def test_pitchDeg_isNULLABLE(self) -> None:
        """`pitchRad` returns None under gyro_implausible (US-749).

        That null is a FINDING -- the only evidence the guard fired. A writer or
        a schema that coerces it to 0.0 destroys it.
        """
        kinds = {name: (kind, nullable) for name, kind, nullable in EDR_COLUMNS[DERIVED_TABLE]}
        assert kinds["pitch_deg"] == ("float", True)

    def test_derivedTable_hasPiDdlAndIndexes(self) -> None:
        assert DERIVED_TABLE in {name for name, _ in EDR_SCHEMAS}
        indexed = {name for name, _ in EDR_INDEXES}
        assert f"ix_{DERIVED_TABLE}_ts" in indexed
        assert f"ix_{DERIVED_TABLE}_drive_id" in indexed

    def test_derivedTable_syncsLikeTheRawTables(self) -> None:
        """It is EDR data: synced, and excluded from the shutdown drain."""
        assert DERIVED_TABLE in EDR_SYNC_TABLES
        assert DERIVED_TABLE in SHUTDOWN_DRAIN_EXCLUDED_TABLES

    def test_derivedTable_carriesNoForeignKeyToTheRawPk(self) -> None:
        """A-45: the Pi `id` is the PI's id-space; on the server it is source_id.

        A cross-tier FK on a synced surrogate is fragile by construction -- the
        join is (source_device, ts_capture), which is why ts_capture is NOT NULL.
        """
        ddl = dict(EDR_SCHEMAS)[DERIVED_TABLE]
        assert "REFERENCES" not in ddl.upper()
        kinds = {name: (kind, nullable) for name, kind, nullable in EDR_COLUMNS[DERIVED_TABLE]}
        assert kinds["ts_capture"] == ("monotonic_s", False)
