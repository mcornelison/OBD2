################################################################################
# File Name: test_bluetooth_connected_state.py
# Purpose/Description: US-876-e -- the link chain's Bluetooth layer reads the
#                      real BT connection: bluetoothctl 'Connected:' parsing,
#                      the 2 s reader, and the off-tick 5 s sampler.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-22    | Ralph (Rex)  | Initial (US-876-e).
# ================================================================================
################################################################################

"""Tests for the BT-connected reading in ``pi.obdii.bluetooth_helper`` (US-876-e).

Every subprocess is an injected double: nothing here spawns bluetoothctl, and
every sampler thread a test starts is stopped and joined before it returns.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Any

import pytest

from pi.obdii import bluetooth_helper as bh

_MAC = "00:04:3E:85:0D:FB"

# Atlas MEASURED key-off shape: bonded, not connected.
_INFO_KEY_OFF = (
    f"Device {_MAC} (public)\n"
    "\tName: OBDLink LX\n"
    "\tAlias: OBDLink LX\n"
    "\tPaired: yes\n"
    "\tBonded: yes\n"
    "\tTrusted: yes\n"
    "\tBlocked: no\n"
    "\tConnected: no\n"
)
_INFO_CONNECTED = _INFO_KEY_OFF.replace("Connected: no", "Connected: yes")
_INFO_NOT_AVAILABLE = f"Device {_MAC} not available\n"
_INFO_UNPAIRED = _INFO_KEY_OFF.replace("Paired: yes", "Paired: no")


class _Runner:
    """Replays one canned bluetoothctl reply (or raises) and records each call."""

    def __init__(self, stdout: str = "", raises: BaseException | None = None):
        self.stdout = stdout
        self.raises = raises
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []
        self.threads: list[threading.Thread] = []
        self.called = threading.Event()

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        self.kwargs.append(dict(kwargs))
        self.threads.append(threading.current_thread())
        self.called.set()
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(cmd, 0, stdout=self.stdout, stderr="")


# ================================================================================
# parseConnectedState -- the E4 precedence
# ================================================================================


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (_INFO_CONNECTED, bh.BT_CONNECTED),
        (_INFO_KEY_OFF, bh.BT_NOT_CONNECTED),
        (_INFO_NOT_AVAILABLE, bh.BT_ABSENT),
        (_INFO_UNPAIRED, bh.BT_ABSENT),
        ("garbage \x00 no flags here", None),
        ("", None),
    ],
    ids=["yes", "no", "not-available", "paired-no", "garbage", "empty"],
)
def test_parseConnectedState_eachShape(output: str, expected: str | None) -> None:
    """
    Given: one bluetoothctl info reply of each shape the story names
    When:  it is parsed
    Then:  yes -> connected, no -> not connected, not available / Paired: no
           -> absent, anything unparseable -> None (never absent)
    """
    assert bh.parseConnectedState(output) == expected


def test_parseConnectedState_connectedYes_winsOverPairedNo() -> None:
    """E4: 'Connected: yes' is up regardless of Paired."""
    output = _INFO_CONNECTED.replace("Paired: yes", "Paired: no")

    assert bh.parseConnectedState(output) == bh.BT_CONNECTED


def test_parseConnectedState_ansiColouredReply_isParsed() -> None:
    """bluetoothctl may colour its output; the codes are stripped first."""
    output = "\x1b[0;94m[bluetooth]\x1b[0m# \n\tConnected: \x1b[1;32myes\x1b[0m\n"

    assert bh.parseConnectedState(output) == bh.BT_CONNECTED


def test_parseConnectedState_pairedYesButNoConnectedLine_isUnreadable() -> None:
    """A reply that names no Connected flag and no absence is not a reading."""
    assert bh.parseConnectedState("\tPaired: yes\n\tTrusted: yes\n") is None


# ================================================================================
# readConnectedState -- the 2 s reader
# ================================================================================


def test_readConnectedState_runsInfoWithTheTwoSecondTimeout_andDeclaresEncoding() -> None:
    """
    Given: an injected runner
    When:  the reader runs
    Then:  it runs `bluetoothctl info <MAC>` with the NEW 2 s timeout, in text
           mode with a declared encoding; the bond read's 5 s cap is untouched
    """
    runner = _Runner(stdout=_INFO_CONNECTED)

    reading = bh.readConnectedState(_MAC, subprocessRunner=runner)

    assert reading == bh.BT_CONNECTED
    assert runner.calls == [["bluetoothctl", "info", _MAC]]
    assert runner.kwargs[0]["timeout"] == bh.BLUETOOTHCTL_CONNECTED_TIMEOUT_S == 2
    assert runner.kwargs[0]["text"] is True
    assert runner.kwargs[0]["encoding"] == "utf-8"
    assert bh.BLUETOOTHCTL_TIMEOUT_S == 5


@pytest.mark.parametrize(
    "error",
    [
        subprocess.TimeoutExpired(["bluetoothctl"], 2),
        FileNotFoundError("bluetoothctl"),
        OSError("bluez wedged"),
    ],
    ids=["timeout", "missing-tool", "os-error"],
)
def test_readConnectedState_unreadable_isNone_neverAbsent(error: BaseException) -> None:
    """A timeout, a missing bluetoothctl (the dev box) or any raise -> None."""
    assert bh.readConnectedState(_MAC, subprocessRunner=_Runner(raises=error)) is None


def test_readConnectedState_notAMac_runsNothing() -> None:
    """An rfcomm path or the --simulate MAC is never handed to bluetoothctl."""
    runner = _Runner(stdout=_INFO_CONNECTED)

    for value in ("/dev/rfcomm0", "SIMULATED:00:11:22:33:44:55", ""):
        assert bh.readConnectedState(value, subprocessRunner=runner) is None
    assert runner.calls == []


# ================================================================================
# BtConnectedSampler -- off the tick, 5 s cadence, daemon, stops on the event
# ================================================================================


class _RecordingStop:
    """A stop event whose wait() records each timeout and stops after N waits."""

    def __init__(self, waitsBeforeStop: int):
        self._remaining = waitsBeforeStop
        self.timeouts: list[float] = []
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def wait(self, timeout: float | None = None) -> bool:
        self.timeouts.append(float(timeout or 0.0))
        self._remaining -= 1
        if self._remaining <= 0:
            self._set = True
        return self._set


def test_sampler_cadenceIsFiveSeconds_andEachSampleCarriesItsOwnTime() -> None:
    """
    Given: a sampler whose stop event ends it after three waits
    When:  its loop runs
    Then:  it samples, then waits 5 s, three times; each sample is dated the
           sample instant (canonical UTC) on the injected clocks
    """
    runner = _Runner(stdout=_INFO_KEY_OFF)
    stop = _RecordingStop(waitsBeforeStop=3)
    ticks = iter(range(100, 200))
    stamps = iter(f"2026-10-22T15:00:0{i}Z" for i in range(10))
    sampler = bh.BtConnectedSampler(
        _MAC,
        stopEvent=stop,
        subprocessRunner=runner,
        clock=lambda: float(next(ticks)),
        wallClockIso=lambda: next(stamps),
    )

    sampler.run()

    assert stop.timeouts == [bh.BT_CONNECTED_SAMPLE_INTERVAL_S] * 3
    assert bh.BT_CONNECTED_SAMPLE_INTERVAL_S == 5.0
    assert len(runner.calls) == 3
    latest = sampler.latest()
    assert latest == bh.BtConnectedSample(
        reading=bh.BT_NOT_CONNECTED, ts="2026-10-22T15:00:02Z", monoS=102.0
    )


def test_sampler_stopEventAlreadySet_samplesNothing() -> None:
    """A shutdown that came first leaves nothing to sample."""
    runner = _Runner(stdout=_INFO_CONNECTED)
    stop = threading.Event()
    stop.set()
    sampler = bh.BtConnectedSampler(_MAC, stopEvent=stop, subprocessRunner=runner)

    sampler.run()

    assert runner.calls == []
    assert sampler.latest() is None


def test_sampler_start_runsOnItsOwnDaemonThread_andExitsOnTheEvent() -> None:
    """
    Given: a started sampler
    When:  its first sample lands and the stop event is then set
    Then:  the sample ran on the sampler's daemon thread (never the caller's),
           and the thread exits
    """
    runner = _Runner(stdout=_INFO_CONNECTED)
    stop = threading.Event()
    sampler = bh.BtConnectedSampler(_MAC, stopEvent=stop, subprocessRunner=runner)

    sampler.start()
    try:
        assert runner.called.wait(timeout=5.0)
    finally:
        stop.set()
        sampler.thread.join(timeout=5.0)

    assert sampler.thread.daemon is True
    assert not sampler.thread.is_alive()
    assert runner.threads == [sampler.thread]
    assert threading.current_thread() not in runner.threads
    latest = sampler.latest()
    assert latest is not None and latest.reading == bh.BT_CONNECTED


def test_sampler_unreadableSample_isRecordedAsNone() -> None:
    """A timeout is a sample whose reading is None -- never an absent device."""
    stop = _RecordingStop(waitsBeforeStop=1)
    sampler = bh.BtConnectedSampler(
        _MAC,
        stopEvent=stop,
        subprocessRunner=_Runner(raises=subprocess.TimeoutExpired(["bluetoothctl"], 2)),
        clock=lambda: 1.0,
        wallClockIso=lambda: "2026-10-22T15:00:00Z",
    )

    sampler.run()

    assert sampler.latest() == bh.BtConnectedSample(
        reading=None, ts="2026-10-22T15:00:00Z", monoS=1.0
    )


def test_sampler_notAMac_isRefused() -> None:
    """The sampler is only ever built for a real MAC."""
    with pytest.raises(ValueError):
        bh.BtConnectedSampler("/dev/rfcomm0", stopEvent=threading.Event())
