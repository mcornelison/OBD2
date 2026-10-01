################################################################################
# File Name: test_sync_home_gate.py
# Purpose/Description: US-776-c -- the shutdown sync asks the home detector
#                      first. A positive AWAY skips at once (no runSync, no
#                      sleep); AT_HOME_* drains; UNKNOWN (a dead SSID or IP
#                      reader without a positive AWAY) drains as
#                      UNKNOWN_NETWORK at WARNING. Drives the REAL detector
#                      with faked readers for the three-way IP rows.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-01    | Rex          | Initial -- US-776-c home-gated drain.
# 2026-10-01    | Rex          | US-776-d: AWAY / DELIVERED kinds; the AWAY skip
#               |              | writes one record.
# ================================================================================
################################################################################
"""US-776-c: away the shutdown powers off at once; at home it drains."""

from __future__ import annotations

import logging
import time
import urllib.error
from collections.abc import Callable

import pytest

from src.pi.network.home_detector import HomeNetworkDetector, HomeNetworkState
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.tasks.sync_with_server import SyncWithServerTask

_HOME_SSID = "DeathStarWiFi"
_HOME_IP = "10.27.27.28"
_FOREIGN_IP = "192.168.1.42"
_LOGGER = "src.pi.power.power_watch.tasks.sync_with_server"


class _FakeClock:
    """Monotonic fake that only moves when something sleeps on it."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _Response:
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _config() -> dict:
    return {
        "pi": {
            "homeNetwork": {
                "ssid": _HOME_SSID,
                "subnet": "10.27.27.0/24",
                "pingTimeoutSeconds": 3,
                "serverPingPath": "/api/v1/health",
            },
            "companionService": {"baseUrl": "http://10.27.27.10:8000"},
        },
    }


def _detector(
    ssid: str | None,
    ips: list[str] | None,
    *,
    serverUp: bool = True,
) -> HomeNetworkDetector:
    """The REAL detector with its three readers faked."""

    def opener(_req: object, timeout: float) -> _Response:
        if not serverUp:
            raise urllib.error.URLError("connection refused")
        return _Response()

    return HomeNetworkDetector(
        _config(),
        ssidReader=lambda: ssid,
        ipReader=lambda: ips,
        httpOpener=opener,
        apiKey="test-key",
    )


def _task(
    homeState: Callable[[], HomeNetworkState],
    syncCalls: list[str],
) -> SyncWithServerTask:
    return SyncWithServerTask(
        homeState=homeState,
        runSync=lambda: syncCalls.append("sync"),
        writeRecord=lambda _kd: None,
        ceilingSec=60.0,
    )


@pytest.fixture
def fakeClock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    """Any sleep or clock read on the task path goes through the fake."""
    clock = _FakeClock()
    monkeypatch.setattr(time, "sleep", clock.sleep)
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    return clock


# =============================================================================
# AWAY -- no runSync, no sleep
# =============================================================================


class TestAwaySkipsAtOnce:

    def test_away_runSyncNeverCalled_noSleep_underOneSecond(
        self, fakeClock: _FakeClock,
    ) -> None:
        """
        Given: the detector reads AWAY
        When: run() is called
        Then: runSync is never called, nothing sleeps, and the fake clock
            shows under 1 s elapsed
        """
        # Arrange
        calls: list[str] = []
        task = _task(lambda: HomeNetworkState.AWAY, calls)
        start = fakeClock.monotonic()

        # Act
        result = task.run()

        # Assert
        assert calls == []
        assert fakeClock.sleeps == []
        assert fakeClock.monotonic() - start < 1.0
        assert result == OutcomeKind.AWAY

    def test_away_makesNoHttpCall(self) -> None:
        """A foreign SSID never reaches the server probe (nothing to block on)."""
        httpCalls: list[object] = []
        detector = HomeNetworkDetector(
            _config(),
            ssidReader=lambda: "CoffeeShopWiFi",
            ipReader=lambda: [_HOME_IP],
            httpOpener=lambda req, timeout: httpCalls.append(req),
            apiKey="test-key",
        )
        calls: list[str] = []

        _task(detector.getHomeNetworkState, calls).run()

        assert httpCalls == []
        assert calls == []

    def test_away_writesOneAwayRecord(self) -> None:
        """US-776-d: the skip is recorded -- a silent skip is how an
        always-false check read as an absent server for weeks."""
        records: list[object] = []
        task = SyncWithServerTask(
            homeState=lambda: HomeNetworkState.AWAY,
            runSync=lambda: None,
            writeRecord=records.append,
            ceilingSec=60.0,
        )

        task.run()

        assert [r[0] for r in records] == [OutcomeKind.AWAY]


# =============================================================================
# The drain decision table, through the REAL detector
# =============================================================================


@pytest.mark.parametrize(
    ("ssid", "ips", "drains", "unknownNetwork"),
    [
        # Home SSID + home IP: at home.
        (_HOME_SSID, [_HOME_IP], True, False),
        # Dead SSID reader + home IP: Atlas gap 2 -- drain, UNKNOWN_NETWORK.
        (None, [_HOME_IP], True, True),
        # Home SSID + FAILED IP read: never a positive AWAY.
        (_HOME_SSID, None, True, True),
        # Dead SSID reader + FAILED IP read: both instruments dead, drain.
        (None, None, True, True),
        # Positive AWAY: a successful IP read with no home-subnet address.
        (_HOME_SSID, [_FOREIGN_IP], False, False),
        (None, [_FOREIGN_IP], False, False),
        (None, [], False, False),
        # Positive AWAY: a foreign SSID, whatever the IP read returns.
        ("CoffeeShopWiFi", [_HOME_IP], False, False),
        ("CoffeeShopWiFi", None, False, False),
        ("CoffeeShopWiFi", [], False, False),
    ],
    ids=[
        "homeSsid-homeIp",
        "noneSsid-homeIp",
        "homeSsid-failedIpRead",
        "noneSsid-failedIpRead",
        "homeSsid-foreignIp",
        "noneSsid-foreignIp",
        "noneSsid-noAddresses",
        "foreignSsid-homeIp",
        "foreignSsid-failedIpRead",
        "foreignSsid-noAddresses",
    ],
)
def test_drainDecision_throughRealDetector(
    ssid: str | None,
    ips: list[str] | None,
    drains: bool,
    unknownNetwork: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: the real detector with faked SSID and IP readers
    When: the sync task runs
    Then: it drains exactly when there is no positive AWAY, and a drain on
        an unconfirmed network logs UNKNOWN_NETWORK at WARNING
    """
    # Arrange
    caplog.set_level(logging.INFO, logger=_LOGGER)
    calls: list[str] = []
    task = _task(_detector(ssid, ips).getHomeNetworkState, calls)

    # Act
    task.run()

    # Assert
    assert calls == (["sync"] if drains else [])
    unknownWarnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "UNKNOWN_NETWORK" in r.getMessage()
    ]
    assert len(unknownWarnings) == (1 if unknownNetwork else 0)


class TestUnknownDrains:

    def test_ssidReaderNone_homeIp_runSyncCalled_unknownNetworkWarning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Given: the SSID reader returns None and a local IP is in the home subnet
        When: the sync task runs
        Then: runSync IS called and UNKNOWN_NETWORK is logged at WARNING
        """
        # Arrange
        caplog.set_level(logging.INFO, logger=_LOGGER)
        calls: list[str] = []
        detector = _detector(None, [_HOME_IP])
        assert detector.getHomeNetworkState() == HomeNetworkState.UNKNOWN

        # Act
        result = _task(detector.getHomeNetworkState, calls).run()

        # Assert
        assert calls == ["sync"]
        assert result == OutcomeKind.DELIVERED
        warnings = [r for r in caplog.records if "UNKNOWN_NETWORK" in r.getMessage()]
        assert [r.levelno for r in warnings] == [logging.WARNING]

    def test_detectorRaises_drainsAsUnknownNetwork_neverRaises(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A detector that raises is a dead instrument: it must not disable the drain."""
        caplog.set_level(logging.INFO, logger=_LOGGER)
        calls: list[str] = []

        def broken() -> HomeNetworkState:
            raise RuntimeError("detector exploded")

        _task(broken, calls).run()

        assert calls == ["sync"]
        assert any(
            r.levelno == logging.WARNING and "UNKNOWN_NETWORK" in r.getMessage()
            for r in caplog.records
        )


class TestAtHomeDrains:

    def test_atHomeServerDown_stillDrains(self) -> None:
        """At home the task drains even when the probe failed (US-776-g retries)."""
        calls: list[str] = []
        detector = _detector(_HOME_SSID, [_HOME_IP], serverUp=False)
        assert detector.getHomeNetworkState() == HomeNetworkState.AT_HOME_SERVER_DOWN

        _task(detector.getHomeNetworkState, calls).run()

        assert calls == ["sync"]

    def test_atHomeReachable_noUnknownNetworkWarning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.INFO, logger=_LOGGER)
        calls: list[str] = []

        _task(lambda: HomeNetworkState.AT_HOME_SERVER_REACHABLE, calls).run()

        assert calls == ["sync"]
        assert not [r for r in caplog.records if "UNKNOWN_NETWORK" in r.getMessage()]

    def test_homeStateReadOncePerRun(self) -> None:
        reads: list[int] = []

        def homeState() -> HomeNetworkState:
            reads.append(1)
            return HomeNetworkState.AT_HOME_SERVER_REACHABLE

        _task(homeState, []).run()

        assert len(reads) == 1

