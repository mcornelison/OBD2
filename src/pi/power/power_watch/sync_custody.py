################################################################################
# File Name: sync_custody.py
# Purpose/Description: US-621 -- the pre-poweroff SYNC CUSTODY record. A clean
#                      shutdown guarantees local DURABILITY (the SQLite write is
#                      fsync-safe); it guarantees nothing about CUSTODY, i.e.
#                      whether the captured rows reached the server. This module
#                      makes the difference visible: every poweroff states
#                      DELIVERED / OUTSTANDING / UNKNOWN, on a greppable prefix,
#                      above the lastResort WARNING floor, plus a durable JSON
#                      record. It never raises and never delays a poweroff.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex (US-621) | Initial -- shutdown sync-custody record. Wired
#                                on the PRE-POWEROFF path (not as a pipeline
#                                ShutdownTask) for the same reason Atlas ruled
#                                the US-526 drain close Option C: the VCELL
#                                floor fast-path SKIPS the pipeline, and that is
#                                precisely the run-to-cutoff shutdown carrying
#                                the most undelivered data.
# 2026-09-17    | Rex (US-789) | The drain-close row THIS shutdown just wrote is
#                                excluded from the verdict by its drain_event_id
#                                (OwnDrainCloseSlot) and reported beside it in
#                                ownDrainCloseExcluded. One PK, never the table.
# 2026-09-25    | Rex (US-790) | OwnTrajectoryRows: the drain VCELL series' ids,
#                                an append-only own-rows set excluded from the
#                                verdict and reported beside it (count, min,
#                                max) under OWN DRAIN TRAJECTORY. Record schema
#                                1 -> 2.
# ================================================================================
################################################################################
"""The pre-poweroff sync-custody record (US-621).

Observed 2026-08-28: the CIO drove off-WiFi, returned, and the Pi ran a full
graceful shutdown -- systemd-poweroff, filesystems synced, journal closed.
Every signal said the system shut down correctly, and he reasonably read that
as "the data is away". It was not: ~35 minutes of capture, on the order of
15,000 rows, never left the Pi.

The sequencer was not wrong about what it was built for. The defect is that
"shutdown complete" was read as "data delivered" and NOTHING distinguished
them. This module is that distinction.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from src.common.time.helper import utcIsoNow
from src.pi.data.sync_log import PK_COLUMN
from src.pi.power.power_watch.outcome import writeAtomicJson
from src.pi.power.types import DRAIN_VCELL_TRAJECTORY_TABLE
from src.pi.sync.backlog import (
    BACKLOG_DELIVERED,
    BACKLOG_OUTSTANDING,
    BACKLOG_UNKNOWN,
    RowExclusion,
    SyncBacklog,
    countOutstandingRows,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CUSTODY_RECORD_FILENAME",
    "CUSTODY_RECORD_SCHEMA_VERSION",
    "EDR_BACKLOG_PREFIX",
    "OWN_DRAIN_CLOSE_PREFIX",
    "OWN_DRAIN_CLOSE_REASON",
    "OWN_DRAIN_CLOSE_TABLE",
    "OWN_TRAJECTORY_PREFIX",
    "OWN_TRAJECTORY_REASON",
    "OWN_TRAJECTORY_TABLE",
    "OwnDrainCloseSlot",
    "OwnTrajectoryRows",
    "SYNC_CUSTODY_PREFIX",
    "buildCustodyRecord",
    "emitSyncCustody",
    "makeSyncCustodyHook",
]

# ONE greppable prefix carried by every disposition, so a single query answers
# "did my data get away?" for any shutdown:
#   journalctl -u eclipse-powerwatch.service --grep='SYNC CUSTODY'
# Modelled directly on ARM_DECISION_PREFIX (US-566), which exists because a
# safety fact split across branches at different severities was unfindable.
SYNC_CUSTODY_PREFIX = "powerwatch: SYNC CUSTODY ="

# US-766: the EDR archive gets its OWN prefix, deliberately NOT
# SYNC_CUSTODY_PREFIX. That prefix exists so ONE grep answers "did my data get
# away?" for a shutdown; emitting a second line under it would hand a log
# scraper two answers to one question and make the first match ambiguous.
# Distinct prefix, distinct question, same shutdown.
EDR_BACKLOG_PREFIX = "powerwatch: EDR BACKLOG ="

# US-789: the row the shutdown's OWN drain close writes, reported beside the
# verdict under its own prefix for the same reason EDR has one -- a second line
# under SYNC_CUSTODY_PREFIX would give one question two answers.
OWN_DRAIN_CLOSE_PREFIX = "powerwatch: OWN DRAIN CLOSE ="

# The drain close writes battery_health_log (keyed by drain_event_id). Named
# once here so the exclusion, the record and the tests cannot drift apart.
OWN_DRAIN_CLOSE_TABLE = "battery_health_log"
OWN_DRAIN_CLOSE_REASON = "written by this shutdown's own drain close"

# US-790: the second own-row class -- the drain's VCELL series, one row per
# poll. Its OWN prefix, per the one-prefix-per-question rule above: a line
# under OWN DRAIN CLOSE would answer a different question.
OWN_TRAJECTORY_PREFIX = "powerwatch: OWN DRAIN TRAJECTORY ="
OWN_TRAJECTORY_TABLE = DRAIN_VCELL_TRAJECTORY_TABLE
OWN_TRAJECTORY_REASON = "written by this shutdown's own drain VCELL series"

# 2 (US-790): ownTrajectoryExcluded joined the record. A consumer parsing v1
# must not silently accept a record carrying a field it does not know.
CUSTODY_RECORD_SCHEMA_VERSION: int = 2

# Sits beside powerwatch_outcome.json in the existing data/ dir. A SEPARATE
# file, deliberately: the outcome record is written with os.replace to a fixed
# path, so sharing it would mean a custody record silently overwriting a sync
# fault record (or the reverse) -- two facts, one slot, last writer wins.
CUSTODY_RECORD_FILENAME = "powerwatch_sync_custody.json"


class OwnDrainCloseSlot:
    """Single-slot handoff: the drain close WRITES it, custody READS it (US-789).

    ``composePrePowerOffHooks`` runs each hook in isolation and discards return
    values -- deliberately, so a failing US-526 close cannot silently delete the
    US-621 custody record. This slot is the only channel between the two, and
    it is shaped so custody never DEPENDS on the close: an empty slot simply
    means "count normally".

    The close clears the slot before it tries, and records an id only when it
    actually closed a row. A close that failed, found nothing, or raised leaves
    the slot empty, so custody can never exclude a row that was never written.
    """

    __slots__ = ("_drainEventId",)

    def __init__(self) -> None:
        self._drainEventId: int | None = None

    def clear(self) -> None:
        """Forget any previous close. Called by the close before it runs."""
        self._drainEventId = None

    def record(self, drainEventId: int) -> None:
        """Remember the drain_event_id this shutdown's close just wrote."""
        self._drainEventId = int(drainEventId)

    @property
    def drainEventId(self) -> int | None:
        """The closed row's id, or None when nothing was closed."""
        return self._drainEventId

    def exclusion(self) -> RowExclusion | None:
        """The typed ONE-row exclusion for custody, or None to count normally."""
        if self._drainEventId is None:
            return None
        return RowExclusion(
            table=OWN_DRAIN_CLOSE_TABLE,
            pk=self._drainEventId,
            reason=OWN_DRAIN_CLOSE_REASON,
        )


class OwnTrajectoryRows:
    """The ids this shutdown's drain VCELL series wrote -- an own-rows SET (US-790).

    The drain writes a row every poll, so one slot cannot hold them. Atlas's
    ruling (2026-09-19, decision 2) fixes the semantics: the set is APPEND-ONLY,
    built empty once when the hooks are composed, and a writer adds an id only
    after its own write is known to have landed. No speculative adds, so no
    clear-before-attempt: a failed write adds nothing, and custody can never
    exclude a row that does not exist.

    Read by BOTH the drain's exit check and custody, so the two cannot
    disagree about which rows are this shutdown's own. Thread-safe: the
    sequencer's poll thread adds while the pipeline thread reads.
    """

    __slots__ = ("_ids", "_lock")

    def __init__(self) -> None:
        self._ids: list[int] = []
        self._lock = threading.Lock()

    def add(self, rowId: int) -> None:
        """Remember one id the trajectory writer just committed."""
        with self._lock:
            self._ids.append(int(rowId))

    def exclusions(self) -> tuple[RowExclusion, ...]:
        """One typed exclusion per id, in write order; empty when none landed."""
        with self._lock:
            ids = tuple(self._ids)
        return tuple(
            RowExclusion(table=OWN_TRAJECTORY_TABLE, pk=pk, reason=OWN_TRAJECTORY_REASON)
            for pk in ids
        )


def _ownTrajectoryField(
    exclusions: tuple[RowExclusion, ...], backlog: SyncBacklog,
) -> dict | None:
    """The ``ownTrajectoryExcluded`` record field (US-790).

    At ~1,500 rows a drain, naming every id is useless; the class is reported
    as its count and id range instead -- still falsifiable, still one line.
    ``None`` means NO exclusion was requested (nothing landed, or unwired).
    ``outstandingRows`` is how many of them actually moved the count; the rest
    had already been pushed during the drain.
    """
    if not exclusions:
        return None
    ids = [e.pk for e in exclusions]
    applied = {e.pk for e in backlog.excludedRows if e.table == OWN_TRAJECTORY_TABLE}
    return {
        "table": OWN_TRAJECTORY_TABLE,
        "reason": OWN_TRAJECTORY_REASON,
        "requestedRows": len(ids),
        "minId": min(ids),
        "maxId": max(ids),
        "outstandingRows": len(applied),
    }


def _ownDrainCloseField(
    exclusion: RowExclusion | None, backlog: SyncBacklog,
) -> dict | None:
    """The ``ownDrainCloseExcluded`` record field.

    ``None`` means NO exclusion was requested (the close wrote nothing, failed,
    or is unwired) -- custody counted every row. Otherwise it names the row and
    says whether it was outstanding, i.e. whether excluding it actually moved
    the count. Nothing is hidden: the row is always on the record.
    """
    if exclusion is None:
        return None
    return {
        "table": exclusion.table,
        PK_COLUMN[exclusion.table]: exclusion.pk,
        "reason": exclusion.reason,
        "wasOutstanding": exclusion in backlog.excludedRows,
    }


def buildCustodyRecord(
    backlog: SyncBacklog,
    *,
    nowIso: str,
    edrBacklog: SyncBacklog | None = None,
    ownDrainClose: RowExclusion | None = None,
    ownTrajectory: tuple[RowExclusion, ...] = (),
) -> dict:
    """Compose the durable custody record for one poweroff.

    Counts are kept as NUMBERS rather than folded into a prose detail string,
    so a later consumer can answer "how many rows were stranded across the last
    ten shutdowns?" without parsing English.

    US-766: the EDR archive is reported BESIDE the verdict, never inside it.
    ``backlog`` is expected to have been measured with the EDR tables excluded,
    so every field describing custody -- verdict, outstandingRows, perTable --
    is byte-identical whether the EDR queue holds nothing or fifteen million
    rows. Folding an unbounded archival backlog into the custody verdict would
    make every healthy shutdown report OUTSTANDING forever, and a verdict that
    always fails is a verdict nobody reads.

    Args:
        backlog: The custody backlog measured at poweroff (EDR excluded).
        nowIso: ISO-8601 UTC stamp for the record.
        edrBacklog: The EDR-only backlog, when it was measured. ``None`` means
            NOT MEASURED and is recorded as ``None`` -- never 0, which would
            claim the EDR queue was looked at and found empty.
        ownDrainClose: US-789 -- the exclusion requested for this shutdown's
            own drain-close row, or ``None`` when none was requested.
        ownTrajectory: US-790 -- the exclusions requested for this shutdown's
            own drain VCELL series rows; empty when none were requested.

    Returns:
        A JSON-serialisable record body.
    """
    return {
        "schema": CUSTODY_RECORD_SCHEMA_VERSION,
        "verdict": backlog.verdict,
        "outstandingRows": backlog.total,
        # False means outstandingRows is a LOWER BOUND -- something could not
        # be read, so the real figure may be higher.
        "countIsComplete": backlog.isComplete,
        "perTable": dict(backlog.perTable),
        "unreadableTables": list(backlog.unreadableTables),
        "error": backlog.error,
        # US-766: a typed absence, not a zero. Reported separately so it can
        # never move the verdict above.
        "edrOutstandingRows": None if edrBacklog is None else edrBacklog.total,
        # US-789: the row this shutdown's own close wrote, BESIDE the verdict.
        "ownDrainCloseExcluded": _ownDrainCloseField(ownDrainClose, backlog),
        # US-790: this shutdown's own VCELL series, BESIDE the verdict.
        "ownTrajectoryExcluded": _ownTrajectoryField(ownTrajectory, backlog),
        "ts": nowIso,
    }


def emitSyncCustody(
    *,
    backlog: SyncBacklog,
    recordPath: str,
    nowIsoFn: Callable[[], str] | None = None,
    edrBacklog: SyncBacklog | None = None,
    ownDrainClose: RowExclusion | None = None,
    ownTrajectory: tuple[RowExclusion, ...] = (),
) -> str:
    """State sync custody for this poweroff, on BOTH channels. Never raises.

    Two independent channels carry the same fact: a journal line (immediate,
    greppable, survives a missing filesystem write) and a durable JSON record
    (structured, survives the poweroff and the journal rotating). Losing one
    does not lose the fact.

    Severity is chosen by disposition and is NEVER below WARNING. That is the
    US-566 lesson, measured on chi-eclipse-01 2026-08-21: this service ran with
    no root handler, so ``logging.lastResort`` (level WARNING, stderr) was the
    only sink and the whole INFO tier was discarded. A custody line at INFO
    would be invisible in exactly the degraded conditions that make custody
    worth reporting.

    Args:
        backlog: The backlog measured at poweroff.
        recordPath: Destination path for the durable record.
        nowIsoFn: DI clock (default UTC now).
        edrBacklog: The EDR-only backlog, reported beside the verdict.
        ownDrainClose: US-789 -- this shutdown's own drain-close exclusion,
            reported beside the verdict.
        ownTrajectory: US-790 -- this shutdown's own VCELL series exclusions,
            reported beside the verdict as a count and id range.

    Returns:
        The exact line logged, so a caller can re-state it without recomposing
        it (one formatting site, per the US-566 pattern).
    """
    line = f"{SYNC_CUSTODY_PREFIX} {backlog.describe()}"
    if backlog.verdict == BACKLOG_OUTSTANDING:
        # Stranded capture is a data-custody FAILURE, not an operational note.
        logger.error(
            "%s. These rows are still in the Pi's local SQLite and are NOT "
            "lost -- they sync on the next run home. Shutdown completing is "
            "NOT delivery.",
            line,
        )
    elif backlog.verdict == BACKLOG_UNKNOWN:
        logger.error(
            "%s. Custody could NOT be established -- treat as undelivered "
            "until checked, never as clean.",
            line,
        )
    else:
        # DELIVERED is reported at WARNING, not INFO. It is the branch a reader
        # most needs to trust, and pinning it to a tier a config change can
        # silence would make "empty queue" indistinguishable from "the recorder
        # never ran" -- the precise ambiguity US-621 VC-2 forbids.
        logger.warning("%s.", line)

    # US-766: stated BESIDE the verdict, never inside it. An EDR backlog is
    # expected and is not a custody failure -- those rows are archival and
    # catch up on the next ordinary sync tick, whereas the verdict above is
    # about drive data that the shutdown was responsible for. Reported at
    # WARNING for the US-566 reason: this service has run with no root handler,
    # so INFO would be discarded in exactly the degraded conditions that make
    # the number worth having.
    if edrBacklog is not None:
        logger.warning(
            "%s %s. Archival -- EXPECTED to be outstanding at poweroff and "
            "deliberately excluded from the custody verdict above.",
            EDR_BACKLOG_PREFIX,
            edrBacklog.describe(),
        )

    # US-789: the row the shutdown itself just wrote, stated beside the verdict
    # so the exclusion is never silent. WARNING for the US-566 reason above.
    if ownDrainClose is not None:
        logger.warning(
            "%s %s %s=%d (%s) -- %s; excluded from the custody verdict above.",
            OWN_DRAIN_CLOSE_PREFIX,
            ownDrainClose.table,
            PK_COLUMN[ownDrainClose.table],
            ownDrainClose.pk,
            "outstanding" if ownDrainClose in backlog.excludedRows
            else "not outstanding",
            ownDrainClose.reason,
        )

    # US-790: the drain's own VCELL series, one line for the whole class.
    trajectory = _ownTrajectoryField(ownTrajectory, backlog)
    if trajectory is not None:
        logger.warning(
            "%s %s %d row(s), min id=%d, max id=%d, %d outstanding (%s); "
            "excluded from the custody verdict above -- they sync on the next run home.",
            OWN_TRAJECTORY_PREFIX,
            trajectory["table"],
            trajectory["requestedRows"],
            trajectory["minId"],
            trajectory["maxId"],
            trajectory["outstandingRows"],
            trajectory["reason"],
        )

    nowIso = nowIsoFn() if nowIsoFn is not None else utcIsoNow()
    writeAtomicJson(
        recordPath,
        buildCustodyRecord(
            backlog,
            nowIso=nowIso,
            edrBacklog=edrBacklog,
            ownDrainClose=ownDrainClose,
            ownTrajectory=ownTrajectory,
        ),
        what="custody",
    )
    return line


def makeSyncCustodyHook(
    *,
    recordPath: str,
    backlogReader: Callable[[], SyncBacklog] | None = None,
    dbPath: str = "",
    busyTimeoutSec: float | None = None,
    edrBacklogReader: Callable[[], SyncBacklog] | None = None,
    ownDrainCloseSlot: OwnDrainCloseSlot | None = None,
    ownTrajectoryRows: OwnTrajectoryRows | None = None,
) -> Callable[[], None]:
    """Build the zero-arg pre-poweroff custody hook.

    The backlog is read WHEN THE HOOK FIRES, never captured at build time: the
    hook is constructed once at service start and runs minutes or hours later,
    so a count taken at wiring time would record a number that was never true
    at the moment custody actually transferred.

    Args:
        recordPath: Destination path for the durable custody record.
        backlogReader: Zero-arg backlog reader (tests inject; production
            defaults to reading ``dbPath``).
        dbPath: Pi SQLite path, used when no explicit reader is supplied.
        busyTimeoutSec: SQLite busy timeout for the default reader. Callers
            pass the shutdown path's own bound so a locked database can never
            delay a poweroff.
        edrBacklogReader: Zero-arg EDR-only backlog reader (US-766).
        ownDrainCloseSlot: US-789 -- the slot the drain close writes. When it
            holds an id, ``backlogReader`` is called with
            ``excludeRows=(<that one row>,)``; when it is empty (the close
            failed or wrote nothing) the reader is called with no exclusion
            and custody counts every row.
        ownTrajectoryRows: US-790 -- the set the drain VCELL series writer
            fills. Its ids join ``excludeRows``; an empty set adds nothing.

    Returns:
        A zero-arg callable suitable for ``ShutdownSequencer(prePowerOffFn=)``.
        It never raises.
    """
    if backlogReader is None:
        kwargs = {} if busyTimeoutSec is None else {"busyTimeoutSec": busyTimeoutSec}
        def backlogReader(**extra) -> SyncBacklog:  # noqa: E306 -- local default reader
            return countOutstandingRows(dbPath, **kwargs, **extra)  # type: ignore[arg-type]

    def _emit() -> None:
        # US-789: read the slot WHEN THE HOOK FIRES -- the close runs first in
        # the same composed hook, so this is the id it just wrote (or nothing).
        ownDrainClose: RowExclusion | None = None
        if ownDrainCloseSlot is not None:
            try:
                ownDrainClose = ownDrainCloseSlot.exclusion()
            except Exception as exc:  # noqa: BLE001 -- never block a poweroff
                logger.warning(
                    "powerwatch: own-drain-close slot unreadable (%s) -- "
                    "custody counts every row",
                    exc,
                )
        ownTrajectory: tuple[RowExclusion, ...] = ()
        if ownTrajectoryRows is not None:
            try:
                ownTrajectory = ownTrajectoryRows.exclusions()
            except Exception as exc:  # noqa: BLE001 -- never block a poweroff
                logger.warning(
                    "powerwatch: own-trajectory set unreadable (%s) -- "
                    "custody counts every row",
                    exc,
                )
        excludeRows = ((ownDrainClose,) if ownDrainClose is not None else ()) + ownTrajectory
        try:
            if not excludeRows:
                backlog = backlogReader()
            else:
                backlog = backlogReader(excludeRows=excludeRows)
        except Exception as exc:  # noqa: BLE001 -- never block a poweroff
            # Report UNKNOWN, never DELIVERED. Swallowing a reader fault into a
            # clean-looking record would manufacture the exact false assurance
            # this story removes.
            logger.error(
                "powerwatch: sync-backlog read failed (%s) -- recording "
                "custody as %s",
                exc,
                BACKLOG_UNKNOWN,
            )
            backlog = SyncBacklog(error=f"backlog read failed: {exc}")

        # US-766: the EDR count is a nice-to-have on the poweroff path. A fault
        # reading it must never cost us the custody record, which is the fact
        # that actually matters -- so it degrades to "not measured" (None), not
        # to a zero and not to an exception.
        edrBacklog: SyncBacklog | None = None
        if edrBacklogReader is not None:
            try:
                edrBacklog = edrBacklogReader()
            except Exception as exc:  # noqa: BLE001 -- never block a poweroff
                logger.warning(
                    "powerwatch: EDR-backlog read failed (%s) -- recording it "
                    "as NOT MEASURED; custody is unaffected",
                    exc,
                )

        try:
            emitSyncCustody(
                backlog=backlog,
                recordPath=recordPath,
                edrBacklog=edrBacklog,
                ownDrainClose=ownDrainClose,
                ownTrajectory=ownTrajectory,
            )
        except Exception as exc:  # noqa: BLE001 -- belt+braces on the poweroff path
            logger.error("powerwatch: sync-custody emit failed (%s)", exc)

    return _emit


# Re-exported so consumers can branch on the verdicts without reaching past
# this module into the reader.
_VERDICTS = (BACKLOG_DELIVERED, BACKLOG_OUTSTANDING, BACKLOG_UNKNOWN)
