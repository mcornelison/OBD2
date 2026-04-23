################################################################################
# File Name: connection_logger.py
# Purpose/Description: Canonical event_type constants for connection_log +
#                      lightweight helper so callers emit canonical strings
#                      instead of magic literals (US-211).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-211) | Initial -- BT-resilient collector event_types
# ================================================================================
################################################################################

"""Canonical ``connection_log.event_type`` constants + writer helper.

The ``connection_log`` table uses ``event_type TEXT`` (free-form, no CHECK
constraint) so that pre-US-211 writers across the Pi codebase keep working
unchanged. This module centralizes the canonical set of event_type literals
that callers should emit -- acting as a Python-level enum that lives
alongside the schema.

Spool's US-211 spec extends the event_type set with five new values
tracking the BT-resilience timeline:

``bt_disconnect``
    Capture loop classified a raised exception as ADAPTER_UNREACHABLE and
    tore down the python-obd connection. Always emitted before the first
    ``adapter_wait`` row so the flap timeline starts cleanly.

``adapter_wait``
    Each iteration of the reconnect-wait loop (before the probe fires).
    The ``retry_count`` column carries the loop iteration number.

``reconnect_attempt``
    The adapter probe returned reachable and the orchestrator is about to
    reopen the python-obd connection. Serves as a checkpoint that
    distinguishes probe-success from OBD-session-success.

``reconnect_success``
    python-obd reopened successfully and capture resumed. Pairs with the
    earlier ``bt_disconnect`` to frame the BT-flap window.

``ecu_silent_wait``
    Capture loop classified a raised exception as ECU_SILENT (adapter OK
    but engine/key off and ECU not responding). Capture stays connected
    but reduces poll cadence; no process-level reconnect.

Existing event_types (``connect_attempt``, ``connect_success``,
``connect_failure``, ``disconnect``, ``reconnect``, ``drive_start``,
``drive_end``, ``data_cleanup``, ``shutdown_sigterm``, ``shutdown_sigint``,
``shutdown_graceful``, plus dynamic profile-switcher and shutdown-command
variants) continue to be valid -- US-211 is additive, not a replacement.

:func:`logConnectionEvent` is the thin wrapper callers should prefer for
the five new event_types so the string literals stay centralized.
"""

from __future__ import annotations

import logging
from typing import Any

from src.common.time.helper import utcIsoNow

logger = logging.getLogger(__name__)


# ================================================================================
# Canonical event_type constants (US-211 additions)
# ================================================================================

#: Classifier fired ADAPTER_UNREACHABLE; python-obd connection torn down.
EVENT_BT_DISCONNECT: str = 'bt_disconnect'

#: Reconnect-wait loop iteration about to sleep before the next probe.
EVENT_ADAPTER_WAIT: str = 'adapter_wait'

#: Probe returned reachable; orchestrator is about to reopen python-obd.
EVENT_RECONNECT_ATTEMPT: str = 'reconnect_attempt'

#: python-obd reopened successfully; capture resumed.
EVENT_RECONNECT_SUCCESS: str = 'reconnect_success'

#: Classifier fired ECU_SILENT; capture stays connected, cadence reduced.
EVENT_ECU_SILENT_WAIT: str = 'ecu_silent_wait'


# ================================================================================
# Canonical event_type constants (pre-US-211, re-exported for convenience)
# ================================================================================

EVENT_CONNECT_ATTEMPT: str = 'connect_attempt'
EVENT_CONNECT_SUCCESS: str = 'connect_success'
EVENT_CONNECT_FAILURE: str = 'connect_failure'
EVENT_DISCONNECT: str = 'disconnect'
EVENT_RECONNECT: str = 'reconnect'
EVENT_DRIVE_START: str = 'drive_start'
EVENT_DRIVE_END: str = 'drive_end'
EVENT_DATA_CLEANUP: str = 'data_cleanup'


#: Frozen set of canonical event_type values defined at US-211 time.
#: Dynamic writers (profile switcher event.eventType, shutdown f'shutdown_{event}')
#: emit additional strings that are intentionally NOT listed here -- the
#: ``connection_log.event_type`` column stays free-text to preserve those
#: paths. This set represents the "known canonical literals" test surface.
US211_EVENT_TYPES: frozenset[str] = frozenset({
    EVENT_BT_DISCONNECT,
    EVENT_ADAPTER_WAIT,
    EVENT_RECONNECT_ATTEMPT,
    EVENT_RECONNECT_SUCCESS,
    EVENT_ECU_SILENT_WAIT,
})

CANONICAL_EVENT_TYPES: frozenset[str] = frozenset({
    EVENT_CONNECT_ATTEMPT,
    EVENT_CONNECT_SUCCESS,
    EVENT_CONNECT_FAILURE,
    EVENT_DISCONNECT,
    EVENT_RECONNECT,
    EVENT_DRIVE_START,
    EVENT_DRIVE_END,
    EVENT_DATA_CLEANUP,
    *US211_EVENT_TYPES,
})


# ================================================================================
# Writer helper
# ================================================================================

def logConnectionEvent(
    database: Any,
    eventType: str,
    macAddress: str | None = None,
    success: bool = False,
    errorMessage: str | None = None,
    retryCount: int = 0,
    driveId: int | None = None,
) -> None:
    """Insert one row into ``connection_log`` using canonical columns.

    This helper exists for callers whose only interaction with the table
    is emitting the US-211 flap-timeline events. Existing per-component
    writers (:mod:`src.pi.obdii.obd_connection`,
    :mod:`src.pi.obdii.drive.detector`, shutdown manager, data_retention)
    keep their own SQL and are not forced through this path.

    Args:
        database: ``ObdDatabase``-shaped object with a ``.connect()``
            context manager yielding a connection whose cursor supports
            SQLite parameter substitution. None is tolerated (no-op) so
            the reconnect loop can accept a null database in unit tests
            without branching at every call-site.
        eventType: One of :data:`CANONICAL_EVENT_TYPES`. The runtime does
            not reject unknown values -- the canonical set is advisory --
            but tests assert callers emit canonical strings.
        macAddress: Bluetooth MAC of the adapter at the time of the event,
            or None when not applicable.
        success: Whether the event represents a successful outcome.
            ``reconnect_success`` is True; all others default False.
        errorMessage: Free-form error details; None when not applicable.
        retryCount: For ``adapter_wait`` rows, the loop iteration number.
            For ``reconnect_attempt`` rows, the attempt number. Zero for
            the rest.
        driveId: Active drive_id if the event fired inside a drive
            lifecycle; None otherwise.
    """
    if database is None:
        return
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO connection_log
                (timestamp, event_type, mac_address, success,
                 error_message, retry_count, drive_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utcIsoNow(),
                    eventType,
                    macAddress,
                    1 if success else 0,
                    errorMessage,
                    retryCount,
                    driveId,
                ),
            )
    except Exception as exc:  # noqa: BLE001 -- observability must not crash capture
        logger.warning(
            "Failed to write connection_log event | event_type=%s error=%s",
            eventType,
            exc,
        )


__all__ = [
    'EVENT_BT_DISCONNECT',
    'EVENT_ADAPTER_WAIT',
    'EVENT_RECONNECT_ATTEMPT',
    'EVENT_RECONNECT_SUCCESS',
    'EVENT_ECU_SILENT_WAIT',
    'EVENT_CONNECT_ATTEMPT',
    'EVENT_CONNECT_SUCCESS',
    'EVENT_CONNECT_FAILURE',
    'EVENT_DISCONNECT',
    'EVENT_RECONNECT',
    'EVENT_DRIVE_START',
    'EVENT_DRIVE_END',
    'EVENT_DATA_CLEANUP',
    'US211_EVENT_TYPES',
    'CANONICAL_EVENT_TYPES',
    'logConnectionEvent',
]
