################################################################################
# File Name: test_edr_gyro_rate_bias_crosses_tiers.py
# Purpose/Description: US-810 -- the five gyro RATE bias columns exist on the
#                      server model, v0031 adds them to the live table (and is a
#                      no-op when present), and an edr_imu_derived sync carrying
#                      them succeeds rather than raising the US-689 guard.
# Author: Rex (US-810)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-24    | Rex (US-810) | Initial.
# ================================================================================
################################################################################
"""No Pi column without its server counterpart (US-810, acceptance 4)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scripts import apply_server_migrations as asm
from src.common.edr.sensor_schema import EDR_IMU_DERIVED_GYRO_RATE_BIAS_COLUMNS
from src.common.edr.server_ddl import KIND_TYPES
from src.server.api.sync import runSyncUpsert
from src.server.db.models import Base, EdrImuDerived
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0027_us805_edr_imu_derived as m0027
from src.server.migrations.versions import v0031_us810_edr_gyro_rate_bias as m0031

NEW_COLUMNS = tuple(name for name, _ in EDR_IMU_DERIVED_GYRO_RATE_BIAS_COLUMNS)

# edr_imu_derived on the live server before v0031 (v0027's shape at US-805).
_COLS_BEFORE = (
    "source_device\nsource_id\nts_utc\nts_capture\nseq\npitch_deg\nstop_count\n"
    "bias_rad\nfusion_version\ndrive_id\ndata_source\nschema_version\n"
    "synced_at\nsync_batch_id\n"
)
_COLS_AFTER = _COLS_BEFORE + "".join(f"{name}\n" for name in NEW_COLUMNS)


@dataclass
class FakeRunner:
    """Scripted subprocess stand-in. First matching needle wins."""

    handlers: list[tuple[str, Callable[[str], subprocess.CompletedProcess[str]]]] = (
        field(default_factory=list)
    )
    calls: list[str] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002 -- subprocess API parity
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        sql = input or ""
        self.calls.append(sql)
        for needle, handler in self.handlers:
            if needle in sql:
                return handler(sql)
        return _ok()

    @property
    def alters(self) -> list[str]:
        return [sql for sql in self.calls if "ALTER TABLE" in sql]


def _ok(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _ctx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(
        addrs=asm.HostAddresses(serverHost="10.27.27.10", serverUser="mcornelison"),
        creds=asm.ServerCreds(dbUser="obd2", dbPassword="secret", dbName="obd2db"),
        runner=runner,
    )


def _runner(columnSets: list[str], tableExists: bool = True) -> FakeRunner:
    """Column probes answer from ``columnSets`` in order (last one repeats)."""
    runner = FakeRunner()
    probes = {"n": 0}

    def columns(_sql: str) -> subprocess.CompletedProcess[str]:
        index = min(probes["n"], len(columnSets) - 1)
        probes["n"] += 1
        return _ok(columnSets[index])

    runner.handlers.append(
        ("information_schema.TABLES", lambda _sql: _ok("1\n" if tableExists else "0\n"))
    )
    runner.handlers.append(("information_schema.COLUMNS", columns))
    return runner


class TestServerModel:
    def test_modelDeclaresTheFiveColumns_nullable(self) -> None:
        columns = EdrImuDerived.__table__.columns
        for name in NEW_COLUMNS:
            assert name in columns, name
            assert columns[name].nullable, name


class TestMigrationV0031:
    def test_isRegisteredLast_asV0031(self) -> None:
        """Chain order: US-810 v0031, then US-683 v0032, then US-790 v0033."""
        assert m0031.MIGRATION.version == "0031"
        assert m0031.MIGRATION in ALL_MIGRATIONS
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions.index("0031") == versions.index("0030") + 1

    def test_liveServer_addsEveryColumn_thenVerifiesThem(self) -> None:
        runner = _runner([_COLS_BEFORE, _COLS_AFTER])

        m0031.apply(_ctx(runner))

        assert runner.alters == [m0031.ADD_COLUMN_DDL[name] for name in NEW_COLUMNS]

    def test_alreadyPresent_isANoOp(self) -> None:
        """A fresh server gets the columns from v0027 (generated from the contract)."""
        runner = _runner([_COLS_AFTER])

        m0031.apply(_ctx(runner))

        assert runner.alters == []

    def test_partialEarlierRun_addsOnlyWhatIsMissing(self) -> None:
        partial = _COLS_BEFORE + "gyro_bias_roll_rad_s\ngyro_bias_pitch_rad_s\n"
        runner = _runner([partial, _COLS_AFTER])

        m0031.apply(_ctx(runner))

        assert runner.alters == [m0031.ADD_COLUMN_DDL[name] for name in NEW_COLUMNS[2:]]

    def test_missingTable_raises(self) -> None:
        with pytest.raises(asm.MigrationError, match="edr_imu_derived"):
            m0031.apply(_ctx(_runner([_COLS_BEFORE], tableExists=False)))

    def test_anAlterThatLeavesTheColumnAbsent_raises(self) -> None:
        """A 'success' that changed nothing is a failure, not a clean migration."""
        with pytest.raises(asm.MigrationError, match="still lacks"):
            m0031.apply(_ctx(_runner([_COLS_BEFORE, _COLS_BEFORE])))

    def test_aFailingAlter_raisesNamingTheColumn(self) -> None:
        runner = _runner([_COLS_BEFORE])
        runner.handlers.insert(0, (
            "ALTER TABLE",
            lambda _sql: subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="boom",
            ),
        ))
        with pytest.raises(asm.MigrationError, match="gyro_bias_roll_rad_s"):
            m0031.apply(_ctx(runner))

    def test_ddlTypesMatchTheFreshTableGenerator(self) -> None:
        """v0031 on the live table and v0027 on a fresh one must agree on every type."""
        fresh = m0027.edrDerivedTableDdl()
        for name, sqlType, _after in m0031.GYRO_RATE_BIAS_COLUMNS:
            assert f"{name} {sqlType}" in fresh, (name, sqlType)
            assert sqlType in KIND_TYPES.values()
            assert f"{name} {sqlType} NULL AFTER" in m0031.ADD_COLUMN_DDL[name]

    def test_revertDropsExactlyTheFiveColumns(self) -> None:
        assert all(f"DROP COLUMN {name}" in m0031.REVERT_DDL for name in NEW_COLUMNS)
        assert m0031.REVERT_DDL.count("DROP COLUMN") == 5


def _derivedRow(sourceId: int, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": sourceId, "ts_utc": "2026-09-24T12:00:00", "ts_capture": 100.0 + sourceId,
        "seq": sourceId, "pitch_deg": -3.9, "stop_count": 1, "bias_rad": 0.0,
        "fusion_version": 1, "drive_id": None, "data_source": "real", "schema_version": 1,
    }
    row.update(extra)
    return row


class TestSyncRoundTrip:
    """US-689 RAISES on a Pi-only column; with v0031's columns the sync succeeds."""

    def _session(self) -> Session:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return Session(engine)

    def test_learnedAndUnlearnedRows_syncAndKeepNULLAsNULL(self) -> None:
        session = self._session()
        learned = _derivedRow(
            1, gyro_bias_roll_rad_s=0.004, gyro_bias_pitch_rad_s=-0.003,
            gyro_bias_yaw_rad_s=0.002, gyro_bias_stops=1, gyro_bias_rejected_stops=0,
        )
        unlearned = _derivedRow(
            2, gyro_bias_roll_rad_s=None, gyro_bias_pitch_rad_s=None,
            gyro_bias_yaw_rad_s=None, gyro_bias_stops=0, gyro_bias_rejected_stops=1,
        )

        result = runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b1",
            tables={"edr_imu_derived": {"rows": [learned, unlearned]}}, syncHistoryId=1,
        )

        assert result["edr_imu_derived"]["inserted"] == 2
        rows = {
            r.source_id: r for r in session.execute(select(EdrImuDerived)).scalars().all()
        }
        assert rows[1].gyro_bias_pitch_rad_s == pytest.approx(-0.003)
        assert rows[1].gyro_bias_stops == 1
        assert rows[2].gyro_bias_roll_rad_s is None
        assert rows[2].gyro_bias_pitch_rad_s is None
        assert rows[2].gyro_bias_yaw_rad_s is None
        assert rows[2].gyro_bias_rejected_stops == 1

    def test_control_aColumnTheServerLacks_stillRaises(self) -> None:
        """The guard the round-trip depends on is live -- this is what v0031 prevents."""
        session = self._session()
        with pytest.raises(ValueError, match="gyro_bias_temp_c"):
            runSyncUpsert(
                session, deviceId="chi-eclipse-01", batchId="b1",
                tables={"edr_imu_derived": {"rows": [_derivedRow(1, gyro_bias_temp_c=1.0)]}},
                syncHistoryId=1,
            )
