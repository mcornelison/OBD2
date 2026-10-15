################################################################################
# File Name: test_fuel_reset_channel.py
# Purpose/Description: US-881-d -- the request/outcome file channel behind
#                      POST /fuel-reset (the dtc_clear_channel pattern, a
#                      separate module; the DTC channel is not generalised).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-881-d) | Initial.
# ================================================================================
################################################################################

"""US-881-d: the fuel-reset request/outcome channel."""

from __future__ import annotations

import pytest

from pi.splash import dtc_clear_channel
from pi.splash import fuel_reset_channel as frc

T = "2026-10-20T15:10:00Z"


def test_filenames_areTheirOwn_notTheDtcChannels():
    assert frc.REQUEST_FILENAME == "fuel-reset-request.json"
    assert frc.OUTCOME_FILENAME == "fuel-reset-outcome.json"
    assert {frc.REQUEST_FILENAME, frc.OUTCOME_FILENAME}.isdisjoint(
        {dtc_clear_channel.REQUEST_FILENAME, dtc_clear_channel.OUTCOME_FILENAME}
    )


def test_request_roundTrip_thenConsumed(tmp_path):
    frc.writeRequest(str(tmp_path), "abc", nowFn=lambda: 12.5)

    assert frc.readRequest(str(tmp_path)) == {"requestId": "abc", "requestedAtEpoch": 12.5}
    frc.consumeRequest(str(tmp_path))
    assert frc.readRequest(str(tmp_path)) is None
    frc.consumeRequest(str(tmp_path))  # idempotent


def test_outcome_roundTrip_echoesTheRequestId(tmp_path):
    frc.writeOutcome(str(tmp_path), requestId="abc", ok=True, reason=None,
                     resetAtTs=T, nowFn=lambda: 3.0)

    assert frc.readOutcome(str(tmp_path)) == {
        "requestId": "abc", "ok": True, "reason": None, "resetAtTs": T,
        "completedAtEpoch": 3.0,
    }


def test_corruptRequest_readsAsNone(tmp_path):
    (tmp_path / frc.REQUEST_FILENAME).write_text("{not json", encoding="utf-8")

    assert frc.readRequest(str(tmp_path)) is None


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def test_runner_returnsTheOutcomeForThisRequest(tmp_path):
    clock = _Clock()
    statesDir = str(tmp_path)

    def sleep(s: float) -> None:
        clock.sleep(s)
        frc.writeOutcome(statesDir, requestId="r1", ok=True, reason=None, resetAtTs=T)

    runner = frc.makeBridgeResetRunner(
        statesDir, timeoutSeconds=5.0, nowFn=clock.now, sleepFn=sleep, idFn=lambda: "r1"
    )

    assert runner() == {"ok": True, "reason": None, "resetAtTs": T}


def test_runner_refusal_isReturnedWithItsReason(tmp_path):
    statesDir = str(tmp_path)

    def sleep(s: float) -> None:
        frc.writeOutcome(statesDir, requestId="r1", ok=False, reason="driving",
                         resetAtTs=None)

    runner = frc.makeBridgeResetRunner(
        statesDir, timeoutSeconds=5.0, nowFn=lambda: 0.0, sleepFn=sleep, idFn=lambda: "r1"
    )

    assert runner() == {"ok": False, "reason": "driving", "resetAtTs": None}


def test_runner_staleOutcomeFromAnEarlierRequest_isNotTheAnswer_timesOut(tmp_path):
    clock = _Clock()
    statesDir = str(tmp_path)
    frc.writeOutcome(statesDir, requestId="old", ok=True, reason=None, resetAtTs=T)
    runner = frc.makeBridgeResetRunner(
        statesDir, timeoutSeconds=5.0, nowFn=clock.now, sleepFn=clock.sleep,
        idFn=lambda: "new",
    )

    with pytest.raises(frc.ResetBridgeTimeout):
        runner()
    assert clock.t >= 5.0
    # The unanswered request is withdrawn so it cannot fire later.
    assert frc.readRequest(statesDir) is None


def test_runner_requestCannotBeWritten_raisesBridgeError(tmp_path):
    missing = str(tmp_path / "no" / "such" / "dir")
    blocker = tmp_path / "no"
    blocker.write_text("a file where the dir should be", encoding="utf-8")
    runner = frc.makeBridgeResetRunner(
        missing, timeoutSeconds=5.0, nowFn=lambda: 0.0, sleepFn=lambda s: None
    )

    with pytest.raises(frc.ResetBridgeError):
        runner()


def test_timeoutIsNotABridgeError_soTheRouteCanTellThemApart():
    assert not issubclass(frc.ResetBridgeTimeout, frc.ResetBridgeError)
