################################################################################
# File Name: push_lock.py
# Purpose/Description: One pusher at a time -- the flock every SyncClient push
#                      holds, and the states/sync-activity record its holder
#                      writes on acquire and release.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-26    | Rex (US-871-a)| Initial: fcntl.flock on
#                               /run/eclipse-obd/sync.lock + states/sync-activity.
# 2026-10-27    | Rex (US-917-a)| isPushLockHeld (non-blocking probe) and
#                               isSyncInProgress for system-status.
# ================================================================================
################################################################################

"""
The Pi->server push lock (US-871-a, F-155).

MEASURED 2026-10-12: four pushers (the eclipse-obd interval tick, its
drive-end flush, the powerwatch drain and ``scripts/sync_now.py``) shared no
lock, and ~19 % of rows (2,000 of 10,620) were sent twice.  Every push now goes
through :meth:`SyncClient.pushAllDeltas` / :meth:`SyncClient.forcePush`, and
both hold :func:`holdPushLock` for the whole call, so every caller inherits it.

The lock is an ``fcntl.flock`` on :data:`DEFAULT_LOCK_PATH`.  The kernel drops
it when the holder's file descriptor closes -- including when the holder is
killed -- so a crashed pusher can never wedge the next one.

Contention policy is the caller's:

* ``wait=False`` (eclipse-obd interval + drive-end): a held lock raises
  :class:`PushLockHeld` at once; the caller skips the tick and pushes nothing.
* ``wait=True`` (powerwatch drain, sync_now): block until the holder releases.

The holder publishes ``states/sync-activity`` atomically:

* on acquire ``{pusher, pid, startedTs, ts}``;
* on release ``{pusher: null, lastDeliveredTs, ts}`` -- ``lastDeliveredTs`` is
  stamped only when the call delivered at least one row, otherwise carried
  over from the previous file (``states/`` is tmpfs, so "this boot"), or null.

Readers (system-status, US-917-a) ask :func:`isSyncInProgress`: a pusher named
in states/sync-activity AND :func:`isPushLockHeld` -- a non-blocking probe of
the same lock -- so a crashed holder (lock freed, record stale) reads false.

Off-Linux (the Windows dev desk has no ``fcntl``) the same contract runs on a
``msvcrt`` byte-range lock, which the OS also drops when the holder dies.
"""

from __future__ import annotations

import errno
import json
import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.common.time.helper import utcIsoNow
from src.pi.splash.boot_state_emitter import writeStateAtomic

try:  # pragma: no cover - platform branch
    import fcntl
except ImportError:  # pragma: no cover - Windows dev desk
    fcntl = None  # type: ignore[assignment]
    import msvcrt

__all__ = [
    "DEFAULT_LOCK_PATH",
    "DEFAULT_STATES_DIR",
    "DRAIN_PUSHER",
    "DRIVE_END_PUSHER",
    "INTERVAL_PUSHER",
    "SYNC_NOW_PUSHER",
    "SYNC_ACTIVITY_FILENAME",
    "PushLockHeld",
    "PushLockSession",
    "holdPushLock",
    "isPushLockHeld",
    "isSyncInProgress",
    "readSyncActivity",
]

logger = logging.getLogger(__name__)

#: The one lock every pusher takes.  /run/eclipse-obd is the runtime dir every
#: Pi unit already shares (eclipse-obd.service RuntimeDirectory); the module
#: creates it in-process when absent (sync_now runs outside any unit).
DEFAULT_LOCK_PATH = "/run/eclipse-obd/sync.lock"

#: The tmpfs states directory the emitters publish into.
DEFAULT_STATES_DIR = "/run/eclipse-obd/states"

#: The holder's activity record, read by system-status (US-917-a / US-917-b).
SYNC_ACTIVITY_FILENAME = "sync-activity"

#: Holder name reported when the activity record does not name one.
UNKNOWN_HOLDER = "unknown"

#: The four pushers' names, as published in sync-activity and in another
#: pusher's ``held by`` / ``waiting for`` line.
INTERVAL_PUSHER = "eclipse-obd-interval"
DRIVE_END_PUSHER = "eclipse-obd-drive-end"
DRAIN_PUSHER = "powerwatch-drain"
SYNC_NOW_PUSHER = "sync-now"


class PushLockHeld(RuntimeError):
    """A non-waiting caller found the push lock held by another pusher.

    Attributes:
        holder: The pusher named in states/sync-activity, or ``"unknown"``.
    """

    def __init__(self, holder: str) -> None:
        super().__init__(f"sync push lock held by {holder}")
        self.holder = holder


@dataclass(slots=True)
class PushLockSession:
    """What the holder reports back before release.

    Attributes:
        rowsDelivered: Rows the server acknowledged during this hold.  A
            positive count stamps ``lastDeliveredTs`` on release.
    """

    rowsDelivered: int = 0


def readSyncActivity(statesDir: str) -> dict[str, Any] | None:
    """Return the parsed states/sync-activity record, or None if unreadable.

    Args:
        statesDir: tmpfs states directory.

    Returns:
        The record dict, or ``None`` when the file is absent or not a JSON
        object.
    """
    path = Path(statesDir) / SYNC_ACTIVITY_FILENAME
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _holderName(statesDir: str) -> str:
    record = readSyncActivity(statesDir) or {}
    return str(record.get("pusher") or UNKNOWN_HOLDER)


def _writeActivity(statesDir: str, payload: dict[str, Any]) -> None:
    # The record is a status signal, not the lock: a failed write must never
    # stop the push it describes.
    try:
        Path(statesDir).mkdir(parents=True, exist_ok=True)
        writeStateAtomic(str(Path(statesDir) / SYNC_ACTIVITY_FILENAME), payload)
    except OSError as exc:
        logger.warning("sync-activity write failed (%s): %s", statesDir, exc)


def _tryLock(fd: int) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _lockBlocking(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return
    while True:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            # LK_LOCK retries for ~10 s and then raises EDEADLOCK; the contract
            # is an unbounded wait, so keep asking until the holder lets go.
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        except OSError as exc:
            if exc.errno == errno.EDEADLOCK:
                continue
            raise
        return


def _unlock(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return
    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def isPushLockHeld(lockPath: str = DEFAULT_LOCK_PATH) -> bool:
    """Return whether another pusher holds the push lock right now.

    A non-blocking probe: it tries the lock without waiting and, when it gets
    it, lets go at once.  The lock file (and its directory) is never created
    -- an absent file is a free lock.  An unreadable lock reads as not held:
    the probe never claims a sync it cannot see.

    Args:
        lockPath: The lock file every pusher takes.

    Returns:
        True when the lock is held by an open descriptor other than the probe's.
    """
    try:
        fd = os.open(lockPath, os.O_RDONLY)
    except OSError:
        return False
    try:
        if not _tryLock(fd):
            return True
        _unlock(fd)
        return False
    except OSError as exc:
        logger.debug("push-lock probe failed (%s): %s", lockPath, exc)
        return False
    finally:
        os.close(fd)


def isSyncInProgress(
    statesDir: str = DEFAULT_STATES_DIR,
    lockPath: str = DEFAULT_LOCK_PATH,
) -> bool:
    """Return whether a push is actually running (US-917-a ``sync.inProgress``).

    True only when states/sync-activity names a pusher AND the lock is held.
    The record alone is not enough: a holder killed mid-push leaves it naming
    the pusher, but the kernel has freed its lock.  With no pusher named the
    lock is not probed at all, so an idle Pi never touches it.

    Args:
        statesDir: tmpfs states directory holding sync-activity.
        lockPath: The lock file every pusher takes.

    Returns:
        True while a named pusher holds the lock, else False.
    """
    record = readSyncActivity(statesDir) or {}
    if not record.get("pusher"):
        return False
    return isPushLockHeld(lockPath)


@contextmanager
def holdPushLock(
    pusher: str,
    *,
    wait: bool,
    lockPath: str = DEFAULT_LOCK_PATH,
    statesDir: str = DEFAULT_STATES_DIR,
    onWait: Callable[[str], None] | None = None,
) -> Iterator[PushLockSession]:
    """Hold the push lock for the body of a ``with`` block.

    Args:
        pusher: This caller's name, published in states/sync-activity and
            reported to anyone who finds the lock held.
        wait: True blocks until the lock is free; False raises
            :class:`PushLockHeld` at once when another pusher holds it.
        lockPath: The lock file (created, with its directory, when absent).
        statesDir: Where states/sync-activity is written.
        onWait: Called once with the holder's name before a waiting caller
            blocks (sync_now prints ``waiting for <pusher>``).

    Yields:
        A :class:`PushLockSession`; set ``rowsDelivered`` before the block ends.

    Raises:
        PushLockHeld: ``wait`` is False and another pusher holds the lock.
    """
    Path(lockPath).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lockPath, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if not _tryLock(fd):
            holder = _holderName(statesDir)
            if not wait:
                raise PushLockHeld(holder)
            logger.info("sync waiting for %s", holder)
            if onWait is not None:
                onWait(holder)
            _lockBlocking(fd)
        try:
            prior = readSyncActivity(statesDir) or {}
            priorDelivered = prior.get("lastDeliveredTs")
            startedTs = utcIsoNow()
            _writeActivity(
                statesDir,
                {"pusher": pusher, "pid": os.getpid(), "startedTs": startedTs, "ts": startedTs},
            )
            session = PushLockSession()
            try:
                yield session
            finally:
                releasedTs = utcIsoNow()
                _writeActivity(
                    statesDir,
                    {
                        "pusher": None,
                        "lastDeliveredTs": (
                            releasedTs if session.rowsDelivered > 0 else priorDelivered
                        ),
                        "ts": releasedTs,
                    },
                )
        finally:
            _unlock(fd)
    finally:
        os.close(fd)
