################################################################################
# File Name: test_startup_log_clock_quality.py
# Purpose/Description: US-419 -- the startup_log writer (the canonical
#                      one-per-boot "first post-boot row") flags
#                      data_quality='clock_unsynced' when the boot clock is
#                      pre-NTP-sync, and never crashes.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-07-01    | Rex     | Initial -- US-419 startup_log clock-guard wiring.
# ================================================================================
################################################################################
"""US-419 startup_log clock-quality wiring tests."""
import sqlite3

from src.pi.diagnostics.boot_progress import _writeStartupLogRow, arm
from src.pi.obdii.database_schema import SCHEMA_STARTUP_LOG


def _dataQuality(dbPath: str, bootId: str) -> str | None:
    row = sqlite3.connect(dbPath).execute(
        "SELECT data_quality FROM startup_log WHERE boot_id = ?", (bootId,)
    ).fetchone()
    return None if row is None else row[0]


def test_writeStartupLogRow_unsyncedClock_flagsClockUnsynced(tmp_path) -> None:
    """
    Given: a boot whose clock the assessor deems pre-NTP-sync
    When: the startup_log row is written
    Then: the row carries data_quality='clock_unsynced' (not silent truth)
    """
    db = str(tmp_path / "obd.db")
    sqlite3.connect(db).executescript(SCHEMA_STARTUP_LOG)

    _writeStartupLogRow(
        db, "bootU", 1, "RUNNING", "ok",
        clockQualityProvider=lambda _iso: "clock_unsynced",
    )

    assert _dataQuality(db, "bootU") == "clock_unsynced"


def test_writeStartupLogRow_syncedClock_flagsFull(tmp_path) -> None:
    """A trustworthy clock records data_quality='full'."""
    db = str(tmp_path / "obd.db")
    sqlite3.connect(db).executescript(SCHEMA_STARTUP_LOG)

    _writeStartupLogRow(
        db, "bootF", 1, "RUNNING", "ok",
        clockQualityProvider=lambda _iso: "full",
    )

    assert _dataQuality(db, "bootF") == "full"


def test_writeStartupLogRow_defaultProvider_doesNotCrash(tmp_path) -> None:
    """
    The default (real) assessor path: on a dev box timedatectl is absent
    (NTP undeterminable) and 'now' is well past the sanity floor, so the row
    is 'full' -- and critically, the write does not crash.
    """
    db = str(tmp_path / "obd.db")
    sqlite3.connect(db).executescript(SCHEMA_STARTUP_LOG)

    _writeStartupLogRow(db, "bootD", 1, "RUNNING", "ok")

    assert _dataQuality(db, "bootD") == "full"


def test_arm_threadsClockProviderIntoRow(tmp_path) -> None:
    """arm() (the boot-time entry point) forwards the clock provider."""
    db = str(tmp_path / "obd.db")
    sqlite3.connect(db).executescript(SCHEMA_STARTUP_LOG)

    arm(
        filePath=str(tmp_path / "boot_progress"),
        dbPath=db,
        bootId="bootArm",
        nasArchiveDir=str(tmp_path / "nas"),
        nasArchiveEnabled=False,
        clockQualityProvider=lambda _iso: "clock_unsynced",
    )

    assert _dataQuality(db, "bootArm") == "clock_unsynced"


def test_ensureStartupLogDataQuality_backfillsLegacyTable(tmp_path) -> None:
    """A legacy startup_log without data_quality gains it, idempotently."""
    from src.pi.obdii.database_schema import ensureStartupLogDataQuality

    db = str(tmp_path / "legacy.db")
    # Legacy table: the pre-US-419 shape (no data_quality column).
    sqlite3.connect(db).executescript(
        "CREATE TABLE startup_log ("
        "  boot_id TEXT PRIMARY KEY,"
        "  recorded_at TEXT NOT NULL"
        ");"
    )
    conn = sqlite3.connect(db)
    try:
        assert ensureStartupLogDataQuality(conn) is True   # added
        assert ensureStartupLogDataQuality(conn) is False  # idempotent
    finally:
        conn.close()

    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(startup_log)")}
    assert "data_quality" in cols
