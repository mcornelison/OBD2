################################################################################
# File Name: error_classification.py
# Purpose/Description: Capture-boundary exception classifier for US-211.
#                      Buckets raised exceptions into ADAPTER_UNREACHABLE /
#                      ECU_SILENT / FATAL so the orchestrator knows whether
#                      to enter the reconnect loop, pause polling, or
#                      re-raise to systemd.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-211) | Initial -- Spool Session 6 amended Story 2.
# ================================================================================
################################################################################

"""Classify capture-path exceptions into three buckets.

Spool Session 6 amendment locked three error classes (grounding
ref: "Error classes: ADAPTER_UNREACHABLE ... ECU_SILENT ... FATAL"):

``ADAPTER_UNREACHABLE``
    The OBDLink / /dev/rfcomm0 stack is not reachable. Typical triggers:
    python-obd raises ``OSError``/``FileNotFoundError`` because the rfcomm
    device vanished, :class:`~src.pi.obdii.bluetooth_helper.BluetoothHelperError`
    for a failed rebind, or
    :class:`~src.pi.obdii.obd_connection.ObdConnectionError` whose message
    names rfcomm. Expected behavior: tear down python-obd, enter the
    reconnect-wait loop, never exit the process.

``ECU_SILENT``
    The Bluetooth stack responded but the ECU did not. Typical trigger:
    engine off / key off, so python-obd's timeout fires even though the
    adapter socket is healthy. Expected behavior: stay connected, pause or
    reduce poll cadence, resume when the ECU comes back. Distinguished
    from ADAPTER_UNREACHABLE by the *class* of exception
    (``TimeoutError``/:class:`~src.pi.obdii.obd_connection.ObdConnectionTimeoutError`)
    combined with the absence of rfcomm-flavored stderr text -- the
    reverse order (adapter down, then ECU-silent heuristic) would false-
    classify ``ECU_SILENT`` during a BT drop.

``FATAL``
    Anything else. Re-raise so the outer systemd ``Restart=always``
    (US-210) handles it with a clean process restart.

The classifier is a pure function of the exception instance. The caller
owns the reaction (close connection / log event_type row / raise).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

__all__ = [
    'CaptureErrorClass',
    'classifyCaptureError',
]


class CaptureErrorClass(Enum):
    """Three-bucket taxonomy for capture-path exceptions (US-211)."""

    ADAPTER_UNREACHABLE = 'adapter_unreachable'
    ECU_SILENT = 'ecu_silent'
    FATAL = 'fatal'


# ================================================================================
# Classifier
# ================================================================================

# Substrings that, when present in an exception's string representation,
# signal an adapter-layer failure (rfcomm bind, kernel socket, bluez).
# Matching is case-insensitive. Tuple-of-substrings pattern keeps the
# classifier easily extensible without regex compilation overhead.
_ADAPTER_SUBSTRINGS: tuple[str, ...] = (
    'rfcomm',
    '/dev/rfcomm',
    'bluetooth',
    'bluez',
    'no such device',
    "can't get info",
    'host is down',
    'connection refused',
    'transport endpoint',
)


def classifyCaptureError(exc: BaseException) -> CaptureErrorClass:
    """Classify ``exc`` into one of the three capture-boundary buckets.

    The classifier is structural (exception class + string content),
    intentionally avoiding a hard dependency on python-obd's private
    exception hierarchy -- python-obd surfaces most failures as plain
    ``Exception`` with a human string, so the substring fallback handles
    those uniformly.

    Order of checks:

    1. :class:`KeyboardInterrupt` / :class:`SystemExit` / :class:`MemoryError`
       -> :attr:`CaptureErrorClass.FATAL` (never swallow control-flow signals).
    2. :class:`OSError` / :class:`FileNotFoundError` / :class:`PermissionError`
       -> :attr:`CaptureErrorClass.ADAPTER_UNREACHABLE` (kernel-level I/O
       against /dev/rfcomm* is almost always adapter loss).
    3. :class:`~src.pi.obdii.bluetooth_helper.BluetoothHelperError`
       -> :attr:`CaptureErrorClass.ADAPTER_UNREACHABLE`.
    4. :class:`~src.pi.obdii.obd_connection.ObdConnectionError` or
       subclass whose message contains an adapter substring
       -> :attr:`CaptureErrorClass.ADAPTER_UNREACHABLE`.
    5. :class:`TimeoutError` or
       :class:`~src.pi.obdii.obd_connection.ObdConnectionTimeoutError` whose
       message does *not* mention rfcomm/bluetooth -> :attr:`CaptureErrorClass.ECU_SILENT`.
    6. Plain :class:`Exception` whose message mentions rfcomm
       -> :attr:`CaptureErrorClass.ADAPTER_UNREACHABLE` (python-obd wraps
       OSError in Exception on some paths).
    7. Everything else -> :attr:`CaptureErrorClass.FATAL`.

    Args:
        exc: Exception instance raised from the capture path.

    Returns:
        Three-bucket classification.
    """
    # Control-flow exceptions -- never swallow.
    if isinstance(exc, (KeyboardInterrupt, SystemExit, MemoryError)):
        return CaptureErrorClass.FATAL

    message = str(exc).lower() if str(exc) else ''
    hasAdapterSignature = any(s in message for s in _ADAPTER_SUBSTRINGS)

    # TimeoutError and ObdConnectionTimeoutError must be checked BEFORE
    # the generic OSError branch below -- :class:`TimeoutError` is a
    # subclass of :class:`OSError` in Python 3.10+, so the generic
    # branch would false-classify every timeout as ADAPTER_UNREACHABLE.
    # Timeouts with rfcomm/bluetooth signature still go to the adapter
    # bucket (BT drop that surfaced as a read timeout); timeouts without
    # signature are ECU_SILENT (engine off, no ECU response).
    if _isObdConnectionTimeoutError(exc) or isinstance(exc, TimeoutError):
        if hasAdapterSignature:
            return CaptureErrorClass.ADAPTER_UNREACHABLE
        return CaptureErrorClass.ECU_SILENT

    # Kernel I/O against /dev/rfcomm* -- adapter layer. :class:`OSError`
    # covers :class:`FileNotFoundError` and :class:`PermissionError`
    # via inheritance; explicit types in the tuple make the intent
    # obvious to readers of the classifier.
    if isinstance(exc, (OSError, FileNotFoundError, PermissionError)):
        return CaptureErrorClass.ADAPTER_UNREACHABLE

    # Named adapter-layer exceptions. Import lazily to avoid cycles.
    if _isBluetoothHelperError(exc):
        return CaptureErrorClass.ADAPTER_UNREACHABLE

    # ObdConnectionError (non-timeout): rfcomm signature -> adapter;
    # otherwise ambiguous -> ECU_SILENT (stay connected rather than
    # tearing down + reopening for a soft failure).
    if _isObdConnectionError(exc):
        if hasAdapterSignature:
            return CaptureErrorClass.ADAPTER_UNREACHABLE
        return CaptureErrorClass.ECU_SILENT

    # python-obd sometimes wraps adapter errors as bare Exception; detect
    # via message substring.
    if hasAdapterSignature:
        return CaptureErrorClass.ADAPTER_UNREACHABLE

    return CaptureErrorClass.FATAL


# ================================================================================
# Lazy-import helpers (avoid circular imports at module load time)
# ================================================================================

def _isBluetoothHelperError(exc: BaseException) -> bool:
    """Return True if ``exc`` is :class:`BluetoothHelperError`.

    Imported lazily because :mod:`error_classification` is loaded from
    orchestrator wiring and :mod:`bluetooth_helper` loads subprocess/bluez
    bindings that are not always available in the test harness.
    """
    try:
        from src.pi.obdii.bluetooth_helper import BluetoothHelperError
    except Exception:  # pragma: no cover -- only triggers on broken installs
        return False
    return isinstance(exc, BluetoothHelperError)


def _isObdConnectionError(exc: BaseException) -> bool:
    """Return True if ``exc`` is :class:`ObdConnectionError`."""
    cls = _getObdConnectionErrorClass()
    if cls is None:
        return False
    return isinstance(exc, cls)


def _isObdConnectionTimeoutError(exc: BaseException) -> bool:
    """Return True if ``exc`` is :class:`ObdConnectionTimeoutError`."""
    cls = _getObdConnectionTimeoutErrorClass()
    if cls is None:
        return False
    return isinstance(exc, cls)


_ObdErrorCache: dict[str, Any] = {}


def _getObdConnectionErrorClass() -> Any | None:
    if 'ObdConnectionError' not in _ObdErrorCache:
        try:
            from src.pi.obdii.obd_connection import ObdConnectionError
            _ObdErrorCache['ObdConnectionError'] = ObdConnectionError
        except Exception:  # pragma: no cover
            _ObdErrorCache['ObdConnectionError'] = None
    return _ObdErrorCache['ObdConnectionError']


def _getObdConnectionTimeoutErrorClass() -> Any | None:
    if 'ObdConnectionTimeoutError' not in _ObdErrorCache:
        try:
            from src.pi.obdii.obd_connection import ObdConnectionTimeoutError
            _ObdErrorCache['ObdConnectionTimeoutError'] = ObdConnectionTimeoutError
        except Exception:  # pragma: no cover
            _ObdErrorCache['ObdConnectionTimeoutError'] = None
    return _ObdErrorCache['ObdConnectionTimeoutError']
