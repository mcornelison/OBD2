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
from collections.abc import Callable

from src.common.time.helper import utcIsoNow
from src.pi.power.power_watch.outcome import writeAtomicJson
from src.pi.sync.backlog import (
    BACKLOG_DELIVERED,
    BACKLOG_OUTSTANDING,
    BACKLOG_UNKNOWN,
    SyncBacklog,
    countOutstandingRows,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CUSTODY_RECORD_FILENAME",
    "CUSTODY_RECORD_SCHEMA_VERSION",
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

CUSTODY_RECORD_SCHEMA_VERSION: int = 1

# Sits beside powerwatch_outcome.json in the existing data/ dir. A SEPARATE
# file, deliberately: the outcome record is written with os.replace to a fixed
# path, so sharing it would mean a custody record silently overwriting a sync
# fault record (or the reverse) -- two facts, one slot, last writer wins.
CUSTODY_RECORD_FILENAME = "powerwatch_sync_custody.json"


def buildCustodyRecord(backlog: SyncBacklog, *, nowIso: str) -> dict:
    """Compose the durable custody record for one poweroff.

    Counts are kept as NUMBERS rather than folded into a prose detail string,
    so a later consumer can answer "how many rows were stranded across the last
    ten shutdowns?" without parsing English.

    Args:
        backlog: The backlog measured at poweroff.
        nowIso: ISO-8601 UTC stamp for the record.

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
        "ts": nowIso,
    }


def emitSyncCustody(
    *,
    backlog: SyncBacklog,
    recordPath: str,
    nowIsoFn: Callable[[], str] | None = None,
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

    nowIso = nowIsoFn() if nowIsoFn is not None else utcIsoNow()
    writeAtomicJson(
        recordPath, buildCustodyRecord(backlog, nowIso=nowIso), what="custody"
    )
    return line


def makeSyncCustodyHook(
    *,
    recordPath: str,
    backlogReader: Callable[[], SyncBacklog] | None = None,
    dbPath: str = "",
    busyTimeoutSec: float | None = None,
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

    Returns:
        A zero-arg callable suitable for ``ShutdownSequencer(prePowerOffFn=)``.
        It never raises.
    """
    if backlogReader is None:
        kwargs = {} if busyTimeoutSec is None else {"busyTimeoutSec": busyTimeoutSec}
        def backlogReader() -> SyncBacklog:  # noqa: E306 -- local default reader
            return countOutstandingRows(dbPath, **kwargs)  # type: ignore[arg-type]

    def _emit() -> None:
        try:
            backlog = backlogReader()
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
        try:
            emitSyncCustody(backlog=backlog, recordPath=recordPath)
        except Exception as exc:  # noqa: BLE001 -- belt+braces on the poweroff path
            logger.error("powerwatch: sync-custody emit failed (%s)", exc)

    return _emit


# Re-exported so consumers can branch on the verdicts without reaching past
# this module into the reader.
_VERDICTS = (BACKLOG_DELIVERED, BACKLOG_OUTSTANDING, BACKLOG_UNKNOWN)
