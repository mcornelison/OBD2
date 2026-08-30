################################################################################
# File Name: drain_event_writer.py
# Purpose/Description: The PRODUCTION drain-event writer (US-526 / F-123 /
#                      BL-028) -- the caller that makes battery_health_log grow
#                      again.  BatteryHealthRecorder has written the columns
#                      correctly since US-217, but no production caller has
#                      existed since the US-216 auto-open path was retired
#                      (US-442 / TD-058), so the battery Health verdict has had
#                      no rows to read and correctly reported `unknown`.
#
#                      Shape = Atlas's Option C ruling (2026-08-02, PM inbox
#                      2026-08-02-from-atlas-v0.29.25-prd-review.md):
#                        OPEN   at wall-power loss  (AC -> BATTERY)
#                        CLOSE  at power restore    (BATTERY -> AC)   [orchestrator]
#                               or on the shutdown path                [powerwatch,
#                               the PRIMARY close -- under Spool's depth gate the
#                               run-to-cutoff drain is the only qualifying drain
#                               and it ends exactly there]
#                        CHECK  the OPEN row every 30 s while draining
#                               (US-605 / Spool US-504a "Consequence 2")
#                        REAP   still-open rows at boot = crash BACKSTOP,
#                               honest-NA when nothing measured the drain, and
#                               the LAST CHECKPOINT when something did
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-03    | Rex (US-526) | Initial -- production writer + boot reaper.
# 2026-08-29    | Rex (US-605) | 30 s open-row checkpoint (Spool EXACT: 30) +
#              |               | the reaper close-onto-checkpoint it enables.
# ================================================================================
################################################################################

"""Production drain-event writer (US-526 / Atlas Option C).

Why the open and the close cannot share memory
----------------------------------------------
The open fires in the **collector** process (``PowerMonitor.onTransition``, fed
GPIO6 truth by the US-502 ``_PowerSourceUiBridge``); the cutoff close fires in
the **eclipse-powerwatch** process (``ShutdownSequencer``, immediately before
``systemctl poweroff``).  Two processes -- so a ``drain_event_id`` held in a
variable is unavailable exactly where it is needed most.  Every close therefore
RE-FINDS its row in the table.  This is why Atlas disqualified the memory-held
option: a hard crash would drop precisely the run-to-cutoff drain the verdict
needs.

The three honest-NA rules
-------------------------
1. **An unreadable gauge writes NULL.**  ``start_vcell_v`` / ``end_vcell_v`` /
   ``*_soc_pct`` are all nullable and a failed read records NULL -- never a
   guessed number, never a crash into a power transition or a poweroff.
2. **The reaper never calls** :meth:`BatteryHealthRecorder.endDrainEvent`.
   That method derives ``runtime_seconds`` from the start/end timestamp delta,
   so across a reboot it would manufacture a multi-hour runtime.  The reaper
   issues its OWN UPDATE stamping ``end_timestamp`` only, leaving
   ``runtime_seconds`` AND ``end_vcell_v`` NULL.  A NULL on either fails Spool's
   depth gate, so a reaped orphan cannot vote in the verdict (double-safe).
3. **Only rows THIS writer opened are ever touched.**  Atlas's DoD says the
   reaper targets still-open rows (``end_timestamp IS NULL``); this module
   NARROWS that to still-open rows carrying :data:`DRAIN_OPEN_NOTE`.  A
   narrowing can only make the backstop more conservative, and it is
   load-bearing: the four US-442 historical orphans (``drain_event_id``
   1/9/18/21) hold ``end_timestamp IS NULL`` **deliberately** -- there is no
   timing-truth source for them, and that NULL is what keeps
   ``scripts/annotate_orphan_production_drain_events.py`` idempotent.  Without
   the narrowing, the first power-restore close would hand one of those
   months-old rows to ``endDrainEvent`` and mint a row with a multi-month
   ``runtime_seconds`` and a real ``end_vcell_v`` -- i.e. a row that looks
   QUALIFYING to the verdict.  That is strictly worse than the reaper trap.

An UN-CHECKPOINTED reaped row is identifiable by its signature --
``end_timestamp`` NOT NULL with ``runtime_seconds`` NULL and ``end_vcell_v``
NULL -- and every reap is logged at WARNING, so interrupted drains stay visible
instead of silently vanishing.

The 30 s checkpoint (US-605), and what it changes above
------------------------------------------------------
Spool's US-504a ruling ("Consequence 2", commit 429a3ed) specified that the OPEN
row be UPDATEd every **30 s** while draining with the current
``end_vcell_v`` / ``end_soc_pct`` / ``runtime_seconds``.  US-526 shipped without
it, so a single lost shutdown write discarded a CORRECT measurement outright.
His framing is the design argument: the checkpoint converts "must not lose the
shutdown write" from a HARD requirement into a SOFT one.

Three properties make that safe rather than merely convenient.

1. **A checkpoint never writes a value it has not read.**  The UPDATE's SET list
   is built from the readings that actually succeeded, so a gauge dying mid-drain
   leaves the last good ``end_vcell_v`` standing while ``runtime_seconds`` -- which
   comes from the clock, not the gauge -- keeps advancing.  Writing NULL on a
   failed read would make the checkpoint the thing that LOSES the drain, which is
   the exact defect it exists to prevent.
2. **A checkpoint never closes the row.**  It writes neither ``end_timestamp``
   nor ``notes`` -- the two columns every other reader keys on.  ``end_timestamp``
   is the "closed" marker for the ownership finder, the ``endDrainEvent``
   close-once guard, the reaper and the verdict's qualifying query alike, so a
   checkpointed row stays findable, closable and (correctly) unable to vote in
   the battery-health verdict while it is still draining.
3. **A checkpoint cannot outrun a close.**  The UPDATE re-asserts
   ``end_timestamp IS NULL``, because the collector's checkpoint and the
   powerwatch close run in DIFFERENT PROCESSES.  Without that clause a checkpoint
   in flight when the shutdown close lands would overwrite the final cutoff depth
   -- Spool's depth gate qualifies on exactly that value -- with an older reading.

The reaper consequently gains one branch.  A row carrying a checkpointed
``runtime_seconds`` is closed at ``start_timestamp + runtime_seconds`` -- the last
instant anything observed the Pi alive and draining -- rather than at the reap
instant, so the row cannot carry two contradictory durations.  Because that
destroys the honest-NA signature above, the reaper appends
:data:`REAP_CHECKPOINTED_NOTE_SUFFIX` so "this close came from a checkpoint, and
both depth and duration therefore UNDERSTATE the real drain by up to one
interval" is a POSITIVE statement rather than an absence a reader must infer.
An un-checkpointed row reaps exactly as it did before.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.common.time.helper import CANONICAL_ISO_FORMAT, utcIsoNow
from src.pi.power.battery_health import (
    BATTERY_HEALTH_LOG_TABLE,
    LOAD_CLASS_DEFAULT,
    BatteryHealthRecorder,
    DrainEventCloseResult,
    _computeRuntimeSeconds,
)
from src.pi.power.soc_calibration import (
    COLD_START_CALIBRATION_WINDOW_SECONDS,
    readCalibratedRegisterSocPct,
    readSystemUptimeSeconds,
)

logger = logging.getLogger(__name__)

__all__ = [
    'DRAIN_CHECKPOINT_INTERVAL_SECONDS',
    'DRAIN_OPEN_NOTE',
    'POWER_SOURCE_AC_VALUE',
    'POWER_SOURCE_BATTERY_VALUE',
    'CLOSE_REASON_POWER_RESTORED',
    'CLOSE_REASON_SHUTDOWN',
    'REAP_CHECKPOINTED_NOTE_SUFFIX',
    'DrainEventWriter',
    'UpsSnapshot',
    'makeDrainEventWriterForPath',
]


# ================================================================================
# Constants
# ================================================================================

#: Provenance stamp written to ``notes`` at open.  It is also the writer's
#: OWNERSHIP MARKER: close + reap both require it, so this writer can only ever
#: touch rows it opened itself (see rule 3 in the module docstring).  Changing
#: this string orphans in-flight rows opened by the previous version -- they stay
#: open until the next reaper run, which will not match them either.  Treat it as
#: a stored contract, not a log message.
DRAIN_OPEN_NOTE: str = (
    'production drain: opened at wall-power loss by DrainEventWriter (US-526)'
)

#: ``PowerSource`` enum VALUES, not members.  ``pi.power.types`` and
#: ``src.pi.power.types`` are distinct module objects, so their ``PowerSource``
#: members are not ``==`` to each other -- comparing members would let a
#: dual-imported enum make this writer silently inert (the cross-module
#: enum-identity class of bug that cost the 9-drain saga).
POWER_SOURCE_AC_VALUE: str = 'ac_power'
POWER_SOURCE_BATTERY_VALUE: str = 'battery'

#: Close reasons (log context only -- the schema has no reason column).
CLOSE_REASON_POWER_RESTORED: str = 'power_restored'
CLOSE_REASON_SHUTDOWN: str = 'shutdown'

#: Seconds between checkpoints of the OPEN drain row.
#:
#: GROUNDING: Spool's US-504a ruling (commit 429a3ed, "Consequence 2") specifies
#: **[EXACT: 30]** seconds.  US-605 AC-3 is explicit that it must NOT be
#: re-tuned here -- it is a grounded value and changing it is his call.  It is
#: deliberately NOT a config key: a tunable would be a standing invitation to
#: re-tune a number that is somebody else's to set, and Rule 2 forbids inventing
#: one the story did not ground.  The constructor takes an override for TESTS,
#: which is how the cadence is exercised without sleeping through it.
DRAIN_CHECKPOINT_INTERVAL_SECONDS: float = 30.0

#: Appended to ``notes`` when the boot reaper closes a row onto its last
#: checkpoint.  US-526 made an interrupted drain identifiable by its SIGNATURE
#: (end_timestamp present, runtime_seconds and end_vcell_v NULL); a checkpointed
#: row destroys that signature by carrying real values, so the fact has to be
#: stated POSITIVELY instead of inferred from an absence.  It is load-bearing
#: for the reader: a checkpointed close understates both depth and duration by
#: up to one interval, so these are FLOORS, not final values.
REAP_CHECKPOINTED_NOTE_SUFFIX: str = (
    ' | INTERRUPTED (US-605): closed by the boot reaper at the last 30 s '
    'checkpoint -- depth and runtime are CHECKPOINTED values and both '
    'UNDERSTATE the real drain by up to one checkpoint interval'
)

_SELECT_OWN_OPEN_ROW_SQL: str = (
    "SELECT drain_event_id, start_timestamp, runtime_seconds "
    f"FROM {BATTERY_HEALTH_LOG_TABLE} "
    "WHERE end_timestamp IS NULL AND notes = ? AND load_class = ? "
    "ORDER BY drain_event_id DESC"
)

#: Reaper UPDATE for a row NOTHING measured.  Stamps end_timestamp ONLY --
#: runtime_seconds, end_vcell_v and end_soc_pct are deliberately absent from the
#: SET list so they stay NULL, and ``notes`` is left exactly as opened.
_REAP_UPDATE_SQL: str = (
    f"UPDATE {BATTERY_HEALTH_LOG_TABLE} SET end_timestamp = ? "
    "WHERE drain_event_id = ? AND end_timestamp IS NULL"
)

#: Reaper UPDATE for a row a checkpoint DID measure (US-605).  end_timestamp is
#: the last checkpoint instant, never the reap instant -- stamping the reap
#: instant beside a checkpointed runtime would put two contradictory durations
#: on one row.  The gauge is still not read: today's resting voltage is not the
#: interrupted drain's depth.
_REAP_FROM_CHECKPOINT_UPDATE_SQL: str = (
    f"UPDATE {BATTERY_HEALTH_LOG_TABLE} SET end_timestamp = ?, "
    "notes = COALESCE(notes, '') || ? "
    "WHERE drain_event_id = ? AND end_timestamp IS NULL"
)


# ================================================================================
# Gauge snapshot
# ================================================================================


@dataclass(frozen=True)
class UpsSnapshot:
    """One MAX17048 sample, with NULLs where the gauge could not be trusted.

    Attributes:
        vcellVolts: LiPo cell volts, or None when the gauge could not be read.
            NOT cold-start guarded -- cell voltage is trustworthy immediately.
        socPct: Register State-of-Charge percent, or None when the gauge is (or
            may be) inside its calibration window, or the read failed.
    """

    vcellVolts: float | None
    socPct: int | None


_NO_READING = UpsSnapshot(vcellVolts=None, socPct=None)


@dataclass(frozen=True)
class _OpenDrainRow:
    """One still-open row of this writer's, as the finder reads it.

    Attributes:
        drainEventId: The row's PK.
        startTimestamp: Its ``start_timestamp`` -- the anchor every runtime is
            measured from, by the checkpoint and the close alike.
        runtimeSeconds: The last CHECKPOINTED runtime, or None when no
            checkpoint has landed on this row.  This is the single fact that
            tells the reaper whether anything measured the drain.
    """

    drainEventId: int
    startTimestamp: Any
    runtimeSeconds: int | None


# ================================================================================
# Writer
# ================================================================================


class DrainEventWriter:
    """Open / close / reap ``battery_health_log`` production drain rows.

    Every public method is total: it logs and returns a benign value rather than
    raising.  Two of the three call sites make that mandatory -- a power
    transition callback must not break ``PowerMonitor``'s callback chain, and the
    shutdown-path close runs microseconds before ``systemctl poweroff`` where a
    raise would be the difference between a clean poweroff and an unclean one.
    """

    def __init__(
        self,
        *,
        database: Any,
        upsResolver: Callable[[], Any | None],
        uptimeReader: Callable[[], float | None] | None = None,
        coldStartWindowSeconds: float = COLD_START_CALIBRATION_WINDOW_SECONDS,
        loadClass: str = LOAD_CLASS_DEFAULT,
        monotonicFn: Callable[[], float] | None = None,
        checkpointIntervalSeconds: float = DRAIN_CHECKPOINT_INTERVAL_SECONDS,
    ) -> None:
        """Args:
            database: ``DatabaseLike`` -- anything exposing ``connect()`` as a
                context manager yielding a DB-API connection (``ObdDatabase`` in
                the collector; see :func:`makeDrainEventWriterForPath` for the
                powerwatch process, which has no ``ObdDatabase``).
            upsResolver: Zero-arg callable returning the live ``UpsMonitor``, or
                None when it does not exist yet.  Called at TRANSITION TIME, not
                captured at construction: the writer is wired during component
                init while ``UpsMonitor`` is created later inside
                ``HardwareManager.start()`` -- capturing the value here would
                pin None forever (the US-501/502/503 boot-order trap, now six
                sightings).
            uptimeReader: Zero-arg seconds-since-power-up reader feeding the
                SoC%% cold-start guard.  Defaults to
                :func:`readSystemUptimeSeconds`.
            coldStartWindowSeconds: The cold-start guard window; resolve it from
                config with
                :func:`src.pi.power.soc_calibration.resolveColdStartWindowSeconds`
                rather than passing a literal.
            loadClass: ``battery_health_log.load_class``.  Defaults to
                ``'production'`` -- the only class the verdict counts.  A bench
                harness may pass ``'test'`` to keep drill rows out of the
                production baseline.
            monotonicFn: Zero-arg elapsed-seconds reader gating the US-605
                checkpoint cadence.  Defaults to :func:`time.monotonic`, and
                that choice is load-bearing rather than stylistic: US-620
                MEASURED this Pi booting at 1970-01-01 and stepping hours
                forward the instant NTP lands, and US-625 had to rebuild a
                drive idle bound for exactly that reason.  A wall-clock gate
                would read the NTP step as elapsed drain time.
            checkpointIntervalSeconds: Seconds between checkpoints.  Defaults
                to :data:`DRAIN_CHECKPOINT_INTERVAL_SECONDS` (Spool's EXACT 30);
                overridden by TESTS only, so the cadence can be exercised
                without sleeping through it.
        """
        self._recorder = BatteryHealthRecorder(database=database)
        self._database = database
        self._resolveUps = upsResolver
        self._readUptime = uptimeReader or readSystemUptimeSeconds
        self._coldStartWindowSeconds = float(coldStartWindowSeconds)
        self._loadClass = loadClass
        self._monotonic = monotonicFn or time.monotonic
        self._checkpointIntervalSeconds = float(checkpointIntervalSeconds)
        self._lastCheckpointMonotonic: float | None = None

    @property
    def checkpointIntervalSeconds(self) -> float:
        """Seconds between checkpoints of the open drain row (Spool EXACT: 30)."""
        return self._checkpointIntervalSeconds

    # ----- PowerMonitor.onTransition sink -------------------------------------

    def handlePowerTransition(
        self, fromSource: Any, toSource: Any,
    ) -> int | DrainEventCloseResult | None:
        """Open or close a drain row from a ``PowerMonitor`` transition.

        Registered via ``PowerMonitor.onTransition`` (the AC [SEAM]).  Accepts
        ``PowerSource`` members or their raw string values and compares on
        ``.value`` -- see :data:`POWER_SOURCE_AC_VALUE`.

        Only a real AC->BATTERY opens and only BATTERY->AC closes.  Anything
        else is ignored, which matters most for UNKNOWN->BATTERY: a Pi that
        boots already on battery has no knowable loss instant, so a row stamped
        at boot time would misreport the drain's start and therefore its
        runtime.  ``PowerMonitor._handleTransition`` already suppresses
        transitions out of UNKNOWN; this method does not add a path around it.

        Args:
            fromSource: Previous power source (member or value).
            toSource: New power source (member or value).

        Returns:
            The new ``drain_event_id`` on an open, the
            :class:`DrainEventCloseResult` on a close, or None when the
            transition is not a drain boundary (or the write failed).
        """
        fromValue = _sourceValue(fromSource)
        toValue = _sourceValue(toSource)

        if (
            fromValue == POWER_SOURCE_AC_VALUE
            and toValue == POWER_SOURCE_BATTERY_VALUE
        ):
            return self.openDrainEvent()
        if (
            fromValue == POWER_SOURCE_BATTERY_VALUE
            and toValue == POWER_SOURCE_AC_VALUE
        ):
            return self.closeOpenDrainEvent(
                reason=CLOSE_REASON_POWER_RESTORED,
            )
        logger.debug(
            "drain writer: %s -> %s is not a drain boundary -- ignored",
            fromValue, toValue,
        )
        return None

    # ----- Open ----------------------------------------------------------------

    def openDrainEvent(self) -> int | None:
        """Open a drain row for a wall-power loss that just happened.

        Returns:
            The new ``drain_event_id``, or None if the row could not be written
            (logged; a failed drain record must never break the power path).
        """
        snapshot = self._readUps()
        try:
            drainEventId = self._recorder.startDrainEvent(
                startSoc=snapshot.vcellVolts,
                loadClass=self._loadClass,
                notes=DRAIN_OPEN_NOTE,
                dataSource='real',
                startSocPct=snapshot.socPct,
            )
        except Exception as exc:  # noqa: BLE001 -- power path must not break
            logger.error(
                "drain writer: FAILED to open a drain row at wall-power loss "
                "(%s) -- this drain will not reach battery_health_log", exc,
            )
            return None
        # US-605: anchor the checkpoint cadence on the OPEN, so the first
        # checkpoint lands one full interval INTO the drain rather than at a
        # position inherited from whenever the run loop last happened to look.
        self._lastCheckpointMonotonic = self._monotonic()
        logger.warning(
            "drain writer: wall power LOST -- drain event %d opened "
            "(start_vcell_v=%s, start_soc_pct=%s)",
            drainEventId, snapshot.vcellVolts, snapshot.socPct,
        )
        return drainEventId

    # ----- Checkpoint (US-605 / Spool US-504a "Consequence 2") -----------------

    def checkpointOpenDrainEvent(self) -> int | None:
        """Write live end-of-drain values onto the still-OPEN row, every 30 s.

        Cheap to call every run-loop pass: this method is its own cadence gate
        and short-circuits when the interval has not elapsed, so the enclosing
        loop needs no state (the ``_maybeTrigger*`` shape US-226 / US-247
        established).  It NEVER raises -- it shares the loop that drives OBD
        capture, and battery bookkeeping must never cost a drive.

        The row stays OPEN: ``end_timestamp`` and ``notes`` are untouched, so
        the ownership finder still finds it, the close still closes it, and the
        verdict's qualifying query (which gates on ``end_timestamp IS NOT NULL``
        first) still cannot let a drain in progress vote.

        Only columns whose value was actually READ this pass are written
        (AC-5).  A gauge that died mid-drain therefore leaves the last good
        depth standing while the runtime keeps advancing -- NULLing a real
        reading would make the checkpoint the thing that loses the measurement.

        Returns:
            The ``drain_event_id`` a checkpoint was written to, or None when
            the interval has not elapsed, no row of this writer's is open,
            nothing could be read, the row was closed by the other process
            between the read and the write, or the write failed (all logged).
        """
        now = self._monotonic()
        last = self._lastCheckpointMonotonic
        if last is not None and (now - last) < self._checkpointIntervalSeconds:
            return None
        # Anchor on the ATTEMPT, not on a successful write: otherwise a Pi
        # sitting on wall power (no open row -- the overwhelmingly common case)
        # would re-run the ownership SELECT on every single loop pass forever.
        self._lastCheckpointMonotonic = now

        openRows = self._findOwnOpenRows()
        if not openRows:
            return None
        row = openRows[0]

        # Read the gauge ONLY once there is a row to write it to -- otherwise
        # this puts I2C traffic on the bus for no record at all.
        snapshot = self._readUps()
        assignments: list[str] = []
        params: list[Any] = []

        # ONE predicate for the checkpoint and the close, so "how long has this
        # drain run" can never be answered two different ways (the US-621
        # _deltaPredicate / US-625 isDriveIdStale discipline).  _computeRuntimeSeconds
        # is module-private to battery_health and imported deliberately: a second
        # implementation here is exactly the drift that discipline forbids.
        runtimeSeconds = _computeRuntimeSeconds(str(row.startTimestamp), utcIsoNow())
        if runtimeSeconds is not None:
            assignments.append("runtime_seconds = ?")
            params.append(int(runtimeSeconds))
        if snapshot.vcellVolts is not None:
            assignments.append("end_vcell_v = ?")
            params.append(float(snapshot.vcellVolts))
        if snapshot.socPct is not None:
            assignments.append("end_soc_pct = ?")
            params.append(float(snapshot.socPct))

        if not assignments:
            logger.warning(
                "drain writer: checkpoint for drain event %d read NOTHING "
                "(no gauge and no derivable runtime) -- writing nothing rather "
                "than a value it has not read", row.drainEventId,
            )
            return None

        params.append(int(row.drainEventId))
        sql = (
            f"UPDATE {BATTERY_HEALTH_LOG_TABLE} SET " + ", ".join(assignments)
            # The end_timestamp re-assertion is the cross-PROCESS guard: the
            # powerwatch close can land between the SELECT above and this
            # UPDATE, and an older checkpoint reading must never overwrite the
            # final cutoff depth Spool's gate qualifies on.
            + " WHERE drain_event_id = ? AND end_timestamp IS NULL"
        )
        try:
            with self._database.connect() as conn:
                written = bool(conn.execute(sql, tuple(params)).rowcount)
        except Exception as exc:  # noqa: BLE001 -- run loop must not break
            logger.error(
                "drain writer: checkpoint of drain event %d FAILED (%s) -- the "
                "row keeps its previous checkpoint", row.drainEventId, exc,
            )
            return None

        if not written:
            logger.info(
                "drain writer: drain event %d was closed between the read and "
                "the checkpoint write -- no-op (the close is the final word)",
                row.drainEventId,
            )
            return None

        logger.info(
            "drain writer: drain event %d checkpointed (runtime_s=%s, "
            "end_vcell_v=%s, end_soc_pct=%s) -- row still OPEN",
            row.drainEventId, runtimeSeconds, snapshot.vcellVolts,
            snapshot.socPct,
        )
        return int(row.drainEventId)

    # ----- Close ---------------------------------------------------------------

    def closeOpenDrainEvent(
        self, *, reason: str = CLOSE_REASON_SHUTDOWN,
    ) -> DrainEventCloseResult | None:
        """Close this writer's still-open drain row, if there is one.

        Re-finds the row in the table rather than trusting a held id -- the
        cutoff close runs in a different process from the open (see the module
        docstring).  ``runtime_seconds`` is computed by
        :meth:`BatteryHealthRecorder.endDrainEvent` from the timestamp delta,
        which is truthful here because the boot reaper has already closed any
        row from a previous boot, so a row found open is necessarily same-boot.

        Args:
            reason: Log context (``power_restored`` / ``shutdown``).

        Returns:
            The :class:`DrainEventCloseResult`, or None when there was no row of
            this writer's to close (or the close failed).
        """
        drainEventId = self._findOwnOpenDrainEventId()
        if drainEventId is None:
            logger.info(
                "drain writer: no open drain row of ours to close "
                "(reason=%s) -- nothing to do", reason,
            )
            return None

        snapshot = self._readUps()
        try:
            result = self._recorder.endDrainEvent(
                drainEventId=drainEventId,
                endSoc=snapshot.vcellVolts,
                endSocPct=snapshot.socPct,
            )
        except Exception as exc:  # noqa: BLE001 -- must not block poweroff
            logger.error(
                "drain writer: FAILED to close drain event %d (reason=%s): "
                "%s -- the boot reaper will mark it interrupted",
                drainEventId, reason, exc,
            )
            return None
        logger.warning(
            "drain writer: drain event %d closed (reason=%s, end_vcell_v=%s, "
            "end_soc_pct=%s, runtime_s=%s)",
            drainEventId, reason, snapshot.vcellVolts, snapshot.socPct,
            result.runtimeSeconds,
        )
        return result

    # ----- Reap (boot backstop) ------------------------------------------------

    def reapOpenDrainEvents(self) -> list[int]:
        """Mark this writer's still-open rows as interrupted (honest-NA).

        Run ONCE at boot, BEFORE any transition can open a new row -- that
        ordering is what makes every runtime this writer computes a same-boot
        delta.  A row found open at boot was orphaned by a hard crash or an
        unclean poweroff, so its duration and depth are both unknown.

        This method must NEVER call ``endDrainEvent`` (which would manufacture a
        runtime from a cross-reboot timestamp delta) and must never read the
        gauge (today's resting voltage is not the interrupted drain's depth --
        and a fabricated value at or under Spool's 3.50 V depth gate would
        falsely QUALIFY the row).  Beyond that it takes one of two branches,
        decided entirely by whether a US-605 checkpoint measured the drain:

        * **Nothing measured it** (died inside the first interval): stamp
          ``end_timestamp`` only, exactly as US-526 always did.
          ``runtime_seconds`` and ``end_vcell_v`` stay NULL, the row cannot
          vote, and ``notes`` are untouched.
        * **A checkpoint measured it**: stamp ``end_timestamp`` at
          ``start_timestamp + runtime_seconds`` -- the last instant anything
          observed the Pi alive and draining -- and append
          :data:`REAP_CHECKPOINTED_NOTE_SUFFIX`.  The reap instant is NOT used:
          beside a checkpointed runtime it would put two contradictory
          durations on one row.  This row CAN vote, which is the point of
          US-605: the shutdown write stops being a hard requirement.

        Returns:
            The ``drain_event_id`` list actually stamped (empty on none, or on
            an unreadable log -- an unreadable table is UNCERTAIN, never
            silently "nothing to reap that mattered").
        """
        openRows = self._findOwnOpenRows()
        if not openRows:
            return []

        reapTs = utcIsoNow()
        reaped: list[int] = []
        stamped: list[tuple[int, str | None]] = []
        try:
            with self._database.connect() as conn:
                for row in openRows:
                    checkpointTs = _checkpointInstant(
                        row.startTimestamp, row.runtimeSeconds,
                    )
                    if checkpointTs is not None:
                        cursor = conn.execute(
                            _REAP_FROM_CHECKPOINT_UPDATE_SQL,
                            (
                                checkpointTs, REAP_CHECKPOINTED_NOTE_SUFFIX,
                                row.drainEventId,
                            ),
                        )
                    else:
                        cursor = conn.execute(
                            _REAP_UPDATE_SQL, (reapTs, row.drainEventId),
                        )
                    if cursor.rowcount:
                        reaped.append(row.drainEventId)
                        stamped.append((row.drainEventId, checkpointTs))
        except Exception as exc:  # noqa: BLE001 -- boot path must not break
            logger.error(
                "drain writer: boot reap FAILED (%s) -- %d row(s) stay open; "
                "they will be retried next boot", exc, len(openRows),
            )
            return []

        for drainEventId, checkpointTs in stamped:
            if checkpointTs is not None:
                logger.warning(
                    "drain writer: drain event %d was left OPEN by a crash or "
                    "unclean poweroff -- closed at its LAST CHECKPOINT "
                    "(end_timestamp=%s), so its measured duration and depth "
                    "SURVIVE and it can vote in the battery-health verdict. "
                    "Both UNDERSTATE the real drain by up to %.0f s (US-605).",
                    drainEventId, checkpointTs, self._checkpointIntervalSeconds,
                )
            else:
                logger.warning(
                    "drain writer: drain event %d was left OPEN by a crash or "
                    "unclean poweroff BEFORE its first checkpoint -- stamped "
                    "end_timestamp=%s with runtime_seconds AND end_vcell_v "
                    "left NULL (interrupted drain: duration and depth are "
                    "unknown, never fabricated). It cannot vote in the "
                    "battery-health verdict.",
                    drainEventId, reapTs,
                )
        return reaped

    # ----- Internals -----------------------------------------------------------

    def _readUps(self) -> UpsSnapshot:
        """Sample the gauge LATE (at call time), NULLing whatever it cannot give.

        Returns:
            An :class:`UpsSnapshot`; ``_NO_READING`` when no UPS exists.
        """
        ups = _resolveSafely(self._resolveUps)
        if ups is None:
            logger.warning(
                "drain writer: no UpsMonitor available -- recording NULL "
                "vcell + soc_pct (honest-instrument, never a guessed number)"
            )
            return _NO_READING

        vcellVolts: float | None
        try:
            vcellVolts = float(ups.getVcell())
        except Exception as exc:  # noqa: BLE001 -- unreadable gauge -> NULL
            logger.warning(
                "drain writer: VCELL read failed -> NULL: %s", exc,
            )
            vcellVolts = None

        socPct = readCalibratedRegisterSocPct(
            ups,
            uptimeSeconds=_resolveSafely(self._readUptime),
            calibrationWindowSeconds=self._coldStartWindowSeconds,
        )
        return UpsSnapshot(vcellVolts=vcellVolts, socPct=socPct)

    def _findOwnOpenRows(self) -> list[_OpenDrainRow]:
        """Return this writer's still-open rows, newest first.

        Carries ``start_timestamp`` and the last checkpointed
        ``runtime_seconds`` alongside the id: the checkpoint needs the anchor
        it measures from, and the reaper needs to know whether anything
        measured the drain at all.
        """
        try:
            with self._database.connect() as conn:
                fetched = conn.execute(
                    _SELECT_OWN_OPEN_ROW_SQL,
                    (DRAIN_OPEN_NOTE, self._loadClass),
                ).fetchall()
        except Exception as exc:  # noqa: BLE001 -- unreadable log -> none
            logger.error(
                "drain writer: could not read open drain rows (%s)", exc,
            )
            return []
        return [
            _OpenDrainRow(
                drainEventId=int(row[0]),
                startTimestamp=row[1],
                runtimeSeconds=int(row[2]) if row[2] is not None else None,
            )
            for row in fetched
        ]

    def _findOwnOpenDrainEventId(self) -> int | None:
        """Return the newest still-open row of this writer's, or None."""
        openRows = self._findOwnOpenRows()
        if not openRows:
            return None
        if len(openRows) > 1:
            # Only reachable if a boot reap was skipped; closing the newest is
            # the honest choice (it is the one this boot opened) and the older
            # ones stay open for the next reaper run.
            logger.warning(
                "drain writer: %d open drain rows found (%s) -- closing the "
                "newest only; the rest await the boot reaper",
                len(openRows), [r.drainEventId for r in openRows],
            )
        return openRows[0].drainEventId


# ================================================================================
# Module helpers
# ================================================================================


def _sourceValue(source: Any) -> str:
    """Return a ``PowerSource``-ish as its raw string value.

    Accepts an enum member (any class object -- see
    :data:`POWER_SOURCE_AC_VALUE` on why identity is not trusted) or a plain
    string.
    """
    value = getattr(source, 'value', source)
    return value if isinstance(value, str) else str(value)


def _checkpointInstant(startTs: Any, runtimeSeconds: int | None) -> str | None:
    """Return the instant of the last checkpoint, or None if there was none.

    ``start_timestamp + runtime_seconds`` is the last moment anything actually
    observed this drain alive -- which is what makes it the only honest
    ``end_timestamp`` for a row the reaper closes from a checkpoint.  Returns
    None when no checkpoint landed (``runtimeSeconds`` is None) or the start
    anchor is unparseable, in which case the caller keeps US-526's original
    reap-instant behaviour rather than deriving a number from a bad input.
    """
    if runtimeSeconds is None:
        return None
    try:
        start = datetime.strptime(str(startTs), CANONICAL_ISO_FORMAT)
    except (TypeError, ValueError):
        return None
    return (
        start + timedelta(seconds=int(runtimeSeconds))
    ).strftime(CANONICAL_ISO_FORMAT)


def _resolveSafely(resolver: Callable[[], Any]) -> Any:
    """Call a zero-arg resolver, returning None if it raises."""
    try:
        return resolver()
    except Exception as exc:  # noqa: BLE001 -- a probe must never break a write
        logger.warning("drain writer: resolver failed (%s) -> None", exc)
        return None


class _SqliteDrainDatabase:
    """Minimal ``DatabaseLike`` over a sqlite path (no ``pi.obdii`` import).

    The powerwatch service is shutdown-critical and its import graph is a
    known hazard (the V0.27.12-DOA class).  Importing ``ObdDatabase`` would drag
    the whole ``pi.obdii`` package -- including the display imports its
    ``__init__`` pulls -- into that process just to get a ``connect()``.  This
    adapter mirrors ``ObdDatabase.connect``'s commit-on-success /
    rollback-on-error / always-close contract over stdlib sqlite3 alone.

    ``busyTimeoutSec`` is deliberately a caller value rather than
    ``ObdDatabase``'s 30 s: on the shutdown path a lock-wait delays
    ``systemctl poweroff``, so the caller passes the bound the shutdown path
    already defines for one unit of work (``pi.powerWatch.perTaskTimeoutSec``).
    """

    def __init__(self, *, dbPath: str, busyTimeoutSec: float) -> None:
        self.dbPath = dbPath
        self._busyTimeoutSec = float(busyTimeoutSec)

    @contextmanager
    def connect(self) -> Any:
        """Yield a sqlite3 connection; commit on success, rollback on error."""
        if not Path(self.dbPath).exists():
            # Do NOT let sqlite3 create an empty db (and its parent tree) on a
            # path that has no schema -- that would turn "no data" into a
            # silently-empty new database.
            raise FileNotFoundError(f"sqlite database not found: {self.dbPath}")
        conn = sqlite3.connect(self.dbPath, timeout=self._busyTimeoutSec)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def makeDrainEventWriterForPath(
    *,
    dbPath: str,
    upsResolver: Callable[[], Any | None],
    busyTimeoutSec: float,
    uptimeReader: Callable[[], float | None] | None = None,
    coldStartWindowSeconds: float = COLD_START_CALIBRATION_WINDOW_SECONDS,
    loadClass: str = LOAD_CLASS_DEFAULT,
) -> DrainEventWriter:
    """Build a writer from a sqlite path -- for the powerwatch process.

    Args:
        dbPath: ``pi.database.path`` from validated config.
        upsResolver: See :class:`DrainEventWriter`.
        busyTimeoutSec: sqlite busy timeout.  Pass the shutdown path's own
            per-unit-of-work bound (``pi.powerWatch.perTaskTimeoutSec``) so a
            locked database cannot delay poweroff.
        uptimeReader: See :class:`DrainEventWriter`.
        coldStartWindowSeconds: See :class:`DrainEventWriter`.
        loadClass: See :class:`DrainEventWriter`.

    Returns:
        A :class:`DrainEventWriter` writing through a plain sqlite connection.
    """
    return DrainEventWriter(
        database=_SqliteDrainDatabase(
            dbPath=dbPath, busyTimeoutSec=busyTimeoutSec,
        ),
        upsResolver=upsResolver,
        uptimeReader=uptimeReader,
        coldStartWindowSeconds=coldStartWindowSeconds,
        loadClass=loadClass,
    )
