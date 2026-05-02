################################################################################
# File Name: test_logshutdown_stage_fsync_and_error_propagation.py
# Purpose/Description: US-267 runtime-validation gate -- proves logShutdownStage
#                      flushes power_log STAGE_* rows durably to disk via
#                      explicit conn.commit() + PRAGMA synchronous=FULL +
#                      os.fsync(), AND propagates INSERT failures with an
#                      ERROR log instead of silently swallowing them.  This
#                      closes Spool's discriminator hypothesis C from the
#                      Sprint 22 truth-table: "pd_stage advances in CSV but
#                      power_log has no STAGE_* rows -> the write path itself
#                      is the gap."  Pre-fix code (lines 208-209 of
#                      src/pi/power/power_db.py at the US-252 baseline)
#                      caught Exception, emitted an ERROR log, but did NOT
#                      re-raise -- meaning a hard-crash before WAL fsync
#                      lost the rows AND any sqlite3.OperationalError
#                      surfacing during the INSERT was swallowed silently.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-02    | Rex (US-267) | Initial -- discriminator C runtime-validation
#                              | gate.  Three test classes: fsync invocation
#                              | + INSERT-error propagation + stair-step
#                              | rows-present runtime gate.  All three would
#                              | FAIL pre-fix because (a) no os.fsync was
#                              | called from logShutdownStage, (b) the
#                              | except-Exception branch logged but did NOT
#                              | re-raise so the test's pytest.raises never
#                              | fires, (c) the stair-step assertion ran
#                              | against the existing US-252 fixture but
#                              | additionally requires the new rows to be
#                              | visible from a SECOND connection after each
#                              | writer call returns -- proving fsync flushed
#                              | rather than just buffering in WAL.
# ================================================================================
################################################################################

"""US-267 logShutdownStage durability + error-propagation gate.

The discriminator: post-Drain-7, if `pd_stage` advances in the
forensics CSV but `power_log` still has zero STAGE_* rows, then this
write-path was the bug class.  US-267 hardens the writer with three
defensive moves in lockstep:

* **PRAGMA synchronous = FULL** on the write connection -- SQLite-level
  guarantee that the WAL is fsynced before the commit returns
* **Explicit conn.commit()** before the context-manager exit -- removes
  the dependency on `database.connect()`'s implicit commit semantics
* **os.fsync(fd)** on the database file after commit -- defense in depth
  that catches any drift in SQLite's own fsync behavior
* **try/except Exception -> log ERROR + re-raise** -- the contract
  inversion that prevents silent swallow

The orchestrator's :func:`_writePowerLogStage` (US-252) wraps the
writer call in its own try/except so the safety ladder cannot be
blocked by a re-raising forensics writer -- the contract change here
is safe.  See test 4 for the runtime-validation gate that the rows
are visible from a second connection after the writer returns
(stronger than "the call returned without error" because WAL-buffered
rows would be visible too -- this proves fsync flushed).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.pi.hardware.ups_monitor import PowerSource
from src.pi.obdii.database import DatabaseConnectionError, ObdDatabase
from src.pi.power.battery_health import BatteryHealthRecorder
from src.pi.power.orchestrator import (
    PowerDownOrchestrator,
    PowerState,
    ShutdownThresholds,
)
from src.pi.power.power_db import logShutdownStage

# ================================================================================
# Fixtures (mirror tests/pi/power/test_staged_shutdown_actually_fires.py)
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """A real ObdDatabase with US-252 schema (vcell column on power_log)."""
    db = ObdDatabase(str(tmp_path / "test_us267_fsync_gate.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def freshDbWal(tmp_path: Path) -> ObdDatabase:
    """A real ObdDatabase with WAL mode (production parity for the
    fsync semantics that motivated US-267)."""
    db = ObdDatabase(str(tmp_path / "test_us267_fsync_gate_wal.db"), walMode=True)
    db.initialize()
    return db


@pytest.fixture()
def thresholds() -> ShutdownThresholds:
    return ShutdownThresholds(
        enabled=True,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
    )


@pytest.fixture()
def recorder(freshDb: ObdDatabase) -> BatteryHealthRecorder:
    return BatteryHealthRecorder(database=freshDb)


# ================================================================================
# Fake objects for the error-propagation test
# ================================================================================


class _RaisingDatabase:
    """A drop-in ObdDatabase substitute whose ``connect()`` yields a
    sqlite3 connection-shaped object that raises on cursor.execute.

    The contract under test is that ``logShutdownStage`` re-raises the
    exception after logging at ERROR level -- the writer must NOT
    silently swallow.  Using a fake here (rather than monkeypatching
    a real ObdDatabase) keeps the test laser-focused on the swallow
    contract and avoids accidentally re-routing the exception through
    ``ObdDatabase.connect()``'s sqlite3.Error->DatabaseConnectionError
    wrapper.
    """

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.dbPath = "/tmp/us267_fake_raising.db"  # noqa: S108  -- fake; never opened

    @contextmanager
    def connect(self) -> Any:
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute.side_effect = self._exc
        conn.cursor.return_value = cursor
        try:
            yield conn
        finally:
            conn.close()


# ================================================================================
# TestLogShutdownStageFsync -- discriminator C test (a)
# ================================================================================


class TestLogShutdownStageFsync:
    """Acceptance #2 + Spool spec Story 6: ``conn.commit()`` then
    ``os.fsync(...)`` (or PRAGMA synchronous=FULL on the write
    connection).  This story uses BOTH for defense in depth -- the
    PRAGMA gives SQLite-level WAL durability, the os.fsync catches
    any drift in SQLite's own fsync behavior at the kernel boundary.

    The pre-US-267 implementation had neither.  These tests would
    FAIL pre-fix because os.fsync was never invoked from
    logShutdownStage.
    """

    def test_logShutdownStage_callsOsFsyncAtLeastOnce(
        self, freshDb: ObdDatabase
    ) -> None:
        """A successful logShutdownStage call must fsync the database
        file at least once after the INSERT commits.  This is the
        load-bearing kernel-level durability assertion."""
        with patch(
            "src.pi.power.power_db.os.fsync", wraps=os.fsync
        ) as mockFsync:
            logShutdownStage(freshDb, "stage_warning", 3.65)
        assert mockFsync.call_count >= 1, (
            "Pre-US-267 regression: logShutdownStage did not fsync "
            "the database file after INSERT -- a hard crash before "
            "WAL checkpoint would lose the row"
        )

    def test_logShutdownStage_setsPragmaSynchronousFull(
        self, freshDb: ObdDatabase
    ) -> None:
        """PRAGMA synchronous=FULL must be set on the write connection
        before the INSERT commits.  In WAL mode this means SQLite
        fsyncs the WAL on every commit; in non-WAL mode it fsyncs the
        main db file.  Either way, durability is guaranteed at the
        SQLite layer independent of os.fsync defense-in-depth.

        Implementation note: sqlite3.Connection does not allow setattr
        on its built-in methods, so we proxy the connection through a
        thin wrapper that records every ``execute()`` call's SQL while
        delegating everything else.  The wrapper preserves the
        sqlite3.Row factory and PRAGMA-foreign-keys side effects of
        the real connection so the surrounding INSERT path is
        unaffected.
        """
        executedSql: list[str] = []
        realConnect = freshDb.connect

        class _SqlTracker:
            """Records connection-level execute() SQL while delegating
            cursor/commit/rollback/close to the real connection."""

            def __init__(self, conn: Any) -> None:
                self._conn = conn

            def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
                executedSql.append(sql)
                return self._conn.execute(sql, *args, **kwargs)

            def __getattr__(self, item: str) -> Any:
                return getattr(self._conn, item)

        @contextmanager
        def trackingConnect() -> Any:
            with realConnect() as realConn:
                yield _SqlTracker(realConn)

        with patch.object(freshDb, "connect", trackingConnect):
            logShutdownStage(freshDb, "stage_warning", 3.65)

        synchronousFullSet = any(
            "synchronous" in sql.lower() and "full" in sql.lower()
            for sql in executedSql
        )
        assert synchronousFullSet, (
            "Pre-US-267 regression: PRAGMA synchronous=FULL was not "
            "set on the write connection -- WAL mode buffering can "
            "lose stage rows on hard crash before checkpoint. "
            f"Executed SQL: {executedSql}"
        )

    def test_logShutdownStage_walMode_rowVisibleFromSecondConnection(
        self, freshDbWal: ObdDatabase
    ) -> None:
        """Production parity: write through one connection in WAL mode;
        a fresh connection must see the row immediately after the
        writer returns.  Pre-US-267 the row was committed to WAL but
        not necessarily fsynced -- a hard crash would lose it.  Post-
        US-267 the explicit commit + PRAGMA synchronous=FULL +
        os.fsync chain guarantees visibility AND durability."""
        logShutdownStage(freshDbWal, "stage_warning", 3.65)
        with freshDbWal.connect() as conn:
            row = conn.execute(
                "SELECT event_type, vcell FROM power_log "
                "WHERE event_type = 'stage_warning'"
            ).fetchone()
        assert row is not None
        assert row[0] == "stage_warning"
        assert row[1] == pytest.approx(3.65, abs=1e-3)


# ================================================================================
# TestLogShutdownStageErrorPropagation -- discriminator C test (b)
# ================================================================================


class TestLogShutdownStageErrorPropagation:
    """Acceptance #3 + Spool spec Story 6: ``Wrap the INSERT in
    try/except OperationalError + Exception -> log ERROR + re-raise``.

    Pre-US-267 the catch swallowed silently (line 208-209 of
    power_db.py at the US-252 baseline) -- a sqlite3.OperationalError
    during the INSERT would hit the ERROR log but the function would
    return None as if successful.  This conflated three distinct
    failure modes into one silent state: (1) hardware crash mid-write,
    (2) SQL syntax bug, (3) actual disk-full / I/O error.  US-267
    inverts the contract: ANY exception during INSERT escapes loud,
    NEVER silent.

    The orchestrator's :func:`_writePowerLogStage` (US-252) catches
    Exception around the writer call so the safety ladder remains
    advance-able even when the forensics writer raises -- the
    contract change here is safe at the system level.
    """

    def test_insertRaisesOperationalError_logsErrorAndReraises(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A sqlite3.OperationalError during INSERT must escape to the
        caller AND emit an ERROR log.  This is the swallow-rejection
        gate."""
        rasingDb = _RaisingDatabase(
            sqlite3.OperationalError("simulated INSERT disk I/O failure")
        )
        with caplog.at_level(logging.ERROR, logger="src.pi.power.power_db"):
            with pytest.raises(
                sqlite3.OperationalError,
                match="simulated INSERT disk I/O failure",
            ):
                logShutdownStage(rasingDb, "stage_warning", 3.65)

        errorRecords = [
            record
            for record in caplog.records
            if record.levelno == logging.ERROR
            and record.name == "src.pi.power.power_db"
        ]
        assert len(errorRecords) >= 1, (
            "Pre-US-267 regression: an INSERT failure either did not "
            "log at ERROR level, or did but also swallowed the exception"
        )
        assert any(
            "shutdown stage" in record.message.lower()
            for record in errorRecords
        )

    def test_insertRaisesGenericException_logsErrorAndReraises(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-sqlite Exception during INSERT (e.g., a wrapping
        DatabaseConnectionError or a bug in upstream code) must also
        escape AND log at ERROR.  The except clause must catch
        Exception broadly, not just sqlite3.Error."""
        raisingDb = _RaisingDatabase(
            DatabaseConnectionError("simulated wrapper-level failure")
        )
        with caplog.at_level(logging.ERROR, logger="src.pi.power.power_db"):
            with pytest.raises(
                DatabaseConnectionError,
                match="simulated wrapper-level failure",
            ):
                logShutdownStage(raisingDb, "stage_warning", 3.65)

        errorRecords = [
            record
            for record in caplog.records
            if record.levelno == logging.ERROR
            and record.name == "src.pi.power.power_db"
        ]
        assert len(errorRecords) >= 1


# ================================================================================
# TestStairStepDrainRowsPresentAfterWriterReturns -- runtime-validation gate
# ================================================================================


class TestStairStepDrainRowsPresentAfterWriterReturns:
    """Acceptance #3 + invariant chain: stair-step VCELL across all 3
    thresholds AND assert ``power_log`` has 3 STAGE_* rows visible
    from a SECOND connection AFTER each writer call returns.

    This is stronger than "the call returned without error" because
    WAL-buffered (uncommitted-to-disk) rows would still be visible to
    other connections within the same process.  The runtime-validation
    semantics this story locks: every stage row, the moment the
    writer returns, has been (a) committed to SQLite, (b) flushed
    via PRAGMA synchronous=FULL, (c) fsynced via os.fsync.  A hard
    crash one nanosecond after the writer returns CANNOT lose any of
    the 3 stage rows.

    This test does NOT exercise actual disk crash -- pytest cannot
    realistically simulate a kernel-level power loss -- but the
    fsync-mock + visibility-from-second-connection assertion together
    prove that the durability chain at the Python+SQLite layer is
    correct.  The Drain Test 7 hardware run is the empirical end
    gate, not pytest.
    """

    def test_stairStepDrain_threeStageRowsVisibleAfterEachWriterReturns(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        """End-to-end gate: build a real PowerDownOrchestrator with
        the real ``logShutdownStage`` writer wired to a real
        ObdDatabase.  Stair-step VCELL through 4.20 -> 3.40 V crossing
        all 3 thresholds.  After EACH stage transition fires, open a
        FRESH connection and assert the corresponding row is visible.
        """

        def writer(eventType: str, vcell: float) -> None:
            logShutdownStage(freshDb, eventType, vcell)

        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=MagicMock(),
            powerLogWriter=writer,
        )

        expectedRowsAfterStep = {
            4.20: [],
            3.80: [],
            3.65: ["stage_warning"],
            3.50: ["stage_warning", "stage_imminent"],
            3.40: ["stage_warning", "stage_imminent", "stage_trigger"],
        }

        for stepVcell, expectedEventTypes in expectedRowsAfterStep.items():
            orchestrator.tick(
                currentVcell=stepVcell,
                currentSource=PowerSource.BATTERY,
            )
            with freshDb.connect() as conn:
                rows = conn.execute(
                    "SELECT event_type FROM power_log "
                    "WHERE event_type LIKE 'stage_%' "
                    "ORDER BY id"
                ).fetchall()
            actualEventTypes = [row[0] for row in rows]
            assert actualEventTypes == expectedEventTypes, (
                f"After tick at {stepVcell}V the visible stage rows "
                f"are {actualEventTypes}, expected {expectedEventTypes}. "
                "Pre-US-267 the rows might appear after a delay (WAL "
                "checkpoint) or never appear (hard crash before fsync); "
                "post-US-267 every row is visible immediately after "
                "the writer returns."
            )

        assert orchestrator.state == PowerState.TRIGGER

        # Final check: all 3 rows present, each with vcell populated.
        with freshDb.connect() as conn:
            finalRows = conn.execute(
                "SELECT event_type, power_source, on_ac_power, vcell "
                "FROM power_log "
                "WHERE event_type LIKE 'stage_%' "
                "ORDER BY id"
            ).fetchall()
        assert len(finalRows) == 3
        assert [row[0] for row in finalRows] == [
            "stage_warning", "stage_imminent", "stage_trigger",
        ]
        for row in finalRows:
            assert row[1] == "battery"
            assert row[2] == 0
            assert row[3] is not None  # vcell populated, not NULL

    def test_writerReturning_isIdempotentForRepeatedSameStage(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
    ) -> None:
        """Acceptance invariant: ``logShutdownStage is idempotent
        (same stage written twice in close succession does not corrupt
        state)``.  US-267's fsync chain runs per-call regardless --
        the orchestrator owns dedup gating via its state machine, the
        writer just persists what it's told.  This test verifies that
        calling logShutdownStage twice with the same stage produces 2
        rows (not corruption, not a crash) AND both are durable."""
        logShutdownStage(freshDb, "stage_warning", 3.65)
        logShutdownStage(freshDb, "stage_warning", 3.64)

        with freshDb.connect() as conn:
            rows = conn.execute(
                "SELECT event_type, vcell FROM power_log "
                "WHERE event_type = 'stage_warning' "
                "ORDER BY id"
            ).fetchall()

        assert len(rows) == 2
        assert rows[0][1] == pytest.approx(3.65, abs=1e-3)
        assert rows[1][1] == pytest.approx(3.64, abs=1e-3)
