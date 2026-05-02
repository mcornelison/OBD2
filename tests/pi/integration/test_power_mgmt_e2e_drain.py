################################################################################
# File Name: test_power_mgmt_e2e_drain.py
# Purpose/Description: US-245 -- end-to-end power-management integration test.
#                      Mocks the MAX17048 chip-read entry (I2cClient.readWord)
#                      with a stair-step VCELL drain 4.20V -> 3.42V across
#                      mocked time. Exercises the REAL UpsMonitor (US-235
#                      sustained + slope BATTERY detection), REAL PowerMonitor
#                      (US-243 power_log writer wired via the lifecycle fan-out),
#                      REAL PowerDownOrchestrator (US-234 VCELL ladder
#                      NORMAL->WARNING->IMMINENT->TRIGGER), and REAL
#                      ShutdownHandler (US-216 + US-225 suppressLegacyTriggers).
#                      Mocks only at the I2C boundary and at subprocess.run.
#                      If this synthetic passes, drain test 5 is a high-
#                      confidence ship.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex (US-245) | Initial -- e2e drain harness pulling US-234,
#                              | US-235, US-243, US-216, US-225 into a single
#                              | drain-trace assertion. Mocks at I2cClient
#                              | (US-235 pattern) + subprocess.run (US-216
#                              | pattern). No production code changes.
# 2026-05-01    | Rex (US-259) | Drain-test harness expansion.  Drain test 5
#                              | still hard-crashed despite the Sprint-20
#                              | US-245 e2e harness passing -- a test-fidelity
#                              | gap.  Threaded the US-252 powerLogWriter
#                              | closure into every orchestrator construction
#                              | so the post-US-252 production code path
#                              | (stage entry -> power_log row) is the path
#                              | exercised here.  Added per-stage VCELL
#                              | boundary assertions: each stage row's vcell
#                              | column carries the exact threshold-crossing
#                              | voltage (3.60 / 3.50 / 3.42 V for the canonical
#                              | drain trace).  Added negative assertions
#                              | covering the recovery + SOC-pinned cases.
#                              | Test runtime preserved (still ~10s per case).
# ================================================================================
################################################################################

"""US-245 + US-259 power-management end-to-end drain integration test.

Discriminator design
--------------------
This is a HARNESS, not a discriminator. It bolts together the real production
modules the prior Sprint-19/Sprint-20/Sprint-21 stories shipped, mocks ONLY at
the hardware boundary (I2cClient.readWord) and the system boundary
(subprocess.run), and walks a synthetic 4.20V -> 3.42V drain trace. If any
module along the chain regresses (UpsMonitor BATTERY detection,
PowerMonitor.power_log writes, orchestrator stage progression, the US-252
powerLogWriter forensic path, ShutdownHandler poweroff invocation), the
end-to-end assertions catch it without requiring a live drain test on the Pi.

The synthetic equivalent of CIO running drain test 6: if these assertions all
pass, the production drain pipeline is wired correctly end-to-end. The
remaining risk is hardware fidelity (the mocked I2C transport vs the real
SMBus + MAX17048 chip), which only a live drain can validate.

US-259 expansion
----------------
Drain test 5 still hard-crashed despite the Sprint-20 US-245 harness passing,
proving the harness was not exercising the production code path drain test 5
hit.  US-259 closes that gap: every orchestrator construction now threads in
the US-252 ``powerLogWriter`` closure, and the assertions cover the
``stage_warning`` / ``stage_imminent`` / ``stage_trigger`` rows in
``power_log`` with per-stage VCELL boundary values.  Discriminator: this
file FAILS against pre-US-252 code because the orchestrator predates the
``powerLogWriter`` parameter so the stage rows never land.

Mocking boundaries
------------------
* :class:`I2cClient.readWord` is mocked. Returns scriptable VCELL words
  (US-235 pattern) so the REAL UpsMonitor.getBatteryVoltage decode path
  runs (byte-swap + 78.125 uV/LSB scale).
* :func:`subprocess.run` inside ``shutdown_handler`` is patched to a
  capturing MagicMock so the TRIGGER stage's ``systemctl poweroff`` path
  is asserted not executed.
* The polling-loop callback fan-out is reproduced inline (matches the
  shape ``LifecycleMixin._subscribePowerMonitorToUpsMonitor`` builds in
  production); the real polling thread is not started -- ticks are driven
  manually so timing is deterministic.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

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
# I2C mock + fake clock (US-235 patterns)
# ================================================================================

# MAX17048 stores VCELL big-endian on the wire at 78.125 uV/LSB; SMBus
# read_word_data returns it little-endian. The real byte-swap happens
# inside UpsMonitor; the test-side encoder mirrors the wire path.
_VCELL_LSB_V = 78.125e-6

# Pinned 60% SOC across the drain -- the production mis-calibration that
# silently bypassed the pre-US-234 SOC%-based ladder across 4 drain tests.
# US-234 made the orchestrator VCELL-driven so SOC is now telemetry-only;
# this test pins it 60 to prove the new path is the load-bearing one.
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
    """Drop-in I2cClient for UpsMonitor with scriptable VCELL reads.

    Only :meth:`readWord` is implemented (the only I2C op UpsMonitor uses
    after US-184's vcgencmd path was removed by US-235).
    """

    def __init__(self, vcellVolts: float, socPercent: int = _SOC_PINNED_PCT):
        self.vcellVolts = vcellVolts
        self.socPercent = socPercent
        self.readWordCalls: list[tuple[int, int]] = []

    def setVcell(self, volts: float) -> None:
        self.vcellVolts = volts

    def readWord(self, address: int, register: int) -> int:
        self.readWordCalls.append((address, register))
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
    """Real ObdDatabase with full schema (power_log + battery_health_log)."""
    db = ObdDatabase(str(tmp_path / "test_us245_e2e.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def thresholds() -> ShutdownThresholds:
    """US-234 default VCELL ladder: 3.70 / 3.55 / 3.45 with 0.05V hysteresis."""
    return ShutdownThresholds(
        enabled=True,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
    )


# ================================================================================
# Harness wiring
# ================================================================================


def _buildFanOut(
    *,
    powerMonitor: PowerMonitor,
    shutdownHandler: ShutdownHandler,
) -> Callable[[PowerSource, PowerSource], None]:
    """Reproduce ``LifecycleMixin._subscribePowerMonitorToUpsMonitor`` shape.

    Forwards the transition to the legacy ShutdownHandler (US-216 path
    suppressed via ``suppressLegacyTriggers`` -- handler.onPowerSourceChange
    becomes a no-op) and to PowerMonitor with the BATTERY-or-not bool.
    """
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
    """Advance synthetic time, set new VCELL, walk the production poll path.

    Mirrors the live UpsMonitor polling thread's per-tick body: read VCELL
    via I2C, read SOC, append to the rolling history buffer that
    getPowerSource consumes for slope + sustained-threshold rules.
    """
    clock.advance(advanceSeconds)
    mockI2c.setVcell(vcellVolts)
    vcell = monitor.getBatteryVoltage()
    soc = monitor.getBatteryPercentage()
    monitor.recordHistorySample(clock.now(), vcell, soc)


def _readPowerLog(database: ObdDatabase) -> list[dict]:
    """Pull all power_log rows ordered by id (insert order)."""
    with database.connect() as conn:
        conn.row_factory = __import__('sqlite3').Row
        rows = conn.execute(
            "SELECT * FROM power_log ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def _readStageRows(database: ObdDatabase) -> list[tuple[str, float | None]]:
    """Pull (event_type, vcell) for the US-252 stage rows in id order.

    Filters to ``stage_warning`` / ``stage_imminent`` / ``stage_trigger`` so
    PowerMonitor's transition rows from the same drain do not pollute the
    sequence assertion.
    """
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT event_type, vcell FROM power_log "
            "WHERE event_type IN "
            "('stage_warning','stage_imminent','stage_trigger') "
            "ORDER BY id ASC"
        ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _buildPowerLogWriter(database: ObdDatabase) -> Callable[[str, float], None]:
    """Mirror the lifecycle ``_createPowerLogWriter`` closure used in production.

    Production builds this in ``LifecycleMixin._createPowerLogWriter`` and
    threads it through ``createHardwareManagerFromConfig`` -> HardwareManager
    -> PowerDownOrchestrator constructor.  Tests reproduce the same shape so
    the orchestrator instance under test exercises the same write path the
    on-Pi instance does on a live drain.
    """
    def writer(eventType: str, vcell: float) -> None:
        logShutdownStage(database, eventType, vcell)
    return writer


# ================================================================================
# Full drain trace e2e
# ================================================================================


class TestE2eDrainFiresFullPipeline:
    """Stair-step drain 4.20V -> 3.42V exercises every wired component:
    UpsMonitor flips to BATTERY -> fan-out -> PowerMonitor writes power_log
    -> orchestrator stages NORMAL/WARNING/IMMINENT/TRIGGER -> battery_health_log
    open + close -> ShutdownHandler._executeShutdown invoked once.
    """

    def test_drain_4_20_to_3_42_fires_full_pipeline(
        self,
        freshDb: ObdDatabase,
        thresholds: ShutdownThresholds,
    ) -> None:
        # ----- Build the production chain (real instances, mocked at boundaries).
        clock = FakeClock()
        mockI2c = _MockI2cClient(vcellVolts=4.20)
        upsMonitor = UpsMonitor(
            i2cClient=mockI2c,
            monotonicClock=clock.now,
        )

        powerMonitor = PowerMonitor(database=freshDb, enabled=True)

        recorder = BatteryHealthRecorder(database=freshDb)

        # US-216 invariant: legacy 30s-after-BATTERY + 10% triggers must be
        # suppressed so the only path to subprocess.run is via the
        # orchestrator's TRIGGER stage. US-225 wiring uses this flag.
        shutdownHandler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )

        stageOrder: list[str] = []

        def onWarning() -> None:
            stageOrder.append("warning")

        def onImminent() -> None:
            stageOrder.append("imminent")

        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownHandler._executeShutdown,  # noqa: SLF001
            onWarning=onWarning,
            onImminent=onImminent,
            # US-259: thread the US-252 forensic-row writer in so the
            # production stage-entry path lands in power_log.  Pre-US-252
            # the orchestrator had no powerLogWriter parameter; passing one
            # here is what makes drain test 6 reproducible synthetically.
            powerLogWriter=_buildPowerLogWriter(freshDb),
        )

        # Wire UpsMonitor -> fan-out -> ShutdownHandler + PowerMonitor.
        # Matches LifecycleMixin._subscribePowerMonitorToUpsMonitor.
        upsMonitor.onPowerSourceChange = _buildFanOut(
            powerMonitor=powerMonitor,
            shutdownHandler=shutdownHandler,
        )

        # ----- Drain trace. Stair-step VCELL across mocked time; each step
        # walks the same path the live polling loop would: chip read,
        # decode, history record, source decision, stage tick. SOC stays
        # pinned 60% throughout (the production mis-calibration; proves
        # US-234's VCELL path is the load-bearing one).
        # 10s advance per step keeps the slope rule decisive (-0.05 to
        # -0.40 V/min) and sustains sub-threshold long enough for the
        # 30s window rule too.
        drainTrace = [4.20, 4.10, 3.90, 3.75, 3.60, 3.50, 3.46, 3.42]
        lastSource: PowerSource = PowerSource.EXTERNAL

        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run"
        ) as mockSubprocess:
            for stepVcell in drainTrace:
                _stepAndRecord(
                    upsMonitor, clock, mockI2c,
                    vcellVolts=stepVcell, advanceSeconds=10.0,
                )
                # Round-trip sanity: the I2C decode reproduces the input
                # to within 78.125 uV resolution (one-LSB tolerance).
                assert upsMonitor.getVcell() == pytest.approx(
                    stepVcell, abs=1e-3,
                )
                # SOC pinned 60% throughout -- proves the new VCELL ladder
                # is the only path that could fire stages here.
                assert upsMonitor.getBatteryPercentage() == _SOC_PINNED_PCT

                currentSource = upsMonitor.getPowerSource()
                if currentSource != lastSource:
                    assert upsMonitor.onPowerSourceChange is not None
                    upsMonitor.onPowerSourceChange(lastSource, currentSource)
                    lastSource = currentSource

                orchestrator.tick(
                    currentVcell=upsMonitor.getVcell(),
                    currentSource=currentSource,
                )

        # ----- Pipeline assertion 1: UpsMonitor flipped EXTERNAL -> BATTERY.
        # US-235 sustained-threshold + tuned-slope rules (the pre-US-235
        # CRATE rule was deleted; CRATE here returns 0xFFFF anyway).
        assert lastSource == PowerSource.BATTERY, (
            "UpsMonitor never flipped to BATTERY -- US-235 detection regressed"
        )
        assert upsMonitor.getPowerSource() == PowerSource.BATTERY

        # ----- Pipeline assertion 2: power_log gained rows from the fan-out.
        # US-243 wiring proof: PowerMonitor wrote at least one row for the
        # EXTERNAL -> BATTERY transition (Spool's 2026-04-29 drill found
        # 8 transitions reaching the journal but 0 reaching power_log
        # because PowerMonitor was never instantiated).
        powerLogRows = _readPowerLog(freshDb)
        assert len(powerLogRows) >= 1, (
            "power_log empty -- US-243 PowerMonitor write path regressed"
        )
        assert any(r["on_ac_power"] == 0 for r in powerLogRows), (
            f"power_log missing on_ac_power=0 row; got {powerLogRows}"
        )
        assert any(r["power_source"] == "battery" for r in powerLogRows), (
            f"power_log missing power_source=battery row; got {powerLogRows}"
        )

        # ----- Pipeline assertion 3: orchestrator stage progression.
        # NORMAL -> WARNING (at <=3.70V) -> IMMINENT (at <=3.55V) ->
        # TRIGGER (at <=3.45V). Stage callbacks fire only on entry.
        assert orchestrator.state == PowerState.TRIGGER, (
            f"Orchestrator stuck at {orchestrator.state.value}; expected TRIGGER"
        )
        assert stageOrder == ["warning", "imminent"], (
            f"Stage callback order wrong: {stageOrder} (expected "
            "['warning', 'imminent'] -- TRIGGER has no callback per US-216)"
        )

        # ----- Pipeline assertion 4: battery_health_log row populated.
        # Opened on WARNING entry with start_soc carrying the highest
        # VCELL seen on battery (US-234 reuses start_soc column for
        # VCELL volts -- see orchestrator module docstring schema note).
        # Closed on TRIGGER entry with end_soc + runtime_seconds.
        with freshDb.connect() as conn:
            healthRows = conn.execute(
                f"SELECT drain_event_id, start_soc, end_soc, "
                f"       end_timestamp, runtime_seconds, load_class "
                f"FROM {BATTERY_HEALTH_LOG_TABLE}"
            ).fetchall()
        assert len(healthRows) == 1, (
            f"Expected 1 battery_health_log row; got {len(healthRows)}"
        )
        eventId, startVcell, endVcell, endTs, runtimeS, loadClass = healthRows[0]
        # The highest pre-WARNING VCELL on battery is 4.10V (the t=10s
        # tick where source first flipped). 4.20V was the t=0 tick when
        # source was still EXTERNAL so the orchestrator's
        # _highestBatteryVcell tracker did not update.
        assert startVcell == pytest.approx(4.10, abs=1e-3), (
            f"start_soc (VCELL) wrong: got {startVcell}, expected ~4.10"
        )
        # End state = TRIGGER stage's currentVcell = 3.42 from the last
        # drain step.
        assert endVcell == pytest.approx(3.42, abs=1e-3), (
            f"end_soc (VCELL) wrong: got {endVcell}, expected ~3.42"
        )
        assert endTs is not None, (
            "battery_health_log row not closed -- end_timestamp NULL"
        )
        assert runtimeS is not None, (
            "battery_health_log runtime_seconds NULL after close"
        )
        assert loadClass == "production"

        # ----- Pipeline assertion 5: subprocess.run(systemctl poweroff)
        # invoked exactly once. US-216 + US-225 invariant: only the
        # orchestrator's TRIGGER stage path fires; the legacy 30s-after-
        # BATTERY timer + 10% low-battery trigger are no-ops because
        # suppressLegacyTriggers=True.
        assert mockSubprocess.call_count == 1, (
            f"subprocess.run called {mockSubprocess.call_count} times; "
            "expected exactly 1 (TRIGGER -> systemctl poweroff)"
        )
        cmd = mockSubprocess.call_args[0][0]
        assert cmd == ["systemctl", "poweroff"], (
            f"Wrong shutdown cmd: {cmd}; expected ['systemctl', 'poweroff']"
        )

        # ----- Pipeline assertion 6 (US-259): US-252 forensic stage rows.
        # Each stage entry writes a power_log row carrying the LiPo cell
        # voltage at threshold crossing.  Order is fixed by the state-
        # machine fall-through within tick(): WARNING before IMMINENT
        # before TRIGGER.  Per-step VCELL pinning catches a regression
        # where a stage fires at the wrong threshold (e.g. WARNING fires
        # but at the IMMINENT voltage because of a thresholds mix-up).
        stageRows = _readStageRows(freshDb)
        assert [r[0] for r in stageRows] == [
            'stage_warning', 'stage_imminent', 'stage_trigger',
        ], (
            f"Stage row sequence wrong: {stageRows}; expected "
            "['stage_warning', 'stage_imminent', 'stage_trigger']"
        )
        # In the canonical drain trace [4.20, 4.10, 3.90, 3.75, 3.60, 3.50,
        # 3.46, 3.42], the orchestrator enters each stage at the FIRST
        # step where currentVcell <= threshold:
        #   - WARNING at step 5 (3.60V <= 3.70V)
        #   - IMMINENT at step 6 (3.50V <= 3.55V)  [3.60V skipped IMMINENT
        #     because the same-tick fall-through checks IMMINENT after
        #     WARNING; 3.60V <= 3.55V is False so IMMINENT waits]
        #   - TRIGGER at step 8 (3.42V <= 3.45V)  [3.46V skipped TRIGGER
        #     because 3.46V > 3.45V]
        warningVcell, imminentVcell, triggerVcell = (
            stageRows[0][1], stageRows[1][1], stageRows[2][1],
        )
        assert warningVcell == pytest.approx(3.60, abs=1e-3), (
            f"WARNING vcell wrong: got {warningVcell}; expected ~3.60V "
            "(first step <= warningVcell threshold 3.70V)"
        )
        assert imminentVcell == pytest.approx(3.50, abs=1e-3), (
            f"IMMINENT vcell wrong: got {imminentVcell}; expected ~3.50V "
            "(first step <= imminentVcell threshold 3.55V)"
        )
        assert triggerVcell == pytest.approx(3.42, abs=1e-3), (
            f"TRIGGER vcell wrong: got {triggerVcell}; expected ~3.42V "
            "(first step <= triggerVcell threshold 3.45V)"
        )


# ================================================================================
# Negative case: AC restored before TRIGGER cancels the drain
# ================================================================================


class TestE2eRecoveryCancelsDrain:
    """If VCELL recovers mid-drain, the orchestrator must close the
    drain event and skip the TRIGGER -> poweroff path.

    The orchestrator has two recovery escape hatches: (a) AC-restore
    when ``currentSource`` flips back to EXTERNAL, and (b) WARNING
    hysteresis when VCELL climbs above ``warningVcell + hysteresisVcell``
    while still on BATTERY. Either path closes the drain event and
    sets state back to NORMAL. This test asserts the safety invariant
    (NORMAL state + zero poweroff calls) without pinning which path
    fired -- the production case where wall power returns mid-drain
    triggers (b) first because UpsMonitor's slope rule keeps source
    BATTERY while the rolling-window samples age out.
    """

    def test_vcellRecovers_midDrain_skipsPoweroff(
        self,
        freshDb: ObdDatabase,
        thresholds: ShutdownThresholds,
    ) -> None:
        clock = FakeClock()
        mockI2c = _MockI2cClient(vcellVolts=4.20)
        upsMonitor = UpsMonitor(
            i2cClient=mockI2c,
            monotonicClock=clock.now,
        )
        powerMonitor = PowerMonitor(database=freshDb, enabled=True)
        recorder = BatteryHealthRecorder(database=freshDb)
        shutdownHandler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )
        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownHandler._executeShutdown,  # noqa: SLF001
            powerLogWriter=_buildPowerLogWriter(freshDb),
        )
        upsMonitor.onPowerSourceChange = _buildFanOut(
            powerMonitor=powerMonitor,
            shutdownHandler=shutdownHandler,
        )

        # Drain into WARNING: 4.20 -> 3.60 (slope rule fires BATTERY,
        # orchestrator enters WARNING at 3.60). Then VCELL recovers to
        # 4.10V well above warningVcell+hysteresis (3.75V) -- the
        # orchestrator's hysteresis path closes the drain event.
        drainPhase = [4.20, 4.10, 3.90, 3.75, 3.60]
        recoveryPhase = [4.10, 4.10, 4.10, 4.10, 4.10]
        lastSource: PowerSource = PowerSource.EXTERNAL

        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run"
        ) as mockSubprocess:
            for stepVcell in drainPhase + recoveryPhase:
                _stepAndRecord(
                    upsMonitor, clock, mockI2c,
                    vcellVolts=stepVcell, advanceSeconds=5.0,
                )
                currentSource = upsMonitor.getPowerSource()
                if currentSource != lastSource:
                    assert upsMonitor.onPowerSourceChange is not None
                    upsMonitor.onPowerSourceChange(lastSource, currentSource)
                    lastSource = currentSource
                orchestrator.tick(
                    currentVcell=upsMonitor.getVcell(),
                    currentSource=currentSource,
                )

            # Safety invariant: orchestrator returned to NORMAL via some
            # recovery path; subprocess.run was never invoked.
            assert orchestrator.state == PowerState.NORMAL, (
                f"Expected NORMAL after VCELL recovery; got "
                f"{orchestrator.state.value}"
            )
            assert mockSubprocess.call_count == 0, (
                f"subprocess.run called {mockSubprocess.call_count} times; "
                "expected 0 (VCELL recovered mid-drain)"
            )

        # battery_health_log row was opened (WARNING entry) AND closed
        # (recovery path). end_timestamp populated; row count == 1.
        with freshDb.connect() as conn:
            healthRows = conn.execute(
                f"SELECT end_timestamp FROM {BATTERY_HEALTH_LOG_TABLE}"
            ).fetchall()
        assert len(healthRows) == 1
        assert healthRows[0][0] is not None, (
            "Recovery did not close battery_health_log row"
        )

        # US-259: forensic stage rows show WARNING fired but neither
        # IMMINENT nor TRIGGER did.  Negative-case proof that the
        # powerLogWriter only fires on actual stage entry, never on
        # tick-without-transition and never on the recovery path.
        stageRows = _readStageRows(freshDb)
        eventTypes = [r[0] for r in stageRows]
        assert eventTypes == ['stage_warning'], (
            f"Recovery path stage rows wrong: got {eventTypes}; expected "
            "['stage_warning'] (drain reached WARNING then VCELL recovered "
            "before IMMINENT crossing)"
        )


# ================================================================================
# Bug-class proof: SOC stays pinned 60% throughout, ladder still fires
# ================================================================================


class TestE2eSocPinnedDoesNotPreventTrigger:
    """The 4-drain production failure mode this whole sprint family fixes:
    MAX17048 SOC reads 60% while VCELL drains 4.20 -> 3.40V. Pre-US-234
    SOC%-based ladder never fired. This test proves the post-US-234
    VCELL ladder still fires across the full chain when SOC is misleading.
    """

    def test_socPinned60_full_chain_still_triggers(
        self,
        freshDb: ObdDatabase,
        thresholds: ShutdownThresholds,
    ) -> None:
        clock = FakeClock()
        mockI2c = _MockI2cClient(vcellVolts=4.20, socPercent=_SOC_PINNED_PCT)
        upsMonitor = UpsMonitor(
            i2cClient=mockI2c,
            monotonicClock=clock.now,
        )
        powerMonitor = PowerMonitor(database=freshDb, enabled=True)
        recorder = BatteryHealthRecorder(database=freshDb)
        shutdownHandler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )
        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownHandler._executeShutdown,  # noqa: SLF001
            powerLogWriter=_buildPowerLogWriter(freshDb),
        )
        upsMonitor.onPowerSourceChange = _buildFanOut(
            powerMonitor=powerMonitor,
            shutdownHandler=shutdownHandler,
        )

        lastSource: PowerSource = PowerSource.EXTERNAL
        captured = MagicMock()

        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run", new=captured,
        ):
            for stepVcell in (4.20, 3.65, 3.50, 3.40):
                _stepAndRecord(
                    upsMonitor, clock, mockI2c,
                    vcellVolts=stepVcell, advanceSeconds=10.0,
                )
                # SOC always 60% -- the production mis-calibration that
                # silently bypassed the pre-US-234 ladder.
                assert upsMonitor.getBatteryPercentage() == _SOC_PINNED_PCT
                currentSource = upsMonitor.getPowerSource()
                if currentSource != lastSource:
                    assert upsMonitor.onPowerSourceChange is not None
                    upsMonitor.onPowerSourceChange(lastSource, currentSource)
                    lastSource = currentSource
                orchestrator.tick(
                    currentVcell=upsMonitor.getVcell(),
                    currentSource=currentSource,
                )

        assert orchestrator.state == PowerState.TRIGGER
        captured.assert_called_once()

        # US-259: with SOC pinned 60% the legacy SOC-based ladder would
        # never have fired (drain tests 1-4 prove the bug).  Asserting
        # all three stage rows landed in power_log proves the post-US-234
        # VCELL ladder + post-US-252 forensic-write path are the only
        # path that could have produced these rows.  Pre-US-252 there
        # was no powerLogWriter and these rows could not exist.
        stageRows = _readStageRows(freshDb)
        assert [r[0] for r in stageRows] == [
            'stage_warning', 'stage_imminent', 'stage_trigger',
        ], (
            f"SOC-pinned drain stage rows wrong: {stageRows}; expected "
            "all three stage entries despite SOC=60% throughout"
        )
