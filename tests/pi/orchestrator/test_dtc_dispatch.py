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

import pytest

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


# ================================================================================
# US-897-a1 -- every drive-time Mode 03 read publishes states/dtc
# ================================================================================


def _diag(code: str, status: str) -> SimpleNamespace:
    return SimpleNamespace(code=code, status=status, description="")


class _PublishingDtcLogger:
    """Answers every DTC entry point with a result carrying `codes` + `polled`."""

    def __init__(self) -> None:
        self.keyOnCodes: list[Any] = []
        self.sessionCodes: list[Any] = []
        self.milCodes: list[Any] = []
        self.periodicCodes: list[Any] = []
        self.periodicPolled = True
        self.periodicCalls: list[dict[str, Any]] = []

    def logKeyOnDtcs(self, *, connection: Any) -> Any:
        return SimpleNamespace(
            storedCount=sum(c.status == "stored" for c in self.keyOnCodes),
            pendingCount=sum(c.status == "pending" for c in self.keyOnCodes),
            mode07Probe=SimpleNamespace(supported=True, reason="supported"),
            codes=list(self.keyOnCodes),
        )

    def logSessionStartDtcs(self, *, driveId: int | None, connection: Any) -> Any:
        return SimpleNamespace(
            storedCount=sum(c.status == "stored" for c in self.sessionCodes),
            pendingCount=sum(c.status == "pending" for c in self.sessionCodes),
            mode07Probe=SimpleNamespace(supported=True, reason="supported"),
            codes=list(self.sessionCodes),
            polled=True,
        )

    def logMilEventDtcs(self, *, driveId: int | None, connection: Any) -> Any:
        return SimpleNamespace(
            inserted=len(self.milCodes), updated=0,
            codes=list(self.milCodes), polled=True,
        )

    def maybePeriodicMode03(self, *, driveId: int | None, connection: Any) -> Any:
        self.periodicCalls.append({"driveId": driveId})
        if driveId is None or not self.periodicPolled:
            return SimpleNamespace(inserted=0, updated=0, codes=[], polled=False)
        return SimpleNamespace(
            inserted=len(self.periodicCodes), updated=0,
            codes=list(self.periodicCodes), polled=True,
        )


class _Driving:
    def isDriving(self) -> bool:
        return True


@dataclass
class _EmitHost(_Host):
    _dtcEmitter: Callable[..., None] | None = None


@pytest.fixture()
def currentDrive() -> Any:
    from pi.obdii.drive_id import setCurrentDriveId

    setCurrentDriveId(None)
    yield setCurrentDriveId
    setCurrentDriveId(None)


def _publishingHost(
    dtcLogger: _PublishingDtcLogger,
) -> tuple[_EmitHost, list[dict[str, Any]]]:
    emitted: list[dict[str, Any]] = []
    host = _EmitHost(
        _dtcLogger=dtcLogger,
        _connection=object(),
        _driveDetector=_Driving(),
        _dtcEmitter=lambda **kw: emitted.append(kw),
    )
    return host, emitted


def _published(emitted: list[dict[str, Any]]) -> list[tuple[str, str, Any]]:
    return [(c["code"], c["status"], c["driveId"]) for c in emitted[-1]["codes"]]


class TestDriveTimePublishes:
    """Atlas 2026-10-14 s6.1 + Q1/Q4: drive-time reads publish with the drive id."""

    def test_periodicPoll_passesTheCurrentDriveId_andPublishesIt(
        self, currentDrive: Any,
    ) -> None:
        """VC: drive 7 active, periodic poll returns P0400 -> codes[0].driveId == 7."""
        currentDrive(7)
        dtcLogger = _PublishingDtcLogger()
        dtcLogger.periodicCodes = [_diag("P0400", "stored")]
        host, emitted = _publishingHost(dtcLogger)

        host._dispatchPeriodicDtcPoll()

        assert dtcLogger.periodicCalls == [{"driveId": 7}]
        assert len(emitted) == 1
        assert emitted[0]["codes"][0]["driveId"] == 7
        assert _published(emitted) == [("P0400", "stored", 7)]
        assert emitted[0]["mil"] is True

    def test_periodicPollWithNoDrive_publishesNothing(self, currentDrive: Any) -> None:
        """VC: no current drive -> the logger's no-op runs, nothing written."""
        dtcLogger = _PublishingDtcLogger()
        dtcLogger.periodicCodes = [_diag("P0400", "stored")]
        host, emitted = _publishingHost(dtcLogger)

        host._dispatchPeriodicDtcPoll()

        assert dtcLogger.periodicCalls == [{"driveId": None}]
        assert emitted == []

    def test_periodicPollInsideTheCooldown_publishesNothing(
        self, currentDrive: Any,
    ) -> None:
        """VC: polled False -> nothing written (Atlas G-a1 ack)."""
        currentDrive(7)
        dtcLogger = _PublishingDtcLogger()
        dtcLogger.periodicPolled = False
        host, emitted = _publishingHost(dtcLogger)

        host._dispatchPeriodicDtcPoll()

        assert emitted == []

    def test_periodicTickViaHandleReading_publishes(self, currentDrive: Any) -> None:
        currentDrive(7)
        dtcLogger = _PublishingDtcLogger()
        dtcLogger.periodicCodes = [_diag("P0400", "stored")]
        host, emitted = _publishingHost(dtcLogger)

        host._handleReading(SimpleNamespace(parameterName='RPM', value=900.0, unit='rpm'))

        assert _published(emitted) == [("P0400", "stored", 7)]

    def test_driveStart_publishesStoredAndPendingWithTheDriveId(
        self, currentDrive: Any,
    ) -> None:
        currentDrive(8)
        dtcLogger = _PublishingDtcLogger()
        dtcLogger.sessionCodes = [_diag("P0400", "stored"), _diag("P0171", "pending")]
        host, emitted = _publishingHost(dtcLogger)

        host._dispatchSessionStartDtcs()

        assert _published(emitted) == [
            ("P0400", "stored", 8), ("P0171", "pending", 8),
        ]

    def test_milEdge_publishesWithTheDriveId(self, currentDrive: Any) -> None:
        currentDrive(9)
        dtcLogger = _PublishingDtcLogger()
        dtcLogger.milCodes = [_diag("P0443", "stored")]
        host, emitted = _publishingHost(dtcLogger)

        host._dispatchMilEventDtcs()

        assert _published(emitted) == [("P0443", "stored", 9)]
        assert emitted[0]["mil"] is True

    def test_keyOnPublish_staysDriveIdNone(self, currentDrive: Any) -> None:
        currentDrive(7)  # a stale process drive id must not reach a key-on publish
        dtcLogger = _PublishingDtcLogger()
        dtcLogger.keyOnCodes = [_diag("P0443", "stored")]
        host, emitted = _publishingHost(dtcLogger)
        host._driveDetector = None

        host._dispatchKeyOnDtcs()

        assert _published(emitted) == [("P0443", "stored", None)]

    def test_resultWithoutCodes_publishesNothing(self, currentDrive: Any) -> None:
        """Test doubles that predate `codes` keep publishing nothing."""
        currentDrive(7)
        dtcLogger = _FakeDtcLogger()
        emitted: list[dict[str, Any]] = []
        host = _EmitHost(
            _dtcLogger=dtcLogger, _connection=object(),
            _dtcEmitter=lambda **kw: emitted.append(kw),
        )

        host._dispatchSessionStartDtcs()
        host._dispatchMilEventDtcs()

        assert emitted == []


class TestPendingCarryForward:
    """Atlas G-a1: a Mode 03-only publish keeps the last Mode 07 pending set."""

    def test_keyOnPending_thenPeriodicStored_carriesThePending(
        self, currentDrive: Any,
    ) -> None:
        """VC: key-on pending P0171, then periodic stored P0400 -> both published."""
        dtcLogger = _PublishingDtcLogger()
        dtcLogger.keyOnCodes = [_diag("P0171", "pending")]
        dtcLogger.periodicCodes = [_diag("P0400", "stored")]
        host, emitted = _publishingHost(dtcLogger)
        host._driveDetector = None
        host._dispatchKeyOnDtcs()

        currentDrive(7)
        host._dispatchPeriodicDtcPoll()

        assert [(c, s) for c, s, _ in _published(emitted)] == [
            ("P0400", "stored"), ("P0171", "pending"),
        ]
        assert emitted[-1]["mil"] is True

    def test_carriedPendingThatIsNowStored_isListedOnce(
        self, currentDrive: Any,
    ) -> None:
        dtcLogger = _PublishingDtcLogger()
        dtcLogger.keyOnCodes = [_diag("P0171", "pending"), _diag("P0300", "pending")]
        dtcLogger.milCodes = [_diag("P0171", "stored")]
        host, emitted = _publishingHost(dtcLogger)
        host._driveDetector = None
        host._dispatchKeyOnDtcs()

        currentDrive(7)
        host._dispatchMilEventDtcs()

        assert [(c, s) for c, s, _ in _published(emitted)] == [
            ("P0171", "stored"), ("P0300", "pending"),
        ]

    def test_driveStartReplacesThePendingSet(self, currentDrive: Any) -> None:
        dtcLogger = _PublishingDtcLogger()
        dtcLogger.keyOnCodes = [_diag("P0171", "pending")]
        dtcLogger.sessionCodes = []  # the drive-start Mode 07 read found none
        dtcLogger.periodicCodes = [_diag("P0400", "stored")]
        host, emitted = _publishingHost(dtcLogger)
        host._driveDetector = None
        host._dispatchKeyOnDtcs()

        currentDrive(7)
        host._dispatchSessionStartDtcs()
        host._dispatchPeriodicDtcPoll()

        assert [(c, s) for c, s, _ in _published(emitted)] == [("P0400", "stored")]
