################################################################################
# File Name: alerts_ack_channel.py
# Purpose/Description: US-897-c (F-127, Atlas s3 + Q20-Q27) -- the cross-process
#   channel that lets POST /alerts-ack reach the one process that writes the
#   alerts acknowledgement store.
#
#   WHY A CHANNEL.  eclipse-states-http and eclipse-obd are SEPARATE PROCESSES.
#   The orchestrator holds the alerts arbiter, the ack store and the states/
#   alerts emit; an ack written by the HTTP process would never reach the
#   published entry.  So the HTTP process asks and the orchestrator answers over
#   the shared `request_channel` (US-897-c0) -- the third caller, never a third
#   copy of the loop.
#
#   THE CONTRACT.  Request ``{requestId, ids, requestedAtEpoch}``; outcome
#   ``{requestId, ok, error, ids, completedAtEpoch}``.  ``error`` is null on
#   success, else ``unknown_id`` / ``not_ackable`` (``ids`` = the bad ones,
#   nothing recorded -- all or nothing, Atlas Q26) or ``store_write_failed``.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-20    | Rex (US-897-c) | Initial -- on US-897-c0's RequestChannel.
# ================================================================================
################################################################################

"""Request/outcome file channel for the alerts acknowledgement (US-897-c)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from pi.splash.request_channel import (
    RequestChannel,
    RequestChannelPublishError,
    RequestChannelTimeout,
)

__all__ = [
    "AckBridgeError",
    "AckBridgeTimeout",
    "OUTCOME_FILENAME",
    "REQUEST_FILENAME",
    "consumeRequest",
    "makeBridgeAckRunner",
    "readOutcome",
    "readRequest",
    "writeOutcome",
    "writeRequest",
]

#: Both files live in the tmpfs states dir the two units already share.
REQUEST_FILENAME = "alerts-ack-request.json"
OUTCOME_FILENAME = "alerts-ack-outcome.json"

#: The shared channel over this module's two files.
_CHANNEL = RequestChannel(REQUEST_FILENAME, OUTCOME_FILENAME)


class AckBridgeError(RuntimeError):
    """The request could not be published -- there is no states channel."""


class AckBridgeTimeout(RuntimeError):
    """No outcome arrived for THIS request inside the budget.

    Not an ``AckBridgeError`` (the fuel-reset precedent): it means "we do not
    know", not "there is no channel", and the route answers the two differently.
    """


# ==============================================================================
# Request -- written by the HTTP process, read by the orchestrator
# ==============================================================================


def writeRequest(
    statesDir: str,
    requestId: str,
    ids: Sequence[str],
    *,
    nowFn: Callable[[], float] = time.time,
) -> None:
    """Publish an ack request for the orchestrator to service."""
    _CHANNEL.writeRequest(statesDir, requestId, nowFn=nowFn, requestFields={"ids": list(ids)})


def readRequest(statesDir: str) -> dict[str, Any] | None:
    """Read the pending request, or None (a corrupt file reads as None)."""
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
    error: str | None,
    ids: Sequence[Any],
    nowFn: Callable[[], float] = time.time,
) -> None:
    """Publish the result of servicing ``requestId`` (echoed back)."""
    _CHANNEL.writeOutcome(
        statesDir,
        {"requestId": requestId, "ok": bool(ok), "error": error, "ids": list(ids)},
        nowFn=nowFn,
    )


def readOutcome(statesDir: str) -> dict[str, Any] | None:
    """Read the most recent outcome, or None."""
    return _CHANNEL.readOutcome(statesDir)


# ==============================================================================
# The bridge -- what POST /alerts-ack calls
# ==============================================================================


def makeBridgeAckRunner(
    statesDir: str,
    *,
    timeoutSeconds: float,
    nowFn: Callable[[], float] = time.monotonic,
    sleepFn: Callable[[float], None] = time.sleep,
    idFn: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> Callable[[Sequence[str]], dict[str, Any]]:
    """Build the runner the route calls with the request's ids.

    Args:
        statesDir: The shared tmpfs states directory.
        timeoutSeconds: Budget for the orchestrator to answer
            (``pi.warnings.ackTimeoutSec``).
        nowFn: Monotonic clock (injectable for tests).
        sleepFn: Sleep (injectable for tests).
        idFn: Request-id factory (injectable for tests).

    Returns:
        ``runner(ids)`` returning ``{"ok": bool, "error": str|None, "ids": list}``.

    Raises:
        AckBridgeError: the request could not be published.
        AckBridgeTimeout: no outcome for this request inside the budget.
    """

    def runner(ids: Sequence[str]) -> dict[str, Any]:
        try:
            outcome = _CHANNEL.awaitOutcome(
                statesDir,
                timeoutSeconds=timeoutSeconds,
                requestFields={"ids": list(ids)},
                nowFn=nowFn,
                wallFn=time.time,
                sleepFn=sleepFn,
                idFn=idFn,
            )
        except RequestChannelPublishError as exc:
            raise AckBridgeError(
                f"could not publish the alerts ack request to {statesDir}: {exc.cause}"
            ) from exc.cause
        except RequestChannelTimeout as exc:
            # The channel has already withdrawn the request so it cannot fire later.
            raise AckBridgeTimeout(
                f"no answer from the OBD service within {timeoutSeconds:g}s"
            ) from exc
        bad = outcome.get("ids")
        return {
            "ok": outcome.get("ok") is True,
            "error": outcome.get("error"),
            "ids": list(bad) if isinstance(bad, list) else [],
        }

    return runner
