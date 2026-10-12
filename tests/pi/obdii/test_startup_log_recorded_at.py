################################################################################
# File Name: test_startup_log_recorded_at.py
# Purpose/Description: US-417 tests for the idempotent Pi-side guard that ensures
#                      startup_log carries the recorded_at cursor column (the
#                      SNAPSHOT_SYNC delta cursor). recorded_at has shipped with
#                      startup_log since its creation (US-263, 665863e), so on a
#                      current-schema DB the guard is a no-op; the guard exists to
#                      cover the "(if absent)" acceptance path defensively -- a
#                      legacy/partial startup_log missing the column gains it
#                      (nullable TEXT; SQLite ALTER cannot use the non-constant
#                      strftime default), and a not-yet-created table is skipped.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-417) | Initial -- recorded_at column guard tests.
# ================================================================================
################################################################################

"""US-417 tests for :func:`ensureStartupLogRecordedAt`."""

from __future__ import annotations

import sqlite3

from src.pi.obdii.database_schema import (
    SCHEMA_STARTUP_LOG,
    ensureStartupLogRecordedAt,
)

# A legacy startup_log DDL predating recorded_at (the "(if absent)" case).
_LEGACY_STARTUP_LOG = """
CREATE TABLE startup_log (
    boot_id TEXT PRIMARY KEY,
    prior_boot_clean INTEGER,
    prior_last_entry_ts TEXT,
    current_boot_first_entry_ts TEXT
)
"""


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


class TestEnsureStartupLogRecordedAt:
    def test_currentSchemaIsNoOp(self) -> None:
        """recorded_at is already present -> the guard does nothing."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(SCHEMA_STARTUP_LOG)
        assert "recorded_at" in _cols(conn, "startup_log")

        didWork = ensureStartupLogRecordedAt(conn)

        assert didWork is False
        assert "recorded_at" in _cols(conn, "startup_log")

    def test_addsColumnWhenAbsent(self) -> None:
        """A legacy startup_log lacking recorded_at gains it (nullable TEXT)."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(_LEGACY_STARTUP_LOG)
        assert "recorded_at" not in _cols(conn, "startup_log")

        didWork = ensureStartupLogRecordedAt(conn)

        assert didWork is True
        assert "recorded_at" in _cols(conn, "startup_log")

    def test_idempotentAfterAdd(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(_LEGACY_STARTUP_LOG)
        ensureStartupLogRecordedAt(conn)

        # Second run is a no-op now the column exists.
        assert ensureStartupLogRecordedAt(conn) is False

    def test_missingTableIsSkippedNotCrash(self) -> None:
        """No startup_log table yet -> guard is a graceful no-op (lazy init)."""
        conn = sqlite3.connect(":memory:")
        # No startup_log created at all.
        assert ensureStartupLogRecordedAt(conn) is False

    def test_existingRowsSurviveTheAdd(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(_LEGACY_STARTUP_LOG)
        conn.execute(
            "INSERT INTO startup_log (boot_id, prior_boot_clean) VALUES (?, ?)",
            ("boot-legacy", 1),
        )
        conn.commit()

        ensureStartupLogRecordedAt(conn)

        row = conn.execute(
            "SELECT boot_id, recorded_at FROM startup_log WHERE boot_id = ?",
            ("boot-legacy",),
        ).fetchone()
        assert row[0] == "boot-legacy"
        # Pre-existing legacy rows have no cursor value; NULL is expected.
        assert row[1] is None
