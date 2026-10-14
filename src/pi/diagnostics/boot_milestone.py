################################################################################
# File Name: boot_milestone.py
# Purpose/Description: US-860-a (F-157) -- the forward boot record.  Writes, once
#                      per boot and first-write-wins, the event time of each rung
#                      of the boot ladder (kernel start -> OBD connected -> the
#                      first sample of each feed -> drive start) into the Pi
#                      boot_milestone table.  startup_log describes the PREVIOUS
#                      boot's shutdown; this is the instrument the V0.30 boot
#                      baseline is measured with.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-13    | Rex (US-860-a)| Initial.
################################################################################
"""Boot milestone ladder writer (US-860-a).

Every writer lives in ONE process, eclipse-obd (Atlas 2026-10-13): the
orchestrator start arms ``kernel_start``, ``ObdConnection``'s connect_success
path writes ``obd_connected``, ``DriveDetector._startDrive`` writes
``drive_start``, and the capture-health emit writes the four
``first_sample_*`` rungs from the ``firstSampleTs`` its feeds block publishes.
SQLite's INSERT OR IGNORE on the (boot_id, milestone) key is the whole of the
first-write-wins rule, so no lock is needed.

EVENT TIME IS THE RECORD. A rung's ``uptime_s`` is its event's ``ts_utc`` minus
``kernel_start``'s ``ts_utc`` -- never ``/proc/uptime`` at write time, which
would charge the rung for however late its writer ran. Both are canonical
second-resolution strings, so every row can be re-derived from the table alone.

Every writer is best-effort: a failure logs and returns False, and never
reaches the caller's own path (a connect, a drive start, a card emit).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from src.common.time.helper import CANONICAL_ISO_FORMAT, toCanonicalIso
from src.pi.diagnostics.boot_progress import readBootId
from src.pi.diagnostics.boot_reason import BOOT_ID_PATH
from src.pi.power.soc_calibration import readSystemUptimeSeconds

logger = logging.getLogger(__name__)

__all__ = [
    'DRIVE_START',
    'FIRST_SAMPLE_IMU',
    'FIRST_SAMPLE_LIGHT',
    'FIRST_SAMPLE_OBD',
    'FIRST_SAMPLE_UPS',
    'KERNEL_START',
    'MILESTONES',
    'OBD_CONNECTED',
    'recordKernelStart',
    'recordMilestone',
]

KERNEL_START = 'kernel_start'
OBD_CONNECTED = 'obd_connected'
FIRST_SAMPLE_OBD = 'first_sample_obd'
FIRST_SAMPLE_IMU = 'first_sample_imu'
FIRST_SAMPLE_LIGHT = 'first_sample_light'
FIRST_SAMPLE_UPS = 'first_sample_ups'
DRIVE_START = 'drive_start'

#: The rung vocabulary, in ladder order. Enforced here rather than by a CHECK
#: so a later rung reaches a populated table without a rebuild.
MILESTONES: tuple[str, ...] = (
    KERNEL_START,
    OBD_CONNECTED,
    FIRST_SAMPLE_OBD,
    FIRST_SAMPLE_IMU,
    FIRST_SAMPLE_LIGHT,
    FIRST_SAMPLE_UPS,
    DRIVE_START,
)

#: What readBootId returns when it cannot read the boot id.
UNKNOWN_BOOT_ID = 'unknown'

_INSERT_SQL = (
    "INSERT OR IGNORE INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) "
    "VALUES (?, ?, ?, ?)"
)

# One warning per process for an unreadable boot id. The capture-health emit
# retries an unwritten rung every tick, and the reason does not change.
_unknownBootLogged = False


def _utcNow() -> datetime:
    """Wall clock now, UTC. A seam so the lazy kernel_start arm is testable."""
    return datetime.now(UTC)


def _bootIdSurfacePresent() -> bool:
    """Whether the kernel boot-id surface exists on this host (a test seam)."""
    return os.path.exists(BOOT_ID_PATH)


def _resolveBootId(bootId: str | None) -> str | None:
    """The boot id to key on, or None (logged) when it cannot be known.

    Under PK (boot_id, milestone) an 'unknown' id would merge every boot that
    failed to read it into one ladder, so such a boot writes nothing.

    With no boot-id surface at all (off-Linux: a desk simulator run) readBootId
    could only return 'unknown', and would log an ERROR saying so on every
    emit tick; that case is answered here without the call.
    """
    global _unknownBootLogged
    if bootId is not None:
        resolved = bootId
    elif _bootIdSurfacePresent():
        resolved = readBootId()
    else:
        resolved = UNKNOWN_BOOT_ID
    if resolved and resolved != UNKNOWN_BOOT_ID:
        return resolved
    if not _unknownBootLogged:
        _unknownBootLogged = True
        logger.warning(
            "boot_milestone: boot id is unknown -- writing no milestones this "
            "boot (an 'unknown' boot_id would merge boots under one ladder)"
        )
    else:
        logger.debug("boot_milestone: boot id still unknown; nothing written")
    return None


def _toUtc(eventTs: datetime | str) -> datetime | None:
    """An event time as an aware UTC datetime, or None when unparseable.

    A naive datetime is the local wall time ``datetime.now()`` produced (the
    DriveDetector's clock); a string is a canonical or ISO-8601 time.
    """
    if isinstance(eventTs, datetime):
        return eventTs.astimezone(UTC)
    if isinstance(eventTs, str):
        try:
            return datetime.strptime(eventTs, CANONICAL_ISO_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(eventTs)
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _armKernelStart(
    conn: Any,
    bootId: str,
    now: datetime,
    uptimeReader: Any,
) -> bool:
    """INSERT OR IGNORE kernel_start = now - /proc/uptime. False if unreadable."""
    uptime = uptimeReader()
    if uptime is None:
        logger.warning(
            "boot_milestone: /proc/uptime unreadable -- kernel_start not written"
        )
        return False
    kernelTs = toCanonicalIso(now - timedelta(seconds=float(uptime)))
    conn.execute(_INSERT_SQL, (bootId, KERNEL_START, kernelTs, 0.0))
    return True


def recordKernelStart(
    database: Any,
    *,
    bootId: str | None = None,
    now: datetime | None = None,
    uptimeReader: Any = None,
) -> bool:
    """Write this boot's kernel_start rung: the wall time minus /proc/uptime.

    Args:
        database: ObdDatabase (anything with ``connect()`` as a context manager).
        bootId: The boot to key on; defaults to ``readBootId()``.
        now: Wall time to subtract the uptime from; defaults to now (UTC).
        uptimeReader: Seconds-since-kernel-start reader; defaults to
            ``readSystemUptimeSeconds``.

    Returns:
        True when the boot's kernel_start row exists after the call (written
        now or already present); False when nothing could be written.
    """
    if database is None:
        return False
    resolved = _resolveBootId(bootId)
    if resolved is None:
        return False
    try:
        with database.connect() as conn:
            return _armKernelStart(
                conn,
                resolved,
                now if now is not None else _utcNow(),
                uptimeReader if uptimeReader is not None else readSystemUptimeSeconds,
            )
    except Exception as e:  # noqa: BLE001 -- a boot record never fails boot
        logger.warning("boot_milestone: kernel_start write failed: %s", e)
        return False


def recordMilestone(
    database: Any,
    milestone: str,
    eventTs: datetime | str,
    *,
    bootId: str | None = None,
) -> bool:
    """Write one rung at its EVENT time; a rung already written is left alone.

    When this boot has no kernel_start row yet (a rung beat the orchestrator's
    arm), kernel_start is armed first so the rung has its base.

    Args:
        database: ObdDatabase (anything with ``connect()`` as a context manager).
        milestone: One of :data:`MILESTONES` other than ``kernel_start``.
        eventTs: When the event happened -- an aware datetime, a naive local
            datetime, or an ISO-8601 string.
        bootId: The boot to key on; defaults to ``readBootId()``.

    Returns:
        True when the rung's row exists after the call; False when nothing
        could be written (no database, unknown boot, bad time, no base, error).

    Raises:
        ValueError: ``milestone`` is ``kernel_start`` or not in the vocabulary.
    """
    if milestone == KERNEL_START or milestone not in MILESTONES:
        raise ValueError(f"not a writable boot milestone: {milestone!r}")
    if database is None:
        return False
    resolved = _resolveBootId(bootId)
    if resolved is None:
        return False
    eventUtc = _toUtc(eventTs)
    if eventUtc is None:
        logger.warning(
            "boot_milestone: %s has an unreadable event time %r -- not written",
            milestone, eventTs,
        )
        return False
    eventIso = toCanonicalIso(eventUtc)

    try:
        with database.connect() as conn:
            kernelTs = _readKernelTs(conn, resolved)
            if kernelTs is None:
                if not _armKernelStart(conn, resolved, _utcNow(), readSystemUptimeSeconds):
                    logger.warning(
                        "boot_milestone: %s not written -- no kernel_start to "
                        "measure it from", milestone,
                    )
                    return False
                kernelTs = _readKernelTs(conn, resolved)
            kernelUtc = _toUtc(kernelTs) if kernelTs is not None else None
            if kernelUtc is None:
                logger.warning(
                    "boot_milestone: kernel_start ts %r unreadable -- %s not written",
                    kernelTs, milestone,
                )
                return False
            eventAt = datetime.strptime(eventIso, CANONICAL_ISO_FORMAT).replace(tzinfo=UTC)
            uptimeS = (eventAt - kernelUtc).total_seconds()
            conn.execute(_INSERT_SQL, (resolved, milestone, eventIso, uptimeS))
            return True
    except Exception as e:  # noqa: BLE001 -- a boot record never fails its caller
        logger.warning("boot_milestone: %s write failed: %s", milestone, e)
        return False


def _readKernelTs(conn: Any, bootId: str) -> str | None:
    """This boot's kernel_start ts_utc, or None when it has none."""
    row = conn.execute(
        "SELECT ts_utc FROM boot_milestone WHERE boot_id = ? AND milestone = ?",
        (bootId, KERNEL_START),
    ).fetchone()
    return row[0] if row is not None else None
