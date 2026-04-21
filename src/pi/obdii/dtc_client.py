################################################################################
# File Name: dtc_client.py
# Purpose/Description: OBD-II Mode 03 (stored) + Mode 07 (pending) DTC retrieval
#                      client for the 2G Eclipse.  Probe-first semantics for
#                      Mode 07 since 2G DSM pre-dates full OBD2 compliance.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-204) | Initial -- Spool Data v2 Story 3 (DTC retrieval).
# ================================================================================
################################################################################

"""Diagnostic Trouble Code (DTC) retrieval for the Pi collector (US-204).

Spool Data v2 Story 3.  The 2G DSM ECU on the Eclipse supports Mode 03
(``GET_DTC`` -- stored DTCs) universally but Mode 07
(``GET_CURRENT_DTC`` -- pending DTCs) is pre-OBD2-full-compliance and
may return a null frame.  :class:`DtcClient` probes Mode 07 once per
connection and surfaces a :class:`Mode07ProbeResult` so callers can
cache the verdict and skip subsequent calls.

Design invariants honored here (US-204 spec):

* Mode 07 probe result is NOT persisted -- caching is the caller's job
  (typically on the ``ObdConnection`` instance).  Reconnects re-probe.
* DTC descriptions come from ``python-obd``'s internal DTC_MAP via the
  response payload itself -- we do NOT invent descriptions for unknown
  codes like Mitsubishi P1XXX.  Unknown entries get an empty string so
  a later pass can populate them from a DSM cheat sheet without
  rewriting the capture path.
* The client does not open or close DB transactions.  Callers
  (:class:`~src.pi.obdii.dtc_logger.DtcLogger`) own persistence.

The one dependency on ``python-obd`` is the command-factory seam:
``commandFactory('GET_DTC')`` resolves to the real
``obd.commands.GET_DTC`` at runtime but tests inject a string-returning
stub so nothing imports ``obd`` off-Pi.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    'DiagnosticCode',
    'DtcClient',
    'DtcClientError',
    'Mode07ProbeResult',
    'ObdConnectionLike',
    'defaultCommandFactory',
]

logger = logging.getLogger(__name__)


# ================================================================================
# Errors
# ================================================================================


class DtcClientError(RuntimeError):
    """Base class for DtcClient errors.  Currently only the disconnected case."""


# ================================================================================
# Value objects
# ================================================================================


@dataclass(frozen=True)
class DiagnosticCode:
    """A single DTC tuple returned by the ECU.

    Attributes:
        code: Five-character DTC (e.g. ``"P0171"``).
        description: Human-readable label from python-obd's DTC_MAP.
            Empty string when python-obd has no mapping (common for
            Mitsubishi P1XXX codes).  Invariant: never fabricated.
        status: Where the code came from -- ``'stored'`` (Mode 03) or
            ``'pending'`` (Mode 07).  Matches the
            :mod:`src.pi.obdii.dtc_logger` schema CHECK constraint.
    """

    code: str
    description: str
    status: str


@dataclass(frozen=True)
class Mode07ProbeResult:
    """Result of the per-connection Mode 07 support probe.

    Attributes:
        supported: True if the ECU returned a Mode 07 frame (even if
            empty).  False if the response was null / unsupported.
        reason: Short operator-facing tag -- ``'supported'`` /
            ``'unsupported'`` / ``'not_probed'``.
    """

    supported: bool
    reason: str


# ================================================================================
# Connection protocol
# ================================================================================


class ObdConnectionLike(Protocol):
    """Structural interface satisfied by
    :class:`src.pi.obdii.obd_connection.ObdConnection` and test fakes.

    Only ``isConnected()`` + ``.obd.query(cmd)`` are touched.
    """

    def isConnected(self) -> bool: ...

    @property
    def obd(self) -> Any: ...  # python-obd facade exposing query(cmd)


# ================================================================================
# Command factory (python-obd seam)
# ================================================================================


def defaultCommandFactory(name: str) -> Any:
    """Resolve a python-obd command object by name.

    Imports ``obd`` lazily so that off-Pi test contexts (which don't
    install python-obd) aren't broken by module import.  Production
    callers on the Pi get the real command objects.

    Args:
        name: The python-obd command name (e.g. ``'GET_DTC'`` or
            ``'GET_CURRENT_DTC'``).

    Returns:
        The resolved ``obd.commands.<name>`` object.

    Raises:
        DtcClientError: If python-obd isn't installed or the command
            name is not recognized.
    """
    try:
        import obd as obdlib  # type: ignore[import-untyped]
    except ImportError as exc:
        raise DtcClientError(
            f"python-obd is not installed; cannot resolve command {name!r}"
        ) from exc
    cmd = getattr(obdlib.commands, name, None)
    if cmd is None:
        raise DtcClientError(
            f"python-obd has no command named {name!r} "
            "(expected GET_DTC or GET_CURRENT_DTC)"
        )
    return cmd


# ================================================================================
# Core client
# ================================================================================


class DtcClient:
    """Mode 03 + Mode 07 DTC retrieval, stateless between calls.

    Usage::

        client = DtcClient()
        stored = client.readStoredDtcs(connection)
        pending, probe = client.readPendingDtcs(connection)
        if not probe.supported:
            logger.info("Mode 07 unsupported on this ECU")
    """

    _MODE_03_COMMAND_NAME = 'GET_DTC'
    _MODE_07_COMMAND_NAME = 'GET_CURRENT_DTC'

    def __init__(
        self,
        commandFactory: Callable[[str], Any] | None = None,
    ) -> None:
        """Args:
            commandFactory: Optional override for python-obd command
                resolution.  Defaults to :func:`defaultCommandFactory`
                which imports ``obd.commands.<name>`` lazily.  Tests
                inject a string-returning stub so no ``obd`` import
                occurs in off-Pi contexts.
        """
        self._commandFactory = commandFactory or defaultCommandFactory

    # ------------------------------------------------------------------
    # Mode 03 -- stored DTCs
    # ------------------------------------------------------------------

    def readStoredDtcs(
        self, connection: ObdConnectionLike,
    ) -> list[DiagnosticCode]:
        """Query Mode 03 and decode the response into stored DTCs.

        Args:
            connection: Live OBD connection.

        Returns:
            List of :class:`DiagnosticCode` with ``status='stored'``.
            Empty list if the ECU reports no DTCs or returns a null
            frame (both are the healthy case -- no codes set).

        Raises:
            DtcClientError: If ``connection.isConnected()`` is False.
        """
        self._requireConnected(connection)
        cmd = self._commandFactory(self._MODE_03_COMMAND_NAME)
        response = connection.obd.query(cmd)
        raw = self._extractTuples(response)
        return [
            self._asCode(entry, status='stored')
            for entry in raw
            if self._isValidEntry(entry)
        ]

    # ------------------------------------------------------------------
    # Mode 07 -- pending DTCs with probe
    # ------------------------------------------------------------------

    def readPendingDtcs(
        self, connection: ObdConnectionLike,
    ) -> tuple[list[DiagnosticCode], Mode07ProbeResult]:
        """Query Mode 07 and classify the response support level.

        Args:
            connection: Live OBD connection.

        Returns:
            ``(codes, probe)`` tuple.  ``codes`` is an empty list when
            the probe fails (unsupported) or when Mode 07 is supported
            but no pending codes are set.  ``probe.supported`` lets the
            caller distinguish the two cases so the result can be
            cached on the connection.

        Raises:
            DtcClientError: If the connection is not open.
        """
        self._requireConnected(connection)
        cmd = self._commandFactory(self._MODE_07_COMMAND_NAME)
        response = connection.obd.query(cmd)

        if self._isNull(response):
            logger.info(
                "Mode 07 (GET_CURRENT_DTC) returned null -- "
                "treating as unsupported on this ECU"
            )
            return [], Mode07ProbeResult(supported=False, reason='unsupported')

        raw = self._extractTuples(response)
        codes = [
            self._asCode(entry, status='pending')
            for entry in raw
            if self._isValidEntry(entry)
        ]
        return codes, Mode07ProbeResult(supported=True, reason='supported')

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _requireConnected(connection: ObdConnectionLike) -> None:
        if not connection.isConnected():
            raise DtcClientError(
                "DtcClient requires an open connection; obd is not connected"
            )

    @staticmethod
    def _isNull(response: Any) -> bool:
        """Treat None or is_null() -> True as null."""
        if response is None:
            return True
        isNullCallable = getattr(response, 'is_null', None)
        if callable(isNullCallable):
            try:
                return bool(isNullCallable())
            except Exception:  # noqa: BLE001 -- null-check must not raise
                return True
        # No is_null() and value is missing -> treat as null
        return getattr(response, 'value', None) is None

    @staticmethod
    def _extractTuples(response: Any) -> list[Any]:
        """Pull the DTC tuple list out of the response, tolerating shape drift.

        python-obd typically returns ``response.value`` as a list of
        ``(code, description)`` tuples.  None / scalar / non-iterable
        values fall back to an empty list.
        """
        if response is None:
            return []
        value = getattr(response, 'value', None)
        if value is None:
            return []
        try:
            return list(value)
        except TypeError:
            return []

    @staticmethod
    def _isValidEntry(entry: Any) -> bool:
        return isinstance(entry, (tuple, list)) and len(entry) >= 2

    @staticmethod
    def _asCode(entry: Any, *, status: str) -> DiagnosticCode:
        """Normalize one ``(code, description)`` tuple into a DiagnosticCode.

        Unknown descriptions (python-obd returns None when the DTC_MAP
        lacks an entry) collapse to the empty string per invariant #6 --
        never fabricate.
        """
        code = str(entry[0])
        rawDescription = entry[1]
        description = '' if rawDescription is None else str(rawDescription)
        return DiagnosticCode(code=code, description=description, status=status)
