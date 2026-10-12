################################################################################
# File Name: disk_space_guard.py
# Purpose/Description: US-762 -- notice low disk on the Pi and report what could
#                      be cleared, ranked by size and age. Observes only: it
#                      never deletes, rotates, or gates a writer.
# Author: Ralph (US-762)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-23    | Ralph (US-762) | Initial -- threshold, typed state, ranked
#               |                | candidates, typed absence on read failure.
# ================================================================================
################################################################################
"""Low-disk guard for the Pi.

**Why this exists.**  The EDR retention window was widened 6.4x on a one-off
arithmetic margin that nothing re-checks.  **A number with no watcher is not a
guard** -- it is a calculation someone did once, and the disk it protects has
been filling ever since without anyone being told.

⚠️ **MEASURED 2026-09-21: 117 GB total, 18 GB used, 95 GB free.**  This guard
will report ``HEALTHY`` on the real car for the foreseeable future.  That is
the reason the BREACH path is proven by test rather than by waiting: a path
that has never executed is not known to work, and the first time it runs
should not be the first time it matters.

🔴 **IT NEVER DELETES ANYTHING.**  The CIO asked for options that *might* help
clear space.  That is a REPORT.  Acting on it is a behaviour change with its
own ruling to obtain, and ``tests/pi/diagnostics/test_disk_space_guard.py``
scans this module for deletion calls to keep it that way.

🔴 **IT NEVER STOPS EDR WRITES.**  Black-box recording is always-on by the
CIO's 2026-09-11 ruling.  Silently throttling capture to save disk is the one
optimisation that ruling exists to forbid -- the recorder going quiet to
protect itself is the recorder failing.

🔴 **AN UNREADABLE FILESYSTEM IS NOT HEALTHY.**  It is ``UNKNOWN`` with a
reason, per the honest-availability pattern in ``specs/ssot-design-pattern.md``:
a typed absence, never a numeric sentinel and never a pass.  The absence of a
failure signal is not a success signal -- the same defect class as a
bit-identical sensor reading sailing through a variance check.
"""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    'DEFAULT_SEARCH_ROOTS',
    'GUARD_MODULE_PATH',
    'LOW_DISK_THRESHOLD_BYTES',
    'MAX_REPORTED_CANDIDATES',
    'ClearableCandidate',
    'DiskSpaceState',
    'DiskVerdict',
    'assessDiskSpace',
]

#: This module's own path, so the no-deletion guard can scan it without
#: hardcoding a path that silently stops matching when the file moves.
GUARD_MODULE_PATH: str = __file__

_BYTES_PER_GB: int = 1024 ** 3

#: Atlas's stop-loss figure, 2026-09-14.  DEFINED ONCE, here.  Every consumer
#: reads this name -- a threshold copied to a use site is how two copies of one
#: number begin to disagree, and this number was already set once on a margin
#: nobody re-checked.
LOW_DISK_THRESHOLD_BYTES: int = 20 * _BYTES_PER_GB

#: An unbounded candidate list turns an alert into a directory listing, and an
#: alert nobody reads is the same as no alert.
MAX_REPORTED_CANDIDATES: int = 10

#: Where clearable files are looked for.  Backups first: the concrete
#: precedent is ``scripts/cleanup_orphan_realtime_data.py``, whose own comment
#: records 5 copies / 11 GB accumulating before anyone looked.
DEFAULT_SEARCH_ROOTS: tuple[str, ...] = (
    'data/backups',
    'logs',
)

_SECONDS_PER_DAY: float = 86400.0


class DiskVerdict(Enum):
    """What the guard can honestly say about free space."""

    #: Free space is at or above the threshold.
    HEALTHY = 'healthy'
    #: Free space is below the threshold.
    BREACHED = 'breached'
    #: The filesystem could not be read.  NOT a pass.
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class ClearableCandidate:
    """One file that could be cleared, with what is needed to judge it.

    Attributes:
        path: Absolute path, as a string.
        sizeBytes: What clearing it would recover.
        ageDays: How long since it was last modified.
    """

    path: str
    sizeBytes: int
    ageDays: float


@dataclass(frozen=True)
class DiskSpaceState:
    """The typed state this guard publishes.

    Attributes:
        verdict: healthy / breached / unknown.
        freeBytes: Measured free space, or None when unreadable. NEVER a
            sentinel -- a numeric NA gets rendered as if real and silently
            corrupts anything that aggregates it.
        thresholdBytes: The threshold compared against, carried so a reader
            never has to look it up to interpret the verdict.
        candidates: Clearable files, largest-and-oldest first. Empty unless
            breached.
        reason: Why the verdict is UNKNOWN, when it is.
    """

    verdict: DiskVerdict
    freeBytes: int | None
    thresholdBytes: int
    candidates: tuple[ClearableCandidate, ...] = ()
    reason: str | None = None


def _defaultFreeSpaceReader(path: Path | str) -> int:
    """Free bytes on the filesystem holding ``path``."""
    return shutil.disk_usage(str(path)).free


def assessDiskSpace(
    rootPath: Path | str = '/',
    *,
    thresholdBytes: int = LOW_DISK_THRESHOLD_BYTES,
    freeSpaceReader: Callable[[Path | str], int] | None = None,
    searchRoots: Sequence[Path | str] | None = None,
    maxCandidates: int = MAX_REPORTED_CANDIDATES,
) -> DiskSpaceState:
    """Measure free space, log a breach, and report what could be cleared.

    Observes only.  Nothing here deletes, rotates, or gates a writer.

    Args:
        rootPath: Filesystem to measure.
        thresholdBytes: Breach boundary; free space BELOW this is a breach.
        freeSpaceReader: Injected reader, for testing the breach path without
            filling a disk. Defaults to :func:`shutil.disk_usage`.
        searchRoots: Where to look for clearable files when breached.
        maxCandidates: Cap on the reported list.

    Returns:
        The typed state. An unreadable filesystem yields ``UNKNOWN`` with a
        reason and no free-space number -- never ``HEALTHY``.
    """
    reader = freeSpaceReader or _defaultFreeSpaceReader

    try:
        freeBytes = reader(rootPath)
    except Exception as exc:  # noqa: BLE001 -- any read failure is UNKNOWN
        # A typed absence, not a pass. Reporting HEALTHY here would assert the
        # disk is fine on the evidence that we could not look at it.
        reason = f'{type(exc).__name__}: {exc}'
        logger.error(
            'disk-space guard could not read free space on %s (%s) -- '
            'reporting UNKNOWN, NOT healthy',
            rootPath, reason,
        )
        return DiskSpaceState(
            verdict=DiskVerdict.UNKNOWN,
            freeBytes=None,
            thresholdBytes=thresholdBytes,
            reason=reason,
        )

    if freeBytes >= thresholdBytes:
        # No candidate walk on the healthy path: scanning the tree on every
        # check would be work done for nothing, on the tier that can least
        # afford it.
        return DiskSpaceState(
            verdict=DiskVerdict.HEALTHY,
            freeBytes=freeBytes,
            thresholdBytes=thresholdBytes,
        )

    candidates = _rankClearableCandidates(
        searchRoots if searchRoots is not None else DEFAULT_SEARCH_ROOTS,
        maxCandidates,
    )
    logger.error(
        'LOW DISK: %.1f GB free, below the %.1f GB threshold. '
        '%d clearable candidate(s) reported, largest-and-oldest first. '
        'Nothing has been deleted -- this guard only reports.',
        freeBytes / _BYTES_PER_GB, thresholdBytes / _BYTES_PER_GB,
        len(candidates),
    )
    return DiskSpaceState(
        verdict=DiskVerdict.BREACHED,
        freeBytes=freeBytes,
        thresholdBytes=thresholdBytes,
        candidates=candidates,
    )


def _rankClearableCandidates(
    searchRoots: Sequence[Path | str], maxCandidates: int,
) -> tuple[ClearableCandidate, ...]:
    """Collect clearable files, largest-and-oldest first.

    SIZE AND AGE TOGETHER, not either alone: a huge NEW file may still be in
    use, and a tiny OLD one buys nothing. The rank is the product of bytes and
    days, so a 5.4 GB 53-day-old backup outranks a 40 MB 9-day-old log by a
    wide margin while a brand-new large file scores near zero.

    Args:
        searchRoots: Directories to walk. Missing ones are skipped.
        maxCandidates: Cap on the returned list.

    Returns:
        The ranked candidates, capped.
    """
    now = time.time()
    found: list[tuple[float, ClearableCandidate]] = []

    for root in searchRoots:
        rootPath = Path(root)
        if not rootPath.is_dir():
            continue
        for path in rootPath.rglob('*'):
            try:
                if not path.is_file():
                    continue
                stat = path.stat()
            except OSError:
                # A file that vanished or cannot be stat'd is simply not a
                # candidate. It is not an error: the tree is live.
                continue
            ageDays = max(0.0, (now - stat.st_mtime) / _SECONDS_PER_DAY)
            found.append((
                stat.st_size * ageDays,
                ClearableCandidate(
                    path=str(path), sizeBytes=stat.st_size, ageDays=ageDays,
                ),
            ))

    found.sort(key=lambda entry: entry[0], reverse=True)
    return tuple(candidate for _, candidate in found[:maxCandidates])
