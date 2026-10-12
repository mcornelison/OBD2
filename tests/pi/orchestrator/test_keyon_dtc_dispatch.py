################################################################################
# File Name: test_keyon_dtc_dispatch.py
# Purpose/Description: US-404 (F-111) tests for the orchestrator's key-on (KOEO)
#   DTC dispatch. _handleConnectionRestored fires a one-shot KOEO Mode 03(+07)
#   read GATED on no active RUNNING drive (a RUNNING drive owns capture via the
#   drive-scoped paths -- Atlas A-9). The dispatcher persists drive_id=NULL via
#   DtcLogger.logKeyOnDtcs and, when a `dtc` emitter is wired, publishes the
#   enriched state. Exception-isolated so the connection-restored handler stays
#   non-fatal.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial -- US-404 KOEO connection-edge dispatch.
# ================================================================================
################################################################################

"""Pin the orchestrator-side wiring of the US-404 key-on DTC read."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from pi.obdii.orchestrator.event_router import EventRouterMixin
from pi.obdii.orchestrator.types import HealthCheckStats


class _FakeDtcLogger:
    def __init__(self, *, codes: list[Any] | None = None) -> None:
        self.keyOnCalls: list[dict[str, Any]] = []
        self.shouldRaise = False
        self._codes = codes or []

    def logKeyOnDtcs(self, *, connection: Any) -> Any:
        if self.shouldRaise:
            raise RuntimeError("simulated key-on failure")
        self.keyOnCalls.append({"connection": connection})
        stored = [c for c in self._codes if c.status == "stored"]
        pending = [c for c in self._codes if c.status == "pending"]
        return SimpleNamespace(
            storedCount=len(stored),
            pendingCount=len(pending),
            mode07Probe=SimpleNamespace(supported=True, reason="supported"),
            codes=self._codes,
        )


class _FakeDriveDetector:
    def __init__(self, *, driving: bool) -> None:
        self._driving = driving

    def isDriving(self) -> bool:
        return self._driving


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
    _dtcEmitter: Callable[..., None] | None = None
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


def _diag(code: str, status: str) -> SimpleNamespace:
    return SimpleNamespace(code=code, status=status, description="")


class TestKeyOnDispatchGating:
    """The KOEO read fires only at key-on (no RUNNING drive)."""

    def test_notDriving_firesKeyOnRead(self) -> None:
        dtcLogger = _FakeDtcLogger()
        host = _Host(
            _dtcLogger=dtcLogger,
            _connection=object(),
            _driveDetector=_FakeDriveDetector(driving=False),
        )

        host._dispatchKeyOnDtcs()

        assert len(dtcLogger.keyOnCalls) == 1

    def test_runningDrive_skipsKeyOnRead(self) -> None:
        """A RUNNING drive owns DTC capture -- the KOEO path stands down (A-9)."""
        dtcLogger = _FakeDtcLogger()
        host = _Host(
            _dtcLogger=dtcLogger,
            _connection=object(),
            _driveDetector=_FakeDriveDetector(driving=True),
        )

        host._dispatchKeyOnDtcs()

        assert dtcLogger.keyOnCalls == []

    def test_noDtcLogger_skipsSilently(self) -> None:
        host = _Host(_dtcLogger=None, _connection=object())
        host._dispatchKeyOnDtcs()  # must not raise

    def test_noConnection_skipsSilently(self) -> None:
        dtcLogger = _FakeDtcLogger()
        host = _Host(_dtcLogger=dtcLogger, _connection=None)

        host._dispatchKeyOnDtcs()

        assert dtcLogger.keyOnCalls == []

    def test_keyOnFailure_swallowed(self) -> None:
        dtcLogger = _FakeDtcLogger()
        dtcLogger.shouldRaise = True
        host = _Host(
            _dtcLogger=dtcLogger,
            _connection=object(),
            _driveDetector=_FakeDriveDetector(driving=False),
        )

        host._dispatchKeyOnDtcs()  # must not raise


class TestKeyOnEmit:
    """When a `dtc` emitter is wired, the captured codes are published."""

    def test_emitsCapturedCodesWithDriveIdNull(self) -> None:
        emitted: list[dict[str, Any]] = []

        def _emit(**kwargs: Any) -> None:
            emitted.append(kwargs)

        dtcLogger = _FakeDtcLogger(
            codes=[_diag("P0443", "stored"), _diag("P1300", "pending")]
        )
        host = _Host(
            _dtcLogger=dtcLogger,
            _connection=object(),
            _driveDetector=_FakeDriveDetector(driving=False),
            _dtcEmitter=_emit,
        )

        host._dispatchKeyOnDtcs()

        assert len(emitted) == 1
        codes = emitted[0]["codes"]
        assert {c["code"] for c in codes} == {"P0443", "P1300"}
        assert all(c["driveId"] is None for c in codes)
        assert emitted[0]["mil"] is True  # a stored code present

    def test_noEmitter_stillPersistsNoCrash(self) -> None:
        dtcLogger = _FakeDtcLogger(codes=[_diag("P0443", "stored")])
        host = _Host(
            _dtcLogger=dtcLogger,
            _connection=object(),
            _driveDetector=_FakeDriveDetector(driving=False),
            _dtcEmitter=None,
        )

        host._dispatchKeyOnDtcs()  # must not raise

        assert len(dtcLogger.keyOnCalls) == 1


class TestConnectionRestoredInvokesKeyOn:
    """_handleConnectionRestored wires the KOEO read on the connection edge."""

    def test_handleConnectionRestored_firesKeyOnDispatch(self) -> None:
        dtcLogger = _FakeDtcLogger()
        host = _Host(
            _dtcLogger=dtcLogger,
            _connection=object(),
            _driveDetector=_FakeDriveDetector(driving=False),
        )

        host._handleConnectionRestored()

        assert len(dtcLogger.keyOnCalls) == 1
