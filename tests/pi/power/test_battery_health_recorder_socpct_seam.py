################################################################################
# File Name: test_battery_health_recorder_socpct_seam.py
# Purpose/Description: US-309 (BL-013 Option A Step 1) -- exercises the optional
#                      startSocPct / endSocPct kwargs added to
#                      BatteryHealthRecorder.startDrainEvent + endDrainEvent.
#                      When kwargs are None (legacy callers), dual-write VCELL
#                      behavior is preserved (US-289 contract).  When set, the
#                      SOC% value is written to start_soc / end_soc while
#                      start_vcell_v / end_vcell_v keep the VCELL voltage.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-09
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-09    | Rex (US-309) | Initial -- 4 tests for the SocPct seam,
#                               2 legacy-preserved + 2 SOC% override paths.
# ================================================================================
################################################################################

"""Tests for the US-309 SOC% seam in :mod:`src.pi.power.battery_health`.

The recorder gains optional ``startSocPct`` / ``endSocPct`` kwargs paired
with the existing positional ``startSoc`` / ``endSoc`` arguments.  When
the kwargs are omitted (the current production caller path -- the
PowerDownOrchestrator's 4 sites that pass VCELL voltage), dual-write
VCELL behavior is preserved bit-for-bit (US-289 contract; lock-down
tests in test_battery_health_log_columns.py).  When the kwargs are
explicitly set, the SOC% value lands in ``start_soc`` / ``end_soc``
while ``start_vcell_v`` / ``end_vcell_v`` continue to hold the VCELL
voltage from ``startSoc`` / ``endSoc``.

Step 1 of the BL-013 Option A migration: lands the API seam without any
behavior change at production callers.  Step 2 (B-060) wires
:meth:`UpsMonitor.getBatteryPercentage` through the orchestrator.
Step 3 (B-061) drops the legacy ``start_soc`` / ``end_soc`` columns
once analytics consumers have migrated to the vcell columns.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.power.battery_health import (
    BATTERY_HEALTH_LOG_TABLE,
    BatteryHealthRecorder,
)


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """Initialized ObdDatabase backed by a fresh file (WAL off for tests)."""
    db = ObdDatabase(str(tmp_path / "test_bhl_socpct_seam.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def recorder(freshDb: ObdDatabase) -> BatteryHealthRecorder:
    return BatteryHealthRecorder(database=freshDb)


# ================================================================================
# startDrainEvent SOC% seam
# ================================================================================


class TestStartDrainEventSocPctSeam:
    """``startSocPct`` kwarg routes the SOC% value to ``start_soc``."""

    def test_legacyBehaviorPreserved_whenStartSocPctOmitted(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        """Omitting startSocPct: start_soc + start_vcell_v BOTH carry VCELL.

        This is the production-caller path (PowerDownOrchestrator passes
        VCELL voltage as ``startSoc``).  US-289 dual-write contract must
        hold bit-for-bit so the lock-down tests in
        test_battery_health_log_columns.py keep passing.
        """
        drainId = recorder.startDrainEvent(startSoc=4.12)

        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT start_soc, start_vcell_v "
                f"FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()

        assert row[0] == 4.12  # start_soc == VCELL (legacy dual-write)
        assert row[1] == 4.12  # start_vcell_v == VCELL

    def test_writesSocPct_whenStartSocPctProvided(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        """startSocPct=78 lands in start_soc; start_vcell_v keeps VCELL.

        The seam: start_soc finally holds an actual SOC% value (0-100)
        while start_vcell_v continues to hold the LiPo cell voltage from
        ``startSoc``.  Step 2 (B-060) will wire
        ``UpsMonitor.getBatteryPercentage()`` here.
        """
        drainId = recorder.startDrainEvent(
            startSoc=4.12,
            startSocPct=78,
        )

        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT start_soc, start_vcell_v "
                f"FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()

        assert row[0] == 78  # start_soc == SOC%
        assert row[1] == 4.12  # start_vcell_v == VCELL


# ================================================================================
# endDrainEvent SOC% seam
# ================================================================================


class TestEndDrainEventSocPctSeam:
    """``endSocPct`` kwarg routes the SOC% value to ``end_soc``."""

    def test_legacyBehaviorPreserved_whenEndSocPctOmitted(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        """Omitting endSocPct: end_soc + end_vcell_v BOTH carry VCELL.

        Same dual-write contract as the start path; preserved at all
        existing production call sites (PowerDownOrchestrator's 3
        ``_closeDrainEvent`` invokers).
        """
        drainId = recorder.startDrainEvent(startSoc=4.12)
        recorder.endDrainEvent(drainEventId=drainId, endSoc=3.42)

        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_soc, end_vcell_v "
                f"FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()

        assert row[0] == 3.42  # end_soc == VCELL (legacy dual-write)
        assert row[1] == 3.42  # end_vcell_v == VCELL

    def test_writesSocPct_whenEndSocPctProvided(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        """endSocPct=12 lands in end_soc; end_vcell_v keeps VCELL.

        The seam: end_soc finally holds an actual SOC% value (0-100).
        """
        drainId = recorder.startDrainEvent(startSoc=4.12)
        recorder.endDrainEvent(
            drainEventId=drainId,
            endSoc=3.42,
            endSocPct=12,
        )

        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_soc, end_vcell_v "
                f"FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()

        assert row[0] == 12  # end_soc == SOC%
        assert row[1] == 3.42  # end_vcell_v == VCELL
