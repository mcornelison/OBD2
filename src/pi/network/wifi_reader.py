################################################################################
# File Name: wifi_reader.py
# Purpose/Description: US-732 -- the ONE OS read of the Pi's WiFi link
#   (associated, ssid, rssiDbm) and the off-tick sampler that feeds
#   system-status `wifi`. SSID and association from NetworkManager's CACHED
#   AP list (home_detector.readWifiRows, --rescan no, ifname wlan0); signal
#   from /proc/net/wireless. Read-only: the Pi observes its link, it never
#   manages it.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-22    | Rex (US-732) | Initial: readWifiLink + WifiLinkSampler (Atlas
#               |              | W1/W2/W5/W6/W7, 732-3/732-5/732-6)
# ================================================================================
################################################################################

"""The Pi's WiFi link, read once and sampled off the system-status tick.

:func:`readWifiLink` is reusable as-is (powerwatch may adopt it later). Its
answer is three facts plus why they are missing:

* ``associated`` -- nmcli lists an ``ACTIVE=yes`` row with a non-empty SSID
  for wlan0. nmcli decides it ALONE: with nmcli absent, /proc never decides
  (Atlas 732-3), because a /proc line exists for an unassociated interface.
* ``ssid`` -- that row's SSID, None when not associated.
* ``rssiDbm`` -- /proc/net/wireless ``level`` for wlan0, read only while
  associated; None when the file or the line is missing.
* ``reason`` -- ``nmcli_absent`` (the dev box: no tool, not a fault) or
  ``read_failed`` (timeout, OS error, non-zero exit), else None. Not
  associated is a MEASUREMENT (reason None), never a reason (Atlas W3).

Never run ``nmcli dev wifi`` without ``--rescan no``: the rescan measured
4.1 s on the Pi (Atlas W1).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from src.pi.network.home_detector import WifiRowsOutcome, WifiRowsRead, readWifiRows

__all__ = [
    "PROC_NET_WIRELESS_PATH",
    "WIFI_INTERFACE",
    "WIFI_REASON_NMCLI_ABSENT",
    "WIFI_REASON_READ_FAILED",
    "WIFI_SAMPLE_INTERVAL_S",
    "WifiLinkSampler",
    "WifiReading",
    "WifiSample",
    "parseProcNetWireless",
    "readRssiDbm",
    "readWifiLink",
    "ssidForHomeDetector",
]

logger = logging.getLogger(__name__)

#: The Pi's WiFi interface (Atlas W7: the nmcli list is filtered to it).
WIFI_INTERFACE = "wlan0"

#: The kernel's wireless-extensions table: one line per interface.
PROC_NET_WIRELESS_PATH = "/proc/net/wireless"

#: Seconds between samples (Atlas W5: every 30 s, as US-916; never on the tick).
WIFI_SAMPLE_INTERVAL_S = 30.0

#: nmcli is not installed -- the dev box. Kept apart from a failed read so a
#: dev box never counts an issue (Iris, 2026-10-19).
WIFI_REASON_NMCLI_ABSENT = "nmcli_absent"

#: nmcli ran and gave no answer: timeout, OS error, or a non-zero exit (Atlas
#: W2: "we could not look" -- null, never down).
WIFI_REASON_READ_FAILED = "read_failed"


@dataclass(frozen=True)
class WifiReading:
    """One read of the WiFi link (US-732).

    Attributes:
        associated: True / False from nmcli, None when not read.
        ssid: The associated SSID, None when not associated or not read.
        rssiDbm: wlan0's signal level in dBm, None when not associated or
            ungradeable (no /proc file, no wlan0 line, no dBm value).
        reason: ``WIFI_REASON_NMCLI_ABSENT`` / ``WIFI_REASON_READ_FAILED``
            when not read, else None.
    """

    associated: bool | None
    ssid: str | None
    rssiDbm: int | None
    reason: str | None

    @property
    def available(self) -> bool:
        """Whether the link was read (``source.wifi.available``)."""
        return self.reason is None


def _unread(reason: str) -> WifiReading:
    return WifiReading(associated=None, ssid=None, rssiDbm=None, reason=reason)


def parseProcNetWireless(text: str, interface: str = WIFI_INTERFACE) -> int | None:
    """Parse ``interface``'s signal level from /proc/net/wireless text.

    The line reads ``wlan0: 0000   50.  -50.  -256 ...`` -- status, link
    quality, level, noise. ``level`` is dBm when negative; a non-negative
    level is a driver reporting a relative scale, which is not dBm, so it is
    not converted into one.

    Args:
        text: The file's contents.
        interface: The interface whose line to read.

    Returns:
        The level in whole dBm, or None when the line is missing or the
        level is not a negative number.
    """
    prefix = f"{interface}:"
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        fields = stripped[len(prefix):].split()
        if len(fields) < 3:
            return None
        try:
            level = float(fields[2].rstrip("."))
        except ValueError:
            return None
        return int(level) if level < 0 else None
    return None


def readRssiDbm(
    path: str = PROC_NET_WIRELESS_PATH, interface: str = WIFI_INTERFACE
) -> int | None:
    """Read ``interface``'s signal level from /proc/net/wireless (2 ms, W1).

    Returns:
        The level in dBm, or None when the file cannot be read (the dev box)
        or carries no usable line.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    return parseProcNetWireless(text, interface)


def readWifiLink(
    *,
    rowsReader: Callable[[], WifiRowsRead] | None = None,
    rssiReader: Callable[[], int | None] | None = None,
) -> WifiReading:
    """Read the WiFi link once: nmcli association + /proc signal (US-732).

    Never raises.

    Args:
        rowsReader: Returns the typed cached nmcli list for wlan0; defaults
            to :func:`readWifiRows` with ``ifname=wlan0``.
        rssiReader: Returns wlan0's level in dBm or None; defaults to
            :func:`readRssiDbm`.

    Returns:
        A :class:`WifiReading`.
    """
    readRows = rowsReader or (lambda: readWifiRows(ifname=WIFI_INTERFACE))
    readRssi = rssiReader or readRssiDbm
    rows = readRows()
    if rows.outcome is WifiRowsOutcome.TOOL_ABSENT:
        return _unread(WIFI_REASON_NMCLI_ABSENT)
    if rows.outcome is not WifiRowsOutcome.ROWS:
        return _unread(WIFI_REASON_READ_FAILED)
    # An ACTIVE row with an empty SSID names no network: not associated.
    ssid = next((s for active, s in rows.rows if active == "yes" and s), None)
    if ssid is None:
        return WifiReading(associated=False, ssid=None, rssiDbm=None, reason=None)
    return WifiReading(associated=True, ssid=ssid, rssiDbm=readRssi(), reason=None)


def ssidForHomeDetector(reading: WifiReading | None) -> str | None:
    """Adapt a reading to ``HomeNetworkDetector``'s ssidReader contract.

    Returns:
        None when not read, ``""`` when not associated, else the SSID.
    """
    if reading is None or not reading.available:
        return None
    return reading.ssid if reading.associated else ""


@dataclass(frozen=True)
class WifiSample:
    """One WiFi sample (US-732).

    Attributes:
        reading: The :func:`readWifiLink` result.
        home: ``isAtHomeWifi()`` for this reading, None when it was not read
            (or the home check could not answer).
        ts: Canonical-UTC time the sample was read (``wifi.ts``, Atlas W6).
        monoS: Monotonic seconds at the sample.
    """

    reading: WifiReading
    home: bool | None
    ts: str
    monoS: float


class _StopEvent(Protocol):
    """The slice of :class:`threading.Event` the sampler waits on."""

    def is_set(self) -> bool:
        ...

    def wait(self, timeout: float | None = None) -> bool:
        ...


def _wallClockIso() -> str:
    """Aware UTC now as canonical ISO -- the default sample stamp."""
    from datetime import UTC, datetime

    from src.common.time.helper import toCanonicalIso

    return toCanonicalIso(datetime.now(UTC))


class WifiLinkSampler:
    """Samples :func:`readWifiLink` every 30 s on its own daemon thread.

    The system-status tick only reads :meth:`latest`, so no subprocess runs
    on the tick (Atlas W5; the US-876-e BT sampler's pattern). After each
    read the sampler asks ``homeCheck`` -- ``HomeNetworkDetector.
    isAtHomeWifi``, the ARCH-065 one owner -- whose ssidReader is
    :meth:`judgedSsid`, i.e. the SAME read: no second nmcli call (732-6).
    """

    def __init__(
        self,
        *,
        stopEvent: _StopEvent,
        reader: Callable[[], WifiReading] | None = None,
        homeCheck: Callable[[], bool] | None = None,
        clock: Callable[[], float] | None = None,
        wallClockIso: Callable[[], str] | None = None,
        intervalS: float = WIFI_SAMPLE_INTERVAL_S,
    ) -> None:
        """
        Args:
            stopEvent: Set to stop the loop (the orchestrator's _shutdownEvent).
            reader: The link read; defaults to :func:`readWifiLink`.
            homeCheck: Answers "home WiFi seen" for the reading being judged;
                None publishes home null.
            clock: Monotonic seconds; defaults to :func:`time.monotonic`.
            wallClockIso: Canonical-UTC now; defaults to the system clock.
            intervalS: Seconds between samples.
        """
        self._stopEvent = stopEvent
        self._reader = reader or readWifiLink
        self.homeCheck = homeCheck
        self._clock = clock or time.monotonic
        self._wallClockIso = wallClockIso or _wallClockIso
        self._intervalS = intervalS
        self._lock = threading.Lock()
        self._latest: WifiSample | None = None
        self._judged: WifiReading | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the sampling loop on a daemon thread."""
        self.thread = threading.Thread(
            target=self.run, name="wifi-link-sampler", daemon=True
        )
        self.thread.start()

    def run(self) -> None:
        """Sample, then wait the cadence, until the stop event is set."""
        while not self._stopEvent.is_set():
            self.sampleOnce()
            if self._stopEvent.wait(self._intervalS):
                return

    def sampleOnce(self) -> WifiSample:
        """Take one sample now and make it the latest.

        Returns:
            The sample just taken.
        """
        ts = self._wallClockIso()
        monoS = float(self._clock())
        try:
            reading = self._reader()
        except Exception as exc:  # noqa: BLE001 -- a link probe must never raise
            logger.debug("wifi read raised: %s", exc)
            reading = _unread(WIFI_REASON_READ_FAILED)
        self._judged = reading
        sample = WifiSample(
            reading=reading, home=self._judgeHome(reading), ts=ts, monoS=monoS
        )
        with self._lock:
            self._latest = sample
        return sample

    def judgedSsid(self) -> str | None:
        """The ssidReader for the home check: the reading being judged."""
        return ssidForHomeDetector(self._judged)

    def latest(self) -> WifiSample | None:
        """The most recent sample, or None before the first."""
        with self._lock:
            return self._latest

    def _judgeHome(self, reading: WifiReading) -> bool | None:
        # Not read -> null: the detector's bool is not trusted on a failed read.
        if not reading.available or self.homeCheck is None:
            return None
        try:
            return bool(self.homeCheck())
        except Exception as exc:  # noqa: BLE001 -- unanswered, never a guess
            logger.debug("wifi home check raised: %s", exc)
            return None
