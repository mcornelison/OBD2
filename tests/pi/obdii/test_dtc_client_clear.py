################################################################################
# File Name: test_dtc_client_clear.py
# Purpose/Description: US-407 (F-111) tests for DtcClient.clearDtcs -- the net-new
#   Mode 04 (CLEAR_DTC) vehicle-write + the immediate Mode 03(+07) re-read that
#   PROVES the clear (advisory sec 4d: never report "command sent", always
#   re-read to confirm "0 stored, 0 pending" and to catch an instant re-set).
#   This is the only DTC path that writes to the ECU; it is issued only after the
#   authoritative clear gate has passed (see test_dtc_clear.py) -- this module
#   tests the primitive itself: it issues Mode 04 FIRST, then re-reads, and it
#   requires an open connection.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial -- US-407 Mode 04 clear + re-read.
# ================================================================================
################################################################################

"""Tests for :meth:`src.pi.obdii.dtc_client.DtcClient.clearDtcs` (US-407)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.pi.obdii.dtc_client import DtcClient, DtcClientError


class _FakeResponse:
    def __init__(self, value: Any, null: bool = False) -> None:
        self.value = value
        self._null = null

    def is_null(self) -> bool:
        return self._null


class _RecordingConnection:
    """Records the order of queried command names + returns scripted responses."""

    def __init__(self, responses: dict[str, Any], *, connected: bool = True) -> None:
        self._responses = responses
        self._connected = connected
        self.calls: list[str] = []
        self.obd = SimpleNamespace(query=self._query)

    def query(self, command: Any) -> Any:
        # US-474: DtcClient routes DTC reads through the serialized query()
        # member now (the raw .obd.query fallback was removed), so the fake
        # exposes query() to satisfy the ObdConnectionLike contract. Delegates
        # to the same _query routing so call-order recording is preserved.
        return self.obd.query(command)

    def _query(self, cmd: Any) -> Any:
        name = cmd if isinstance(cmd, str) else getattr(cmd, "name", str(cmd))
        self.calls.append(name)
        return self._responses.get(name) or _FakeResponse(value=None, null=True)

    def isConnected(self) -> bool:
        return self._connected


def _factory(name: str) -> str:
    return name


def test_clearDtcs_issuesMode04ThenReReads_provesCleared():
    """Given a clean re-read after the wipe, When clearDtcs runs, Then it issues
    CLEAR_DTC (Mode 04) and returns an empty stored+pending readback (proof)."""
    conn = _RecordingConnection(
        {
            "CLEAR_DTC": _FakeResponse(value=None),
            "GET_DTC": _FakeResponse(value=[]),
            "GET_CURRENT_DTC": _FakeResponse(value=[]),
        }
    )
    client = DtcClient(commandFactory=_factory)

    readback = client.clearDtcs(conn)

    assert "CLEAR_DTC" in conn.calls, "Mode 04 CLEAR_DTC must be issued"
    assert readback.stored == [], "re-read proves no stored codes remain"
    assert readback.pending == [], "re-read proves no pending codes remain"


def test_clearDtcs_issuesClearBeforeReRead_neverReportsCommandSent():
    """The wipe is issued BEFORE the re-read -- the re-read is the proof, so the
    clear must happen first (advisory sec 4d)."""
    conn = _RecordingConnection(
        {
            "CLEAR_DTC": _FakeResponse(value=None),
            "GET_DTC": _FakeResponse(value=[]),
            "GET_CURRENT_DTC": _FakeResponse(value=[]),
        }
    )
    client = DtcClient(commandFactory=_factory)

    client.clearDtcs(conn)

    assert conn.calls[0] == "CLEAR_DTC", "Mode 04 must precede the re-read"
    assert conn.calls.index("CLEAR_DTC") < conn.calls.index("GET_DTC")


def test_clearDtcs_reReadCatchesInstantReSet():
    """If a code returns immediately after the wipe, the Mode 03 re-read surfaces
    it (feeds US-407 re-set detection / session-lock)."""
    conn = _RecordingConnection(
        {
            "CLEAR_DTC": _FakeResponse(value=None),
            "GET_DTC": _FakeResponse(value=[("P0443", "EVAP purge control")]),
            "GET_CURRENT_DTC": _FakeResponse(value=[]),
        }
    )
    client = DtcClient(commandFactory=_factory)

    readback = client.clearDtcs(conn)

    assert [c.code for c in readback.stored] == ["P0443"], "re-set code re-read"
    assert readback.stored[0].status == "stored"


def test_clearDtcs_requiresOpenConnection():
    """A Mode 04 vehicle-write must never be attempted on a closed connection."""
    conn = _RecordingConnection({}, connected=False)
    client = DtcClient(commandFactory=_factory)

    with pytest.raises(DtcClientError):
        client.clearDtcs(conn)

    assert conn.calls == [], "no command issued when disconnected"
