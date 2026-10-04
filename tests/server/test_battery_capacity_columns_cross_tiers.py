################################################################################
# File Name: test_battery_capacity_columns_cross_tiers.py
# Purpose/Description: ARCH-065 -- every Pi battery-capacity column (and the
#                      three startup_log prior-boot additions) exists on the
#                      server model with a matching kind, and migration v0035
#                      adds them replay-safely (a re-run issues no ALTER; a
#                      partial prior run is finished).
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author            | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a) | Initial.
# ================================================================================
################################################################################
"""The ARCH-065 capacity columns cross the tier boundary."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest
from sqlalchemy import Float, Integer, String

from scripts import apply_server_migrations as asm
from src.pi.obdii.database_schema import STARTUP_LOG_PRIOR_BOOT_SYNC_COLUMNS
from src.pi.power.battery_health import BATTERY_HEALTH_CAPACITY_COLUMNS
from src.server.db.models import BatteryHealthLog, StartupLog
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0035_arch065_battery_capacity_columns as m

_BH = "battery_health_log"
_SL = "startup_log"
_BH_NEW = tuple(m.COLUMNS[_BH])
_SL_NEW = tuple(m.COLUMNS[_SL])
_BH_BEFORE = "drain_event_id\nstart_timestamp\nend_timestamp\nload_class\nclose_reason\n"
_SL_BEFORE = "id\nboot_id\nprior_boot_clean\nprior_boot_backlog_end\n"
_BH_AFTER = _BH_BEFORE + "".join(f"{c}\n" for c in _BH_NEW)
_SL_AFTER = _SL_BEFORE + "".join(f"{c}\n" for c in _SL_NEW)


def test_everyPiCapacityColumn_existsOnTheServerModel() -> None:
    server = {c.name for c in BatteryHealthLog.__table__.columns}
    assert {name for name, _ in BATTERY_HEALTH_CAPACITY_COLUMNS} <= server


def test_startupLogTimesAndCutVcell_existOnTheServerModel() -> None:
    server = {c.name for c in StartupLog.__table__.columns}
    assert {n for n, _ in STARTUP_LOG_PRIOR_BOOT_SYNC_COLUMNS} <= server


def test_v0035_isRegisteredLast_andCoversBothTables() -> None:
    assert ALL_MIGRATIONS[-1].version == "0035"
    assert set(m.COLUMNS) == {_BH, _SL}


def test_migrationColumns_matchThePiNames_inOrder() -> None:
    assert _BH_NEW == tuple(n for n, _ in BATTERY_HEALTH_CAPACITY_COLUMNS)
    assert _SL_NEW == tuple(n for n, _ in STARTUP_LOG_PRIOR_BOOT_SYNC_COLUMNS[-3:])


def test_modelKinds_matchThePiKinds() -> None:
    kinds = {"TEXT": String, "REAL": Float, "INTEGER": Integer}
    for name, piType in BATTERY_HEALTH_CAPACITY_COLUMNS:
        column = BatteryHealthLog.__table__.columns[name]
        assert isinstance(column.type, kinds[piType.split()[0]]), name
    for name, piType in STARTUP_LOG_PRIOR_BOOT_SYNC_COLUMNS:
        assert isinstance(StartupLog.__table__.columns[name].type, kinds[piType]), name


def test_drainTrigger_isNotNull_everyOtherCapacityColumnIsNullable() -> None:
    cols = BatteryHealthLog.__table__.columns
    assert not cols["drain_trigger"].nullable
    assert all(cols[n].nullable for n in _BH_NEW if n != "drain_trigger")


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


def _fail(_sql: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")


def _ctx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(
        addrs=asm.HostAddresses(serverHost="10.27.27.10", serverUser="mcornelison"),
        creds=asm.ServerCreds(dbUser="obd2", dbPassword="secret", dbName="obd2db"),
        runner=runner,
    )


def _runner(
    bh: list[str], sl: list[str], *, missingTable: str | None = None,
) -> FakeRunner:
    """Per-table column probes answer from their list in order (last repeats)."""
    runner = FakeRunner()
    probes = {_BH: 0, _SL: 0}
    sets = {_BH: bh, _SL: sl}

    def columnsFor(table: str) -> Callable[[str], subprocess.CompletedProcess[str]]:
        def handler(_sql: str) -> subprocess.CompletedProcess[str]:
            index = min(probes[table], len(sets[table]) - 1)
            probes[table] += 1
            return _ok(sets[table][index])
        return handler

    def tables(sql: str) -> subprocess.CompletedProcess[str]:
        return _ok("0\n" if missingTable and f"'{missingTable}'" in sql else "1\n")

    runner.handlers.append(("information_schema.TABLES", tables))
    runner.handlers.append((f"TABLE_NAME='{_BH}'", columnsFor(_BH)))
    runner.handlers.append((f"TABLE_NAME='{_SL}'", columnsFor(_SL)))
    return runner


class TestMigrationV0035:
    def test_liveShapeApply_addsExactlyTheMissingColumnsPerTable(self) -> None:
        runner = _runner([_BH_BEFORE, _BH_AFTER], [_SL_BEFORE, _SL_AFTER])

        m.apply(_ctx(runner))

        assert runner.alters == (
            [m.ADD_COLUMN_DDL[_BH][c] for c in _BH_NEW]
            + [m.ADD_COLUMN_DDL[_SL][c] for c in _SL_NEW]
        )

    def test_reRun_issuesNoAlter(self) -> None:
        runner = _runner([_BH_AFTER], [_SL_AFTER])

        m.apply(_ctx(runner))

        assert runner.alters == []

    def test_partialPriorRun_finishesOnlyTheMissingColumns(self) -> None:
        partialBh = _BH_BEFORE + "drain_trigger\ncell_epoch\n"
        runner = _runner([partialBh, _BH_AFTER], [_SL_AFTER])

        m.apply(_ctx(runner))

        assert runner.alters == [m.ADD_COLUMN_DDL[_BH][c] for c in _BH_NEW[2:]]

    def test_missingTable_raises(self) -> None:
        runner = _runner([_BH_AFTER], [_SL_BEFORE], missingTable=_SL)
        with pytest.raises(asm.MigrationError, match=_SL):
            m.apply(_ctx(runner))

    def test_anAddThatLeavesAColumnAbsent_raises(self) -> None:
        runner = _runner([_BH_BEFORE, _BH_BEFORE], [_SL_AFTER])
        with pytest.raises(asm.SchemaProbeError, match="still lacks"):
            m.apply(_ctx(runner))

    def test_aFailingAdd_raises(self) -> None:
        runner = _runner([_BH_BEFORE, _BH_AFTER], [_SL_AFTER])
        runner.handlers.insert(0, ("ADD COLUMN", _fail))
        with pytest.raises(asm.MigrationError, match="drain_trigger"):
            m.apply(_ctx(runner))

    def test_ddl_drainTriggerNotNullDefaultKeyoff_everyOtherNullable(self) -> None:
        ddl = m.ADD_COLUMN_DDL[_BH]
        assert "NOT NULL DEFAULT 'keyoff'" in ddl["drain_trigger"]
        for table in (_BH, _SL):
            for name, stmt in m.ADD_COLUMN_DDL[table].items():
                if name != "drain_trigger":
                    assert stmt.endswith(" NULL;") and "NOT NULL" not in stmt, name

    def test_revertDropsEveryColumn(self) -> None:
        for table, columns in m.COLUMNS.items():
            for name in columns:
                assert f"DROP COLUMN {name}" in m.REVERT_DDL[table]
