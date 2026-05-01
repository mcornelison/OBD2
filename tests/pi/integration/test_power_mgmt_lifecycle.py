################################################################################
# File Name: test_power_mgmt_lifecycle.py
# Purpose/Description: US-259 power-management full-lifecycle integration test.
#                      Companion to test_power_mgmt_e2e_drain.py.  Whereas the
#                      drain test exercises one continuous trace, this one
#                      walks the FULL service-lifetime sequence:
#
#                          startup -> idle EXTERNAL -> wall-out -> BATTERY
#                          -> stage-firing -> systemctl poweroff
#                          -> [boot replay across the poweroff boundary]
#                          -> service restart -> idle EXTERNAL
#
#                      Two production-shaped instances run against the same
#                      ObdDatabase.  Instance 1 drains and TRIGGERs.  Instance
#                      2 simulates the post-boot service restart -- fresh
#                      UpsMonitor + recorder + orchestrator constructed
#                      anew, pointing at the same persistent DB.  The boot
#                      replay verifies the prior drain_event row survives
#                      with end_timestamp populated AND the fresh orchestrator
#                      starts at NORMAL (no stale stage state leaks across
#                      the simulated reboot).
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Rex (US-259) | Initial -- full-lifecycle e2e gate to close
#                              | the test-fidelity gap that left drain test 5
#                              | passing the harness yet hard-crashing in
#                              | production.  Two-instance shape exercises
#                              | the service-restart boundary that the single-
#                              | trace harness cannot.  Discriminator: the
#                              | stage-row + drain-event-closed assertions
#                              | FAIL against pre-US-252 code because the
#                              | orchestrator predates the powerLogWriter
#                              | parameter required to populate power_log
#                              | stage rows.
# ================================================================================
################################################################################

"""US-259 full-lifecycle power-management integration test.

Why two instances
-----------------
The Sprint-20 US-245 harness covers a continuous drain inside one instance.
But the production scenario US-216 + US-252 are designed for is bigger: the
Pi runs idle on wall power for extended stretches, the operator removes
wall power (key-off in the future B-043 wiring), the staged ladder fires
``systemctl poweroff``, and on next key-on the service comes back up and
returns to idle EXTERNAL.

Drain test 5 demonstrated the harness gap: a single-trace test cannot prove
the cross-restart path.  Stage rows from a prior crash COULD pollute a
fresh orchestrator's view; an open ``battery_health_log`` row from a
crashed prior instance COULD prevent a fresh recorder from opening a new
drain event.  Two instances against the same DB closes both gaps.

Discriminator design
--------------------
Mocks operate at the same boundaries US-245 + US-252 use:

* :class:`I2cClient.readWord` is mocked.  Real UpsMonitor decode +
  history-buffer + slope/sustained rules drive the source decision.
* :func:`subprocess.run` inside ``shutdown_handler`` is patched per
  instance so the TRIGGER stage's ``systemctl poweroff`` call is
  capturable.

The lifecycle structure is the discriminator: pre-US-252 the orchestrator
lacks a ``powerLogWriter`` parameter, so the stage-row assertions on
both instances cannot pass.  Post-US-252 they pass; the cross-restart
``stage_*`` row count delta proves the second instance starts clean
(no stale rows fire on idle EXTERNAL ticks).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from src.pi.hardware.shutdown_handler import ShutdownHandler
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
from src.pi.power.power import PowerMonitor
from src.pi.power.power_db import logShutdownStage

# ================================================================================
# Mock I2C client + fake clock (mirrors US-245 + US-252 patterns)
# ================================================================================

_VCELL_LSB_V = 78.125e-6
_SOC_PINNED_PCT = 60


def _vcellWordLittleEndian(volts: float) -> int:
    """Encode VCELL volts as the little-endian word SMBus would return."""
    raw = int(round(volts / _VCELL_LSB_V)) & 0xFFFF
    return ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)


def _socWordLittleEndian(percent: int) -> int:
    """Encode SOC% as the little-endian word SMBus would return."""
    bigEndian = (percent & 0xFF) << 8
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


class FakeClock:
    """Deterministic monotonic clock so sustained-window math is exact."""

    def __init__(self, startSeconds: float = 0.0) -> None:
        self.t = startSeconds

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _MockI2cClient:
    """Drop-in I2cClient for UpsMonitor with scriptable VCELL reads."""

    def __init__(self, vcellVolts: float, socPercent: int = _SOC_PINNED_PCT):
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
# Fixtures + harness
# ================================================================================


@pytest.fixture()
def lifecycleDb(tmp_path: Path) -> ObdDatabase:
    """Persistent on-disk DB shared between instance 1 + instance 2.

    File-based (not in-memory) so the second instance reads what the first
    instance wrote, which is the lifecycle property under test.
    """
    db = ObdDatabase(str(tmp_path / "test_us259_lifecycle.db"), walMode=False)
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


def _buildPowerLogWriter(database: ObdDatabase) -> Callable[[str, float], None]:
    """Mirror lifecycle._createPowerLogWriter."""
    def writer(eventType: str, vcell: float) -> None:
        logShutdownStage(database, eventType, vcell)
    return writer


def _buildFanOut(
    *,
    powerMonitor: PowerMonitor,
    shutdownHandler: ShutdownHandler,
) -> Callable[[PowerSource, PowerSource], None]:
    """Mirror LifecycleMixin._subscribePowerMonitorToUpsMonitor fan-out."""
    def fanOut(oldSource: PowerSource, newSource: PowerSource) -> None:
        shutdownHandler.onPowerSourceChange(oldSource, newSource)
        onAcPower = newSource != PowerSource.BATTERY
        powerMonitor.checkPowerStatus(onAcPower)
    return fanOut


def _stepAndRecord(
    monitor: UpsMonitor,
    clock: FakeClock,
    mockI2c: _MockI2cClient,
    *,
    vcellVolts: float,
    advanceSeconds: float,
) -> None:
    """Advance the fake clock, set new VCELL, record one history sample."""
    clock.advance(advanceSeconds)
    mockI2c.setVcell(vcellVolts)
    vcell = monitor.getBatteryVoltage()
    soc = monitor.getBatteryPercentage()
    monitor.recordHistorySample(clock.now(), vcell, soc)


def _readStageRows(database: ObdDatabase) -> list[tuple[str, float | None]]:
    """Return (event_type, vcell) for stage rows in id order."""
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT event_type, vcell FROM power_log "
            "WHERE event_type IN "
            "('stage_warning','stage_imminent','stage_trigger') "
            "ORDER BY id ASC"
        ).fetchall()
    return [(r[0], r[1]) for r in rows]


# ================================================================================
# Full lifecycle: startup -> idle -> drain -> trigger -> boot replay -> resume
# ================================================================================


class TestPowerMgmtFullLifecycleAcrossPoweroffBoundary:
    """Two-instance lifecycle test covering the service-restart boundary.

    Instance 1: startup, idle on EXTERNAL, wall-out, drain to TRIGGER,
    ``systemctl poweroff`` invoked, drain-event row closed.

    Instance 2 ("boot replay"): fresh UpsMonitor + recorder + orchestrator
    against the same persistent DB.  Verifies the prior drain_event row is
    closed with end_timestamp; verifies fresh orchestrator starts at NORMAL;
    verifies idle EXTERNAL ticks fire NO new stage rows.
    """

    def test_full_lifecycle_drain_to_trigger_then_boot_replay_to_idle(
        self,
        lifecycleDb: ObdDatabase,
        thresholds: ShutdownThresholds,
    ) -> None:
        # ============================================================
        # INSTANCE 1: startup -> idle EXTERNAL -> wall-out -> drain
        # -> stages fire -> systemctl poweroff
        # ============================================================
        clock1 = FakeClock()
        mockI2c1 = _MockI2cClient(vcellVolts=4.20)
        upsMonitor1 = UpsMonitor(
            i2cClient=mockI2c1,
            monotonicClock=clock1.now,
        )
        powerMonitor1 = PowerMonitor(database=lifecycleDb, enabled=True)
        recorder1 = BatteryHealthRecorder(database=lifecycleDb)
        shutdownHandler1 = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )
        orchestrator1 = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder1,
            shutdownAction=shutdownHandler1._executeShutdown,  # noqa: SLF001
            powerLogWriter=_buildPowerLogWriter(lifecycleDb),
        )
        upsMonitor1.onPowerSourceChange = _buildFanOut(
            powerMonitor=powerMonitor1,
            shutdownHandler=shutdownHandler1,
        )

        # ----- Phase 1A: idle EXTERNAL.  Three ticks at 4.20V, 30s apart.
        # UpsMonitor's slope rule + sustained-window rule both stay quiet:
        # VCELL is well above the 3.95V sustained threshold AND there's no
        # negative slope.  Source stays EXTERNAL.  Orchestrator stays at
        # NORMAL.  No stage rows.  No subprocess.run calls.
        for _ in range(3):
            _stepAndRecord(
                upsMonitor1, clock1, mockI2c1,
                vcellVolts=4.20, advanceSeconds=30.0,
            )
            currentSource = upsMonitor1.getPowerSource()
            assert currentSource == PowerSource.EXTERNAL
            orchestrator1.tick(
                currentVcell=upsMonitor1.getVcell(),
                currentSource=currentSource,
            )

        assert orchestrator1.state == PowerState.NORMAL, (
            "Orchestrator escalated during idle EXTERNAL phase"
        )
        idleStageRows = _readStageRows(lifecycleDb)
        assert idleStageRows == [], (
            f"Idle EXTERNAL phase wrote stage rows: {idleStageRows}"
        )

        # ----- Phase 1B: wall-out + drain to TRIGGER.  Same trace shape
        # as the US-245 canonical drain.  10s per step keeps the slope
        # rule decisive.
        drainTrace = [4.10, 3.90, 3.75, 3.60, 3.50, 3.46, 3.42]
        lastSource: PowerSource = PowerSource.EXTERNAL

        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run"
        ) as mockSubprocess1:
            for stepVcell in drainTrace:
                _stepAndRecord(
                    upsMonitor1, clock1, mockI2c1,
                    vcellVolts=stepVcell, advanceSeconds=10.0,
                )
                currentSource = upsMonitor1.getPowerSource()
                if currentSource != lastSource:
                    upsMonitor1.onPowerSourceChange(lastSource, currentSource)
                    lastSource = currentSource
                orchestrator1.tick(
                    currentVcell=upsMonitor1.getVcell(),
                    currentSource=currentSource,
                )

        # ----- Phase 1C: assertions on instance-1 final state.
        assert lastSource == PowerSource.BATTERY
        assert orchestrator1.state == PowerState.TRIGGER
        assert mockSubprocess1.call_count == 1
        assert mockSubprocess1.call_args[0][0] == ["systemctl", "poweroff"]

        # All three stage rows landed; vcell column populated.
        instance1Rows = _readStageRows(lifecycleDb)
        assert [r[0] for r in instance1Rows] == [
            'stage_warning', 'stage_imminent', 'stage_trigger',
        ]
        # Per-stage VCELL pinning matches the canonical US-245 trace
        # (3.60 / 3.50 / 3.42 V).
        assert instance1Rows[0][1] == pytest.approx(3.60, abs=1e-3)
        assert instance1Rows[1][1] == pytest.approx(3.50, abs=1e-3)
        assert instance1Rows[2][1] == pytest.approx(3.42, abs=1e-3)

        # battery_health_log row was opened on WARNING entry AND closed
        # on TRIGGER entry (orchestrator._closeDrainEvent fires before
        # _shutdownAction so the row is durable even if the process is
        # killed mid-poweroff).
        with lifecycleDb.connect() as conn:
            healthRowsBeforeReboot = conn.execute(
                f"SELECT drain_event_id, end_timestamp, end_soc, "
                f"       runtime_seconds "
                f"FROM {BATTERY_HEALTH_LOG_TABLE}"
            ).fetchall()
        assert len(healthRowsBeforeReboot) == 1
        priorEventId, priorEndTs, priorEndVcell, priorRuntime = (
            healthRowsBeforeReboot[0]
        )
        assert priorEndTs is not None, (
            "Pre-poweroff drain_event row was not closed before "
            "_shutdownAction fired -- post-mortem analytics would lose "
            "the runtime_seconds field if the process were killed"
        )
        assert priorEndVcell == pytest.approx(3.42, abs=1e-3)
        assert priorRuntime is not None

        # ============================================================
        # SIMULATED POWEROFF BOUNDARY
        # ============================================================
        # Real Pi: bootloader executes systemctl poweroff -> SoC halts ->
        # PMIC stays alive watching wall power -> wake-on-power restore.
        # Synthetic: drop instance-1 references.  The DB stays.  An
        # explicit close() on UpsMonitor flushes any internal state but
        # is not strictly required because no I2C resources are held.
        upsMonitor1.close()
        del orchestrator1, recorder1, shutdownHandler1
        del powerMonitor1, upsMonitor1, mockI2c1, clock1

        # ============================================================
        # INSTANCE 2: boot replay -> service restart -> idle EXTERNAL
        # ============================================================
        clock2 = FakeClock(startSeconds=10000.0)
        mockI2c2 = _MockI2cClient(vcellVolts=4.20)
        upsMonitor2 = UpsMonitor(
            i2cClient=mockI2c2,
            monotonicClock=clock2.now,
        )
        powerMonitor2 = PowerMonitor(database=lifecycleDb, enabled=True)
        recorder2 = BatteryHealthRecorder(database=lifecycleDb)
        shutdownHandler2 = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )
        orchestrator2 = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder2,
            shutdownAction=shutdownHandler2._executeShutdown,  # noqa: SLF001
            powerLogWriter=_buildPowerLogWriter(lifecycleDb),
        )
        upsMonitor2.onPowerSourceChange = _buildFanOut(
            powerMonitor=powerMonitor2,
            shutdownHandler=shutdownHandler2,
        )

        # ----- Boot-replay invariant 1: fresh orchestrator starts at
        # NORMAL.  No stale state leaks across the simulated reboot --
        # each PowerDownOrchestrator instance owns its own state.
        assert orchestrator2.state == PowerState.NORMAL

        # ----- Boot-replay invariant 2: prior drain_event row survives
        # the reboot intact.  This is the gate that proves the close-
        # before-shutdown ordering in orchestrator._enterTrigger isn't
        # purely best-effort.
        with lifecycleDb.connect() as conn:
            healthRowsAfterReboot = conn.execute(
                f"SELECT drain_event_id, end_timestamp "
                f"FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (priorEventId,),
            ).fetchall()
        assert len(healthRowsAfterReboot) == 1
        assert healthRowsAfterReboot[0][1] == priorEndTs

        # ----- Boot-replay invariant 3: idle EXTERNAL ticks under the
        # second instance fire NO new stage rows.  The pre-reboot rows
        # remain (the test does not truncate them; they're the durable
        # forensic trail), but the count does not increase.
        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run"
        ) as mockSubprocess2:
            for _ in range(3):
                _stepAndRecord(
                    upsMonitor2, clock2, mockI2c2,
                    vcellVolts=4.20, advanceSeconds=30.0,
                )
                currentSource = upsMonitor2.getPowerSource()
                assert currentSource == PowerSource.EXTERNAL, (
                    "Boot-replay UpsMonitor flipped to BATTERY despite "
                    "VCELL pinned at 4.20V -- buffer carryover regression"
                )
                orchestrator2.tick(
                    currentVcell=upsMonitor2.getVcell(),
                    currentSource=currentSource,
                )

        # No new TRIGGER on the second instance: no subprocess calls.
        assert mockSubprocess2.call_count == 0

        # Stage row count unchanged from instance-1's final tally.
        instance2Rows = _readStageRows(lifecycleDb)
        assert [r[0] for r in instance2Rows] == [
            r[0] for r in instance1Rows
        ], (
            f"Boot-replay phase mutated stage row sequence: "
            f"before={instance1Rows} after={instance2Rows}"
        )
        assert orchestrator2.state == PowerState.NORMAL

        upsMonitor2.close()
