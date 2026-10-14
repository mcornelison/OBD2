################################################################################
# File Name: fuel_reset_channel.py
# Purpose/Description: US-881-d (F-159, Atlas gap 4) -- the cross-process
#   channel that lets POST /fuel-reset reach the one process that owns the
#   fuel_since_reset row.
#
#   WHY A CHANNEL.  eclipse-states-http and eclipse-obd are SEPARATE PROCESSES.
#   The orchestrator holds the database handle, the provider's cached sinceReset
#   and its persist watermark; a reset that touched the table from the HTTP
#   process would leave the other two behind, and the next persist would write
#   pre-reset accumulation back in.  So the HTTP process asks and the
#   orchestrator answers -- the dtc_clear_channel pattern, copied into its own
#   module (the DTC channel is not generalised).
#
#   THE CONTRACT.  Request ``{requestId, requestedAtEpoch}``; outcome
#   ``{requestId, ok, reason, resetAtTs, completedAtEpoch}``.  ``requestId`` is
#   echoed so a leftover outcome can never answer a later request.  A refusal
#   (``ok: false``) names its reason (``driving`` while a drive is recording).
#
#   Both files are written temp + os.replace via the shared writeStateAtomic, so
#   a reader never sees a torn payload.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-881-d) | Initial -- request/outcome channel + the bridge
#               |                | runner POST /fuel-reset calls.
# ================================================================================
################################################################################

"""Request/outcome file channel for the since-reset fuel totals reset (US-881-d)."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pi.splash.boot_state_emitter import writeStateAtomic

# Poll the same way, at the same cadence, as the DTC channel: a stat on tmpfs.
from pi.splash.dtc_clear_channel import POLL_INTERVAL_SECONDS

__all__ = [
    "OUTCOME_FILENAME",
    "REQUEST_FILENAME",
    "ResetBridgeError",
    "ResetBridgeTimeout",
    "consumeRequest",
    "makeBridgeResetRunner",
    "readOutcome",
    "readRequest",
    "writeOutcome",
    "writeRequest",
]

#: Both files live in the tmpfs states dir the two units already share.
REQUEST_FILENAME = "fuel-reset-request.json"
OUTCOME_FILENAME = "fuel-reset-outcome.json"


class ResetBridgeError(RuntimeError):
    """The request could not be published -- there is no states channel."""


class ResetBridgeTimeout(RuntimeError):
    """No outcome arrived for THIS request inside the budget.

    Deliberately not a ``ResetBridgeError``: it means "we do not know", not
    "there is no channel", and the route answers the two differently.
    """


# ==============================================================================
# Request -- written by the HTTP process, read by the orchestrator
# ==============================================================================


def writeRequest(
    statesDir: str,
    requestId: str,
    *,
    nowFn: Callable[[], float] = time.time,
) -> None:
    """Publish a reset request for the orchestrator to service."""
    writeStateAtomic(
        str(Path(statesDir) / REQUEST_FILENAME),
        {"requestId": requestId, "requestedAtEpoch": nowFn()},
    )


def readRequest(statesDir: str) -> dict[str, Any] | None:
    """Read the pending request, or None when there is none.

    A corrupt or half-written file reads as None: this is polled from the
    orchestrator's run loop, and a malformed request must never take capture
    down.  The requester then times out honestly.
    """
    return _readJson(Path(statesDir) / REQUEST_FILENAME)


def consumeRequest(statesDir: str) -> None:
    """Remove the request once it has been serviced (or abandoned). Idempotent."""
    try:
        (Path(statesDir) / REQUEST_FILENAME).unlink()
    except OSError:
        pass


# ==============================================================================
# Outcome -- written by the orchestrator, read by the HTTP process
# ==============================================================================


def writeOutcome(
    statesDir: str,
    *,
    requestId: str,
    ok: bool,
    reason: str | None,
    resetAtTs: str | None,
    nowFn: Callable[[], float] = time.time,
) -> None:
    """Publish the result of servicing ``requestId`` (echoed back)."""
    writeStateAtomic(
        str(Path(statesDir) / OUTCOME_FILENAME),
        {
            "requestId": requestId,
            "ok": bool(ok),
            "reason": reason,
            "resetAtTs": resetAtTs,
            "completedAtEpoch": nowFn(),
        },
    )


def readOutcome(statesDir: str) -> dict[str, Any] | None:
    """Read the most recent outcome, or None."""
    return _readJson(Path(statesDir) / OUTCOME_FILENAME)


# ==============================================================================
# The bridge -- what POST /fuel-reset calls
# ==============================================================================


def makeBridgeResetRunner(
    statesDir: str,
    *,
    timeoutSeconds: float,
    nowFn: Callable[[], float] = time.monotonic,
    sleepFn: Callable[[float], None] = time.sleep,
    idFn: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> Callable[[], dict[str, Any]]:
    """Build the zero-arg runner the route calls.

    Publishes a request and waits for the orchestrator's outcome for THAT
    request id.

    Args:
        statesDir: The shared tmpfs states directory.
        timeoutSeconds: Budget for the orchestrator to answer
            (``pi.fuel.resetTimeoutSec``).
        nowFn: Monotonic clock (injectable for tests).
        sleepFn: Sleep (injectable for tests).
        idFn: Request-id factory (injectable for tests).

    Returns:
        A callable returning ``{"ok": bool, "reason": str|None,
        "resetAtTs": str|None}``.

    Raises:
        ResetBridgeError: the request could not be published.
        ResetBridgeTimeout: no outcome for this request inside the budget.
    """

    def runner() -> dict[str, Any]:
        requestId = idFn()
        try:
            writeRequest(statesDir, requestId)
        except OSError as exc:
            raise ResetBridgeError(
                f"could not publish the fuel reset request to {statesDir}: {exc}"
            ) from exc

        deadline = nowFn() + timeoutSeconds
        while True:
            outcome = readOutcome(statesDir)
            # The requestId match stops a LEFTOVER outcome answering this press.
            if isinstance(outcome, Mapping) and outcome.get("requestId") == requestId:
                return {
                    "ok": bool(outcome.get("ok", False)),
                    "reason": outcome.get("reason"),
                    "resetAtTs": outcome.get("resetAtTs"),
                }
            if nowFn() >= deadline:
                consumeRequest(statesDir)  # do not leave it to fire later
                raise ResetBridgeTimeout(
                    f"no answer from the OBD service within {timeoutSeconds:g}s"
                )
            sleepFn(POLL_INTERVAL_SECONDS)

    return runner


# ==============================================================================
# Internals
# ==============================================================================


def _readJson(path: Path) -> dict[str, Any] | None:
    """Read a JSON object, or None when absent/unreadable/not an object."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
