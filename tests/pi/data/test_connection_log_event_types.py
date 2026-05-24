################################################################################
# File Name: test_connection_log_event_types.py
# Purpose/Description: Tests that the US-211 canonical event_type constants
#                      exist, the connection_log accepts rows with each new
#                      literal, and the helper writer emits well-formed rows.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-211) | Initial -- Spool Session 6 amended Story 2.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.data.connection_logger` + connection_log schema.

Per US-211 the ``event_type`` column stays TEXT (free-form, no CHECK)
because dynamic writers across the codebase (profile switcher, shutdown
command_core.py) emit runtime-composed strings. The Python constants in
:mod:`src.pi.data.connection_logger` are the canonical source of truth;
these tests pin that constants match Spool's spec and that the DB
accepts the new literals end-to-end.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from src.pi.data.connection_logger import (
    CANONICAL_EVENT_TYPES,
    EVENT_ADAPTER_WAIT,
    EVENT_BT_DISCONNECT,
    EVENT_ECU_SILENT_WAIT,
    EVENT_RECONNECT_ATTEMPT,
    EVENT_RECONNECT_SUCCESS,
    US211_EVENT_TYPES,
    logConnectionEvent,
)
from src.pi.obdii.database import ObdDatabase


@pytest.fixture
def freshDb(tmp_path) -> Generator[ObdDatabase, None, None]:
    """Fresh Pi database with full schema."""
    dbPath = tmp_path / "obd.db"
    db = ObdDatabase(str(dbPath), walMode=False)
    db.initialize()
    yield db


# ================================================================================
# Constants
# ================================================================================

def test_us211_eventTypes_exactFive():
    """Spool Session 6 locked five new event_type literals."""
    assert US211_EVENT_TYPES == frozenset({
        'bt_disconnect',
        'adapter_wait',
        'reconnect_attempt',
        'reconnect_success',
        'ecu_silent_wait',
    })


def test_us211_constantValues_matchLiterals():
    """Each constant must equal its wire-level string -- no typos."""
    assert EVENT_BT_DISCONNECT == 'bt_disconnect'
    assert EVENT_ADAPTER_WAIT == 'adapter_wait'
    assert EVENT_RECONNECT_ATTEMPT == 'reconnect_attempt'
    assert EVENT_RECONNECT_SUCCESS == 'reconnect_success'
    assert EVENT_ECU_SILENT_WAIT == 'ecu_silent_wait'


def test_canonical_eventTypes_includesPreUs211Literals():
    """Existing literals (US-211 invariant) stay in the canonical set."""
    # Per US-211 invariant + observed codebase literals.
    expectedPreUs211 = {
        'connect_attempt',
        'connect_success',
        'connect_failure',
        'disconnect',
        'reconnect',
        'drive_start',
        'drive_end',
        'data_cleanup',
    }
    assert expectedPreUs211.issubset(CANONICAL_EVENT_TYPES)
    assert US211_EVENT_TYPES.issubset(CANONICAL_EVENT_TYPES)


# ================================================================================
# Schema acceptance
# ================================================================================

def test_connectionLog_acceptsAllUs211EventTypes(freshDb):
    """Fresh connection_log table accepts every US-211 literal with no CHECK failure."""
    with freshDb.connect() as conn:
        for eventType in US211_EVENT_TYPES:
            conn.execute(
                """
                INSERT INTO connection_log
                (event_type, mac_address, success, error_message, retry_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                (eventType, '00:04:3E:85:0D:FB', 0, None, 0),
            )
        conn.commit()
        rows = conn.execute(
            "SELECT event_type FROM connection_log ORDER BY id"
        ).fetchall()
        observed = {row[0] for row in rows}
    assert observed == US211_EVENT_TYPES


def test_connectionLog_acceptsDynamicShutdownLiteral(freshDb):
    """Guard: dynamic writer from shutdown/command_core.py still works.

    We must NOT have added a CHECK constraint that rejects runtime-
    composed strings (f'shutdown_{event}').
    """
    with freshDb.connect() as conn:
        conn.execute(
            """
            INSERT INTO connection_log (event_type, mac_address, success)
            VALUES (?, ?, ?)
            """,
            ('shutdown_pre_flight_drives', None, 1),
        )
        conn.commit()
        row = conn.execute(
            "SELECT event_type FROM connection_log WHERE id = last_insert_rowid()"
        ).fetchone()
    assert row[0] == 'shutdown_pre_flight_drives'


# ================================================================================
# logConnectionEvent helper
# ================================================================================

def test_logConnectionEvent_writesCanonicalRow(freshDb):
    """Helper writes a row with timestamp + the supplied columns."""
    logConnectionEvent(
        database=freshDb,
        eventType=EVENT_BT_DISCONNECT,
        macAddress='00:04:3E:85:0D:FB',
        success=False,
        errorMessage='rfcomm timeout',
        retryCount=0,
    )
    with freshDb.connect() as conn:
        row = conn.execute(
            """
            SELECT event_type, mac_address, success,
                   error_message, retry_count, drive_id, timestamp
            FROM connection_log ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    assert row[0] == 'bt_disconnect'
    assert row[1] == '00:04:3E:85:0D:FB'
    assert row[2] == 0
    assert row[3] == 'rfcomm timeout'
    assert row[4] == 0
    assert row[5] is None  # drive_id null when not provided
    assert row[6] is not None  # canonical timestamp populated


def test_logConnectionEvent_successFlag_isInt(freshDb):
    """Boolean->int conversion matches existing writer semantics."""
    logConnectionEvent(
        database=freshDb,
        eventType=EVENT_RECONNECT_SUCCESS,
        macAddress='00:04:3E:85:0D:FB',
        success=True,
        retryCount=3,
    )
    with freshDb.connect() as conn:
        row = conn.execute(
            "SELECT success, retry_count FROM connection_log "
            "WHERE event_type = 'reconnect_success'"
        ).fetchone()
    assert row[0] == 1
    assert row[1] == 3


def test_logConnectionEvent_nullDatabase_noOp():
    """None database argument is a no-op (unit tests pass db=None)."""
    logConnectionEvent(
        database=None,
        eventType=EVENT_BT_DISCONNECT,
    )  # Should not raise.


def test_logConnectionEvent_swallowsDbExceptions(freshDb):
    """A broken DB must not crash the capture loop -- observability stays soft."""
    class BrokenDb:
        def connect(self):
            raise RuntimeError("simulated DB failure")

    # Must not raise:
    logConnectionEvent(
        database=BrokenDb(),
        eventType=EVENT_ADAPTER_WAIT,
    )


# ================================================================================
# Writer-site audit (lightweight grep-style discipline)
# ================================================================================

def test_existingWriters_useCanonicalLiterals():
    """Guard: every existing US-211 literal is referenced somewhere in src/.

    This is a grep-style audit -- if a canonical constant exists in
    connection_logger.py but no writer ever imports it, we probably
    failed to wire the callers into the new path.
    """
    from pathlib import Path

    srcRoot = Path(__file__).resolve().parents[3] / 'src' / 'pi'
    pySources = list(srcRoot.rglob('*.py'))
    assert pySources, "Expected to find Pi-side Python sources"

    text = ''
    for path in pySources:
        try:
            text += path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue

    # Every US-211 literal appears at least once in src/pi/ -- either
    # as a constant definition or a writer.
    for literal in US211_EVENT_TYPES:
        assert literal in text, (
            f"US-211 literal {literal!r} is not referenced in src/pi/. "
            f"Either the constant has no writer or the codebase drifted."
        )


# ================================================================================
# US-340b -- connection_log state-change-only logging (chatter reduction)
# ================================================================================
#
# CIO 2026-05-13: connection_log exists to help debug other aspects of the
# project; "minimal information is required."  Mobile telemetry hygiene says
# log STATE CHANGES, not per-action.  Pre-V0.27.10 a sustained adapter outage
# generated ~2000 rows/day (7 rows per heartbeat tick x ~12 ticks/hour
# steady-state with US-325 backoff).  Server-side mirror filled up with
# thousands of repetitive "still trying" rows.
#
# Fix: a tiny dedup at the writer.  When the SAME event_type fires for the
# SAME mac_address as the most-recently-logged event, AND the event is one
# of the spammy "still trying" types (connect_attempt / adapter_wait /
# reconnect_attempt), the writer skips the row.  State-change events
# (connect_success / connect_failure / disconnect / reconnect /
# reconnect_success / bt_disconnect / ...) ALWAYS log -- the transition is
# the load-bearing signal.  Per-mac state means two different adapters
# don't dedup against each other.
# ================================================================================


class TestUs340bConnectionLogDedup:
    """Regression tests for the US-340b state-change-only logging dedup."""

    @pytest.fixture(autouse=True)
    def _resetDedupState(self) -> Generator[None, None, None]:
        """Each test starts with a clean dedup tracker so order-of-tests
        cannot leak state between cases."""
        from src.pi.data import connection_logger as cl
        cl.resetDedupStateForTests()
        yield
        cl.resetDedupStateForTests()

    def test_repeatedConnectAttempt_writesOnlyOneRow(self, freshDb) -> None:
        """
        Given: two `connect_attempt` events for the same mac_address in a row
        When: each is passed to logConnectionEvent
        Then: only ONE row lands in connection_log (the 2nd is deduped)
        """
        from src.pi.data.connection_logger import EVENT_CONNECT_ATTEMPT

        mac = '00:04:3E:85:0D:FB'
        for _ in range(5):
            logConnectionEvent(
                database=freshDb,
                eventType=EVENT_CONNECT_ATTEMPT,
                macAddress=mac,
            )
        with freshDb.connect() as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM connection_log "
                "WHERE event_type = 'connect_attempt' AND mac_address = ?",
                (mac,),
            ).fetchone()[0]
        assert cnt == 1, (
            f"US-340b regression: 5 connect_attempt events for the same mac "
            f"should produce 1 row (state-change-only logging); got {cnt}.  "
            f"Pre-fix this produced 5 rows -- one of the row-volume sources "
            f"that filled the server-side mirror to thousands of rows."
        )

    def test_stateChangeEvents_alwaysLog_evenAfterRepeats(self, freshDb) -> None:
        """
        Given: a sequence of attempts followed by a state-change
        When: connect_attempt repeats AND THEN connect_failure fires
        Then: 1 row for connect_attempt (deduped) + 1 row for connect_failure
              (state change -- always logs)
        """
        from src.pi.data.connection_logger import (
            EVENT_CONNECT_ATTEMPT,
            EVENT_CONNECT_FAILURE,
            EVENT_CONNECT_SUCCESS,
        )

        mac = '00:04:3E:85:0D:FB'
        for _ in range(3):
            logConnectionEvent(database=freshDb, eventType=EVENT_CONNECT_ATTEMPT,
                               macAddress=mac)
        logConnectionEvent(database=freshDb, eventType=EVENT_CONNECT_FAILURE,
                           macAddress=mac, errorMessage='out of retries')
        # After a state-change, a NEW outage's connect_attempt should log
        # again (the last-logged is now connect_failure, so connect_attempt
        # is a new transition).
        for _ in range(3):
            logConnectionEvent(database=freshDb, eventType=EVENT_CONNECT_ATTEMPT,
                               macAddress=mac)
        logConnectionEvent(database=freshDb, eventType=EVENT_CONNECT_SUCCESS,
                           macAddress=mac, success=True)

        with freshDb.connect() as conn:
            rows = conn.execute(
                "SELECT event_type FROM connection_log "
                "WHERE mac_address = ? ORDER BY id",
                (mac,),
            ).fetchall()
        observed = [r[0] for r in rows]
        # The full outage timeline is still legible -- attempt, failure,
        # attempt (new try), success.  Just without per-retry repeats.
        assert observed == [
            'connect_attempt',
            'connect_failure',
            'connect_attempt',
            'connect_success',
        ], (
            f"US-340b: full outage transition timeline must be preserved; "
            f"got {observed}"
        )

    def test_dedupIsPerMac_differentAdaptersIndependent(self, freshDb) -> None:
        """
        Given: connect_attempt for two different mac_addresses
        When: both fire repeatedly interleaved
        Then: each mac gets its own dedup state (one row per mac, no
              cross-contamination)
        """
        from src.pi.data.connection_logger import EVENT_CONNECT_ATTEMPT

        macA = '00:04:3E:85:0D:FB'
        macB = '11:22:33:44:55:66'
        for _ in range(3):
            logConnectionEvent(database=freshDb,
                               eventType=EVENT_CONNECT_ATTEMPT, macAddress=macA)
            logConnectionEvent(database=freshDb,
                               eventType=EVENT_CONNECT_ATTEMPT, macAddress=macB)
        with freshDb.connect() as conn:
            rowsByMac = dict(conn.execute(
                "SELECT mac_address, COUNT(*) FROM connection_log "
                "GROUP BY mac_address"
            ).fetchall())
        assert rowsByMac[macA] == 1
        assert rowsByMac[macB] == 1

    def test_adapterWaitAndReconnectAttempt_alsoDeduped(self, freshDb) -> None:
        """
        Given: ReconnectLoop's adapter_wait and reconnect_attempt events
        When: each fires repeatedly for the same mac
        Then: only one row per event_type sequence (same dedup rule)
        """
        mac = '00:04:3E:85:0D:FB'
        # Simulate ReconnectLoop's per-iteration pattern: adapter_wait + probe
        for _ in range(4):
            logConnectionEvent(database=freshDb,
                               eventType=EVENT_ADAPTER_WAIT, macAddress=mac)
            logConnectionEvent(database=freshDb,
                               eventType=EVENT_RECONNECT_ATTEMPT, macAddress=mac)
        # Eventually probe succeeds -- state change
        logConnectionEvent(database=freshDb,
                           eventType=EVENT_RECONNECT_SUCCESS, macAddress=mac,
                           success=True)
        with freshDb.connect() as conn:
            rows = conn.execute(
                "SELECT event_type FROM connection_log "
                "WHERE mac_address = ? ORDER BY id",
                (mac,),
            ).fetchall()
        observed = [r[0] for r in rows]
        # Expect: adapter_wait (first), reconnect_attempt (first),
        # reconnect_success (transition).  Subsequent adapter_wait /
        # reconnect_attempt repeats interleaved are deduped against their
        # own last-seen state.
        assert observed == [
            'adapter_wait',
            'reconnect_attempt',
            'reconnect_success',
        ], f"US-340b dedup must cover adapter_wait + reconnect_attempt too; got {observed}"
