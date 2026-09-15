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

    @pytest.mark.parametrize("table", ["edr_imu_sample", "edr_light_sample"])
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
        assert EDR_SYNC_TABLES == ("edr_imu_sample", "edr_light_sample")

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
