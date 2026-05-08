################################################################################
# File Name: test_dtc_logger_drive_lifecycle.py
# Purpose/Description: Tests for the US-292 drive-lifecycle gap closures on
#                      DtcLogger -- 30s during-drive Mode 03 cadence and
#                      drive_end Mode 07 trigger (Spool 2026-05-06 ask).
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-07    | Rex (US-292) | Initial -- Spool gap closure: maybePeriodicMode03
#               |              | + logDriveEndDtcs.  Pre-existing US-204 ship
#               |              | covers session-start + MIL-edge; this file owns
#               |              | the new during-drive 30s cadence + drive-end
#               |              | Mode 07 paths.
# ================================================================================
################################################################################

"""Drive-lifecycle DTC tests for :mod:`src.pi.obdii.dtc_logger` (US-292).

Discriminator tests: every test in this file is designed to FAIL pre-fix --
either the method does not exist (AttributeError) or the cadence/trigger
behavior is missing.  Per Sprint 26 sprint.json US-292 acceptance criterion 3
("Synthetic test asserts new triggers fire correctly + footer renders code;
would FAIL pre-fix").
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive_id import setCurrentDriveId
from src.pi.obdii.dtc_client import DtcClient
from src.pi.obdii.dtc_log_schema import DTC_LOG_TABLE
from src.pi.obdii.dtc_logger import DtcLogger

# ================================================================================
# Fakes (mirrors test_dtc_logger.py shape so the discriminator stays narrow)
# ================================================================================


class _FakeResponse:
    def __init__(self, value: Any, null: bool = False) -> None:
        self.value = value
        self._null = null

    def is_null(self) -> bool:
        return self._null


class _FakeConnection:
    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        connected: bool = True,
    ) -> None:
        self._responses = responses or {}
        self._connected = connected
        self.queryCalls: list[str] = []
        self.obd = SimpleNamespace(query=self._query)

    def _query(self, cmd: Any) -> Any:
        name = cmd if isinstance(cmd, str) else getattr(cmd, "name", str(cmd))
        self.queryCalls.append(name)
        return self._responses.get(name) or _FakeResponse(value=None, null=True)

    def isConnected(self) -> bool:
        return self._connected


def _factory(name: str) -> str:
    return name


# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "test_dtc_logger_drive_lifecycle.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture(autouse=True)
def clearDriveContext() -> Any:
    setCurrentDriveId(None)
    yield
    setCurrentDriveId(None)


def _client(
    *,
    stored: list[tuple[str, str | None]] | None = None,
    pending: list[tuple[str, str | None]] | None = None,
    mode07Supported: bool = True,
) -> tuple[DtcClient, _FakeConnection]:
    responses: dict[str, Any] = {}
    if stored is not None:
        responses["GET_DTC"] = _FakeResponse(value=stored)
    if mode07Supported and pending is not None:
        responses["GET_CURRENT_DTC"] = _FakeResponse(value=pending)
    conn = _FakeConnection(responses=responses)
    client = DtcClient(commandFactory=_factory)
    return client, conn


def _readDtcRows(db: ObdDatabase) -> list[dict[str, Any]]:
    with db.connect() as conn:
        cursor = conn.execute(
            f"SELECT id, dtc_code, description, status, drive_id, "
            f"data_source, first_seen_timestamp, last_seen_timestamp "
            f"FROM {DTC_LOG_TABLE} ORDER BY id"
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row, strict=True)) for row in cursor.fetchall()]


# ================================================================================
# maybePeriodicMode03 -- 30s during-drive cadence (Spool gap #1)
# ================================================================================


class TestMaybePeriodicMode03:
    """Spool 2026-05-06: 'Mode 03 query at drive_start + every 30s during drive'.

    US-204 (Sprint 15) shipped the drive_start half via
    :meth:`logSessionStartDtcs`.  US-292 closes the during-drive cadence:
    a polling helper that is cheap to call every reading tick, fires the
    Mode 03 upsert when ``intervalSeconds`` has elapsed since the last
    successful poll, and resets cleanly across drive boundaries.
    """

    def test_firstCallAfterDriveStartFiresMode03(
        self, freshDb: ObdDatabase,
    ) -> None:
        """Cadence cold-start: no prior poll => first call fires."""
        client, conn = _client(stored=[("P0420", "cat")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)
        now = datetime(2026, 5, 9, 14, 0, 0)

        result = dtcLogger.maybePeriodicMode03(
            driveId=42, connection=conn, now=now, intervalSeconds=30.0,
        )

        assert "GET_DTC" in conn.queryCalls
        assert result.inserted == 1

    def test_secondCallWithinIntervalIsNoOp(
        self, freshDb: ObdDatabase,
    ) -> None:
        """Within the 30s window => no Mode 03 query fires; counts zero."""
        client, conn = _client(stored=[("P0420", "cat")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)
        t0 = datetime(2026, 5, 9, 14, 0, 0)
        dtcLogger.maybePeriodicMode03(
            driveId=42, connection=conn, now=t0, intervalSeconds=30.0,
        )
        callsAfterFirst = len(conn.queryCalls)

        result = dtcLogger.maybePeriodicMode03(
            driveId=42,
            connection=conn,
            now=t0 + timedelta(seconds=29.9),
            intervalSeconds=30.0,
        )

        assert len(conn.queryCalls) == callsAfterFirst, "skip: must not query"
        assert result.inserted == 0
        assert result.updated == 0

    def test_secondCallAfterIntervalFires(
        self, freshDb: ObdDatabase,
    ) -> None:
        """At/past the 30s mark => Mode 03 fires again; same code bumps last_seen."""
        client, conn = _client(stored=[("P0420", "cat")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)
        t0 = datetime(2026, 5, 9, 14, 0, 0)
        dtcLogger.maybePeriodicMode03(
            driveId=42, connection=conn, now=t0, intervalSeconds=30.0,
        )
        callsAfterFirst = len(conn.queryCalls)

        result = dtcLogger.maybePeriodicMode03(
            driveId=42,
            connection=conn,
            now=t0 + timedelta(seconds=30.0),
            intervalSeconds=30.0,
        )

        assert len(conn.queryCalls) == callsAfterFirst + 1
        # Same code in same drive: upsert bumps last_seen, does not insert.
        assert result.inserted == 0
        assert result.updated == 1

    def test_newDriveIdResetsCadenceState(
        self, freshDb: ObdDatabase,
    ) -> None:
        """A new drive_id mid-poll resets the timer (drive boundary)."""
        client, conn = _client(stored=[("P0420", "cat")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)
        t0 = datetime(2026, 5, 9, 14, 0, 0)
        dtcLogger.maybePeriodicMode03(
            driveId=42, connection=conn, now=t0, intervalSeconds=30.0,
        )
        callsAfterFirstDrive = len(conn.queryCalls)

        # New drive 5s later -- under the 30s window of drive 42 -- should
        # still fire because drive boundary resets the cadence state.
        result = dtcLogger.maybePeriodicMode03(
            driveId=43,
            connection=conn,
            now=t0 + timedelta(seconds=5.0),
            intervalSeconds=30.0,
        )

        assert len(conn.queryCalls) == callsAfterFirstDrive + 1
        rows = _readDtcRows(freshDb)
        assert any(r['drive_id'] == 43 for r in rows)
        # Same code, fresh drive => INSERT (per US-204 invariant).
        assert result.inserted == 1

    def test_skipsWhenDriveIdNone(
        self, freshDb: ObdDatabase,
    ) -> None:
        """No active drive => skip (cadence is during-drive only)."""
        client, conn = _client(stored=[("P0420", "cat")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        result = dtcLogger.maybePeriodicMode03(
            driveId=None,
            connection=conn,
            now=datetime(2026, 5, 9, 14, 0, 0),
            intervalSeconds=30.0,
        )

        assert "GET_DTC" not in conn.queryCalls
        assert result.inserted == 0
        assert result.updated == 0

    def test_returnsMilEventResultShape(
        self, freshDb: ObdDatabase,
    ) -> None:
        """Per-poll counts come back as MilEventResult so callers can log them."""
        client, conn = _client(stored=[])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        result = dtcLogger.maybePeriodicMode03(
            driveId=1,
            connection=conn,
            now=datetime(2026, 5, 9, 14, 0, 0),
            intervalSeconds=30.0,
        )

        assert hasattr(result, 'inserted')
        assert hasattr(result, 'updated')


# ================================================================================
# logDriveEndDtcs -- Mode 07 trigger at drive_end (Spool gap #2)
# ================================================================================


class TestLogDriveEndDtcs:
    """Spool 2026-05-06: 'Mode 07 query at drive_end (pending codes are the
    leading indicator -- they fire before MIL)'.

    US-204 (Sprint 15) shipped Mode 07 at session-start via the probe-first
    pattern.  US-292 adds the drive-end trigger so the next drive's
    leading-indicator catch is comprehensive: any pending code that
    appeared during the drive lands in dtc_log before the drive closes.
    """

    def test_pendingCodesPersisted(self, freshDb: ObdDatabase) -> None:
        client, conn = _client(stored=[], pending=[("P0420", "cat")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        result = dtcLogger.logDriveEndDtcs(driveId=7, connection=conn)

        rows = _readDtcRows(freshDb)
        assert [r['dtc_code'] for r in rows] == ["P0420"]
        assert result.pendingCount == 1
        assert result.mode07Probe.supported is True

    def test_pendingCodesCarryDriveIdAndPendingStatus(
        self, freshDb: ObdDatabase,
    ) -> None:
        client, conn = _client(stored=[], pending=[("P0301", "misfire cyl 1")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        dtcLogger.logDriveEndDtcs(driveId=11, connection=conn)

        rows = _readDtcRows(freshDb)
        assert rows[0]['drive_id'] == 11
        assert rows[0]['status'] == 'pending'

    def test_mode07UnsupportedYieldsZeroAndCachedProbe(
        self, freshDb: ObdDatabase,
    ) -> None:
        """2G ECU path: Mode 07 returns null -> probe records unsupported."""
        client, conn = _client(stored=[], mode07Supported=False)
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        result = dtcLogger.logDriveEndDtcs(driveId=3, connection=conn)

        assert _readDtcRows(freshDb) == []
        assert result.pendingCount == 0
        assert result.mode07Probe.supported is False

    def test_doesNotQueryMode03(self, freshDb: ObdDatabase) -> None:
        """Drive-end is Mode 07 only -- Mode 03 was already polled mid-drive."""
        client, conn = _client(stored=[("P0420", "cat")], pending=[])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        dtcLogger.logDriveEndDtcs(driveId=2, connection=conn)

        assert "GET_CURRENT_DTC" in conn.queryCalls
        assert "GET_DTC" not in conn.queryCalls
