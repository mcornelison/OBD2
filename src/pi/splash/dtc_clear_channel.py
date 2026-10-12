################################################################################
# File Name: dtc_clear_channel.py
# Purpose/Description: ARCH-023 -- the cross-process channel that lets the
#   US-407 CLEAR CODES button reach the one process allowed to talk to the ECU.
#
#   WHY THIS FILE EXISTS.  US-407 shipped every part of the Mode-04 clear except
#   one join.  `states_http_server`'s POST /dtc-clear takes an INJECTED
#   `clearRunner`; nothing in the tree ever injected one, so the route answered
#   503 and the button was inert.  Same shape as the carousel emitters nothing
#   called (A-16) and `pi.pollingTiers` nothing imported (A-28): a complete,
#   correct implementation with no caller.
#
#   WHY IT IS A CHANNEL AND NOT AN INJECTION.  The HTTP server
#   (eclipse-states-http.service) and the orchestrator (eclipse-obd.service) are
#   SEPARATE PROCESSES.  Only the orchestrator may hold the OBD serial port: a
#   second opener is exactly what killed capture for a month (A-17, a DTC read
#   that bypassed the io lock) and battery health for 111 days (A-26, GPIO6
#   acquired by two services).  So the HTTP process asks, and the process that
#   already owns the connection answers -- `specs/ssot-design-pattern.md` rule B,
#   read once and let others subscribe.
#
#   THE CONTRACT.  `dtc_clear.performClear` needs only a zero-arg callable
#   returning ``{"stored": [...], "pending": [...], "mil": bool}``.  So the
#   bridge IS a clearRunner and the shipped route needs no change.
#
#   🔴 THE RULE EVERY FAILURE PATH HERE OBEYS.  A clear that cannot be PROVEN
#   must never read as success.  Returning an empty readback when the
#   orchestrator is down would have `performClear` report "cleared -- 0 stored,
#   0 pending" for a Mode 04 that was never issued.  That is the
#   manufactured-reading rule (`ssot-design-pattern` rule A corollary) applied to
#   an ECU write, and it is the reason every unhappy path raises instead of
#   returning.
#
#   Both files are written temp + os.replace via the shared writeStateAtomic, so
#   a reader never sees a torn payload and a power cut mid-write cannot leave a
#   zero-byte file (the US-682 lesson).
# Author: Atlas (Architect) -- built under the CIO's standing build directive
# Creation Date: 2026-09-09
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-09-09    | Atlas   | Initial -- ARCH-023 request/outcome channel + the
#               |         | bridge clearRunner the HTTP route was missing.
# ================================================================================
################################################################################

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pi.splash.boot_state_emitter import writeStateAtomic

__all__ = [
    "ClearBridgeError",
    "ClearBridgeTimeout",
    "DEFAULT_TIMEOUT_SECONDS",
    "OUTCOME_FILENAME",
    "POLL_INTERVAL_SECONDS",
    "REQUEST_FILENAME",
    "consumeRequest",
    "makeBridgeClearRunner",
    "readOutcome",
    "readRequest",
    "writeOutcome",
    "writeRequest",
]

#: Both files live in the tmpfs states dir the two units already share.
REQUEST_FILENAME = "dtc-clear-request.json"
OUTCOME_FILENAME = "dtc-clear-outcome.json"

#: How long the HTTP request will wait for the orchestrator to answer.
#: Sized against the orchestrator's run-loop period plus a real Mode 04 and the
#: Mode 03(+07) re-read on a 10,400 bps K-line, which is seconds, not
#: milliseconds.  A caller that wants a different budget passes one.
DEFAULT_TIMEOUT_SECONDS = 20.0

#: Poll cadence while waiting.  Cheap: a stat on tmpfs.
POLL_INTERVAL_SECONDS = 0.25


class ClearBridgeError(RuntimeError):
    """The clear could not be carried out, and we can say why.

    Raised rather than returned so no failure can reach ``performClear`` wearing
    the shape of a successful readback.
    """


class ClearBridgeTimeout(ClearBridgeError):
    """No outcome arrived for THIS request inside the budget.

    ⚠️ Explicitly NOT "the clear failed" -- it means we do not know.  The
    orchestrator may be down, wedged, or simply slower than the budget, and a
    Mode 04 may or may not have reached the ECU.  The caller must report an
    honest unknown; the next `dtc` state refresh is what settles it.
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
    """Publish a clear request for the orchestrator to service."""
    writeStateAtomic(
        str(Path(statesDir) / REQUEST_FILENAME),
        {"requestId": requestId, "requestedAtEpoch": nowFn()},
    )


def readRequest(statesDir: str) -> dict[str, Any] | None:
    """Read the pending request, or None when there is none.

    A corrupt or half-written file reads as None: this is polled from the
    orchestrator's run loop, and a malformed request must never take capture
    down.  It is also self-correcting -- the requester times out and the
    operator sees an honest failure.
    """
    return _readJson(Path(statesDir) / REQUEST_FILENAME)


def consumeRequest(statesDir: str) -> None:
    """Remove the request once it has been serviced. Idempotent.

    🔴 Load-bearing: Mode 04 is irreversible, so a request left in place would be
    serviced again on the next run-loop pass -- a second wipe nobody asked for.
    """
    try:
        (Path(statesDir) / REQUEST_FILENAME).unlink()
    except FileNotFoundError:
        pass
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
    stored: list[str],
    pending: list[str],
    mil: bool,
    error: str | None,
    nowFn: Callable[[], float] = time.time,
) -> None:
    """Publish the result of servicing ``requestId``.

    ``requestId`` is echoed so a stale outcome can never be mistaken for the
    answer to a later request.
    """
    writeStateAtomic(
        str(Path(statesDir) / OUTCOME_FILENAME),
        {
            "requestId": requestId,
            "ok": bool(ok),
            "stored": [str(c) for c in stored],
            "pending": [str(c) for c in pending],
            "mil": bool(mil),
            "error": error,
            "completedAtEpoch": nowFn(),
        },
    )


def readOutcome(statesDir: str) -> dict[str, Any] | None:
    """Read the most recent outcome, or None."""
    return _readJson(Path(statesDir) / OUTCOME_FILENAME)


# ==============================================================================
# The bridge -- this is what gets injected as `clearRunner`
# ==============================================================================


def makeBridgeClearRunner(
    statesDir: str,
    *,
    timeoutSeconds: float = DEFAULT_TIMEOUT_SECONDS,
    nowFn: Callable[[], float] = time.monotonic,
    sleepFn: Callable[[float], None] = time.sleep,
    idFn: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> Callable[[], Mapping[str, Any]]:
    """Build the zero-arg clearRunner ``performClear`` expects.

    Publishes a request, waits for the orchestrator's matching outcome, and
    returns the readback mapping.  **Every path that cannot prove a clear
    raises** -- see the module header.

    Args:
        statesDir: The shared tmpfs states directory.
        timeoutSeconds: Wall-clock budget for the orchestrator to answer.
        nowFn: Monotonic clock (injectable for tests).
        sleepFn: Sleep (injectable for tests).
        idFn: Request-id factory (injectable for tests).

    Returns:
        A callable returning ``{"stored": [...], "pending": [...], "mil": bool}``.

    Raises:
        ClearBridgeTimeout: no outcome for THIS request inside the budget.
        ClearBridgeError: the request could not be published, or the
            orchestrator reported a refusal.
    """

    def runner() -> Mapping[str, Any]:
        requestId = idFn()
        try:
            writeRequest(statesDir, requestId, nowFn=time.time)
        except OSError as exc:
            raise ClearBridgeError(
                f"could not publish the clear request to {statesDir}: {exc}"
            ) from exc

        deadline = nowFn() + timeoutSeconds
        while True:
            outcome = readOutcome(statesDir)
            # ⚠️ The requestId match is what stops a LEFTOVER outcome from an
            # earlier press answering this one.  Without it the second press
            # reports the first press's result and issues no Mode 04 at all.
            if isinstance(outcome, Mapping) and outcome.get("requestId") == requestId:
                if not outcome.get("ok", False):
                    reason = outcome.get("error") or "orchestrator refused the clear"
                    raise ClearBridgeError(str(reason))
                return {
                    "stored": [str(c) for c in (outcome.get("stored") or [])],
                    "pending": [str(c) for c in (outcome.get("pending") or [])],
                    "mil": bool(outcome.get("mil", False)),
                }
            if nowFn() >= deadline:
                consumeRequest(statesDir)  # do not leave it to fire later
                raise ClearBridgeTimeout(
                    "no answer from the OBD service within "
                    f"{timeoutSeconds:g}s -- the clear may or may not have been "
                    "issued; re-read the codes before pressing again"
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
