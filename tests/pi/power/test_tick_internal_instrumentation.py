################################################################################
# File Name: test_tick_internal_instrumentation.py
# Purpose/Description: US-275 Round 3 discriminator -- every BATTERY-relevant
#                      tick() call must emit ONE INFO-level log line capturing
#                      vcell + currentStage + thresholds + willTransition + reason
#                      so a post-Drain-8 forensic walk in journalctl identifies
#                      exactly which gating-logic mode is silently bailing.
#                      Drain Test 7 proved the tick thread runs (337 ticks across
#                      16 min on battery) but `_enterStage` was NEVER called
#                      despite VCELL crossing all 3 thresholds -- so the bug is
#                      an internal decision the existing US-266 DEBUG logs do
#                      not render at the default INFO journalctl level.
#                      Pre-fix these 5 tests FAIL because no INFO-level per-tick
#                      log line exists.  Post-fix they PASS, and the negative-
#                      invariant happy-AC test ensures the new INFO log does
#                      NOT spam the journal during normal AC operation.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-02    | Rex (US-275) | Initial -- 5 parametrized cases (one per reason
#                              | value) + AC-no-spam negative invariant.
# ================================================================================
################################################################################

"""US-275 Round 3 discriminator: tick-internal instrumentation.

Background
----------
Drain Test 7 (2026-05-02 18:56-19:15 CDT) was the 7th consecutive hard-crash
with full Sprint 22 deployed (US-262 forensic logger + US-263 boot-reason +
US-265 tick-thread health-check + US-266 silent-bail DEBUG instrumentation +
US-267 fsync stage-row writes).  The data eliminated H1 (tick thread never
ran -- US-265 health-check showed 337 ticks across drain) and pointed at H2
(tick runs but a guard early-returns silently).  US-266 added DEBUG logs
at the 4 silent-bail sites but DEBUG does not render at the default INFO
journalctl level so post-Drain-7 walks could not see the bail messages.

Discriminator design
--------------------
US-275 adds ONE INFO-level log line per BATTERY-relevant tick() call
capturing the complete decision-relevant state.  The 5 ``reason`` field
values discriminate Spool's hypothesis modes:

* ``power_source!=BATTERY`` -- upstream getPowerSource() returned UNKNOWN
  (or some other non-BATTERY value) while we KNOW we're on battery.
  State-caching bug class.
* ``vcell_none`` -- upstream getVcell() returned None.  Defensive guard
  for a state-caching corruption mode.  In normal operation
  :meth:`UpsMonitor.getVcell` raises rather than returning None, so this
  reason firing in the wild proves a caller is feeding bad data.
* ``already_at_stage`` -- terminal TRIGGER state; tick() must idempotently
  bail without re-firing the shutdown action.
* ``threshold_not_crossed`` -- on BATTERY, no threshold met.  If this
  reason fires while VCELL is clearly below WARNING -> comparison-logic
  bug class (sign error, units mismatch).
* ``OK`` -- transition fired (state changed).  If we see ``OK`` repeatedly
  in the logger CSV but no STAGE_* row appears in ``power_log``, the bug
  is downstream in ``_enterStage``/``_writePowerLogStage`` (US-267).

Spam control
------------
The new INFO log does NOT fire on the AC happy path
(``EXTERNAL`` source during ``NORMAL`` state) so the journal is not
flooded during normal operation.  The negative-invariant test
:class:`TestAcHappyPathEmitsNoInfoLog` enforces this invariant.

Test fidelity
-------------
Mocks operate at :class:`I2cClient.readWord` -- the actual MAX17048
chip-read entry point -- per the
``feedback_runtime_validation_required.md`` rule (mocking at
``UpsMonitor.getVcell()`` would bypass the real byte-swap path and let
encoding bugs hide).  The orchestrator consumes ``upsMonitor.getVcell()``
for the VCELL value and the ``PowerSource`` enum value as the
``currentSource`` parameter.

Pre-US-275 these tests FAIL because no INFO-level per-tick log line
exists.  Post-US-275 they PASS.  Tests would also FAIL if a future
refactor either changed the log shape or stopped emitting on a particular
reason path.
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
# Mock I2C client -- MAX17048 chip-read fidelity (US-266 pattern)
# ================================================================================


_VCELL_LSB_V = 78.125e-6
_SOC_PINNED_PCT = 60
_INFO_PREFIX = "PowerDownOrchestrator.tick:"


def _vcellWordLittleEndian(volts: float) -> int:
    """Encode a VCELL voltage as the little-endian word SMBus returns."""
    raw = int(round(volts / _VCELL_LSB_V))
    bigEndian = raw & 0xFFFF
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


def _socWordLittleEndian(percent: int) -> int:
    """Encode a SOC% as the little-endian word SMBus returns."""
    bigEndian = (percent & 0xFF) << 8
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


class _MockI2cClient:
    """Drop-in I2cClient for UpsMonitor with scriptable VCELL/SOC reads."""

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
# Fixtures
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "test_us275_instrumentation.db"), walMode=False)
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
    """Mock I2C client; default VCELL above WARNING (4.10V)."""
    return _MockI2cClient(vcellVolts=4.10)


@pytest.fixture()
def upsMonitor(mockI2c: _MockI2cClient) -> UpsMonitor:
    """Real UpsMonitor wired to the mock I2C client (real byte-swap path)."""
    return UpsMonitor(i2cClient=mockI2c)


@pytest.fixture()
def shutdownAction() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def orchestrator(
    thresholds: ShutdownThresholds,
    recorder: BatteryHealthRecorder,
    shutdownAction: MagicMock,
) -> PowerDownOrchestrator:
    return PowerDownOrchestrator(
        thresholds=thresholds,
        batteryHealthRecorder=recorder,
        shutdownAction=shutdownAction,
        onWarning=MagicMock(),
        onImminent=MagicMock(),
        onAcRestore=MagicMock(),
    )


def _infoLogs(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return INFO-level orchestrator messages matching the US-275 prefix."""
    return [
        r.getMessage() for r in caplog.records
        if r.levelno == logging.INFO
        and r.name == "src.pi.power.orchestrator"
        and _INFO_PREFIX in r.getMessage()
    ]


def _assertCommonLogShape(message: str, *, willTransition: bool, reason: str) -> None:
    """Assert the spec'd per-tick log line shape.

    The shape is fixed by Spool's Story 1 spec block:
        ``vcell=... currentStage=... thresholds={...} willTransition=... reason=...``

    with ``willTransition`` rendered as Python ``True``/``False`` (the ``%s``
    formatter) and ``reason`` rendered as one of the 5 spec values.
    """
    assert "currentStage=" in message
    assert "thresholds={" in message
    assert "WARNING:3.7" in message
    assert "IMMINENT:3.55" in message
    assert "TRIGGER:3.45" in message
    assert f"willTransition={willTransition}" in message
    assert f"reason={reason}" in message


# ================================================================================
# 5 parametrized cases -- one per reason value
# ================================================================================


class TestTickDecisionLogPerReasonValue:
    """Each of the 5 ``reason`` values must emit exactly one INFO log line
    per tick with the spec'd shape.

    Pre-US-275 ALL 5 tests FAIL because the INFO log line does not exist.
    Post-US-275 ALL 5 PASS.
    """

    def test_reason_powerSourceNotBattery_logsOnUnknownSource(
        self,
        orchestrator: PowerDownOrchestrator,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Reason 1/5: ``power_source!=BATTERY`` discriminates state-caching bugs.

        Upstream returned ``UNKNOWN`` while the orchestrator was on battery.
        The discriminator log captures this so post-Drain-8 forensic walks
        can flag UNKNOWN-bursts as state-caching corruption candidates.
        """
        # 3.40V is below TRIGGER but irrelevant -- source bail fires first.
        mockI2c.setVcell(3.40)
        vcell = upsMonitor.getVcell()

        with caplog.at_level(logging.INFO, logger="src.pi.power.orchestrator"):
            orchestrator.tick(currentVcell=vcell, currentSource=PowerSource.UNKNOWN)

        # tick() did not advance state -- UNKNOWN never reaches the stage logic.
        assert orchestrator.state == PowerState.NORMAL

        infoMessages = _infoLogs(caplog)
        assert len(infoMessages) == 1, (
            f"Expected exactly 1 INFO discriminator log; got {infoMessages!r}"
        )
        _assertCommonLogShape(
            infoMessages[0], willTransition=False, reason="power_source!=BATTERY",
        )
        assert "vcell=3.4" in infoMessages[0]
        assert "currentStage=normal" in infoMessages[0]

    def test_reason_vcellNone_logsOnNoneVcellWithoutTypeError(
        self,
        orchestrator: PowerDownOrchestrator,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Reason 2/5: ``vcell_none`` discriminates upstream None-corruption.

        :meth:`UpsMonitor.getVcell` raises rather than returning None in
        normal operation, but the discriminator must catch the corruption
        mode where a stale-cached None reaches tick().  Pre-US-275 a None
        VCELL TypeError'd on the threshold comparison (caught loud upstream
        as ERROR by ``_powerDownTickLoop``); post-US-275 it bails gracefully
        with a discriminator log.  The shift from TypeError-loud to
        log-and-bail is the *whole point* of the discriminator -- a quiet
        single-line indicator beats a noisy stack trace for a high-frequency
        forensics signal.
        """
        with caplog.at_level(logging.INFO, logger="src.pi.power.orchestrator"):
            # Pass None directly; this is a defensive-guard test, so we
            # bypass UpsMonitor and feed the orchestrator directly.
            orchestrator.tick(
                currentVcell=None,  # type: ignore[arg-type]
                currentSource=PowerSource.BATTERY,
            )

        assert orchestrator.state == PowerState.NORMAL

        infoMessages = _infoLogs(caplog)
        assert len(infoMessages) == 1, (
            f"Expected exactly 1 INFO discriminator log; got {infoMessages!r}"
        )
        _assertCommonLogShape(
            infoMessages[0], willTransition=False, reason="vcell_none",
        )
        # vcell field renders as ``None`` (not ``%.3f`` formatted).
        assert "vcell=None" in infoMessages[0]
        assert "currentStage=normal" in infoMessages[0]

    def test_reason_alreadyAtStage_logsOnTerminalTrigger(
        self,
        orchestrator: PowerDownOrchestrator,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
        shutdownAction: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Reason 3/5: ``already_at_stage`` discriminates idempotent terminal.

        Once the orchestrator has fired TRIGGER, subsequent ticks must
        idempotently bail without re-invoking shutdownAction AND must emit
        the discriminator log so post-Drain-8 walks can confirm the ladder
        already fired (not silently stuck).
        """
        # Drive a fast drain so the orchestrator reaches TRIGGER.
        for stepVcell in (4.10, 3.65, 3.50, 3.40):
            mockI2c.setVcell(stepVcell)
            orchestrator.tick(
                currentVcell=upsMonitor.getVcell(),
                currentSource=PowerSource.BATTERY,
            )
        assert orchestrator.state == PowerState.TRIGGER  # precondition
        priorShutdownCalls = shutdownAction.call_count

        # Open the caplog window AFTER the drive so we capture only the
        # post-TRIGGER tick under test, not the 4 BATTERY ticks above.
        with caplog.at_level(logging.INFO, logger="src.pi.power.orchestrator"):
            orchestrator.tick(
                currentVcell=upsMonitor.getVcell(),
                currentSource=PowerSource.BATTERY,
            )

        assert orchestrator.state == PowerState.TRIGGER
        assert shutdownAction.call_count == priorShutdownCalls

        infoMessages = _infoLogs(caplog)
        assert len(infoMessages) == 1, (
            f"Expected exactly 1 INFO discriminator log; got {infoMessages!r}"
        )
        _assertCommonLogShape(
            infoMessages[0], willTransition=False, reason="already_at_stage",
        )
        assert "currentStage=trigger" in infoMessages[0]

    def test_reason_thresholdNotCrossed_logsOnBatteryAboveWarning(
        self,
        orchestrator: PowerDownOrchestrator,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Reason 4/5: ``threshold_not_crossed`` is the comparison-logic discriminator.

        On BATTERY at 4.10V (above WARNING 3.70V), tick() must emit the
        discriminator log with ``willTransition=False reason=threshold_not_crossed``.
        If post-Drain-8 we see this reason firing while VCELL is clearly
        below WARNING, the bug is in the comparison logic (sign error,
        units mismatch) and Sprint 24 Story 3 will know exactly where to fix.
        """
        mockI2c.setVcell(4.10)
        vcell = upsMonitor.getVcell()

        with caplog.at_level(logging.INFO, logger="src.pi.power.orchestrator"):
            orchestrator.tick(
                currentVcell=vcell, currentSource=PowerSource.BATTERY,
            )

        assert orchestrator.state == PowerState.NORMAL

        infoMessages = _infoLogs(caplog)
        assert len(infoMessages) == 1, (
            f"Expected exactly 1 INFO discriminator log; got {infoMessages!r}"
        )
        _assertCommonLogShape(
            infoMessages[0], willTransition=False, reason="threshold_not_crossed",
        )
        assert "vcell=4.1" in infoMessages[0]
        assert "currentStage=normal" in infoMessages[0]

    def test_reason_ok_logsOnBatteryStageTransition(
        self,
        orchestrator: PowerDownOrchestrator,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Reason 5/5: ``OK`` is the happy-path transition discriminator.

        On BATTERY at 3.65V (below WARNING 3.70V), tick() must transition
        NORMAL -> WARNING and emit ``willTransition=True reason=OK``.
        If post-Drain-8 we see ``OK`` firing in the CSV but no STAGE_* row
        in ``power_log``, the bug is downstream of tick() -- in
        ``_enterStage``/``_writePowerLogStage`` (US-267 territory).
        """
        mockI2c.setVcell(3.65)
        vcell = upsMonitor.getVcell()

        with caplog.at_level(logging.INFO, logger="src.pi.power.orchestrator"):
            orchestrator.tick(
                currentVcell=vcell, currentSource=PowerSource.BATTERY,
            )

        assert orchestrator.state == PowerState.WARNING

        infoMessages = _infoLogs(caplog)
        assert len(infoMessages) == 1, (
            f"Expected exactly 1 INFO discriminator log; got {infoMessages!r}"
        )
        _assertCommonLogShape(
            infoMessages[0], willTransition=True, reason="OK",
        )
        # currentStage in the log line is the PRE-transition state so a
        # post-mortem can correlate the CSV row's pd_stage column with the
        # journalctl log line's currentStage at the same timestamp.  WARNING
        # appears in the post-tick state assertion above; the log line
        # captures NORMAL -- the entry stage of this tick.
        assert "currentStage=normal" in infoMessages[0]
        assert "vcell=3.65" in infoMessages[0]


# ================================================================================
# Negative invariant: AC happy path emits NO INFO log (no journal spam)
# ================================================================================


class TestAcHappyPathEmitsNoInfoLog:
    """The story invariant ``does NOT emit on AC ticks (no spam)`` is
    enforced by this test: AC operation (``EXTERNAL`` source during
    ``NORMAL`` state) must produce zero INFO discriminator logs so the
    journal is not flooded during normal (non-drain) operation.
    """

    def test_externalDuringNormal_emitsNoInfoLog(
        self,
        orchestrator: PowerDownOrchestrator,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mockI2c.setVcell(4.10)
        vcell = upsMonitor.getVcell()
        assert orchestrator.state == PowerState.NORMAL  # precondition

        with caplog.at_level(logging.INFO, logger="src.pi.power.orchestrator"):
            for _ in range(5):
                orchestrator.tick(
                    currentVcell=vcell, currentSource=PowerSource.EXTERNAL,
                )

        assert orchestrator.state == PowerState.NORMAL

        infoMessages = _infoLogs(caplog)
        assert infoMessages == [], (
            f"AC happy path emitted unexpected INFO discriminator logs: "
            f"{infoMessages!r}"
        )
