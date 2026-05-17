################################################################################
# File Name: test_boot_reason_boot_id.py
# Purpose/Description: Covers the surviving boot-id helpers in
#                      src/pi/diagnostics/boot_reason.py after the T10 cutover
#                      (readCurrentBootId + _normalizeBootId + BOOT_ID_PATH)
#                      and asserts the legacy journal-scan canary symbols are
#                      removed (I-037 -- the deleted canary classified hard
#                      crashes as clean shutdowns).  Also carries the relocated
#                      US-263/US-283 startup_log schema pin (TestStartupLogSchema,
#                      byte-faithful from the deleted test_boot_reason.py) so
#                      the 7-column STRICT contract guard survives the cutover.
# Author: Plan (T10)
# Creation Date: 2026-05-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-15    | Plan (T10)   | Initial -- created during the journal-scan
#               |              | canary cutover.  Boot-id helper coverage +
#               |              | removed-symbol guard + relocated (byte-
#               |              | faithful) TestStartupLogSchema /
#               |              | TestNormalizeBootId / TestReadCurrentBootId
#               |              | from the now-deleted test_boot_reason.py.
# ================================================================================
################################################################################

"""Surviving boot-id helper tests + I-037 removed-symbol guard.

The T10 cutover deleted the journal-scan boot-reason canary (the
``detectBootReason`` / ``recordBootReason`` / ``writeStartupLog`` path
and its journal-scan helpers).  ``startup_log`` is now written by the
honest instrument ``src/pi/diagnostics/boot_progress.py``.  This file:

* exercises the boot-id surface that survived
  (``readCurrentBootId`` + ``_normalizeBootId``);
* pins that the journal-scan symbols are gone (I-037 regression guard);
* carries the relocated US-263/US-283 ``startup_log`` schema pin so the
  STRICT 7-column / sole-PK contract guard survives the deletion of
  ``test_boot_reason.py`` without weakening a single assertion.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path -- tests are invoked from various
# CWDs via the makefile + IDE runners; importing src.pi.* from a
# brand-new package needs the safety net (mirrors the convention from
# the relocated-out-of test_boot_reason.py).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import src.pi.diagnostics.boot_reason as br  # noqa: E402  (import after path-mutate)
from src.pi.diagnostics.boot_reason import (  # noqa: E402
    _normalizeBootId,
    readCurrentBootId,
)
from src.pi.obdii.database_schema import SCHEMA_STARTUP_LOG  # noqa: E402

# ================================================================================
# Surviving boot-id surface + I-037 removed-symbol guard
# ================================================================================

def test_readCurrentBootId_normalizes(tmp_path):
    f = tmp_path / "bid"
    f.write_text("ABCD-1234\n", encoding="ascii")
    assert br.readCurrentBootId(str(f)) == "abcd1234"


def test_journalScanSymbolsRemoved():
    for gone in ("detectBootReason", "_probeLadderGraceful", "_readBootList",
                 "_hasShutdownMarker", "parseListBoots", "runJournalctl",
                 "recordBootReason", "writeStartupLog",
                 "SHUTDOWN_MARKERS", "LADDER_GRACEFUL_GREP_PATTERN"):
        assert not hasattr(br, gone), f"{gone} should be deleted"


# ================================================================================
# Relocated (byte-faithful) -- Pure Helper: boot_id normalizer
# ================================================================================

class TestNormalizeBootId:
    """:func:`_normalizeBootId` lowercases + strips whitespace + strips dashes."""

    @pytest.mark.parametrize("raw,expected", [
        ("abcd1234-abcd-1234-abcd-1234abcd1234\n", "abcd1234abcd1234abcd1234abcd1234"),
        ("A1B2C3D4E5F67890\n", "a1b2c3d4e5f67890"),
        ("  abc-def-123  ", "abcdef123"),
        ("", ""),
    ])
    def test_normalizeBootId_handlesShapes(self, raw: str, expected: str) -> None:
        assert _normalizeBootId(raw) == expected


# ================================================================================
# Relocated (byte-faithful) -- I/O Boundary: boot_id surface read
# ================================================================================

class TestReadCurrentBootId:
    """Boot-id surface read + normalization."""

    def test_readCurrentBootId_validFile_returnsNormalized(self, tmp_path: Path) -> None:
        bootIdPath = tmp_path / 'boot_id'
        bootIdPath.write_text('ABCD1234-ABCD-1234-ABCD-1234ABCD1234\n')
        result = readCurrentBootId(str(bootIdPath))
        assert result == 'abcd1234abcd1234abcd1234abcd1234'

    def test_readCurrentBootId_missingFile_returnsNone(self, tmp_path: Path) -> None:
        result = readCurrentBootId(str(tmp_path / 'does_not_exist'))
        assert result is None

    def test_readCurrentBootId_emptyFile_returnsNone(self, tmp_path: Path) -> None:
        bootIdPath = tmp_path / 'boot_id'
        bootIdPath.write_text('')
        assert readCurrentBootId(str(bootIdPath)) is None


# ================================================================================
# Relocated (byte-faithful) -- US-283 Production Schema Pin
# ================================================================================

class TestStartupLogSchema:
    """Pin the canonical ``startup_log`` column set from US-263 (Sprint 22).

    Sprint 24 US-283 audit traced Spool's drift flag to its source: the
    deployed table has no ``id`` column.  That matches the spec -- the
    canonical schema uses ``boot_id`` as the PRIMARY KEY and there never
    was an ``id`` column.  Production ``SCHEMA_STARTUP_LOG`` in
    ``src/pi/obdii/database_schema.py`` matches the US-263 contract,
    which as of the 2026-05-15 honest-instrument addition is now 7
    columns: the original US-263 5 (``boot_id`` TEXT PK,
    ``prior_boot_clean`` INTEGER, ``prior_last_entry_ts`` TEXT,
    ``current_boot_first_entry_ts`` TEXT, ``recorded_at`` TEXT NOT NULL)
    plus the 2 honest-instrument additions ``prior_boot_last_stage``
    TEXT and ``prior_boot_reason`` TEXT (spec
    2026-05-15-honest-boot-progress-instrument-design.md §4.4).

    These tests apply the production schema to a fresh in-memory SQLite,
    introspect via ``PRAGMA table_info``, and assert the (name, type,
    notnull, pk) tuple matches the contract exactly.  Any future drift --
    a stray ``id`` column, a renamed column, a type change, an added
    NOT NULL, or a compound PK -- breaks the test loudly instead of
    silently rotting the writer / reader contract.
    """

    # (name, type, notnull, pk) per ``PRAGMA table_info`` semantics.
    # ``dflt_value`` is intentionally not pinned: ``recorded_at`` carries
    # a ``DEFAULT (strftime(...))`` expression in production and we treat
    # that detail as orthogonal to the column-set contract.
    EXPECTED_COLUMNS: tuple[tuple[str, str, int, int], ...] = (
        ('boot_id', 'TEXT', 0, 1),
        ('prior_boot_clean', 'INTEGER', 0, 0),
        ('prior_last_entry_ts', 'TEXT', 0, 0),
        ('current_boot_first_entry_ts', 'TEXT', 0, 0),
        # 2026-05-15 honest-instrument addition (spec
        # 2026-05-15-honest-boot-progress-instrument-design.md §4.4):
        # highest boot_progress milestone reached + its decoded reason.
        ('prior_boot_last_stage', 'TEXT', 0, 0),
        ('prior_boot_reason', 'TEXT', 0, 0),
        ('recorded_at', 'TEXT', 1, 0),
    )

    @staticmethod
    def _introspectStartupLog() -> tuple[tuple[str, str, int, int], ...]:
        """Apply production schema to a fresh DB and return PRAGMA tuple."""
        conn = sqlite3.connect(':memory:')
        try:
            conn.executescript(SCHEMA_STARTUP_LOG)
            cursor = conn.execute("PRAGMA table_info(startup_log)")
            return tuple(
                (row[1], row[2].upper(), row[3], row[5])
                for row in cursor.fetchall()
            )
        finally:
            conn.close()

    def test_startupLogSchema_matchesUs263CanonicalColumnSet(self) -> None:
        # 2026-05-15 honest-instrument addition: the canonical set grew
        # from the original US-263 5 columns to 7 -- prior_boot_last_stage
        # and prior_boot_reason were added per design spec
        # 2026-05-15-honest-boot-progress-instrument-design.md §4.4.  This
        # remains a STRICT exact-set assertion (no subset / >=); any other
        # drift still breaks loudly.
        actual = self._introspectStartupLog()
        assert actual == self.EXPECTED_COLUMNS, (
            "startup_log schema drift detected.\n"
            f"Expected: {self.EXPECTED_COLUMNS}\n"
            f"Actual:   {actual}\n"
            "If this fails after a deliberate schema change, update both "
            "EXPECTED_COLUMNS and the US-263 spec; do NOT relax the test."
        )

    def test_startupLogSchema_bootIdIsSolePrimaryKey(self) -> None:
        # Defends specifically against the failure mode Spool flagged:
        # someone "fixing" the schema by adding an ``id INTEGER PRIMARY KEY``
        # rowid alias and demoting boot_id to a UNIQUE column.  That
        # would silently break the writer's INSERT OR IGNORE idempotency
        # contract because the PK changes from boot_id to rowid.
        actual = self._introspectStartupLog()
        pkColumns = [name for (name, _type, _notnull, pk) in actual if pk == 1]
        assert pkColumns == ['boot_id'], (
            f"startup_log PK must be exactly ['boot_id']; got {pkColumns}. "
            "Adding an `id` rowid alias or compound PK breaks the US-263 "
            "INSERT OR IGNORE idempotency contract."
        )

    def test_startupLogSchema_columnCount_isSeven(self) -> None:
        # Quick canary on extra columns: any addition (even if otherwise
        # well-formed) widens the contract surface; force a deliberate
        # spec update instead of silently accepting drift.  2026-05-15
        # honest-instrument: count grew 5 -> 7 (prior_boot_last_stage +
        # prior_boot_reason added per design spec
        # 2026-05-15-honest-boot-progress-instrument-design.md §4.4).
        actual = self._introspectStartupLog()
        assert len(actual) == 7, (
            f"startup_log has {len(actual)} columns; canonical schema is "
            f"exactly 7 (US-263 5-col + 2026-05-15 honest-instrument "
            f"prior_boot_last_stage/prior_boot_reason). "
            f"Got: {[name for (name, *_) in actual]}"
        )
