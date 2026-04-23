################################################################################
# File Name: bt_resilience.py
# Purpose/Description: BT-resilient capture-error mixin for the orchestrator
#                      (US-211). Wires error classification + reconnect loop +
#                      canonical connection_log event_types into a single
#                      handleCaptureError() entry-point the data-logger calls
#                      when a capture-path exception surfaces.
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

"""Wire the capture loop into the BT-resilient reconnect path.

Spool Session 6 amendment insists the collector process NEVER exits on
BT disconnect -- only FATAL errors surface to systemd. The existing
:class:`~src.pi.obdii.orchestrator.connection_recovery.ConnectionRecoveryMixin`
handles state-change-driven reconnection (isConnected() polled in the
health check); this mixin adds the orthogonal error-class-driven path
invoked from the capture boundary.

Separation of concerns:

* :mod:`~src.pi.obdii.error_classification` -- pure exception classifier
* :mod:`~src.pi.obdii.reconnect_loop` -- backoff-capped wait loop
* :mod:`~src.pi.data.connection_logger` -- canonical event_type writer
* This module -- composition into the orchestrator facade

The mixin does not rewrite :class:`~src.pi.obdii.orchestrator.connection_recovery.ConnectionRecoveryMixin`;
both paths coexist. The new path is synchronous (callers own the
thread), the existing path is background-threaded. Over time the legacy
path can be narrowed; US-211 scope is additive.
"""

from __future__ import annotations

import logging
from typing import Any

from ..error_classification import CaptureErrorClass, classifyCaptureError
from ..reconnect_loop import ReconnectLoop

logger = logging.getLogger("pi.obdii.orchestrator")


class BtResilienceMixin:
    """Orchestrator mixin exposing :meth:`handleCaptureError`.

    Assumes the composing class has:

    * ``_connection`` -- the :class:`~src.pi.obdii.obd_connection.ObdConnection`
      or a duck-typed stand-in with ``.isConnected()`` / ``.disconnect()``
      / ``.reconnect()``.
    * ``_database`` -- :class:`~src.pi.obdii.database.ObdDatabase` for
      event logging (None is tolerated).
    * ``_reconnectLoopFactory`` -- optional zero-arg callable returning
      a :class:`ReconnectLoop`. Defaults to :func:`_defaultLoopFactory`
      which builds one using the live database + MAC + rfcomm device.
    """

    _connection: Any | None
    _database: Any | None
    _reconnectLoopFactory: Any | None

    def handleCaptureError(self, exc: BaseException) -> CaptureErrorClass:
        """Classify and react to a capture-path exception.

        This is the single orchestrator-side entry-point for US-211.
        Callers (data_logger, poll set iterator, DTC reader) invoke it
        whenever python-obd or the adapter layer raises.

        Reactions per class:

        * :attr:`~src.pi.obdii.error_classification.CaptureErrorClass.ADAPTER_UNREACHABLE`
          -> tear down python-obd, log ``bt_disconnect``, run the
          reconnect loop, reopen on success.
        * :attr:`~src.pi.obdii.error_classification.CaptureErrorClass.ECU_SILENT`
          -> stay connected, log ``ecu_silent_wait``. Caller is expected
          to reduce its poll cadence (not the mixin's concern).
        * :attr:`~src.pi.obdii.error_classification.CaptureErrorClass.FATAL`
          -> log at ERROR level with full traceback and re-raise. systemd
          ``Restart=always`` from US-210 handles the process restart.

        Args:
            exc: Exception raised at the capture boundary.

        Returns:
            The :class:`CaptureErrorClass` that was selected, so the
            caller can decide how to resume its own loop state.

        Raises:
            The original exception when classified as FATAL.
        """
        classification = classifyCaptureError(exc)
        logger.debug(
            "handleCaptureError | class=%s exc=%r", classification.value, exc
        )

        if classification is CaptureErrorClass.ADAPTER_UNREACHABLE:
            self._reactToAdapterUnreachable(exc)
        elif classification is CaptureErrorClass.ECU_SILENT:
            self._reactToEcuSilent(exc)
        else:  # FATAL
            logger.error(
                "FATAL capture-boundary exception -- surfacing to systemd",
                exc_info=exc,
            )
            raise exc

        return classification

    # --------------------------------------------------------------------------
    # ADAPTER_UNREACHABLE path
    # --------------------------------------------------------------------------

    def _reactToAdapterUnreachable(self, exc: BaseException) -> None:
        """Tear down python-obd, log bt_disconnect, wait, reopen."""
        from src.pi.data.connection_logger import (
            EVENT_BT_DISCONNECT,
            logConnectionEvent,
        )

        macAddress = self._getMacAddress()
        logConnectionEvent(
            database=self._database,
            eventType=EVENT_BT_DISCONNECT,
            macAddress=macAddress,
            success=False,
            errorMessage=str(exc),
            retryCount=0,
        )

        self._safeDisconnect()

        loop = self._buildReconnectLoop()
        reached = loop.waitForAdapter()
        if not reached:
            # shouldExitFn fired -- caller will handle shutdown.
            return

        self._safeReopen()

    def _safeDisconnect(self) -> None:
        """Close the python-obd connection, swallowing any close errors.

        Invariant: disconnect() must not raise during the ADAPTER
        path -- we're already in an error state and need to reach the
        reconnect loop.
        """
        conn = self._connection
        if conn is None:
            return
        try:
            if hasattr(conn, 'disconnect'):
                conn.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.debug("disconnect() raised during adapter recovery: %s", exc)

    def _safeReopen(self) -> None:
        """Reopen the python-obd connection, downgrading failures to a warning."""
        conn = self._connection
        if conn is None:
            logger.warning("Reconnect succeeded but _connection is None -- cannot reopen")
            return
        try:
            if hasattr(conn, 'reconnect'):
                conn.reconnect()
            elif hasattr(conn, 'connect'):
                conn.connect()
        except Exception as exc:  # noqa: BLE001
            logger.warning("OBD reopen failed after adapter recovery: %s", exc)

    def _buildReconnectLoop(self) -> ReconnectLoop:
        """Return a fresh :class:`ReconnectLoop` with production wiring.

        Tests set ``self._reconnectLoopFactory`` to a zero-arg lambda
        that returns a pre-built loop with injected probe + sleep.
        """
        factory = getattr(self, '_reconnectLoopFactory', None)
        if factory is not None:
            return factory()
        return self._defaultLoopFactory()

    def _defaultLoopFactory(self) -> ReconnectLoop:
        """Construct the live-Pi reconnect loop using injected components."""
        from src.pi.obdii.reconnect_loop import buildDefaultReconnectLoop

        rfcommDevice = 0
        conn = self._connection
        if conn is not None and hasattr(conn, 'rfcommDevice'):
            rfcommDevice = int(getattr(conn, 'rfcommDevice', 0) or 0)

        return buildDefaultReconnectLoop(
            database=self._database,
            macAddress=self._getMacAddress(),
            rfcommDevice=rfcommDevice,
        )

    # --------------------------------------------------------------------------
    # ECU_SILENT path
    # --------------------------------------------------------------------------

    def _reactToEcuSilent(self, exc: BaseException) -> None:
        """Log ecu_silent_wait; do NOT disconnect -- adapter is healthy."""
        from src.pi.data.connection_logger import (
            EVENT_ECU_SILENT_WAIT,
            logConnectionEvent,
        )

        logConnectionEvent(
            database=self._database,
            eventType=EVENT_ECU_SILENT_WAIT,
            macAddress=self._getMacAddress(),
            success=False,
            errorMessage=str(exc),
            retryCount=0,
        )
        logger.info("ECU silent (adapter OK) -- capture loop will pause cadence")

    # --------------------------------------------------------------------------
    # Shared helpers
    # --------------------------------------------------------------------------

    def _getMacAddress(self) -> str | None:
        conn = self._connection
        if conn is None:
            return None
        mac = getattr(conn, 'macAddress', None)
        if not mac:
            return None
        return str(mac)


__all__ = ['BtResilienceMixin']
