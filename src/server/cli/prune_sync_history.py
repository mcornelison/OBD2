################################################################################
# File Name: prune_sync_history.py
# Purpose/Description: US-418 (F-078) -- recurring 90-day retention for the
#                      server's sync_history table, run inside the nightly
#                      analytics batch (CIO 2026-10-08).
# Author: Atlas (Architect)
# Creation Date: 2026-10-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-08    | Atlas (US-418)| Initial.
# ================================================================================
################################################################################

"""Prune ``sync_history`` rows older than the retention horizon (US-418).

Usage::

    python -m src.server.cli.prune_sync_history

Migration v0007 pruned the table ONCE and left "future ongoing pruning" to a
job nobody built; 88,810 rows sat past the horizon on 2026-10-07. This is that
job. It runs as the first step of ``server-analytics-batch.service``.

Three decisions, each load-bearing:

* **One source for the horizon.** The days come from v0007's own constant and
  its ``SYNC_HISTORY_RETENTION_DAYS`` override -- never a second literal.
* **A UTC cutoff computed here, not ``NOW() - INTERVAL``.** ``started_at`` is
  written as naive UTC (TD-027), while MariaDB ``NOW()`` on chi-srv-01 is CDT,
  so v0007's SQL drew its line five hours off. A bound parameter is also
  portable, which is what makes the rule testable.
* **Exactly one line per run, deleted or not.** The batch exits 0 on failure
  (US-840) and the unit runs this step with a leading ``-``, so this line is
  the ONLY evidence the prune ran. "Deleted nothing" must never read like
  "never ran" (ARCH-060).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from src.server.cli._ecu_lineage_support import resolveSyncDatabaseUrl
from src.server.db.models import SyncHistory
from src.server.migrations.versions.v0007_sync_history_retention import (
    _resolveRetentionDays,
)

EXIT_OK = 0
EXIT_FAILED = 1


@dataclass(frozen=True)
class PruneResult:
    """What one prune run did."""

    retentionDays: int
    cutoff: datetime
    deleted: int
    remainingPastHorizon: int

    def logLine(self) -> str:
        """The single journal line the exit test reads."""
        return (
            f"sync_history retention: horizon={self.retentionDays}d "
            f"cutoff={self.cutoff.isoformat()}Z deleted={self.deleted} "
            f"past_horizon_after={self.remainingPastHorizon}"
        )


def resolveRetentionDays() -> int:
    """The horizon in days: v0007's constant, or its env override."""
    return _resolveRetentionDays()


def pruneSyncHistory(
    session: Session, *, now: datetime, retentionDays: int
) -> PruneResult:
    """Delete rows with ``started_at`` strictly before ``now - retentionDays``.

    Args:
        session: An open session on the server database.
        now: The reference instant, naive UTC (the column's clock).
        retentionDays: The horizon in days.

    Returns:
        The cutoff, the rows deleted and the rows still past the horizon after
        the delete (0 unless the delete silently missed rows).
    """
    cutoff = now - timedelta(days=retentionDays)
    deleted = session.execute(
        delete(SyncHistory).where(SyncHistory.started_at < cutoff)
    ).rowcount or 0
    session.commit()
    remaining = session.scalar(
        select(func.count()).select_from(SyncHistory).where(SyncHistory.started_at < cutoff)
    ) or 0
    return PruneResult(
        retentionDays=retentionDays, cutoff=cutoff,
        deleted=int(deleted), remainingPastHorizon=int(remaining),
    )


def _buildArgParser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="python -m src.server.cli.prune_sync_history",
        description="Delete sync_history rows older than the retention horizon.",
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m src.server.cli.prune_sync_history``."""
    _buildArgParser().parse_args(argv)
    try:
        retentionDays = resolveRetentionDays()
        engine = create_engine(resolveSyncDatabaseUrl(), future=True)
        try:
            with Session(engine) as session:
                result = pruneSyncHistory(
                    session,
                    now=datetime.now(UTC).replace(tzinfo=None),
                    retentionDays=retentionDays,
                )
        finally:
            engine.dispose()
    except Exception as exc:  # noqa: BLE001 -- the line IS the failure record
        print(f"sync_history retention: FAILED ({type(exc).__name__}: {exc})", file=sys.stderr)
        return EXIT_FAILED

    print(result.logLine())
    if result.remainingPastHorizon > 0:
        print(
            f"sync_history retention: FAILED -- {result.remainingPastHorizon} row(s) "
            f"still past the horizon after the delete",
            file=sys.stderr,
        )
        return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
