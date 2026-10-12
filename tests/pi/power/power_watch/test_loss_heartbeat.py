################################################################################
# File Name: test_loss_heartbeat.py
# Purpose/Description: US-748 -- the 1 Hz power-loss heartbeat that turns
#                      time-to-death after a cut into a NUMBER read from SQLite
#                      on the next boot. Pins: rows land committed while the
#                      window runs; they SURVIVE a hard kill of the writing
#                      process; an unreadable gauge/PLD writes NULL, never a
#                      guess; a missing db is never created; the next-boot
#                      reader returns the last surviving elapsed; and the
#                      sequencer starts the heartbeat at handleOnBattery ENTRY
#                      without a failing hook ever blocking poweroff.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-14    | Rex (US-748) | Initial.
# ================================================================================
################################################################################

"""The power-loss heartbeat and its next-boot reader (US-748)."""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from src.pi.power.power_watch import __main__ as powerwatchMain
from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.power_watch.loss_heartbeat import (
    HEARTBEAT_DURATION_SEC,
    HEARTBEAT_INTERVAL_SEC,
    LOSS_HEARTBEAT_TABLE,
    PowerLossHeartbeat,
    ensureLossHeartbeatTable,
    readLatestLossHeartbeat,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FAST_INTERVAL_SEC = 0.02
_JOIN_TIMEOUT_SEC = 10.0


@pytest.fixture
def dbPath(tmp_path: Path) -> str:
    """An EXISTING, empty sqlite file (the writer never creates one)."""
    path = tmp_path / 'obd.db'
    sqlite3.connect(path).close()
    return str(path)


def _rows(dbPath: str) -> list[tuple]:
    with sqlite3.connect(dbPath) as conn:
        return conn.execute(
            f"SELECT loss_started_utc, seq, elapsed_s, vcell_v, power_lost "
            f"FROM {LOSS_HEARTBEAT_TABLE} ORDER BY id"
        ).fetchall()


def _raise() -> float:
    raise OSError("i2c bus gone")


def _seed(dbPath: str, lossUtc: str, elapsedList: list[float], vcell: float = 4.1) -> None:
    with sqlite3.connect(dbPath) as conn:
        ensureLossHeartbeatTable(conn)
        for seq, elapsed in enumerate(elapsedList):
            conn.execute(
                f"INSERT INTO {LOSS_HEARTBEAT_TABLE} (loss_started_utc, seq, "
                "elapsed_s, vcell_v, power_lost, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                (lossUtc, seq, elapsed, vcell - seq * 0.001, 1, lossUtc),
            )


# ================================================================================
# Grounded constants
# ================================================================================


def test_constants_matchAtlasGate_1HzFor60s() -> None:
    """
    Given: Atlas's Sprint 86 gate: "a durable 1 Hz heartbeat row ... for 60 s".
    When:  the shipped defaults are read.
    Then:  they are exactly that -- not re-tuned here.
    """
    assert HEARTBEAT_INTERVAL_SEC == 1.0
    assert HEARTBEAT_DURATION_SEC == 60.0


# ================================================================================
# Writer
# ================================================================================


class TestHeartbeatWrites:
    def test_window_writesContiguousRowsWithMonotonicElapsed_thenStops(self, dbPath: str) -> None:
        """
        Given: a heartbeat over a short window, gauge 4.18 V, PLD lost.
        When:  it runs to the end of its window.
        Then:  rows are one event, seq 0..n contiguous, elapsed ascending and
               never past the window, VCELL and power_lost recorded.
        """
        heartbeat = PowerLossHeartbeat(
            dbPath=dbPath, vcellFn=lambda: 4.18, isPowerLostFn=lambda: True,
            intervalSec=_FAST_INTERVAL_SEC, durationSec=0.2,
        )

        assert heartbeat.start() is True
        heartbeat._thread.join(timeout=_JOIN_TIMEOUT_SEC)

        rows = _rows(dbPath)
        assert len(rows) >= 3
        assert len({r[0] for r in rows}) == 1
        assert [r[1] for r in rows] == list(range(len(rows)))
        elapsed = [r[2] for r in rows]
        assert elapsed == sorted(elapsed)
        assert elapsed[0] >= 0.0 and elapsed[-1] <= 0.2
        assert all(r[3] == pytest.approx(4.18) and r[4] == 1 for r in rows)
        assert heartbeat.isRunning is False

    def test_start_returnsImmediately_andIgnoresSecondStartWhileRunning(self, dbPath: str) -> None:
        """
        Given: a heartbeat whose gauge read is slow.
        When:  start() is called twice.
        Then:  the first returns at once (the loss path is never held) and the
               second is ignored -- one loss, one series of rows.
        """
        heartbeat = PowerLossHeartbeat(
            dbPath=dbPath, vcellFn=lambda: time.sleep(0.3) or 4.0,
            isPowerLostFn=lambda: True, intervalSec=_FAST_INTERVAL_SEC, durationSec=0.5,
        )

        began = time.monotonic()
        first = heartbeat.start()
        tookSec = time.monotonic() - began
        second = heartbeat.start()
        heartbeat.stop(timeoutSec=_JOIN_TIMEOUT_SEC)

        assert first is True
        assert tookSec < 0.25
        assert second is False
        assert len({r[0] for r in _rows(dbPath)}) == 1

    def test_unreadableGaugeAndPld_writeNullRows_neverAGuess(self, dbPath: str) -> None:
        """
        Given: the gauge and the PLD both raise.
        When:  the heartbeat runs.
        Then:  rows are STILL written (their existence is the measurement) with
               vcell_v and power_lost NULL.
        """
        heartbeat = PowerLossHeartbeat(
            dbPath=dbPath, vcellFn=_raise, isPowerLostFn=_raise,
            intervalSec=_FAST_INTERVAL_SEC, durationSec=0.08,
        )

        heartbeat.start()
        heartbeat._thread.join(timeout=_JOIN_TIMEOUT_SEC)

        rows = _rows(dbPath)
        assert rows
        assert all(r[3] is None and r[4] is None for r in rows)

    def test_powerReturned_isRecordedAsZero(self, dbPath: str) -> None:
        """
        Given: PLD reads power PRESENT during the window.
        When:  rows are written.
        Then:  power_lost = 0, so a cancelled loss is not read as a death.
        """
        heartbeat = PowerLossHeartbeat(
            dbPath=dbPath, vcellFn=lambda: 4.1, isPowerLostFn=lambda: False,
            intervalSec=_FAST_INTERVAL_SEC, durationSec=0.05,
        )

        heartbeat.start()
        heartbeat._thread.join(timeout=_JOIN_TIMEOUT_SEC)

        assert all(r[4] == 0 for r in _rows(dbPath))

    def test_missingDatabase_isNeverCreated(self, tmp_path: Path) -> None:
        """
        Given: pi.database.path does not exist.
        When:  a loss starts the heartbeat.
        Then:  no database file is invented and nothing raises.
        """
        missing = tmp_path / 'nope' / 'obd.db'
        heartbeat = PowerLossHeartbeat(
            dbPath=str(missing), vcellFn=lambda: 4.1, isPowerLostFn=lambda: True,
            intervalSec=_FAST_INTERVAL_SEC, durationSec=0.05,
        )

        heartbeat.start()
        heartbeat.stop(timeoutSec=_JOIN_TIMEOUT_SEC)

        assert not missing.exists()
        assert not missing.parent.exists()


class TestRowsSurviveAHardKill:
    def test_writerProcessKilledMidWindow_committedRowsAreReadable(self, dbPath: str) -> None:
        """
        Given: a separate process running the REAL heartbeat against the db.
        When:  that process is hard-killed mid-window (no finally, no close).
        Then:  a fresh connection -- the next boot -- reads the rows it had
               committed, and their last elapsed is a number. A power cut is
               harsher than a kill; this pins that no row depends on the
               writer exiting cleanly.
        """
        script = textwrap.dedent(
            f"""
            import sys, time
            sys.path.insert(0, {str(_REPO_ROOT)!r})
            from src.pi.power.power_watch.loss_heartbeat import PowerLossHeartbeat
            hb = PowerLossHeartbeat(dbPath={dbPath!r}, vcellFn=lambda: 4.18,
                                    isPowerLostFn=lambda: True,
                                    intervalSec=0.05, durationSec=60.0)
            hb.start()
            print('started', flush=True)
            time.sleep(60)
            """
        )
        proc = subprocess.Popen(
            [sys.executable, '-c', script], stdout=subprocess.PIPE, text=True,
        )
        try:
            assert proc.stdout is not None
            assert proc.stdout.readline().strip() == 'started'
            deadline = time.monotonic() + _JOIN_TIMEOUT_SEC
            while time.monotonic() < deadline:
                try:
                    if len(_rows(dbPath)) >= 5:
                        break
                except sqlite3.OperationalError:
                    pass
                time.sleep(0.05)
        finally:
            proc.kill()
            proc.wait(timeout=_JOIN_TIMEOUT_SEC)

        summary = readLatestLossHeartbeat(dbPath)

        assert summary is not None
        assert summary.rowCount >= 5
        assert summary.lastElapsedS > 0.0
        assert summary.windowCompleted is False


# ================================================================================
# Next-boot reader
# ================================================================================


class TestNextBootReader:
    def test_latestEvent_lastElapsedIsTheNumber(self, dbPath: str) -> None:
        """
        Given: an older completed event and a newer one that stopped at 27 s.
        When:  the next boot reads the heartbeat.
        Then:  it reports the NEWER event, 28 rows, last elapsed 27.0 s, and
               NOT a completed window -- time-to-death is a number.
        """
        _seed(dbPath, '2026-09-14T16:04:44Z', [float(s) for s in range(61)])
        _seed(dbPath, '2026-09-14T16:40:03Z', [float(s) for s in range(28)], vcell=3.949)

        summary = readLatestLossHeartbeat(dbPath)

        assert summary is not None
        assert summary.lossStartedUtc == '2026-09-14T16:40:03Z'
        assert summary.rowCount == 28
        assert summary.lastElapsedS == 27.0
        assert summary.minVcellV == pytest.approx(3.949 - 27 * 0.001)
        assert summary.windowCompleted is False

    def test_fullWindow_isReportedAsOutlivingTheInstrument(self, dbPath: str) -> None:
        """
        Given: rows through the whole 60 s window.
        When:  read.
        Then:  windowCompleted -- the machine outlived the instrument, so the
               last elapsed is NOT a death time.
        """
        _seed(dbPath, '2026-09-14T17:00:00Z', [float(s) for s in range(61)])

        summary = readLatestLossHeartbeat(dbPath)

        assert summary is not None and summary.windowCompleted is True

    def test_noDbOrNoTable_isNone(self, dbPath: str, tmp_path: Path) -> None:
        """
        Given: a db without the table, and a path with no db.
        When:  read.
        Then:  None both times -- no fabricated summary, no table created.
        """
        assert readLatestLossHeartbeat(dbPath) is None
        assert readLatestLossHeartbeat(str(tmp_path / 'absent.db')) is None
        with sqlite3.connect(dbPath) as conn:
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE name=?", (LOSS_HEARTBEAT_TABLE,),
            ).fetchone() is None

    def test_bootReport_logsTheNumberBehindOneGreppablePrefix(
        self, dbPath: str, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Given: a loss whose rows stop at 27 s.
        When:  powerwatch starts and emits the prior-loss report.
        Then:  one WARNING line carries the prefix and the seconds.
        """
        _seed(dbPath, '2026-09-14T16:40:03Z', [float(s) for s in range(28)])

        with caplog.at_level(logging.INFO, logger=powerwatchMain.logger.name):
            summary = powerwatchMain.emitPriorLossHeartbeat(dbPath)

        assert summary is not None
        lines = [r for r in caplog.records if powerwatchMain.LOSS_HEARTBEAT_PREFIX in r.getMessage()]
        assert len(lines) == 1
        assert lines[0].levelno == logging.WARNING
        assert '27.0s' in lines[0].getMessage()
        assert 'TIME-TO-DEATH' in lines[0].getMessage()


# ================================================================================
# Sequencer wiring
# ================================================================================


def _sequencer(*, calls: list[str], onBattery, hook) -> ShutdownSequencer:
    return ShutdownSequencer(
        isOnBattery=onBattery,
        vcell=lambda: 4.18,
        runPipelineFn=lambda: calls.append('pipeline'),
        powerOffFn=lambda: calls.append('poweroff'),
        vcellFloor=3.50,
        totalCapSec=5.0,
        smoothingSec=0.0,
        smoothingPollSec=0.0,
        sleepFn=lambda _s: None,
        powerLossObservedFn=hook,
    )


class TestSequencerStartsTheHeartbeat:
    def test_hookRunsAtEntry_beforeThePipelineAndPoweroff(self) -> None:
        """
        Given: a confirmed sustained loss above the floor.
        When:  handleOnBattery runs.
        Then:  the heartbeat starts FIRST -- the 09-14 deaths came inside the
               window that follows.
        """
        calls: list[str] = []
        sequencer = _sequencer(
            calls=calls, onBattery=lambda: True, hook=lambda: calls.append('heartbeat'),
        )

        sequencer.handleOnBattery()

        assert calls == ['heartbeat', 'pipeline', 'poweroff']

    def test_hookRunsOnABlipToo(self) -> None:
        """
        Given: a loss signal that is gone by the smoothing check (a blip).
        When:  handleOnBattery runs.
        Then:  the heartbeat still started (its power_lost=0 rows say so) and
               nothing powered off.
        """
        calls: list[str] = []
        sequencer = _sequencer(
            calls=calls, onBattery=lambda: False, hook=lambda: calls.append('heartbeat'),
        )

        sequencer.handleOnBattery()

        assert calls == ['heartbeat']

    def test_raisingHook_neverBlocksPoweroff(self) -> None:
        """
        Given: a heartbeat hook that raises.
        When:  a real loss is handled.
        Then:  the pipeline and poweroff still run.
        """
        calls: list[str] = []

        def _boom() -> None:
            raise RuntimeError("heartbeat broke")

        sequencer = _sequencer(calls=calls, onBattery=lambda: True, hook=_boom)

        sequencer.handleOnBattery()

        assert calls == ['pipeline', 'poweroff']

    def test_mainWiresHeartbeatStartIntoTheSequencer(self) -> None:
        """
        Given: the powerwatch entrypoint source.
        When:  inspected.
        Then:  the sequencer is built with powerLossObservedFn bound to the
               heartbeat's start, and the prior-loss report is emitted -- a
               heartbeat constructed but never called is the construction-is-
               not-a-call defect Sprint 85 named.
        """
        source = Path(powerwatchMain.__file__).read_text(encoding='utf-8')

        # ⚠️ ARCH-031 widened this from the exact-spelling grep
        # 'powerLossObservedFn=lossHeartbeat.start' to "the heartbeat is IN the
        # loss-observed wiring". That slot is now COMPOSED -- load shedding runs
        # on the same edge -- so the old assertion failed on a spelling change
        # while the behaviour it guards was untouched. Scoping the search to the
        # slot keeps the defect it was written for (constructed but never
        # called) fully covered, without pinning the expression to one shape.
        assert 'powerLossObservedFn=' in source
        slot = source.split('powerLossObservedFn=', 1)[1].split('powerRestoredFn=', 1)[0]
        assert 'lossHeartbeat.start' in slot, (
            'the heartbeat must be WIRED into the loss-observed hook, not merely '
            'constructed'
        )
        assert 'emitPriorLossHeartbeat(dbPath)' in source
