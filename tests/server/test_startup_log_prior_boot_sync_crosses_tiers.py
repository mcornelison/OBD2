################################################################################
# File Name: test_startup_log_prior_boot_sync_crosses_tiers.py
# Purpose/Description: US-776-f -- the four startup_log prior_boot_* shutdown-
#                      sync columns exist on the server model with the Pi's
#                      names, v0034 adds them replay-safely (a re-run issues no
#                      ALTER), and the existing startup_log snapshot sync
#                      carries their values -- including NULL -- to the server.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-30    | Ralph (Rex)  | Initial -- US-776-f.
# ================================================================================
################################################################################
"""The prior-boot shutdown-sync columns cross the tier boundary (US-776-f)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest
from sqlalchemy import Integer, String, create_engine
from sqlalchemy.orm import Session

from scripts import apply_server_migrations as asm
from src.common.sync.snapshot_registry import getSnapshotSpec
from src.pi.obdii.database_schema import STARTUP_LOG_PRIOR_BOOT_SYNC_COLUMNS
from src.server.api.sync import runSyncUpsert
from src.server.db.models import StartupLog
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0034_us776f_startup_log_prior_boot_sync as m0034

_TABLE = "startup_log"
_NEW_COLUMNS = (
    "prior_boot_home_state",
    "prior_boot_sync_outcome",
    "prior_boot_backlog_start",
    "prior_boot_backlog_end",
)
_COLS_BEFORE = (
    "id\nsource_device\nsynced_at\nsync_batch_id\nboot_id\nprior_boot_clean\n"
    "prior_last_entry_ts\ncurrent_boot_first_entry_ts\nprior_boot_last_stage\n"
    "prior_boot_reason\nrecorded_at\n"
)
_COLS_AFTER = _COLS_BEFORE + "".join(f"{c}\n" for c in _NEW_COLUMNS)


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


def _runner(columnSets: list[str], *, tableExists: bool = True) -> FakeRunner:
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


# ================================================================================
# Server model
# ================================================================================


class TestServerModel:
    def test_modelDeclaresTheFourColumns_nullable(self) -> None:
        for name in _NEW_COLUMNS:
            assert StartupLog.__table__.columns[name].nullable, name

    def test_namesAndKindsMatchThePi(self) -> None:
        assert tuple(n for n, _ in STARTUP_LOG_PRIOR_BOOT_SYNC_COLUMNS) == _NEW_COLUMNS
        for name, piType in STARTUP_LOG_PRIOR_BOOT_SYNC_COLUMNS:
            serverType = StartupLog.__table__.columns[name].type
            expected = Integer if piType == "INTEGER" else String
            assert isinstance(serverType, expected), name

    def test_stringColumnsHoldTheLongestStateName(self) -> None:
        longest = len("AT_HOME_SERVER_REACHABLE")
        for name in ("prior_boot_home_state", "prior_boot_sync_outcome"):
            assert StartupLog.__table__.columns[name].type.length >= longest

    def test_syncIsStillSnapshot(self) -> None:
        """Atlas chose startup_log because it is NOT UPDATE-synced (US-789)."""
        spec = getSnapshotSpec(_TABLE)
        assert spec.naturalKeyCols == ("boot_id",)
        assert spec.cursorCol == "recorded_at"


# ================================================================================
# Migration v0034
# ================================================================================


class TestMigrationV0034:
    def test_isRegisteredDirectlyAfterV0033(self) -> None:
        assert m0034.MIGRATION.version == "0034"
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions.index("0034") == versions.index("0033") + 1

    def test_liveServer_addsExactlyTheFourColumns(self) -> None:
        runner = _runner([_COLS_BEFORE, _COLS_AFTER])

        m0034.apply(_ctx(runner))

        assert runner.alters == [m0034.ADD_COLUMN_DDL[c] for c in _NEW_COLUMNS]

    def test_reRun_issuesNoAlter(self) -> None:
        runner = _runner([_COLS_AFTER])

        m0034.apply(_ctx(runner))

        assert runner.alters == []

    def test_partialPriorApply_addsOnlyTheMissingColumns(self) -> None:
        partial = _COLS_BEFORE + "prior_boot_home_state\nprior_boot_sync_outcome\n"
        runner = _runner([partial, _COLS_AFTER])

        m0034.apply(_ctx(runner))

        assert runner.alters == [
            m0034.ADD_COLUMN_DDL["prior_boot_backlog_start"],
            m0034.ADD_COLUMN_DDL["prior_boot_backlog_end"],
        ]

    def test_missingTable_raises(self) -> None:
        with pytest.raises(asm.MigrationError, match="startup_log"):
            m0034.apply(_ctx(_runner([_COLS_BEFORE], tableExists=False)))

    def test_anAddThatLeavesAColumnAbsent_raises(self) -> None:
        with pytest.raises(asm.SchemaProbeError, match="still lacks"):
            m0034.apply(_ctx(_runner([_COLS_BEFORE, _COLS_BEFORE])))

    def test_aFailingAdd_raises(self) -> None:
        runner = _runner([_COLS_BEFORE, _COLS_AFTER])
        runner.handlers.insert(0, ("ADD COLUMN", _fail))
        with pytest.raises(asm.MigrationError, match="prior_boot_home_state"):
            m0034.apply(_ctx(runner))

    def test_ddlIsNullableWithNoDefault_andMatchesTheModelTypes(self) -> None:
        for name in _NEW_COLUMNS:
            ddl = m0034.ADD_COLUMN_DDL[name]
            assert "NULL" in ddl and "NOT NULL" not in ddl and "DEFAULT" not in ddl
        assert "INT" in m0034.ADD_COLUMN_DDL["prior_boot_backlog_start"]
        assert "VARCHAR(64)" in m0034.ADD_COLUMN_DDL["prior_boot_home_state"]

    def test_revertDropsExactlyTheFourColumns(self) -> None:
        for name in _NEW_COLUMNS:
            assert f"DROP COLUMN {name}" in m0034.REVERT_DDL


# ================================================================================
# The existing startup_log snapshot sync carries the values
# ================================================================================


def _newSession() -> Session:
    engine = create_engine("sqlite:///:memory:")
    StartupLog.__table__.create(engine)
    return Session(engine)


def _piRow(bootId: str, **sync: object) -> dict:
    row: dict[str, object] = {
        "boot_id": bootId,
        "prior_boot_clean": 1,
        "prior_last_entry_ts": None,
        "current_boot_first_entry_ts": None,
        "prior_boot_last_stage": "CLEAN_COMPLETE",
        "prior_boot_reason": "graceful",
        "recorded_at": "2026-09-30T20:00:00Z",
    }
    row.update(sync)
    return row


class TestSnapshotSyncCarriesTheColumns:
    def test_valuesLandOnTheServer(self) -> None:
        session = _newSession()
        row = _piRow(
            "boot-garage",
            prior_boot_home_state="AT_HOME_SERVER_REACHABLE",
            prior_boot_sync_outcome="DELIVERED",
            prior_boot_backlog_start=412,
            prior_boot_backlog_end=0,
        )

        runSyncUpsert(session, deviceId="chi-eclipse-01", batchId="b1",
                      tables={_TABLE: {"rows": [row]}}, syncHistoryId=1)

        landed = session.query(StartupLog).filter_by(boot_id="boot-garage").one()
        assert landed.prior_boot_home_state == "AT_HOME_SERVER_REACHABLE"
        assert landed.prior_boot_sync_outcome == "DELIVERED"
        assert landed.prior_boot_backlog_start == 412
        assert landed.prior_boot_backlog_end == 0
        assert landed.prior_boot_reason == "graceful"

    def test_nullsLandAsNull(self) -> None:
        session = _newSession()
        row = _piRow("boot-cut", **{c: None for c in _NEW_COLUMNS})

        runSyncUpsert(session, deviceId="chi-eclipse-01", batchId="b1",
                      tables={_TABLE: {"rows": [row]}}, syncHistoryId=1)

        landed = session.query(StartupLog).filter_by(boot_id="boot-cut").one()
        assert all(getattr(landed, c) is None for c in _NEW_COLUMNS)

    def test_aRowFromAnOlderPiBuild_stillSyncs(self) -> None:
        """A Pi that has not deployed the columns sends rows without them."""
        session = _newSession()

        result = runSyncUpsert(session, deviceId="chi-eclipse-01", batchId="b1",
                               tables={_TABLE: {"rows": [_piRow("boot-old")]}},
                               syncHistoryId=1)

        assert result[_TABLE] == {"inserted": 1, "updated": 0, "errors": 0}
        landed = session.query(StartupLog).filter_by(boot_id="boot-old").one()
        assert all(getattr(landed, c) is None for c in _NEW_COLUMNS)
