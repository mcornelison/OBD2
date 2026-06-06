################################################################################
# File Name: test_freeze_frame_dispatch.py
# Purpose/Description: Sprint 43 V0.28.0 (US-368 / F-109) -- orchestrator wiring
#                      tests: a MIL_ON 0->1 rising edge fires
#                      FreezeFrameCapture.captureOnMilEvent alongside the US-204
#                      DTC re-fetch.  Sustained MIL stays single-shot; a missing
#                      capture component or a capture failure never crashes the
#                      poll loop.  Bare EventRouterMixin host (no full
#                      orchestrator), mirroring test_dtc_dispatch.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-368) | Initial -- F-109 freeze-frame MIL-edge wiring.
# ================================================================================
################################################################################

"""US-368 / F-109 orchestrator wiring for Mode 02 freeze-frame capture."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from pi.obdii.mil_edge import MilRisingEdgeDetector
from pi.obdii.orchestrator.event_router import EventRouterMixin
from pi.obdii.orchestrator.types import HealthCheckStats


class _FakeDtcLogger:
    def __init__(self) -> None:
        self.milCalls: list[dict[str, Any]] = []

    def logMilEventDtcs(self, *, driveId: int | None, connection: Any) -> Any:
        self.milCalls.append({"driveId": driveId, "connection": connection})
        return SimpleNamespace(inserted=0, updated=0)


class _FakeFreezeFrameCapture:
    def __init__(self, raises: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raises = raises

    def captureOnMilEvent(self, *, connection: Any, dtcLogId: int | None) -> Any:
        if self._raises:
            raise RuntimeError("simulated freeze-frame failure")
        self.calls.append({"connection": connection, "dtcLogId": dtcLogId})
        return SimpleNamespace(rowId=1, pidCount=16, vehicleInfoVin=None, degraded=False)


@dataclass
class _Host(EventRouterMixin):
    _connection: Any | None = None
    _driveDetector: Any | None = None
    _alertManager: Any | None = None
    _statisticsEngine: Any | None = None
    _dataLogger: Any | None = None
    _profileSwitcher: Any | None = None
    _displayManager: Any | None = None
    _hardwareManager: Any | None = None
    _profileManager: Any | None = None
    _dtcLogger: Any | None = None
    _milEdgeDetector: Any | None = None
    _freezeFrameCapture: Any | None = None
    _healthCheckStats: HealthCheckStats = field(default_factory=HealthCheckStats)
    _dashboardParameters: set[str] = field(default_factory=set)
    _alertsPausedForReconnect: bool = False
    _onDriveStart: Callable[[Any], None] | None = None
    _onDriveEnd: Callable[[Any], None] | None = None
    _onAlert: Callable[[Any], None] | None = None
    _onAnalysisComplete: Callable[[Any], None] | None = None
    _onConnectionLost: Callable[[], None] | None = None
    _onConnectionRestored: Callable[[], None] | None = None


def _milReading(value: float) -> SimpleNamespace:
    return SimpleNamespace(parameterName="MIL_ON", value=value, unit="mil")


def _host(**overrides: Any) -> _Host:
    return _Host(**overrides)


class TestFreezeFrameMilDispatch:
    def test_risingEdgeFiresCaptureOnce(self) -> None:
        capture = _FakeFreezeFrameCapture()
        host = _host(
            _dtcLogger=_FakeDtcLogger(),
            _freezeFrameCapture=capture,
            _connection=object(),
            _milEdgeDetector=MilRisingEdgeDetector(),
        )

        host._handleReading(_milReading(0.0))
        host._handleReading(_milReading(1.0))
        host._handleReading(_milReading(1.0))  # sustained -> no extra

        assert len(capture.calls) == 1
        assert capture.calls[0]["dtcLogId"] is None  # capture resolves latest

    def test_zeroDoesNotFire(self) -> None:
        capture = _FakeFreezeFrameCapture()
        host = _host(
            _dtcLogger=_FakeDtcLogger(),
            _freezeFrameCapture=capture,
            _connection=object(),
            _milEdgeDetector=MilRisingEdgeDetector(),
        )
        host._handleReading(_milReading(0.0))
        assert capture.calls == []

    def test_firesAlongsideDtcRefetch(self) -> None:
        dtcLogger = _FakeDtcLogger()
        capture = _FakeFreezeFrameCapture()
        host = _host(
            _dtcLogger=dtcLogger,
            _freezeFrameCapture=capture,
            _connection=object(),
            _milEdgeDetector=MilRisingEdgeDetector(),
        )
        host._handleReading(_milReading(1.0))
        assert len(dtcLogger.milCalls) == 1
        assert len(capture.calls) == 1

    def test_missingCaptureComponentDoesNotCrash(self) -> None:
        host = _host(
            _dtcLogger=_FakeDtcLogger(),
            _freezeFrameCapture=None,
            _connection=object(),
            _milEdgeDetector=MilRisingEdgeDetector(),
        )
        host._handleReading(_milReading(1.0))  # must not raise

    def test_captureFailureSwallowed(self) -> None:
        host = _host(
            _dtcLogger=_FakeDtcLogger(),
            _freezeFrameCapture=_FakeFreezeFrameCapture(raises=True),
            _connection=object(),
            _milEdgeDetector=MilRisingEdgeDetector(),
        )
        host._handleReading(_milReading(1.0))  # must not raise
