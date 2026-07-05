################################################################################
# File Name: test_statistics_vs_drive_statistics_no_dual_write.py
# Purpose/Description: US-452 / F-104 (D-1) -- reconcile `statistics` (per-profile
#                      rollup, raw Pi-sync mirror) vs `drive_statistics` (granular
#                      per-drive per-parameter SSOT, server-harness-derived).
#                      Asserts NO independent dual-write: only drive_statistics is
#                      server-derived; statistics is never constructed server-side
#                      (a raw mirror), so no single fact is derived into both.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-452) | Initial -- D-1 no-dual-write reconciliation:
#               |              | role split (per-profile rollup vs per-drive SSOT)
#               |              | + a source-scan proving statistics is never
#               |              | server-derived + manifest/write-path/doc guards.
# ================================================================================
################################################################################

"""US-452 / F-104 (D-1) -- statistics vs drive_statistics: no independent dual-write.

The D-1 concern: two per-parameter statistics tables could hold the *same* fact,
written by two independent paths.  This test makes "no dual-write" a CHECKABLE
contract:

1. **Source-scan** -- no server code constructs a ``statistics`` rollup row
   (``Statistic(...)``).  ``statistics`` is written ONLY by the generic raw
   Pi-sync mirror (``api.sync._TABLE_REGISTRY``), which passes the Pi-computed
   row through verbatim -- it is never *derived* server-side.  Only
   ``drive_statistics`` is server-derived (by the harness), so no single fact is
   independently derived into both.
2. **Manifest** -- the owned-table manifest records the honest writer roles:
   ``statistics`` = raw sync mirror (not harness-owned); ``drive_statistics`` =
   harness-owned granular SSOT.
3. **Write paths** -- ``statistics`` is in the sync registry (mirror);
   ``drive_statistics`` is NOT (server-derived).  Disjoint, non-overlapping paths.
4. **Role doc** -- the durable decision record documents which table is
   authoritative for which fact.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from src.server.analytics.owned_tables import (  # noqa: E402
    WRITER_HARNESS,
    WRITER_SYNC_MIRROR,
    harness_owned_tables,
    manifest_by_table,
)
from src.server.api.sync import _TABLE_REGISTRY  # noqa: E402
from src.server.db.models import Base  # noqa: E402

# tests/server/analytics/<file> -> repo root is parents[3].
REPO_ROOT = Path(__file__).resolve().parents[3]
SERVER_SRC = REPO_ROOT / "src" / "server"
ROLE_DOC = REPO_ROOT / "docs" / "statistics-vs-drive-statistics-roles.md"

# ``statistics`` rollup constructor (``Statistic(...)``).  ``\bStatistic\(`` never
# matches ``DriveStatistic(`` (no word boundary between ``e`` and ``S``), so this
# isolates the rollup model from the granular per-drive one.
_STATISTIC_CONSTRUCTOR = re.compile(r"\bStatistic\(")

# Files that legitimately NAME the Statistic model without deriving a row:
#   models.py       -- the ORM class definition (``class Statistic(Base)``).
#   owned_tables.py -- the manifest that documents the writer (writes nothing).
_SCAN_EXEMPT = {"models.py", "owned_tables.py"}


def _derivesAStatisticsRow(text: str) -> bool:
    """True iff a line of real code constructs a ``Statistic(...)`` rollup row.

    Whole-line comments are skipped (e.g. a migration's model-name listing
    ``# Statistic(statistics), ...`` is documentation, not a construction).
    """
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if _STATISTIC_CONSTRUCTOR.search(line):
            return True
    return False


# =========================================================================
# 1. Source-scan: statistics is never server-derived
# =========================================================================


class TestNoServerSideStatisticsDerivation:
    """No server code constructs a ``statistics`` rollup row."""

    def test_noServerCode_constructsAStatisticsRollupRow(self):
        offenders: list[str] = []
        for path in sorted(SERVER_SRC.rglob("*.py")):
            if path.name in _SCAN_EXEMPT:
                continue
            # The migrations layer runs DDL/DML via the runner; it never
            # constructs ORM model instances, so a `Statistic(` there is only
            # ever a comment/name reference, not a derivation.
            if "migrations" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if _derivesAStatisticsRow(text):
                offenders.append(str(path.relative_to(REPO_ROOT)))
        assert offenders == [], (
            "server code constructs a `statistics` rollup row -- statistics must "
            "stay a raw Pi-sync mirror (never server-derived), else it dual-writes "
            "the per-parameter fact drive_statistics owns (US-452 / D-1): "
            f"{offenders}"
        )


# =========================================================================
# 2. Manifest: honest writer roles
# =========================================================================


class TestManifestRoles:
    """The owned-table manifest records the distinct writer roles."""

    def test_statistics_isSyncMirror_notHarnessOwned(self):
        stat = manifest_by_table()["statistics"]
        assert stat.writer == WRITER_SYNC_MIRROR
        assert stat.harness_owned is False
        assert stat.analyze_writes is False

    def test_driveStatistics_isHarnessOwned(self):
        ds = manifest_by_table()["drive_statistics"]
        assert ds.writer == WRITER_HARNESS
        assert ds.harness_owned is True

    def test_statistics_isNotAmongHarnessOwnedTables(self):
        owned = harness_owned_tables()
        assert "drive_statistics" in owned
        assert "statistics" not in owned


# =========================================================================
# 3. Disjoint write paths (mirror vs server-derived)
# =========================================================================


class TestDistinctWritePaths:
    """statistics rides the raw sync mirror; drive_statistics is server-derived."""

    def test_statistics_isRawSyncMirrorTarget(self):
        assert "statistics" in _TABLE_REGISTRY

    def test_driveStatistics_isNotASyncTarget(self):
        assert "drive_statistics" not in _TABLE_REGISTRY

    def test_bothAreDistinctRealTables(self):
        real = set(Base.metadata.tables.keys())
        assert {"statistics", "drive_statistics"} <= real


# =========================================================================
# 4. Durable role documentation
# =========================================================================


class TestRoleDoc:
    """The D-1 decision record documents which table is authoritative."""

    def test_roleDoc_exists_andDocumentsAuthority(self):
        assert ROLE_DOC.exists(), (
            "US-452 requires a durable statistics-vs-drive_statistics role record"
        )
        text = ROLE_DOC.read_text(encoding="utf-8").lower()
        assert "drive_statistics" in text
        assert "statistics" in text
        assert "authoritative" in text
        assert "dual-write" in text
