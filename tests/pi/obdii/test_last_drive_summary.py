################################################################################
# File Name: test_last_drive_summary.py
# Purpose/Description: US-505 tests for the last-drive-summary producer.  The
#   idle-home card rendered "No recent drive" PERMANENTLY because the emitter
#   reports driveId=None whenever a drive is not actively recording and no
#   last-drive producer existed at all.  This suite pins the producer that
#   supplies the real fact.
#
#   Honest-instrument, load-bearing: an absent DB, a missing/unreadable
#   drive_summary table, an empty table, or a non-integer drive id all resolve
#   to the UNKNOWN summary -- which renders the SAME honest "No recent drive"
#   the card shows today.  The bug being fixed is a missing fact, so the fix may
#   never manufacture one.
#
#   B-104 boundary: the producer reads Pi-LOCAL drive_summary only (drive id +
#   drive-start wall time).  It computes NO derived vehicle analytics -- those
#   are the server's authority since the Pi-side drive_statistics table was
#   retired (US-351), and re-deriving them here would rebuild exactly what that
#   story deleted.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Ralph (Rex)  | Initial -- US-505 last-drive producer.
# ================================================================================
################################################################################

"""US-505: the last-drive summary is real, Pi-local, and honestly unknown."""

import sqlite3
from contextlib import contextmanager

import pytest

from pi.obdii.drive_summary import SCHEMA_DRIVE_SUMMARY
from pi.obdii.last_drive_summary import (
    LAST_DRIVE_DATA_SOURCE,
    LastDriveSummary,
    computeLastDriveSummary,
    readLastDriveSummary,
)


class _FakeDatabase:
    """Minimal stand-in for the orchestrator database handle.

    Exposes the one method the producer contracts on -- ``connect()`` as a
    context manager yielding a DB-API connection.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @contextmanager
    def connect(self):  # noqa: ANN202 -- test double
        yield self._conn


class _ExplodingDatabase:
    """A handle whose connect() raises -- locked file / mid-migration DB."""

    @contextmanager
    def connect(self):  # noqa: ANN202 -- test double
        raise sqlite3.OperationalError("database is locked")
        yield  # pragma: no cover -- unreachable, keeps this a generator


def _db(withTable: bool = True) -> _FakeDatabase:
    conn = sqlite3.connect(":memory:")
    if withTable:
        conn.execute(SCHEMA_DRIVE_SUMMARY)
    return _FakeDatabase(conn)


def _insert(
    database: _FakeDatabase,
    driveId: int,
    startedAt: str | None = "2026-08-02T09:15:00Z",
    dataSource: str = LAST_DRIVE_DATA_SOURCE,
) -> None:
    with database.connect() as conn:
        conn.execute(
            "INSERT INTO drive_summary "
            "(drive_id, drive_start_timestamp, data_source) VALUES (?, ?, ?)",
            (driveId, startedAt, dataSource),
        )


# ================================================================================
# readLastDriveSummary -- the real Pi-local read
# ================================================================================


def test_readLastDriveSummary_noDatabase_returnsUnknown():
    """
    Given: no database handle (bench / not yet built in the boot order)
    When: the last-drive summary is read
    Then: the honest unknown summary comes back rather than a raise
    """
    result = readLastDriveSummary(database=None)

    assert result.driveId is None
    assert result.startedAtTs is None
    assert result.isKnown is False


def test_readLastDriveSummary_emptyTable_returnsUnknown():
    """
    Given: a drive_summary table that exists but holds no drives
    When: the last-drive summary is read
    Then: unknown -- a fresh Pi has genuinely never recorded a drive
    """
    result = readLastDriveSummary(database=_db())

    assert result.isKnown is False


def test_readLastDriveSummary_oneRealDrive_returnsIdAndStartTime():
    """
    Given: one real recorded drive in drive_summary
    When: the last-drive summary is read
    Then: the real drive id + drive-start wall time come back
    """
    database = _db()
    _insert(database, 35, "2026-08-02T09:15:00Z")

    result = readLastDriveSummary(database=database)

    assert result.driveId == 35
    assert result.startedAtTs == "2026-08-02T09:15:00Z"
    assert result.isKnown is True


def test_readLastDriveSummary_manyDrives_returnsHighestDriveId():
    """
    Given: several recorded drives, inserted out of order
    When: the last-drive summary is read
    Then: the HIGHEST drive_id wins (drive_id is monotonic per drive_id.py),
          never merely the last row inserted
    """
    database = _db()
    _insert(database, 12, "2026-07-01T08:00:00Z")
    _insert(database, 34, "2026-08-01T08:00:00Z")
    _insert(database, 20, "2026-07-15T08:00:00Z")

    result = readLastDriveSummary(database=database)

    assert result.driveId == 34
    assert result.startedAtTs == "2026-08-01T08:00:00Z"


def test_readLastDriveSummary_simulatedDriveOnly_returnsUnknown():
    """
    Given: the only drives on the box are physics_sim / replay rows
    When: the last-drive summary is read
    Then: unknown -- presenting a simulated drive to the operator as "your last
          drive" would be a fabrication in the only terms the panel has
    """
    database = _db()
    _insert(database, 41, "2026-08-02T09:15:00Z", dataSource="physics_sim")
    _insert(database, 42, "2026-08-02T10:15:00Z", dataSource="replay")

    result = readLastDriveSummary(database=database)

    assert result.isKnown is False


def test_readLastDriveSummary_simulatedNewerThanReal_returnsTheRealDrive():
    """
    Given: a simulated drive with a HIGHER drive_id than the last real drive
    When: the last-drive summary is read
    Then: the real drive is reported -- the sim row cannot mask it, and it
          cannot be relabelled as real either
    """
    database = _db()
    _insert(database, 30, "2026-08-01T07:00:00Z")
    _insert(database, 44, "2026-08-02T11:00:00Z", dataSource="physics_sim")

    result = readLastDriveSummary(database=database)

    assert result.driveId == 30
    assert result.startedAtTs == "2026-08-01T07:00:00Z"


def test_readLastDriveSummary_missingTable_returnsUnknownNotRaise():
    """
    Given: a DB with no drive_summary table at all (pre-migration / fresh)
    When: the last-drive summary is read
    Then: unknown, and no exception escapes into the card-emit loop
    """
    result = readLastDriveSummary(database=_db(withTable=False))

    assert result.isKnown is False


def test_readLastDriveSummary_unreadableDatabase_returnsUnknownNotRaise():
    """
    Given: a database handle whose connect() raises (locked file)
    When: the last-drive summary is read
    Then: unknown, swallowed -- a dashboard read never crashes the loop
    """
    result = readLastDriveSummary(database=_ExplodingDatabase())

    assert result.isKnown is False


def test_readLastDriveSummary_blankStartTimestamp_stillReportsTheDrive():
    """
    Given: a real recorded drive whose start timestamp is blank
    When: the last-drive summary is read
    Then: the drive id is still reported with startedAtTs=None -- the drive
          genuinely happened, so hiding it would lose a real fact; the display
          degrades to "age unknown" on the missing half only

    Blank rather than NULL on purpose: drive_start_timestamp is
    ``NOT NULL DEFAULT (strftime(...))``, so a true NULL is unreachable through
    the real table. An empty string satisfies NOT NULL and IS reachable (a
    foreign/imported row), which makes it the honest version of this test.
    """
    database = _db()
    _insert(database, 51, startedAt="")

    result = readLastDriveSummary(database=database)

    assert result.driveId == 51
    assert result.startedAtTs is None
    assert result.isKnown is True


def test_driveSummarySchema_forbidsNullStartTimestamp():
    """
    Given: the real drive_summary schema
    When: a row is inserted with an explicit NULL start timestamp
    Then: the NOT NULL constraint rejects it -- documenting WHY the test above
          uses a blank string, so a future reader does not "fix" it back into an
          unreachable NULL case
    """
    database = _db()

    with pytest.raises(sqlite3.IntegrityError):
        with database.connect() as conn:
            conn.execute(
                "INSERT INTO drive_summary (drive_id, drive_start_timestamp, "
                "data_source) VALUES (?, NULL, ?)",
                (52, LAST_DRIVE_DATA_SOURCE),
            )


# ================================================================================
# computeLastDriveSummary -- the pure half
# ================================================================================


def test_computeLastDriveSummary_noRows_returnsUnknown():
    """
    Given: no candidate rows
    When: the summary is computed
    Then: unknown
    """
    assert computeLastDriveSummary(rows=[]).isKnown is False


def test_computeLastDriveSummary_picksHighestDriveIdAcrossRows():
    """
    Given: rows out of drive_id order
    When: the summary is computed
    Then: the highest drive_id is selected (the pure half does not lean on
          SQL ordering to be correct)
    """
    rows = [
        {"drive_id": 7, "drive_start_timestamp": "2026-07-01T08:00:00Z"},
        {"drive_id": 19, "drive_start_timestamp": "2026-07-20T08:00:00Z"},
        {"drive_id": 11, "drive_start_timestamp": "2026-07-10T08:00:00Z"},
    ]

    result = computeLastDriveSummary(rows=rows)

    assert result.driveId == 19
    assert result.startedAtTs == "2026-07-20T08:00:00Z"


def test_computeLastDriveSummary_nonIntegerDriveId_returnsUnknown():
    """
    Given: a row whose drive id is not a usable integer
    When: the summary is computed
    Then: unknown -- "Drive None" / "Drive abc" on the panel is worse than the
          honest absence it would replace
    """
    rows = [{"drive_id": None, "drive_start_timestamp": "2026-07-01T08:00:00Z"}]

    assert computeLastDriveSummary(rows=rows).isKnown is False


def test_computeLastDriveSummary_blankStartTimestamp_normalizesToNone():
    """
    Given: a row whose start timestamp is a blank string
    When: the summary is computed
    Then: startedAtTs is None, never the empty string -- the display's
          "age unknown" branch keys on null
    """
    rows = [{"drive_id": 8, "drive_start_timestamp": "   "}]

    result = computeLastDriveSummary(rows=rows)

    assert result.driveId == 8
    assert result.startedAtTs is None


# ================================================================================
# State payload -- the shape the emitter embeds
# ================================================================================


def test_toStatePayload_unknownSummary_isNone():
    """
    Given: the unknown summary
    When: it is converted for the state file
    Then: None -- the card's "No recent drive" branch keys on the absence of a
          lastDrive block, so unknown must not become a block full of nulls
    """
    assert LastDriveSummary().toStatePayload() is None


def test_toStatePayload_knownSummary_carriesIdAndStartTs():
    """
    Given: a known last-drive summary
    When: it is converted for the state file
    Then: exactly the two real facts, under the display's key names
    """
    payload = LastDriveSummary(driveId=35, startedAtTs="2026-08-02T09:15:00Z")

    assert payload.toStatePayload() == {
        "driveId": 35,
        "startedAtTs": "2026-08-02T09:15:00Z",
    }
