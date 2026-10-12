################################################################################
# File Name: test_sync_log_quarantine.py
# Purpose/Description: US-391 (F-076) -- sync_log queue-level quarantine for
#                      records whose cross-tier push keeps failing.  Proves the
#                      bookkeeping primitives: idempotent schema migration,
#                      consecutive-failure counting, the N-failure quarantine
#                      transition (surface-once signal), state readback, and
#                      the clear-on-success reset that makes quarantine
#                      re-drainable.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-28    | Rex (US-391) | Initial -- queue-level quarantine bookkeeping.
# ================================================================================
################################################################################

"""US-391 unit tests for the sync_log quarantine bookkeeping.

The quarantine lives at the queue level (Pi sync_log), NOT in the per-attempt
resolver: 'fail loudly, no silent re-resolve' stays correct on the server, but
a single unresolvable record must stop being re-attempted every cycle.  These
tests exercise the sync_log primitives the SyncClient drives.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.pi.data import sync_log

_TABLE = "dtc_freeze_frame"
_T0 = "2026-06-28T12:00:00+00:00"


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Fresh in-memory SQLite with the migrated sync_log table."""
    c = sqlite3.connect(":memory:")
    sync_log.initDb(c)
    sync_log.ensureQuarantineSchema(c)
    yield c
    c.close()


# ==============================================================================
# Schema migration (idempotent ADD COLUMN)
# ==============================================================================


def test_ensureQuarantineSchema_addsColumns_onLegacyDb():
    """A pre-US-391 sync_log gains the quarantine columns; re-run is a no-op."""
    c = sqlite3.connect(":memory:")
    # Legacy shape: the base table without the quarantine columns.
    c.execute(
        "CREATE TABLE sync_log (table_name TEXT PRIMARY KEY, "
        "last_synced_id INTEGER NOT NULL DEFAULT 0, last_synced_at TEXT, "
        "last_batch_id TEXT, status TEXT NOT NULL DEFAULT 'pending')"
    )
    c.commit()

    firstRun = sync_log.ensureQuarantineSchema(c)
    cols = {row[1] for row in c.execute("PRAGMA table_info(sync_log)")}
    secondRun = sync_log.ensureQuarantineSchema(c)

    assert firstRun is True
    assert "consecutive_failures" in cols
    assert "quarantined_at" in cols
    assert secondRun is False  # already migrated -> no work
    c.close()


# ==============================================================================
# Failure counting + quarantine transition
# ==============================================================================


def test_recordPushFailure_incrementsCount_belowThreshold_notQuarantined(conn):
    """Below N consecutive failures the record is failed but NOT quarantined."""
    just1 = sync_log.recordPushFailure(
        conn, _TABLE, "b1", quarantineThreshold=3, nowIso=_T0,
    )
    just2 = sync_log.recordPushFailure(
        conn, _TABLE, "b2", quarantineThreshold=3, nowIso=_T0,
    )

    count, quarantinedAt = sync_log.getQuarantineState(conn, _TABLE)
    assert just1 is False
    assert just2 is False
    assert count == 2
    assert quarantinedAt is None


def test_recordPushFailure_quarantinesOnNthFailure_andSignalsOnce(conn):
    """The Nth consecutive failure quarantines and returns True exactly once."""
    sync_log.recordPushFailure(conn, _TABLE, "b1", quarantineThreshold=3, nowIso=_T0)
    sync_log.recordPushFailure(conn, _TABLE, "b2", quarantineThreshold=3, nowIso=_T0)
    justQuarantined = sync_log.recordPushFailure(
        conn, _TABLE, "b3", quarantineThreshold=3, nowIso=_T0,
    )
    # A 4th failure is already-quarantined -> must NOT re-signal (surface once).
    afterQuarantine = sync_log.recordPushFailure(
        conn, _TABLE, "b4", quarantineThreshold=3, nowIso="2026-06-28T13:00:00+00:00",
    )

    count, quarantinedAt = sync_log.getQuarantineState(conn, _TABLE)
    assert justQuarantined is True
    assert afterQuarantine is False
    assert count == 4
    # quarantined_at is stamped once, at the transition instant -- never moved.
    assert quarantinedAt == _T0


def test_recordPushFailure_doesNotAdvanceHighWaterMark(conn):
    """Quarantine throttles re-attempts; it must never advance last_synced_id."""
    sync_log.updateHighWaterMark(conn, _TABLE, 7, "ok-batch", status="ok")

    sync_log.recordPushFailure(conn, _TABLE, "f1", quarantineThreshold=2, nowIso=_T0)
    sync_log.recordPushFailure(conn, _TABLE, "f2", quarantineThreshold=2, nowIso=_T0)

    lastId, _, _, status = sync_log.getHighWaterMark(conn, _TABLE)
    assert lastId == 7  # HWM unchanged -> the raw record is preserved/re-sendable
    assert status == "failed"


# ==============================================================================
# Clear-on-success -> re-drainable
# ==============================================================================


def test_clearQuarantine_resetsCountAndFlag(conn):
    """A successful drain clears the quarantine so the record can flow again."""
    sync_log.recordPushFailure(conn, _TABLE, "b1", quarantineThreshold=2, nowIso=_T0)
    sync_log.recordPushFailure(conn, _TABLE, "b2", quarantineThreshold=2, nowIso=_T0)
    assert sync_log.getQuarantineState(conn, _TABLE)[1] is not None

    sync_log.clearQuarantine(conn, _TABLE)

    count, quarantinedAt = sync_log.getQuarantineState(conn, _TABLE)
    assert count == 0
    assert quarantinedAt is None


def test_getQuarantineState_unknownTable_raisesValueError(conn):
    with pytest.raises(ValueError, match="sync scope"):
        sync_log.getQuarantineState(conn, "not_a_table")
