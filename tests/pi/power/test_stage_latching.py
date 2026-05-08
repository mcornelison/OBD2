################################################################################
# File Name: test_stage_latching.py
# Purpose/Description: US-288 stage state-machine latching synthetic test
#                      (Spool Story 5).  Drain analysis showed 7 WARNING + 6
#                      IMMINENT but only 4 TRIGGER rows across 4 drain tests --
#                      multiple WARNING/IMMINENT rows per actual power-down
#                      cycle pollute downstream analytics.  Pattern fix:
#                      monotonic stage progression.  Once the orchestrator
#                      advances to a stage, that stage's _enterX must NOT re-
#                      fire even if VCELL hysteresis fluctuates the state
#                      attribute back to NORMAL.  TRIGGER atomicity already
#                      good (Sprint 21 US-252 _shutdownFired flag).
#                      Discriminator: TestWarningRefireAfterHysteresisDrop
#                      FAILS pre-fix because _enterWarning re-fires on every
#                      tick where state == NORMAL and currentVcell <=
#                      warningVcell, including after a hysteresis-induced
#                      de-escalation back to NORMAL.  Post-fix the high-water
#                      stage attribute (set by _enterX, reset by _acRestore)
#                      blocks the re-fire while preserving the existing 0.05V
#                      hysteresis de-escalation invariant.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-07    | Rex (US-288) | Initial -- 5 tests across 3 classes pinning
#                              | the WARNING/IMMINENT latching invariant.
#                              | Pre-fix the WARNING-after-hysteresis-recovery
#                              | re-fire test FAILS (warningCount == 2);
#                              | post-fix it PASSES (warningCount == 1) while
#                              | the existing US-234 hysteresis de-escalation
#                              | tests in test_orchestrator_vcell_hysteresis.py
#                              | continue to pass unchanged (latching is
#                              | orthogonal to hysteresis per US-288 invariant).
# ================================================================================
################################################################################

"""US-288 stage state-machine latching synthetic test.

Background
----------
Spool's drain analysis (sprint26 P0 spec note, 2026-05-05) showed that across
the 4 drain tests the orchestrator emitted 7 ``stage_warning`` rows and 6
``stage_imminent`` rows -- but only 4 ``stage_trigger`` rows.  The TRIGGER
atomicity is good (Sprint 21 US-252 ``_shutdownFired`` flag); the WARNING and
IMMINENT paths re-fire on every tick that satisfies the gating condition,
even after a hysteresis-induced de-escalation returns ``_state`` to NORMAL.

Failure mode mechanics
----------------------
Existing :meth:`PowerDownOrchestrator.tick` body (pre-US-288)::

    if (
        self._state == PowerState.NORMAL
        and currentVcell <= self._thresholds.warningVcell
    ):
        self._enterWarning(currentVcell)
    ...

The ``_state == NORMAL`` gate is satisfied AGAIN after ``_deEscalateWarning
ToNormal`` runs at VCELL >= 3.75V (warningVcell + hysteresisVcell).  A
subsequent drop below 3.70V re-enters WARNING and writes another
``stage_warning`` row to ``power_log`` (and another drain-event row to
``battery_health_log``).  Each oscillation across the threshold doubles the
forensic noise without any actual change in physical state.

Fix
---
US-288 introduces a separate ``_highWaterStage`` attribute that tracks the
highest stage entered in the current drain event.  The escalation gates use
``_highWaterStage`` instead of ``_state``: WARNING fires only if high-water
is NORMAL; IMMINENT fires only if high-water is in {NORMAL, WARNING}.
``_acRestore`` resets the high-water mark to NORMAL (a real AC restoration
ends the drain event; a fresh battery cycle should fire all 3 stages
again).  Hysteresis de-escalation continues to mutate ``_state`` (preserving
the US-234 invariant that VCELL recovery above 3.75V returns the state
machine to NORMAL) but does NOT reset ``_highWaterStage``.

Test fidelity
-------------
Mocks operate at :class:`I2cClient.readWord` per the runtime-validation-
required rule (mirror US-234 + US-279 patterns; the pre-WARNING tick at
4.10V seeds ``_highestBatteryVcell`` so battery_health_log captures the
true drain-start VCELL).  ``shutdownAction`` is a :class:`MagicMock` so
TRIGGER paths can run without invoking ``systemctl poweroff``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.pi.hardware.ups_monitor import (
    CRATE_DISABLED_RAW,
    REGISTER_CRATE,
    REGISTER_SOC,
    REGISTER_VCELL,
    PowerSource,
    UpsMonitor,
)
from src.pi.obdii.database import ObdDatabase
from src.pi.power.battery_health import (
    BATTERY_HEALTH_LOG_TABLE,
    BatteryHealthRecorder,
)
from src.pi.power.orchestrator import (
    PowerDownOrchestrator,
    PowerState,
    ShutdownThresholds,
)

# ================================================================================
# I2C-level mock — same shape as test_orchestrator_vcell_hysteresis.py
# ================================================================================

_VCELL_LSB_V = 78.125e-6


def _vcellWordLittleEndian(volts: float) -> int:
    raw = int(round(volts / _VCELL_LSB_V))
    bigEndian = raw & 0xFFFF
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


def _socWordLittleEndian(percent: int) -> int:
    bigEndian = (percent & 0xFF) << 8
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


class _MockI2cClient:
    def __init__(self, vcellVolts: float, socPercent: int = 60):
        self.vcellVolts = vcellVolts
        self.socPercent = socPercent

    def setVcell(self, volts: float) -> None:
        self.vcellVolts = volts

    def readWord(self, address: int, register: int) -> int:
        if register == REGISTER_VCELL:
            return _vcellWordLittleEndian(self.vcellVolts)
        if register == REGISTER_SOC:
            return _socWordLittleEndian(self.socPercent)
        if register == REGISTER_CRATE:
            return CRATE_DISABLED_RAW
        return 0x0000

    def close(self) -> None:
        pass


# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "test_us288_stage_latching.db"), walMode=False)
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
def mockI2c() -> _MockI2cClient:
    return _MockI2cClient(vcellVolts=4.10)


@pytest.fixture()
def upsMonitor(mockI2c: _MockI2cClient) -> UpsMonitor:
    return UpsMonitor(i2cClient=mockI2c)


def _drainStep(
    orchestrator: PowerDownOrchestrator,
    upsMonitor: UpsMonitor,
    mockI2c: _MockI2cClient,
    vcell: float,
) -> None:
    """Mock a single VCELL reading + tick on BATTERY at the given volts."""
    mockI2c.setVcell(vcell)
    orchestrator.tick(
        currentVcell=upsMonitor.getVcell(),
        currentSource=PowerSource.BATTERY,
    )


# ================================================================================
# Discriminator tests -- WARNING re-fire after hysteresis recovery
# ================================================================================


class TestWarningRefireAfterHysteresisDrop:
    """The pre-US-288 discriminator: WARNING re-fires after hysteresis.

    Pre-fix the WARNING gate is ``state == NORMAL``.  After hysteresis
    de-escalates state from WARNING to NORMAL (VCELL recovers above 3.75V),
    a subsequent drop below 3.70V satisfies the gate AGAIN and ``_enterWarning``
    runs a second time -- second drain-event row, second ``stage_warning``
    power_log entry, second ``onWarning`` callback invocation.

    Post-fix the gate is ``_highWaterStage == NORMAL`` (a separate attribute
    set by ``_enterWarning`` and reset only by ``_acRestore``).  Hysteresis
    de-escalation continues to mutate ``_state`` for the US-234 invariant
    but does NOT reset the high-water mark, so the second drop is a no-op.
    """

    def test_warning_does_not_refire_after_hysteresis_recovery_then_drop(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """3.65V (WARNING) -> 3.80V (de-escalate to NORMAL) -> 3.65V should
        NOT re-enter WARNING.

        Pre-fix: warningCount == 2 (FAIL).
        Post-fix: warningCount == 1 (PASS).
        """
        warningCount: list[int] = [0]

        def onWarning() -> None:
            warningCount[0] += 1

        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=MagicMock(),
            onWarning=onWarning,
        )

        _drainStep(orchestrator, upsMonitor, mockI2c, 4.10)
        _drainStep(orchestrator, upsMonitor, mockI2c, 3.65)
        assert orchestrator.state == PowerState.WARNING
        assert warningCount[0] == 1

        _drainStep(orchestrator, upsMonitor, mockI2c, 3.80)
        assert orchestrator.state == PowerState.NORMAL

        _drainStep(orchestrator, upsMonitor, mockI2c, 3.65)
        assert warningCount[0] == 1

    def test_warning_refire_does_not_open_second_drain_event(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """Latching also gates ``BatteryHealthRecorder.startDrainEvent``.

        Pre-fix the second WARNING entry opens a SECOND
        ``battery_health_log`` row -- 4 drains produce 7 rows.
        Post-fix exactly 1 row exists per drain event.
        """
        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=MagicMock(),
        )

        _drainStep(orchestrator, upsMonitor, mockI2c, 4.10)
        _drainStep(orchestrator, upsMonitor, mockI2c, 3.65)
        _drainStep(orchestrator, upsMonitor, mockI2c, 3.80)
        _drainStep(orchestrator, upsMonitor, mockI2c, 3.65)

        with freshDb.connect() as conn:
            rowCount = conn.execute(
                f"SELECT COUNT(*) FROM {BATTERY_HEALTH_LOG_TABLE}"
            ).fetchone()[0]
        assert rowCount == 1


# ================================================================================
# IMMINENT latching -- forward escalation after de-escalation + no re-fire
# ================================================================================


class TestImminentLatching:
    """IMMINENT may still fire after a WARNING-band de-escalation, but
    must not re-fire once entered.

    Forward path: when ``_highWaterStage`` is WARNING and ``_state`` is
    NORMAL (after hysteresis), VCELL dropping to 3.55V SHOULD escalate
    directly to IMMINENT (skipping a WARNING re-fire that the latch
    blocks).  This is the post-US-288 escalation behavior.

    Reverse path: once IMMINENT has fired, subsequent ticks at the IMMINENT
    threshold do NOT re-fire IMMINENT.  Pre-fix this is already true
    because the existing ``state == WARNING`` gate fails when state is
    IMMINENT; post-fix the ``_highWaterStage in {NORMAL, WARNING}`` gate
    fails for the same reason.  The test pins the post-fix invariant
    against future regressions of the gate condition.
    """

    def test_imminent_fires_once_after_warning_de_escalation_then_drop(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """Path: 3.65 (WARN) -> 3.80 (de-escalate) -> 3.50 (-> IMMINENT).

        WARNING does NOT re-fire (latched).  IMMINENT DOES fire because
        the forward gate ``_highWaterStage in (NORMAL, WARNING)`` is
        satisfied when high-water is WARNING.  This is the post-fix
        forward-escalation contract: skipping a stage on the way up is
        allowed; re-firing a stage already entered is not.
        """
        warningCount: list[int] = [0]
        imminentCount: list[int] = [0]

        def onWarning() -> None:
            warningCount[0] += 1

        def onImminent() -> None:
            imminentCount[0] += 1

        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=MagicMock(),
            onWarning=onWarning,
            onImminent=onImminent,
        )

        _drainStep(orchestrator, upsMonitor, mockI2c, 4.10)
        _drainStep(orchestrator, upsMonitor, mockI2c, 3.65)
        _drainStep(orchestrator, upsMonitor, mockI2c, 3.80)
        _drainStep(orchestrator, upsMonitor, mockI2c, 3.50)

        assert warningCount[0] == 1
        assert imminentCount[0] == 1
        assert orchestrator.state == PowerState.IMMINENT

    def test_imminent_does_not_refire_at_imminent_threshold(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """Repeated ticks at VCELL=3.50V on BATTERY fire IMMINENT exactly once."""
        imminentCount: list[int] = [0]

        def onImminent() -> None:
            imminentCount[0] += 1

        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=MagicMock(),
            onImminent=onImminent,
        )

        for vcell in (4.10, 3.65, 3.50, 3.50, 3.50):
            _drainStep(orchestrator, upsMonitor, mockI2c, vcell)

        assert imminentCount[0] == 1


# ================================================================================
# Latching guardrails -- invariants the fix must not break
# ================================================================================


class TestLatchingGuardrails:
    """TRIGGER atomicity + AC-restore reset + single-tick fall-through."""

    def test_trigger_atomicity_preserved_with_latching(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """Single-tick fast drop 4.10 -> 3.40 fires each stage exactly once.

        Falls through NORMAL -> WARNING -> IMMINENT -> TRIGGER in one tick;
        ``shutdownAction`` is invoked once.  Subsequent ticks at 3.40V on
        BATTERY are no-ops (terminal TRIGGER state).
        """
        shutdownMock = MagicMock()
        warningCount: list[int] = [0]
        imminentCount: list[int] = [0]

        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownMock,
            onWarning=lambda: warningCount.__setitem__(0, warningCount[0] + 1),
            onImminent=lambda: imminentCount.__setitem__(0, imminentCount[0] + 1),
        )

        _drainStep(orchestrator, upsMonitor, mockI2c, 4.10)
        _drainStep(orchestrator, upsMonitor, mockI2c, 3.40)
        _drainStep(orchestrator, upsMonitor, mockI2c, 3.40)

        assert warningCount[0] == 1
        assert imminentCount[0] == 1
        assert shutdownMock.call_count == 1
        assert orchestrator.state == PowerState.TRIGGER

    def test_ac_restore_resets_high_water_allowing_full_relatch(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """A fresh BATTERY drain after an AC restore re-fires every stage.

        Cycle 1: 4.10 -> 3.65 -> WARNING fires.
        AC restore: state -> NORMAL, high-water reset to NORMAL.
        Cycle 2: 3.65 -> WARNING fires AGAIN (high-water was reset by
        the AC restore -- the "drain event" boundary).
        """
        warningCount: list[int] = [0]
        acRestoreCount: list[int] = [0]

        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=MagicMock(),
            onWarning=lambda: warningCount.__setitem__(0, warningCount[0] + 1),
            onAcRestore=lambda: acRestoreCount.__setitem__(0, acRestoreCount[0] + 1),
        )

        _drainStep(orchestrator, upsMonitor, mockI2c, 4.10)
        _drainStep(orchestrator, upsMonitor, mockI2c, 3.65)
        assert warningCount[0] == 1

        # AC restore -- state goes NORMAL, high-water reset.
        mockI2c.setVcell(3.95)
        orchestrator.tick(
            currentVcell=upsMonitor.getVcell(),
            currentSource=PowerSource.EXTERNAL,
        )
        assert orchestrator.state == PowerState.NORMAL
        assert acRestoreCount[0] == 1

        # New drain event -- WARNING must re-fire because the latch reset.
        _drainStep(orchestrator, upsMonitor, mockI2c, 4.10)
        _drainStep(orchestrator, upsMonitor, mockI2c, 3.65)
        assert warningCount[0] == 2
