################################################################################
# File Name: test_pi_health.py
# Purpose/Description: US-877-a -- the Pi health provider behind system-status
#   `pi`: vcgencmd temp/throttle parsing and readers, the over-limit rule
#   (79/80 C boundary, bits 0-3 counted, 16-19 not), disk through the real
#   US-762 guard (breached / healthy / unknown), uptime floored, and the
#   sampler's cadence + off-tick daemon thread.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author        | Description
# ================================================================================
# 2026-10-22    | Rex (US-877-a)| Initial.
# ================================================================================
################################################################################

"""Tests for ``src.pi.hardware.pi_health``."""

from __future__ import annotations

import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from src.pi.diagnostics.disk_space_guard import (
    LOW_DISK_THRESHOLD_BYTES,
    assessDiskSpace,
)
from src.pi.hardware.pi_health import (
    DISK_READ_INTERVAL_S,
    FAST_READ_INTERVAL_S,
    PI_HEALTH_KEYS,
    VCGENCMD_TIMEOUT_S,
    PiHealthSampler,
    buildPiHealthBlock,
    derivePiOverLimit,
    parseMeasureTemp,
    parseThrottled,
    readCpuTempC,
    readThrottled,
)

_TS = "2026-10-22T12:00:00Z"


def _runner(stdout: str, returncode: int = 0, calls: list | None = None):
    def run(args, **kwargs):
        if calls is not None:
            calls.append((args, kwargs))
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return run


def _raising(exc: Exception):
    def run(args, **kwargs):
        raise exc

    return run


def _guard(freeBytes: int | None):
    """The REAL guard on an injected free-space reader (None = unreadable)."""

    def reader(_path):
        if freeBytes is None:
            raise OSError("no such filesystem")
        return freeBytes

    return lambda: assessDiskSpace("/", freeSpaceReader=reader, searchRoots=[])


def _block(**overrides):
    kwargs = dict(
        cpuTempC=None, cpuTempTs=None, cpuTempLimitC=80.0,
        throttled=None, throttledTs=None, disk=None, diskTs=None,
        uptimeS=None, uptimeTs=None,
    )
    kwargs.update(overrides)
    return buildPiHealthBlock(**kwargs)


# --------------------------------------------------------------- the readers


def test_parseMeasureTemp_tenthsOfADegree():
    assert parseMeasureTemp("temp=52.6'C\n") == 52.6
    assert parseMeasureTemp("temp=80.0'C") == 80.0
    assert parseMeasureTemp("garbage") is None
    assert parseMeasureTemp("") is None


def test_readCpuTempC_runsMeasureTemp_withTimeoutAndEncodingDeclared():
    calls: list = []
    assert readCpuTempC(_runner("temp=52.6'C\n", calls=calls)) == 52.6
    args, kwargs = calls[0]
    assert args == ["vcgencmd", "measure_temp"]
    assert kwargs["timeout"] == VCGENCMD_TIMEOUT_S == 2.0
    assert kwargs["encoding"] == "utf-8"


def test_readThrottled_runsGetThrottled_withTimeoutAndEncodingDeclared():
    calls: list = []
    reading = readThrottled(_runner("throttled=0x50000\n", calls=calls))
    assert reading is not None and reading.hexText == "0x50000"
    args, kwargs = calls[0]
    assert args == ["vcgencmd", "get_throttled"]
    assert kwargs["timeout"] == 2.0 and kwargs["encoding"] == "utf-8"


@pytest.mark.parametrize(
    "runner",
    [
        _raising(FileNotFoundError("vcgencmd")),
        _raising(subprocess.TimeoutExpired("vcgencmd", 2.0)),
        _raising(OSError("exec failed")),
        _runner("", returncode=1),
        _runner("not a reading"),
    ],
    ids=["missing", "timeout", "oserror", "nonzero-exit", "garbage"],
)
def test_vcgencmdWithNoAnswer_isNone_neverZero(runner):
    assert readCpuTempC(runner) is None
    assert readThrottled(runner) is None


def test_offPi_realHost_vcgencmdAbsent_tempAndThrottledAreNone():
    """No mock: on a host without vcgencmd (this dev box) both read None."""
    import shutil

    if shutil.which("vcgencmd") is not None:
        pytest.skip("vcgencmd present on this host")
    assert readCpuTempC() is None
    assert readThrottled() is None


# ----------------------------------------------------- limits and overLimit


@pytest.mark.parametrize(
    ("temp", "over"),
    [(79.9, False), (79.0, False), (80.0, True), (80.1, True)],
)
def test_cpuTemp_boundary_7980_isInclusive(temp, over):
    assert (
        derivePiOverLimit(
            cpuTempC=temp, cpuTempLimitC=80.0, throttled=False, diskVerdict="healthy"
        )
        == (["cpuTemp"] if over else [])
    )


@pytest.mark.parametrize("bit", [0, 1, 2, 3])
def test_throttled_eachOfBits0to3_isCountedNow(bit):
    reading = parseThrottled(f"throttled=0x{1 << bit:x}")
    assert reading is not None and reading.throttledNow and not reading.sinceBoot
    assert _block(throttled=reading)["overLimit"] == ["throttled"]


@pytest.mark.parametrize("bit", [16, 17, 18, 19])
def test_throttled_bits16to19_areSinceBoot_neverCounted(bit):
    reading = parseThrottled(f"throttled=0x{1 << bit:x}")
    assert reading is not None and reading.sinceBoot and not reading.throttledNow
    block = _block(throttled=reading)
    assert block["throttledSinceBoot"] is True
    assert block["throttled"] is False
    assert block["overLimit"] == []


def test_validation_temp80_throttled0x0_overLimitIsCpuTempOnly():
    """VC: measure_temp 80.0 C, throttled 0x0 -> pi.overLimit ['cpuTemp']."""
    block = _block(
        cpuTempC=readCpuTempC(_runner("temp=80.0'C")), cpuTempTs=_TS,
        throttled=readThrottled(_runner("throttled=0x0")), throttledTs=_TS,
    )
    assert block["overLimit"] == ["cpuTemp"]
    assert (block["throttled"], block["throttledHex"]) == (False, "0x0")


def test_validation_throttled0x50000_sinceBootTrue_notCounted():
    """VC: throttled 0x50000 (bits 16, 18) -> sinceBoot true; not counted."""
    block = _block(
        throttled=readThrottled(_runner("throttled=0x50000")), throttledTs=_TS
    )
    assert block["throttledSinceBoot"] is True
    assert block["throttledHex"] == "0x50000"
    assert "throttled" not in block["overLimit"]


@pytest.mark.parametrize(
    ("freeBytes", "verdict", "published", "over"),
    [
        (LOW_DISK_THRESHOLD_BYTES - 1, "breached", LOW_DISK_THRESHOLD_BYTES - 1, True),
        (LOW_DISK_THRESHOLD_BYTES, "healthy", LOW_DISK_THRESHOLD_BYTES, False),
        (102005460992, "healthy", 102005460992, False),
        (None, "unknown", None, False),
    ],
    ids=["breached", "at-threshold-healthy", "healthy", "unknown"],
)
def test_disk_theGuardsVerdict_isPublished_breachedIsOver(
    freeBytes, verdict, published, over
):
    block = _block(disk=_guard(freeBytes)(), diskTs=_TS)
    assert block["diskVerdict"] == verdict
    assert block["diskFreeBytes"] == published
    assert block["diskThresholdBytes"] == LOW_DISK_THRESHOLD_BYTES
    assert block["diskTs"] == _TS
    assert block["overLimit"] == (["disk"] if over else [])


def test_overLimit_order_isCpuTempThrottledDisk():
    block = _block(
        cpuTempC=85.0, throttled=parseThrottled("throttled=0x4"),
        disk=_guard(1)(),
    )
    assert block["overLimit"] == ["cpuTemp", "throttled", "disk"]


def test_notRead_isNeverOver():
    assert _block()["overLimit"] == []


def test_block_hasTheExactKeySet_andUptimeIsFlooredInt():
    block = _block(uptimeS=3720.97, uptimeTs=_TS)
    assert tuple(block) == PI_HEALTH_KEYS
    assert block["uptimeS"] == 3720 and isinstance(block["uptimeS"], int)


# ------------------------------------------------------------- the sampler


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Counting:
    def __init__(self, value) -> None:
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


def _sampler(clock=None, **readers):
    defaults = dict(
        tempReader=_Counting(52.6),
        throttledReader=_Counting(parseThrottled("throttled=0x0")),
        diskReader=_Counting(_guard(102005460992)()),
        uptimeReader=_Counting(3720.4),
    )
    defaults.update(readers)
    sampler = PiHealthSampler(
        stopEvent=threading.Event(), cpuTempLimitC=80.0,
        clock=clock or _Clock(), wallClockIso=lambda: _TS, **defaults,
    )
    return sampler, defaults


def test_sampler_beforeTheFirstRead_everyKeyNull_overLimitEmpty():
    sampler, readers = _sampler()
    block = sampler.snapshot()
    assert block.pop("overLimit") == []
    assert set(block.values()) == {None}
    assert readers["tempReader"].calls == 0


def test_sampler_example_payload():
    sampler, _ = _sampler()
    sampler.sampleDue()
    assert sampler.snapshot() == {
        "cpuTempC": 52.6, "cpuTempTs": _TS, "cpuTempLimitC": 80.0,
        "throttled": False, "throttledHex": "0x0", "throttledSinceBoot": False,
        "throttledTs": _TS,
        "diskFreeBytes": 102005460992, "diskThresholdBytes": 21474836480,
        "diskVerdict": "healthy", "diskTs": _TS,
        "uptimeS": 3720, "uptimeTs": _TS, "overLimit": [],
    }


def test_sampler_cadence_fast10s_disk600s_uptimeEverySnapshot():
    clock = _Clock()
    sampler, r = _sampler(clock)
    assert (FAST_READ_INTERVAL_S, DISK_READ_INTERVAL_S) == (10.0, 600.0)

    sampler.sampleDue()
    clock.now += 9.9
    sampler.sampleDue()
    assert (r["tempReader"].calls, r["throttledReader"].calls) == (1, 1)
    clock.now += 0.1
    sampler.sampleDue()
    assert (r["tempReader"].calls, r["throttledReader"].calls) == (2, 2)
    assert r["diskReader"].calls == 1
    clock.now = 1000.0 + 599.9
    sampler.sampleDue()
    assert r["diskReader"].calls == 1
    clock.now = 1000.0 + 600.0
    sampler.sampleDue()
    assert r["diskReader"].calls == 2

    before = r["tempReader"].calls
    sampler.snapshot()
    sampler.snapshot()
    assert r["uptimeReader"].calls == 2
    assert r["tempReader"].calls == before  # a snapshot never reads vcgencmd


def test_sampler_aFailedRead_publishesNullForThatFieldOnly():
    def boom():
        raise RuntimeError("wedged")

    sampler, _ = _sampler(tempReader=boom, throttledReader=lambda: None)
    sampler.sampleDue()
    block = sampler.snapshot()
    assert block["cpuTempC"] is None and block["cpuTempTs"] == _TS
    assert block["throttled"] is None and block["throttledHex"] is None
    assert block["diskVerdict"] == "healthy"
    assert block["cpuTempLimitC"] == 80.0


def test_sampler_aLaterFailedRead_replacesTheCachedValueWithNull():
    clock = _Clock()
    temp = _Counting(52.6)
    sampler, _ = _sampler(clock, tempReader=temp)
    sampler.sampleDue()
    temp.value = None
    clock.now += FAST_READ_INTERVAL_S
    sampler.sampleDue()
    assert sampler.snapshot()["cpuTempC"] is None


def test_sampler_eachValueCarriesItsOwnReadTs():
    stamps = iter([
        "2026-10-22T12:00:01Z", "2026-10-22T12:00:02Z", "2026-10-22T12:00:03Z",
        "2026-10-22T12:00:04Z",
    ])
    sampler = PiHealthSampler(
        stopEvent=threading.Event(), clock=_Clock(),
        wallClockIso=lambda: next(stamps),
        tempReader=lambda: 50.0, throttledReader=lambda: parseThrottled("throttled=0x0"),
        diskReader=_guard(102005460992), uptimeReader=lambda: 10.0,
    )
    sampler.sampleDue()
    block = sampler.snapshot()
    assert (block["cpuTempTs"], block["throttledTs"], block["diskTs"], block["uptimeTs"]) == (
        "2026-10-22T12:00:01Z", "2026-10-22T12:00:02Z", "2026-10-22T12:00:03Z",
        "2026-10-22T12:00:04Z",
    )


def test_sampler_defaultLimit_is80():
    sampler = PiHealthSampler(
        stopEvent=threading.Event(), tempReader=lambda: 80.0,
        throttledReader=lambda: None, diskReader=_guard(None), uptimeReader=lambda: None,
    )
    sampler.sampleDue()
    block = sampler.snapshot()
    assert block["cpuTempLimitC"] == 80.0
    assert block["overLimit"] == ["cpuTemp"]


def test_sampler_readsOnADaemonThread_andStopsOnTheEvent():
    readThreads: list = []

    def temp():
        readThreads.append(threading.current_thread())
        return 50.0

    stop = threading.Event()
    sampler = PiHealthSampler(
        stopEvent=stop, tempReader=temp, throttledReader=lambda: None,
        diskReader=_guard(102005460992), uptimeReader=lambda: None,
    )
    sampler.start()
    try:
        deadline = time.monotonic() + 5.0
        while sampler.snapshot()["cpuTempC"] is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert sampler.snapshot()["cpuTempC"] == 50.0
        assert sampler.thread is not None and sampler.thread.daemon
        assert readThreads and all(t is not threading.main_thread() for t in readThreads)
    finally:
        stop.set()
        assert sampler.thread is not None
        sampler.thread.join(timeout=5.0)
    assert not sampler.thread.is_alive()
