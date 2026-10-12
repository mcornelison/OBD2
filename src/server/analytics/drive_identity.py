################################################################################
# File Name: drive_identity.py
# Purpose/Description: US-448 / F-104 canonical drive-identity helpers -- the
#                      server-side mint + resolver for the ``drives`` table
#                      (:class:`src.server.db.models.Drive`).  ``upsert_drive``
#                      is the natural-key upsert mint (idempotent, never
#                      renumbers); ``resolve_canonical_drive_id`` +
#                      ``map_overlap_to_canonical`` re-point the
#                      attribution-anomaly tripwire OUTPUT to the canonical
#                      ``drives.drive_id`` identity while detection stays on the
#                      RAW ``realtime_data.drive_id`` (the Pi-dual-mint signal).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-448) | Initial -- F-104 spine: canonical drives mint +
#               |              | tripwire-output canonical resolver.
# ================================================================================
################################################################################

"""US-448 / F-104 canonical drive-identity mint + tripwire-output resolver.

The canonical ``drives`` table (:class:`src.server.db.models.Drive`) is the
single drive-identity SSOT.  This module owns two concerns:

1. **Minting** -- :func:`upsert_drive` is an upsert-by-natural-key on
   ``(source_device, source_drive_id)``.  Minting a drive that has already
   been seen re-uses its existing ``drive_id`` (idempotent; it NEVER
   renumbers), which is what keeps the US-449 harness idempotent and stops
   FKs orphaning on a recompute.  A straight autoincrement insert is
   forbidden precisely because it would renumber on replay.

2. **Tripwire output re-point** -- :func:`resolve_canonical_drive_id` and
   :func:`map_overlap_to_canonical` map a RAW Pi ``realtime_data.drive_id``
   to its canonical ``drives.drive_id``.  This is deliberately a mapping of
   the OUTPUT only: the ``detect_overlapping_drives`` backstop
   (:mod:`src.server.analytics.overlap`) MUST keep DETECTING overlap on the
   raw ``realtime_data.drive_id`` -- that raw id is the Pi-dual-mint signal
   the tripwire exists to catch.  Re-grouping detection by the (already
   deduped) server ``drive_id`` would blind the backstop, so we never do it.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.server.db.models import (
    DATA_SOURCE_DEFAULT,
    DRIVES_DATA_QUALITY_FULL,
    Drive,
)

__all__ = [
    'upsert_drive',
    'resolve_canonical_drive_id',
    'map_overlap_to_canonical',
]


def upsert_drive(
    session: Session,
    *,
    source_device: str,
    source_drive_id: int,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    data_source: str = DATA_SOURCE_DEFAULT,
    data_quality: str = DRIVES_DATA_QUALITY_FULL,
) -> int:
    """Mint (or re-use) the canonical ``drive_id`` for a Pi-advisory drive.

    Upsert-by-natural-key on ``(source_device, source_drive_id)``: if a
    ``drives`` row already exists for the pair, its mutable columns are
    refreshed and the EXISTING ``drive_id`` is returned unchanged (the mint
    never renumbers an already-seen drive -- this is what makes the US-449
    harness idempotent and stops FKs orphaning on recompute).  Otherwise a
    new row is inserted and its server-minted ``drive_id`` returned.

    The natural key must be fully specified: ``source_device`` must be a
    non-empty string and ``source_drive_id`` a real integer.  Unmappable
    legacy drives (NULL ``source_drive_id`` -- pre-connection_log history,
    foreign-vehicle rows) are NOT minted here; US-451 inserts them as one
    honest ``drives`` row per distinct legacy key via its own path.

    Args:
        session: Open sync SQLAlchemy session bound to the server DB.
        source_device: The Pi host id (advisory), e.g. ``"chi-eclipse-01"``.
        source_drive_id: The Pi drive_counter id (advisory).
        start_time: Drive start (optional; refreshed on re-mint if given).
        end_time: Drive end (optional; NULL for an open drive).
        data_source: Origin tag (default ``'real'``).
        data_quality: Drive-level quality flag (default ``'full'``).

    Returns:
        The canonical server-minted ``drives.drive_id`` for the pair.

    Raises:
        ValueError: ``source_device`` is empty or ``source_drive_id`` is None.
    """
    if not source_device:
        raise ValueError('upsert_drive requires a non-empty source_device')
    if source_drive_id is None:  # type: ignore[redundant-expr]
        raise ValueError(
            'upsert_drive requires a non-NULL source_drive_id; unmappable '
            'legacy drives are minted by US-451, not here',
        )

    existing = session.execute(
        select(Drive)
        .where(Drive.source_device == source_device)
        .where(Drive.source_drive_id == source_drive_id)
    ).scalars().first()

    if existing is not None:
        # Refresh mutable columns but NEVER touch drive_id -- re-mint re-uses
        # the identity (idempotent, no renumber).
        existing.start_time = start_time
        existing.end_time = end_time
        existing.data_source = data_source
        existing.data_quality = data_quality
        session.flush()
        return existing.drive_id

    drive = Drive(
        source_device=source_device,
        source_drive_id=source_drive_id,
        start_time=start_time,
        end_time=end_time,
        data_source=data_source,
        data_quality=data_quality,
    )
    session.add(drive)
    session.flush()  # populate the autoincrement PK
    return drive.drive_id


def resolve_canonical_drive_id(
    session: Session,
    source_device: str | None,
    source_drive_id: int | None,
) -> int | None:
    """Map a RAW Pi ``(device, drive_id)`` to its canonical ``drive_id``.

    Returns the canonical ``drives.drive_id`` for the advisory pair, or
    ``None`` when no canonical row exists yet (e.g. the harness has not
    minted it) -- ``None`` is surfaced honestly, never silently coerced to a
    sentinel, so callers can distinguish "not yet minted" from a real id.

    Args:
        session: Open sync SQLAlchemy session bound to the server DB.
        source_device: The Pi host id (advisory) as stamped on the raw row.
        source_drive_id: The RAW ``realtime_data.drive_id`` (advisory Pi id).

    Returns:
        The canonical ``drives.drive_id``, or ``None`` if unmapped.
    """
    if source_device is None or source_drive_id is None:
        return None
    return session.execute(
        select(Drive.drive_id)
        .where(Drive.source_device == source_device)
        .where(Drive.source_drive_id == source_drive_id)
    ).scalars().first()


def map_overlap_to_canonical(
    session: Session,
    source_device: str | None,
    raw_drive_ids: Iterable[int],
) -> dict[int, int | None]:
    """Re-point an attribution-anomaly OUTPUT to the canonical identity.

    ``detect_overlapping_drives`` detects overlap on the RAW
    ``realtime_data.drive_id`` (unchanged -- that is the Pi-dual-mint signal).
    This helper maps each detected RAW id to its canonical
    ``drives.drive_id`` so the anomaly is *flagged against* the canonical
    identity without blinding the raw detection.

    Every raw id is preserved as a key (nothing is silently dropped); the
    value is the canonical id, or ``None`` when that raw drive has no
    canonical row yet.

    Args:
        session: Open sync SQLAlchemy session bound to the server DB.
        source_device: The Pi host id the raw drives were captured on.
        raw_drive_ids: The RAW ``realtime_data.drive_id`` values from
            ``detect_overlapping_drives``.

    Returns:
        ``{raw_drive_id: canonical_drive_id_or_None}`` for every input id.
    """
    return {
        int(raw_id): resolve_canonical_drive_id(session, source_device, raw_id)
        for raw_id in raw_drive_ids
    }
