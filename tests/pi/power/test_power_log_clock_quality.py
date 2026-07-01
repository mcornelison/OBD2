################################################################################
# File Name: test_power_log_clock_quality.py
# Purpose/Description: US-419 (F-080) -- the power_log writers stamp a
#                      data_quality clock-drift flag.  power_log writes can fire
#                      in the early-boot window before systemd-timesyncd
#                      disciplines the clock, so a floor-only (subprocess-free)
#                      guard flags 'clock_unsynced' rather than persisting a
#                      dead-RTC timestamp as truth.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-07-01    | Rex     | Initial -- US-419 power_log clock-guard wiring.
# ================================================================================
################################################################################
"""US-419 power_log clock-quality wiring tests."""
from __future__ import annotations

import sqlite3

from src.pi.power import power_db
from src.pi.power.types import PowerReading, PowerSource

_UNSYNCED = "clock_unsynced"
_FULL = "full"


class _FakeDatabase:
    """ObdDatabase stand-in whose power_log carries the US-419 data_quality col."""

    def __init__(self, path: str) -> None:
        self.dbPath = path
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE power_log ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  timestamp DATETIME NOT NULL,"
                "  event_type TEXT NOT NULL,"
                "  power_source TEXT NOT NULL,"
                "  on_ac_power INTEGER NOT NULL DEFAULT 1,"
                "  vcell REAL,"
                "  data_quality TEXT)"
            )

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.dbPath)
        conn.row_factory = sqlite3.Row
        return conn


def _dataQualities(db: _FakeDatabase) -> list[str | None]:
    with db.connect() as conn:
        return [r["data_quality"] for r in conn.execute("SELECT data_quality FROM power_log")]


def test_logPowerReading_unsyncedClock_flagsRow(tmp_path) -> None:
    db = _FakeDatabase(str(tmp_path / "p.db"))
    reading = PowerReading(powerSource=PowerSource.AC_POWER, onAcPower=True)

    power_db.logPowerReading(
        db, reading, "ac_power", clockQuality=lambda _iso: _UNSYNCED
    )

    assert _dataQualities(db) == [_UNSYNCED]


def test_logPowerTransition_unsyncedClock_flagsRow(tmp_path) -> None:
    db = _FakeDatabase(str(tmp_path / "p.db"))

    power_db.logPowerTransition(
        db, "transition_to_battery", None, PowerSource.BATTERY,  # type: ignore[arg-type]
        clockQuality=lambda _iso: _UNSYNCED,
    )

    assert _dataQualities(db) == [_UNSYNCED]


def test_logPowerSavingEvent_unsyncedClock_flagsRow(tmp_path) -> None:
    db = _FakeDatabase(str(tmp_path / "p.db"))

    power_db.logPowerSavingEvent(
        db, "power_saving_enabled", PowerSource.BATTERY,
        clockQuality=lambda _iso: _UNSYNCED,
    )

    assert _dataQualities(db) == [_UNSYNCED]


def test_logShutdownStage_unsyncedClock_flagsRow(tmp_path) -> None:
    db = _FakeDatabase(str(tmp_path / "p.db"))

    power_db.logShutdownStage(
        db, "stage_warning", 3.45, clockQuality=lambda _iso: _UNSYNCED,
    )

    assert _dataQualities(db) == [_UNSYNCED]


def test_logPowerReading_defaultProvider_saneClockIsFull(tmp_path) -> None:
    """Default floor-only classifier: 'now' is post-floor -> 'full', no crash."""
    db = _FakeDatabase(str(tmp_path / "p.db"))
    reading = PowerReading(powerSource=PowerSource.AC_POWER, onAcPower=True)

    power_db.logPowerReading(db, reading, "ac_power")

    assert _dataQualities(db) == [_FULL]
