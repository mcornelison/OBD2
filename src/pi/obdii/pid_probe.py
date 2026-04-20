################################################################################
# File Name: pid_probe.py
# Purpose/Description: Mode 01 PID 0x00 support-bitmask probe (US-199)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Ralph Agent  | Initial (US-199 Spool Data v2 Story 1)
# ================================================================================
################################################################################

"""
Per-session supported-PID discovery for Mode 01.

At connection-open time python-obd performs its own auto-probe against
PID 0x00 / 0x20 / 0x40 / 0x60 and exposes the union as
``obd.OBD().supported_commands``. This module normalizes that list into
a :class:`SupportedPidSet` keyed by lowercase two-hex-char PID codes
(``'0x0c'``, ``'0x03'``, ...) so the realtime logger can silently skip
PIDs the ECU does not answer.

Adapter-level commands (``ELM_VOLTAGE`` / ``ATRV``) carry ``pid=None``
because they are not Mode 01 PIDs; they are always treated as supported
by :meth:`SupportedPidSet.isSupported` (caller passes ``None`` as the
PID code).

See specs/obd2-research.md for the empirical Eclipse 1998 2G support
matrix (three confirmed-unsupported PIDs: 0x0A / 0x0B / 0x42).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ================================================================================
# SupportedPidSet
# ================================================================================


@dataclass
class SupportedPidSet:
    """
    Normalized supported-PID set returned by :func:`probeSupportedPids`.

    Attributes:
        supported: Set of lowercase two-hex-char PID codes (e.g. ``'0x0c'``).
            Input is normalized on construction so callers can pass mixed
            case like ``{'0x0C', '0x3'}`` without surprises.
        fallbackAllowAll: When True, :meth:`isSupported` returns True for any
            code — used when the probe could not run (disconnected / no
            python-obd data). Caller still gets silent-skip semantics at
            query time from null-response handling.
    """

    supported: set[str] = field(default_factory=set)
    fallbackAllowAll: bool = False

    def __post_init__(self) -> None:
        self.supported = {_normalizePidCode(c) for c in self.supported}

    @classmethod
    def alwaysSupported(cls) -> SupportedPidSet:
        """Fallback factory: treat every PID code as supported."""
        return cls(supported=set(), fallbackAllowAll=True)

    def isSupported(self, pidCode: str | None) -> bool:
        """
        Return True if the given PID hex code is in the supported set.

        Adapter-level commands pass ``pidCode=None`` — always True because
        they bypass the K-line ECU bandwidth entirely.
        """
        if pidCode is None:
            return True
        if self.fallbackAllowAll:
            return True
        return _normalizePidCode(pidCode) in self.supported

    def __len__(self) -> int:
        return len(self.supported)


# ================================================================================
# probeSupportedPids
# ================================================================================


def probeSupportedPids(obdConnection: Any) -> SupportedPidSet:
    """
    Read python-obd's auto-probed supported-commands list and normalize it.

    Args:
        obdConnection: An :class:`ObdConnection`-shaped facade exposing an
            ``obd`` attribute that in turn exposes ``supported_commands``.

    Returns:
        :class:`SupportedPidSet` keyed by lowercase two-hex-char PID codes.
        Falls back to :meth:`SupportedPidSet.alwaysSupported` when the
        probe cannot run (disconnected, python-obd missing the attribute,
        ``obd=None``).
    """
    obd = getattr(obdConnection, "obd", None)
    if obd is None:
        logger.debug("probeSupportedPids: obd is None — falling back to always-supported")
        return SupportedPidSet.alwaysSupported()

    isConnected = _isConnected(obd)
    if not isConnected:
        logger.debug("probeSupportedPids: not connected — falling back to always-supported")
        return SupportedPidSet.alwaysSupported()

    supportedCmds = getattr(obd, "supported_commands", None)
    if supportedCmds is None:
        logger.debug(
            "probeSupportedPids: obd has no supported_commands — falling back to always-supported"
        )
        return SupportedPidSet.alwaysSupported()

    codes: set[str] = set()
    for cmd in supportedCmds:
        mode = getattr(cmd, "mode", None)
        pidInt = getattr(cmd, "pid", None)
        # Only record Mode 01 PIDs — the probe's bitmap covers Mode 01 exclusively.
        if mode != 1 or pidInt is None:
            continue
        codes.add(_normalizePidCode(hex(pidInt)))

    logger.info("probeSupportedPids: discovered %d Mode 01 PIDs", len(codes))
    return SupportedPidSet(supported=codes)


# ================================================================================
# Internal helpers
# ================================================================================


def _normalizePidCode(raw: str) -> str:
    """Normalize a hex PID representation to lowercase two-hex-char form.

    Accepts ``'0x0C'``, ``'0xc'``, ``'0XC'``, and returns ``'0x0c'``.
    """
    text = raw.strip().lower()
    if text.startswith("0x"):
        digits = text[2:]
    else:
        digits = text
    return f"0x{digits.zfill(2)}"


def _isConnected(obd: Any) -> bool:
    """Best-effort connected check that tolerates mocks and real python-obd alike."""
    check = getattr(obd, "is_connected", None)
    if callable(check):
        try:
            return bool(check())
        except Exception:  # noqa: BLE001 — tolerate mock misbehavior
            return False
    return False
