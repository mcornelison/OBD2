################################################################################
# File Name: test_prune_sync_history_cli.py
# Purpose/Description: US-418 (F-078) -- recurring sync_history retention.
#   v0007 pruned once at migration time and said "future ongoing pruning is a
#   separate concern". Nothing ever did it: 88,810 rows sat past the 90-day
#   horizon on 2026-10-07 (87,339 on 10-04). The prune now runs inside the
#   nightly analytics batch (CIO 2026-10-08) and must say what it did on EVERY
#   run, because that batch exits 0 on failure (US-840) and its unit status
#   can never be the evidence.
# Author: Atlas (Architect)
# Creation Date: 2026-10-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-08    | Atlas (US-418)| Initial.
# ================================================================================
################################################################################

"""US-418 tests for the sync_history retention prune."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.server.cli import prune_sync_history
from src.server.cli.prune_sync_history import pruneSyncHistory
from src.server.db.models import Base, SyncHistory
from src.server.migrations.versions.v0007_sync_history_retention import (
    RETENTION_DAYS_DEFAULT,
    RETENTION_ENV_VAR,
)

NOW = datetime(2026, 10, 8, 3, 30, 0)


def _addRow(session: Session, startedAt: datetime) -> None:
    session.add(
        SyncHistory(
            device_id="chi-eclipse-01", status="completed", rows_synced=1,
            started_at=startedAt,
        )
    )


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def test_prunesOnlyRowsOlderThanTheHorizon(session) -> None:
    cutoff = NOW - timedelta(days=90)
    for startedAt in (
        NOW - timedelta(days=200),
        cutoff - timedelta(seconds=1),   # just past the horizon -> deleted
        cutoff,                           # exactly on it -> kept (strict <)
        cutoff + timedelta(seconds=1),
        NOW - timedelta(days=1),
    ):
        _addRow(session, startedAt)
    session.commit()

    result = pruneSyncHistory(session, now=NOW, retentionDays=90)

    assert result.cutoff == cutoff
    assert result.deleted == 2
    assert result.remainingPastHorizon == 0
    kept = sorted(session.scalars(select(SyncHistory.started_at)))
    assert kept == [cutoff, cutoff + timedelta(seconds=1), NOW - timedelta(days=1)]


def test_aRunThatDeletesNothingStillReportsIt(session) -> None:
    # "Ran and deleted nothing" must never look like "never ran" (ARCH-060).
    _addRow(session, NOW - timedelta(days=3))
    session.commit()

    result = pruneSyncHistory(session, now=NOW, retentionDays=90)

    assert result.deleted == 0
    assert result.remainingPastHorizon == 0
    assert "deleted=0" in result.logLine()
    assert "horizon=90d" in result.logLine()


def test_theHorizonIsV0007s_oneSourceForTheNinetyDays() -> None:
    # One rule: the CLI reads the migration's constant and env override.
    assert prune_sync_history.resolveRetentionDays() == RETENTION_DAYS_DEFAULT == 90


def test_theEnvOverrideApplies(monkeypatch) -> None:
    monkeypatch.setenv(RETENTION_ENV_VAR, "30")
    assert prune_sync_history.resolveRetentionDays() == 30


def test_main_printsOneLineAndExitsZero(tmp_path, monkeypatch, capsys) -> None:
    url = f"sqlite:///{(tmp_path / 'srv.db').as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        _addRow(s, datetime.now() - timedelta(days=400))
        _addRow(s, datetime.now() - timedelta(days=2))
        s.commit()
    engine.dispose()
    monkeypatch.setattr(prune_sync_history, "resolveSyncDatabaseUrl", lambda: url)

    code = prune_sync_history.main([])

    out = capsys.readouterr().out.strip().splitlines()
    assert code == 0
    assert len(out) == 1, out
    assert out[0].startswith("sync_history retention:")
    assert "deleted=1" in out[0]
    assert "past_horizon_after=0" in out[0]


def test_main_aDatabaseFailureIsLoudAndNonZero(monkeypatch, capsys) -> None:
    # The unit runs this with a leading '-', so a failure cannot stop the
    # analytics recompute -- which makes THIS line the only evidence.
    def _boom():
        raise RuntimeError("no DATABASE_URL")

    monkeypatch.setattr(prune_sync_history, "resolveSyncDatabaseUrl", _boom)

    code = prune_sync_history.main([])

    err = capsys.readouterr().err
    assert code != 0
    assert "sync_history retention: FAILED" in err
