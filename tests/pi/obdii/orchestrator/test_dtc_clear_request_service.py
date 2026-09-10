################################################################################
# File Name: test_dtc_clear_request_service.py
# Purpose/Description: ARCH-023 -- the orchestrator half of the CLEAR CODES
#   bridge: the run-loop hook that services a clear request.
#
#   The orchestrator is the ONLY process permitted to touch the OBD serial port
#   (A-17 / A-26 -- a second opener cost this project a month of capture and 111
#   days of battery health).  So the HTTP process publishes a request and this
#   hook answers it, following the established `_maybeTriggerX()` per-pass shape.
#
#   🔴 WHAT THESE TESTS PIN, and it is all about refusing to fake an ECU write:
#     * no request                  -> do nothing, cheaply (this runs every pass)
#     * request + no connection     -> write an HONEST failure, never a clear
#     * request + connection        -> issue Mode 04, publish the readback
#     * the request is CONSUMED     -> Mode 04 is irreversible; servicing twice
#                                      is a second wipe nobody asked for
#     * the clear RAISES            -> publish the failure; never leave the
#                                      requester hanging on a timeout it cannot
#                                      distinguish from a dead orchestrator
# Author: Atlas (Architect) -- built under the CIO's standing build directive
# Creation Date: 2026-09-09
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-09-09    | Atlas   | Initial -- ARCH-023 orchestrator service hook.
# ================================================================================
################################################################################

from __future__ import annotations

import types

from pi.splash.dtc_clear_channel import readOutcome, readRequest, writeRequest


class _FakeReadback:
    def __init__(self, stored, pending):
        self.stored = stored
        self.pending = pending


class _FakeDtcClient:
    """Stands in for DtcClient. Records whether Mode 04 was actually issued."""

    def __init__(self, stored=None, pending=None, raises=None):
        self.calls = 0
        self._stored = stored if stored is not None else []
        self._pending = pending if pending is not None else []
        self._raises = raises

    def clearDtcs(self, connection):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return _FakeReadback(self._stored, self._pending)


def _orchestrator(tmp_path, connection, client):
    """A bare object carrying just what the hook touches.

    Deliberately NOT a real Orchestrator: the hook must depend only on
    `_connection`, the states dir and an injected client, so it can be reasoned
    about (and serviced) without standing up the whole lifecycle.
    """
    from pi.obdii.orchestrator.core import ApplicationOrchestrator

    obj = types.SimpleNamespace()
    obj._connection = connection
    obj._config = {"pi": {"splash": {"statesDir": str(tmp_path)}}}
    obj._dtcClearClientFactory = lambda: client
    obj._maybeServiceDtcClearRequest = types.MethodType(
        ApplicationOrchestrator._maybeServiceDtcClearRequest, obj
    )
    obj._publishDtcClearOutcome = types.MethodType(
        ApplicationOrchestrator._publishDtcClearOutcome, obj
    )
    return obj


class TestServiceDtcClearRequest:
    def test_noRequest_isANoOp_andIssuesNoClear(self, tmp_path):
        client = _FakeDtcClient()
        orch = _orchestrator(tmp_path, connection=object(), client=client)

        assert orch._maybeServiceDtcClearRequest() is False
        assert client.calls == 0

    def test_request_withConnection_issuesMode04_andPublishesTheReadback(
        self, tmp_path
    ):
        client = _FakeDtcClient(stored=[], pending=[])
        conn = types.SimpleNamespace(isConnected=lambda: True)
        orch = _orchestrator(tmp_path, connection=conn, client=client)
        writeRequest(str(tmp_path), "req-1", nowFn=lambda: 1.0)

        assert orch._maybeServiceDtcClearRequest() is True

        assert client.calls == 1
        outcome = readOutcome(str(tmp_path))
        assert outcome["requestId"] == "req-1"
        assert outcome["ok"] is True
        assert outcome["stored"] == []

    def test_theRequestIsConsumed_soOneRequestClearsExactlyOnce(self, tmp_path):
        """🔴 Mode 04 is irreversible; a request left behind is a second wipe."""
        client = _FakeDtcClient()
        conn = types.SimpleNamespace(isConnected=lambda: True)
        orch = _orchestrator(tmp_path, connection=conn, client=client)
        writeRequest(str(tmp_path), "req-1", nowFn=lambda: 1.0)

        orch._maybeServiceDtcClearRequest()
        orch._maybeServiceDtcClearRequest()  # next run-loop pass

        assert client.calls == 1
        assert readRequest(str(tmp_path)) is None

    def test_noConnection_publishesAnHonestFailure_andIssuesNoClear(self, tmp_path):
        """No OBD link is a REFUSAL, and it must be said out loud.

        Silence here is indistinguishable from a dead orchestrator, so the
        operator would be told 'timed out' when the truth is 'not connected'.
        """
        client = _FakeDtcClient()
        orch = _orchestrator(tmp_path, connection=None, client=client)
        writeRequest(str(tmp_path), "req-1", nowFn=lambda: 1.0)

        assert orch._maybeServiceDtcClearRequest() is True

        assert client.calls == 0
        outcome = readOutcome(str(tmp_path))
        assert outcome["requestId"] == "req-1"
        assert outcome["ok"] is False
        assert "connect" in (outcome["error"] or "").lower()

    def test_disconnectedConnection_alsoRefuses(self, tmp_path):
        client = _FakeDtcClient()
        conn = types.SimpleNamespace(isConnected=lambda: False)
        orch = _orchestrator(tmp_path, connection=conn, client=client)
        writeRequest(str(tmp_path), "req-1", nowFn=lambda: 1.0)

        orch._maybeServiceDtcClearRequest()

        assert client.calls == 0
        assert readOutcome(str(tmp_path))["ok"] is False

    def test_clearRaises_publishesTheFailure_ratherThanHangingTheRequester(
        self, tmp_path
    ):
        client = _FakeDtcClient(raises=RuntimeError("elm327 write failed"))
        conn = types.SimpleNamespace(isConnected=lambda: True)
        orch = _orchestrator(tmp_path, connection=conn, client=client)
        writeRequest(str(tmp_path), "req-1", nowFn=lambda: 1.0)

        assert orch._maybeServiceDtcClearRequest() is True

        outcome = readOutcome(str(tmp_path))
        assert outcome["ok"] is False
        assert "elm327 write failed" in outcome["error"]
        assert readRequest(str(tmp_path)) is None  # still consumed

    def test_aRaisingClearNeverPropagates_soCaptureSurvives(self, tmp_path):
        """This runs inside the capture loop. It must never take it down."""
        client = _FakeDtcClient(raises=RuntimeError("boom"))
        conn = types.SimpleNamespace(isConnected=lambda: True)
        orch = _orchestrator(tmp_path, connection=conn, client=client)
        writeRequest(str(tmp_path), "req-1", nowFn=lambda: 1.0)

        orch._maybeServiceDtcClearRequest()  # must not raise
