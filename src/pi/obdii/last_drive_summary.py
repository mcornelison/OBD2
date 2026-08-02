################################################################################
# File Name: last_drive_summary.py
# Purpose/Description: US-505 -- the last-drive-summary producer for the
#   idle-home card's LAST DRIVE tile (F-123).  The tile rendered "No recent
#   drive" PERMANENTLY, not "until the next drive": the card reads
#   ``systemStatusData.drive.driveId``, which the emitter reports as None
#   whenever a drive is not ACTIVELY recording, and no producer for the most
#   recent COMPLETED drive existed anywhere.  This module is that producer.
#
#   Source = Pi-LOCAL ``drive_summary`` (US-206), which the DriveDetector still
#   writes at every drive start.  It carries the two facts Iris's idle spec asks
#   for -- the drive id and when the drive began.
#
#   B-104 BOUNDARY (load-bearing).  This producer reads drive IDENTITY and
#   drive-start WALL TIME only.  It computes no distance, no duration, no
#   max/avg anything: derived per-drive analytics are the SERVER's authority
#   since US-351 retired the Pi-side ``drive_statistics`` table, and re-deriving
#   them here would rebuild exactly what that story deleted.
#
#   Honest-instrument.  An absent DB, a missing or unreadable ``drive_summary``,
#   an empty table, or a non-integer drive id all resolve to the UNKNOWN summary
#   -- which renders the SAME honest "No recent drive" the card shows today. The
#   defect being fixed is a MISSING fact; the fix may never manufacture one.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Ralph (Rex)  | Initial -- US-505 last-drive-summary producer.
# ================================================================================
################################################################################

"""Last-drive-summary producer (US-505).

Design notes worth keeping:

* **The age is NOT computed here.** The producer carries the drive-start
  TIMESTAMP and the display formats the age, exactly as the battery card
  already does with ``lastHealthCheckTs``.  A pre-computed "2 h ago" would be
  frozen at emit time and would age visibly wrong on a kiosk that emits every
  few seconds but is read minutes later.

* **The anchor is drive START, not drive end.**  ``drive_summary`` has no
  end-of-drive column -- there is no Pi-local record of when a drive FINISHED.
  Synthesising one (e.g. the newest ``realtime_data`` sample) would be a guess
  dressed as a measurement, and doubly so while capture is down (BL-025).  So
  the fact carried is the one that actually exists.

* **Simulated drives are filtered.**  ``drive_summary.data_source`` tags rows
  ``real`` / ``replay`` / ``physics_sim`` / ``fixture`` / ``foreign``, and
  US-195 established that analytics filter real-vs-sim off it.  Presenting a
  bench ``physics_sim`` run to the operator as "your last drive" would be a
  fabrication in the only terms the panel has.  Consequence to know about: on a
  simulator-only box the tile reads "No recent drive", which is correct but can
  look like a regression -- the skip is logged at debug for exactly that reason.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    'LAST_DRIVE_DATA_SOURCE',
    'LastDriveSummary',
    'computeLastDriveSummary',
    'readLastDriveSummary',
]


# ================================================================================
# Constants
# ================================================================================

#: The only ``drive_summary.data_source`` tag that represents a drive the
#: operator actually took.  See the module docstring for why sim rows are
#: excluded rather than relabelled.
LAST_DRIVE_DATA_SOURCE: str = 'real'

#: Newest real drive first.  ``drive_id`` is monotonic (minted by
#: :mod:`src.pi.obdii.drive_id`), so it -- not the timestamp column, which is
#: nullable -- is the ordering key.
_LAST_DRIVE_SQL: str = (
    "SELECT drive_id, drive_start_timestamp "
    "FROM drive_summary "
    "WHERE data_source = ? "
    "ORDER BY drive_id DESC "
    "LIMIT 1"
)


# ================================================================================
# LastDriveSummary
# ================================================================================


@dataclass(frozen=True)
class LastDriveSummary:
    """The most recent completed drive, or the honest unknown.

    Attributes:
        driveId: Pi-local drive id, or None when no real drive is on record.
        startedAtTs: ISO-8601 UTC drive-start instant, or None when the column
            is NULL/blank.  Independent of ``driveId``: a drive that genuinely
            happened is still reported when its start time is missing, and the
            display degrades to "age unknown" on that half alone.
    """

    driveId: int | None = None
    startedAtTs: str | None = None

    @property
    def isKnown(self) -> bool:
        """Whether a real drive is on record (``driveId`` is the load-bearing
        half -- there is nothing to render without it)."""
        return self.driveId is not None

    def toStatePayload(self) -> dict[str, Any] | None:
        """Render for the ``drive.lastDrive`` block of the system-status file.

        Returns:
            The two real facts, or None when unknown.  None -- not a dict of
            nulls -- because the display's "No recent drive" branch keys on the
            ABSENCE of the block, and a null-filled block would read as a
            drive whose every detail failed to load.
        """
        if not self.isKnown:
            return None
        return {"driveId": self.driveId, "startedAtTs": self.startedAtTs}


#: Shared immutable unknown -- the default answer on every failure path.
_UNKNOWN: LastDriveSummary = LastDriveSummary()


# ================================================================================
# Public API
# ================================================================================


def computeLastDriveSummary(
    *,
    rows: Iterable[Mapping[str, Any]],
) -> LastDriveSummary:
    """Select the most recent real drive from candidate rows (pure).

    Does not rely on the caller's ordering: the highest ``drive_id`` wins even
    if the rows arrive unsorted, so the SQL's ORDER BY and this function are
    independently correct rather than jointly.

    Args:
        rows: Mappings carrying ``drive_id`` and ``drive_start_timestamp``.

    Returns:
        The :class:`LastDriveSummary`; unknown when no row carries a usable
        integer drive id.
    """
    best: LastDriveSummary = _UNKNOWN
    bestId: int | None = None
    for row in rows:
        driveId = _asDriveId(row.get('drive_id'))
        if driveId is None:
            continue
        if bestId is None or driveId > bestId:
            bestId = driveId
            best = LastDriveSummary(
                driveId=driveId,
                startedAtTs=_asTimestamp(row.get('drive_start_timestamp')),
            )
    return best


def readLastDriveSummary(*, database: Any | None) -> LastDriveSummary:
    """Read the most recent real drive from Pi-local ``drive_summary``.

    Best-effort by contract: an absent handle, a missing table (fresh or
    pre-migration DB) or a locked file returns the honest unknown rather than
    raising into the card-emit loop.

    Args:
        database: An object exposing ``connect()`` as a context manager
            yielding a DB-API connection, or None (bench / not yet built in the
            boot order).

    Returns:
        The :class:`LastDriveSummary`; unknown on any read failure.
    """
    if database is None:
        return _UNKNOWN
    try:
        with database.connect() as conn:
            fetched = conn.execute(
                _LAST_DRIVE_SQL, (LAST_DRIVE_DATA_SOURCE,)
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 -- unreadable log -> honest unknown
        logger.debug("last-drive summary read failed (%s) -- unknown", exc)
        return _UNKNOWN

    rows = [
        {'drive_id': row[0], 'drive_start_timestamp': row[1]}
        for row in fetched
    ]
    summary = computeLastDriveSummary(rows=rows)
    if not summary.isKnown:
        # Distinguishable in the log from "no rows at all": on a simulator-only
        # box the tile legitimately reads "No recent drive", and that is the
        # single most likely thing to be mistaken for a regression.
        logger.debug(
            "no real drive in drive_summary (data_source=%r) -- tile shows "
            "the honest absence",
            LAST_DRIVE_DATA_SOURCE,
        )
    return summary


# ================================================================================
# Internal helpers
# ================================================================================


def _asDriveId(value: Any) -> int | None:
    """Coerce a drive id, or None when it could not be one.

    ``bool`` is rejected explicitly: it is an ``int`` subclass in Python, so a
    stray True would otherwise render as "Drive 1".
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _asTimestamp(value: Any) -> str | None:
    """Normalise a drive-start timestamp to a non-blank string, else None.

    Blank normalises to None so the display has ONE absence to branch on -- an
    empty string would slip past a null check and reach the age formatter.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
