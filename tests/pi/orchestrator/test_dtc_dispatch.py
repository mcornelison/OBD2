################################################################################
# File Name: test_dtc_dispatch.py
# Purpose/Description: Tests for the orchestrator's DTC dispatch hooks --
#                      drive-start fires DtcLogger.logSessionStartDtcs and
#                      MIL_ON rising edges fire logMilEventDtcs (US-204).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-204) | Initial -- orchestrator DTC dispatch coverage.
# ================================================================================
################################################################################

"""Pin the orchestrator-side wiring of US-204 DTC capture.

Two integration points covered here:

1. ``EventRouterMixin._handleDriveStart`` calls
   ``DtcLogger.logSessionStartDtcs`` when the orchestrator owns both a
   live OBD connection and a configured ``_dtcLogger``.

2. ``EventRouterMixin._handleReading`` feeds ``MIL_ON`` observations
   into a ``MilRisingEdgeDetector`` and dispatches
   ``DtcLogger.logMilEventDtcs`` on rising edges.

The tests construct a bare subclass of :class:`EventRouterMixin` so we
exercise the new dispatch logic without having to spin up the full
``ApplicationOrchestrator``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from pi.obdii.orchestrator.event_router import EventRouterMixin
from pi.obdii.orchestrator.types import HealthCheckStats

# ================================================================================
# Bare host: just enough attributes to satisfy EventRouterMixin
# ================================================================================


class _FakeDtcLogger:
    def __init__(self) -> None:
        self.sessionCalls: list[dict[str, Any]] = []
        self.milCalls: list[dict[str, Any]] = []
        self.sessionResult: Any = SimpleNamespace(
            storedCount=0,
            pendingCount=0,
            mode07Probe=SimpleNamespace(supported=True, reason='supported'),
        )
        self.milResult: Any = SimpleNamespace(inserted=0, updated=0)
        self.shouldRaiseSession = False
        self.shouldRaiseMil = False

    def logSessionStartDtcs(self, *, driveId: int | None, connection: Any) -> Any:
        if self.shouldRaiseSession:
            raise RuntimeError("simulated session-start failure")
        self.sessionCalls.append({"driveId": driveId, "connection": connection})
        return self.sessionResult

    def logMilEventDtcs(self, *, driveId: int | None, connection: Any) -> Any:
        if self.shouldRaiseMil:
            raise RuntimeError("simulated mil-event failure")
        self.milCalls.append({"driveId": driveId, "connection": connection})
        return self.milResult


@dataclass
class _Host(EventRouterMixin):
    """Minimal host wiring for EventRouterMixin attributes."""

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
    _healthCheckStats: HealthCheckStats = field(default_factory=HealthCheckStats)
    _dashboardParameters: set[str] = field(default_factory=set)
    _alertsPausedForReconnect: bool = False
    _onDriveStart: Callable[[Any], None] | None = None
    _onDriveEnd: Callable[[Any], None] | None = None
    _onAlert: Callable[[Any], None] | None = None
    _onAnalysisComplete: Callable[[Any], None] | None = None
    _onConnectionLost: Callable[[], None] | None = None
    _onConnectionRestored: Callable[[], None] | None = None


def _newHost(**overrides: Any) -> _Host:
    return _Host(**overrides)


# ================================================================================
# Drive-start dispatch
# ================================================================================


class TestDriveStartDispatch:
    """When a drive starts, fetch session-start DTCs."""

    def test_callsLogSessionStartDtcsWithConnection(self) -> None:
        dtcLogger = _FakeDtcLogger()
        connection = object()
        host = _newHost(_dtcLogger=dtcLogger, _connection=connection)

        host._handleDriveStart(SimpleNamespace(id="drv1"))

        assert len(dtcLogger.sessionCalls) == 1
        assert dtcLogger.sessionCalls[0]["connection"] is connection

    def test_skipsWhenNoDtcLoggerConfigured(self) -> None:
        host = _newHost(_dtcLogger=None, _connection=object())

        host._handleDriveStart(SimpleNamespace(id="drv1"))  # must not raise

    def test_skipsWhenNoConnection(self) -> None:
        dtcLogger = _FakeDtcLogger()
        host = _newHost(_dtcLogger=dtcLogger, _connection=None)

        host._handleDriveStart(SimpleNamespace(id="drv1"))

        assert dtcLogger.sessionCalls == []

    def test_swallowsExceptions(self) -> None:
        """A DTC fetch failure must not blow up the drive-start path."""
        dtcLogger = _FakeDtcLogger()
        dtcLogger.shouldRaiseSession = True
        host = _newHost(_dtcLogger=dtcLogger, _connection=object())

        host._handleDriveStart(SimpleNamespace(id="drv1"))  # must not raise


# ================================================================================
# MIL rising-edge dispatch via _handleReading
# ================================================================================


class TestMilDispatchViaReading:
    """_handleReading watches MIL_ON and fires DTC re-fetch on 0->1."""

    def _milReading(self, value: float) -> SimpleNamespace:
        return SimpleNamespace(parameterName='MIL_ON', value=value, unit='mil')

    def test_zeroDoesNotFire(self) -> None:
        from pi.obdii.mil_edge import MilRisingEdgeDetector

        dtcLogger = _FakeDtcLogger()
        host = _newHost(
            _dtcLogger=dtcLogger,
            _connection=object(),
            _milEdgeDetector=MilRisingEdgeDetector(),
        )

        host._handleReading(self._milReading(0.0))

        assert dtcLogger.milCalls == []

    def test_zeroToOneFiresOnce(self) -> None:
        from pi.obdii.mil_edge import MilRisingEdgeDetector

        dtcLogger = _FakeDtcLogger()
        host = _newHost(
            _dtcLogger=dtcLogger,
            _connection=object(),
            _milEdgeDetector=MilRisingEdgeDetector(),
        )

        host._handleReading(self._milReading(0.0))
        host._handleReading(self._milReading(1.0))
        host._handleReading(self._milReading(1.0))  # sustained -> no extra

        assert len(dtcLogger.milCalls) == 1

    def test_skipsWhenNoEdgeDetector(self) -> None:
        dtcLogger = _FakeDtcLogger()
        host = _newHost(
            _dtcLogger=dtcLogger,
            _connection=object(),
            _milEdgeDetector=None,
        )

        host._handleReading(self._milReading(1.0))  # must not raise
        assert dtcLogger.milCalls == []

    def test_nonMilReadingDoesNotTriggerDispatch(self) -> None:
        from pi.obdii.mil_edge import MilRisingEdgeDetector

        dtcLogger = _FakeDtcLogger()
        host = _newHost(
            _dtcLogger=dtcLogger,
            _connection=object(),
            _milEdgeDetector=MilRisingEdgeDetector(),
        )

        host._handleReading(SimpleNamespace(
            parameterName='RPM', value=2500.0, unit='rpm',
        ))
        assert dtcLogger.milCalls == []

    def test_swallowsMilDispatchFailure(self) -> None:
        from pi.obdii.mil_edge import MilRisingEdgeDetector

        dtcLogger = _FakeDtcLogger()
        dtcLogger.shouldRaiseMil = True
        host = _newHost(
            _dtcLogger=dtcLogger,
            _connection=object(),
            _milEdgeDetector=MilRisingEdgeDetector(),
        )

        host._handleReading(self._milReading(1.0))  # must not raise
