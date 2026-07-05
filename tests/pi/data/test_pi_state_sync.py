################################################################################
# File Name: test_pi_state_sync.py
# Purpose/Description: Pi-side sync tests for pi_state (US-453 / D-7 / F-082).
#                      pi_state is a MUTABLE singleton (id pinned to 1; carries
#                      the no_new_drives gate).  These tests prove the Pi
#                      re-sends the row after a no_new_drives flip -- the id
#                      cursor sticks at 1, so the modified_at update-propagation
#                      cursor (SYNC_UPDATE_TABLES_PK) is what keeps the server
#                      mirror current.  Also VERIFY (do not redo) that power_log
#                      already delta-syncs and startup_log already snapshot-syncs.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-453) | Initial -- pi_state joins the raw-sync scope.
# ================================================================================
################################################################################

"""Pi-side pi_state raw-sync tests (US-453 / D-7 / F-082).

The delta path was built for append-only event streams (monotonic id cursor).
pi_state is the degenerate single-row case: id is always 1, and no_new_drives
is UPDATEd in place.  A plain id cursor would push id=1 once and then go
permanently stale (1 > 1 is false forever), so pi_state opts into the
modified_at cursor -- exactly the drive_summary UPDATE-replay pattern -- so the
AFTER UPDATE trigger stamps _sync_modified_at and getDeltaRows re-fetches the
flipped row even though the id cursor has not moved.  That is what makes the
server mirror match the Pi over time.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.common.sync.snapshot_registry import isSnapshotSyncTable
from src.pi.data import sync_log
from src.pi.obdii.pi_state import ensurePiStateTable, setNoNewDrives

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def conn() -> sqlite3.Connection:
    """In-memory DB with pi_state at production shape + modified_at wired.

    Mirrors the production boot path: ensurePiStateTable creates the singleton,
    then ensureSyncModifiedAtSchema adds the _sync_modified_at column + AFTER
    UPDATE trigger to every SYNC_UPDATE_TABLES_PK table (pi_state included).
    """
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    sync_log.initDb(c)
    ensurePiStateTable(c)
    c.commit()
    sync_log.ensureSyncModifiedAtSchema(c)
    yield c
    c.close()


# --------------------------------------------------------------------------- #
# Registration (US-453)
# --------------------------------------------------------------------------- #


class TestPiStateRegistration:
    """pi_state joins the delta set AND the modified_at update-propagation set."""

    def test_inScopeAndDeltaSyncable(self) -> None:
        assert 'pi_state' in sync_log.IN_SCOPE_TABLES
        assert 'pi_state' in sync_log.DELTA_SYNC_TABLES

    def test_pkIsId(self) -> None:
        assert sync_log.PK_COLUMN['pi_state'] == 'id'

    def test_optsIntoModifiedAtCursor(self) -> None:
        assert sync_log.SYNC_UPDATE_TABLES_PK.get('pi_state') == 'id'

    def test_notASnapshotTable(self) -> None:
        """pi_state is integer-PK delta, NOT the profiles/vehicle_info reject."""
        assert 'pi_state' not in sync_log.SNAPSHOT_TABLES
        assert not isSnapshotSyncTable('pi_state')


# --------------------------------------------------------------------------- #
# Delta + modified_at behaviour (the mutable-singleton guarantee)
# --------------------------------------------------------------------------- #


class TestPiStateDeltaAndUpdatePropagation:
    """First push via id cursor; every flip re-caught via modified_at cursor."""

    def test_firstPushCapturesSingletonViaIdCursor(
        self, conn: sqlite3.Connection,
    ) -> None:
        rows = sync_log.getDeltaRows(conn, 'pi_state', lastId=0, limit=100)
        assert len(rows) == 1
        assert rows[0]['id'] == 1
        assert rows[0]['no_new_drives'] == 0
        # The Pi-only bookkeeping column never rides the wire.
        assert sync_log.SYNC_MODIFIED_AT_COLUMN not in rows[0]

    def test_idCursorAloneGoesStaleAfterFirstPush(
        self, conn: sqlite3.Connection,
    ) -> None:
        """RED discriminator: without modified_at, id=1 > 1 is empty forever.

        Passing lastModifiedAt=None but with no UPDATE yet, the id cursor at 1
        returns nothing -- proving a plain id cursor cannot re-sync the flip.
        """
        rows = sync_log.getDeltaRows(conn, 'pi_state', lastId=1, limit=100)
        assert rows == []

    def test_flagFlipReSyncsViaModifiedAtCursor(
        self, conn: sqlite3.Connection,
    ) -> None:
        """After a no_new_drives flip, getDeltaRows re-fetches id=1 at lastId=1.

        The AFTER UPDATE trigger stamps _sync_modified_at on the setNoNewDrives
        UPDATE, so the combined cursor catches the row even though the id cursor
        (1) has not advanced -- this is the keep-the-server-current mechanism.
        """
        setNoNewDrives(conn, True)  # WARNING-stage flip -> UPDATE fires trigger
        conn.commit()

        rows = sync_log.getDeltaRows(
            conn, 'pi_state', lastId=1, limit=100, lastModifiedAt=None,
        )
        assert len(rows) == 1
        assert rows[0]['id'] == 1
        assert rows[0]['no_new_drives'] == 1

    def test_clearReSyncsAgain(self, conn: sqlite3.Connection) -> None:
        """AC-restore (clear) is a second UPDATE -> re-syncs the 0 value too.

        Uses lastModifiedAt=None (not the first flip's timestamp) deliberately:
        two in-memory UPDATEs can land in the same strftime('%f') millisecond,
        so a strict-greater cursor keyed on the first flip would be flaky.  The
        guarantee under test is "a clear UPDATE stamps _sync_modified_at and is
        therefore re-fetchable while the id cursor is stuck at 1" -- which holds
        regardless of the exact timestamp.
        """
        setNoNewDrives(conn, True)
        conn.commit()
        setNoNewDrives(conn, False)  # AC-restore -> second UPDATE
        conn.commit()

        rows = sync_log.getDeltaRows(
            conn, 'pi_state', lastId=1, limit=100, lastModifiedAt=None,
        )
        assert len(rows) == 1
        assert rows[0]['no_new_drives'] == 0


# --------------------------------------------------------------------------- #
# VERIFY (do not redo): power_log + startup_log already synced
# --------------------------------------------------------------------------- #


class TestSiblingRawTablesAlreadySynced:
    """US-453 acceptance: power_log/startup_log already synced -- verify only."""

    def test_powerLogAlreadyDeltaSynced(self) -> None:
        """power_log joined the delta set in US-412 (F-101) -- unchanged."""
        assert sync_log.PK_COLUMN['power_log'] == 'id'
        assert 'power_log' in sync_log.DELTA_SYNC_TABLES

    def test_startupLogAlreadySnapshotSynced(self) -> None:
        """startup_log rides the natural-key snapshot path from US-416/417."""
        assert isSnapshotSyncTable('startup_log')
        assert 'startup_log' in sync_log.snapshotSyncTables()
