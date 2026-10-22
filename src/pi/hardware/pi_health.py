################################################################################
# File Name: pi_health.py
# Purpose/Description: US-877-a -- the Pi health provider behind system-status
#   `pi`: CPU temperature and throttle state from vcgencmd, free disk from the
#   US-762 disk_space_guard, uptime from /proc/uptime -- each against its
#   sourced limit, with the over-limit list computed HERE so the page compares
#   nothing. The slow reads run on a daemon sampler thread; the system-status
#   tick only publishes cached values.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author        | Description
# ================================================================================
# 2026-10-22    | Rex (US-877-a)| Initial: vcgencmd temp/throttle readers, the
#               |               | over-limit rule and PiHealthSampler (Atlas
#               |               | Y-5, P1-P5).
# ================================================================================
################################################################################

"""Pi health, read off the system-status tick and judged against its limits.

The block this module builds is system-status ``pi`` (Atlas Y-5)::

    cpuTempC, cpuTempTs, cpuTempLimitC,
    throttled, throttledHex, throttledSinceBoot, throttledTs,
    diskFreeBytes, diskThresholdBytes, diskVerdict, diskTs,
    uptimeS, uptimeTs, overLimit

Limits (Atlas P1, sourced -- no number here is invented):

* ``cpuTemp`` -- ``pi.health.limits.cpuTempC`` (80 C shipped: the onset of the
  Arm core's firmware throttling, raspberrypi.com frequency management). Over
  when ``cpuTempC >= limit`` (P5: inclusive).
* ``throttled`` -- ANY of ``get_throttled`` bits 0-3 set NOW (under-voltage,
  frequency capped, throttled, soft temperature limit). Firmware facts, no
  threshold. Bits 16-19 are the same four conditions SINCE BOOT: published as
  ``throttledSinceBoot`` and NOT counted -- a past event is not a present one.
* ``disk`` -- the guard's own verdict ``breached`` against its
  ``LOW_DISK_THRESHOLD_BYTES``; this module never re-compares free bytes.

``cpuTempC`` comes from ``vcgencmd measure_temp`` ONLY (Atlas P1: no
thermal_zone0 fallback). Off-Pi there is no vcgencmd, so temp and throttle are
null; the disk read is real on any host.
"""

from __future__ import annotations

import logging
import math
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from src.pi.diagnostics.disk_space_guard import (
    DiskSpaceState,
    DiskVerdict,
    assessDiskSpace,
)
from src.pi.power.soc_calibration import readSystemUptimeSeconds

__all__ = [
    "DEFAULT_CPU_TEMP_LIMIT_C",
    "DISK_READ_INTERVAL_S",
    "FAST_READ_INTERVAL_S",
    "OVER_LIMIT_CPU_TEMP",
    "OVER_LIMIT_DISK",
    "OVER_LIMIT_THROTTLED",
    "PI_HEALTH_KEYS",
    "THROTTLED_NOW_MASK",
    "THROTTLED_SINCE_BOOT_MASK",
    "VCGENCMD_TIMEOUT_S",
    "PiHealthSampler",
    "ThrottledReading",
    "buildPiHealthBlock",
    "derivePiOverLimit",
    "parseMeasureTemp",
    "parseThrottled",
    "readCpuTempC",
    "readThrottled",
    "unreadPiHealth",
]

logger = logging.getLogger(__name__)

#: The block's exact key set, in publish order (Atlas Y-5; no block ts).
PI_HEALTH_KEYS: tuple[str, ...] = (
    "cpuTempC", "cpuTempTs", "cpuTempLimitC",
    "throttled", "throttledHex", "throttledSinceBoot", "throttledTs",
    "diskFreeBytes", "diskThresholdBytes", "diskVerdict", "diskTs",
    "uptimeS", "uptimeTs",
    "overLimit",
)

#: Mirrors validator DEFAULTS ``pi.health.limits.cpuTempC`` (the SSOT), for a
#: host whose config never went through the validator.
DEFAULT_CPU_TEMP_LIMIT_C: float = 80.0

#: The overLimit names, in publish order (Atlas P5: cpuTemp, throttled, disk).
OVER_LIMIT_CPU_TEMP = "cpuTemp"
OVER_LIMIT_THROTTLED = "throttled"
OVER_LIMIT_DISK = "disk"

#: get_throttled bits 0-3: under-voltage / arm frequency capped / currently
#: throttled / soft temperature limit -- NOW.
THROTTLED_NOW_MASK = 0xF
#: Bits 16-19: the same four conditions, occurred since boot.
THROTTLED_SINCE_BOOT_MASK = 0xF0000

#: vcgencmd subprocess timeout (the ups_monitor pattern; story acceptance).
VCGENCMD_TIMEOUT_S = 2.0

#: Temp + throttle cadence and the disk cadence (Atlas P2).
FAST_READ_INTERVAL_S = 10.0
DISK_READ_INTERVAL_S = 600.0

_MEASURE_TEMP_RE = re.compile(r"temp=\s*(-?\d+(?:\.\d+)?)")
_THROTTLED_RE = re.compile(r"throttled=\s*(0x[0-9a-fA-F]+)")


@dataclass(frozen=True)
class ThrottledReading:
    """One ``vcgencmd get_throttled`` read.

    Attributes:
        value: The raw bit field.
        hexText: The field as published (``0x50000``).
        throttledNow: Any of bits 0-3 set.
        sinceBoot: Any of bits 16-19 set.
    """

    value: int
    hexText: str
    throttledNow: bool
    sinceBoot: bool


SubprocessRunner = Callable[..., Any]


def _runVcgencmd(args: list[str], runner: SubprocessRunner | None) -> str | None:
    """Run ``vcgencmd <args>``; its stdout, or None when it gave no answer."""
    run = runner or subprocess.run
    try:
        result = run(
            ["vcgencmd", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=VCGENCMD_TIMEOUT_S,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.debug("vcgencmd %s unavailable: %s", " ".join(args), e)
        return None
    if result.returncode != 0:
        logger.debug("vcgencmd %s failed: rc=%s", " ".join(args), result.returncode)
        return None
    stdout: str = result.stdout
    return stdout


def parseMeasureTemp(text: str) -> float | None:
    """Parse ``temp=52.6'C`` to 52.6 (0.1 C), or None when unparseable."""
    match = _MEASURE_TEMP_RE.search(text or "")
    if not match:
        return None
    value = float(match.group(1))
    return round(value, 1) if math.isfinite(value) else None


def parseThrottled(text: str) -> ThrottledReading | None:
    """Parse ``throttled=0x50000``, or None when unparseable."""
    match = _THROTTLED_RE.search(text or "")
    if not match:
        return None
    value = int(match.group(1), 16)
    return ThrottledReading(
        value=value,
        hexText=f"0x{value:x}",
        throttledNow=bool(value & THROTTLED_NOW_MASK),
        sinceBoot=bool(value & THROTTLED_SINCE_BOOT_MASK),
    )


def readCpuTempC(runner: SubprocessRunner | None = None) -> float | None:
    """``vcgencmd measure_temp`` in C, or None (no vcgencmd, failed, garbage)."""
    stdout = _runVcgencmd(["measure_temp"], runner)
    return parseMeasureTemp(stdout) if stdout is not None else None


def readThrottled(runner: SubprocessRunner | None = None) -> ThrottledReading | None:
    """``vcgencmd get_throttled``, or None (no vcgencmd, failed, garbage)."""
    stdout = _runVcgencmd(["get_throttled"], runner)
    return parseThrottled(stdout) if stdout is not None else None


def derivePiOverLimit(
    *,
    cpuTempC: float | None,
    cpuTempLimitC: float | None,
    throttled: bool | None,
    diskVerdict: str | None,
) -> list[str]:
    """Which of cpuTemp / throttled / disk are over their limit (Atlas P1, P5).

    A field not read is never over: null is not a breach.

    Returns:
        The over names, in the order cpuTemp, throttled, disk.
    """
    over: list[str] = []
    if cpuTempC is not None and cpuTempLimitC is not None and cpuTempC >= cpuTempLimitC:
        over.append(OVER_LIMIT_CPU_TEMP)
    if throttled is True:
        over.append(OVER_LIMIT_THROTTLED)
    if diskVerdict == DiskVerdict.BREACHED.value:
        over.append(OVER_LIMIT_DISK)
    return over


def unreadPiHealth() -> dict[str, Any]:
    """The block when unwired or not yet read: every key null, overLimit []."""
    block: dict[str, Any] = dict.fromkeys(PI_HEALTH_KEYS)
    block["overLimit"] = []
    return block


def buildPiHealthBlock(
    *,
    cpuTempC: float | None,
    cpuTempTs: str | None,
    cpuTempLimitC: float | None,
    throttled: ThrottledReading | None,
    throttledTs: str | None,
    disk: DiskSpaceState | None,
    diskTs: str | None,
    uptimeS: float | None,
    uptimeTs: str | None,
) -> dict[str, Any]:
    """Assemble the ``pi`` block from the latest reads (pure).

    Args:
        cpuTempC: The last temperature read, None when it failed / not read.
        cpuTempTs: When that read was taken, None before the first.
        cpuTempLimitC: The effective ``pi.health.limits.cpuTempC``.
        throttled: The last get_throttled read, None when failed / not read.
        throttledTs: When that read was taken, None before the first.
        disk: The guard's last state, None before the first 600 s read.
        diskTs: When that read was taken, None before the first.
        uptimeS: Seconds since boot, None when unreadable.
        uptimeTs: When uptime was read.

    Returns:
        The exact :data:`PI_HEALTH_KEYS` dict.
    """
    diskVerdict = disk.verdict.value if disk is not None else None
    throttledNow = throttled.throttledNow if throttled is not None else None
    return {
        "cpuTempC": cpuTempC,
        "cpuTempTs": cpuTempTs,
        "cpuTempLimitC": cpuTempLimitC,
        "throttled": throttledNow,
        "throttledHex": throttled.hexText if throttled is not None else None,
        "throttledSinceBoot": throttled.sinceBoot if throttled is not None else None,
        "throttledTs": throttledTs,
        # Guard UNKNOWN carries freeBytes None already (Atlas P3).
        "diskFreeBytes": disk.freeBytes if disk is not None else None,
        # The guard carries the LOW_DISK_THRESHOLD_BYTES it compared against.
        "diskThresholdBytes": disk.thresholdBytes if disk is not None else None,
        "diskVerdict": diskVerdict,
        "diskTs": diskTs,
        # Floored whole seconds (Atlas a-3).
        "uptimeS": math.floor(uptimeS) if uptimeS is not None else None,
        "uptimeTs": uptimeTs,
        "overLimit": derivePiOverLimit(
            cpuTempC=cpuTempC,
            cpuTempLimitC=cpuTempLimitC,
            throttled=throttledNow,
            diskVerdict=diskVerdict,
        ),
    }


class _StopEvent(Protocol):
    """The slice of :class:`threading.Event` the sampler waits on."""

    def is_set(self) -> bool:
        ...

    def wait(self, timeout: float | None = None) -> bool:
        ...


def _wallClockIso() -> str:
    """Aware UTC now as canonical ISO -- the default read stamp."""
    from datetime import UTC, datetime

    from src.common.time.helper import toCanonicalIso

    return toCanonicalIso(datetime.now(UTC))


class PiHealthSampler:
    """Reads temp + throttle every 10 s and disk every 600 s on a daemon thread.

    The system-status tick calls :meth:`snapshot` only: it reads the cached
    values plus ``/proc/uptime`` (a file read, never a subprocess), so a slow
    vcgencmd or a breach walk can never stall the tick (Atlas P2/P4; the
    US-876-e BT sampler's pattern). A failed read replaces its field with null
    and is stamped with the time it was tried.
    """

    def __init__(
        self,
        *,
        stopEvent: _StopEvent,
        cpuTempLimitC: float = DEFAULT_CPU_TEMP_LIMIT_C,
        tempReader: Callable[[], float | None] | None = None,
        throttledReader: Callable[[], ThrottledReading | None] | None = None,
        diskReader: Callable[[], DiskSpaceState] | None = None,
        uptimeReader: Callable[[], float | None] | None = None,
        clock: Callable[[], float] | None = None,
        wallClockIso: Callable[[], str] | None = None,
        fastIntervalS: float = FAST_READ_INTERVAL_S,
        diskIntervalS: float = DISK_READ_INTERVAL_S,
    ) -> None:
        """
        Args:
            stopEvent: Set to stop the loop (the orchestrator's _shutdownEvent).
            cpuTempLimitC: The effective ``pi.health.limits.cpuTempC``.
            tempReader: Defaults to :func:`readCpuTempC`.
            throttledReader: Defaults to :func:`readThrottled`.
            diskReader: Defaults to :func:`assessDiskSpace` (the US-762 guard).
            uptimeReader: Defaults to ``soc_calibration.readSystemUptimeSeconds``.
            clock: Monotonic seconds; defaults to :func:`time.monotonic`.
            wallClockIso: Canonical-UTC now; defaults to the system clock.
            fastIntervalS: Seconds between temp + throttle reads.
            diskIntervalS: Seconds between disk reads.
        """
        self._stopEvent = stopEvent
        self._cpuTempLimitC = cpuTempLimitC
        self._tempReader = tempReader or readCpuTempC
        self._throttledReader = throttledReader or readThrottled
        self._diskReader = diskReader or assessDiskSpace
        self._uptimeReader = uptimeReader or readSystemUptimeSeconds
        self._clock = clock or time.monotonic
        self._wallClockIso = wallClockIso or _wallClockIso
        self._fastIntervalS = fastIntervalS
        self._diskIntervalS = diskIntervalS
        self._lock = threading.Lock()
        self._cpuTempC: float | None = None
        self._cpuTempTs: str | None = None
        self._throttled: ThrottledReading | None = None
        self._throttledTs: str | None = None
        self._disk: DiskSpaceState | None = None
        self._diskTs: str | None = None
        self._fastReadS: float | None = None
        self._diskReadS: float | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the sampling loop on a daemon thread."""
        self.thread = threading.Thread(
            target=self.run, name="pi-health-sampler", daemon=True
        )
        self.thread.start()

    def run(self) -> None:
        """Read whatever is due, then wait the fast cadence, until stopped."""
        while not self._stopEvent.is_set():
            self.sampleDue()
            if self._stopEvent.wait(self._fastIntervalS):
                return

    def sampleDue(self) -> None:
        """Take every read whose cadence has elapsed (the first call takes all)."""
        nowS = float(self._clock())
        if self._fastReadS is None or nowS - self._fastReadS >= self._fastIntervalS:
            self._fastReadS = nowS
            self._readFast()
        if self._diskReadS is None or nowS - self._diskReadS >= self._diskIntervalS:
            self._diskReadS = nowS
            self._readDisk()

    def snapshot(self) -> dict[str, Any]:
        """The ``pi`` block now: cached reads + uptime read on this call.

        Before the first read lands the block is every key null (Atlas P2):
        the sampler has not looked yet.
        """
        with self._lock:
            if self._cpuTempTs is None and self._diskTs is None:
                return unreadPiHealth()
        uptimeTs = self._wallClockIso()
        try:
            uptimeS = self._uptimeReader()
        except Exception as e:  # noqa: BLE001 -- unread, never a guess
            logger.debug("pi health: uptime read raised: %s", e)
            uptimeS = None
        with self._lock:
            return buildPiHealthBlock(
                cpuTempC=self._cpuTempC,
                cpuTempTs=self._cpuTempTs,
                cpuTempLimitC=self._cpuTempLimitC,
                throttled=self._throttled,
                throttledTs=self._throttledTs,
                disk=self._disk,
                diskTs=self._diskTs,
                uptimeS=uptimeS,
                uptimeTs=uptimeTs,
            )

    def _readFast(self) -> None:
        tempTs = self._wallClockIso()
        try:
            temp = self._tempReader()
        except Exception as e:  # noqa: BLE001 -- a probe must never raise
            logger.debug("pi health: temp read raised: %s", e)
            temp = None
        throttledTs = self._wallClockIso()
        try:
            throttled = self._throttledReader()
        except Exception as e:  # noqa: BLE001 -- a probe must never raise
            logger.debug("pi health: throttle read raised: %s", e)
            throttled = None
        with self._lock:
            self._cpuTempC, self._cpuTempTs = temp, tempTs
            self._throttled, self._throttledTs = throttled, throttledTs

    def _readDisk(self) -> None:
        diskTs = self._wallClockIso()
        try:
            disk: DiskSpaceState | None = self._diskReader()
        except Exception as e:  # noqa: BLE001 -- the guard should not raise; if it does, null
            logger.debug("pi health: disk read raised: %s", e)
            disk = None
        with self._lock:
            self._disk, self._diskTs = disk, diskTs
