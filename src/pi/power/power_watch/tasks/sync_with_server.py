################################################################################
# File Name: sync_with_server.py
# Purpose/Description: The CIO pre-shutdown server-sync task for Phase-2
#                      power-watch: home? -> sync -> retry a transient
#                      (RuntimeError) failure with growing waits until the
#                      backlog is empty or has not fallen for stallSec (no
#                      absolute cap; ARCH-065) -> classify; a positive
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
# 2026-10-01    | Rex     | US-776-e: AT_HOME_JOINING polls for the WiFi
#               |         | association inside the same ceiling, then drains;
#               |         | still joining at the ceiling is
#               |         | AT_HOME_JOINING_TIMEOUT.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T3: the at-home sync runs to
#               |         | completion (CIO 2026-10-02). ceilingSec is retired:
#               |         | joinWaitSec bounds the WiFi-join wait (120 s);
#               |         | stallSec ends a drain whose backlog did not fall
#               |         | (60 s, re-read after every attempt, clock from
#               |         | association). New outcome STALLED; lastOutcome.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T2: the record carries the drain's start/end (nowIsoFn).
# 2026-10-03    | Atlas (ARCH-065a) | Ruling 19: lastOutcome reset at run start (M3); the
#               |         | loss generation is read ONCE at run start and rides on
#               |         | the record (lossGeneration), so a run left over from a
#               |         | cancelled loss is dropped by HomeStateAtLoss.wrapSink and
#               |         | never overwrites lastOutcome (I1).
# 2026-10-05    | Atlas (US-833) | writeProvisional: a PROVISIONAL INTERRUPTED record at
#               |         | run start (backlog_start) and at drain start (+ the
#               |         | start stamp), before the sync can be cut off, so a hard
#               |         | cut / floor / cap never leaves the record silent. The
#               |         | final outcome still goes to writeRecord exactly once.
# ================================================================================
################################################################################
"""The CIO pre-shutdown server-sync pipeline task (Phase-2 power-watch)."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import NamedTuple

from src.common.time.helper import utcIsoNow
from src.pi.network.home_detector import HomeNetworkState, ProbeResult
from src.pi.power.power_watch.contract import OutcomeKind

logger = logging.getLogger(__name__)
__all__ = [
    "JOIN_POLL_SEC",
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

#: US-776-e: how often AT_HOME_JOINING is re-read while waiting for the WiFi
#: association. Fixed, not growing: the drain should start within one poll
#: of the rejoin. The shortest wait this task already makes, and the nmcli
#: read behind each poll is itself bounded at 2 s.
JOIN_POLL_SEC = RETRY_FIRST_WAIT_SEC

#: Log level of the one outcome line each run() emits. A positive AWAY and a
#: delivery are the expected cases; an unconfirmed home is the dead-instrument
#: warning (US-776-c); everything else is a sync that did not happen.
_OUTCOME_LOG_LEVEL: dict[OutcomeKind, int] = {
    OutcomeKind.AWAY: logging.INFO,
    OutcomeKind.DELIVERED: logging.INFO,
    OutcomeKind.UNKNOWN_NETWORK: logging.WARNING,
    OutcomeKind.STALLED: logging.WARNING,
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
        startedAt: ARCH-065 -- UTC ISO second the drain began (after any
            JOINING wait), or ``None`` when no drain ran.
        endedAt: UTC ISO second the drain returned, or ``None``.
        lossGeneration: Ruling 19 -- the ``HomeStateAtLoss`` loss generation
            the run started under, or ``None`` when the task was not given
            one. ``HomeStateAtLoss.wrapSink`` drops a record of an older loss.
    """

    kind: OutcomeKind
    detail: str
    backlogStart: int | None
    backlogEnd: int | None
    startedAt: str | None = None
    endedAt: str | None = None
    lossGeneration: int | None = None


class SyncWithServerTask:
    """Best-effort pre-shutdown sync of the local drive log to the home server.

    Satisfies the ``ShutdownTask`` protocol (``name`` + ``run()``); ``run()``
    never raises. The CIO state machine (spec sec 6.4), gated on the home
    detector (US-776-c, Atlas gap 2):

      0. Ask the home detector ONCE, and read the backlog (``backlog_start``).
         ``AWAY`` (a positive not-home answer) -> ``AWAY`` (skip: no wait,
         no network call of its own).
         ``AT_HOME_JOINING`` (home SSID in range, not associated; US-776-e)
         -> re-read the state every ``JOIN_POLL_SEC`` until it is something
         else, then apply this step to that state. The wait is bounded by
         ``joinWaitSec`` on its own (the drain's stall clock starts at the
         association); still joining when it is spent ->
         ``AT_HOME_JOINING_TIMEOUT`` (no attempt).
         ``AT_HOME_SERVER_*`` -> drain.
         ``UNKNOWN`` (a dead SSID/IP reader, or a detector that raised) ->
         drain anyway, logged ``UNKNOWN_NETWORK`` at WARNING. A dead
         instrument must never disable the drain (design-patterns sec 6).
      1. Drain: push, then RE-READ the backlog after every attempt (runSync
         can return having pushed nothing). Backlog 0 -> ``DELIVERED``.
         There is NO absolute time cap (ARCH-065, CIO 2026-10-02).
      2. Transient sync failure -> wait, retry; each wait doubles (US-776-g).
         The drain ends when the backlog has not FALLEN for ``stallSec``:
         ``STALLED`` when the last attempt returned quietly; when the last
         attempt raised it is classified (US-776-d): ``UNKNOWN_NETWORK`` when
         home was never confirmed; ``PROBE_MISCONFIGURED`` when the
         detector's probe was answered 404/405/401/403; otherwise
         ``AT_HOME_SERVER_DOWN``. The battery's reserve floor, enforced by
         the sequencer, is the only other bound.
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
        joinWaitSec: float,
        stallSec: float,
        sleepFn: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
        backlogReader: Callable[[], int | None] | None = None,
        lastProbe: Callable[[], ProbeResult | None] | None = None,
        nowIsoFn: Callable[[], str] | None = None,
        lossGeneration: Callable[[], int] | None = None,
        writeProvisional: Callable[[SyncOutcomeRecord], None] | None = None,
    ):
        """Args:
        homeState: Zero-arg home-network read, called once per ``run()``,
            then once per poll while it reads ``AT_HOME_JOINING``.
            Production passes ``HomeNetworkDetector.getHomeNetworkState``;
            every subprocess and HTTP call behind it is timeout-bounded.
        runSync: Zero-arg one-shot DB sync; returns on success, raises on
            failure (RuntimeError-family = transient/retryable).
        writeRecord: Single-arg sink, called exactly once per ``run()`` with
            the :class:`SyncOutcomeRecord`.
        joinWaitSec: ARCH-065 -- ``pi.homeNetwork.joinWaitSec``. How long an
            AT_HOME_JOINING wait polls for the association (US-776-e).
        stallSec: ARCH-065 -- ``pi.homeNetwork.stallSec``. The drain ends
            once the backlog has not fallen for this long (clock starts at
            association). The sequencer's reserve-floor poll may end the
            shutdown sooner.
        sleepFn: Wait between attempts; ``time.sleep`` when None.
        monotonic: Clock the waits are measured on; ``time.monotonic``
            when None.
        backlogReader: US-776-d -- zero-arg count of unsynced rows (the
            shared US-621 reader), ``None`` when it cannot say. Read before
            the first attempt and after the last. When None the record's
            backlog counts are ``None``.
        lastProbe: US-776-d -- zero-arg read of the probe behind the home
            state (``HomeNetworkDetector.lastProbe``); never probes again.
            Classifies a failed drain at home. When None, a failed drain at
            home is ``AT_HOME_SERVER_DOWN``.
        nowIsoFn: ARCH-065 -- UTC ISO-second clock stamping the drain's start
            and end; ``utcIsoNow`` when None.
        lossGeneration: Ruling 19 -- ``HomeStateAtLoss.lossGeneration``. Read
            ONCE at the start of ``run()``; the record carries it, and
            ``lastOutcome`` is set only while it is still the current loss.
            When None, every run is treated as current (no generation).
        writeProvisional: US-833 -- optional sink for the PROVISIONAL
            ``INTERRUPTED`` record, written at run start (``backlogStart``) and
            again at drain start (``startedAt``) so a poweroff that ends the run
            early leaves an honest record, not silence. Production passes the
            same file as ``writeRecord`` (the final outcome overwrites it). It
            never sets ``lastOutcome`` and a failing write never stops the run.
            When None, no provisional record is written.
        """
        self._homeState = homeState
        self._runSync = runSync
        self._writeRecord = writeRecord
        self._joinWaitSec = float(joinWaitSec)
        self._stallSec = float(stallSec)
        #: The kind the last run() ended with (read by the sequencer); None before.
        self.lastOutcome: OutcomeKind | None = None
        # Resolved at construction, not at import, so a patched time module
        # is honoured.
        self._sleep = sleepFn if sleepFn is not None else time.sleep
        self._monotonic = monotonic if monotonic is not None else time.monotonic
        self._backlogReader = backlogReader
        self._lastProbe = lastProbe
        self._nowIso = nowIsoFn if nowIsoFn is not None else utcIsoNow
        self._lossGeneration = lossGeneration
        self._writeProvisional = writeProvisional

    def run(self) -> OutcomeKind:
        """Run the CIO sync state machine and record its outcome. Never raises."""
        # M3: a reader mid-run never sees the PREVIOUS run's outcome.
        self.lastOutcome = None
        # I1: the loss this run belongs to, read once and kept LOCAL -- a later
        # run on another thread must not be able to rewrite it.
        generation = self._readLossGeneration()
        state = self._readHomeState()
        backlogStart = self._readBacklog()
        # US-833: from here on a cut leaves INTERRUPTED + the backlog, not silence.
        self._recordProvisional(backlogStart, None, generation)
        if state is HomeNetworkState.AT_HOME_JOINING:
            # US-776-e: the join wait is bounded on its own (joinWaitSec); the
            # drain's stall clock starts when the drain starts, at association.
            state = self._awaitAssociation(self._monotonic())
            if state is HomeNetworkState.AT_HOME_JOINING:
                return self._record(
                    OutcomeKind.AT_HOME_JOINING_TIMEOUT,
                    f"still joining the home WiFi after {self._joinWaitSec:.0f}s",
                    backlogStart,
                    backlogStart,
                    generation=generation,
                )
        if state is HomeNetworkState.AWAY:
            logger.info(
                "powerwatch sync_with_server: AWAY from home -- skipping the "
                "sync, powering off without waiting on the network"
            )
            # No attempt ran, so the start read is also the end.
            return self._record(
                OutcomeKind.AWAY, "away from home -- sync skipped", backlogStart, backlogStart,
                generation=generation,
            )
        if state is HomeNetworkState.UNKNOWN:
            logger.warning(
                "powerwatch sync_with_server: UNKNOWN_NETWORK -- home cannot be "
                "confirmed (SSID or IP reader unavailable) and nothing says "
                "AWAY -- draining anyway"
            )
        # ARCH-065: the drain's own span -- the JOINING wait above is not sync time.
        startedAt = self._stamp()
        self._recordProvisional(backlogStart, startedAt, generation)
        kind, detail = self._drain(state)
        endedAt = self._stamp()
        return self._record(
            kind, detail, backlogStart, self._readBacklog(), startedAt, endedAt,
            generation=generation,
        )

    def _awaitAssociation(self, startMono: float) -> HomeNetworkState:
        """Poll the home state while it reads AT_HOME_JOINING (US-776-e).

        Waits for NetworkManager's own association -- never forces a rescan or
        a connection. No poll wait is begun that would end at or past
        ``joinWaitSec``. Never raises.

        Returns:
            The first state that is not AT_HOME_JOINING, or AT_HOME_JOINING
            when ``joinWaitSec`` (or a broken wait) ended the polling.
        """
        logger.info(
            "powerwatch sync_with_server: AT_HOME_JOINING -- home WiFi in range "
            "but not associated; waiting up to %.0fs for the rejoin",
            self._joinWaitSec,
        )
        polls = 0
        while self._monotonic() - startMono + JOIN_POLL_SEC < self._joinWaitSec:
            try:
                self._sleep(JOIN_POLL_SEC)
            except Exception as exc:  # noqa: BLE001 -- never raise; a broken wait ends the polling
                logger.error(
                    "powerwatch sync_with_server: join wait failed (%s) -- giving up", exc
                )
                break
            polls += 1
            state = self._readHomeState()
            if state is not HomeNetworkState.AT_HOME_JOINING:
                logger.info(
                    "powerwatch sync_with_server: rejoin resolved as %s after %.0fs "
                    "(%d poll(s))",
                    state.name,
                    self._monotonic() - startMono,
                    polls,
                )
                return state
        logger.warning(
            "powerwatch sync_with_server: still AT_HOME_JOINING after %d poll(s) "
            "-- the %.0fs join wait is spent",
            polls,
            self._joinWaitSec,
        )
        return HomeNetworkState.AT_HOME_JOINING

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
        """Push until the backlog is empty, it stops falling for stallSec, or a real fault.

        No time cap (CIO 2026-10-02): the battery's reserve floor, enforced by the
        sequencer, is the only other bound. The backlog is RE-READ after every
        attempt: runSync can return having pushed nothing. Never raises.

        Args:
            state: The home state the drain was decided on.

        Returns:
            The outcome kind and its detail text.
        """
        lastRows = self._readBacklog()
        lastProgress = self._monotonic()
        wait = RETRY_FIRST_WAIT_SEC
        attempt = 0
        lastError: RuntimeError | None = None
        while True:
            attempt += 1
            try:
                self._runSync()
                lastError = None
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
            rows = self._readBacklog()
            if rows == 0 or (self._backlogReader is None and lastError is None):
                # With no backlog reader at all (no instrument) a clean runSync
                # is the only evidence there is. A reader that cannot read
                # (rows None) is NOT delivered: no evidence of progress is not
                # progress.
                logger.info(
                    "powerwatch sync_with_server: delivered after %d attempt(s)", attempt
                )
                return OutcomeKind.DELIVERED, f"delivered after {attempt} attempt(s)"
            now = self._monotonic()
            if rows is not None and (lastRows is None or rows < lastRows):
                lastProgress, lastRows, wait = now, rows, RETRY_FIRST_WAIT_SEC
                continue
            if now - lastProgress >= self._stallSec:
                break
            logger.warning(
                "powerwatch sync_with_server: attempt %d left backlog %s (%s) -- "
                "retrying in %.0fs (%.0fs of %.0fs without progress)",
                attempt,
                rows,
                lastError,
                wait,
                now - lastProgress,
                self._stallSec,
            )
            try:
                self._sleep(min(wait, max(0.0, self._stallSec - (now - lastProgress))))
            except Exception as exc:  # noqa: BLE001 -- never raise; a broken wait ends the drain
                logger.error(
                    "powerwatch sync_with_server: retry wait failed (%s) -- giving up", exc
                )
                break
            wait *= RETRY_WAIT_GROWTH

        detail = (
            f"backlog {lastRows} did not fall for {self._stallSec:.0f}s "
            f"(attempts={attempt}, last error {lastError})"
        )
        logger.error(
            "powerwatch sync_with_server: drain ended without delivery after %d "
            "attempt(s) (%s) -- continuing the shutdown",
            attempt,
            detail,
        )
        if lastError is not None:
            return self._classifyFailedDrain(state, detail)
        return OutcomeKind.STALLED, detail

    def _classifyFailedDrain(
        self, state: HomeNetworkState, detail: str
    ) -> tuple[OutcomeKind, str]:
        """Why a drain that stalled on a failing sync never delivered (US-776-d).

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

    def _readLossGeneration(self) -> int | None:
        """The current loss generation, or None (no source, or it raised). Never raises."""
        if self._lossGeneration is None:
            return None
        try:
            return int(self._lossGeneration())
        except Exception as exc:  # noqa: BLE001 -- never raise
            logger.warning("powerwatch sync_with_server: loss generation read failed (%s)", exc)
            return None

    def _stamp(self) -> str | None:
        """The injected ISO clock, never raising (a stamp must not break the drain)."""
        try:
            return self._nowIso()
        except Exception as exc:  # noqa: BLE001 -- never raise
            logger.warning("powerwatch sync_with_server: clock read failed (%s)", exc)
            return None

    def _recordProvisional(
        self, backlogStart: int | None, startedAt: str | None, generation: int | None
    ) -> None:
        """US-833: hand the PROVISIONAL INTERRUPTED record to its sink. Never raises.

        Deliberately NOT ``_record``: a provisional record is not an outcome, so
        it neither sets ``lastOutcome`` nor logs an outcome line.
        """
        if self._writeProvisional is None:
            return
        try:
            self._writeProvisional(SyncOutcomeRecord(
                OutcomeKind.INTERRUPTED,
                "provisional: the shutdown sync has not reached its end",
                backlogStart, None, startedAt, None, generation,
            ))
        except Exception as exc:  # noqa: BLE001 -- never raise; the drain must proceed
            logger.error(
                "powerwatch sync_with_server: could not write the provisional record (%s)",
                exc,
            )

    def _record(
        self,
        kind: OutcomeKind,
        detail: str,
        backlogStart: int | None,
        backlogEnd: int | None,
        startedAt: str | None = None,
        endedAt: str | None = None,
        *,
        generation: int | None = None,
    ) -> OutcomeKind:
        """Log the outcome and hand its one record to the sink. Never raises.

        ``lastOutcome`` is set only while ``generation`` is still the current
        loss: a run left over from a cancelled loss must not overwrite the
        current loss's outcome (its record is dropped by the sink too).
        """
        if generation is None or self._readLossGeneration() == generation:
            self.lastOutcome = kind
        logger.log(
            _OUTCOME_LOG_LEVEL.get(kind, logging.ERROR),
            "powerwatch sync_with_server: outcome=%s backlog_start=%s backlog_end=%s (%s)",
            kind.name,
            backlogStart,
            backlogEnd,
            detail,
        )
        try:
            self._writeRecord(SyncOutcomeRecord(
                kind, detail, backlogStart, backlogEnd, startedAt, endedAt, generation
            ))
        except Exception as exc:  # noqa: BLE001 -- never raise; the poweroff must proceed
            logger.error(
                "powerwatch sync_with_server: could not write the %s record (%s)",
                kind.name,
                exc,
            )
        return kind
