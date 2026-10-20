################################################################################
# File Name: test_dtc_last_known.py
# Purpose/Description: US-752 (F-123) tests for the last-known DTC reader and the
#   Mode-04 clear watermark. Runs against a REAL ObdDatabase so the rows the
#   reader selects are the rows the capture path actually persists: one entry
#   per code (newest wins), real-origin rows only, `asOfTs` from
#   last_seen_timestamp, None when never read, and -- the non-sticky half --
#   nothing remembered from before a clear.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-14    | Ralph (Rex)  | Initial -- US-752 last-known reader + watermark.
# 2026-10-20    | Ralph (Rex)  | US-897-a3: readFirstSeenByCode (first seen since
#               |              | the last clear, canonical UTC passed through).
# ================================================================================
################################################################################

"""Tests for :mod:`pi.obdii.dtc_last_known` (US-752)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from pi.obdii.database import ObdDatabase
from pi.obdii.dtc_last_known import (
    LAST_KNOWN_SOURCE,
    readFirstSeenByCode,
    readLastKnownDtcs,
    recordClearWatermark,
)

# Before any plausible wall clock, so a watermark stamped "now" is always later.
_OLD = "2026-01-01T08:00:00Z"
_OLDER = "2026-01-01T07:00:00Z"


@pytest.fixture()
def db(tmp_path: Path) -> ObdDatabase:
    database = ObdDatabase(str(tmp_path / "last_known.db"), walMode=False)
    database.initialize()
    return database


def _seed(
    database: ObdDatabase,
    code: str,
    *,
    status: str = "stored",
    lastSeen: str = _OLD,
    source: str = "real",
    description: str = "desc",
    driveId: int | None = None,
) -> None:
    with database.connect() as conn:
        conn.execute(
            "INSERT INTO dtc_log (dtc_code, description, status, first_seen_timestamp, "
            "last_seen_timestamp, drive_id, data_source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (code, description, status, lastSeen, lastSeen, driveId, source),
        )


def _statuses(database: ObdDatabase) -> list[tuple[str, str]]:
    with database.connect() as conn:
        return [
            (r[0], r[1])
            for r in conn.execute("SELECT dtc_code, status FROM dtc_log ORDER BY id")
        ]


def test_readLastKnownDtcs_neverRead_returnsNone(db):
    """
    Given: a fresh install -- no dtc_log rows
    When: last-known is read
    Then: None, so the resting state keeps the true "not read" absence
    """
    assert readLastKnownDtcs(db) is None


def test_readLastKnownDtcs_noDatabase_returnsNone():
    """No database wired -> nothing to remember (never a crash)."""
    assert readLastKnownDtcs(None) is None


def test_readLastKnownDtcs_storedAndPending_datedFromLastSeen(db):
    """
    Given: a stored and a pending code persisted by earlier reads
    When: last-known is read
    Then: both present newest-first with their own lastSeenTs, asOfTs is the
          newest last_seen_timestamp, provenance is dtc_log
    """
    _seed(db, "P0443", lastSeen=_OLD, description="EVAP purge", driveId=None)
    _seed(db, "P0400", status="pending", lastSeen=_OLDER, driveId=7)

    got = readLastKnownDtcs(db)

    assert got == {
        "codes": [
            {
                "code": "P0443",
                "status": "stored",
                "description": "EVAP purge",
                "driveId": None,
                "lastSeenTs": _OLD,
            },
            {
                "code": "P0400",
                "status": "pending",
                "description": "desc",
                "driveId": 7,
                "lastSeenTs": _OLDER,
            },
        ],
        "asOfTs": _OLD,
        "source": LAST_KNOWN_SOURCE,
    }


def test_readLastKnownDtcs_sameCodeOnManyReads_appearsOnce_newestWins(db):
    """Every key-on read inserts fresh rows -- the resting view lists a code ONCE."""
    _seed(db, "P0443", lastSeen=_OLDER)
    _seed(db, "P0443", lastSeen=_OLD)

    got = readLastKnownDtcs(db)

    assert [c["code"] for c in got["codes"]] == ["P0443"]
    assert got["codes"][0]["lastSeenTs"] == _OLD


def test_readLastKnownDtcs_nonRealRows_areNotSomethingTheCarReported(db):
    """Replay / fixture rows never become remembered codes."""
    _seed(db, "P0301", source="replay")
    _seed(db, "P0302", source="fixture")

    assert readLastKnownDtcs(db) is None


def test_readLastKnownDtcs_unreadableLog_returnsNone():
    """A database that cannot be opened degrades to 'not read', never raises."""

    class _Broken:
        def connect(self):
            raise OSError("disk gone")

    assert readLastKnownDtcs(_Broken()) is None


def test_recordClearWatermark_hidesEveryPreClearCode(db):
    """
    Given: two remembered codes
    When: a Mode-04 clear records its watermark
    Then: one `cleared` row per code is written and nothing is remembered --
          last-known does NOT outlive the clear
    """
    _seed(db, "P0443")
    _seed(db, "P0400")

    written = recordClearWatermark(db)

    assert written == 2
    assert sorted(s for s in _statuses(db) if s[1] == "cleared") == [
        ("P0400", "cleared"),
        ("P0443", "cleared"),
    ]
    assert readLastKnownDtcs(db) is None


def test_readLastKnownDtcs_codeReadAfterTheClear_isRememberedAgain(db):
    """A code that re-sets and is logged by a later read comes back -- alone."""
    _seed(db, "P0443")
    _seed(db, "P0400")
    recordClearWatermark(db)
    _seed(db, "P0443", lastSeen=_OLD)  # a later read (higher id) found it again

    got = readLastKnownDtcs(db)

    assert [c["code"] for c in got["codes"]] == ["P0443"]


def test_recordClearWatermark_nothingRemembered_writesNothing(db):
    assert recordClearWatermark(db) == 0
    assert _statuses(db) == []


# ---- US-897-a3: readFirstSeenByCode ----------------------------------------


def _seedRow(
    database: ObdDatabase,
    code: str,
    *,
    firstSeen: str,
    lastSeen: str | None = None,
    status: str = "stored",
    source: str = "real",
) -> int:
    with database.connect() as conn:
        cur = conn.execute(
            "INSERT INTO dtc_log (dtc_code, description, status, first_seen_timestamp, "
            "last_seen_timestamp, drive_id, data_source) VALUES (?, '', ?, ?, ?, NULL, ?)",
            (code, status, firstSeen, lastSeen or firstSeen, source),
        )
        return int(cur.lastrowid)


def _clearAt(database: ObdDatabase, code: str, ts: str) -> None:
    _seedRow(database, code, firstSeen=ts, status="cleared")


def test_readFirstSeenByCode_repeatedKeyOnRows_returnsTheEarliest(db):
    """
    Given: three key-on reads logged P0400 (a row each), plus one P0443 row
    When: first-seen is read
    Then: each code maps to its MIN first_seen_timestamp
    """
    _seedRow(db, "P0400", firstSeen="2026-09-12T10:00:00Z")
    _seedRow(db, "P0400", firstSeen="2026-09-04T13:20:05Z")
    _seedRow(db, "P0400", firstSeen="2026-09-10T09:00:00Z")
    _seedRow(db, "p0443", firstSeen="2026-09-06T07:00:00Z", status="pending")

    assert readFirstSeenByCode(db) == {
        "P0400": "2026-09-04T13:20:05Z",
        "P0443": "2026-09-06T07:00:00Z",
    }


def test_readFirstSeenByCode_rowsBeforeTheClear_areIgnored(db):
    """
    Given: P0400 first seen 09-04, a clear at 09-08, P0400 seen again 09-10
    When: first-seen is read
    Then: 09-10 -- the code's age restarts at the clear that wiped it
    """
    _seedRow(db, "P0400", firstSeen="2026-09-04T13:20:05Z")
    _seedRow(db, "P0443", firstSeen="2026-09-05T13:20:05Z")
    _clearAt(db, "P0400", "2026-09-08T12:00:00Z")
    _seedRow(db, "P0400", firstSeen="2026-09-10T08:15:00Z")

    assert readFirstSeenByCode(db) == {"P0400": "2026-09-10T08:15:00Z"}


def test_readFirstSeenByCode_nonRealRows_areIgnored(db):
    """Replay / fixture rows are not something the car reported."""
    _seedRow(db, "P0400", firstSeen="2026-09-01T00:00:00Z", source="fixture")
    _seedRow(db, "P0400", firstSeen="2026-09-02T00:00:00Z", source="replay")
    _seedRow(db, "P0400", firstSeen="2026-09-10T00:00:00Z")
    _seedRow(db, "P0302", firstSeen="2026-09-01T00:00:00Z", source="physics_sim")

    assert readFirstSeenByCode(db) == {"P0400": "2026-09-10T00:00:00Z"}


def test_readFirstSeenByCode_nonRealClearRow_isNotAWatermark(db):
    """A fixture `cleared` row never hides the car's real codes."""
    _seedRow(db, "P0400", firstSeen="2026-09-04T00:00:00Z")
    _seedRow(db, "P0400", firstSeen="2026-09-08T00:00:00Z", status="cleared", source="fixture")

    assert readFirstSeenByCode(db) == {"P0400": "2026-09-04T00:00:00Z"}


def test_readFirstSeenByCode_preClearRowBumpedByLastSeen_isIgnored(db):
    """
    Given: a pre-clear P0400 row the drive-scoped upsert re-read AFTER the clear
           (last_seen bumped past the marker, id still below it)
    When: first-seen is read
    Then: that row is ignored -- its first_seen predates the clear (Atlas G-a1)
    """
    preClearId = _seedRow(db, "P0400", firstSeen="2026-09-04T13:20:05Z")
    _clearAt(db, "P0400", "2026-09-08T12:00:00Z")
    with db.connect() as conn:
        conn.execute(
            "UPDATE dtc_log SET last_seen_timestamp = ? WHERE id = ?",
            ("2026-09-12T00:00:00Z", preClearId),
        )

    assert readFirstSeenByCode(db) == {}

    _seedRow(db, "P0400", firstSeen="2026-09-10T08:15:00Z")
    assert readFirstSeenByCode(db) == {"P0400": "2026-09-10T08:15:00Z"}


def test_readFirstSeenByCode_underChicagoTz_returnsTheSameUtcString(db, monkeypatch):
    """
    Given: the process local zone is America/Chicago (Atlas Q5)
    When: first-seen is read
    Then: the stored canonical UTC string comes back byte-for-byte -- no local
          conversion anywhere on the path
    """
    _seedRow(db, "P0400", firstSeen="2026-09-04T13:20:05Z")
    utcResult = readFirstSeenByCode(db)

    monkeypatch.setenv("TZ", "America/Chicago")
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        chicagoResult = readFirstSeenByCode(db)
    finally:
        monkeypatch.delenv("TZ")
        if hasattr(time, "tzset"):
            time.tzset()

    assert os.environ.get("TZ") is None
    assert chicagoResult == utcResult == {"P0400": "2026-09-04T13:20:05Z"}


def test_readFirstSeenByCode_nothingLogged_returnsEmpty(db):
    assert readFirstSeenByCode(db) == {}


def test_readFirstSeenByCode_noDatabase_returnsEmpty():
    assert readFirstSeenByCode(None) == {}


def test_readFirstSeenByCode_unreadableLog_returnsEmpty():
    """A log that cannot be read degrades to 'no first-seen', never raises."""

    class _Broken:
        def connect(self):
            raise OSError("disk gone")

    assert readFirstSeenByCode(_Broken()) == {}
