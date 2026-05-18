################################################################################
# File Name: sync_with_server.py
# Purpose/Description: The CIO pre-shutdown server-sync task for Phase-2
#                      power-watch: reachable? -> sync -> retry-once on a
#                      transient (RuntimeError) failure -> classify; benign
#                      server-unavailable skips silently, genuine faults emit a
#                      producer record. Never raises (it is a PipelineTask).
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T5 sync_with_server CIO state machine.
# ================================================================================
################################################################################
"""The CIO pre-shutdown server-sync pipeline task (Phase-2 power-watch)."""
from __future__ import annotations

import logging
from collections.abc import Callable

from src.pi.power.power_watch.contract import OutcomeKind

logger = logging.getLogger(__name__)
__all__ = ["SyncWithServerTask"]


class SyncWithServerTask:
    """Best-effort pre-shutdown sync of the local drive log to the home server.

    Satisfies the ``PipelineTask`` protocol (``name`` + ``run()``); ``run()``
    never raises. The CIO state machine (spec sec 6.4):

      1. Server unreachable  -> ``SERVER_UNAVAILABLE`` (benign skip, NO record).
      2. Reachable, sync ok  -> ``OK``.
      3. Reachable, transient sync failure -> retry once;
         retry ok           -> ``OK``;
         retry fails again   -> ``SYNC_FAILED_AFTER_RETRY`` (record + continue).
      4. A genuine (non-transient) fault -> ``REAL_ERROR`` (record, no retry).

    Unsynced data is never lost -- it stays in the Pi's local SQLite and syncs
    next time home. "Confirmed sync" means the bounded attempt resolved.

    T6 wiring contract: the production ``runSync`` MUST raise a
    ``RuntimeError``-family exception for transient/network sync failures (the
    retry-eligible path). ANY non-``RuntimeError`` exception is treated as a
    genuine ``REAL_ERROR`` (no retry). ``writeRecord`` is invoked only for
    ``SYNC_FAILED_AFTER_RETRY`` and ``REAL_ERROR`` (never for the benign
    ``SERVER_UNAVAILABLE`` or for ``OK``), with a single
    ``(OutcomeKind, detail)`` tuple argument.
    """

    name = "sync_with_server"

    def __init__(
        self,
        *,
        serverReachable: Callable[[], bool],
        runSync: Callable[[], None],
        writeRecord: Callable[[object], None],
    ):
        """Args:
        serverReachable: Zero-arg, True if chi-srv-01 is reachable now.
        runSync: Zero-arg one-shot DB sync; returns on success, raises on
            failure (RuntimeError-family = transient/retryable).
        writeRecord: Single-arg producer sink, called with a
            ``(OutcomeKind, detail)`` tuple only for genuine/after-retry
            faults.
        """
        self._serverReachable = serverReachable
        self._runSync = runSync
        self._writeRecord = writeRecord

    def run(self) -> OutcomeKind:
        """Run the CIO sync state machine. Never raises."""
        if not self._serverReachable():
            logger.info(
                "powerwatch sync_with_server: chi-srv-01 unreachable -- benign skip"
            )
            return OutcomeKind.SERVER_UNAVAILABLE
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
