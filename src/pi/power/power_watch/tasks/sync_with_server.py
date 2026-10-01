################################################################################
# File Name: sync_with_server.py
# Purpose/Description: The CIO pre-shutdown server-sync task for Phase-2
#                      power-watch: home? -> sync -> retry-once on a
#                      transient (RuntimeError) failure -> classify; a positive
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
# ================================================================================
################################################################################
"""The CIO pre-shutdown server-sync pipeline task (Phase-2 power-watch)."""
from __future__ import annotations

import logging
from collections.abc import Callable

from src.pi.network.home_detector import HomeNetworkState
from src.pi.power.power_watch.contract import OutcomeKind

logger = logging.getLogger(__name__)
__all__ = ["SyncWithServerTask"]


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
      2. Transient sync failure -> retry once;
         retry ok           -> ``OK``;
         retry fails again   -> ``SYNC_FAILED_AFTER_RETRY`` (record + continue).
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
        """
        self._homeState = homeState
        self._runSync = runSync
        self._writeRecord = writeRecord

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
        """One sync attempt plus at most one retry. Never raises."""
        try:
            self._runSync()
            logger.info("powerwatch sync_with_server: sync succeeded")
            return OutcomeKind.OK
        except RuntimeError as exc:
            logger.error(
                "powerwatch sync_with_server: sync failed (%s) -- retrying once", exc
            )
            return self._retry()
        except Exception as exc:  # noqa: BLE001 -- never raise; non-RuntimeError = real fault
            logger.error(
                "powerwatch sync_with_server: genuine fault (%s) -- recording", exc
            )
            self._writeRecord((OutcomeKind.REAL_ERROR, str(exc)))
            return OutcomeKind.REAL_ERROR

    def _retry(self) -> OutcomeKind:
        """Single retry of a transient sync failure. Never raises."""
        try:
            self._runSync()
            logger.info("powerwatch sync_with_server: sync succeeded on retry")
            return OutcomeKind.OK
        except RuntimeError as exc:
            logger.error(
                "powerwatch sync_with_server: sync failed after retry (%s) -- continue",
                exc,
            )
            self._writeRecord((OutcomeKind.SYNC_FAILED_AFTER_RETRY, str(exc)))
            return OutcomeKind.SYNC_FAILED_AFTER_RETRY
        except Exception as exc:  # noqa: BLE001 -- never raise; non-RuntimeError = real fault
            logger.error(
                "powerwatch sync_with_server: genuine fault on retry (%s) -- recording",
                exc,
            )
            self._writeRecord((OutcomeKind.REAL_ERROR, str(exc)))
            return OutcomeKind.REAL_ERROR
