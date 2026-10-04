################################################################################
# File Name: test_prior_boot_sync_landing.py
# Purpose/Description: US-776-f -- startup_log carries the prior boot's home
#                      state, sync outcome and backlog counts.  The shutdown
#                      record powerwatch writes (outcome.py) gains the four
#                      fields plus the writer's boot_id; boot_progress.arm
#                      lands them into four new prior_boot_* columns, and
#                      lands NULL whenever it cannot PROVE the record belongs
#                      to the prior boot.  The column step is replay-safe
#                      (specs/design-patterns.md #10).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-30    | Ralph (Rex)  | Initial -- US-776-f.
# 2026-10-03    | Atlas (ARCH-065a) | Registry grew to eight columns (T6 fix: + loss_at); the schema-step
#               |              | tests pin _REGISTRY_COLUMNS (landing tests keep the four).
# ================================================================================
################################################################################
"""The prior boot's shutdown-sync record lands in startup_log (US-776-f)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.pi.diagnostics import boot_progress
from src.pi.diagnostics.boot_progress import (
    OUTCOME_RECORD_FILENAME,
    arm,
    readPriorShutdownRecord,
)
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.database_schema import (
    SCHEMA_STARTUP_LOG,
    STARTUP_LOG_PRIOR_BOOT_SYNC_COLUMNS,
    ensureStartupLogPriorBootSyncColumns,
)
from src.pi.power.power_watch import outcome
from src.pi.power.power_watch.contract import OutcomeKind

_PRIOR_BOOT = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_OLDER_BOOT = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
_NEW_BOOT = "cccccccccccccccccccccccccccccccc"

_NEW_COLUMNS = (
    "prior_boot_home_state",
    "prior_boot_sync_outcome",
    "prior_boot_backlog_start",
    "prior_boot_backlog_end",
)

# ARCH-065 appended three more to the registry (the landing step does not write
# them); the schema-step tests below pin the whole registry.
_REGISTRY_COLUMNS = _NEW_COLUMNS + (
    "prior_boot_sync_started_at",
    "prior_boot_sync_ended_at",
    "prior_boot_vcell_before_cut_v",
    "prior_boot_loss_at",
)

_LEGACY_STARTUP_LOG = """
CREATE TABLE startup_log (
    boot_id TEXT PRIMARY KEY,
    prior_boot_clean INTEGER,
    prior_last_entry_ts TEXT,
    current_boot_first_entry_ts TEXT,
    prior_boot_last_stage TEXT,
    prior_boot_reason TEXT,
    recorded_at TEXT NOT NULL DEFAULT '',
    data_quality TEXT
);
"""


def _writeTrail(path: Path, bootId: str, stages: list[str]) -> None:
    path.write_text(
        "".join(
            json.dumps({"boot_id": bootId, "stage": s, "ts": "t", "vcell": None}) + "\n"
            for s in stages
        ),
        encoding="utf-8",
    )


def _freshDb(tmp_path: Path) -> Path:
    db = tmp_path / "obd.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_STARTUP_LOG)
    conn.close()
    return db


def _landedRow(db: Path, bootId: str = _NEW_BOOT) -> dict:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM startup_log WHERE boot_id = ?", (bootId,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "arm wrote no startup_log row"
    return dict(row)


def _armNextBoot(tmp_path: Path, db: Path) -> dict:
    arm(filePath=str(tmp_path / "boot_progress"), dbPath=str(db), bootId=_NEW_BOOT,
        nasArchiveDir=str(tmp_path / "nas"), nasArchiveEnabled=False,
        clockQualityProvider=lambda _ts: "full")
    return _landedRow(db)


def _writeShutdownRecord(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, bootId: str, **fields: object,
) -> Path:
    """Write the record exactly as powerwatch would, from boot ``bootId``."""
    monkeypatch.setattr(outcome, "readBootId", lambda: bootId)
    path = tmp_path / OUTCOME_RECORD_FILENAME
    outcome.writeOutcomeRecord(
        str(path), OutcomeKind.OK, detail="drained", task="sync_with_server",
        **fields,
    )
    return path


# ================================================================================
# The record powerwatch writes
# ================================================================================


class TestShutdownRecordCarriesTheFields:
    def test_allFourFieldsAndTheWritersBootId_areWritten(self, tmp_path, monkeypatch):
        path = _writeShutdownRecord(
            tmp_path, monkeypatch, bootId=_PRIOR_BOOT,
            homeState="AT_HOME_SERVER_REACHABLE", syncOutcome="DELIVERED",
            backlogStart=412, backlogEnd=0,
        )

        record = json.loads(path.read_text(encoding="utf-8"))

        assert record["boot_id"] == _PRIOR_BOOT
        assert record["home_state"] == "AT_HOME_SERVER_REACHABLE"
        assert record["sync_outcome"] == "DELIVERED"
        assert record["backlog_start"] == 412
        assert record["backlog_end"] == 0

    def test_existingKeysUnchanged_andUnsuppliedFieldsAbsent(self, tmp_path, monkeypatch):
        path = _writeShutdownRecord(tmp_path, monkeypatch, bootId=_PRIOR_BOOT)

        record = json.loads(path.read_text(encoding="utf-8"))

        assert {"schema", "kind", "detail", "task", "ts", "boot_id"} == set(record)
        assert record["kind"] == OutcomeKind.OK.value
        assert record["task"] == "sync_with_server"

    def test_powerwatchWritesTheRecordArmReads(self):
        """arm derives the record path from the DB dir, as powerwatch does."""
        source = Path("src/pi/power/power_watch/__main__.py").read_text(encoding="utf-8")
        assert f'"{OUTCOME_RECORD_FILENAME}"' in source


# ================================================================================
# Landing at the next boot (validation criteria)
# ================================================================================


class TestLandingAtNextBoot:
    def test_recordWithAllFour_landsAllFour(self, tmp_path, monkeypatch):
        """VC1: write a shutdown record with all four fields, then boot."""
        db = _freshDb(tmp_path)
        _writeTrail(tmp_path / "boot_progress", _PRIOR_BOOT,
                    ["RUNNING", "WARNING", "IMMINENT", "TRIGGER"])
        _writeShutdownRecord(
            tmp_path, monkeypatch, bootId=_PRIOR_BOOT,
            homeState="AT_HOME_SERVER_REACHABLE", syncOutcome="DELIVERED",
            backlogStart=412, backlogEnd=0,
        )

        row = _armNextBoot(tmp_path, db)

        assert row["prior_boot_home_state"] == "AT_HOME_SERVER_REACHABLE"
        assert row["prior_boot_sync_outcome"] == "DELIVERED"
        assert row["prior_boot_backlog_start"] == 412
        assert row["prior_boot_backlog_end"] == 0

    def test_existingPriorBootFields_landExactlyAsBefore(self, tmp_path, monkeypatch):
        db = _freshDb(tmp_path)
        _writeTrail(tmp_path / "boot_progress", _PRIOR_BOOT,
                    ["RUNNING", "WARNING", "IMMINENT", "TRIGGER", "POWEROFF_INVOKED"])
        _writeShutdownRecord(tmp_path, monkeypatch, bootId=_PRIOR_BOOT,
                             syncOutcome="AWAY", backlogStart=7, backlogEnd=7)

        row = _armNextBoot(tmp_path, db)

        assert row["prior_boot_clean"] == 0
        assert row["prior_boot_last_stage"] == "POWEROFF_INVOKED"
        assert row["prior_boot_reason"] == "poweroff_invoked_never_returned"

    def test_olderBuildRecordWithNoneOfThem_landsAllNull(self, tmp_path):
        """VC2: a record from a build that wrote none of the four fields."""
        db = _freshDb(tmp_path)
        _writeTrail(tmp_path / "boot_progress", _PRIOR_BOOT, ["RUNNING", "TRIGGER"])
        (tmp_path / OUTCOME_RECORD_FILENAME).write_text(json.dumps({
            "schema": 1, "kind": "success", "detail": "x",
            "task": "sync_with_server", "ts": "2026-09-29T20:00:00Z",
        }), encoding="utf-8")

        row = _armNextBoot(tmp_path, db)

        assert all(row[c] is None for c in _NEW_COLUMNS)

    def test_newBuildRecordWithNoneOfThem_landsAllNull(self, tmp_path, monkeypatch):
        db = _freshDb(tmp_path)
        _writeTrail(tmp_path / "boot_progress", _PRIOR_BOOT, ["RUNNING", "TRIGGER"])
        _writeShutdownRecord(tmp_path, monkeypatch, bootId=_PRIOR_BOOT)

        row = _armNextBoot(tmp_path, db)

        assert all(row[c] is None for c in _NEW_COLUMNS)

    def test_hardCut_staleRecordFromAnEarlierBoot_landsAllNull(self, tmp_path, monkeypatch):
        """The prior boot wrote no record; the file on disk is an older boot's."""
        db = _freshDb(tmp_path)
        _writeTrail(tmp_path / "boot_progress", _PRIOR_BOOT, ["RUNNING"])
        _writeShutdownRecord(
            tmp_path, monkeypatch, bootId=_OLDER_BOOT,
            homeState="AWAY", syncOutcome="AWAY", backlogStart=9, backlogEnd=9,
        )

        row = _armNextBoot(tmp_path, db)

        assert all(row[c] is None for c in _NEW_COLUMNS)

    def test_noRecordOnDisk_landsAllNull(self, tmp_path):
        db = _freshDb(tmp_path)
        _writeTrail(tmp_path / "boot_progress", _PRIOR_BOOT, ["RUNNING"])

        row = _armNextBoot(tmp_path, db)

        assert all(row[c] is None for c in _NEW_COLUMNS)

    def test_noPriorTrail_cannotProveOwnership_landsAllNull(self, tmp_path, monkeypatch):
        db = _freshDb(tmp_path)
        _writeShutdownRecord(
            tmp_path, monkeypatch, bootId=_PRIOR_BOOT,
            homeState="AWAY", syncOutcome="AWAY", backlogStart=1, backlogEnd=1,
        )

        row = _armNextBoot(tmp_path, db)

        assert all(row[c] is None for c in _NEW_COLUMNS)

    def test_unknownBootIdOnBothSides_isNotAMatch(self, tmp_path, monkeypatch):
        """'unknown' is readBootId's failure value: two of them prove nothing."""
        db = _freshDb(tmp_path)
        _writeTrail(tmp_path / "boot_progress", "unknown", ["RUNNING"])
        _writeShutdownRecord(
            tmp_path, monkeypatch, bootId="unknown",
            homeState="AWAY", syncOutcome="AWAY", backlogStart=1, backlogEnd=1,
        )

        row = _armNextBoot(tmp_path, db)

        assert all(row[c] is None for c in _NEW_COLUMNS)

    def test_tornRecord_landsAllNull_andArmStillReArms(self, tmp_path):
        db = _freshDb(tmp_path)
        trail = tmp_path / "boot_progress"
        _writeTrail(trail, _PRIOR_BOOT, ["RUNNING"])
        (tmp_path / OUTCOME_RECORD_FILENAME).write_text('{"boot_id": "aa', encoding="utf-8")

        row = _armNextBoot(tmp_path, db)

        assert all(row[c] is None for c in _NEW_COLUMNS)
        lines = trail.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1 and json.loads(lines[0])["boot_id"] == _NEW_BOOT


class TestFieldValidation:
    """A field that is present but not a valid value lands NULL, never coerced."""

    @pytest.mark.parametrize("field,value", [
        ("home_state", ""),
        ("home_state", "   "),
        ("home_state", 3),
        ("sync_outcome", None),
        ("sync_outcome", ["DELIVERED"]),
        ("backlog_start", -1),
        ("backlog_start", True),
        ("backlog_start", "412"),
        ("backlog_end", 1.5),
        ("backlog_end", None),
    ])
    def test_invalidValue_isNull_othersStillLand(self, tmp_path, field, value):
        record = {
            "boot_id": _PRIOR_BOOT, "home_state": "AWAY", "sync_outcome": "AWAY",
            "backlog_start": 5, "backlog_end": 5,
        }
        record[field] = value
        path = tmp_path / OUTCOME_RECORD_FILENAME
        path.write_text(json.dumps(record), encoding="utf-8")

        landed = readPriorShutdownRecord(str(path), {_PRIOR_BOOT})

        column = f"prior_boot_{field}"
        assert landed[column] is None
        assert all(landed[c] is not None for c in _NEW_COLUMNS if c != column)

    def test_partialRecord_landsOnlyWhatItHas(self, tmp_path):
        path = tmp_path / OUTCOME_RECORD_FILENAME
        path.write_text(json.dumps({"boot_id": _PRIOR_BOOT, "home_state": "AWAY"}),
                        encoding="utf-8")

        landed = readPriorShutdownRecord(str(path), {_PRIOR_BOOT})

        assert landed == {
            "prior_boot_home_state": "AWAY",
            "prior_boot_sync_outcome": None,
            "prior_boot_backlog_start": None,
            "prior_boot_backlog_end": None,
            "prior_boot_sync_started_at": None,
            "prior_boot_sync_ended_at": None,
            "prior_boot_vcell_before_cut_v": None,
            "prior_boot_loss_at": None,
        }

    def test_nonObjectJson_landsAllNull(self, tmp_path):
        path = tmp_path / OUTCOME_RECORD_FILENAME
        path.write_text("[1, 2]", encoding="utf-8")

        landed = readPriorShutdownRecord(str(path), {_PRIOR_BOOT})

        assert all(v is None for v in landed.values())

    def test_cliDefaultRecordPath_isBesideTheDb(self, tmp_path, monkeypatch):
        seen: dict[str, object] = {}

        def fakeArm(**kwargs: object) -> None:
            seen.update(kwargs)

        monkeypatch.setattr(boot_progress, "arm", fakeArm)
        db = tmp_path / "data" / "obd.db"

        boot_progress.main(["--arm", "--db", str(db), "--boot-id", _NEW_BOOT])

        assert seen["outcomeRecordPath"] == str(db.parent / OUTCOME_RECORD_FILENAME)


# ================================================================================
# The schema step (design-patterns #10: replay-safe against a POPULATED db)
# ================================================================================


def _populatedLegacyDb(tmp_path: Path) -> Path:
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(_LEGACY_STARTUP_LOG)
    conn.executemany(
        "INSERT INTO startup_log (boot_id, prior_boot_clean, prior_boot_last_stage, "
        "prior_boot_reason, recorded_at, data_quality) VALUES (?, ?, ?, ?, ?, ?)",
        [(f"boot{i}", i % 2, "TRIGGER", "wedged_before_poweroff",
          f"2026-09-{i + 1:02d}T00:00:00Z", "full") for i in range(5)],
    )
    conn.commit()
    conn.close()
    return db


class TestSchemaStep:
    def test_columnSpecIsTheFourPlusThreeColumns(self):
        assert tuple(name for name, _ in STARTUP_LOG_PRIOR_BOOT_SYNC_COLUMNS) == _REGISTRY_COLUMNS
        types = dict(STARTUP_LOG_PRIOR_BOOT_SYNC_COLUMNS)
        assert types["prior_boot_backlog_start"] == "INTEGER"
        assert types["prior_boot_backlog_end"] == "INTEGER"

    def test_freshSchemaHasTheFourColumns_andTheStepIsANoOp(self, tmp_path):
        conn = sqlite3.connect(tmp_path / "fresh.db")
        conn.executescript(SCHEMA_STARTUP_LOG)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(startup_log)")}
        assert set(_NEW_COLUMNS) <= cols
        assert ensureStartupLogPriorBootSyncColumns(conn) == []
        conn.close()

    def test_runTwiceOnAPopulatedDb_secondRunExecutesNoAlter_rowsUntouched(self, tmp_path):
        db = _populatedLegacyDb(tmp_path)
        conn = sqlite3.connect(db)
        before = conn.execute(
            "SELECT boot_id, prior_boot_clean, prior_boot_last_stage, "
            "prior_boot_reason, recorded_at, data_quality FROM startup_log ORDER BY boot_id"
        ).fetchall()

        first = ensureStartupLogPriorBootSyncColumns(conn)
        conn.commit()
        executed: list[str] = []
        conn.set_trace_callback(executed.append)
        second = ensureStartupLogPriorBootSyncColumns(conn)
        conn.commit()
        conn.set_trace_callback(None)

        assert first == list(_REGISTRY_COLUMNS)
        assert second == []
        assert not [s for s in executed if "ALTER" in s.upper()]
        after = conn.execute(
            "SELECT boot_id, prior_boot_clean, prior_boot_last_stage, "
            "prior_boot_reason, recorded_at, data_quality FROM startup_log ORDER BY boot_id"
        ).fetchall()
        assert after == before
        newValues = conn.execute(
            "SELECT " + ", ".join(_REGISTRY_COLUMNS) + " FROM startup_log"
        ).fetchall()
        assert all(v is None for row in newValues for v in row)
        conn.close()

    def test_firstRunOnlyAddsColumns_neverMovesARow(self, tmp_path):
        db = _populatedLegacyDb(tmp_path)
        conn = sqlite3.connect(db)
        executed: list[str] = []
        conn.set_trace_callback(executed.append)

        ensureStartupLogPriorBootSyncColumns(conn)

        conn.set_trace_callback(None)
        writes = [s for s in executed
                  if s.lstrip().upper().startswith(("ALTER", "CREATE", "INSERT",
                                                    "UPDATE", "DELETE", "DROP"))]
        assert len(writes) == len(_REGISTRY_COLUMNS)
        assert all("ADD COLUMN" in s for s in writes)
        conn.close()

    def test_missingTable_isANoOp(self, tmp_path):
        conn = sqlite3.connect(tmp_path / "empty.db")
        assert ensureStartupLogPriorBootSyncColumns(conn) == []
        conn.close()

    def test_initializeReachesTheStep_onAPopulatedLegacyDb_twice(self, tmp_path):
        db = _populatedLegacyDb(tmp_path)

        ObdDatabase(str(db), walMode=False).initialize()
        ObdDatabase(str(db), walMode=False).initialize()

        conn = sqlite3.connect(db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(startup_log)")}
        count = conn.execute("SELECT COUNT(*) FROM startup_log").fetchone()[0]
        conn.close()
        assert set(_NEW_COLUMNS) <= cols
        assert count == 5

    def test_armOnALegacyDb_addsTheColumnsAndLands(self, tmp_path, monkeypatch):
        db = _populatedLegacyDb(tmp_path)
        _writeTrail(tmp_path / "boot_progress", _PRIOR_BOOT, ["RUNNING"])
        _writeShutdownRecord(
            tmp_path, monkeypatch, bootId=_PRIOR_BOOT,
            homeState="AWAY", syncOutcome="AWAY", backlogStart=3, backlogEnd=3,
        )
        # The legacy db is named legacy.db, so point arm at the record explicitly.
        arm(filePath=str(tmp_path / "boot_progress"), dbPath=str(db), bootId=_NEW_BOOT,
            nasArchiveDir="", nasArchiveEnabled=False,
            clockQualityProvider=lambda _ts: "full",
            outcomeRecordPath=str(tmp_path / OUTCOME_RECORD_FILENAME))

        row = _landedRow(db)
        assert row["prior_boot_home_state"] == "AWAY"
        assert row["prior_boot_backlog_start"] == 3


# ================================================================================
# The landed columns reach the sync wire
# ================================================================================


def test_snapshotRowsCarryTheFourColumns(tmp_path, monkeypatch):
    from src.pi.data.sync_log import getSnapshotRows

    db = _freshDb(tmp_path)
    _writeTrail(tmp_path / "boot_progress", _PRIOR_BOOT, ["RUNNING"])
    _writeShutdownRecord(
        tmp_path, monkeypatch, bootId=_PRIOR_BOOT,
        homeState="AT_HOME_SERVER_REACHABLE", syncOutcome="DELIVERED",
        backlogStart=412, backlogEnd=0,
    )
    _armNextBoot(tmp_path, db)

    conn = sqlite3.connect(db)
    try:
        rows = getSnapshotRows(conn, "startup_log", None, 10)
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0]["prior_boot_home_state"] == "AT_HOME_SERVER_REACHABLE"
    assert rows[0]["prior_boot_sync_outcome"] == "DELIVERED"
    assert rows[0]["prior_boot_backlog_start"] == 412
    assert rows[0]["prior_boot_backlog_end"] == 0
