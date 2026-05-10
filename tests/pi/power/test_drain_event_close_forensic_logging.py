################################################################################
# File Name: test_drain_event_close_forensic_logging.py
# Purpose/Description: US-307 (BL-012 Option A) -- forensic instrumentation
#                      for PowerDownOrchestrator._closeDrainEvent. When the
#                      recorder's endDrainEvent raises, the except-handler log
#                      line must include the exception class name, the
#                      drain_event_id, and the caller context (which stage
#                      triggered the close). These fields discriminate the
#                      three Drain-9-class hypotheses (fsync race / silent
#                      exception swallow / Pi died before TRIGGER) on the next
#                      IRL drain capture. Behavior of UPDATE/COMMIT path is
#                      unchanged; only the failure log gets richer.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-09
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-09    | Rex (US-307) | Initial -- forensic logging regression gate.
# ================================================================================
################################################################################

"""Regression gate for US-307: enriched _closeDrainEvent failure logging.

The test forces the recorder's ``endDrainEvent`` to raise during the
TRIGGER / AC-restore / WARNING-to-NORMAL paths and asserts the resulting
log line carries (a) the exception class name, (b) the drain_event_id,
and (c) the caller context string. Pre-fix the log line lacks all three,
so every test in this module would FAIL (per the runtime-validation rule
in feedback_runtime_validation_required.md).
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.pi.hardware.ups_monitor import PowerSource
from src.pi.obdii.database import ObdDatabase
from src.pi.power.battery_health import BatteryHealthRecorder
from src.pi.power.orchestrator import PowerDownOrchestrator, ShutdownThresholds

# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "us307_forensic.db"), walMode=False)
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


def _makeRecorderWithFailingEnd(
    freshDb: ObdDatabase, exc: Exception,
) -> BatteryHealthRecorder:
    """Real recorder so startDrainEvent succeeds; endDrainEvent raises ``exc``."""
    recorder = BatteryHealthRecorder(database=freshDb)
    recorder.endDrainEvent = MagicMock(side_effect=exc)  # type: ignore[method-assign]
    return recorder


def _makeOrchestrator(
    recorder: BatteryHealthRecorder, thresholds: ShutdownThresholds,
) -> PowerDownOrchestrator:
    return PowerDownOrchestrator(
        thresholds=thresholds,
        batteryHealthRecorder=recorder,
        shutdownAction=MagicMock(),
        onWarning=MagicMock(),
        onImminent=MagicMock(),
        onAcRestore=MagicMock(),
    )


# ================================================================================
# Forensic logging on _closeDrainEvent failure
# ================================================================================


class TestCloseDrainEventForensicLogging:
    """Failure log includes type(e).__name__ + drain_event_id + caller."""

    def test_triggerPath_logsExceptionClassName(
        self,
        freshDb: ObdDatabase,
        thresholds: ShutdownThresholds,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        recorder = _makeRecorderWithFailingEnd(
            freshDb, ValueError("simulated close failure"),
        )
        orchestrator = _makeOrchestrator(recorder, thresholds)
        with caplog.at_level(logging.ERROR, logger="src.pi.power.orchestrator"):
            orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
            orchestrator.tick(currentVcell=3.55, currentSource=PowerSource.BATTERY)
            orchestrator.tick(currentVcell=3.45, currentSource=PowerSource.BATTERY)
        failureLines = [
            r.getMessage() for r in caplog.records
            if "failed to close drain event" in r.getMessage()
        ]
        assert len(failureLines) == 1
        assert "ValueError" in failureLines[0]

    def test_triggerPath_logsDrainEventId(
        self,
        freshDb: ObdDatabase,
        thresholds: ShutdownThresholds,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        recorder = _makeRecorderWithFailingEnd(
            freshDb, ValueError("boom"),
        )
        orchestrator = _makeOrchestrator(recorder, thresholds)
        with caplog.at_level(logging.ERROR, logger="src.pi.power.orchestrator"):
            orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
            orchestrator.tick(currentVcell=3.55, currentSource=PowerSource.BATTERY)
            orchestrator.tick(currentVcell=3.45, currentSource=PowerSource.BATTERY)
        failureLines = [
            r.getMessage() for r in caplog.records
            if "failed to close drain event" in r.getMessage()
        ]
        assert len(failureLines) == 1
        assert "drain_event_id=1" in failureLines[0]

    def test_triggerPath_logsCallerContext(
        self,
        freshDb: ObdDatabase,
        thresholds: ShutdownThresholds,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        recorder = _makeRecorderWithFailingEnd(
            freshDb, ValueError("boom"),
        )
        orchestrator = _makeOrchestrator(recorder, thresholds)
        with caplog.at_level(logging.ERROR, logger="src.pi.power.orchestrator"):
            orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
            orchestrator.tick(currentVcell=3.55, currentSource=PowerSource.BATTERY)
            orchestrator.tick(currentVcell=3.45, currentSource=PowerSource.BATTERY)
        failureLines = [
            r.getMessage() for r in caplog.records
            if "failed to close drain event" in r.getMessage()
        ]
        assert len(failureLines) == 1
        assert "caller=trigger" in failureLines[0]

    def test_acRestorePath_logsCallerAcRestore(
        self,
        freshDb: ObdDatabase,
        thresholds: ShutdownThresholds,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        recorder = _makeRecorderWithFailingEnd(
            freshDb, RuntimeError("boom"),
        )
        orchestrator = _makeOrchestrator(recorder, thresholds)
        # Open a drain event by entering WARNING, then AC-restore mid-drain.
        orchestrator.tick(currentVcell=3.65, currentSource=PowerSource.BATTERY)
        with caplog.at_level(logging.ERROR, logger="src.pi.power.orchestrator"):
            orchestrator.tick(
                currentVcell=3.65, currentSource=PowerSource.EXTERNAL,
            )
        failureLines = [
            r.getMessage() for r in caplog.records
            if "failed to close drain event" in r.getMessage()
        ]
        assert len(failureLines) == 1
        assert "RuntimeError" in failureLines[0]
        assert "caller=ac_restore" in failureLines[0]
        assert "drain_event_id=1" in failureLines[0]

    def test_warningToNormalPath_logsCallerWarningToNormal(
        self,
        freshDb: ObdDatabase,
        thresholds: ShutdownThresholds,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        recorder = _makeRecorderWithFailingEnd(
            freshDb, OSError("disk gone"),
        )
        orchestrator = _makeOrchestrator(recorder, thresholds)
        # WARNING -> hysteresis recovery to NORMAL while still on battery.
        orchestrator.tick(currentVcell=3.69, currentSource=PowerSource.BATTERY)
        with caplog.at_level(logging.ERROR, logger="src.pi.power.orchestrator"):
            orchestrator.tick(
                currentVcell=3.80, currentSource=PowerSource.BATTERY,
            )
        failureLines = [
            r.getMessage() for r in caplog.records
            if "failed to close drain event" in r.getMessage()
        ]
        assert len(failureLines) == 1
        assert "OSError" in failureLines[0]
        assert "caller=warning_to_normal" in failureLines[0]
        assert "drain_event_id=1" in failureLines[0]


# ================================================================================
# Behavior preservation -- US-307 must NOT change UPDATE/COMMIT semantics
# ================================================================================


class TestCloseDrainEventBehaviorUnchanged:
    """The except handler still swallows + clears _activeDrainEventId."""

    def test_failure_doesNotPropagate(
        self,
        freshDb: ObdDatabase,
        thresholds: ShutdownThresholds,
    ) -> None:
        """Exception in endDrainEvent must be caught (ladder must keep
        advancing so poweroff still fires)."""
        recorder = _makeRecorderWithFailingEnd(
            freshDb, ValueError("boom"),
        )
        orchestrator = _makeOrchestrator(recorder, thresholds)
        # If the except handler propagated, this tick chain would raise.
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.55, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.45, currentSource=PowerSource.BATTERY)
        # Shutdown action still fired exactly once.
        orchestrator._shutdownAction.assert_called_once()  # noqa: SLF001

    def test_failure_clearsActiveDrainEventId(
        self,
        freshDb: ObdDatabase,
        thresholds: ShutdownThresholds,
    ) -> None:
        recorder = _makeRecorderWithFailingEnd(
            freshDb, ValueError("boom"),
        )
        orchestrator = _makeOrchestrator(recorder, thresholds)
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.55, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.45, currentSource=PowerSource.BATTERY)
        assert orchestrator.activeDrainEventId is None
