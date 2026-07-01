################################################################################
# File Name: dtc_clear.py
# Purpose/Description: US-407 [F-111] AUTHORITATIVE clear-gate SSOT + Mode-04
#   clear orchestration. This is the load-bearing safety layer for the only DTC
#   path that WRITES to the vehicle. The gate is RE-DERIVED here from the raw
#   captured codes at the privileged action path -- it NEVER trusts the UI's (or
#   the emitter's) precomputed `clearGate.enabled` flag, so a tampered or stale
#   kiosk can never force a clear (S-10 / F-3; the DTC analog of US-403's
#   action-path allow-list re-check in service_control.py).
#
#   Gate (Spool advisory sec 4b, NON-NEGOTIABLE): Mode 04 is all-or-nothing (it
#   wipes EVERY stored+pending code, the freeze-frame, and resets readiness
#   monitors), so the gate keys off ALL stored codes, not the one on screen. It is
#   ENABLED only when every stored (non-`na`) code is MINOR (green) AND logged AND
#   server-sync-acked, and no code re-set this session. Any STOP/WATCH ->
#   `severity_present`; an un-synced MINOR -> `sync_pending`; a returned code (in
#   sessionResetLock) -> `session_locked` ("don't chase the light", advisory
#   sec 4d).
#
#   performClear refuses to invoke the injected vehicle-write runner when the gate
#   fails (no wipe, no freeze-frame destroyed), and detects an instant re-set from
#   the post-clear re-read so US-407 can lock Clear for the session.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial implementation (US-407 clear gate).
# ================================================================================
################################################################################

"""Authoritative DTC clear gate + Mode-04 clear orchestration (US-407)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

# Severity tokens (mirrors dtc_severity_table / the `dtc` state schema). Only a
# MINOR (green) code is ever clear-eligible; `na` is not a real fault on this car.
_SEVERITY_MINOR = "minor"
_SEVERITY_NA = "na"

# Gate reasons (design-spec sec 6.1 + advisory sec 4). `ok` is the only enabled
# state; the rest are honest disable reasons the UI renders verbatim.
GATE_OK = "ok"
GATE_SEVERITY = "severity_present"
GATE_SYNC = "sync_pending"
GATE_NO_CODES = "no_codes"
GATE_SESSION_LOCKED = "session_locked"

__all__ = [
    "GATE_NO_CODES",
    "GATE_OK",
    "GATE_SESSION_LOCKED",
    "GATE_SEVERITY",
    "GATE_SYNC",
    "ClearGateDecision",
    "ClearOutcome",
    "evaluateClearGate",
    "performClear",
]


@dataclass(frozen=True)
class ClearGateDecision:
    """The authoritative clear-gate verdict.

    Attributes:
        enabled: True only when every stored (non-``na``) code is MINOR, logged,
            server-sync-acked, and none re-set this session.
        reason: ``ok`` when enabled; otherwise the honest disable cause
            (``severity_present`` / ``sync_pending`` / ``no_codes`` /
            ``session_locked``).
    """

    enabled: bool
    reason: str


@dataclass(frozen=True)
class ClearOutcome:
    """The result of a clear attempt at the privileged action path.

    Attributes:
        issued: True iff the gate passed and the Mode-04 runner was invoked. When
            False, no vehicle-write occurred (the gate rejected it).
        reason: The gate reason (``ok`` when issued, else the disable cause).
        cleared: True iff the post-clear re-read proved 0 stored, 0 pending, and
            MIL off. False when a code returned immediately.
        storedAfter: Stored code strings from the post-clear re-read.
        pendingAfter: Pending code strings from the post-clear re-read.
        milAfter: Whether the MIL is still reported lit after the re-read.
        reSetCodes: Codes present before AND after the wipe (instant re-set) ->
            US-407 locks Clear for the session for these.
    """

    issued: bool
    reason: str
    cleared: bool
    storedAfter: list[str]
    pendingAfter: list[str]
    milAfter: bool
    reSetCodes: list[str]


def _relevantStored(dtcState: Mapping) -> list[Mapping]:
    """Return the stored codes that gate the all-or-nothing clear.

    Pending codes are informational; ``na`` codes (auto-trans P1xxx on this
    manual car) are not real faults -- neither participates in the gate.
    """
    codes = dtcState.get("codes") or []
    return [
        c
        for c in codes
        if isinstance(c, Mapping)
        and c.get("status") == "stored"
        and c.get("severity") != _SEVERITY_NA
    ]


def evaluateClearGate(dtcState: Mapping) -> ClearGateDecision:
    """Re-derive the clear gate from the raw codes (the S-10 / F-3 safety re-check).

    This deliberately IGNORES any precomputed ``clearGate.enabled`` in the state:
    the gate is recomputed from the codes so a tampered or stale UI can never
    force a clear. The order of the disable checks yields the most operator-
    relevant reason (severity first, then capture/sync, then the session lock).

    Args:
        dtcState: The current ``dtc`` state mapping (see the emitter schema).

    Returns:
        A :class:`ClearGateDecision`.
    """
    relevant = _relevantStored(dtcState)
    if not relevant:
        return ClearGateDecision(enabled=False, reason=GATE_NO_CODES)
    if any(c.get("severity") != _SEVERITY_MINOR for c in relevant):
        return ClearGateDecision(enabled=False, reason=GATE_SEVERITY)
    if any(not (c.get("logged") and c.get("syncAcked")) for c in relevant):
        return ClearGateDecision(enabled=False, reason=GATE_SYNC)
    lock = set(dtcState.get("sessionResetLock") or [])
    if any(c.get("code") in lock for c in relevant):
        return ClearGateDecision(enabled=False, reason=GATE_SESSION_LOCKED)
    return ClearGateDecision(enabled=True, reason=GATE_OK)


def _codesPresentBefore(dtcState: Mapping) -> set[str]:
    codes = dtcState.get("codes") or []
    return {
        str(c.get("code"))
        for c in codes
        if isinstance(c, Mapping) and c.get("status") in ("stored", "pending")
    }


def performClear(
    dtcState: Mapping,
    *,
    clearRunner: Callable[[], Mapping],
) -> ClearOutcome:
    """Re-check the gate, then (only if it passes) issue the Mode-04 clear.

    The gate is re-evaluated HERE from the raw codes; if it fails, ``clearRunner``
    is NEVER called -- no vehicle-write, no freeze-frame destroyed (S-10 / F-2 /
    F-4). On success the runner issues Mode 04 and returns the immediate re-read
    (``{"stored": [...], "pending": [...], "mil": bool}``, code strings); any code
    present before AND after the wipe is an instant re-set flagged to lock Clear
    for the session (advisory sec 4d).

    Args:
        dtcState: The current ``dtc`` state mapping.
        clearRunner: Zero-arg callable that issues Mode 04 + re-reads Mode 03(+07)
            and returns the after-state. Injected by the connection owner (the
            orchestrator on the Pi); tests supply a fake.

    Returns:
        A :class:`ClearOutcome`.
    """
    decision = evaluateClearGate(dtcState)
    if not decision.enabled:
        return ClearOutcome(
            issued=False,
            reason=decision.reason,
            cleared=False,
            storedAfter=[],
            pendingAfter=[],
            milAfter=False,
            reSetCodes=[],
        )

    before = _codesPresentBefore(dtcState)
    readback = clearRunner()
    storedAfter = [str(c) for c in (readback.get("stored") or [])]
    pendingAfter = [str(c) for c in (readback.get("pending") or [])]
    milAfter = bool(readback.get("mil", False))
    afterSet = set(storedAfter) | set(pendingAfter)
    reSetCodes = sorted(before & afterSet)
    cleared = not storedAfter and not pendingAfter and not milAfter

    return ClearOutcome(
        issued=True,
        reason=GATE_OK,
        cleared=cleared,
        storedAfter=storedAfter,
        pendingAfter=pendingAfter,
        milAfter=milAfter,
        reSetCodes=reSetCodes,
    )
