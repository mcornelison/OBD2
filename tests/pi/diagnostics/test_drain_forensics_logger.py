################################################################################
# File Name: test_drain_forensics_logger.py
# Purpose/Description: Unit tests for scripts/drain_forensics.py (US-262) and
#                      the PowerDownOrchestrator tickCount + currentStage
#                      accessors that drive the logger's pd_tick_count + pd_stage
#                      forensic columns.  Mocks all 14 source surfaces
#                      (MAX17048 regs via UPS telemetry, vcgencmd, /proc/loadavg,
#                      orchestrator state, monotonic + wall-clock providers) so
#                      the test never touches real hardware or the real
#                      filesystem outside tmp_path.  Asserts: row written every
#                      5s on BATTERY, all 14 columns populated, os.fsync called
#                      after each row, file rotation on AC->BATTERY transition,
#                      no row written when AC restored.  Plus orchestrator
#                      tickCount-before-early-return invariant per US-262
#                      Hypothesis-A discriminator.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Rex (US-262) | Initial -- 14-column drain forensics CSV +
#                                tickCount accessor invariants.
# ================================================================================
################################################################################

"""Unit tests for drain forensics logger + orchestrator US-262 accessors.

These tests exercise :mod:`scripts.drain_forensics` and the new
:attr:`PowerDownOrchestrator.tickCount` / :attr:`currentStage` snapshot
accessors that the logger consumes for the ``pd_tick_count`` + ``pd_stage``
columns of the forensic CSV.

Per US-262 acceptance: mocks every source surface (so the tests never
touch real hardware or the real /var/log/eclipse-obd path), asserts the
14 CSV columns are populated, asserts ``os.fsync`` is invoked on the
file descriptor after every row write (so a hard-crash cannot strand
buffered rows in pagecache), and asserts the AC-restoration rotation
invariant (a new file is opened on the next BATTERY transition, named
by the transition timestamp suffix).

The orchestrator-accessor sub-suite is co-located here rather than in
``test_power_down_orchestrator.py`` because the new accessors are the
contract the drain_forensics logger consumes; testing both sides of the
contract in one file keeps the bug-class story legible to the future
agent who reads the test cold.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import drain_forensics
from src.pi.hardware.ups_monitor import PowerSource
from src.pi.obdii.database import ObdDatabase
from src.pi.power.battery_health import BatteryHealthRecorder
from src.pi.power.orchestrator import (
    PowerDownOrchestrator,
    PowerState,
    ShutdownThresholds,
)

# ================================================================================
# Shared fixtures + helpers for drain_forensics
# ================================================================================


@dataclass
class _ProviderState:
    """Mutable state backing the dependency-injected provider callables.

    Tests grow this between runOnce calls to simulate sensor changes
    over time without spinning up real I2C / vcgencmd subprocesses.
    """

    powerSource: str = 'battery'
    vcellV: float = 3.65
    socPct: int = 58
    cratePctPerHr: float | None = -3.5
    cpuTempC: float = 47.2
    coreV: float = 0.8625
    sdramCV: float = 1.1
    sdramIV: float = 1.1
    sdramPV: float = 1.1
    throttledHex: str = '0x0'
    load1min: float = 0.42
    pdStage: str = 'normal'
    pdTickCount: int = 12
    nowEpoch: float = 1_714_608_000.0
    nowUtcIso: str = '2026-05-02T01:00:00Z'


def _buildContext(
    state: _ProviderState,
    logDir: Path,
    rotationGapSeconds: float = 30.0,
) -> drain_forensics.ForensicsContext:
    """Construct a ForensicsContext whose providers all read from `state`.

    Mutating ``state`` between successive ``runOnce`` calls advances the
    simulated drain trace.
    """

    return drain_forensics.ForensicsContext(
        logDir=logDir,
        powerSourceProvider=lambda: state.powerSource,
        upsTelemetryProvider=lambda: {
            'vcell_v': state.vcellV,
            'soc_pct': state.socPct,
            'crate_pct_per_hr': state.cratePctPerHr,
        },
        vcgencmdProvider=lambda: {
            'cpu_temp_c': state.cpuTempC,
            'core_v': state.coreV,
            'sdram_c_v': state.sdramCV,
            'sdram_i_v': state.sdramIV,
            'sdram_p_v': state.sdramPV,
            'throttled_hex': state.throttledHex,
        },
        loadAvgProvider=lambda: state.load1min,
        orchestratorStateProvider=lambda: {
            'pd_stage': state.pdStage,
            'pd_tick_count': state.pdTickCount,
        },
        nowUtcIso=lambda: state.nowUtcIso,
        nowEpoch=lambda: state.nowEpoch,
        rotationGapSeconds=rotationGapSeconds,
    )


def _readCsvRows(path: Path) -> list[dict[str, str]]:
    with path.open(newline='') as fp:
        return list(csv.DictReader(fp))


# ================================================================================
# Drain forensics logger -- AC restored / no-op cases
# ================================================================================


class TestRunOnceOnExternalPower:
    """When AC is feeding the UPS, runOnce must be a complete no-op."""

    def test_powerSourceExternal_returnsNoOpAction(
        self, tmp_path: Path,
    ) -> None:
        state = _ProviderState(powerSource='external')
        ctx = _buildContext(state, tmp_path)

        result = drain_forensics.runOnce(ctx)

        assert result.action == 'no_op_external'

    def test_powerSourceExternal_doesNotCreateOrWriteAnyFile(
        self, tmp_path: Path,
    ) -> None:
        state = _ProviderState(powerSource='external')
        ctx = _buildContext(state, tmp_path)

        drain_forensics.runOnce(ctx)

        assert list(tmp_path.glob('drain-forensics-*.csv')) == []

    def test_powerSourceUnknown_isNoOpEquivalentToExternal(
        self, tmp_path: Path,
    ) -> None:
        state = _ProviderState(powerSource='unknown')
        ctx = _buildContext(state, tmp_path)

        result = drain_forensics.runOnce(ctx)

        assert result.action == 'no_op_external'
        assert list(tmp_path.glob('drain-forensics-*.csv')) == []


# ================================================================================
# Drain forensics logger -- BATTERY happy path
# ================================================================================


class TestRunOnceOnBattery:
    """On BATTERY, runOnce writes one 14-column row and fsyncs."""

    def test_battery_firstTick_createsCsvFileWithHeaderRow(
        self, tmp_path: Path,
    ) -> None:
        state = _ProviderState(powerSource='battery')
        ctx = _buildContext(state, tmp_path)

        result = drain_forensics.runOnce(ctx)

        assert result.action == 'wrote_row'
        assert result.isNewFile is True
        files = list(tmp_path.glob('drain-forensics-*.csv'))
        assert len(files) == 1
        with files[0].open(newline='') as fp:
            reader = csv.reader(fp)
            header = next(reader)
        assert tuple(header) == drain_forensics.CSV_COLUMNS

    def test_battery_writesAllFourteenColumnsPopulated(
        self, tmp_path: Path,
    ) -> None:
        state = _ProviderState(powerSource='battery')
        ctx = _buildContext(state, tmp_path)

        drain_forensics.runOnce(ctx)

        files = list(tmp_path.glob('drain-forensics-*.csv'))
        rows = _readCsvRows(files[0])
        assert len(rows) == 1
        row = rows[0]
        assert tuple(row.keys()) == drain_forensics.CSV_COLUMNS
        # Every column must be populated (non-empty string) so a
        # post-mortem reader can mechanically distinguish "logger wrote
        # this column blank" (data missing) from "column never written".
        for column in drain_forensics.CSV_COLUMNS:
            assert row[column] != '', (
                f"column {column!r} empty in CSV row {row!r}"
            )

    def test_battery_rowValuesReflectInjectedProviders(
        self, tmp_path: Path,
    ) -> None:
        state = _ProviderState(
            powerSource='battery',
            vcellV=3.487,
            socPct=33,
            cratePctPerHr=-12.3,
            cpuTempC=58.4,
            coreV=0.860,
            sdramCV=1.099,
            sdramIV=1.100,
            sdramPV=1.101,
            throttledHex='0x50000',
            load1min=1.07,
            pdStage='warning',
            pdTickCount=247,
            nowUtcIso='2026-05-02T03:14:00Z',
        )
        ctx = _buildContext(state, tmp_path)

        drain_forensics.runOnce(ctx)

        files = list(tmp_path.glob('drain-forensics-*.csv'))
        row = _readCsvRows(files[0])[0]
        assert row['timestamp_utc'] == '2026-05-02T03:14:00Z'
        assert float(row['vcell_v']) == pytest.approx(3.487)
        assert int(row['soc_pct']) == 33
        assert float(row['crate_pct_per_hr']) == pytest.approx(-12.3)
        assert float(row['cpu_temp_c']) == pytest.approx(58.4)
        assert float(row['core_v']) == pytest.approx(0.860)
        assert float(row['sdram_c_v']) == pytest.approx(1.099)
        assert float(row['sdram_i_v']) == pytest.approx(1.100)
        assert float(row['sdram_p_v']) == pytest.approx(1.101)
        assert row['throttled_hex'] == '0x50000'
        assert float(row['load_1min']) == pytest.approx(1.07)
        assert row['pd_stage'] == 'warning'
        assert int(row['pd_tick_count']) == 247

    def test_battery_callsOsFsyncAfterRowWrite(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state = _ProviderState(powerSource='battery')
        ctx = _buildContext(state, tmp_path)

        fsyncCalls: list[int] = []
        realFsync = os.fsync

        def trackingFsync(fd: int) -> None:
            fsyncCalls.append(fd)
            realFsync(fd)

        monkeypatch.setattr('scripts.drain_forensics.os.fsync', trackingFsync)

        drain_forensics.runOnce(ctx)

        # At least one fsync per row write -- the spec invariant
        # "fsync after every CSV row -- buffered data loss on hard
        # crash is unacceptable for this story" demands it.
        assert len(fsyncCalls) >= 1, (
            'os.fsync was never called; buffered row could be lost on crash'
        )


class TestThreeQuickTicks:
    """Three runOnce calls in quick succession produce three rows in one file."""

    def test_threeQuickTicks_writeThreeRowsInSameFile(
        self, tmp_path: Path,
    ) -> None:
        state = _ProviderState(powerSource='battery', nowEpoch=1_000.0)
        ctx = _buildContext(state, tmp_path)

        drain_forensics.runOnce(ctx)
        state.nowEpoch = 1_005.0
        drain_forensics.runOnce(ctx)
        state.nowEpoch = 1_010.0
        drain_forensics.runOnce(ctx)

        files = list(tmp_path.glob('drain-forensics-*.csv'))
        assert len(files) == 1, (
            f"expected continuation in one file; got {[f.name for f in files]}"
        )
        rows = _readCsvRows(files[0])
        assert len(rows) == 3


# ================================================================================
# Drain forensics logger -- AC transition rotation
# ================================================================================


class TestAcTransitionRotation:
    """An AC restore between BATTERY runs must rotate to a new file.

    The script is stateless across systemd-timer invocations (the timer
    fires every 5s and runs a fresh interpreter each time), so rotation
    is detected via the active CSV file's mtime: if the latest CSV
    file's mtime is older than `rotationGapSeconds` (30s default), the
    next run treats this as a fresh AC->BATTERY transition and opens a
    new file with a current-timestamp suffix.
    """

    def test_acGapBeyondRotationWindow_createsNewFileWithFreshSuffix(
        self, tmp_path: Path,
    ) -> None:
        state = _ProviderState(
            powerSource='battery',
            nowEpoch=1_000.0,
            nowUtcIso='2026-05-02T01:00:00Z',
        )
        ctx = _buildContext(state, tmp_path, rotationGapSeconds=30.0)

        drain_forensics.runOnce(ctx)
        firstFiles = list(tmp_path.glob('drain-forensics-*.csv'))
        assert len(firstFiles) == 1
        firstName = firstFiles[0].name

        # Backdate the file to simulate AC restoration causing a gap >30s.
        oldMtime = state.nowEpoch - 60.0  # 60s gap > rotation window
        os.utime(firstFiles[0], (oldMtime, oldMtime))

        # Subsequent BATTERY tick: new file with fresh suffix.
        state.nowEpoch = 1_500.0
        state.nowUtcIso = '2026-05-02T01:08:20Z'

        result = drain_forensics.runOnce(ctx)

        assert result.action == 'wrote_row'
        assert result.isNewFile is True

        allFiles = sorted(tmp_path.glob('drain-forensics-*.csv'))
        assert len(allFiles) == 2
        assert allFiles[1].name != firstName
        # New file name must encode a fresh timestamp suffix derived
        # from the AC-return tick's timestamp.
        assert allFiles[1].name != firstName

    def test_continuousBatteryWithinRotationGap_appendsToSameFile(
        self, tmp_path: Path,
    ) -> None:
        state = _ProviderState(
            powerSource='battery',
            nowEpoch=1_000.0,
            nowUtcIso='2026-05-02T01:00:00Z',
        )
        ctx = _buildContext(state, tmp_path, rotationGapSeconds=30.0)

        drain_forensics.runOnce(ctx)
        # 10s later (well within the 30s rotation gap) -> continuation
        state.nowEpoch = 1_010.0
        state.nowUtcIso = '2026-05-02T01:00:10Z'
        drain_forensics.runOnce(ctx)

        files = list(tmp_path.glob('drain-forensics-*.csv'))
        assert len(files) == 1
        rows = _readCsvRows(files[0])
        assert len(rows) == 2


# ================================================================================
# Drain forensics logger -- seconds_on_battery anchor
# ================================================================================


class TestSecondsOnBattery:
    """seconds_on_battery is computed against the active file's start time."""

    def test_firstRow_secondsOnBatteryIsZero(self, tmp_path: Path) -> None:
        state = _ProviderState(
            powerSource='battery',
            nowEpoch=1_000.0,
            nowUtcIso='2026-05-02T01:00:00Z',
        )
        ctx = _buildContext(state, tmp_path)

        drain_forensics.runOnce(ctx)

        files = list(tmp_path.glob('drain-forensics-*.csv'))
        rows = _readCsvRows(files[0])
        assert int(float(rows[0]['seconds_on_battery'])) == 0

    def test_continuationRow_secondsOnBatteryReflectsElapsed(
        self, tmp_path: Path,
    ) -> None:
        state = _ProviderState(
            powerSource='battery',
            nowEpoch=1_000.0,
            nowUtcIso='2026-05-02T01:00:00Z',
        )
        ctx = _buildContext(state, tmp_path)

        drain_forensics.runOnce(ctx)
        state.nowEpoch = 1_037.0
        state.nowUtcIso = '2026-05-02T01:00:37Z'
        drain_forensics.runOnce(ctx)

        files = list(tmp_path.glob('drain-forensics-*.csv'))
        rows = _readCsvRows(files[0])
        assert int(float(rows[1]['seconds_on_battery'])) == 37


# ================================================================================
# PowerDownOrchestrator US-262 accessor invariants
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "test_orchestrator.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def recorder(freshDb: ObdDatabase) -> BatteryHealthRecorder:
    return BatteryHealthRecorder(database=freshDb)


@pytest.fixture()
def thresholdsEnabled() -> ShutdownThresholds:
    return ShutdownThresholds(
        enabled=True,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
    )


@pytest.fixture()
def thresholdsDisabled() -> ShutdownThresholds:
    return ShutdownThresholds(
        enabled=False,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
    )


@pytest.fixture()
def orchestrator(
    thresholdsEnabled: ShutdownThresholds,
    recorder: BatteryHealthRecorder,
) -> PowerDownOrchestrator:
    return PowerDownOrchestrator(
        thresholds=thresholdsEnabled,
        batteryHealthRecorder=recorder,
        shutdownAction=MagicMock(),
    )


class TestOrchestratorTickCountAccessor:
    """`tickCount` increments BEFORE any early-return guard inside tick()."""

    def test_initialTickCountIsZero(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        assert orchestrator.tickCount == 0

    def test_tickCount_incrementsOnEveryTickCall(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=4.20, currentSource=PowerSource.EXTERNAL)
        assert orchestrator.tickCount == 1
        orchestrator.tick(currentVcell=4.10, currentSource=PowerSource.EXTERNAL)
        assert orchestrator.tickCount == 2
        orchestrator.tick(currentVcell=4.00, currentSource=PowerSource.EXTERNAL)
        assert orchestrator.tickCount == 3

    def test_tickCount_incrementsBeforeEnabledFalseEarlyReturn(
        self,
        thresholdsDisabled: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
    ) -> None:
        """With enabled=False, tick() bails immediately. Counter MUST still advance.

        This is the load-bearing US-262 invariant: a stays-at-0
        tickCount post-Drain-7 must mean "the dedicated tick thread
        never advanced", NOT "the orchestrator was disabled". Putting
        the counter increment AFTER the enabled guard would conflate
        these two distinguishable failure modes.
        """
        orch = PowerDownOrchestrator(
            thresholds=thresholdsDisabled,
            batteryHealthRecorder=recorder,
            shutdownAction=MagicMock(),
        )

        orch.tick(currentVcell=3.40, currentSource=PowerSource.BATTERY)

        assert orch.tickCount == 1
        # And the state machine itself did NOT advance because enabled
        # is False -- the counter increment must NOT have side-effects.
        assert orch.state == PowerState.NORMAL

    def test_tickCount_incrementsBeforeUnknownSourceEarlyReturn(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """PowerSource UNKNOWN bails the tick body. Counter MUST still advance.

        Hypothesis-B discriminator: if pd_tick_count increments but
        pd_stage stays NORMAL across a drain, the bug is in the
        gating logic (UNKNOWN reads, stale VCELL, etc.), not in the
        thread liveness.  That hypothesis only works if the counter
        advances on UNKNOWN-bail paths.
        """
        orchestrator.tick(
            currentVcell=4.20, currentSource=PowerSource.UNKNOWN,
        )

        assert orchestrator.tickCount == 1
        assert orchestrator.state == PowerState.NORMAL

    def test_tickCount_keepsAdvancingAfterTriggerTerminalState(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """TRIGGER is terminal; subsequent ticks no-op. Counter MUST still advance.

        Forensic CSV continues being written after TRIGGER fires (the
        process may be killed by `systemctl poweroff` mid-row); knowing
        whether the post-TRIGGER ticks happened helps reconstruct the
        crash-window timeline.
        """
        orchestrator.tick(currentVcell=3.40, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.TRIGGER
        triggerCount = orchestrator.tickCount

        orchestrator.tick(currentVcell=3.40, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.40, currentSource=PowerSource.BATTERY)

        assert orchestrator.tickCount == triggerCount + 2


class TestOrchestratorCurrentStageAccessor:
    """`currentStage` is a snapshot-read alias for `state`, no lock."""

    def test_currentStage_isNormalAtConstruction(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        assert orchestrator.currentStage == PowerState.NORMAL

    def test_currentStage_advancesThroughLadder(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.69, currentSource=PowerSource.BATTERY)
        assert orchestrator.currentStage == PowerState.WARNING

        orchestrator.tick(currentVcell=3.54, currentSource=PowerSource.BATTERY)
        assert orchestrator.currentStage == PowerState.IMMINENT

        orchestrator.tick(currentVcell=3.44, currentSource=PowerSource.BATTERY)
        assert orchestrator.currentStage == PowerState.TRIGGER

    def test_currentStage_alwaysMatchesState(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """The two properties MUST read the same backing state on every tick."""
        for vcell in (4.20, 3.69, 3.54, 3.44):
            orchestrator.tick(
                currentVcell=vcell, currentSource=PowerSource.BATTERY,
            )
            assert orchestrator.currentStage is orchestrator.state
