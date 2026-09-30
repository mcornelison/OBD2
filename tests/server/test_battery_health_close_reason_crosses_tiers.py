################################################################################
# File Name: test_battery_health_close_reason_crosses_tiers.py
# Purpose/Description: US-683 -- battery_health_log.close_reason exists on the
#                      server model with the Pi's vocabulary, v0032 adds it,
#                      constrains it and backfills it with the Pi's derivation,
#                      and a sync carrying it succeeds -- including the re-sync
#                      that corrects a server row whose notes never got the
#                      reap suffix.
# Author: Rex (US-683)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-24    | Rex (US-683) | Initial.
# ================================================================================
################################################################################
"""The typed close discriminator crosses the tier boundary (US-683)."""

from __future__ import annotations

import sqlite3
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scripts import apply_server_migrations as asm
from src.pi.power import battery_health as piBatteryHealth
from src.server.api.sync import runSyncUpsert
from src.server.db.models import (
    BATTERY_HEALTH_CLOSE_REASON_VALUES,
    Base,
    BatteryHealthLog,
)
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0032_us683_battery_health_close_reason as m0032

_COLS_BEFORE = (
    "id\nsource_id\nsource_device\nsynced_at\nsync_batch_id\nstart_timestamp\n"
    "end_timestamp\nstart_vcell_v\nend_vcell_v\nstart_soc_pct\nend_soc_pct\n"
    "runtime_seconds\nambient_temp_c\nload_class\nnotes\ndata_source\n"
)
_COLS_AFTER = _COLS_BEFORE + "close_reason\n"


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

    @property
    def updates(self) -> list[str]:
        return [sql for sql in self.calls if sql.lstrip().startswith("UPDATE")]


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
    columnSets: list[str], *, checkExists: bool = False, tableExists: bool = True,
) -> FakeRunner:
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
    runner.handlers.append(
        ("information_schema.CHECK_CONSTRAINTS",
         lambda _sql: _ok("1\n" if checkExists else "0\n"))
    )
    runner.handlers.append(("information_schema.COLUMNS", columns))
    return runner


# ================================================================================
# Model and vocabulary
# ================================================================================


class TestServerModel:
    def test_modelDeclaresCloseReason_nullable(self) -> None:
        column = BatteryHealthLog.__table__.columns["close_reason"]
        assert column.nullable

    def test_vocabularyMatchesThePi(self) -> None:
        assert BATTERY_HEALTH_CLOSE_REASON_VALUES == piBatteryHealth.CLOSE_REASON_VALUES

    def test_modelCheckRejectsAValueOutsideTheVocabulary(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(BatteryHealthLog(
                source_id=1, source_device="d", load_class="production",
                close_reason="interrupted",
            ))
            with pytest.raises(IntegrityError):
                session.commit()


# ================================================================================
# Migration v0032
# ================================================================================


class TestMigrationV0032:
    def test_isRegisteredDirectlyAfterV0031(self) -> None:
        """Chain order: US-810 v0031, then US-683 v0032, then US-790 v0033."""
        assert m0032.MIGRATION.version == "0032"
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions.index("0032") == versions.index("0031") + 1

    def test_liveServer_addsColumn_thenCheck_thenBackfills(self) -> None:
        runner = _runner([_COLS_BEFORE, _COLS_AFTER])

        m0032.apply(_ctx(runner))

        assert runner.alters == [m0032.ADD_COLUMN_DDL, m0032.ADD_CHECK_DDL]
        assert runner.updates == [m0032.BACKFILL_SQL]

    def test_reRun_addsNothing_andTheBackfillIsSelfLimiting(self) -> None:
        runner = _runner([_COLS_AFTER], checkExists=True)

        m0032.apply(_ctx(runner))

        assert runner.alters == []
        assert "close_reason IS NULL" in m0032.BACKFILL_SQL
        assert "end_timestamp IS NOT NULL" in m0032.BACKFILL_SQL

    def test_missingTable_raises(self) -> None:
        with pytest.raises(asm.MigrationError, match="battery_health_log"):
            m0032.apply(_ctx(_runner([_COLS_BEFORE], tableExists=False)))

    def test_anAddThatLeavesTheColumnAbsent_raises(self) -> None:
        with pytest.raises(asm.SchemaProbeError, match="still lacks"):
            m0032.apply(_ctx(_runner([_COLS_BEFORE, _COLS_BEFORE])))

    @pytest.mark.parametrize("needle", ["ADD COLUMN", "ADD CONSTRAINT", "UPDATE "])
    def test_aFailingStep_raises(self, needle: str) -> None:
        runner = _runner([_COLS_BEFORE, _COLS_AFTER])
        runner.handlers.insert(0, (needle, _fail))
        with pytest.raises(asm.MigrationError, match="close_reason|CHECK"):
            m0032.apply(_ctx(runner))

    def test_suffixIsThePiConstant(self) -> None:
        assert m0032.REAP_CHECKPOINTED_NOTE_SUFFIX == (
            piBatteryHealth.REAP_CHECKPOINTED_NOTE_SUFFIX
        )
        assert "'" not in m0032.REAP_CHECKPOINTED_NOTE_SUFFIX

    def test_revertDropsExactlyTheColumnAndItsCheck(self) -> None:
        assert "DROP COLUMN close_reason" in m0032.REVERT_DDL
        assert f"DROP CONSTRAINT {m0032.CHECK_CONSTRAINT_NAME}" in m0032.REVERT_DDL


# ================================================================================
# The backfill statement itself, run against rows
# ================================================================================

#: (source_id, end_timestamp, end_vcell_v, runtime_seconds, notes)
_ROWS: tuple[tuple[int, str | None, float | None, int | None, str | None], ...] = (
    (1, None, None, None, "US-442 orphan"),
    (2, "2026-05-09 12:12:07", 3.41, 727, "drill"),
    (4, "2026-08-05 12:01:40", None, 100, None),
    (5, "2026-08-06 12:00:00", None, None, None),
    (6, "2026-09-01 12:10:00", 3.48, 600,
     "opened" + piBatteryHealth.REAP_CHECKPOINTED_NOTE_SUFFIX),
    (9, None, None, None, None),
    (18, None, None, None, None),
    (21, None, None, None, None),
)
_EXPECTED = {
    1: None, 9: None, 18: None, 21: None,
    2: "clean", 4: "clean",
    5: "reaped_uncheckpointed",
    6: "reaped_checkpointed",
}


class TestTheBackfillStatement:
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE battery_health_log (source_id INTEGER, end_timestamp TEXT, "
            "end_vcell_v REAL, runtime_seconds INTEGER, notes TEXT, close_reason TEXT)"
        )
        conn.executemany(
            "INSERT INTO battery_health_log (source_id, end_timestamp, end_vcell_v, "
            "runtime_seconds, notes) VALUES (?, ?, ?, ?, ?)",
            _ROWS,
        )
        return conn

    def test_classifiesLikeThePi_andLeavesOpenRowsAlone(self) -> None:
        conn = self._conn()

        conn.execute(m0032.BACKFILL_SQL)

        assert dict(conn.execute(
            "SELECT source_id, close_reason FROM battery_health_log"
        ).fetchall()) == _EXPECTED

    def test_sameRowsGiveTheSameAnswerAsThePiStatement(self) -> None:
        server = self._conn()
        server.execute(m0032.BACKFILL_SQL)
        pi = self._conn()
        pi.execute(
            piBatteryHealth._BACKFILL_CLOSE_REASON_SQL,  # noqa: SLF001
            (piBatteryHealth.REAP_CHECKPOINTED_NOTE_SUFFIX,),
        )
        query = "SELECT source_id, close_reason FROM battery_health_log ORDER BY 1"
        assert server.execute(query).fetchall() == pi.execute(query).fetchall()

    def test_aSecondRun_changesNothing(self) -> None:
        conn = self._conn()
        conn.execute(m0032.BACKFILL_SQL)

        cursor = conn.execute(m0032.BACKFILL_SQL)

        assert cursor.rowcount == 0


# ================================================================================
# Sync
# ================================================================================


def _bhRow(sourceId: int, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": sourceId,
        "start_timestamp": "2026-09-01T12:00:00Z",
        "end_timestamp": "2026-09-01T12:10:00Z",
        "end_vcell_v": 3.48,
        "runtime_seconds": 600,
        "load_class": "production",
        "data_source": "real",
    }
    row.update(extra)
    return row


class TestSyncRoundTrip:
    def _session(self) -> Session:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return Session(engine)

    def _push(self, session: Session, row: dict[str, Any], batch: str) -> None:
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId=batch,
            tables={"battery_health_log": {"rows": [row]}}, syncHistoryId=1,
        )

    def test_openRowSyncsNULL_andTheCloseCarriesTheReason(self) -> None:
        session = self._session()
        self._push(session, _bhRow(
            7, end_timestamp=None, end_vcell_v=None, runtime_seconds=None,
            close_reason=None,
        ), "b1")
        assert session.execute(select(BatteryHealthLog)).scalar_one().close_reason is None

        self._push(session, _bhRow(7, close_reason="clean"), "b2")

        assert session.execute(select(BatteryHealthLog)).scalar_one().close_reason == "clean"

    def test_reSync_correctsTheReason_whileNotesStayPreserved(self) -> None:
        """
        Given: a server row first received OPEN, so its notes lack the reap suffix
        When:  the Pi's backfilled row re-syncs with close_reason and new notes
        Then:  close_reason updates (the typed value arrives) -- notes do not
        """
        session = self._session()
        self._push(session, _bhRow(8, notes="opened", close_reason="clean"), "b1")

        self._push(session, _bhRow(
            8, notes="opened" + piBatteryHealth.REAP_CHECKPOINTED_NOTE_SUFFIX,
            close_reason="reaped_checkpointed",
        ), "b2")

        row = session.execute(select(BatteryHealthLog)).scalar_one()
        assert row.close_reason == "reaped_checkpointed"
        assert row.notes == "opened"
