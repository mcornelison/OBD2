################################################################################
# File Name: test_wifi_reader.py
# Purpose/Description: US-732 -- the ONE WiFi OS read (nmcli cached list for
#   wlan0 + /proc/net/wireless), its typed nmcli outcome beside powerwatch's
#   unchanged reader, and the off-tick sampler that asks the home detector
#   about the same read.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-22    | Rex (US-732) | Initial
# ================================================================================
################################################################################

"""Tests for ``src.pi.network.wifi_reader`` and the typed nmcli read."""

from __future__ import annotations

import subprocess
import threading
from unittest.mock import patch

import pytest

from src.pi.network import home_detector
from src.pi.network.home_detector import (
    HomeNetworkDetector,
    WifiRowsOutcome,
    WifiRowsRead,
    readWifiRows,
)
from src.pi.network.wifi_reader import (
    WIFI_INTERFACE,
    WIFI_REASON_NMCLI_ABSENT,
    WIFI_REASON_READ_FAILED,
    WIFI_SAMPLE_INTERVAL_S,
    WifiLinkSampler,
    WifiReading,
    parseProcNetWireless,
    readRssiDbm,
    readWifiLink,
    ssidForHomeDetector,
)

_RUN = "src.pi.network.home_detector.subprocess.run"
_HOME = "DeathStarWiFi"
_PROC_WIRELESS = (
    "Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n"
    " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n"
    " wlan0: 0000   50.  -50.  -256        0      0      0      0      0        0\n"
)


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["nmcli"], returncode=returncode,
                                       stdout=stdout, stderr="")


def _rows(*rows: tuple[str, str]) -> WifiRowsRead:
    return WifiRowsRead(WifiRowsOutcome.ROWS, tuple(rows), 0)


def _config() -> dict:
    return {"pi": {"homeNetwork": {"ssid": _HOME, "subnet": "10.27.27.0/24"}}}


# =============================================================================
# The typed nmcli outcome, pinned beside powerwatch's reader (Atlas W2)
# =============================================================================


@pytest.mark.parametrize(
    ("runKwargs", "outcome", "powerwatchRows", "powerwatchSsid"),
    [
        ({"return_value": _completed("no:Cafe\nyes:Home\n")},
         WifiRowsOutcome.ROWS, [("no", "Cafe"), ("yes", "Home")], "Home"),
        ({"return_value": _completed("no:Cafe\n")},
         WifiRowsOutcome.ROWS, [("no", "Cafe")], ""),
        ({"side_effect": FileNotFoundError("nmcli")},
         WifiRowsOutcome.TOOL_ABSENT, None, None),
        ({"side_effect": subprocess.TimeoutExpired(cmd="nmcli", timeout=2.0)},
         WifiRowsOutcome.READ_FAILED, None, None),
        ({"side_effect": OSError("exec format error")},
         WifiRowsOutcome.READ_FAILED, None, None),
        ({"return_value": _completed("", returncode=8)},
         WifiRowsOutcome.READ_FAILED, [], ""),
    ],
    ids=["associated", "unassociated", "tool-absent", "timeout", "os-error", "non-zero-exit"],
)
def test_bothReaders_oneNmcliCondition_typedOutcome_andPowerwatchUnchanged(
    runKwargs, outcome, powerwatchRows, powerwatchSsid
):
    """W2: ONE table pins both readers. The typed read tells a missing tool
    from a failed read (a non-zero exit included); powerwatch's reader keeps
    today's None / [] and its SSID reader today's None / ""."""
    with patch(_RUN, **runKwargs):
        typed = readWifiRows(ifname=WIFI_INTERFACE)
        legacyRows = home_detector._listWifiRows(2.0)
        legacySsid = home_detector._readSsidViaNmcli()

    assert typed.outcome is outcome
    assert legacyRows == powerwatchRows
    assert legacySsid == powerwatchSsid


def test_readWifiRows_ifname_filtersToWlan0_andNeverRescans():
    """W7 + W1: the provider's list is filtered to wlan0 and always carries
    --rescan no (the rescan measured 4.1 s)."""
    with patch(_RUN, return_value=_completed("")) as run:
        readWifiRows(ifname=WIFI_INTERFACE)
    argv = run.call_args.args[0]
    assert argv[:7] == ["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi", "list"]
    assert argv[argv.index("ifname") + 1] == "wlan0"
    assert argv[argv.index("--rescan") + 1] == "no"
    assert run.call_args.kwargs["encoding"] == "utf-8"
    assert 0 < run.call_args.kwargs["timeout"] <= 2.0


def test_powerwatchReader_commandUnchanged_noIfname():
    """Powerwatch's home read is untouched: no interface filter."""
    with patch(_RUN, return_value=_completed("")) as run:
        home_detector._listWifiRows(2.0)
    assert run.call_args.args[0] == [
        "nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi", "list", "--rescan", "no",
    ]


# =============================================================================
# /proc/net/wireless
# =============================================================================


def test_parseProcNetWireless_storyExample_isMinus50():
    assert parseProcNetWireless(_PROC_WIRELESS) == -50


@pytest.mark.parametrize("text", [
    "Inter-| sta-|\n face | tus |\n",                       # no wlan0 line
    " wlan1: 0000   50.  -50.  -256 0 0 0 0 0 0\n",          # another interface
    " wlan0: 0000   50.  206.  0 0 0 0 0 0 0\n",             # relative scale, not dBm
    " wlan0: 0000   50.\n",                                  # truncated line
    " wlan0: 0000   50.  abc.  -256 0 0 0 0 0 0\n",          # garbage
])
def test_parseProcNetWireless_noUsableLevel_isNone(text):
    assert parseProcNetWireless(text) is None


def test_readRssiDbm_missingFile_isNone(tmp_path):
    assert readRssiDbm(str(tmp_path / "absent")) is None


def test_readRssiDbm_readsTheFile(tmp_path):
    path = tmp_path / "wireless"
    path.write_text(_PROC_WIRELESS, encoding="utf-8")
    assert readRssiDbm(str(path)) == -50


# =============================================================================
# readWifiLink -- the one OS read
# =============================================================================


def test_readWifiLink_associatedHome_ssidAndRssi():
    reading = readWifiLink(rowsReader=lambda: _rows(("no", "Cafe"), ("yes", _HOME)),
                           rssiReader=lambda: -50)
    assert reading == WifiReading(associated=True, ssid=_HOME, rssiDbm=-50, reason=None)
    assert reading.available


def test_readWifiLink_associatedOther_isAssociated():
    reading = readWifiLink(rowsReader=lambda: _rows(("yes", "CoffeeShop")),
                           rssiReader=lambda: -61)
    assert reading == WifiReading(associated=True, ssid="CoffeeShop", rssiDbm=-61,
                                  reason=None)


def test_readWifiLink_unassociated_isAMeasurement_noReason_noRssi():
    """W3: not associated is read (reason null); /proc is not consulted."""
    rssiCalls = []
    reading = readWifiLink(rowsReader=lambda: _rows(("no", _HOME)),
                           rssiReader=lambda: rssiCalls.append(1) or -40)
    assert reading == WifiReading(associated=False, ssid=None, rssiDbm=None, reason=None)
    assert reading.available
    assert rssiCalls == []


def test_readWifiLink_emptySsidOnTheActiveRow_isNotAssociated():
    reading = readWifiLink(rowsReader=lambda: _rows(("yes", "")), rssiReader=lambda: -50)
    assert reading.associated is False
    assert reading.ssid is None


def test_readWifiLink_nmcliMissing_allNull_nmcliAbsent_procNeverDecides():
    """732-3: with nmcli absent /proc alone never decides."""
    rssiCalls = []
    reading = readWifiLink(
        rowsReader=lambda: WifiRowsRead(WifiRowsOutcome.TOOL_ABSENT),
        rssiReader=lambda: rssiCalls.append(1) or -50,
    )
    assert reading == WifiReading(associated=None, ssid=None, rssiDbm=None,
                                  reason=WIFI_REASON_NMCLI_ABSENT)
    assert not reading.available
    assert rssiCalls == []


def test_readWifiLink_nonZeroExit_isReadFailed_neverDown():
    reading = readWifiLink(
        rowsReader=lambda: WifiRowsRead(WifiRowsOutcome.READ_FAILED, returncode=8),
        rssiReader=lambda: -50,
    )
    assert reading.associated is None
    assert reading.reason == WIFI_REASON_READ_FAILED


def test_readWifiLink_procFileMissing_associatedWithNullRssi(tmp_path):
    reading = readWifiLink(rowsReader=lambda: _rows(("yes", _HOME)),
                           rssiReader=lambda: readRssiDbm(str(tmp_path / "absent")))
    assert reading == WifiReading(associated=True, ssid=_HOME, rssiDbm=None, reason=None)


def test_readWifiLink_defaults_runOneNmcliForWlan0_withRescanNo():
    """The default read is ONE nmcli call, filtered to wlan0, never a rescan."""
    with patch(_RUN, side_effect=FileNotFoundError("nmcli")) as run:
        reading = readWifiLink()
    assert reading.reason == WIFI_REASON_NMCLI_ABSENT
    assert run.call_count == 1
    argv = run.call_args.args[0]
    assert "ifname" in argv and argv[argv.index("--rescan") + 1] == "no"


@pytest.mark.parametrize(("reading", "expected"), [
    (None, None),
    (WifiReading(None, None, None, WIFI_REASON_READ_FAILED), None),
    (WifiReading(False, None, None, None), ""),
    (WifiReading(True, _HOME, -50, None), _HOME),
])
def test_ssidForHomeDetector_adaptsToTheSsidReaderContract(reading, expected):
    assert ssidForHomeDetector(reading) == expected


# =============================================================================
# WifiLinkSampler -- off the tick, home from the same read
# =============================================================================


class _Event:
    """A stop event that never waits (sampleOnce tests never run the loop)."""

    def is_set(self) -> bool:
        return False

    def wait(self, timeout: float | None = None) -> bool:
        return True


def _sampler(reading: WifiReading, homeCheck=None) -> WifiLinkSampler:
    return WifiLinkSampler(stopEvent=_Event(), reader=lambda: reading,
                           homeCheck=homeCheck, clock=lambda: 7.0,
                           wallClockIso=lambda: "2026-10-22T12:00:00Z")


def _detectorFor(sampler: WifiLinkSampler, ips: list[str] | None) -> HomeNetworkDetector:
    return HomeNetworkDetector(_config(), ssidReader=sampler.judgedSsid,
                               ipReader=lambda: ips)


@pytest.mark.parametrize(("reading", "ips", "home"), [
    (WifiReading(True, _HOME, -50, None), ["10.27.27.124"], True),
    (WifiReading(True, "deathstarwifi", -50, None), ["10.27.27.124"], True),
    (WifiReading(True, "CoffeeShop", -50, None), ["10.27.27.124"], False),
    (WifiReading(True, _HOME, -50, None), ["192.168.1.9"], False),
    (WifiReading(False, None, None, None), ["10.27.27.124"], False),
], ids=["associated-home", "home-casefold", "associated-other", "home-ssid-other-subnet",
        "unassociated"])
def test_sampler_home_isTheDetectorsAnswer_aboutTheSameRead(reading, ips, home):
    """W2: home = isAtHomeWifi(), the ARCH-065 one owner, judging the read
    the sampler just took."""
    sampler = _sampler(reading)
    sampler.homeCheck = _detectorFor(sampler, ips).isAtHomeWifi

    sample = sampler.sampleOnce()

    assert sample.home is home
    assert sample.reading is reading
    assert sample.ts == "2026-10-22T12:00:00Z"
    assert sampler.latest() is sample


@pytest.mark.parametrize("reason", [WIFI_REASON_NMCLI_ABSENT, WIFI_REASON_READ_FAILED])
def test_sampler_notRead_homeIsNull_andTheDetectorIsNeverAsked(reason):
    asked = []
    sampler = _sampler(WifiReading(None, None, None, reason),
                       homeCheck=lambda: asked.append(1) or True)
    sample = sampler.sampleOnce()
    assert sample.home is None
    assert asked == []


def test_sampler_noHomeCheck_homeIsNull():
    assert _sampler(WifiReading(True, _HOME, -50, None)).sampleOnce().home is None


def test_sampler_raisingReader_isReadFailed_neverRaises():
    def boom() -> WifiReading:
        raise RuntimeError("driver gone")

    sampler = WifiLinkSampler(stopEvent=_Event(), reader=boom,
                              wallClockIso=lambda: "2026-10-22T12:00:00Z")
    sample = sampler.sampleOnce()
    assert sample.reading.reason == WIFI_REASON_READ_FAILED
    assert sample.home is None


def test_sampler_raisingHomeCheck_homeIsNull():
    def boom() -> bool:
        raise RuntimeError("hostname wedged")

    sampler = _sampler(WifiReading(True, _HOME, -50, None), homeCheck=boom)
    assert sampler.sampleOnce().home is None


def test_sampler_realReads_oneNmcliAndOneHostnamePerSample_noDuplicate(tmp_path):
    """732-6: a sample costs ONE nmcli (the detector reads the same row) and
    the detector's own single hostname -I -- never a second of either."""
    calls: list[str] = []

    def fakeRun(argv, **kwargs):
        calls.append(argv[0])
        if argv[0] == "nmcli":
            return _completed(f"yes:{_HOME}\n")
        return subprocess.CompletedProcess(argv, 0, stdout="10.27.27.124\n", stderr="")

    sampler = WifiLinkSampler(
        stopEvent=_Event(),
        reader=lambda: readWifiLink(rssiReader=lambda: -50),
        wallClockIso=lambda: "2026-10-22T12:00:00Z",
    )
    with patch(_RUN, side_effect=fakeRun):
        sampler.homeCheck = HomeNetworkDetector(
            _config(), ssidReader=sampler.judgedSsid
        ).isAtHomeWifi
        sample = sampler.sampleOnce()

    assert sample.home is True
    assert sample.reading.rssiDbm == -50
    assert calls == ["nmcli", "hostname"]


def test_sampler_thread_samplesThenStopsOnTheEvent():
    """The loop samples on its own daemon thread and exits on the stop event."""
    stop = threading.Event()
    sampled = threading.Event()

    def reader() -> WifiReading:
        sampled.set()
        return WifiReading(False, None, None, None)

    sampler = WifiLinkSampler(stopEvent=stop, reader=reader)
    sampler.start()
    try:
        assert sampled.wait(timeout=5.0)
        assert sampler.thread is not None and sampler.thread.daemon
        assert sampler.thread.name == "wifi-link-sampler"
    finally:
        stop.set()
        assert sampler.thread is not None
        sampler.thread.join(timeout=5.0)
    assert not sampler.thread.is_alive()
    assert sampler.latest() is not None


def test_sampleInterval_isThirtySeconds():
    """Atlas W5: every 30 s, as US-916."""
    assert WIFI_SAMPLE_INTERVAL_S == 30.0
