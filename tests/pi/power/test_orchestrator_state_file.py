################################################################################
# File Name: test_orchestrator_state_file.py
# Purpose/Description: US-276 -- PowerDownOrchestrator writes
#                      /var/run/eclipse-obd/orchestrator-state.json on every
#                      tick via atomic-rename so the US-262 drain-forensics
#                      logger's pd_stage / pd_tick_count columns get real
#                      values instead of the unknown / -1 sentinels they have
#                      shown across Drains 6 and 7.  Pre-fix the writer side
#                      did not exist; all 4 tests below FAIL.  Post-fix they
#                      PASS.  Schema field names align with the reader at
#                      scripts/drain_forensics.py::_readOrchestratorState
#                      (pd_stage / pd_tick_count are load-bearing keys per
#                      US-276 stop-condition #2 -- "do NOT change reader").
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-02    | Rex (US-276) | Initial -- 4 tests per acceptance: happy-path
#                              | schema content + atomic-rename pattern +
#                              | PermissionError graceful + missing-dir
#                              | graceful.  Failure modes never propagate
#                              | from tick() (forensics MUST NOT block the
#                              | safety ladder).
# ================================================================================
################################################################################

"""US-276 orchestrator state-file writer.

Background
----------
US-262 (Sprint 22) shipped the drain-forensics logger which reads
``/var/run/eclipse-obd/orchestrator-state.json`` for the ``pd_stage``
and ``pd_tick_count`` CSV columns.  The reader was built but the
writer was never wired -- across Drains 6 and 7 those two columns
have been ``unknown`` / ``-1`` sentinels.  US-276 closes the gap:
:class:`PowerDownOrchestrator` writes the JSON file on every tick via
atomic-rename so the reader (running in a sibling systemd-timer
process) never sees a partial / corrupt file.

Schema (aligned with reader)
----------------------------
The reader at ``scripts/drain_forensics.py::_readOrchestratorState``
expects exactly two keys:

* ``pd_stage``   -- the orchestrator stage value (``normal`` /
  ``warning`` / ``imminent`` / ``trigger``).
* ``pd_tick_count`` -- monotonically increasing tick counter.

Per US-276 stop-condition #2 ("do NOT change reader"), those two keys
are load-bearing.  Spool's spec also asks for ``lastTickTimestamp``
(canonical ISO via :func:`utcIsoNow`), ``lastVcellRead`` (the most
recent VCELL value tick() consumed), and ``powerSource`` (the most
recent source value tick() consumed) as additive forensic fields --
not consumed by the reader today, but trivially extensible by future
analytics that mount the same JSON.

Failure isolation
-----------------
The state-file write happens at the END of :meth:`tick`.  Any
filesystem failure (PermissionError, missing parent directory, full
disk) is logged at ERROR but MUST NOT propagate -- a forensics
side-channel cannot block the safety ladder.  The two failure-mode
tests in :class:`TestStateFileFailureIsolation` enforce this rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pi.hardware.ups_monitor import PowerSource
from src.pi.obdii.database import ObdDatabase
from src.pi.power.battery_health import BatteryHealthRecorder
from src.pi.power.orchestrator import (
    PowerDownOrchestrator,
    PowerState,
    ShutdownThresholds,
)

# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "test_us276_state_file.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def recorder(freshDb: ObdDatabase) -> BatteryHealthRecorder:
    return BatteryHealthRecorder(database=freshDb)


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
def stateFilePath(tmp_path: Path) -> Path:
    """Per-test state file path under tmp_path so tests are independent.

    Production callers pass ``/var/run/eclipse-obd/orchestrator-state.json``
    which is created by US-277's deploy-pi.sh + systemd-tmpfiles.  Tests
    that simulate the missing-dir failure mode use a deeper path; happy-path
    tests place the file directly under tmp_path which always exists.
    """
    return tmp_path / "orchestrator-state.json"


@pytest.fixture()
def orchestrator(
    thresholds: ShutdownThresholds,
    recorder: BatteryHealthRecorder,
    stateFilePath: Path,
) -> PowerDownOrchestrator:
    """Orchestrator with the state file routed under tmp_path."""
    return PowerDownOrchestrator(
        thresholds=thresholds,
        batteryHealthRecorder=recorder,
        shutdownAction=MagicMock(),
        onWarning=MagicMock(),
        onImminent=MagicMock(),
        onAcRestore=MagicMock(),
        stateFilePath=stateFilePath,
    )


# ================================================================================
# Happy path: state file written with correct schema after every tick
# ================================================================================


class TestStateFileHappyPath:
    """One tick -> state file exists with the spec'd schema."""

    def test_oneTick_writesStateFile_withReaderRequiredKeys(
        self,
        orchestrator: PowerDownOrchestrator,
        stateFilePath: Path,
    ) -> None:
        """Reader at scripts/drain_forensics.py needs `pd_stage` + `pd_tick_count`.

        Stop-condition #2 of US-276: do NOT change reader.  The writer must
        emit those two keys verbatim.
        """
        orchestrator.tick(currentVcell=4.10, currentSource=PowerSource.BATTERY)

        assert stateFilePath.exists(), (
            f"State file not written at {stateFilePath}; tick() should write "
            "/var/run/eclipse-obd/orchestrator-state.json on every tick."
        )

        data = json.loads(stateFilePath.read_text(encoding='utf-8'))

        # Reader-required keys (US-276 stop-condition #2).
        assert data['pd_stage'] == 'normal'
        assert data['pd_tick_count'] == 1

    def test_oneTick_writesStateFile_withSpecAdditiveFields(
        self,
        orchestrator: PowerDownOrchestrator,
        stateFilePath: Path,
    ) -> None:
        """Spool's spec also asks for lastTickTimestamp / lastVcellRead /
        powerSource forensic fields.

        These are additive to the reader-required keys and document the
        last tick() call's inputs for future analytics.  ``lastTickTimestamp``
        uses :func:`utcIsoNow` per Sprint 14 US-202 standard (canonical
        ``YYYY-MM-DDTHH:MM:SSZ``).
        """
        orchestrator.tick(currentVcell=3.85, currentSource=PowerSource.BATTERY)

        data = json.loads(stateFilePath.read_text(encoding='utf-8'))

        # Spec additive fields.
        assert data['lastVcellRead'] == pytest.approx(3.85, abs=1e-6)
        assert data['powerSource'] == PowerSource.BATTERY.value
        # Canonical ISO format -- second-resolution UTC trailing 'Z'.
        ts = data['lastTickTimestamp']
        assert isinstance(ts, str)
        # Cheap shape check; canonical format is YYYY-MM-DDTHH:MM:SSZ.
        assert len(ts) == 20 and ts.endswith('Z')

    def test_multipleTicks_advanceTickCount_andUpdateStage(
        self,
        orchestrator: PowerDownOrchestrator,
        stateFilePath: Path,
    ) -> None:
        """Each tick rewrites the file; pd_tick_count advances and pd_stage
        reflects the post-tick state.
        """
        # Tick 1: still NORMAL above WARNING.
        orchestrator.tick(currentVcell=4.10, currentSource=PowerSource.BATTERY)
        data = json.loads(stateFilePath.read_text(encoding='utf-8'))
        assert data['pd_tick_count'] == 1
        assert data['pd_stage'] == 'normal'

        # Tick 2: cross WARNING (3.65V <= 3.70V).
        orchestrator.tick(currentVcell=3.65, currentSource=PowerSource.BATTERY)
        data = json.loads(stateFilePath.read_text(encoding='utf-8'))
        assert data['pd_tick_count'] == 2
        assert data['pd_stage'] == 'warning'
        assert orchestrator.state == PowerState.WARNING


# ================================================================================
# Atomic rename: writer must use os.replace via a .tmp sibling
# ================================================================================


class TestStateFileAtomicRename:
    """The reader (sibling process) must NEVER see a partial JSON file."""

    def test_writerUsesOsReplace_fromTmpSibling(
        self,
        orchestrator: PowerDownOrchestrator,
        stateFilePath: Path,
    ) -> None:
        """Verify the atomic-rename pattern: write to <path>.tmp, replace to
        final.  ``os.replace`` is atomic on POSIX (renameat2 on Linux) so
        the reader either sees the prior file or the new one -- never a
        partial.
        """
        with patch(
            'src.pi.power.orchestrator.os.replace', wraps=__import__('os').replace,
        ) as mockReplace:
            orchestrator.tick(
                currentVcell=4.10, currentSource=PowerSource.BATTERY,
            )

        assert mockReplace.call_count == 1, (
            f"Expected exactly 1 os.replace call (atomic rename); got "
            f"{mockReplace.call_count}"
        )
        callArgs = mockReplace.call_args
        srcArg, dstArg = callArgs[0][0], callArgs[0][1]
        # Source must be a sibling .tmp file under the same parent dir.
        assert str(srcArg).endswith('.tmp'), (
            f"Atomic rename source must be a .tmp sibling; got {srcArg!r}"
        )
        assert Path(srcArg).parent == stateFilePath.parent
        # Destination must be the canonical state file path.
        assert Path(dstArg) == stateFilePath
        # Post-rename the .tmp must NOT exist (rename moves the inode).
        assert not Path(srcArg).exists()


# ================================================================================
# Failure isolation: filesystem errors MUST NOT propagate from tick()
# ================================================================================


class TestStateFileFailureIsolation:
    """Forensics MUST NOT block the safety ladder.

    A filesystem failure (PermissionError, missing parent dir, full disk)
    in the state-file writer must be logged-and-swallowed; tick() returns
    cleanly and the state machine continues to function.
    """

    def test_permissionError_onWrite_doesNotPropagate_stateAdvances(
        self,
        orchestrator: PowerDownOrchestrator,
        stateFilePath: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Mock the file open to raise PermissionError; tick() must not raise."""
        # Drain to WARNING in one tick: 3.65V <= 3.70V.  The state advance
        # should happen BEFORE the failed state-file write, so the orchestrator
        # state still becomes WARNING.
        with patch(
            'src.pi.power.orchestrator.Path.open',
            side_effect=PermissionError("mock permission denied"),
        ):
            orchestrator.tick(
                currentVcell=3.65, currentSource=PowerSource.BATTERY,
            )

        # State machine still advanced.
        assert orchestrator.state == PowerState.WARNING

        # State file failure was logged at ERROR (or higher) -- the failure
        # is observable but never propagates.
        errorRecords = [
            r for r in caplog.records
            if r.levelno >= 40  # ERROR or higher
            and r.name == 'src.pi.power.orchestrator'
        ]
        assert errorRecords, (
            "PermissionError on state-file write must be logged at ERROR "
            "(observable failure) but never propagate."
        )

    def test_missingParentDir_doesNotCrashTick_logsErrorAndSkipsWrite(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Per US-276 stop-condition #1, the writer MUST NOT create the
        parent directory -- US-277's deploy-pi.sh + systemd-tmpfiles owns
        ``/var/run/eclipse-obd/`` provisioning.  When the parent is absent,
        the writer logs at ERROR and skips the write; tick() must still
        complete normally so the safety ladder advances.
        """
        deepPath = (
            tmp_path
            / "deeply" / "nested" / "missing" / "dir" / "orchestrator-state.json"
        )
        assert not deepPath.parent.exists()  # precondition

        orch = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=MagicMock(),
            stateFilePath=deepPath,
        )

        with caplog.at_level('ERROR', logger='src.pi.power.orchestrator'):
            orch.tick(currentVcell=4.10, currentSource=PowerSource.BATTERY)

        # tick advanced (state machine works); state-file write skipped.
        assert orch.tickCount == 1
        assert not deepPath.parent.exists(), (
            "Writer must NOT create the parent directory (US-277's "
            "responsibility per stop-condition #1)."
        )
        assert not deepPath.exists()

        # Failure was logged at ERROR (observable signal for ops).
        errorRecords = [
            r for r in caplog.records
            if r.levelno >= 40
            and r.name == 'src.pi.power.orchestrator'
        ]
        assert errorRecords, (
            "Missing-dir failure must be logged at ERROR (observable) "
            "even though it does not propagate."
        )
