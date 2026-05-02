################################################################################
# File Name: test_tick_gating_no_silent_bail.py
# Purpose/Description: US-266 Discriminator-B parametrized synthetic tests --
#                      every silent-bail early-return inside tick() must emit
#                      a DEBUG log capturing the bail-causing value.  Pre-fix
#                      these tests FAIL because no DEBUG logs existed at the
#                      early-return sites; post-fix they PASS, so a post-Drain-7
#                      forensic walk in journalctl can pin down which guard
#                      (if any) swallowed a BATTERY -> WARNING transition when
#                      the logger CSV's pd_tick_count column is incrementing
#                      but pd_stage stays NORMAL.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-02    | Rex (US-266) | Initial -- 4 parametrized tests, one per silent-
#                              | bail guard found in the audit, plus a property-
#                              | level confirmation that the happy escalation
#                              | path emits NO DEBUG early-return log (so the
#                              | discriminator only fires when the bug class
#                              | actually exists).
# ================================================================================
################################################################################

"""US-266 Discriminator-B: tick() silent-bail audit + DEBUG instrumentation.

Discriminator design
--------------------
Drain Test 6 produced 1 ``power_log`` row across a 21-min battery window
proving the staged-shutdown ladder did not fire even with US-252's
display/tick decouple shipped.  Spool's truth-table identifies three
hypotheses; this test class covers Hypothesis B: ``pd_tick_count``
increments (thread alive) but ``pd_stage`` stays NORMAL even when VCELL
crosses thresholds.  Cause class: an early-return guard inside tick()
silently bails before reaching the stage-comparison logic.

Audit (against ``src.pi.power.orchestrator.PowerDownOrchestrator.tick``
post-US-262, pre-US-266) found 4 silent-bail early-return paths:

1. ``if not self._thresholds.enabled`` -- config-disabled bail.
2. ``if self._state == PowerState.TRIGGER`` -- terminal-state bail.
3. ``if currentSource == EXTERNAL`` AND ``self._state == NORMAL`` --
   wall-power or upstream stale-cache; no escalation possible.
4. ``if currentSource != BATTERY`` -- ``UNKNOWN``-source bail.

The audit also evaluated the spec's hypothesis modes ``vcell=None`` and
``threshold=None``: both currently TypeError on the threshold comparison
and are caught loud by ``hardware_manager._powerDownTickLoop``'s
``except Exception`` (an ERROR log, not a silent bail).  They are
therefore NOT hypothesis-B candidates and no new defensive guards were
added (per the story's "behavior unchanged / no logic refactored"
invariant).  Mapping to spec test list:

* ``BATTERY/UNKNOWN`` -> Guard 4 (UNKNOWN-source bail).
* ``stale-cache``     -> Guard 3 path B (EXTERNAL during NORMAL -- the
  upstream stale-cache failure mode the spec author pointed at).
* ``vcell=None``      -> tested as ``enabled=False`` instead because
  vcell=None is NOT a silent bail in current code; ``enabled=False`` IS
  a silent bail and exercises the bail-without-state-change discriminator
  the spec wants.
* ``threshold=None``  -> tested as ``state=TRIGGER terminal`` instead
  because threshold=None is also not a silent bail in current code (would
  TypeError loud); the terminal-state silent bail is the closest match.

Fidelity
--------
Mocks operate at :class:`I2cClient.readWord` -- the actual MAX17048
chip-read entry point -- per the
``feedback_runtime_validation_required.md`` rule (mocking at
``UpsMonitor.getPowerSource()`` would bypass the bug class).  The
orchestrator consumes ``upsMonitor.getVcell()`` for the VCELL value and
the ``PowerSource`` enum value as the ``currentSource`` parameter.

Assertions
----------
Each parametrized case asserts:

* Exactly the expected DEBUG log message text appears in ``caplog`` at
  level DEBUG, with the bail-causing value included in the message.
* No stage transition occurred -- ``orchestrator.state`` stays at the
  pre-tick state and ``onWarning``/``onImminent`` callbacks are never
  invoked.
* ``tickCount`` advanced by exactly 1 (US-262 invariant: counter
  increments BEFORE the early-return guard, so the forensic CSV can
  distinguish "thread never ran" from "thread ran but bailed").

Pre-US-266 these tests FAIL because the DEBUG log assertion finds zero
matching records.  Post-US-266 they PASS.
"""

from __future__ import annotations

import logging
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
from src.pi.power.battery_health import BatteryHealthRecorder
from src.pi.power.orchestrator import (
    PowerDownOrchestrator,
    PowerState,
    ShutdownThresholds,
)

# ================================================================================
# Mock I2C client -- MAX17048 chip-read fidelity (per US-234 pattern)
# ================================================================================


_VCELL_LSB_V = 78.125e-6
_SOC_PINNED_PCT = 60


def _vcellWordLittleEndian(volts: float) -> int:
    """Encode a VCELL voltage as the little-endian word SMBus would return.

    Mirrors the encoding used by ``test_orchestrator_vcell_thresholds.py``
    so the round-trip ``I2C -> byte-swap -> 78.125 uV/LSB -> volts``
    reproduces the input within 1 LSB of the chip resolution.
    """
    raw = int(round(volts / _VCELL_LSB_V))
    bigEndian = raw & 0xFFFF
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


def _socWordLittleEndian(percent: int) -> int:
    """Encode a SOC% as the little-endian word SMBus would return."""
    bigEndian = (percent & 0xFF) << 8
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


class _MockI2cClient:
    """Drop-in I2cClient for UpsMonitor with scriptable VCELL/SOC reads."""

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
    db = ObdDatabase(str(tmp_path / "test_us266_gating.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def recorder(freshDb: ObdDatabase) -> BatteryHealthRecorder:
    return BatteryHealthRecorder(database=freshDb)


@pytest.fixture()
def thresholds() -> ShutdownThresholds:
    """Default-enabled VCELL thresholds (Sprint 19 US-234 production values)."""
    return ShutdownThresholds(
        enabled=True,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
    )


@pytest.fixture()
def mockI2c() -> _MockI2cClient:
    """Mock I2C client; default VCELL chosen below WARNING (3.40V) so a
    successfully-not-bailing tick on BATTERY would advance state."""
    return _MockI2cClient(vcellVolts=3.40)


@pytest.fixture()
def upsMonitor(mockI2c: _MockI2cClient) -> UpsMonitor:
    """Real UpsMonitor wired to the mock I2C client (real byte-swap path)."""
    return UpsMonitor(i2cClient=mockI2c)


@pytest.fixture()
def onWarning() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def onImminent() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def shutdownAction() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def orchestrator(
    thresholds: ShutdownThresholds,
    recorder: BatteryHealthRecorder,
    shutdownAction: MagicMock,
    onWarning: MagicMock,
    onImminent: MagicMock,
) -> PowerDownOrchestrator:
    return PowerDownOrchestrator(
        thresholds=thresholds,
        batteryHealthRecorder=recorder,
        shutdownAction=shutdownAction,
        onWarning=onWarning,
        onImminent=onImminent,
        onAcRestore=MagicMock(),
    )


# ================================================================================
# The discriminator: 4 parametrized cases, one per silent-bail guard
# ================================================================================


class TestSilentBailEarlyReturnsLog:
    """Each silent-bail early-return inside tick() must DEBUG-log the
    bail-causing value AND produce no stage transition.

    Pre-US-266 these tests FAIL because the DEBUG log assertion finds
    zero matching records.  Post-US-266 they PASS.  Tests would also
    FAIL if a future refactor turned the bail into a happy-path advance
    (the "no stage transition" assertion catches that).
    """

    def test_sourceUnknown_logsBailWithoutTransition(
        self,
        orchestrator: PowerDownOrchestrator,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
        onWarning: MagicMock,
        onImminent: MagicMock,
        shutdownAction: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Spec mapping: ``BATTERY/UNKNOWN``.

        Guard 4 (``currentSource != _PS.BATTERY``) silently bails when
        upstream returns ``PowerSource.UNKNOWN`` instead of the expected
        ``BATTERY``.  Pre-US-266 this bail produced no log; post-US-266
        a single DEBUG line captures the source value.
        """
        # 3.40V is below trigger -- on BATTERY it would fire all 3 stages.
        # On UNKNOWN it must silently bail (no transition).
        mockI2c.setVcell(3.40)
        vcell = upsMonitor.getVcell()
        assert vcell == pytest.approx(3.40, abs=1e-3)

        priorTickCount = orchestrator.tickCount

        with caplog.at_level(
            logging.DEBUG, logger="src.pi.power.orchestrator",
        ):
            orchestrator.tick(
                currentVcell=vcell, currentSource=PowerSource.UNKNOWN,
            )

        assert orchestrator.state == PowerState.NORMAL
        onWarning.assert_not_called()
        onImminent.assert_not_called()
        shutdownAction.assert_not_called()
        assert orchestrator.tickCount == priorTickCount + 1

        bailMessages = [
            r.getMessage() for r in caplog.records
            if r.levelno == logging.DEBUG
            and "tick early-return" in r.getMessage()
        ]
        assert len(bailMessages) == 1, (
            f"Expected exactly 1 DEBUG bail log; got {bailMessages!r}"
        )
        # Bail message must capture the source value AND the vcell value
        # so a post-mortem can correlate against the logger CSV row.
        assert "source=unknown" in bailMessages[0]
        assert "expected BATTERY" in bailMessages[0]
        assert "3.4" in bailMessages[0]

    def test_sourceExternalDuringNormal_logsBailWithoutTransition(
        self,
        orchestrator: PowerDownOrchestrator,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
        onWarning: MagicMock,
        shutdownAction: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Spec mapping: ``stale-cache``.

        Guard 3 path B (``currentSource == EXTERNAL`` AND
        ``self._state == NORMAL``) silently bails when wall-power is
        genuinely feeding the UPS OR the upstream ``getPowerSource()``
        returned a stale-cached ``EXTERNAL`` because its VCELL-history
        buffer lacked decisive evidence.  Either way no escalation is
        possible from NORMAL on EXTERNAL.
        """
        # VCELL value at 3.40 is irrelevant -- the source guard fires
        # before any threshold comparison.  Use a sub-warning value to
        # prove that the bail is source-driven, not threshold-driven.
        mockI2c.setVcell(3.40)
        vcell = upsMonitor.getVcell()
        assert orchestrator.state == PowerState.NORMAL  # precondition

        priorTickCount = orchestrator.tickCount

        with caplog.at_level(
            logging.DEBUG, logger="src.pi.power.orchestrator",
        ):
            orchestrator.tick(
                currentVcell=vcell, currentSource=PowerSource.EXTERNAL,
            )

        assert orchestrator.state == PowerState.NORMAL
        onWarning.assert_not_called()
        shutdownAction.assert_not_called()
        assert orchestrator.tickCount == priorTickCount + 1

        bailMessages = [
            r.getMessage() for r in caplog.records
            if r.levelno == logging.DEBUG
            and "tick early-return" in r.getMessage()
        ]
        assert len(bailMessages) == 1, (
            f"Expected exactly 1 DEBUG bail log; got {bailMessages!r}"
        )
        # Bail message must say it was a stale-cache OR wall-power case;
        # the message text covers both interpretations so the post-
        # mortem can decide which one applies based on logger CSV
        # context.
        assert "source=EXTERNAL state=NORMAL" in bailMessages[0]
        assert "stale-cache" in bailMessages[0]

    def test_enabledFalse_logsBailWithoutTransition(
        self,
        recorder: BatteryHealthRecorder,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
        shutdownAction: MagicMock,
        onWarning: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Spec mapping: ``vcell=None`` substitution.

        Guard 1 (``not self._thresholds.enabled``) silently bails when
        the staged-ladder is config-disabled.  This is the first guard
        in tick() and the only one that ignores BOTH the source AND
        the vcell value.  ``vcell=None`` is NOT itself a silent bail
        in current code (would TypeError loud), so we use this guard
        as the closest current-code analog of the spec's "input
        irrelevant -> bail" failure mode.
        """
        disabledThresholds = ShutdownThresholds(
            enabled=False,
            warningVcell=3.70,
            imminentVcell=3.55,
            triggerVcell=3.45,
            hysteresisVcell=0.05,
        )
        orch = PowerDownOrchestrator(
            thresholds=disabledThresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
            onWarning=onWarning,
        )

        # 3.40V on BATTERY would trigger all stages if enabled.  Because
        # disabled, the bail must fire before any state change.
        mockI2c.setVcell(3.40)
        vcell = upsMonitor.getVcell()

        with caplog.at_level(
            logging.DEBUG, logger="src.pi.power.orchestrator",
        ):
            orch.tick(
                currentVcell=vcell, currentSource=PowerSource.BATTERY,
            )

        assert orch.state == PowerState.NORMAL
        onWarning.assert_not_called()
        shutdownAction.assert_not_called()
        assert orch.tickCount == 1

        bailMessages = [
            r.getMessage() for r in caplog.records
            if r.levelno == logging.DEBUG
            and "tick early-return" in r.getMessage()
        ]
        assert len(bailMessages) == 1, (
            f"Expected exactly 1 DEBUG bail log; got {bailMessages!r}"
        )
        assert "thresholds.enabled=False" in bailMessages[0]
        assert "source=battery" in bailMessages[0]

    def test_stateTriggerTerminal_logsBailWithoutTransition(
        self,
        orchestrator: PowerDownOrchestrator,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
        shutdownAction: MagicMock,
        onWarning: MagicMock,
        onImminent: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Spec mapping: ``threshold=None`` substitution.

        Guard 2 (``self._state == PowerState.TRIGGER``) silently bails
        once the orchestrator has already fired the terminal stage.
        Subsequent ticks must NOT re-invoke the shutdown action
        (idempotence) and must NOT advance state.  ``threshold=None``
        is NOT itself a silent bail in current code (would TypeError
        loud); the terminal-state guard is the closest current-code
        analog of the spec's "post-condition state -> bail" failure
        mode.
        """
        # Drive a fast drain so the orchestrator reaches TRIGGER.
        # Once in TRIGGER, the next tick must DEBUG-log the bail.
        for stepVcell in (4.10, 3.65, 3.50, 3.40):
            mockI2c.setVcell(stepVcell)
            orchestrator.tick(
                currentVcell=upsMonitor.getVcell(),
                currentSource=PowerSource.BATTERY,
            )
        assert orchestrator.state == PowerState.TRIGGER  # precondition
        # Reset the action-fired counter so we can prove the next tick
        # does NOT re-fire it.
        priorShutdownCalls = shutdownAction.call_count
        priorTickCount = orchestrator.tickCount

        # Keep mockI2c at 3.40V; on BATTERY at 3.40V a non-terminal
        # state would still escalate -- but TRIGGER is terminal.
        mockI2c.setVcell(3.40)
        with caplog.at_level(
            logging.DEBUG, logger="src.pi.power.orchestrator",
        ):
            orchestrator.tick(
                currentVcell=upsMonitor.getVcell(),
                currentSource=PowerSource.BATTERY,
            )

        # Idempotent: shutdownAction NOT re-invoked; state stays TRIGGER.
        assert orchestrator.state == PowerState.TRIGGER
        assert shutdownAction.call_count == priorShutdownCalls
        assert orchestrator.tickCount == priorTickCount + 1

        bailMessages = [
            r.getMessage() for r in caplog.records
            if r.levelno == logging.DEBUG
            and "tick early-return" in r.getMessage()
        ]
        # Drive sequence above already ran 4 ticks BEFORE caplog opened
        # the DEBUG window.  The window is opened inside this `with`
        # block so it captures only the FINAL post-TRIGGER tick.  Any
        # pre-TRIGGER bail logs (e.g. transient EXTERNAL/UNKNOWN) would
        # have happened earlier under the test's default WARNING-log
        # level and would not appear in caplog.records here.
        assert len(bailMessages) == 1, (
            f"Expected exactly 1 DEBUG bail log; got {bailMessages!r}"
        )
        assert "state=TRIGGER terminal" in bailMessages[0]
        assert "source=battery" in bailMessages[0]


# ================================================================================
# Negative invariant: happy escalation path emits NO early-return log
# ================================================================================


class TestHappyPathEmitsNoBailLog:
    """The story invariant ``DEBUG logs do not fire on the happy-path
    (must be early-return-only)`` is enforced by this test: a real
    BATTERY drain that crosses WARNING must produce zero
    ``tick early-return`` DEBUG lines.
    """

    def test_batteryDrainCrossingWarning_emitsNoEarlyReturnLog(
        self,
        orchestrator: PowerDownOrchestrator,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
        onWarning: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(
            logging.DEBUG, logger="src.pi.power.orchestrator",
        ):
            for stepVcell in (4.10, 3.80, 3.65):
                mockI2c.setVcell(stepVcell)
                orchestrator.tick(
                    currentVcell=upsMonitor.getVcell(),
                    currentSource=PowerSource.BATTERY,
                )

        assert orchestrator.state == PowerState.WARNING
        onWarning.assert_called_once()

        bailMessages = [
            r.getMessage() for r in caplog.records
            if r.levelno == logging.DEBUG
            and "tick early-return" in r.getMessage()
        ]
        assert bailMessages == [], (
            f"Happy-path emitted unexpected early-return logs: "
            f"{bailMessages!r}"
        )
