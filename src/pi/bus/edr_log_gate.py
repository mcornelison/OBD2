################################################################################
# File Name: edr_log_gate.py
# Purpose/Description: US-767-b -- decides WHEN EDR sensor rows are written.
#                      OPEN while the OBD link is up; CLOSED holds a monotonic
#                      pre-roll ring and writes nothing, and opening flushes that
#                      ring in order; OPEN->HOLD keeps writing for holdSec after
#                      the link drops and re-arms if it returns. The gate reads
#                      two producer facts (ConnectionStatus.connected and
#                      .signalReadable) and follows Atlas's fail-OPEN table: a
#                      signal it cannot read -- unreadable, raising, or not wired
#                      -- keeps the gate OPEN. A black box that silently drops
#                      drive data is worse than keeping garage rows.
#                      Design: Atlas, superpowers/plans/2026-09-14-us734-edr-
#                      server-sync.md Task 7; spec: specs/architecture.md 10.8.
# Author: Rex (US-767-b)
# Creation Date: 2026-09-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-18    | Rex (US-767-b) | Initial -- two-input gate, pre-roll, hold,
#               |                | fail-OPEN, enabled=False pass-through.
# ================================================================================
################################################################################
"""Link-gated EDR logging state machine (US-767-b)."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_HOLD_SEC",
    "DEFAULT_PRE_ROLL_SEC",
    "GATE_CLOSED",
    "GATE_HOLD",
    "GATE_OPEN",
    "EdrLogGate",
    "LinkSignal",
]

GATE_CLOSED = "closed"
GATE_OPEN = "open"
GATE_HOLD = "hold"

# Atlas's US-734 plan (Tasks 7-8); mirrored by validator DEFAULTS
# pi.sensors.logGate.{preRollSec,holdSec}.
DEFAULT_PRE_ROLL_SEC = 60.0
DEFAULT_HOLD_SEC = 300.0

# Minimum seconds between "signal unreadable" WARNINGs (Atlas's plan, Task 7).
_WARN_INTERVAL_S = 60.0


class LinkSignal(Protocol):
    """The two producer facts the gate reads (``ObdConnection.getStatus()``)."""

    connected: bool
    signalReadable: bool


class EdrLogGate:
    """Admit EDR rows only while linked, with a pre-roll and a hold.

    ``admit(table, row)`` returns the ``(table, row)`` pairs to write NOW, oldest
    first. Rows are opaque to the gate; it only orders and buffers them.

    Atlas's fail-OPEN table (specs/architecture.md 10.8):

    ============  ================  ======
    connected     signalReadable    gate
    ============  ================  ======
    False         True              CLOSED -- link genuinely down, buffer
    False         False             OPEN -- cannot tell; rate-limited WARNING
    True          True              OPEN
    ============  ================  ======

    A signal callable that raises, or no callable at all, is signalReadable
    False. ``enabled=False`` is always OPEN and never reads the signal.
    """

    def __init__(
        self,
        linkSignalFn: Callable[[], LinkSignal] | None,
        *,
        enabled: bool = False,
        preRollSec: float = DEFAULT_PRE_ROLL_SEC,
        holdSec: float = DEFAULT_HOLD_SEC,
        monotonicFn: Callable[[], float] = time.monotonic,
    ) -> None:
        """Build the gate.

        Args:
            linkSignalFn: Returns the current link facts (``connected``,
                ``signalReadable``). None means no signal is wired, which the
                gate treats as unreadable -> OPEN.
            enabled: False (the default) makes the gate a pass-through: always
                OPEN, never buffering, never reading the signal. Defaulting off
                means a caller that forgets the flag never loses a row.
            preRollSec: Seconds of CLOSED rows kept and written when it opens.
            holdSec: Seconds rows keep landing after the link drops.
            monotonicFn: Monotonic clock (injected for tests).

        Raises:
            ValueError: If preRollSec or holdSec is not positive.
        """
        if preRollSec <= 0:
            raise ValueError(f"preRollSec must be positive (got {preRollSec!r})")
        if holdSec <= 0:
            raise ValueError(f"holdSec must be positive (got {holdSec!r})")
        self._linkSignalFn = linkSignalFn
        self._enabled = bool(enabled)
        self._preRollSec = float(preRollSec)
        self._holdSec = float(holdSec)
        self._now = monotonicFn
        self._state = GATE_CLOSED if self._enabled else GATE_OPEN
        self._holdUntil: float | None = None
        self._ring: deque[tuple[float, str, Any]] = deque()
        self._lastTransition: tuple[str, str, str] | None = None
        self._lastWarn: float | None = None

    @property
    def enabled(self) -> bool:
        """True when the gate can close; False is a pass-through."""
        return self._enabled

    @property
    def preRollSec(self) -> float:
        """Seconds of CLOSED rows written when the gate opens."""
        return self._preRollSec

    @property
    def holdSec(self) -> float:
        """Seconds rows keep landing after the link drops."""
        return self._holdSec

    @property
    def state(self) -> str:
        """One of GATE_CLOSED, GATE_OPEN, GATE_HOLD."""
        return self._state

    @property
    def lastTransition(self) -> tuple[str, str, str] | None:
        """The most recent ``(from, to, reason)``, or None before any."""
        return self._lastTransition

    @property
    def bufferedRows(self) -> int:
        """Rows currently held in the pre-roll ring."""
        return len(self._ring)

    def _readLink(self, now: float) -> tuple[bool, str]:
        """Return (openGate, reason) from the signal, failing OPEN."""
        failure: object
        if self._linkSignalFn is None:
            failure = "no link signal wired"
        else:
            try:
                status = self._linkSignalFn()
                connected = bool(status.connected)
                readable = bool(status.signalReadable)
            except Exception as exc:  # noqa: BLE001 -- fail OPEN, never closed
                failure = exc
            else:
                if readable:
                    return connected, "link_linked" if connected else "link_lost"
                failure = "signalReadable=False"
        if self._lastWarn is None or now - self._lastWarn >= _WARN_INTERVAL_S:
            self._lastWarn = now
            logger.warning(
                "EDR log gate: link signal unreadable (%s) -- failing OPEN", failure
            )
        return True, "signal_unreadable"

    def _transition(self, to: str, reason: str, buffered: int = 0) -> None:
        if to == self._state:
            return
        self._lastTransition = (self._state, to, reason)
        logger.info(
            "EDR log gate: %s->%s reason=%s buffered=%d",
            self._state.upper(), to.upper(), reason, buffered,
        )
        self._state = to

    def admit(self, table: str, row: Any) -> list[tuple[str, Any]]:
        """Offer one row; return the rows to write now, oldest first.

        Args:
            table: The row's destination table key.
            row: The row payload (opaque to the gate).

        Returns:
            ``(table, row)`` pairs to write now -- empty while CLOSED, the
            flushed pre-roll plus this row on opening, else just this row.
        """
        if not self._enabled:
            return [(table, row)]
        now = self._now()
        isOpen, reason = self._readLink(now)
        if isOpen:
            self._holdUntil = None
            if self._state == GATE_CLOSED:
                flushed = [
                    (t, r) for ts, t, r in self._ring if now - ts <= self._preRollSec
                ]
                self._ring.clear()
                self._transition(GATE_OPEN, reason, buffered=len(flushed))
                return flushed + [(table, row)]
            self._transition(GATE_OPEN, reason)
            return [(table, row)]

        if self._state == GATE_OPEN:
            self._holdUntil = now + self._holdSec
            self._transition(GATE_HOLD, reason)
        if self._state == GATE_HOLD:
            if self._holdUntil is not None and now <= self._holdUntil:
                return [(table, row)]
            self._transition(GATE_CLOSED, "hold_expired")
            self._holdUntil = None

        self._ring.append((now, table, row))
        while self._ring and now - self._ring[0][0] > self._preRollSec:
            self._ring.popleft()
        return []
