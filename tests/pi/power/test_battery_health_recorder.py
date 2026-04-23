################################################################################
# File Name: test_battery_health_recorder.py
# Purpose/Description: Tests for BatteryHealthRecorder (US-217) -- opens +
#                      closes battery_health_log rows, computes runtime, and
#                      preserves close-once semantics on re-call.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-217) | Initial -- start/end + close-once tests.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.power.battery_health.BatteryHealthRecorder`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.power.battery_health import (
    BATTERY_HEALTH_LOG_TABLE,
    BatteryHealthRecorder,
    DrainEventCloseResult,
    _computeRuntimeSeconds,
)

_ISO_UTC = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """Initialized ObdDatabase backed by a fresh file (WAL off for tests)."""
    db = ObdDatabase(str(tmp_path / "test_bhl_recorder.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def recorder(freshDb: ObdDatabase) -> BatteryHealthRecorder:
    return BatteryHealthRecorder(database=freshDb)


# ================================================================================
# startDrainEvent
# ================================================================================


class TestStartDrainEvent:
    """Opening a new drain event."""

    def test_returnsMonotonicId(
        self, recorder: BatteryHealthRecorder,
    ) -> None:
        id1 = recorder.startDrainEvent(startSoc=100.0)
        id2 = recorder.startDrainEvent(startSoc=99.0)
        id3 = recorder.startDrainEvent(startSoc=98.0)
        assert id1 < id2 < id3

    def test_writesCanonicalStartTimestamp(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        drainId = recorder.startDrainEvent(startSoc=100.0)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT start_timestamp FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert _ISO_UTC.match(row[0]) is not None

    def test_defaultLoadClassIsProduction(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        drainId = recorder.startDrainEvent(startSoc=100.0)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT load_class FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] == 'production'

    def test_acceptsTestLoadClass(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        drainId = recorder.startDrainEvent(
            startSoc=100.0, loadClass='test', notes='April drill',
        )
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT load_class, notes FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] == 'test'
        assert row[1] == 'April drill'

    def test_rejectsInvalidLoadClass(
        self, recorder: BatteryHealthRecorder,
    ) -> None:
        with pytest.raises(ValueError, match='loadClass'):
            recorder.startDrainEvent(startSoc=100.0, loadClass='bogus')

    def test_startSocIsWritten(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        drainId = recorder.startDrainEvent(startSoc=72.5)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT start_soc FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] == 72.5

    def test_preCloseEndColumnsAreNull(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        drainId = recorder.startDrainEvent(startSoc=100.0)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_timestamp, end_soc, runtime_seconds, "
                f"       ambient_temp_c "
                f"FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] is None
        assert row[1] is None
        assert row[2] is None
        assert row[3] is None


# ================================================================================
# endDrainEvent
# ================================================================================


class TestEndDrainEvent:
    """Closing a drain event."""

    def test_writesEndColumns(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        drainId = recorder.startDrainEvent(startSoc=100.0)
        result = recorder.endDrainEvent(
            drainEventId=drainId, endSoc=20.0, ambientTempC=22.5,
        )
        assert result.closed is True
        assert result.drainEventId == drainId
        assert result.endSoc == 20.0
        assert _ISO_UTC.match(result.endTimestamp or '') is not None
        assert result.runtimeSeconds is not None
        assert result.runtimeSeconds >= 0

        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_timestamp, end_soc, ambient_temp_c, "
                f"       runtime_seconds "
                f"FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] == result.endTimestamp
        assert row[1] == 20.0
        assert row[2] == 22.5
        assert row[3] == result.runtimeSeconds

    def test_runtimeSecondsPositiveOnDifferentTimestamps(self) -> None:
        """Helper test: a one-hour span yields 3600 seconds."""
        runtime = _computeRuntimeSeconds(
            '2026-04-21T12:00:00Z', '2026-04-21T13:00:00Z',
        )
        assert runtime == 3600

    def test_runtimeSecondsNullOnMalformedStart(self) -> None:
        """Corrupted start_timestamp yields None (row is still closeable)."""
        runtime = _computeRuntimeSeconds(
            'corrupted', '2026-04-21T12:00:00Z',
        )
        assert runtime is None

    def test_ambientTempOptional(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        drainId = recorder.startDrainEvent(startSoc=100.0)
        recorder.endDrainEvent(drainEventId=drainId, endSoc=20.0)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_c FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] is None

    def test_unknownIdRaisesValueError(
        self, recorder: BatteryHealthRecorder,
    ) -> None:
        with pytest.raises(ValueError, match='not found'):
            recorder.endDrainEvent(drainEventId=9999, endSoc=20.0)


# ================================================================================
# Close-once semantic
# ================================================================================


class TestCloseOnceSemantic:
    """Re-calling endDrainEvent does not overwrite the original close."""

    def test_secondCloseIsNoOp(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        drainId = recorder.startDrainEvent(startSoc=100.0)
        first = recorder.endDrainEvent(drainEventId=drainId, endSoc=20.0)
        assert first.closed is True

        second = recorder.endDrainEvent(drainEventId=drainId, endSoc=5.0)
        assert second.closed is False
        # First close's values are preserved.
        assert second.endSoc == 20.0
        assert second.endTimestamp == first.endTimestamp
        assert second.runtimeSeconds == first.runtimeSeconds

        # DB state matches the first close.
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_timestamp, end_soc FROM "
                f"{BATTERY_HEALTH_LOG_TABLE} WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] == first.endTimestamp
        assert row[1] == 20.0

    def test_closeResultFields(
        self, recorder: BatteryHealthRecorder,
    ) -> None:
        """DrainEventCloseResult carries all four accessor fields."""
        drainId = recorder.startDrainEvent(startSoc=100.0)
        result = recorder.endDrainEvent(drainEventId=drainId, endSoc=20.0)
        assert isinstance(result, DrainEventCloseResult)
        assert result.drainEventId == drainId
        assert result.closed is True
        assert result.endSoc == 20.0
        assert result.endTimestamp is not None
        assert result.runtimeSeconds is not None
