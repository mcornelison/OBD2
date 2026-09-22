################################################################################
# File Name: test_card_prior_shutdown_wiring.py
# Purpose/Description: US-744 -- the US-728 prior-shutdown verdict actually
#     REACHES the system-status state file. US-728 added the emitter parameter
#     and the payload key, but _emitSystemStatusState never passed it, so the car
#     published "priorShutdown": null on every boot (measured on chi-eclipse-01
#     2026-09-22 with 296 startup_log rows present). These tests pin the wiring:
#     the block is read from startup_log through the US-728 reader, transported
#     verbatim, and every unreadable case degrades to null without taking the
#     emit loop down.
# Author: Rex (US-744)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-22    | Rex (US-744)   | Initial -- the verdict reaches the state file.
# ================================================================================
################################################################################
"""US-744: the prior-shutdown verdict reaches system-status (producer side)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pi.diagnostics.prior_shutdown_summary import (
    VERDICT_CLEAN,
    VERDICT_NO_RECORD,
    VERDICT_UNGRACEFUL,
)
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin

_STARTUP_LOG = """
CREATE TABLE startup_log (
    boot_id TEXT, prior_boot_clean INTEGER, prior_last_entry_ts TEXT,
    prior_boot_last_stage TEXT, prior_boot_reason TEXT, recorded_at TEXT,
    data_quality TEXT
)
"""


class _Db:
    """A real on-disk SQLite DB: the US-728 reader opens dbPath read-only."""

    def __init__(self, path: Path, rows=()) -> None:
        self.dbPath = str(path)
        with sqlite3.connect(self.dbPath) as conn:
            conn.execute(_STARTUP_LOG)
            for row in rows:
                conn.execute(
                    "INSERT INTO startup_log (boot_id, prior_boot_clean,"
                    " prior_last_entry_ts, prior_boot_last_stage, prior_boot_reason,"
                    " recorded_at, data_quality) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    row,
                )


def _boot(clean, reason, recordedAt="2026-09-21T23:20:44Z", quality="clock_unsynced"):
    return ("boot-" + str(clean), clean, None, None, reason, recordedAt, quality)


class _FakeOrch(CardStateEmitterMixin):
    """Minimal composing object exposing the attrs the mixin reads."""

    def __init__(self, config, *, database=None):
        self._config = config
        self._connection = None
        self._driveDetector = None
        self._powerSourceProvider = None
        self._hardwareManager = None
        if database is not None:
            self._database = database
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = None
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0


def _config(tmp_path):
    return {
        "pi": {
            "splash": {"statesDir": str(tmp_path / "states")},
            "dashboard": {"stateEmitIntervalSeconds": 0.0},
        }
    }


def _emitAndRead(tmp_path, orch):
    orch._initializeCardStateEmitters()
    orch._maybeEmitCardStates()
    return json.loads((tmp_path / "states" / "system-status").read_text(encoding="utf-8"))


def test_emit_carriesTheVerdictFromStartupLog(tmp_path: Path) -> None:
    """
    Given: a startup_log whose newest row records a CLEAN prior shutdown
    When: the card states are emitted
    Then: the priorShutdown block carries that verdict -- on the pre-US-744
        emitter this key was null with the very same row present
    """
    db = _Db(tmp_path / "obd.db", [_boot(1, "graceful")])
    block = _emitAndRead(tmp_path, _FakeOrch(_config(tmp_path), database=db))["priorShutdown"]
    assert block is not None
    assert block["verdict"] == VERDICT_CLEAN
    assert block["label"] == "CLEAN"
    assert block["dataQuality"] == "clock_unsynced"
    assert block["notAfterTs"] == "2026-09-21T23:20:44Z"


def test_emit_carriesAnUngracefulVerdictWithItsCaveat(tmp_path: Path) -> None:
    """An ungraceful verdict travels with the reason text and the US-728 caveat."""
    db = _Db(tmp_path / "obd.db", [_boot(0, "crashed_during_operation")])
    block = _emitAndRead(tmp_path, _FakeOrch(_config(tmp_path), database=db))["priorShutdown"]
    assert block["verdict"] == VERDICT_UNGRACEFUL
    assert block["caveat"]
    assert block["label"].startswith("UNGRACEFUL")


def test_emit_newestRowWins_byRowidNotByClock(tmp_path: Path) -> None:
    """
    Given: an older row written with a LATER wall clock (the dead-RTC case --
        clock_unsynced on 198 of 296 rows on the car)
    When: emitted
    Then: the newest INSERTED row is the verdict, per the US-728 reader
    """
    db = _Db(tmp_path / "obd.db", [
        _boot(0, "crashed_during_operation", recordedAt="2027-01-01T00:00:00Z"),
        _boot(1, "graceful", recordedAt="2026-09-21T23:20:44Z"),
    ])
    block = _emitAndRead(tmp_path, _FakeOrch(_config(tmp_path), database=db))["priorShutdown"]
    assert block["verdict"] == VERDICT_CLEAN


def test_emit_noRowRecorded_isTheNoRecordVerdict_notNull(tmp_path: Path) -> None:
    """A row that records no prior boot is NO RECORD -- a different fact from
    'not read', which the renderer must also distinguish."""
    db = _Db(tmp_path / "obd.db", [_boot(None, "indeterminate_no_record")])
    block = _emitAndRead(tmp_path, _FakeOrch(_config(tmp_path), database=db))["priorShutdown"]
    assert block["verdict"] == VERDICT_NO_RECORD


def test_emit_emptyStartupLog_isNull_andTheCardStillEmits(tmp_path: Path) -> None:
    """No row at all is 'not read' -> null. The card must still publish."""
    db = _Db(tmp_path / "obd.db")
    status = _emitAndRead(tmp_path, _FakeOrch(_config(tmp_path), database=db))
    assert status["priorShutdown"] is None
    assert status["ts"]


def test_emit_noDatabaseAtAll_isNull_andTheCardStillEmits(tmp_path: Path) -> None:
    """On the bench there is no database attribute; a missing verdict can never
    take the whole status card down."""
    status = _emitAndRead(tmp_path, _FakeOrch(_config(tmp_path)))
    assert status["priorShutdown"] is None
    assert status["ts"]


def test_emit_unreadableDatabase_isNull_andTheCardStillEmits(tmp_path: Path) -> None:
    """A DB path that is not a readable SQLite file degrades to null."""
    broken = tmp_path / "broken.db"
    broken.write_text("not a database", encoding="utf-8")

    class _Broken:
        dbPath = str(broken)

    status = _emitAndRead(tmp_path, _FakeOrch(_config(tmp_path), database=_Broken()))
    assert status["priorShutdown"] is None
    assert status["ts"]


def test_emit_transportsTheProducerBlockVerbatim(tmp_path: Path) -> None:
    """
    Given: the US-728 summary for the same row
    When: the emitter publishes
    Then: the block is byte-identical to the producer's toStatePayload() -- the
        card computes no verdict of its own (AC4)
    """
    from pi.diagnostics.prior_shutdown_summary import readPriorShutdownSummaryFromPath

    db = _Db(tmp_path / "obd.db", [_boot(0, "died_mid_drain")])
    published = _emitAndRead(tmp_path, _FakeOrch(_config(tmp_path), database=db))["priorShutdown"]
    expected = readPriorShutdownSummaryFromPath(db.dbPath).toStatePayload()
    assert published == expected
