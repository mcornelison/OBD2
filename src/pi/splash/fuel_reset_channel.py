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
#   orchestrator answers -- the same shared `request_channel` the DTC clear
#   rides (US-897-c0); this module keeps its own filenames, exception classes,
#   messages and the return-on-refusal shape.
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
# 2026-10-20    | Rex (US-897-c0) | Thin wrapper over request_channel; every
#               |                 | public name, message and shape unchanged.
# ================================================================================
################################################################################

"""Request/outcome file channel for the since-reset fuel totals reset (US-881-d)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

# Poll the same way, at the same cadence, as the DTC channel: a stat on tmpfs.
from pi.splash.request_channel import (
    POLL_INTERVAL_SECONDS,
    RequestChannel,
    RequestChannelPublishError,
    RequestChannelTimeout,
)

__all__ = [
    "OUTCOME_FILENAME",
    "POLL_INTERVAL_SECONDS",
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

#: The shared channel over this module's two files.
_CHANNEL = RequestChannel(REQUEST_FILENAME, OUTCOME_FILENAME)


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
    _CHANNEL.writeRequest(statesDir, requestId, nowFn=nowFn)


def readRequest(statesDir: str) -> dict[str, Any] | None:
    """Read the pending request, or None when there is none.

    A corrupt or half-written file reads as None: this is polled from the
    orchestrator's run loop, and a malformed request must never take capture
    down.  The requester then times out honestly.
    """
    return _CHANNEL.readRequest(statesDir)


def consumeRequest(statesDir: str) -> None:
    """Remove the request once it has been serviced (or abandoned). Idempotent."""
    _CHANNEL.consumeRequest(statesDir)


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
    _CHANNEL.writeOutcome(
        statesDir,
        {
            "requestId": requestId,
            "ok": bool(ok),
            "reason": reason,
            "resetAtTs": resetAtTs,
        },
        nowFn=nowFn,
    )


def readOutcome(statesDir: str) -> dict[str, Any] | None:
    """Read the most recent outcome, or None."""
    return _CHANNEL.readOutcome(statesDir)


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
        # The channel's requestId match stops a LEFTOVER outcome answering this press.
        try:
            outcome = _CHANNEL.awaitOutcome(
                statesDir,
                timeoutSeconds=timeoutSeconds,
                nowFn=nowFn,
                wallFn=time.time,
                sleepFn=sleepFn,
                idFn=idFn,
            )
        except RequestChannelPublishError as exc:
            raise ResetBridgeError(
                f"could not publish the fuel reset request to {statesDir}: {exc.cause}"
            ) from exc.cause
        except RequestChannelTimeout as exc:
            # The channel has already withdrawn the request so it cannot fire later.
            raise ResetBridgeTimeout(
                f"no answer from the OBD service within {timeoutSeconds:g}s"
            ) from exc
        return {
            "ok": bool(outcome.get("ok", False)),
            "reason": outcome.get("reason"),
            "resetAtTs": outcome.get("resetAtTs"),
        }

    return runner
