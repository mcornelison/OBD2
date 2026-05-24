################################################################################
# File Name: test_sync_history_timestamps_utc.py
# Purpose/Description: Regression tests for B-079 / US-333 — sync_history rows must
#                      record started_at and completed_at on the SAME UTC clock so
#                      (completed_at - started_at) is a real sync duration, not the
#                      ~18000s artifact of one column being DB-server-local time.
# Author: Ralph Agent
# Creation Date: 2026-05-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-12    | Ralph (US-333) | B-079: started_at was filled by the model's
#               |                | server_default=func.now() (MariaDB local time)
#               |                | while completed_at was datetime.now(UTC) — 5h
#               |                | apart in the same row.  Tests pin the writer to
#               |                | a single UTC clock for both columns.
# ================================================================================
################################################################################

"""Tests for the ``sync_history`` timestamp writers in ``src/server/api/sync.py``.

B-079: every recent ``sync_history`` row had ``completed_at - started_at ==
18000s`` (= the America/Chicago CDT offset) because ``started_at`` was filled by
the MariaDB column ``server_default`` (``NOW()`` — the DB server's *local* clock)
while ``completed_at`` was written by Python as ``datetime.now(UTC)``.  The fix
has :func:`_createSyncHistoryRow` set ``started_at`` explicitly from the same
UTC clock, so both columns agree and the duration metric is meaningful.

The tests freeze ``src.server.api.sync.datetime`` and assert ``started_at``
reflects that frozen clock.  Pre-fix, ``started_at`` is filled by the database's
``CURRENT_TIMESTAMP`` instead, so the assertions fail.  These tests run against a
local aiosqlite file (no MariaDB needed) and skip cleanly when aiosqlite is
absent.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from sqlalchemy import create_engine, select  # noqa: E402

from src.server.api import sync as sync_module  # noqa: E402
from src.server.api.sync import (  # noqa: E402
    _completeSyncHistoryRow,
    _createSyncHistoryRow,
)
from src.server.db.models import Base, SyncHistory  # noqa: E402

try:
    import aiosqlite as _aiosqlite  # noqa: F401

    _HAS_AIOSQLITE = True
except ImportError:  # pragma: no cover — env without aiosqlite
    _HAS_AIOSQLITE = False

_skipNoAsyncDb = pytest.mark.skipif(
    not _HAS_AIOSQLITE,
    reason="aiosqlite not installed — skipping async DB sync_history tests",
)


class _FrozenClock:
    """Stand-in for ``src.server.api.sync.datetime`` with canned ``now()`` values.

    Constructed with one or more moments; each ``now(tz)`` call returns the next
    one (the last is repeated once exhausted).  The ``tz`` argument is accepted
    and ignored — callers always pass canonical UTC moments.
    """

    def __init__(self, *moments: datetime) -> None:
        if not moments:
            raise ValueError("_FrozenClock needs at least one moment")
        self._moments = list(moments)

    def now(self, tz: object | None = None) -> datetime:  # noqa: ARG002 — mirrors datetime.now
        if len(self._moments) == 1:
            return self._moments[0]
        return self._moments.pop(0)


def _freshAsyncEngine() -> tuple[object, str]:
    """Create an aiosqlite AsyncEngine over a temp file with the server schema."""
    from sqlalchemy.ext.asyncio import create_async_engine

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    syncEng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(syncEng)
    syncEng.dispose()
    return create_async_engine(f"sqlite+aiosqlite:///{tmp.name}"), tmp.name


async def _readSyncHistoryRow(engine: object, historyId: int) -> SyncHistory:
    """Fetch a single sync_history row by id."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(engine) as session:  # type: ignore[arg-type]
        result = await session.execute(
            select(SyncHistory).where(SyncHistory.id == historyId),
        )
        return result.scalar_one()


@_skipNoAsyncDb
@pytest.mark.asyncio
async def test_createSyncHistoryRow_writesStartedAtFromUtcClock(monkeypatch):
    """started_at comes from the module's UTC clock, not the DB server_default.

    Given: the sync module's clock is frozen to a sentinel UTC moment.
    When:  a sync_history row is created.
    Then:  its started_at equals the frozen moment (naive-UTC).

    Pre-fix this fails — started_at is left to the column's ``server_default``
    (``NOW()`` / ``CURRENT_TIMESTAMP``), so it reflects the real wall clock, not
    the sentinel.
    """
    engine, path = _freshAsyncEngine()
    try:
        frozen = datetime(2031, 6, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(sync_module, "datetime", _FrozenClock(frozen))

        historyId = await _createSyncHistoryRow(engine, "chi-eclipse-01")
        row = await _readSyncHistoryRow(engine, historyId)

        assert row.started_at == frozen.replace(tzinfo=None)
    finally:
        await engine.dispose()  # type: ignore[attr-defined]
        Path(path).unlink(missing_ok=True)


@_skipNoAsyncDb
@pytest.mark.asyncio
async def test_syncHistoryDuration_isSecondsNotTimezoneOffset(monkeypatch):
    """completed_at - started_at is a real (seconds-scale) duration.

    Given: started_at and completed_at are written 3 seconds apart on the same
           UTC clock.
    When:  the sync_history row is created then completed.
    Then:  the recorded duration is exactly 3 seconds — well under a minute, not
           the ~18000s (5h CDT/UTC) artifact B-079 reported.

    Pre-fix this fails — started_at is the DB ``CURRENT_TIMESTAMP`` while
    completed_at is the Python-supplied UTC moment, so the diff is years, not
    seconds.
    """
    engine, path = _freshAsyncEngine()
    try:
        started = datetime(2031, 6, 1, 12, 0, 0, tzinfo=UTC)
        completed = datetime(2031, 6, 1, 12, 0, 3, tzinfo=UTC)
        monkeypatch.setattr(sync_module, "datetime", _FrozenClock(started))

        historyId = await _createSyncHistoryRow(engine, "chi-eclipse-01")
        await _completeSyncHistoryRow(
            engine,
            historyId,
            {"realtime_data": {"inserted": 1, "updated": 0, "errors": 0}},
            completed.replace(tzinfo=None),
        )
        row = await _readSyncHistoryRow(engine, historyId)

        assert row.started_at is not None
        assert row.completed_at is not None
        delta = row.completed_at - row.started_at
        assert timedelta(0) <= delta < timedelta(seconds=60), (
            f"sync duration {delta} — expected a seconds-scale value, not the "
            "~18000s CDT/UTC artifact"
        )
        assert delta == timedelta(seconds=3)
    finally:
        await engine.dispose()  # type: ignore[attr-defined]
        Path(path).unlink(missing_ok=True)
