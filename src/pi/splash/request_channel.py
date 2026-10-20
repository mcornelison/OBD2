################################################################################
# File Name: request_channel.py
# Purpose/Description: US-897-c0 (Atlas s3 + Q19) -- the ONE request/outcome
#   file channel the HTTP process uses to ask the orchestrator for an action.
#
#   WHY ONE.  /dtc-clear (ARCH-023) and /fuel-reset (US-881-d) each carried a
#   copy of the same channel: write a request, poll for the outcome that echoes
#   its requestId, withdraw the request on timeout.  The alerts ack would have
#   been a third copy.  This module owns that mechanism once; each route keeps
#   its own thin wrapper (filenames, exception classes, messages, return shape)
#   in `dtc_clear_channel` / `fuel_reset_channel`.
#
#   WHY A CHANNEL.  eclipse-states-http and eclipse-obd are SEPARATE PROCESSES,
#   and only the orchestrator owns the ECU connection and the database handle.
#   So the HTTP process asks and the process that owns the resource answers
#   (`specs/ssot-design-pattern.md` rule B).
#
#   THE CONTRACT.  Request ``{requestId, requestedAtEpoch, **requestFields}``;
#   outcome ``{requestId, ..., completedAtEpoch}``.  ``requestId`` is echoed so
#   a LEFTOVER outcome can never answer a later request.
#
#   The errors here are NEUTRAL on purpose: what a timeout or a publish failure
#   MEANS (and whether a timeout is a kind of bridge error) differs per route,
#   so each wrapper maps them onto its own classes and words.
#
#   Both files are written temp + os.replace via the shared writeStateAtomic, so
#   a reader never sees a torn payload and a power cut mid-write cannot leave a
#   zero-byte file (the US-682 lesson).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-20    | Rex (US-897-c0) | Initial -- extracted from dtc_clear_channel
#               |                 | and fuel_reset_channel (pure refactor).
# ================================================================================
################################################################################

"""The shared request/outcome file channel behind the HTTP -> orchestrator asks."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pi.splash.boot_state_emitter import writeStateAtomic

__all__ = [
    "POLL_INTERVAL_SECONDS",
    "RequestChannel",
    "RequestChannelPublishError",
    "RequestChannelTimeout",
]

#: Poll cadence while waiting for an outcome.  Cheap: a stat on tmpfs.
POLL_INTERVAL_SECONDS = 0.25


class RequestChannelPublishError(RuntimeError):
    """The request could not be written to the states dir.

    Attributes:
        statesDir: The directory the request was written to.
        cause: The underlying ``OSError`` (also the ``__cause__``).
    """

    def __init__(self, statesDir: str, cause: OSError) -> None:
        super().__init__(f"could not publish the request to {statesDir}: {cause}")
        self.statesDir = statesDir
        self.cause = cause


class RequestChannelTimeout(RuntimeError):
    """No outcome arrived for THIS request inside the budget.

    It means "we do not know", not "the action failed".  The request has
    already been withdrawn so it cannot fire later.

    Attributes:
        timeoutSeconds: The budget that ran out.
    """

    def __init__(self, timeoutSeconds: float) -> None:
        super().__init__(f"no outcome within {timeoutSeconds:g}s")
        self.timeoutSeconds = timeoutSeconds


class RequestChannel:
    """One request/outcome file pair in the shared tmpfs states dir.

    Args:
        requestFilename: Filename the HTTP process writes and the orchestrator
            reads and consumes.
        outcomeFilename: Filename the orchestrator writes and the HTTP process
            polls.
    """

    def __init__(self, requestFilename: str, outcomeFilename: str) -> None:
        self.requestFilename = requestFilename
        self.outcomeFilename = outcomeFilename

    # --------------------------------------------------------------------------
    # Request -- written by the HTTP process, read by the orchestrator
    # --------------------------------------------------------------------------

    def writeRequest(
        self,
        statesDir: str,
        requestId: str,
        *,
        nowFn: Callable[[], float] = time.time,
        requestFields: Mapping[str, Any] | None = None,
    ) -> None:
        """Publish a request for the orchestrator to service.

        ``requestFields`` add to the payload but can never replace
        ``requestId`` or ``requestedAtEpoch``: the id match is what stops a
        leftover outcome answering this request.

        Raises:
            OSError: the file could not be written.
        """
        payload: dict[str, Any] = dict(requestFields or {})
        payload.update({"requestId": requestId, "requestedAtEpoch": nowFn()})
        writeStateAtomic(str(Path(statesDir) / self.requestFilename), payload)

    def readRequest(self, statesDir: str) -> dict[str, Any] | None:
        """Read the pending request, or None when there is none.

        A corrupt or half-written file reads as None: this is polled from the
        orchestrator's run loop, and a malformed request must never take
        capture down.  The requester then times out honestly.
        """
        return _readJson(Path(statesDir) / self.requestFilename)

    def consumeRequest(self, statesDir: str) -> None:
        """Remove the request once it has been serviced (or abandoned). Idempotent."""
        try:
            (Path(statesDir) / self.requestFilename).unlink()
        except OSError:
            pass

    # --------------------------------------------------------------------------
    # Outcome -- written by the orchestrator, read by the HTTP process
    # --------------------------------------------------------------------------

    def writeOutcome(
        self,
        statesDir: str,
        fields: Mapping[str, Any],
        *,
        nowFn: Callable[[], float] = time.time,
    ) -> None:
        """Publish an outcome; ``fields`` must carry the echoed ``requestId``."""
        payload: dict[str, Any] = dict(fields)
        payload["completedAtEpoch"] = nowFn()
        writeStateAtomic(str(Path(statesDir) / self.outcomeFilename), payload)

    def readOutcome(self, statesDir: str) -> dict[str, Any] | None:
        """Read the most recent outcome, or None."""
        return _readJson(Path(statesDir) / self.outcomeFilename)

    # --------------------------------------------------------------------------
    # The one poll loop
    # --------------------------------------------------------------------------

    def awaitOutcome(
        self,
        statesDir: str,
        *,
        timeoutSeconds: float,
        requestFields: Mapping[str, Any] | None = None,
        nowFn: Callable[[], float] = time.monotonic,
        wallFn: Callable[[], float] = time.time,
        sleepFn: Callable[[float], None] = time.sleep,
        idFn: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> dict[str, Any]:
        """Publish a request and wait for the outcome that answers IT.

        Args:
            statesDir: The shared tmpfs states directory.
            timeoutSeconds: Budget for the orchestrator to answer.
            requestFields: Extra fields for the request payload.
            nowFn: Monotonic clock bounding the deadline (injectable).
            wallFn: Wall clock stamping ``requestedAtEpoch`` (injectable).
            sleepFn: Sleep (injectable).
            idFn: Request-id factory (injectable).

        Returns:
            The outcome whose ``requestId`` matches this request.

        Raises:
            RequestChannelPublishError: the request could not be written.
            RequestChannelTimeout: no matching outcome inside the budget; the
                request has been withdrawn.
        """
        requestId = idFn()
        try:
            self.writeRequest(statesDir, requestId, nowFn=wallFn, requestFields=requestFields)
        except OSError as exc:
            raise RequestChannelPublishError(statesDir, exc) from exc

        deadline = nowFn() + timeoutSeconds
        while True:
            outcome = self.readOutcome(statesDir)
            # ⚠️ The requestId match is what stops a LEFTOVER outcome from an
            # earlier request answering this one.
            if isinstance(outcome, Mapping) and outcome.get("requestId") == requestId:
                return outcome
            if nowFn() >= deadline:
                self.consumeRequest(statesDir)  # do not leave it to fire later
                raise RequestChannelTimeout(timeoutSeconds)
            sleepFn(POLL_INTERVAL_SECONDS)


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
