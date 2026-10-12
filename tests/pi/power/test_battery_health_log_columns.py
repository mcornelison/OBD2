################################################################################
# File Name: test_battery_health_log_columns.py
# Purpose/Description: Tests for the start_vcell_v / end_vcell_v columns added
#                      to battery_health_log by US-289.  Spool Sprint 26 Story 6:
#                      the existing start_soc / end_soc columns hold VCELL
#                      voltage values (3.4-4.2V) but are misnamed + commented as
#                      SOC % (0..100).  Don't lie about column contents -- ship
#                      the renamed columns, populate both old + new during the
#                      deprecation phase, never drop the old columns mid-sprint.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-07    | Rex (US-289) | Initial -- new column tests + idempotency
#                               + writer back-compat tests + legacy-row preserve.
# ================================================================================
################################################################################

"""Tests for the US-289 start_vcell_v / end_vcell_v columns.

Two paths are exercised:

* **Fresh-install path**: a brand-new ObdDatabase.initialize() returns a
  battery_health_log with the new columns present (via the schema +
  ensureBatteryHealthLogVcellColumns idempotent helper).
* **Legacy-upgrade path**: a sqlite db carrying only the old start_soc /
  end_soc columns (simulating a pre-US-289 install) gains the new columns
  via the helper without losing existing rows.

The writer-side contract for the deprecation phase: BatteryHealthRecorder
emits each drain-event row's VCELL voltage to BOTH the old column
(start_soc / end_soc) AND the new column (start_vcell_v / end_vcell_v).
Rationale: stopCondition[1] of US-289 -- existing analytics consumers
read start_soc as voltage; renaming alone breaks them mid-deploy.  The
double-write keeps the old readers working while new writers (post-US-289
analytics + future sync schema) move to the renamed columns.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.power.battery_health import (
    BATTERY_HEALTH_LOG_TABLE,
    BatteryHealthRecorder,
    ensureBatteryHealthLogSocPctColumns,
    ensureBatteryHealthLogTable,
    ensureBatteryHealthLogVcellColumns,
)


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """Initialized ObdDatabase backed by a fresh file (WAL off for tests)."""
    db = ObdDatabase(str(tmp_path / "test_bhl_vcell.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def recorder(freshDb: ObdDatabase) -> BatteryHealthRecorder:
    return BatteryHealthRecorder(database=freshDb)


# ================================================================================
# Fresh-install: new columns present after ObdDatabase.initialize()
# ================================================================================


class TestNewColumnsPresentAfterInitialize:
    """A fresh db has both start_vcell_v and end_vcell_v after initialize()."""

    def test_startVcellColumnExists(self, freshDb: ObdDatabase) -> None:
        cols = {
            c['name']: c
            for c in freshDb.getTableInfo(BATTERY_HEALTH_LOG_TABLE)
        }
        assert 'start_vcell_v' in cols

    def test_endVcellColumnExists(self, freshDb: ObdDatabase) -> None:
        cols = {
            c['name']: c
            for c in freshDb.getTableInfo(BATTERY_HEALTH_LOG_TABLE)
        }
        assert 'end_vcell_v' in cols

    def test_startVcellIsRealNullable(self, freshDb: ObdDatabase) -> None:
        cols = {
            c['name']: c
            for c in freshDb.getTableInfo(BATTERY_HEALTH_LOG_TABLE)
        }
        # start_vcell_v is nullable so legacy rows (pre-US-289) remain valid.
        # The writer fills it; legacy readers/migrators don't break.
        assert cols['start_vcell_v']['notnull'] == 0
        assert cols['start_vcell_v']['type'].upper() == 'REAL'

    def test_endVcellIsRealNullable(self, freshDb: ObdDatabase) -> None:
        cols = {
            c['name']: c
            for c in freshDb.getTableInfo(BATTERY_HEALTH_LOG_TABLE)
        }
        assert cols['end_vcell_v']['notnull'] == 0
        assert cols['end_vcell_v']['type'].upper() == 'REAL'

    def test_legacySocColumnsDropped_socPctPresent(
        self, freshDb: ObdDatabase,
    ) -> None:
        """US-426: the misnamed legacy start_soc / end_soc are gone; the
        dedicated start_soc_pct / end_soc_pct SoC% columns replace them."""
        cols = {
            c['name']: c
            for c in freshDb.getTableInfo(BATTERY_HEALTH_LOG_TABLE)
        }
        assert 'start_soc' not in cols
        assert 'end_soc' not in cols
        assert 'start_soc_pct' in cols
        assert 'end_soc_pct' in cols


# ================================================================================
# Idempotent migration helper: ALTER TABLE only if missing
# ================================================================================


class TestEnsureBatteryHealthLogVcellColumnsIdempotency:
    """ensureBatteryHealthLogVcellColumns is safe to re-run."""

    def test_returnsTrueOnFirstCallToLegacyDb(self, tmp_path: Path) -> None:
        """A pre-US-289 db (table exists, new columns missing) gets the columns."""
        path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(path))
        try:
            # Simulate a legacy db with the OLD shape (no vcell columns).
            conn.execute(
                "CREATE TABLE battery_health_log ("
                "drain_event_id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "start_timestamp TEXT NOT NULL, "
                "end_timestamp TEXT, "
                "start_soc REAL NOT NULL, "
                "end_soc REAL, "
                "runtime_seconds INTEGER, "
                "ambient_temp_c REAL, "
                "load_class TEXT NOT NULL DEFAULT 'production', "
                "notes TEXT, "
                "data_source TEXT NOT NULL DEFAULT 'real')"
            )
            conn.commit()

            assert ensureBatteryHealthLogVcellColumns(conn) is True
            conn.commit()

            # Both new columns now present.
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(battery_health_log)"
                ).fetchall()
            }
            assert 'start_vcell_v' in columns
            assert 'end_vcell_v' in columns
        finally:
            conn.close()

    def test_returnsFalseOnSecondCall(self, tmp_path: Path) -> None:
        """Re-running the helper is a no-op once the columns exist."""
        path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(path))
        try:
            conn.execute(
                "CREATE TABLE battery_health_log ("
                "drain_event_id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "start_timestamp TEXT NOT NULL, "
                "start_soc REAL NOT NULL)"
            )
            conn.commit()

            assert ensureBatteryHealthLogVcellColumns(conn) is True
            conn.commit()
            assert ensureBatteryHealthLogVcellColumns(conn) is False
        finally:
            conn.close()

    def test_returnsFalseWhenTableMissing(self, tmp_path: Path) -> None:
        """No table -> no-op (mirrors ensurePowerLogVcellColumn semantics)."""
        path = tmp_path / "bare.db"
        conn = sqlite3.connect(str(path))
        try:
            assert ensureBatteryHealthLogVcellColumns(conn) is False
        finally:
            conn.close()

    def test_existingRowsPreserved(self, tmp_path: Path) -> None:
        """ALTER TABLE keeps legacy rows; new columns are NULL on those rows."""
        path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(path))
        try:
            conn.execute(
                "CREATE TABLE battery_health_log ("
                "drain_event_id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "start_timestamp TEXT NOT NULL DEFAULT "
                "(strftime('%Y-%m-%dT%H:%M:%SZ', 'now')), "
                "end_timestamp TEXT, "
                "start_soc REAL NOT NULL, "
                "end_soc REAL, "
                "runtime_seconds INTEGER, "
                "ambient_temp_c REAL, "
                "load_class TEXT NOT NULL DEFAULT 'production', "
                "notes TEXT, "
                "data_source TEXT NOT NULL DEFAULT 'real')"
            )
            # Seed two pre-US-289 rows holding VCELL-as-soc.
            conn.execute(
                "INSERT INTO battery_health_log "
                "(start_timestamp, start_soc) VALUES (?, ?)",
                ('2026-04-01T00:00:00Z', 4.10),
            )
            conn.execute(
                "INSERT INTO battery_health_log "
                "(start_timestamp, start_soc, end_timestamp, end_soc, "
                "runtime_seconds) VALUES (?, ?, ?, ?, ?)",
                ('2026-04-15T00:00:00Z', 4.05, '2026-04-15T00:30:00Z',
                 3.55, 1800),
            )
            conn.commit()

            ensureBatteryHealthLogVcellColumns(conn)
            conn.commit()

            rows = conn.execute(
                "SELECT drain_event_id, start_soc, end_soc, "
                "       start_vcell_v, end_vcell_v "
                "FROM battery_health_log ORDER BY drain_event_id"
            ).fetchall()
            assert len(rows) == 2

            # Original start_soc / end_soc untouched on both rows.
            assert rows[0][1] == 4.10  # row 1 start_soc
            assert rows[0][2] is None  # row 1 end_soc (was NULL)
            assert rows[1][1] == 4.05  # row 2 start_soc
            assert rows[1][2] == 3.55  # row 2 end_soc

            # New columns are NULL on legacy rows -- migration does not
            # backfill (separate sprint can run a backfill later).
            assert rows[0][3] is None  # row 1 start_vcell_v
            assert rows[0][4] is None  # row 1 end_vcell_v
            assert rows[1][3] is None  # row 2 start_vcell_v
            assert rows[1][4] is None  # row 2 end_vcell_v
        finally:
            conn.close()


# ================================================================================
# Writer back-compat: BatteryHealthRecorder writes BOTH old + new columns
# ================================================================================


class TestRecorderEmitsToBothColumns:
    """Post-US-426 the writer puts VCELL volts in *_vcell_v only; the legacy
    *_soc columns are gone and *_soc_pct stays NULL absent the SocPct kwarg."""

    def test_startDrainEventEmitsToStartVcellV(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        """startSoc=3.85 (a VCELL value) lands in start_vcell_v; soc_pct NULL."""
        drainId = recorder.startDrainEvent(startSoc=3.85)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT start_vcell_v, start_soc_pct FROM "
                f"{BATTERY_HEALTH_LOG_TABLE} WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        # US-426: VCELL volts live only in start_vcell_v now; start_soc_pct is
        # NULL until US-427 wires the MAX17048 register SoC% read.
        assert row[0] == 3.85  # start_vcell_v populated
        assert row[1] is None  # start_soc_pct NULL (no SocPct kwarg)

    def test_endDrainEventEmitsToEndVcellV(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        """endSoc=3.41 (TRIGGER threshold) lands in end_vcell_v; soc_pct NULL."""
        drainId = recorder.startDrainEvent(startSoc=4.10)
        recorder.endDrainEvent(drainEventId=drainId, endSoc=3.41)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_vcell_v, end_soc_pct FROM "
                f"{BATTERY_HEALTH_LOG_TABLE} WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] == 3.41  # end_vcell_v populated
        assert row[1] is None  # end_soc_pct NULL (no SocPct kwarg)

    def test_endVcellNullBeforeClose(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        """end_vcell_v stays NULL between startDrainEvent and endDrainEvent."""
        drainId = recorder.startDrainEvent(startSoc=4.05)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_vcell_v FROM "
                f"{BATTERY_HEALTH_LOG_TABLE} WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] is None

    def test_recorderRoundTripVcellAcrossFullDrain(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        """A complete drain lands VCELL volts in *_vcell_v; *_soc_pct NULL."""
        drainId = recorder.startDrainEvent(startSoc=4.12)
        recorder.endDrainEvent(drainEventId=drainId, endSoc=3.45)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT start_vcell_v, end_vcell_v, start_soc_pct, end_soc_pct "
                f"FROM {BATTERY_HEALTH_LOG_TABLE} WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] == 4.12  # start_vcell_v
        assert row[1] == 3.45  # end_vcell_v
        assert row[2] is None  # start_soc_pct NULL (no SocPct kwarg)
        assert row[3] is None  # end_soc_pct NULL

    def test_closeOnceSemanticPreservedForVcell(
        self,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        """Re-call of endDrainEvent does NOT overwrite end_vcell_v."""
        drainId = recorder.startDrainEvent(startSoc=4.10)
        recorder.endDrainEvent(drainEventId=drainId, endSoc=3.55)
        # Re-call with a different value would overwrite if close-once
        # were broken.  US-217 invariant says first close wins.
        recorder.endDrainEvent(drainEventId=drainId, endSoc=2.99)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_vcell_v FROM "
                f"{BATTERY_HEALTH_LOG_TABLE} WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] == 3.55  # first-close-wins on end_vcell_v


# ================================================================================
# Cross-helper composition: ensureBatteryHealthLogTable + Vcell columns chain
# ================================================================================


class TestEnsureChainComposability:
    """ensureBatteryHealthLogTable + ensureBatteryHealthLogVcellColumns in order."""

    def test_helpersComposeOnBareDb(self, tmp_path: Path) -> None:
        """Bare db -> table created, then vcell columns added in second helper."""
        path = tmp_path / "bare.db"
        conn = sqlite3.connect(str(path))
        try:
            assert ensureBatteryHealthLogTable(conn) is True
            conn.commit()

            # The new columns may or may not be in the schema literal; both
            # paths should converge to "columns present" after the second
            # helper.  This is the contract ObdDatabase.initialize() relies
            # on for legacy + fresh installs to behave identically.
            ensureBatteryHealthLogVcellColumns(conn)
            conn.commit()

            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(battery_health_log)"
                ).fetchall()
            }
            assert 'start_vcell_v' in columns
            assert 'end_vcell_v' in columns
        finally:
            conn.close()


# ================================================================================
# US-426 (BL-015): the SoC% rebuild migration -- drop legacy *_soc, add *_soc_pct
# ================================================================================


def _makeLegacyBhlDb(path: Path) -> sqlite3.Connection:
    """Create a pre-US-426 battery_health_log (start_soc/end_soc + vcell)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE battery_health_log ("
        "drain_event_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "start_timestamp TEXT NOT NULL, "
        "end_timestamp TEXT, "
        "start_soc REAL NOT NULL, "
        "end_soc REAL, "
        "start_vcell_v REAL, "
        "end_vcell_v REAL, "
        "runtime_seconds INTEGER, "
        "ambient_temp_c REAL, "
        "load_class TEXT NOT NULL DEFAULT 'production', "
        "notes TEXT, "
        "data_source TEXT NOT NULL DEFAULT 'real')"
    )
    conn.commit()
    return conn


class TestEnsureBatteryHealthLogSocPctColumns:
    """The US-426 CREATE-SELECT-DROP-RENAME rebuild helper."""

    def test_freshSchema_isNoOp(self, freshDb: ObdDatabase) -> None:
        """A fresh DB already lands in the target shape -> helper is a no-op."""
        with freshDb.connect() as conn:
            assert ensureBatteryHealthLogSocPctColumns(conn) is False

    def test_missingTable_isNoOp(self, tmp_path: Path) -> None:
        conn = sqlite3.connect(str(tmp_path / "bare.db"))
        try:
            assert ensureBatteryHealthLogSocPctColumns(conn) is False
        finally:
            conn.close()

    def test_legacyDb_dropsSocAddsSocPct(self, tmp_path: Path) -> None:
        conn = _makeLegacyBhlDb(tmp_path / "legacy.db")
        try:
            assert ensureBatteryHealthLogSocPctColumns(conn) is True
            conn.commit()
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(battery_health_log)"
                ).fetchall()
            }
            assert 'start_soc' not in columns
            assert 'end_soc' not in columns
            assert 'start_soc_pct' in columns
            assert 'end_soc_pct' in columns
            assert 'start_vcell_v' in columns
            assert 'end_vcell_v' in columns
        finally:
            conn.close()

    def test_secondCallIsNoOp(self, tmp_path: Path) -> None:
        conn = _makeLegacyBhlDb(tmp_path / "legacy.db")
        try:
            assert ensureBatteryHealthLogSocPctColumns(conn) is True
            conn.commit()
            assert ensureBatteryHealthLogSocPctColumns(conn) is False
        finally:
            conn.close()

    def test_preservesVoltage_coalescingLegacySocIntoVcell(
        self, tmp_path: Path,
    ) -> None:
        """Pre-US-289 rows carry voltage only in start_soc/end_soc (vcell NULL);
        the rebuild COALESCEs it into *_vcell_v so no voltage is lost."""
        conn = _makeLegacyBhlDb(tmp_path / "legacy.db")
        try:
            # Row A: pre-US-289 -- voltage only in start_soc/end_soc.
            conn.execute(
                "INSERT INTO battery_health_log "
                "(drain_event_id, start_timestamp, end_timestamp, start_soc, "
                " end_soc) VALUES (1, '2026-04-01T00:00:00Z', "
                "'2026-04-01T00:30:00Z', 4.10, 3.55)"
            )
            # Row B: post-US-289 -- vcell populated, soc mirrors it.
            conn.execute(
                "INSERT INTO battery_health_log "
                "(drain_event_id, start_timestamp, start_soc, start_vcell_v) "
                "VALUES (2, '2026-05-01T00:00:00Z', 4.05, 4.05)"
            )
            conn.commit()

            assert ensureBatteryHealthLogSocPctColumns(conn) is True
            conn.commit()

            rows = conn.execute(
                "SELECT drain_event_id, start_vcell_v, end_vcell_v, "
                "       start_soc_pct, end_soc_pct "
                "FROM battery_health_log ORDER BY drain_event_id"
            ).fetchall()
            # Row A: legacy volts preserved via COALESCE into vcell.
            assert rows[0] == (1, 4.10, 3.55, None, None)
            # Row B: existing vcell preserved.
            assert rows[1] == (2, 4.05, None, None, None)
        finally:
            conn.close()

    def test_rebuildPreservesIndex(self, tmp_path: Path) -> None:
        conn = _makeLegacyBhlDb(tmp_path / "legacy.db")
        try:
            ensureBatteryHealthLogSocPctColumns(conn)
            conn.commit()
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='battery_health_log'"
                ).fetchall()
            }
            assert 'IX_battery_health_log_start' in names
        finally:
            conn.close()

    def test_initializeRunsRebuildOnLegacyDb(self, tmp_path: Path) -> None:
        """ObdDatabase.initialize() wires the rebuild after the vcell helper:
        a legacy DB opened through it lands in the US-426 shape."""
        path = tmp_path / "legacy_full.db"
        _makeLegacyBhlDb(path).close()
        db = ObdDatabase(str(path), walMode=False)
        db.initialize()
        cols = {c['name'] for c in db.getTableInfo(BATTERY_HEALTH_LOG_TABLE)}
        assert 'start_soc' not in cols
        assert 'end_soc' not in cols
        assert {'start_soc_pct', 'end_soc_pct'}.issubset(cols)
