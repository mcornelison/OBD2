################################################################################
# File Name: test_drive_detector_warm_restart_e2e.py
# Purpose/Description: US-311 / I-019 -- end-to-end warm-restart drive lifecycle
#                      Test A/B/C protocol.  Discriminator for the orchestrator
#                      one-shot ``_engineOnEscalated`` flag that swallows
#                      drive_start on the second engine-on cycle in the same
#                      process (Drive 8 -> around-the-block -> Drive 9 orphan
#                      window 1078 NULL-tagged rows on chi-eclipse-01
#                      2026-05-09 evening).
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex (US-311) | Initial -- A/B/C protocol composes the same
#                              | Sprint-20 trio as test_drive_lifecycle_cold_
#                              | start.py but drives THREE engine-on cycles in
#                              | one process so a regression of the warm-restart
#                              | escalation re-arm surfaces.  Pre-US-311 code:
#                              | Drive A escalates fine, Drive A ends, Drive B
#                              | BATTERY_V trace cannot re-escalate (one-shot
#                              | flag), drive_id never minted -> Test B FAILS.
# ================================================================================
################################################################################

"""US-311 -- DriveDetector warm-restart Test A/B/C integration gate.

Live counterpart: I-019 -- Spool 2026-05-09 evening 3-drive test on
chi-eclipse-01.  Drive 8 captured cleanly (8268 rows, 459 rows/min);
~3 minute around-the-block within the next 37-min window produced
1,078 NULL-drive_id rows but NEVER fired drive_start; Drive 9 captured
again at 36 rows/min (12x lower, brownout-throttled).  PM ruled out
Spool's MIN_INTER_DRIVE_SECONDS debounce hypothesis (constant exists
but is not referenced) and surfaced four candidate paths.  Pre-flight
audit by this story isolates the actual root cause to the orchestrator
one-shot ``_engineOnEscalated`` flag in :class:`ApplicationOrchestrator`
(``core.py:368``): set True on first engine-on cycle and never reset,
so the second cycle's BATTERY_V > 13.8V trace finds the early-exit
``if self._engineOnEscalated: return False`` and silently fails to
inject the RPM probe that wakes :class:`DriveDetector` in idle-poll.

Test A/B/C protocol (synthetic counterpart to the I-019 IRL drill):

* **Test A** -- cold-start cycle.  BATTERY_V trace
  ``[12.7, 12.7, 11.4, 14.4, 14.4, 14.4]`` escalates exactly like
  Drive 5 baseline (offices/tuner/knowledge.md).  RPM probe fires;
  detector advances STOPPED -> STARTING -> RUNNING; drive_id=N is
  minted.  Drive A ends via RPM=0 debounce -> drive_id closes.

* **Test B** -- warm-restart cycle within the same process.  After
  Drive A's drive_end clears ``_engineOnEscalated`` (post-US-311),
  another ``[12.7, 11.4, 14.4, 14.4, 14.4]`` trace MUST re-trigger
  escalation -> RPM probe -> drive_id=N+1 minted.  THIS IS THE
  DISCRIMINATOR.  Pre-US-311 code: Drive A's escalation set the flag
  to True forever; Drive B's trace runs the early-exit branch on
  every BATTERY_V sample; no RPM probe fires; ``getCurrentDriveId()``
  stays at the closed Drive A id; the new-drive assertion FAILS.

* **Test C** -- third cycle.  Same shape as Test B; pins that the
  re-arm is per-drive (not just per-A->B), so a third drive in one
  process is also clean.  drive_id=N+2.

Mocks live at the same boundaries as test_drive_lifecycle_cold_start.py:

* ``_dataLogger.queryAndLogParameter`` returns RPM=800 (escalation
  probe surface).  Used three times in a clean run (once per drive).
* ``readingSnapshotSource.getLatestReadings`` is empty for the
  warm-restart cycles -- the defer-INSERT path is exercised in the
  cold-start sibling test, not here.  This test is exclusively about
  the escalation re-arm + drive_start firing.
* ``_syncClient.pushAllDeltas`` is mocked OK; counted to confirm one
  drive-end push per drive (3 total).

Discriminator (runtime-validation per ``feedback_runtime_validation_required``):

* Against pre-US-311 code, ``_handleDriveEnd`` does not call
  ``_resetEngineOnEscalation`` (the method does not exist).
  ``_engineOnEscalated`` stays True after Drive A; Drive B's
  ``[14.4, 14.4, 14.4]`` trace runs ``_maybeEscalateOnAlternatorActive
  Signature`` which early-exits at the first line; no RPM probe fires;
  detector state remains STOPPED; ``getCurrentDriveId()`` returns the
  Drive A id (already closed).  Assertion ``driveBId != driveAId`` FAILS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive.types import DriveState
from src.pi.obdii.drive_id import clearCurrentDriveId, getCurrentDriveId
from src.pi.obdii.orchestrator.core import ApplicationOrchestrator
from src.pi.sync.client import PushResult, PushStatus

# ================================================================================
# Helpers / fixtures
# ================================================================================


def _baseConfig() -> dict[str, Any]:
    """Tier-aware minimal config exercising the US-242 + US-311 seams."""
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "obdii": {
                "orchestrator": {
                    "engineOnVoltageThreshold": 13.8,
                    "engineOnSampleCount": 3,
                },
            },
            "analysis": {
                "driveStartRpmThreshold": 500,
                "driveStartDurationSeconds": 0.0,
                "driveEndRpmThreshold": 0,
                "driveEndDurationSeconds": 0.0,
                "triggerAfterDrive": False,
                "driveSummaryBackfillSeconds": 0,
            },
            "sync": {"enabled": False},
        },
        "server": {},
    }


def _makeReading(parameterName: str, value: float) -> MagicMock:
    """Build a LoggedReading-shaped mock the EventRouterMixin can route."""
    reading = MagicMock(spec=["parameterName", "value", "unit"])
    reading.parameterName = parameterName
    reading.value = value
    reading.unit = "V" if parameterName == "BATTERY_V" else None
    return reading


@pytest.fixture()
def warmRestartDb(tmp_path: Path) -> ObdDatabase:
    """On-disk DB; ``initialize()`` builds connection_log + drive_counter."""
    db = ObdDatabase(str(tmp_path / "test_us311_warm_restart.db"), walMode=False)
    db.initialize()
    yield db
    clearCurrentDriveId()


@pytest.fixture()
def warmRestartHarness(warmRestartDb: ObdDatabase) -> dict[str, Any]:
    """Wire ApplicationOrchestrator + DriveDetector for the A/B/C cycle.

    Mirrors ``coldStartHarness`` in test_drive_lifecycle_cold_start.py
    so the contracts under test compose identically; the only behavior
    delta is the warm-restart cycling itself.
    """
    config = _baseConfig()
    orchestrator = ApplicationOrchestrator(config=config, simulate=True)
    orchestrator._database = warmRestartDb

    detector = DriveDetector(config=config, database=warmRestartDb)
    detector.start()
    orchestrator._driveDetector = detector

    inner = MagicMock()
    inner.queryAndLogParameter = MagicMock(
        return_value=_makeReading("RPM", 800.0)
    )
    outer = MagicMock()
    outer._dataLogger = inner
    orchestrator._dataLogger = outer

    syncClient = MagicMock()
    syncClient.pushAllDeltas.return_value = [
        PushResult(
            tableName="drive_summary",
            rowsPushed=1,
            batchId="batch-warm",
            elapsed=0.001,
            status=PushStatus.OK,
            reason="",
        ),
    ]
    orchestrator._syncClient = syncClient
    orchestrator._syncTriggerOn = ["drive_end"]

    detector.registerCallbacks(
        onDriveEnd=orchestrator._handleDriveEnd,
    )

    return {
        "orchestrator": orchestrator,
        "detector": detector,
        "syncClient": syncClient,
        "innerDataLogger": inner,
    }


def _runEngineOnTrace(orchestrator: ApplicationOrchestrator) -> None:
    """Replay the canonical engine-on BATTERY_V trace (Drive 5 baseline)."""
    for voltage in [12.7, 11.4, 14.4, 14.4, 14.4]:
        orchestrator._handleReading(_makeReading("BATTERY_V", voltage))


def _runDriveEndTrace(detector: DriveDetector) -> None:
    """Drive RPM=0 sustained -- two ticks fire the zero-duration debounce."""
    detector.processValue("RPM", 0.0)
    detector.processValue("RPM", 0.0)


def _readDriveStartConnectionLog(
    db: ObdDatabase,
) -> list[tuple[int | None, str]]:
    """Return ``(drive_id, event_type)`` for every connection_log row,
    ordered by id.  Diagnostic surface for the A/B/C assertions."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT drive_id, event_type FROM connection_log "
            "WHERE event_type IN ('drive_start', 'drive_end') "
            "ORDER BY id ASC"
        ).fetchall()
    return [(r[0], r[1]) for r in rows]


# ================================================================================
# Acceptance: A/B/C cycle through one orchestrator process
# ================================================================================


class TestWarmRestartLifecycleEndToEnd:
    """I-019 / US-311 Test A/B/C protocol.

    One driving test that walks three engine-on cycles in the same
    orchestrator process and asserts each cycle mints a fresh drive_id.
    Per-cycle assertions surface which cycle's contract broke so a
    regression names which engine-on transition lost wake-up signal.
    """

    def test_warmRestart_threeCycles_eachMintsFreshDriveId(
        self, warmRestartHarness: dict[str, Any], warmRestartDb: ObdDatabase,
    ) -> None:
        orchestrator = warmRestartHarness["orchestrator"]
        detector = warmRestartHarness["detector"]
        syncClient = warmRestartHarness["syncClient"]
        innerDataLogger = warmRestartHarness["innerDataLogger"]

        # ============================================================
        # Test A: cold-start cycle -- escalation MUST fire and mint a
        # fresh drive_id.  Pre-US-242 territory; this is the existing
        # contract pinned by test_drive_lifecycle_cold_start.py.  Here
        # it serves as the baseline for the warm-restart discriminator.
        # ============================================================
        _runEngineOnTrace(orchestrator)

        assert orchestrator._engineOnEscalated is True, (
            "Test A: BATTERY_V trace [12.7, 11.4, 14.4 x3] MUST escalate."
        )
        # Second RPM tick fires _startDrive (zero-duration debounce);
        # the first tick was the escalation probe itself.
        detector.processValue("RPM", 800.0)
        assert detector.getDriveState() == DriveState.RUNNING

        driveAId = getCurrentDriveId()
        assert driveAId is not None, "Test A: drive_id MUST be minted."
        assert driveAId == 1
        assert innerDataLogger.queryAndLogParameter.call_count == 1

        _runDriveEndTrace(detector)
        assert detector.getDriveState() == DriveState.STOPPED
        assert getCurrentDriveId() is None, (
            "Test A: drive_id MUST clear on drive_end."
        )

        # ============================================================
        # Test B: warm-restart cycle within the SAME process.  This is
        # the I-019 discriminator: pre-US-311, ``_engineOnEscalated``
        # stays True after Drive A so the BATTERY_V trace runs the
        # early-exit branch in _maybeEscalateOnAlternatorActiveSignature
        # and the RPM probe never fires.  Detector stays at STOPPED;
        # no drive_id is minted; getCurrentDriveId() stays None.
        #
        # POST-US-311: _handleDriveEnd resets _engineOnEscalated and
        # _consecutiveAlternatorActiveSamples on every drive_end so the
        # next engine-on transition re-runs the escalation handshake
        # cleanly.
        # ============================================================
        assert orchestrator._engineOnEscalated is False, (
            "Test B precondition: _handleDriveEnd MUST clear "
            "_engineOnEscalated so the next cycle re-arms.  "
            "Pre-US-311 the flag stays True forever -- this assertion "
            "FAILS and pinpoints the warm-restart re-arm bug."
        )
        assert orchestrator._consecutiveAlternatorActiveSamples == 0, (
            "Test B precondition: the consecutive-sample counter MUST "
            "reset alongside the escalation flag so a single residual "
            "sample doesn't leak into the next cycle."
        )

        _runEngineOnTrace(orchestrator)

        assert orchestrator._engineOnEscalated is True, (
            "Test B: warm-restart BATTERY_V trace MUST re-escalate.  "
            "Pre-US-311 the early-exit at line 1117 of core.py "
            "(`if self._engineOnEscalated: return False`) swallows the "
            "trace silently -- this is the I-019 root cause."
        )
        detector.processValue("RPM", 800.0)
        assert detector.getDriveState() == DriveState.RUNNING

        driveBId = getCurrentDriveId()
        assert driveBId is not None, (
            "Test B: warm-restart drive MUST mint a NEW drive_id.  "
            "Pre-US-311 no escalation -> no probe -> no RPM tick to "
            "DriveDetector -> getCurrentDriveId() stays None.  This is "
            "exactly the around-the-block 1078-NULL-row failure mode "
            "captured on chi-eclipse-01 2026-05-09 evening."
        )
        assert driveBId == driveAId + 1, (
            f"Test B drive_id MUST be Drive A + 1 (monotonic counter); "
            f"got driveAId={driveAId} driveBId={driveBId}"
        )
        assert innerDataLogger.queryAndLogParameter.call_count == 2, (
            "Test B: queryAndLogParameter MUST be called a second time "
            "for the warm-restart escalation probe."
        )

        _runDriveEndTrace(detector)
        assert detector.getDriveState() == DriveState.STOPPED

        # ============================================================
        # Test C: third cycle.  Pins that the re-arm is PER-drive, not
        # just A->B.  Without per-drive reset, a fix that only handles
        # the first transition would still pass Test B and fail Test C.
        # ============================================================
        assert orchestrator._engineOnEscalated is False
        _runEngineOnTrace(orchestrator)
        assert orchestrator._engineOnEscalated is True
        detector.processValue("RPM", 800.0)
        assert detector.getDriveState() == DriveState.RUNNING

        driveCId = getCurrentDriveId()
        assert driveCId is not None, "Test C: drive_id MUST be minted."
        assert driveCId == driveBId + 1, (
            f"Test C drive_id MUST be Drive B + 1; "
            f"got driveBId={driveBId} driveCId={driveCId}"
        )
        assert innerDataLogger.queryAndLogParameter.call_count == 3

        _runDriveEndTrace(detector)
        assert detector.getDriveState() == DriveState.STOPPED

        # ============================================================
        # Cross-cycle invariants: connection_log carries six rows in
        # strict alternation, each pair sharing a drive_id; sync push
        # fires once per drive_end.
        # ============================================================
        events = _readDriveStartConnectionLog(warmRestartDb)
        assert events == [
            (driveAId, "drive_start"),
            (driveAId, "drive_end"),
            (driveBId, "drive_start"),
            (driveBId, "drive_end"),
            (driveCId, "drive_start"),
            (driveCId, "drive_end"),
        ], (
            f"connection_log MUST carry 3x (drive_start, drive_end) pairs "
            f"with monotonically increasing drive_id ({driveAId} < {driveBId} "
            f"< {driveCId}); got {events}.  Pre-US-311 only Drive A's pair "
            f"appears -- Drive B + Drive C never fire."
        )

        assert syncClient.pushAllDeltas.call_count == 3, (
            "Sync trigger MUST fire once per drive_end (3 total).  "
            "Pre-US-311 only Drive A's drive_end fires -> 1 sync push."
        )
