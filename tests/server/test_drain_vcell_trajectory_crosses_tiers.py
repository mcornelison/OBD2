################################################################################
# File Name: test_drain_vcell_trajectory_crosses_tiers.py
# Purpose/Description: US-790 -- drain_vcell_trajectory exists on the server with
#                      the Pi's columns and termination vocabulary, v0033
#                      creates it (probe-guarded, registered after v0032), and a
#                      sync of the Pi's rows lands them -- NULL vcell_v, the one
#                      terminal row and cell_epoch included.
# Author: Rex (US-790)
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-25    | Rex (US-790) | Initial.
# ================================================================================
################################################################################
"""The drain VCELL series crosses the tier boundary (US-790)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scripts import apply_server_migrations as asm
from src.pi.power.types import DRAIN_TERMINATION_VALUES, DRAIN_VCELL_TRAJECTORY_TABLE
from src.server.api.sync import _TABLE_REGISTRY, runSyncUpsert
from src.server.db.models import (
    DRAIN_TERMINATION_REASON_VALUES,
    Base,
    DrainVcellTrajectory,
)
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0033_us790_drain_vcell_trajectory as m0033


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
    def creates(self) -> list[str]:
        return [sql for sql in self.calls if "CREATE TABLE" in sql]


def _ok(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _ctx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(
        addrs=asm.HostAddresses(serverHost="10.27.27.10", serverUser="mcornelison"),
        creds=asm.ServerCreds(dbUser="obd2", dbPassword="secret", dbName="obd2db"),
        runner=runner,
    )


def _runner(tableAnswers: list[bool], *, createFails: bool = False) -> FakeRunner:
    """Table-exists probes answer from ``tableAnswers`` in order (last repeats)."""
    runner = FakeRunner()
    probes = {"n": 0}

    def exists(_sql: str) -> subprocess.CompletedProcess[str]:
        index = min(probes["n"], len(tableAnswers) - 1)
        probes["n"] += 1
        return _ok("1\n" if tableAnswers[index] else "0\n")

    if createFails:
        runner.handlers.append((
            "CREATE TABLE",
            lambda _sql: subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="boom",
            ),
        ))
    runner.handlers.append(("information_schema.TABLES", exists))
    return runner


class TestServerModel:
    def test_isTheSyncedTable_withThePiColumns(self) -> None:
        columns = DrainVcellTrajectory.__table__.columns
        assert DrainVcellTrajectory.__tablename__ == DRAIN_VCELL_TRAJECTORY_TABLE
        assert {
            "source_id", "source_device", "ts_utc", "ts_capture", "seq",
            "vcell_v", "termination_reason", "cell_epoch",
        } <= set(columns.keys())
        assert columns["vcell_v"].nullable
        assert columns["termination_reason"].nullable
        assert not columns["cell_epoch"].nullable

    def test_vocabularyMatchesThePi(self) -> None:
        assert DRAIN_TERMINATION_REASON_VALUES == DRAIN_TERMINATION_VALUES

    def test_isAcceptedBySyncWithNoRename(self) -> None:
        assert _TABLE_REGISTRY[DRAIN_VCELL_TRAJECTORY_TABLE] == (DrainVcellTrajectory, ())

    @pytest.mark.parametrize("reason, rejected", [("drain_floor", False), ("died", True)])
    def test_modelCheck_acceptsTheVocabulary_andRejectsAnythingElse(
        self, reason: str, rejected: bool,
    ) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(DrainVcellTrajectory(
                source_id=1, source_device="d", ts_utc=datetime(2026, 9, 25, 18, 50),
                ts_capture=1.0, seq=0, termination_reason=reason, cell_epoch="unknown",
            ))
            if rejected:
                with pytest.raises(IntegrityError):
                    session.commit()
            else:
                session.commit()


class TestMigrationV0033:
    def test_isRegisteredDirectlyAfterV0032(self) -> None:
        """Chain order: US-810 v0031, US-683 v0032, then this story's v0033."""
        assert m0033.MIGRATION.version == "0033"
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions.index("0033") == versions.index("0032") + 1

    def test_freshServer_createsTheTable_once(self) -> None:
        runner = _runner([False, True])

        m0033.apply(_ctx(runner))

        assert runner.creates == [m0033.CREATE_TABLE_DDL]

    def test_reRun_onAnExistingTable_issuesNoCreate(self) -> None:
        runner = _runner([True])

        m0033.apply(_ctx(runner))

        assert runner.creates == []

    def test_aCreateThatFails_raises(self) -> None:
        with pytest.raises(asm.MigrationError, match=DRAIN_VCELL_TRAJECTORY_TABLE):
            m0033.apply(_ctx(_runner([False], createFails=True)))

    def test_aCreateThatLeavesNoTable_raises(self) -> None:
        with pytest.raises(asm.SchemaProbeError, match=DRAIN_VCELL_TRAJECTORY_TABLE):
            m0033.apply(_ctx(_runner([False, False])))

    def test_ddlCarriesTheColumnsAndTheTypedReason(self) -> None:
        ddl = m0033.CREATE_TABLE_DDL
        for column in ("ts_utc", "ts_capture", "seq", "vcell_v",
                       "termination_reason", "cell_epoch"):
            assert column in ddl
        assert "UNIQUE KEY" in ddl and "source_device, source_id" in ddl
        for value in DRAIN_TERMINATION_VALUES:
            assert f"'{value}'" in ddl


def _row(sourceId: int, seq: int, vcell: float | None, reason: str | None) -> dict[str, Any]:
    return {
        "id": sourceId,
        "ts_utc": f"2026-09-25T18:50:0{seq}Z",
        "ts_capture": 1000.0 + seq,
        "seq": seq,
        "vcell_v": vcell,
        "termination_reason": reason,
        "cell_epoch": "2000mah-pouch",
    }


class TestSyncRoundTrip:
    def test_aDrainsRowsLand_withNULLReadsAndOneTerminalRow(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        rows = [
            _row(11, 0, 3.95, None),
            _row(12, 1, None, None),
            _row(13, 2, 3.60, "drain_floor"),
        ]
        with Session(engine) as session:
            runSyncUpsert(
                session, deviceId="chi-eclipse-01", batchId="b1",
                tables={DRAIN_VCELL_TRAJECTORY_TABLE: {"rows": rows}}, syncHistoryId=1,
            )
            stored = session.execute(
                select(DrainVcellTrajectory).order_by(DrainVcellTrajectory.source_id)
            ).scalars().all()

        assert [(r.source_id, r.seq, r.vcell_v, r.termination_reason) for r in stored] == [
            (11, 0, 3.95, None), (12, 1, None, None), (13, 2, 3.60, "drain_floor"),
        ]
        assert {r.cell_epoch for r in stored} == {"2000mah-pouch"}
