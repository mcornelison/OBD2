################################################################################
# File Name: sync_with_server.py
# Purpose/Description: The CIO pre-shutdown server-sync task for Phase-2
#                      power-watch: home? -> sync -> retry a transient
#                      (RuntimeError) failure with growing waits until the
#                      shutdownSyncCeilingSec ceiling -> classify; a positive
#                      AWAY skips at once, genuine faults emit a producer
#                      record. Never raises (it is a ShutdownTask -- renamed
#                      from PipelineTask in SS-T6).
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T5 sync_with_server CIO state machine.
# 2026-10-01    | Rex     | US-776-c: the gate is the home detector's state, not
#               |         | one server probe. A positive AWAY skips without
#               |         | waiting; AT_HOME_* drains; UNKNOWN drains as
#               |         | UNKNOWN_NETWORK at WARNING.
# 2026-10-01    | Rex     | US-776-g: the single retry is now a backoff loop
#               |         | (2, 4, 8, 16 s ...) bounded by
#               |         | pi.homeNetwork.shutdownSyncCeilingSec.
# 2026-10-01    | Rex     | US-776-d: every run() writes exactly one
#               |         | SyncOutcomeRecord -- why the sync ended, with the
#               |         | backlog before the first attempt and after the last.
#               |         | A failed drain at home tells a misconfigured probe
#               |         | from a down server.
# ================================================================================
################################################################################
"""The CIO pre-shutdown server-sync pipeline task (Phase-2 power-watch)."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import NamedTuple

from src.pi.network.home_detector import HomeNetworkState, ProbeResult
from src.pi.power.power_watch.contract import OutcomeKind

logger = logging.getLogger(__name__)
__all__ = [
    "RETRY_FIRST_WAIT_SEC",
    "RETRY_WAIT_GROWTH",
    "SyncOutcomeRecord",
    "SyncWithServerTask",
]

#: US-776-g backoff: the first wait after a failed attempt, and the factor
#: each later wait grows by. Attempts land at ~0, 2, 6, 14, 30 s (the story's
#: worked example); how long the loop runs is the configured ceiling, not these.
RETRY_FIRST_WAIT_SEC = 2.0
RETRY_WAIT_GROWTH = 2.0

#: Log level of the one outcome line each run() emits. A positive AWAY and a
#: delivery are the expected cases; an unconfirmed home is the dead-instrument
#: warning (US-776-c); everything else is a sync that did not happen.
_OUTCOME_LOG_LEVEL: dict[OutcomeKind, int] = {
    OutcomeKind.AWAY: logging.INFO,
    OutcomeKind.DELIVERED: logging.INFO,
    OutcomeKind.UNKNOWN_NETWORK: logging.WARNING,
}


class SyncOutcomeRecord(NamedTuple):
    """The one record a shutdown sync writes (US-776-d).

    A tuple whose first item is the kind, so a sink that indexes ``[0]``
    still reads the outcome.

    Attributes:
        kind: Why the sync ended.
        detail: Free-text cause: the last error, attempt count, probe answer.
        backlogStart: Unsynced rows before the first attempt, or ``None``
            when the count could not be read.
        backlogEnd: Unsynced rows after the last attempt (the same read as
            ``backlogStart`` when no attempt ran), or ``None``.
    """

    kind: OutcomeKind
    detail: str
    backlogStart: int | None
    backlogEnd: int | None


class SyncWithServerTask:
    """Best-effort pre-shutdown sync of the local drive log to the home server.

    Satisfies the ``ShutdownTask`` protocol (``name`` + ``run()``); ``run()``
    never raises. The CIO state machine (spec sec 6.4), gated on the home
    detector (US-776-c, Atlas gap 2):

      0. Ask the home detector ONCE, and read the backlog (``backlog_start``).
         ``AWAY`` (a positive not-home answer) -> ``AWAY`` (skip: no wait,
         no network call of its own).
         ``AT_HOME_*`` -> drain.
         ``UNKNOWN`` (a dead SSID/IP reader, or a detector that raised) ->
         drain anyway, logged ``UNKNOWN_NETWORK`` at WARNING. A dead
         instrument must never disable the drain (design-patterns sec 6).
      1. Drain, sync ok      -> ``DELIVERED``.
      2. Transient sync failure -> wait, retry; each wait doubles (US-776-g).
         Any attempt ok     -> ``DELIVERED`` (stops at the first success);
         the ceiling (``pi.homeNetwork.shutdownSyncCeilingSec``) is reached
         -> classified (US-776-d): ``UNKNOWN_NETWORK`` when home was never
         confirmed; ``PROBE_MISCONFIGURED`` when the detector's probe was
         answered 404/405/401/403; otherwise ``AT_HOME_SERVER_DOWN``. No
         attempt starts after the ceiling. With a blind fuel gauge the
         sequencer's ``totalWindowCapSec`` may end the shutdown first; that
         is the accepted degraded mode (Atlas, gap 4).
      3. A genuine (non-transient) fault -> ``REAL_ERROR`` (no retry).

    US-776-d: EVERY run() hands ``writeRecord`` exactly one
    :class:`SyncOutcomeRecord`, the skip and the success included, carrying
    ``backlog_start`` (read before the first attempt) and ``backlog_end``
    (read after the last). A DELIVERED drain that started with nothing owed
    is therefore distinguishable from one that moved rows.

    Unsynced data is never lost -- it stays in the Pi's local SQLite and syncs
    next time home. "Confirmed sync" means the bounded attempt resolved.

    T6 wiring contract: the production ``runSync`` MUST raise a
    ``RuntimeError``-family exception for transient/network sync failures (the
    retry-eligible path). ANY non-``RuntimeError`` exception is treated as a
    genuine ``REAL_ERROR`` (no retry).
    """

    name = "sync_with_server"

    def __init__(
        self,
        *,
        homeState: Callable[[], HomeNetworkState],
        runSync: Callable[[], None],
        writeRecord: Callable[[SyncOutcomeRecord], None],
        ceilingSec: float,
        sleepFn: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
        backlogReader: Callable[[], int | None] | None = None,
        lastProbe: Callable[[], ProbeResult | None] | None = None,
    ):
        """Args:
        homeState: Zero-arg home-network read, called once per ``run()``.
            Production passes ``HomeNetworkDetector.getHomeNetworkState``;
            every subprocess and HTTP call behind it is timeout-bounded.
        runSync: Zero-arg one-shot DB sync; returns on success, raises on
            failure (RuntimeError-family = transient/retryable).
        writeRecord: Single-arg sink, called exactly once per ``run()`` with
            the :class:`SyncOutcomeRecord`.
        ceilingSec: US-776-g -- ``pi.homeNetwork.shutdownSyncCeilingSec``.
            No attempt starts once this long has passed since the drain
            began. The sequencer's floor poll (and, with a blind gauge, its
            ``totalWindowCapSec``) may end the shutdown sooner.
        sleepFn: Wait between attempts; ``time.sleep`` when None.
        monotonic: Clock the ceiling is measured on; ``time.monotonic``
            when None.
        backlogReader: US-776-d -- zero-arg count of unsynced rows (the
            shared US-621 reader), ``None`` when it cannot say. Read before
            the first attempt and after the last. When None the record's
            backlog counts are ``None``.
        lastProbe: US-776-d -- zero-arg read of the probe behind the home
            state (``HomeNetworkDetector.lastProbe``); never probes again.
            Classifies a failed drain at home. When None, a failed drain at
            home is ``AT_HOME_SERVER_DOWN``.
        """
        self._homeState = homeState
        self._runSync = runSync
        self._writeRecord = writeRecord
        self._ceilingSec = float(ceilingSec)
        # Resolved at construction, not at import, so a patched time module
        # is honoured.
        self._sleep = sleepFn if sleepFn is not None else time.sleep
        self._monotonic = monotonic if monotonic is not None else time.monotonic
        self._backlogReader = backlogReader
        self._lastProbe = lastProbe

    def run(self) -> OutcomeKind:
        """Run the CIO sync state machine and record its outcome. Never raises."""
        state = self._readHomeState()
        backlogStart = self._readBacklog()
        if state is HomeNetworkState.AWAY:
            logger.info(
                "powerwatch sync_with_server: AWAY from home -- skipping the "
                "sync, powering off without waiting on the network"
            )
            # No attempt ran, so the start read is also the end.
            return self._record(
                OutcomeKind.AWAY, "away from home -- sync skipped", backlogStart, backlogStart
            )
        if state is HomeNetworkState.UNKNOWN:
            logger.warning(
                "powerwatch sync_with_server: UNKNOWN_NETWORK -- home cannot be "
                "confirmed (SSID or IP reader unavailable) and nothing says "
                "AWAY -- draining anyway"
            )
        kind, detail = self._drain(state)
        return self._record(kind, detail, backlogStart, self._readBacklog())

    def _readHomeState(self) -> HomeNetworkState:
        """The detector's state, or UNKNOWN when the detector itself raises."""
        try:
            return self._homeState()
        except Exception as exc:  # noqa: BLE001 -- never raise; a dead detector is UNKNOWN
            logger.warning(
                "powerwatch sync_with_server: home detector failed (%s) -- "
                "treating the network as UNKNOWN",
                exc,
            )
            return HomeNetworkState.UNKNOWN

    def _readBacklog(self) -> int | None:
        """Unsynced rows now, or None when there is no reader or it failed."""
        if self._backlogReader is None:
            return None
        try:
            return self._backlogReader()
        except Exception as exc:  # noqa: BLE001 -- never raise; an unread count is None
            logger.warning("powerwatch sync_with_server: backlog read failed (%s)", exc)
            return None

    def _drain(self, state: HomeNetworkState) -> tuple[OutcomeKind, str]:
        """Retry a transient failure with growing waits until the ceiling.

        No attempt starts once ``ceilingSec`` has elapsed since the drain
        began, and no wait is begun that would end at or past it. Never raises.

        Returns:
            The outcome kind and its detail text.
        """
        startMono = self._monotonic()
        wait = RETRY_FIRST_WAIT_SEC
        attempt = 0
        lastError: RuntimeError | None = None
        while True:
            attempt += 1
            try:
                self._runSync()
            except RuntimeError as exc:
                lastError = exc
            except Exception as exc:  # noqa: BLE001 -- never raise; non-RuntimeError = real fault
                logger.error(
                    "powerwatch sync_with_server: genuine fault on attempt %d (%s) "
                    "-- recording, no retry",
                    attempt,
                    exc,
                )
                return OutcomeKind.REAL_ERROR, str(exc)
            else:
                logger.info(
                    "powerwatch sync_with_server: sync succeeded on attempt %d", attempt
                )
                return OutcomeKind.DELIVERED, f"delivered on attempt {attempt}"

            elapsed = self._monotonic() - startMono
            if elapsed + wait >= self._ceilingSec:
                break
            logger.warning(
                "powerwatch sync_with_server: attempt %d failed (%s) -- retrying "
                "in %.0fs (%.0fs of %.0fs ceiling used)",
                attempt,
                lastError,
                wait,
                elapsed,
                self._ceilingSec,
            )
            try:
                self._sleep(wait)
            except Exception as exc:  # noqa: BLE001 -- never raise; a broken wait ends the retries
                logger.error(
                    "powerwatch sync_with_server: retry wait failed (%s) -- giving up", exc
                )
                break
            if self._monotonic() - startMono >= self._ceilingSec:
                break
            wait *= RETRY_WAIT_GROWTH

        logger.error(
            "powerwatch sync_with_server: sync failed after %d attempt(s) within the "
            "%.0fs ceiling (%s) -- continuing the shutdown",
            attempt,
            self._ceilingSec,
            lastError,
        )
        return self._classifyFailedDrain(state, f"{lastError} (attempts={attempt})")

    def _classifyFailedDrain(
        self, state: HomeNetworkState, detail: str
    ) -> tuple[OutcomeKind, str]:
        """Why a drain that ran to the ceiling never delivered (US-776-d).

        Home never confirmed -> UNKNOWN_NETWORK. At home, a probe the server
        answered 404/405/401/403 means the server is up and the configured
        route or key is wrong -> PROBE_MISCONFIGURED (Atlas ruling 4).
        Anything else at home -> AT_HOME_SERVER_DOWN.
        """
        if state is HomeNetworkState.UNKNOWN:
            return OutcomeKind.UNKNOWN_NETWORK, detail
        probe = self._readLastProbe()
        if probe is not None and probe.isMisconfigured:
            return OutcomeKind.PROBE_MISCONFIGURED, f"probe HTTP {probe.status}; {detail}"
        if probe is not None and probe.error:
            return OutcomeKind.AT_HOME_SERVER_DOWN, f"probe {probe.error}; {detail}"
        return OutcomeKind.AT_HOME_SERVER_DOWN, detail

    def _readLastProbe(self) -> ProbeResult | None:
        """The detector's last probe, or None when unavailable."""
        if self._lastProbe is None:
            return None
        try:
            return self._lastProbe()
        except Exception as exc:  # noqa: BLE001 -- never raise; no probe reads as server-down
            logger.warning("powerwatch sync_with_server: probe read failed (%s)", exc)
            return None

    def _record(
        self,
        kind: OutcomeKind,
        detail: str,
        backlogStart: int | None,
        backlogEnd: int | None,
    ) -> OutcomeKind:
        """Log the outcome and hand its one record to the sink. Never raises."""
        logger.log(
            _OUTCOME_LOG_LEVEL.get(kind, logging.ERROR),
            "powerwatch sync_with_server: outcome=%s backlog_start=%s backlog_end=%s (%s)",
            kind.name,
            backlogStart,
            backlogEnd,
            detail,
        )
        try:
            self._writeRecord(SyncOutcomeRecord(kind, detail, backlogStart, backlogEnd))
        except Exception as exc:  # noqa: BLE001 -- never raise; the poweroff must proceed
            logger.error(
                "powerwatch sync_with_server: could not write the %s record (%s)",
                kind.name,
                exc,
            )
        return kind
