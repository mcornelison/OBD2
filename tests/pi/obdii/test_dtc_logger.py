################################################################################
# File Name: test_dtc_logger.py
# Purpose/Description: Integration tests for DtcLogger -- the orchestration
#                      layer that combines DtcClient, drive_id context, and
#                      dtc_log database writes (US-204).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-204) | Initial -- DtcLogger session-start + MIL-event.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.obdii.dtc_logger`."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive_id import setCurrentDriveId
from src.pi.obdii.dtc_client import (
    DtcClient,
    Mode07ProbeResult,
)
from src.pi.obdii.dtc_log_schema import DTC_LOG_TABLE
from src.pi.obdii.dtc_logger import DtcLogger

# ================================================================================
# Fakes
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
        self.obd = SimpleNamespace(query=self._query)

    def _query(self, cmd: Any) -> Any:
        name = cmd if isinstance(cmd, str) else getattr(cmd, "name", str(cmd))
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
    db = ObdDatabase(str(tmp_path / "test_dtc_logger.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture(autouse=True)
def clearDriveContext() -> Any:
    """Make sure no stale drive_id leaks across tests."""
    setCurrentDriveId(None)
    yield
    setCurrentDriveId(None)


def _client(*, stored: list[tuple[str, str | None]] | None = None,
            pending: list[tuple[str, str | None]] | None = None,
            mode07Supported: bool = True) -> tuple[DtcClient, _FakeConnection]:
    """Build a DtcClient + matching FakeConnection in one step."""
    responses: dict[str, Any] = {}
    if stored is not None:
        responses["GET_DTC"] = _FakeResponse(value=stored)
    if mode07Supported and pending is not None:
        responses["GET_CURRENT_DTC"] = _FakeResponse(value=pending)
    # If mode07Supported is False, omit the Mode 07 response so the
    # FakeConnection returns null (-> probe flagged unsupported).
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
# logSessionStartDtcs
# ================================================================================


class TestLogSessionStartDtcs:

    def test_storedAndPendingBothLogged(self, freshDb: ObdDatabase) -> None:
        client, conn = _client(
            stored=[("P0171", "System Too Lean (Bank 1)")],
            pending=[("P0420", "Cat Efficiency")],
        )
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        result = dtcLogger.logSessionStartDtcs(driveId=42, connection=conn)

        rows = _readDtcRows(freshDb)
        assert {r['dtc_code'] for r in rows} == {"P0171", "P0420"}
        assert result.storedCount == 1
        assert result.pendingCount == 1
        assert result.mode07Probe.supported is True

    def test_eachRowCarriesDriveId(self, freshDb: ObdDatabase) -> None:
        client, conn = _client(
            stored=[("P0171", "lean"), ("P0301", "misfire cyl 1")],
            pending=[],
        )
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        dtcLogger.logSessionStartDtcs(driveId=7, connection=conn)

        rows = _readDtcRows(freshDb)
        assert all(r['drive_id'] == 7 for r in rows)

    def test_dataSourceDefaultsToReal(self, freshDb: ObdDatabase) -> None:
        client, conn = _client(stored=[("P0171", "lean")], pending=[])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        dtcLogger.logSessionStartDtcs(driveId=1, connection=conn)

        rows = _readDtcRows(freshDb)
        assert rows[0]['data_source'] == 'real'

    def test_mode07UnsupportedSkipsPendingButLogsStored(
        self, freshDb: ObdDatabase,
    ) -> None:
        """2G ECU path: Mode 03 succeeds, Mode 07 returns null."""
        client, conn = _client(
            stored=[("P0420", "Cat Efficiency")],
            mode07Supported=False,
        )
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        result = dtcLogger.logSessionStartDtcs(driveId=3, connection=conn)

        rows = _readDtcRows(freshDb)
        assert [r['dtc_code'] for r in rows] == ["P0420"]
        assert result.storedCount == 1
        assert result.pendingCount == 0
        assert result.mode07Probe.supported is False

    def test_noStoredCodesNoRows(self, freshDb: ObdDatabase) -> None:
        """Healthy ECU: no codes -> no rows -> still returns probe info."""
        client, conn = _client(stored=[], pending=[])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        result = dtcLogger.logSessionStartDtcs(driveId=99, connection=conn)

        assert _readDtcRows(freshDb) == []
        assert result.storedCount == 0
        assert result.pendingCount == 0

    def test_pendingCodeStatusIsPending(self, freshDb: ObdDatabase) -> None:
        client, conn = _client(stored=[], pending=[("P0300", "misfire")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        dtcLogger.logSessionStartDtcs(driveId=5, connection=conn)

        rows = _readDtcRows(freshDb)
        assert rows[0]['status'] == 'pending'

    def test_storedCodeStatusIsStored(self, freshDb: ObdDatabase) -> None:
        client, conn = _client(stored=[("P0420", "cat")], pending=[])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        dtcLogger.logSessionStartDtcs(driveId=8, connection=conn)

        rows = _readDtcRows(freshDb)
        assert rows[0]['status'] == 'stored'

    def test_unknownDescriptionIsEmptyString(self, freshDb: ObdDatabase) -> None:
        """Invariant #6: never fabricate descriptions for unknown codes."""
        client, conn = _client(stored=[("P1234", None)], pending=[])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        dtcLogger.logSessionStartDtcs(driveId=1, connection=conn)

        rows = _readDtcRows(freshDb)
        assert rows[0]['description'] == ''


# ================================================================================
# logMilEventDtcs
# ================================================================================


class TestLogMilEventDtcs:
    """MIL rising edge mid-drive triggers a Mode 03 re-fetch with upsert."""

    def test_newCodeInsertsNewRow(self, freshDb: ObdDatabase) -> None:
        client, conn = _client(stored=[("P0420", "cat")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        dtcLogger.logMilEventDtcs(driveId=11, connection=conn)

        rows = _readDtcRows(freshDb)
        assert [r['dtc_code'] for r in rows] == ["P0420"]
        assert rows[0]['status'] == 'stored'
        assert rows[0]['drive_id'] == 11

    def test_duplicateInSameDriveBumpsLastSeen(
        self, freshDb: ObdDatabase,
    ) -> None:
        client, conn = _client(stored=[("P0171", "lean")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        # First MIL event: inserts the row.
        dtcLogger.logMilEventDtcs(driveId=4, connection=conn)
        firstRows = _readDtcRows(freshDb)
        firstId = firstRows[0]['id']
        firstLastSeen = firstRows[0]['last_seen_timestamp']

        # Second MIL event in the SAME drive with the SAME code: must
        # NOT insert a new row.  (We bump the last_seen via UPDATE.)
        dtcLogger.logMilEventDtcs(driveId=4, connection=conn)
        secondRows = _readDtcRows(freshDb)

        assert len(secondRows) == 1
        assert secondRows[0]['id'] == firstId  # UPDATE, not INSERT
        # last_seen may equal firstLastSeen if both calls land in the same
        # second; the contract is "no new row", not "strictly later ts".
        assert secondRows[0]['last_seen_timestamp'] >= firstLastSeen

    def test_sameCodeNewDriveInsertsNewRow(
        self, freshDb: ObdDatabase,
    ) -> None:
        """Different drive_id with same code -> new row (per spec)."""
        client, conn = _client(stored=[("P0420", "cat")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        dtcLogger.logMilEventDtcs(driveId=10, connection=conn)
        dtcLogger.logMilEventDtcs(driveId=11, connection=conn)

        rows = _readDtcRows(freshDb)
        assert {r['drive_id'] for r in rows} == {10, 11}
        assert len(rows) == 2

    def test_returnsCountSummary(self, freshDb: ObdDatabase) -> None:
        client, conn = _client(stored=[("P0420", "cat"), ("P0301", "misfire")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        result = dtcLogger.logMilEventDtcs(driveId=1, connection=conn)

        assert result.inserted == 2
        assert result.updated == 0

        # Re-run inserts 0, updates 2.
        again = dtcLogger.logMilEventDtcs(driveId=1, connection=conn)
        assert again.inserted == 0
        assert again.updated == 2

    def test_noCodesNoRows(self, freshDb: ObdDatabase) -> None:
        """Mode 03 returns empty list -> no rows touched."""
        client, conn = _client(stored=[])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        result = dtcLogger.logMilEventDtcs(driveId=1, connection=conn)

        assert result.inserted == 0
        assert result.updated == 0
        assert _readDtcRows(freshDb) == []


# ================================================================================
# Drive context fallback
# ================================================================================


class TestDriveContextFallback:
    """When the orchestrator dispatches MIL events it may not know
    driveId locally -- DtcLogger pulls from setCurrentDriveId() instead.
    """

    def test_fallsBackToCurrentDriveId(self, freshDb: ObdDatabase) -> None:
        client, conn = _client(stored=[("P0171", "lean")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        setCurrentDriveId(77)
        dtcLogger.logMilEventDtcs(driveId=None, connection=conn)

        rows = _readDtcRows(freshDb)
        assert rows[0]['drive_id'] == 77

    def test_noDriveContextLeavesDriveIdNull(self, freshDb: ObdDatabase) -> None:
        """If no drive is active, the row is still written with NULL drive_id."""
        client, conn = _client(stored=[("P0171", "lean")])
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        # No setCurrentDriveId, no explicit driveId.
        dtcLogger.logMilEventDtcs(driveId=None, connection=conn)

        rows = _readDtcRows(freshDb)
        assert rows[0]['drive_id'] is None


# ================================================================================
# Disconnected connection
# ================================================================================


class TestDisconnectedConnection:
    """A disconnected connection at logger-call time fails fast and
    leaves the dtc_log untouched."""

    def test_sessionStartRaisesOnDisconnect(self, freshDb: ObdDatabase) -> None:
        client = DtcClient(commandFactory=_factory)
        conn = _FakeConnection(connected=False)
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        with pytest.raises(RuntimeError):
            dtcLogger.logSessionStartDtcs(driveId=1, connection=conn)
        assert _readDtcRows(freshDb) == []


# ================================================================================
# Mode 07 probe injection seam
# ================================================================================


class TestMode07ProbeReturned:
    """Caller (DriveDetector) uses the probe to cache 'don't try again'."""

    def test_supportedFlagSetWhenSupported(self, freshDb: ObdDatabase) -> None:
        client, conn = _client(stored=[], pending=[])  # both supported but empty
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        result = dtcLogger.logSessionStartDtcs(driveId=1, connection=conn)

        assert isinstance(result.mode07Probe, Mode07ProbeResult)
        assert result.mode07Probe.supported is True

    def test_unsupportedFlagSetWhenUnsupported(
        self, freshDb: ObdDatabase,
    ) -> None:
        client, conn = _client(stored=[], mode07Supported=False)
        dtcLogger = DtcLogger(database=freshDb, dtcClient=client)

        result = dtcLogger.logSessionStartDtcs(driveId=1, connection=conn)

        assert result.mode07Probe.supported is False
