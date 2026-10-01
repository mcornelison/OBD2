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
# ================================================================================
################################################################################
"""The CIO pre-shutdown server-sync pipeline task (Phase-2 power-watch)."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from src.pi.network.home_detector import HomeNetworkState
from src.pi.power.power_watch.contract import OutcomeKind

logger = logging.getLogger(__name__)
__all__ = ["RETRY_FIRST_WAIT_SEC", "RETRY_WAIT_GROWTH", "SyncWithServerTask"]

#: US-776-g backoff: the first wait after a failed attempt, and the factor
#: each later wait grows by. Attempts land at ~0, 2, 6, 14, 30 s (the story's
#: worked example); how long the loop runs is the configured ceiling, not these.
RETRY_FIRST_WAIT_SEC = 2.0
RETRY_WAIT_GROWTH = 2.0


class SyncWithServerTask:
    """Best-effort pre-shutdown sync of the local drive log to the home server.

    Satisfies the ``ShutdownTask`` protocol (``name`` + ``run()``); ``run()``
    never raises. The CIO state machine (spec sec 6.4), gated on the home
    detector (US-776-c, Atlas gap 2):

      0. Ask the home detector ONCE.
         ``AWAY`` (a positive not-home answer) -> ``SERVER_UNAVAILABLE``
         (benign skip, NO record, no wait, no network call of its own).
         ``AT_HOME_*`` -> drain.
         ``UNKNOWN`` (a dead SSID/IP reader, or a detector that raised) ->
         drain anyway, logged ``UNKNOWN_NETWORK`` at WARNING. A dead
         instrument must never disable the drain (design-patterns sec 6).
      1. Drain, sync ok      -> ``OK``.
      2. Transient sync failure -> wait, retry; each wait doubles (US-776-g).
         Any attempt ok     -> ``OK`` (stops at the first success);
         the ceiling (``pi.homeNetwork.shutdownSyncCeilingSec``) is reached
         -> ``SYNC_FAILED_AFTER_RETRY`` (record + continue). No attempt
         starts after the ceiling. With a blind fuel gauge the sequencer's
         ``totalWindowCapSec`` may end the shutdown first; that is the
         accepted degraded mode (Atlas, gap 4).
      3. A genuine (non-transient) fault -> ``REAL_ERROR`` (record, no retry).

    Unsynced data is never lost -- it stays in the Pi's local SQLite and syncs
    next time home. "Confirmed sync" means the bounded attempt resolved.

    T6 wiring contract: the production ``runSync`` MUST raise a
    ``RuntimeError``-family exception for transient/network sync failures (the
    retry-eligible path). ANY non-``RuntimeError`` exception is treated as a
    genuine ``REAL_ERROR`` (no retry). ``writeRecord`` is invoked only for
    ``SYNC_FAILED_AFTER_RETRY`` and ``REAL_ERROR`` (never for the benign
    AWAY skip or for ``OK``), with a single ``(OutcomeKind, detail)`` tuple
    argument.
    """

    name = "sync_with_server"

    def __init__(
        self,
        *,
        homeState: Callable[[], HomeNetworkState],
        runSync: Callable[[], None],
        writeRecord: Callable[[object], None],
        ceilingSec: float,
        sleepFn: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
    ):
        """Args:
        homeState: Zero-arg home-network read, called once per ``run()``.
            Production passes ``HomeNetworkDetector.getHomeNetworkState``;
            every subprocess and HTTP call behind it is timeout-bounded.
        runSync: Zero-arg one-shot DB sync; returns on success, raises on
            failure (RuntimeError-family = transient/retryable).
        writeRecord: Single-arg producer sink, called with a
            ``(OutcomeKind, detail)`` tuple only for genuine/after-retry
            faults.
        ceilingSec: US-776-g -- ``pi.homeNetwork.shutdownSyncCeilingSec``.
            No attempt starts once this long has passed since the drain
            began. The sequencer's floor poll (and, with a blind gauge, its
            ``totalWindowCapSec``) may end the shutdown sooner.
        sleepFn: Wait between attempts; ``time.sleep`` when None.
        monotonic: Clock the ceiling is measured on; ``time.monotonic``
            when None.
        """
        self._homeState = homeState
        self._runSync = runSync
        self._writeRecord = writeRecord
        self._ceilingSec = float(ceilingSec)
        # Resolved at construction, not at import, so a patched time module
        # is honoured.
        self._sleep = sleepFn if sleepFn is not None else time.sleep
        self._monotonic = monotonic if monotonic is not None else time.monotonic

    def run(self) -> OutcomeKind:
        """Run the CIO sync state machine. Never raises."""
        state = self._readHomeState()
        if state is HomeNetworkState.AWAY:
            logger.info(
                "powerwatch sync_with_server: AWAY from home -- skipping the "
                "sync, powering off without waiting on the network"
            )
            return OutcomeKind.SERVER_UNAVAILABLE
        if state is HomeNetworkState.UNKNOWN:
            logger.warning(
                "powerwatch sync_with_server: UNKNOWN_NETWORK -- home cannot be "
                "confirmed (SSID or IP reader unavailable) and nothing says "
                "AWAY -- draining anyway"
            )
        return self._drain()

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

    def _drain(self) -> OutcomeKind:
        """Retry a transient failure with growing waits until the ceiling.

        No attempt starts once ``ceilingSec`` has elapsed since the drain
        began, and no wait is begun that would end at or past it. Never raises.
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
                return self._record(OutcomeKind.REAL_ERROR, str(exc))
            else:
                logger.info(
                    "powerwatch sync_with_server: sync succeeded on attempt %d", attempt
                )
                return OutcomeKind.OK

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
        return self._record(
            OutcomeKind.SYNC_FAILED_AFTER_RETRY, f"{lastError} (attempts={attempt})"
        )

    def _record(self, kind: OutcomeKind, detail: str) -> OutcomeKind:
        """Hand one fault record to the sink; a failing sink never raises out."""
        try:
            self._writeRecord((kind, detail))
        except Exception as exc:  # noqa: BLE001 -- never raise; the poweroff must proceed
            logger.error(
                "powerwatch sync_with_server: could not write the %s record (%s)",
                kind,
                exc,
            )
        return kind
