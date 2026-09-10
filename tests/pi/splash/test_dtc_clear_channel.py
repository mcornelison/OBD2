################################################################################
# File Name: test_dtc_clear_channel.py
# Purpose/Description: ARCH-023 -- the cross-process channel that finally makes
#   the US-407 CLEAR CODES button do something.
#
#   THE DEFECT THIS EXISTS TO CLOSE.  Every part of US-407 shipped except one
#   join.  The UI button, the client-side gate mirror, the authoritative
#   `dtc_clear.evaluateClearGate`, `performClear`, the POST /dtc-clear route and
#   `DtcClient.clearDtcs` are all present and correct.  The route takes an
#   INJECTED `clearRunner` and NOTHING IN THE TREE EVER INJECTED ONE, so the
#   route answered 503 and the button was inert -- the same shape as the
#   carousel emitters with no caller (A-16) and `pi.pollingTiers` with no
#   importer (A-28): a complete implementation nothing calls.
#
#   WHY IT COULD NOT SIMPLY BE INJECTED, which is the whole design.  The HTTP
#   server (eclipse-states-http.service) and the orchestrator (eclipse-obd.service)
#   are SEPARATE PROCESSES, and only the orchestrator may hold the OBD serial
#   port.  A second opener is precisely the defect that killed capture for a
#   month (A-17: a DTC read bypassing the io lock) and battery health for 111
#   days (A-26: GPIO6 acquired twice).  So the clear crosses the boundary as a
#   REQUEST, serviced by the one process that owns the connection --
#   ssot-design-pattern rule B, read once, others subscribe.
#
#   THE CONTRACT UNDER TEST.  `performClear` needs only a zero-arg callable
#   returning {"stored": [...], "pending": [...], "mil": bool}.  So the bridge IS
#   a clearRunner and the shipped handler needs no change.
#
#   WHAT THESE TESTS REFUSE TO ALLOW.  A clear that cannot be proven must never
#   read as success.  If the orchestrator is down, or slow, or has no OBD
#   connection, the bridge must fail LOUDLY -- never synthesise an empty
#   readback, which `performClear` would faithfully report as "cleared, 0 stored".
#   That is the manufactured-reading rule applied to an ECU write.
# Author: Atlas (Architect) -- built under the CIO's standing build directive
# Creation Date: 2026-09-09
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-09-09    | Atlas   | Initial -- ARCH-023 request/outcome channel + bridge
#               |         | runner, incl. the honest-failure cases.
# ================================================================================
################################################################################

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pi.splash.dtc_clear_channel import (
    OUTCOME_FILENAME,
    REQUEST_FILENAME,
    ClearBridgeError,
    ClearBridgeTimeout,
    consumeRequest,
    makeBridgeClearRunner,
    readRequest,
    writeOutcome,
    writeRequest,
)

# ==============================================================================
# 1) The request half -- written by the HTTP process
# ==============================================================================


class TestRequest:
    def test_writeRequest_landsAnAtomicReadableRequest(self, tmp_path):
        writeRequest(str(tmp_path), "req-1", nowFn=lambda: 100.0)

        req = readRequest(str(tmp_path))
        assert req is not None
        assert req["requestId"] == "req-1"
        assert req["requestedAtEpoch"] == 100.0

    def test_writeRequest_leavesNoTempFileBehind(self, tmp_path):
        """Atomicity is temp + os.replace; a stray .tmp means a torn write."""
        writeRequest(str(tmp_path), "req-1", nowFn=lambda: 1.0)

        assert not (tmp_path / (REQUEST_FILENAME + ".tmp")).exists()

    def test_readRequest_absentFile_isNone_notAnError(self, tmp_path):
        assert readRequest(str(tmp_path)) is None

    def test_readRequest_corruptFile_isNone_notAnException(self, tmp_path):
        """A half-written or garbage request must not crash the run loop."""
        (tmp_path / REQUEST_FILENAME).write_text("{not json", encoding="utf-8")

        assert readRequest(str(tmp_path)) is None

    def test_consumeRequest_removesIt_soOneRequestClearsOnce(self, tmp_path):
        """Mode 04 is irreversible. Servicing a request twice is a second wipe."""
        writeRequest(str(tmp_path), "req-1", nowFn=lambda: 1.0)

        consumeRequest(str(tmp_path))

        assert readRequest(str(tmp_path)) is None

    def test_consumeRequest_isIdempotent_whenAlreadyGone(self, tmp_path):
        consumeRequest(str(tmp_path))  # must not raise


# ==============================================================================
# 2) The outcome half -- written by the orchestrator
# ==============================================================================


class TestOutcome:
    def test_writeOutcome_roundTrips(self, tmp_path):
        writeOutcome(
            str(tmp_path),
            requestId="req-1",
            ok=True,
            stored=["P0443"],
            pending=[],
            mil=True,
            error=None,
            nowFn=lambda: 200.0,
        )

        payload = json.loads((tmp_path / OUTCOME_FILENAME).read_text(encoding="utf-8"))
        assert payload["requestId"] == "req-1"
        assert payload["ok"] is True
        assert payload["stored"] == ["P0443"]
        assert payload["mil"] is True
        assert payload["completedAtEpoch"] == 200.0

    def test_writeOutcome_leavesNoTempFileBehind(self, tmp_path):
        writeOutcome(
            str(tmp_path), requestId="r", ok=True, stored=[], pending=[],
            mil=False, error=None, nowFn=lambda: 1.0,
        )

        assert not (tmp_path / (OUTCOME_FILENAME + ".tmp")).exists()


# ==============================================================================
# 3) The bridge runner -- what the HTTP process hands to performClear
# ==============================================================================


class TestBridgeClearRunner:
    def test_happyPath_returnsThePerformClearMapping(self, tmp_path):
        """The readback shape performClear consumes: stored / pending / mil."""
        ticks = iter([0.0, 0.1, 0.2, 0.3])

        def fakeSleep(_seconds):
            # The orchestrator "services" the request on the first wait.
            req = readRequest(str(tmp_path))
            if req is not None:
                consumeRequest(str(tmp_path))
                writeOutcome(
                    str(tmp_path), requestId=req["requestId"], ok=True,
                    stored=[], pending=[], mil=False, error=None,
                    nowFn=lambda: 5.0,
                )

        runner = makeBridgeClearRunner(
            str(tmp_path), timeoutSeconds=5.0,
            nowFn=lambda: next(ticks), sleepFn=fakeSleep,
            idFn=lambda: "req-happy",
        )

        readback = runner()

        assert readback == {"stored": [], "pending": [], "mil": False}

    def test_carriesTheCodesThatCameBack_soAnInstantResetIsVisible(self, tmp_path):
        """performClear compares before/after to catch a code that re-sets at once."""
        ticks = iter([0.0, 0.1, 0.2])

        def fakeSleep(_seconds):
            req = readRequest(str(tmp_path))
            if req is not None:
                consumeRequest(str(tmp_path))
                writeOutcome(
                    str(tmp_path), requestId=req["requestId"], ok=True,
                    stored=["P0443"], pending=["P0400"], mil=True, error=None,
                    nowFn=lambda: 5.0,
                )

        runner = makeBridgeClearRunner(
            str(tmp_path), timeoutSeconds=5.0,
            nowFn=lambda: next(ticks), sleepFn=fakeSleep, idFn=lambda: "r",
        )

        assert runner() == {
            "stored": ["P0443"], "pending": ["P0400"], "mil": True,
        }

    def test_orchestratorDown_RAISES_ratherThanReportingAnEmptyClear(self, tmp_path):
        """🔴 THE LOAD-BEARING TEST.

        Nothing services the request. A bridge that returned an empty readback
        here would have performClear report "cleared -- 0 stored, 0 pending":
        a fabricated success for an ECU write that never happened.
        """
        ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])

        runner = makeBridgeClearRunner(
            str(tmp_path), timeoutSeconds=3.0,
            nowFn=lambda: next(ticks), sleepFn=lambda _s: None,
            idFn=lambda: "req-never-serviced",
        )

        with pytest.raises(ClearBridgeTimeout):
            runner()

    def test_orchestratorReportedFailure_RAISES_neverReadsAsCleared(self, tmp_path):
        """An `ok: false` outcome is a refusal (e.g. no OBD connection)."""
        ticks = iter([0.0, 0.1, 0.2])

        def fakeSleep(_seconds):
            req = readRequest(str(tmp_path))
            if req is not None:
                consumeRequest(str(tmp_path))
                writeOutcome(
                    str(tmp_path), requestId=req["requestId"], ok=False,
                    stored=[], pending=[], mil=False,
                    error="no OBD connection", nowFn=lambda: 5.0,
                )

        runner = makeBridgeClearRunner(
            str(tmp_path), timeoutSeconds=5.0,
            nowFn=lambda: next(ticks), sleepFn=fakeSleep, idFn=lambda: "r",
        )

        with pytest.raises(ClearBridgeError, match="no OBD connection"):
            runner()

    def test_staleOutcomeFromAnEarlierRequest_isIgnored(self, tmp_path):
        """🔴 A leftover outcome must never satisfy a NEW request.

        Otherwise the second press of CLEAR CODES reports the FIRST press's
        result and no Mode 04 is ever issued -- a lie built from a real record.
        """
        writeOutcome(
            str(tmp_path), requestId="OLD-request", ok=True, stored=[],
            pending=[], mil=False, error=None, nowFn=lambda: 1.0,
        )
        ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])

        runner = makeBridgeClearRunner(
            str(tmp_path), timeoutSeconds=2.0,
            nowFn=lambda: next(ticks), sleepFn=lambda _s: None,
            idFn=lambda: "NEW-request",
        )

        with pytest.raises(ClearBridgeTimeout):
            runner()

    def test_writesTheRequestBeforeWaiting(self, tmp_path):
        """The orchestrator can only service what it can see."""
        seen = {}

        def fakeSleep(_seconds):
            seen["request"] = readRequest(str(tmp_path))
            req = seen["request"]
            if req:
                consumeRequest(str(tmp_path))
                writeOutcome(
                    str(tmp_path), requestId=req["requestId"], ok=True,
                    stored=[], pending=[], mil=False, error=None,
                    nowFn=lambda: 9.0,
                )

        ticks = iter([0.0, 0.1, 0.2])
        runner = makeBridgeClearRunner(
            str(tmp_path), timeoutSeconds=5.0,
            nowFn=lambda: next(ticks), sleepFn=fakeSleep, idFn=lambda: "req-x",
        )
        runner()

        assert seen["request"] is not None
        assert seen["request"]["requestId"] == "req-x"

    def test_unwritableStatesDir_RAISES_ratherThanSilentlySucceeding(self, tmp_path):
        missing = Path(tmp_path) / "nope" / "deeper"

        runner = makeBridgeClearRunner(
            str(missing), timeoutSeconds=1.0, nowFn=lambda: 0.0,
            sleepFn=lambda _s: None, idFn=lambda: "r",
        )

        with pytest.raises(ClearBridgeError):
            runner()
