################################################################################
# File Name: test_capture_loop_integration.py
# Purpose/Description: Unit tests for US-221 -- handleCaptureError() wired into
#                      RealtimeDataLogger._pollCycle. Covers classifier
#                      routing, ECU-silent cadence reduction, FATAL re-raise
#                      signaling, and backward compatibility when no handler
#                      is injected.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-22    | Rex (US-221) | Initial -- US-211 integration wiring.
# ================================================================================
################################################################################

"""Tests for US-221: US-211 classifier wired into the capture loop.

The :class:`RealtimeDataLogger` drives the capture loop (see
:mod:`src.pi.obdii.data.realtime`).  Before US-221, any exception that
bubbled out of ``queryParameter`` past :exc:`ParameterReadError` was
logged and counted but otherwise ignored -- a BT flap left the collector
polling a dead connection silently until systemd bounced the process.

US-221 introduces two injection points on :class:`RealtimeDataLogger`:

* ``captureErrorHandler`` -- a callable routing exceptions through
  :class:`~src.pi.obdii.orchestrator.bt_resilience.BtResilienceMixin.handleCaptureError`,
  which classifies into ADAPTER_UNREACHABLE / ECU_SILENT / FATAL and
  reacts (tear-down + reconnect loop, cadence reduction, re-raise).
* ``onFatalError`` -- a callable invoked by the loop when the classifier
  re-raises.  Production wires this to an orchestrator shutdown hook so
  systemd ``Restart=always`` can bounce the process.

These tests drive the loop directly (no orchestrator) with a hand-built
fake connection, a fake handler, and pytest capturing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pi.obdii.data.realtime import RealtimeDataLogger
from src.pi.obdii.error_classification import CaptureErrorClass

# ================================================================================
# Fakes
# ================================================================================

class _FakeOdbResponse:
    """Minimal python-obd response stand-in."""

    def __init__(self, value: float, unit: str | None = "rpm") -> None:
        self.value = value
        self.unit = unit

    def is_null(self) -> bool:
        return False


class _FakeObd:
    """The ``.obd`` attribute of :class:`_FakeConnection`.

    Each ``query()`` call pops from ``responses``; when a popped entry
    is an Exception class/instance, it is raised instead of returned.
    """

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.queryCalls = 0

    def query(self, cmd: Any) -> Any:
        self.queryCalls += 1
        if not self._responses:
            return _FakeOdbResponse(1000.0)
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item("fake failure")
        return item


class _FakeConnection:
    """Connection stand-in that exposes the attributes RealtimeDataLogger needs."""

    isSimulated: bool = False

    def __init__(self, responses: list[Any] | None = None) -> None:
        self.obd = _FakeObd(responses or [])
        self.supportedPids = None  # Skip PID-support probe branch.

    def isConnected(self) -> bool:
        return True


class _FakeDatabase:
    """ObdDatabase stand-in -- accepts logReading() writes without storing."""

    def __init__(self) -> None:
        self.inserts: list[tuple[Any, ...]] = []

    def connect(self) -> Any:
        outer = self

        class _Cursor:
            def execute(self, sql: str, params: tuple[Any, ...]) -> None:
                outer.inserts.append(params)

        class _Conn:
            def cursor(self) -> _Cursor:
                return _Cursor()

            def __enter__(self) -> _Conn:
                return self

            def __exit__(self, *exc: Any) -> None:
                return None

        return _Conn()


def _makeConfig(pollingIntervalMs: int = 100) -> dict[str, Any]:
    """Minimal config dict honored by RealtimeDataLogger / ObdDataLogger."""
    return {
        'pi': {
            'profiles': {
                'activeProfile': 'daily',
                'availableProfiles': [
                    {'id': 'daily', 'pollingIntervalMs': pollingIntervalMs}
                ],
            },
            'realtimeData': {
                'pollingIntervalMs': pollingIntervalMs,
                'parameters': [
                    {'name': 'RPM', 'logData': True, 'displayOnDashboard': True},
                ],
            },
        }
    }


def _makeLogger(
    responses: list[Any],
    *,
    captureErrorHandler: Callable[[BaseException], CaptureErrorClass] | None = None,
    onFatalError: Callable[[BaseException], None] | None = None,
    ecuSilentMultiplier: int = 5,
    pollingIntervalMs: int = 100,
) -> RealtimeDataLogger:
    return RealtimeDataLogger(
        _makeConfig(pollingIntervalMs=pollingIntervalMs),
        _FakeConnection(responses=responses),
        _FakeDatabase(),
        captureErrorHandler=captureErrorHandler,
        onFatalError=onFatalError,
        ecuSilentMultiplier=ecuSilentMultiplier,
    )


# ================================================================================
# Handler wiring -- constructor accepts the injection points
# ================================================================================

class TestCaptureLoopConstructor:
    """RealtimeDataLogger accepts captureErrorHandler + onFatalError kwargs."""

    def test_constructor_acceptsCaptureErrorHandler(self):
        handler = MagicMock(return_value=CaptureErrorClass.ECU_SILENT)
        rt = _makeLogger([], captureErrorHandler=handler)
        assert rt._captureErrorHandler is handler

    def test_constructor_acceptsOnFatalError(self):
        onFatal = MagicMock()
        rt = _makeLogger([], onFatalError=onFatal)
        assert rt._onFatalError is onFatal

    def test_constructor_defaultsToNoHandler_backwardCompatible(self):
        rt = _makeLogger([])
        assert rt._captureErrorHandler is None
        assert rt._onFatalError is None
        assert rt._ecuSilentMode is False


# ================================================================================
# Routing -- ADAPTER_UNREACHABLE path
# ================================================================================

class TestAdapterUnreachableRouting:
    """Capture loop invokes captureErrorHandler on adapter-layer exceptions."""

    def test_pollCycle_adapterUnreachable_invokesHandlerNotFatal(self):
        """Capture-boundary OSError routes through handler as ADAPTER_UNREACHABLE."""
        handler = MagicMock(return_value=CaptureErrorClass.ADAPTER_UNREACHABLE)
        onFatal = MagicMock()
        rt = _makeLogger(
            [OSError("rfcomm vanished")],
            captureErrorHandler=handler,
            onFatalError=onFatal,
        )

        rt._pollCycle()

        assert handler.call_count == 1
        routedExc = handler.call_args[0][0]
        assert isinstance(routedExc, OSError)
        assert "rfcomm" in str(routedExc)
        onFatal.assert_not_called()
        assert rt._stopEvent.is_set() is False  # process stays alive

    def test_pollCycle_adapterUnreachable_recordsError(self):
        """Adapter exception counts as an error for stats / observability."""
        handler = MagicMock(return_value=CaptureErrorClass.ADAPTER_UNREACHABLE)
        rt = _makeLogger(
            [OSError("rfcomm vanished")],
            captureErrorHandler=handler,
        )

        rt._pollCycle()

        assert rt._stats.totalErrors >= 1

    def test_pollCycle_adapterUnreachable_doesNotEnterSilentMode(self):
        """ADAPTER recovery is in-line; no cadence reduction after return."""
        handler = MagicMock(return_value=CaptureErrorClass.ADAPTER_UNREACHABLE)
        rt = _makeLogger(
            [OSError("rfcomm vanished")],
            captureErrorHandler=handler,
        )

        rt._pollCycle()

        assert rt._ecuSilentMode is False


# ================================================================================
# Routing -- ECU_SILENT path
# ================================================================================

class TestEcuSilentRouting:
    """ECU_SILENT sets the cadence-reduction flag without disconnecting."""

    def test_pollCycle_ecuSilent_entersSilentMode(self):
        handler = MagicMock(return_value=CaptureErrorClass.ECU_SILENT)
        rt = _makeLogger(
            [TimeoutError("ECU did not respond to 010C")],
            captureErrorHandler=handler,
        )
        assert rt._ecuSilentMode is False

        rt._pollCycle()

        assert rt._ecuSilentMode is True
        handler.assert_called_once()

    def test_ecuSilentMode_multipliesPollingInterval(self):
        handler = MagicMock(return_value=CaptureErrorClass.ECU_SILENT)
        rt = _makeLogger(
            [TimeoutError("no response")],
            captureErrorHandler=handler,
            ecuSilentMultiplier=5,
            pollingIntervalMs=100,
        )
        assert rt._getEffectivePollingIntervalMs() == 100

        rt._pollCycle()  # Enters silent mode.

        assert rt._getEffectivePollingIntervalMs() == 500

    def test_ecuSilentMode_clearedOnSuccessfulQuery(self):
        """First successful query after silent entry restores normal cadence."""
        handler = MagicMock(return_value=CaptureErrorClass.ECU_SILENT)
        # Cycle 1: TimeoutError -> silent.  Cycle 2: valid response -> clear.
        rt = _makeLogger(
            [TimeoutError("no response"), _FakeOdbResponse(2500.0)],
            captureErrorHandler=handler,
            ecuSilentMultiplier=5,
        )

        rt._pollCycle()
        assert rt._ecuSilentMode is True

        rt._pollCycle()
        assert rt._ecuSilentMode is False

    def test_ecuSilentMode_neverCallsOnFatal(self):
        handler = MagicMock(return_value=CaptureErrorClass.ECU_SILENT)
        onFatal = MagicMock()
        rt = _makeLogger(
            [TimeoutError("no response")],
            captureErrorHandler=handler,
            onFatalError=onFatal,
        )

        rt._pollCycle()

        onFatal.assert_not_called()
        assert rt._stopEvent.is_set() is False


# ================================================================================
# Routing -- FATAL path
# ================================================================================

class TestFatalRouting:
    """FATAL re-raise from the handler signals orchestrator shutdown."""

    def _raiseFatal(self, exc: BaseException) -> CaptureErrorClass:
        """Mimic BtResilienceMixin.handleCaptureError FATAL branch."""
        raise exc

    def test_pollCycle_fatal_invokesOnFatalError(self):
        fatal = RuntimeError("parser wedged -- process unsafe to continue")
        handler = MagicMock(side_effect=self._raiseFatal)
        onFatal = MagicMock()
        rt = _makeLogger(
            [fatal],
            captureErrorHandler=handler,
            onFatalError=onFatal,
        )

        rt._pollCycle()

        onFatal.assert_called_once()
        forwarded = onFatal.call_args[0][0]
        assert isinstance(forwarded, RuntimeError)
        assert "parser wedged" in str(forwarded)

    def test_pollCycle_fatal_setsStopEvent(self):
        """Loop stops iterating; orchestrator takes over exit path."""
        handler = MagicMock(side_effect=self._raiseFatal)
        onFatal = MagicMock()
        rt = _makeLogger(
            [RuntimeError("broken")],
            captureErrorHandler=handler,
            onFatalError=onFatal,
        )

        rt._pollCycle()

        assert rt._stopEvent.is_set() is True

    def test_pollCycle_fatal_withNoOnFatalCallback_stillSetsStopEvent(self):
        """Missing callback does not prevent the stopEvent signal."""
        handler = MagicMock(side_effect=self._raiseFatal)
        rt = _makeLogger(
            [RuntimeError("broken")],
            captureErrorHandler=handler,
            onFatalError=None,
        )

        rt._pollCycle()

        assert rt._stopEvent.is_set() is True

    def test_pollCycle_fatal_onFatalCallbackRaises_swallowed(self):
        """Observability code must never crash the capture thread."""
        handler = MagicMock(side_effect=self._raiseFatal)
        onFatal = MagicMock(side_effect=RuntimeError("callback blew up"))
        rt = _makeLogger(
            [RuntimeError("broken")],
            captureErrorHandler=handler,
            onFatalError=onFatal,
        )

        rt._pollCycle()  # Must not raise.

        assert rt._stopEvent.is_set() is True


# ================================================================================
# Backward compatibility
# ================================================================================

class TestBackwardCompatibility:
    """With no handler wired, the legacy per-parameter error path runs."""

    def test_pollCycle_noHandler_legacyPathStillHandlesExceptions(self):
        """OSError without handler logs an error via _handleParameterError."""
        rt = _makeLogger([OSError("rfcomm vanished")])
        errorSink: list[tuple[str, Exception]] = []
        rt._onError = lambda name, exc: errorSink.append((name, exc))

        rt._pollCycle()  # Must not raise.

        assert len(errorSink) == 1
        assert errorSink[0][0] == 'RPM'
        assert isinstance(errorSink[0][1], OSError)
        assert rt._stats.totalErrors >= 1
        assert rt._stopEvent.is_set() is False


# ================================================================================
# Benign ParameterReadError classification fallthrough
# ================================================================================

class TestParameterReadErrorUnwrap:
    """ParameterReadError carrying a capture-boundary __cause__ re-routes."""

    def test_queryParameterSafe_nullResponse_noCause_swallows(self):
        """Pure null-response ParameterReadError stays benign (no cause)."""
        # Build a response that reports is_null=True to trigger null-path.
        class _NullResponse:
            value = None
            unit = None

            def is_null(self) -> bool:
                return True

        rt = _makeLogger([_NullResponse()])
        result = rt._queryParameterSafe('RPM')

        assert result is None  # Null-response swallowed; no raise.

    def test_queryParameterSafe_wrappedCaptureBoundary_reraisesCause(self):
        """ParameterReadError wrapping an OSError re-raises the OSError.

        This unwraps queryParameter's ``raise ParameterReadError(...) from e``
        so _pollCycle can route the underlying cause through the classifier.
        """
        rt = _makeLogger([OSError("rfcomm vanished")])

        with pytest.raises(OSError, match="rfcomm vanished"):
            rt._queryParameterSafe('RPM')

    def test_queryParameterSafe_wrappedParameterNotSupported_stillSwallowed(self):
        """ParameterNotSupportedError path is unchanged (no cause to re-raise)."""
        # Arrange a parameter with a PID probe that reports unsupported.
        config = _makeConfig()
        connection = _FakeConnection(responses=[])
        # Minimal fake supportedPids that reports the command unsupported.
        from types import SimpleNamespace
        connection.supportedPids = SimpleNamespace(isSupported=lambda pid: False)

        rt = RealtimeDataLogger(config, connection, _FakeDatabase())
        # Switch to a parameter that has a PID decoder entry to trigger the probe.
        rt._parameters = ['RUNTIME_SEC']

        result = rt._queryParameterSafe('RUNTIME_SEC')

        assert result is None
