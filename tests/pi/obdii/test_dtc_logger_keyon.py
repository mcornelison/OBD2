################################################################################
# File Name: test_dtc_logger_keyon.py
# Purpose/Description: US-404 (F-111) tests for DtcLogger.logKeyOnDtcs -- the
#   key-on (KOEO) connection-edge DTC read. Verifies a Mode 03(+07) read
#   persists stored+pending codes with drive_id stamped NULL EXPLICITLY (never
#   via getCurrentDriveId -- the load-bearing pre-US-388 stale-open-leak guard,
#   cross-links A-9 Root 2): even with a stale drive_id published on the process
#   context, the KOEO rows MUST be NULL. Also returns the captured codes so the
#   dispatcher can feed the `dtc` emitter.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial -- US-404 KOEO read, drive_id NULL.
# ================================================================================
################################################################################

"""Tests for :meth:`src.pi.obdii.dtc_logger.DtcLogger.logKeyOnDtcs` (US-404)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive_id import setCurrentDriveId
from src.pi.obdii.dtc_client import DtcClient
from src.pi.obdii.dtc_log_schema import DTC_LOG_TABLE
from src.pi.obdii.dtc_logger import DtcLogger


class _FakeResponse:
    def __init__(self, value: Any, null: bool = False) -> None:
        self.value = value
        self._null = null

    def is_null(self) -> bool:
        return self._null


class _FakeConnection:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self._responses = responses or {}
        self.obd = SimpleNamespace(query=self._query)

    def query(self, command: Any) -> Any:
        # US-474: DtcClient routes DTC reads through the serialized query()
        # member now (the raw .obd.query fallback was removed), so the fake
        # exposes query() to satisfy the ObdConnectionLike contract.
        return self.obd.query(command)

    def _query(self, cmd: Any) -> Any:
        name = cmd if isinstance(cmd, str) else getattr(cmd, "name", str(cmd))
        return self._responses.get(name) or _FakeResponse(value=None, null=True)

    def isConnected(self) -> bool:
        return True


def _factory(name: str) -> str:
    return name


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "test_keyon.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture(autouse=True)
def clearDriveContext() -> Any:
    setCurrentDriveId(None)
    yield
    setCurrentDriveId(None)


def _logger(db: ObdDatabase, *, stored=None, pending=None) -> tuple[DtcLogger, _FakeConnection]:
    responses: dict[str, Any] = {}
    if stored is not None:
        responses["GET_DTC"] = _FakeResponse(value=stored)
    if pending is not None:
        responses["GET_CURRENT_DTC"] = _FakeResponse(value=pending)
    conn = _FakeConnection(responses=responses)
    client = DtcClient(commandFactory=_factory)
    return DtcLogger(database=db, dtcClient=client), conn


def _rows(db: ObdDatabase) -> list[dict[str, Any]]:
    with db.connect() as conn:
        cur = conn.execute(
            f"SELECT dtc_code, status, drive_id FROM {DTC_LOG_TABLE} ORDER BY id"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def test_logKeyOnDtcs_persistsStoredAndPending(freshDb):
    """
    Given: a KOEO read with one stored + one pending code
    When: logKeyOnDtcs runs
    Then: both are persisted and the result reports the counts
    """
    logger, conn = _logger(
        freshDb,
        stored=[("P0443", "EVAP purge control valve")],
        pending=[("P1300", "")],
    )

    result = logger.logKeyOnDtcs(connection=conn)

    assert result.storedCount == 1
    assert result.pendingCount == 1
    rows = _rows(freshDb)
    assert {r["dtc_code"] for r in rows} == {"P0443", "P1300"}


def test_logKeyOnDtcs_stampsDriveIdNull_evenWithStaleCurrentDriveId(freshDb):
    """
    Given: a STALE drive_id is published on the process context (the pre-US-388
           leak scenario)
    When: a KOEO read runs
    Then: every row is drive_id NULL -- the KOEO path stamps NULL EXPLICITLY and
          MUST NOT inherit getCurrentDriveId (A-9 Root 2 cross-link)
    """
    setCurrentDriveId(99)  # a stale open drive leaked onto the context
    logger, conn = _logger(
        freshDb,
        stored=[("P0443", "EVAP purge control valve")],
        pending=[("P1300", "")],
    )

    logger.logKeyOnDtcs(connection=conn)

    rows = _rows(freshDb)
    assert rows, "expected KOEO rows"
    assert all(r["drive_id"] is None for r in rows), (
        "KOEO rows must be NULL, not the stale drive_id 99"
    )


def test_logKeyOnDtcs_returnsCapturedCodesForEmitter(freshDb):
    """
    Given: a KOEO read
    When: logKeyOnDtcs runs
    Then: the captured DiagnosticCodes (stored + pending) are returned so the
          dispatcher can feed the `dtc` emitter without a re-read
    """
    logger, conn = _logger(
        freshDb,
        stored=[("P0443", "EVAP purge control valve")],
        pending=[("P1300", "")],
    )

    result = logger.logKeyOnDtcs(connection=conn)

    captured = {c.code for c in result.codes}
    assert captured == {"P0443", "P1300"}
    statuses = {c.code: c.status for c in result.codes}
    assert statuses["P0443"] == "stored"
    assert statuses["P1300"] == "pending"


def test_logKeyOnDtcs_mode07Unsupported_storedStillCaptured(freshDb):
    """
    Given: an ECU that does not answer Mode 07 (pending probe unsupported)
    When: a KOEO read runs
    Then: stored codes still persist NULL; pendingCount is 0 (no fabrication)
    """
    logger, conn = _logger(freshDb, stored=[("P0443", "EVAP purge control valve")])

    result = logger.logKeyOnDtcs(connection=conn)

    assert result.storedCount == 1
    assert result.pendingCount == 0
    rows = _rows(freshDb)
    assert all(r["drive_id"] is None for r in rows)
