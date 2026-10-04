################################################################################
# File Name: battery_verdict_fixture.py
# Purpose/Description: ARCH-065 -- one in-memory database shaped like the Pi's
#   for every battery-health verdict test.  The verdict reads THREE kinds of
#   fact (the current pack's monthly test and calibration rows in
#   battery_health_log, and the at-home DELIVERED shutdown syncs in
#   startup_log), so each test file building its own partial fake is how the
#   US-617 class of bug starts: a fixture that quietly stops writing a column
#   the query filters on.  One builder, real DDL, used everywhere.
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a)  | ARCH-065 T7: created.
# 2026-10-03    | Atlas (ARCH-065a)  | T7 fix 1: addFloorEnded (Ruling 13); test
#                                      end/window values may be NULL (Ruling 16).
# ================================================================================
################################################################################

"""Shared ARCH-065 verdict fixture (not a test module)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from src.pi.obdii.database_schema import SCHEMA_STARTUP_LOG
from src.pi.power.battery_health import (
    DRAIN_TRIGGER_CALIBRATION,
    DRAIN_TRIGGER_KEYOFF,
    DRAIN_TRIGGER_MONTHLY_TEST,
    SCHEMA_BATTERY_HEALTH_LOG,
)
from src.pi.power.battery_health_verdict import VERDICT_REPLACE
from src.pi.power.power_watch.contract import OutcomeKind

ISO = "%Y-%m-%dT%H:%M:%SZ"

#: The pack every helper writes unless told otherwise.
PACK = "18650-pack"

#: A monthly test row's measured values: 4.07 V at the window end, 0.04 mV/s.
TEST_RATE_MV_S = -0.04
TEST_END_VCELL_V = 4.07
TEST_WINDOW_END_S = 660

#: A calibration of 5 h to the floor at the same rate as the test -> T = 18000 s.
CAL_T_FLOOR_S = 18000

#: battery_health_log columns this fixture WRITES.  Declared once; the US-707
#: guard in test_card_battery_health_verdict_wiring.py checks it against the
#: verdict's own SQL.
BATTERY_LOG_COLUMNS: tuple[str, ...] = (
    "start_timestamp", "drain_trigger", "cell_epoch", "drain_rate_mv_s",
    "end_vcell_v", "window_end_s", "t_floor_s", "verdict",
)

#: startup_log columns this fixture WRITES.
STARTUP_LOG_COLUMNS: tuple[str, ...] = (
    "boot_id", "prior_boot_sync_outcome", "prior_boot_sync_started_at",
    "prior_boot_sync_ended_at",
)


class VerdictDatabase:
    """battery_health_log + startup_log with the real DDL, in memory.

    ``connect()`` yields one shared connection and commits on exit, like
    ``ObdDatabase.connect`` -- so the verdict's history write is observable.
    """

    def __init__(self, now: datetime) -> None:
        self.now = now
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.execute(SCHEMA_BATTERY_HEALTH_LOG)
        self.conn.execute(SCHEMA_STARTUP_LOG)
        self.conn.commit()
        self._boots = 0

    def iso(self, daysAgo: float) -> str:
        return (self.now - timedelta(days=daysAgo)).strftime(ISO)

    def _insertDrain(self, values: dict) -> int:
        cols = ", ".join(values)
        cur = self.conn.execute(
            f"INSERT INTO battery_health_log ({cols}) VALUES "
            f"({', '.join('?' * len(values))})",
            tuple(values.values()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def addTest(
        self, daysAgo: float, *, cellEpoch: str = PACK,
        drainRateMvS: float | None = TEST_RATE_MV_S,
        endVcellV: float | None = TEST_END_VCELL_V,
        windowEndS: int | None = TEST_WINDOW_END_S,
    ) -> int:
        """A monthly-test row; ``drainRateMvS=None`` is an UNCOUNTED test."""
        return self._insertDrain({
            "start_timestamp": self.iso(daysAgo),
            "drain_trigger": DRAIN_TRIGGER_MONTHLY_TEST,
            "cell_epoch": cellEpoch,
            "drain_rate_mv_s": drainRateMvS,
            "end_vcell_v": endVcellV,
            "window_end_s": windowEndS,
        })

    def addCalibration(
        self, daysAgo: float, *, cellEpoch: str = PACK,
        tFloorS: int = CAL_T_FLOOR_S, drainRateMvS: float = TEST_RATE_MV_S,
    ) -> int:
        return self._insertDrain({
            "start_timestamp": self.iso(daysAgo),
            "drain_trigger": DRAIN_TRIGGER_CALIBRATION,
            "cell_epoch": cellEpoch,
            "drain_rate_mv_s": drainRateMvS,
            "t_floor_s": tFloorS,
        })

    def addFloorEnded(
        self, daysAgo: float, *, cellEpoch: str = PACK,
        trigger: str = DRAIN_TRIGGER_KEYOFF,
    ) -> int:
        """A drain the reserve floor ended at home: the finaliser stamped replace."""
        return self._insertDrain({
            "start_timestamp": self.iso(daysAgo),
            "drain_trigger": trigger,
            "cell_epoch": cellEpoch,
            "verdict": VERDICT_REPLACE,
        })

    def addKeyoff(self, daysAgo: float, *, cellEpoch: str | None = PACK) -> int:
        return self._insertDrain({
            "start_timestamp": self.iso(daysAgo),
            "drain_trigger": DRAIN_TRIGGER_KEYOFF,
            "cell_epoch": cellEpoch,
        })

    def addJobs(
        self, count: int, *, syncSeconds: float = 100.0,
        outcome: str = OutcomeKind.DELIVERED.name,
    ) -> None:
        """``count`` boots, each landing one prior-boot shutdown sync."""
        for _ in range(count):
            self._boots += 1
            started = self.now - timedelta(days=self._boots)
            ended = started + timedelta(seconds=syncSeconds)
            self.conn.execute(
                "INSERT INTO startup_log (boot_id, prior_boot_sync_outcome, "
                "prior_boot_sync_started_at, prior_boot_sync_ended_at) "
                "VALUES (?, ?, ?, ?)",
                (f"boot{self._boots:04d}", outcome,
                 started.strftime(ISO), ended.strftime(ISO)),
            )
        self.conn.commit()

    def storedVerdict(self, drainEventId: int) -> str | None:
        return self.conn.execute(
            "SELECT verdict FROM battery_health_log WHERE drain_event_id = ?",
            (drainEventId,),
        ).fetchone()[0]

    @contextmanager
    def connect(self):
        yield self.conn
        self.conn.commit()


def goodPack(now: datetime, *, testDaysAgo: float = 1.0) -> VerdictDatabase:
    """A pack with a fresh counted test, a calibration and ten 100 s syncs.

    T = 18000 s; J = smoothingSec + 100 + 4 s -> ``good`` by a wide margin.
    """
    db = VerdictDatabase(now)
    db.addCalibration(testDaysAgo + 10)
    db.addTest(testDaysAgo)
    db.addJobs(10)
    return db
