################################################################################
# File Name: test_request_channel.py
# Purpose/Description: US-897-c0 -- the ONE request/outcome file channel that
#                      /dtc-clear and /fuel-reset (and next the alerts ack)
#                      share: file round-trips, the single poll loop, its
#                      neutral timeout and publish errors.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-20    | Rex (US-897-c0) | Initial.
# ================================================================================
################################################################################

"""US-897-c0: the shared request/outcome channel helper."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pi.splash import dtc_clear_channel, fuel_reset_channel
from pi.splash import request_channel as rc

SPLASH_DIR = Path(rc.__file__).resolve().parent


def _channel() -> rc.RequestChannel:
    return rc.RequestChannel("x-request.json", "x-outcome.json")


def _answerOnSleep(statesDir: str, channel: rc.RequestChannel, **extra):
    """A sleepFn that 'services' the pending request like the orchestrator."""
    seen: list[float] = []

    def sleep(seconds: float) -> None:
        seen.append(seconds)
        req = channel.readRequest(statesDir)
        if req is not None:
            channel.consumeRequest(statesDir)
            channel.writeOutcome(statesDir, {"requestId": req["requestId"], **extra})

    return sleep, seen


# ==============================================================================
# Files
# ==============================================================================


def test_channel_keepsItsFilenames():
    channel = _channel()

    assert channel.requestFilename == "x-request.json"
    assert channel.outcomeFilename == "x-outcome.json"


def test_request_roundTrip_carriesExtraFields_thenConsumedIdempotently(tmp_path):
    channel = _channel()
    statesDir = str(tmp_path)

    channel.writeRequest(statesDir, "abc", nowFn=lambda: 12.5, requestFields={"key": "v"})

    assert (tmp_path / "x-request.json").exists()
    assert channel.readRequest(statesDir) == {
        "requestId": "abc", "requestedAtEpoch": 12.5, "key": "v",
    }
    channel.consumeRequest(statesDir)
    assert channel.readRequest(statesDir) is None
    channel.consumeRequest(statesDir)  # idempotent


def test_extraRequestFields_cannotOverwriteTheIdOrTheStamp(tmp_path):
    """The requestId match is the whole safety of the channel: a field named
    ``requestId`` must never replace the id the poll loop waits for."""
    channel = _channel()
    statesDir = str(tmp_path)

    channel.writeRequest(
        statesDir, "real", nowFn=lambda: 1.0,
        requestFields={"requestId": "forged", "requestedAtEpoch": 99.0},
    )

    assert channel.readRequest(statesDir) == {"requestId": "real", "requestedAtEpoch": 1.0}


def test_outcome_roundTrip_stampsCompletedAtEpoch(tmp_path):
    channel = _channel()
    statesDir = str(tmp_path)

    channel.writeOutcome(statesDir, {"requestId": "abc", "ok": True}, nowFn=lambda: 3.0)

    assert (tmp_path / "x-outcome.json").exists()
    assert channel.readOutcome(statesDir) == {
        "requestId": "abc", "ok": True, "completedAtEpoch": 3.0,
    }


@pytest.mark.parametrize("raw", ["{not json", "[1, 2]", "\"text\"", ""])
def test_corruptOrNonObjectFile_readsAsNone(tmp_path, raw):
    channel = _channel()
    (tmp_path / "x-request.json").write_text(raw, encoding="utf-8")
    (tmp_path / "x-outcome.json").write_text(raw, encoding="utf-8")

    assert channel.readRequest(str(tmp_path)) is None
    assert channel.readOutcome(str(tmp_path)) is None


def test_absentFiles_readAsNone(tmp_path):
    channel = _channel()

    assert channel.readRequest(str(tmp_path)) is None
    assert channel.readOutcome(str(tmp_path)) is None


def test_twoChannels_inOneDir_doNotSeeEachOther(tmp_path):
    a = rc.RequestChannel("a-request.json", "a-outcome.json")
    b = rc.RequestChannel("b-request.json", "b-outcome.json")
    statesDir = str(tmp_path)

    a.writeRequest(statesDir, "for-a", nowFn=lambda: 1.0)
    a.writeOutcome(statesDir, {"requestId": "for-a"}, nowFn=lambda: 2.0)

    assert b.readRequest(statesDir) is None
    assert b.readOutcome(statesDir) is None


# ==============================================================================
# awaitOutcome -- the one poll loop
# ==============================================================================


def test_awaitOutcome_returnsTheMatchingOutcome_withTwoClockReads(tmp_path):
    """The existing channel tests feed a 3-value nowFn iterator: the happy path
    must read the monotonic clock no more than today's loop (deadline + one
    check) -- a StopIteration here would mean an extra read."""
    channel = _channel()
    statesDir = str(tmp_path)
    sleep, seen = _answerOnSleep(statesDir, channel, ok=True, value=7)
    ticks = iter([0.0, 0.1])

    outcome = channel.awaitOutcome(
        statesDir, timeoutSeconds=5.0, nowFn=lambda: next(ticks),
        wallFn=lambda: 1.0, sleepFn=sleep, idFn=lambda: "r1",
    )

    assert outcome["requestId"] == "r1"
    assert outcome["ok"] is True
    assert outcome["value"] == 7
    assert seen == [rc.POLL_INTERVAL_SECONDS]


def test_awaitOutcome_publishesTheRequestFirst_stampedByWallFn_withFields(tmp_path):
    channel = _channel()
    statesDir = str(tmp_path)
    captured = {}

    def sleep(_seconds: float) -> None:
        captured["request"] = channel.readRequest(statesDir)
        channel.writeOutcome(statesDir, {"requestId": "r9"})

    channel.awaitOutcome(
        statesDir, timeoutSeconds=5.0, requestFields={"alertId": "COOLANT"},
        nowFn=lambda: 0.0, wallFn=lambda: 1234.5, sleepFn=sleep, idFn=lambda: "r9",
    )

    assert captured["request"] == {
        "requestId": "r9", "requestedAtEpoch": 1234.5, "alertId": "COOLANT",
    }


def test_awaitOutcome_staleOutcome_isNotTheAnswer_timesOutAndWithdrawsTheRequest(tmp_path):
    channel = _channel()
    statesDir = str(tmp_path)
    channel.writeOutcome(statesDir, {"requestId": "old", "ok": True})
    clock = {"t": 0.0}

    def sleep(seconds: float) -> None:
        clock["t"] += seconds

    with pytest.raises(rc.RequestChannelTimeout) as info:
        channel.awaitOutcome(
            statesDir, timeoutSeconds=2.0, nowFn=lambda: clock["t"],
            sleepFn=sleep, idFn=lambda: "new",
        )

    assert clock["t"] >= 2.0
    assert info.value.timeoutSeconds == 2.0
    # The unanswered request is withdrawn so it cannot fire later.
    assert channel.readRequest(statesDir) is None


def test_awaitOutcome_nonMappingOrIdlessOutcome_isIgnored(tmp_path):
    channel = _channel()
    statesDir = str(tmp_path)
    (tmp_path / "x-outcome.json").write_text("[\"r1\"]", encoding="utf-8")
    ticks = iter([0.0, 1.0, 2.0])

    with pytest.raises(rc.RequestChannelTimeout):
        channel.awaitOutcome(
            statesDir, timeoutSeconds=1.0, nowFn=lambda: next(ticks),
            sleepFn=lambda _s: None, idFn=lambda: "r1",
        )


def test_awaitOutcome_unwritableDir_raisesPublishError_carryingTheCause(tmp_path):
    blocker = tmp_path / "no"
    blocker.write_text("a file where the dir should be", encoding="utf-8")
    missing = str(blocker / "deeper")
    slept: list[float] = []

    with pytest.raises(rc.RequestChannelPublishError) as info:
        _channel().awaitOutcome(
            missing, timeoutSeconds=1.0, nowFn=lambda: 0.0,
            sleepFn=slept.append, idFn=lambda: "r",
        )

    assert info.value.statesDir == missing
    assert isinstance(info.value.cause, OSError)
    assert info.value.__cause__ is info.value.cause
    assert slept == []  # nothing to wait for


def test_neutralErrors_areNotRelated():
    """Each wrapper maps the two onto its own classes and hierarchy."""
    assert not issubclass(rc.RequestChannelTimeout, rc.RequestChannelPublishError)
    assert not issubclass(rc.RequestChannelPublishError, rc.RequestChannelTimeout)


# ==============================================================================
# The wrappers ride the helper
# ==============================================================================


def test_bothWrappers_shareThePollCadence():
    assert dtc_clear_channel.POLL_INTERVAL_SECONDS == rc.POLL_INTERVAL_SECONDS
    assert fuel_reset_channel.POLL_INTERVAL_SECONDS == rc.POLL_INTERVAL_SECONDS


def test_grepGate_exactlyOnePollLoop_andOneJsonReader_underSplash():
    sleeps, readers = [], []
    for path in sorted(SPLASH_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        sleeps += [path.name] * len(re.findall(r"sleepFn\(POLL_INTERVAL_SECONDS\)", text))
        readers += [path.name] * len(re.findall(r"def _readJson\b", text))

    assert sleeps == ["request_channel.py"]
    assert readers == ["request_channel.py"]
