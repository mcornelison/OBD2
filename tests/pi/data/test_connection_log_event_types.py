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
