################################################################################
# File Name: snapshot_registry.py
# Purpose/Description: Single-source, cross-tier registry for the natural-key
#                      "snapshot sync" path -- the reusable Pi->server mechanism
#                      for append-only TEXT-PK (insert-once) tables that do NOT
#                      fit the integer-delta cursor. Defines each registered
#                      table's naturalKeyCols + cursorCol ONCE here in src/common/
#                      so the Pi snapshot reader and the server natural-key upsert
#                      derive from the same contract and cannot drift (A-4 gate).
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-416) | Initial -- general SNAPSHOT_SYNC registry + spec.
#                               Built to the Atlas ruling
#                               offices/architect/reports/2026-07-01-us416-startup-
#                               log-snapshot-sync-ruling.md (recorded_at time-cursor,
#                               natural-key UNIQUE(source_device, *naturalKeyCols)
#                               upsert, A-4 define-once). The registry ships EMPTY;
#                               startup_log is the first registrant (US-417) and the
#                               F-115 EDR event-vault reuses this same path.
# ================================================================================
################################################################################
"""Cross-tier natural-key snapshot-sync registry (US-416, F-101 / F-115-reusable).

Some Pi tables are **append-only + immutable** but keyed by a natural TEXT
primary key (e.g. ``startup_log.boot_id``), not an ``INTEGER PRIMARY KEY``.  The
established delta path (:mod:`src.pi.data.sync_log`) cannot sync them: a TEXT PK
has no monotonic integer cursor, and the implicit ``rowid`` is not stable
(``VACUUM`` renumbers it).  This module defines the *general* mechanism those
tables use instead -- table-parameterized, so a new table registers here rather
than copy-pasting a sync branch.

Per the Atlas ruling (2026-07-01):

* **Cursor (Q1).** The Pi pushes rows where ``cursorCol > last_snapshot_cursor``
  (an explicit insertion-timestamp column such as ``recorded_at``), NOT a
  full-snapshot re-push and NOT ``rowid``.  Because the server upsert is
  idempotent on the natural key, cursor precision is *not* safety-critical -- an
  over-reading cursor just harmlessly re-pushes; the cursor only **bounds
  volume**, the natural key guarantees correctness.
* **Resolver (Q2).** The server upserts on ``(source_device, *naturalKeyCols)``
  against a ``UNIQUE(source_device, *naturalKeyCols)`` constraint.  This is a
  NEW pattern -- natural-key *dedup* -- distinct from the generic
  ``id -> source_id`` registry path AND from ``dtc_freeze_frame``'s cross-tier
  FK-resolution special-case (which is orthogonal and left untouched).
* **A-4 (define-once).** ``naturalKeyCols`` for each table lives ONCE, right
  here, imported by both tiers (the Pi reader in :mod:`src.pi.data.sync_log` and
  the server upsert in :mod:`src.server.api.sync`).  One contract, N tables, no
  per-table drift surface -- the same discipline as the EDR schema
  (:mod:`src.common.edr.sensor_schema`).

Naming note -- do NOT conflate with :data:`src.pi.data.sync_log.SNAPSHOT_TABLES`.
That is a *reject-list* (``profiles`` / ``vehicle_info``) the delta path refuses;
:data:`SNAPSHOT_SYNC` here is a *positive push path*.  Same word, opposite role.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "SNAPSHOT_SYNC",
    "SnapshotSyncSpec",
    "getSnapshotSpec",
    "isSnapshotSyncTable",
    "snapshotSyncTables",
]


@dataclass(frozen=True, slots=True)
class SnapshotSyncSpec:
    """Per-table snapshot-sync parameters (A-4 single definition).

    Attributes:
        naturalKeyCols: The column(s) that uniquely identify a row within a
            device.  Combined with ``source_device`` they form the server
            dedup key ``UNIQUE(source_device, *naturalKeyCols)``.  MUST be a
            stable, insert-once natural key (e.g. ``("boot_id",)``); never a
            mutable or renumberable column.
        cursorCol: The append-only insertion-timestamp column the Pi reader
            deltas by (``cursorCol > last_snapshot_cursor``).  ISO-8601 TEXT so
            lexicographic ordering matches time order (e.g. ``"recorded_at"``).
    """

    naturalKeyCols: tuple[str, ...]
    cursorCol: str

    def __post_init__(self) -> None:
        if not self.naturalKeyCols:
            raise ValueError("naturalKeyCols must not be empty")
        if not self.cursorCol:
            raise ValueError("cursorCol must not be empty")


# ==============================================================================
# The registry
# ==============================================================================
#
# EMPTY on purpose in US-416 -- this story ships the *mechanism*.  startup_log is
# the first registrant (US-417, naturalKeyCols=("boot_id",), cursorCol=
# "recorded_at"); the F-115 EDR event-vault registers here rather than getting
# its own sync code.  Adding a table = one row here, referenced by both tiers.
SNAPSHOT_SYNC: dict[str, SnapshotSyncSpec] = {}


def snapshotSyncTables() -> frozenset[str]:
    """Return the set of currently-registered snapshot-sync table names.

    Computed from :data:`SNAPSHOT_SYNC` on each call (NOT a frozen snapshot at
    import time) so a registration -- whether module-level in a consumer or a
    test fixture -- is visible to both tiers without a re-import dance.
    """
    return frozenset(SNAPSHOT_SYNC.keys())


def isSnapshotSyncTable(tableName: str) -> bool:
    """Return True iff ``tableName`` is registered for the snapshot-sync path."""
    return tableName in SNAPSHOT_SYNC


def getSnapshotSpec(tableName: str) -> SnapshotSyncSpec:
    """Return the :class:`SnapshotSyncSpec` for ``tableName``.

    Raises:
        KeyError: If ``tableName`` is not registered in :data:`SNAPSHOT_SYNC`.
            The registry doubles as the whitelist for the table-name identifier
            interpolated into SQL on both tiers -- an unregistered table must
            fail loudly, never fall through.
    """
    try:
        return SNAPSHOT_SYNC[tableName]
    except KeyError as exc:
        raise KeyError(
            f"table {tableName!r} is not registered for snapshot sync; "
            f"expected one of {sorted(SNAPSHOT_SYNC)}",
        ) from exc
