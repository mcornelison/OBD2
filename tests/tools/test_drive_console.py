################################################################################
# File Name: test_drive_console.py
# Purpose/Description: ARCH-058 -- the BUTTON-driven session controller that
#   runs the CIO's step sequence and keeps the durable step log.
# Author: Atlas (architect) -- CIO-directed build; override recorded on ARCH-058
# Creation Date: 2026-09-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-27    | Atlas          | Initial -- button advance, retry after a
#               | (ARCH-058)     | failed draw, durable log, restore-on-end.
# 2026-09-27    | Atlas          | Reworked to the CIO's own 24-step sequence:
#               | (ARCH-058)     | BEGIN / START+STOP A / START+STOP B; marker
#               |                | presses are instant, switch presses verify.
# ================================================================================
################################################################################
"""What the driver's buttons must guarantee, tested before the code.

🔴 THE ROWS DO NOT KNOW WHICH MECHANISM PRODUCED THEM. MEASURED 2026-09-27:
``edr_imu_sample`` carries ``mag_x/y/z`` and no source column. **The step log is
the ONLY record that partitions the drive** -- and the START/STOP presses are
what line it up with the CIO's Strava track. A press logged but not applied, or
applied but not logged, voids the comparison silently; both are pinned here.

🔴 A FAILED DRAW MUST BE VISIBLE AND RECOVERABLE (hand-over ~75 %/start,
ARCH-032): NOT RECORDING on screen, the button becomes RETRY for the SAME step.
"""
from __future__ import annotations

import json

import pytest

from tools.imu.drive_console import CIO_2026_09_27_STEPS, DriveConsole
from tools.imu.drive_phases import MECH_KEEPALIVE, MECH_ORIGINAL
from tools.imu.mechanism_apply import ApplyResult, AttachNotVerified


class _Rig:
    """Fake hardware: records calls, fails on demand."""

    def __init__(self, failFor: set[int] | None = None) -> None:
        self.applied: list[str] = []
        self.failFor = failFor or set()  # apply-call indices (0-based) that fail
        self.restored = 0
        self.events: list[dict] = []
        self.now = 1000.0

    def apply(self, mechanism: str, onAttempt) -> ApplyResult:
        idx = len(self.applied)
        self.applied.append(mechanism)
        onAttempt(1)
        if idx in self.failFor:
            raise AttachNotVerified(f"{mechanism} did not verify")
        mode = "bypass" if mechanism == MECH_ORIGINAL else "master"
        return ApplyResult(mechanism=mechanism, magMode=mode, attempts=1, verified=True)

    def restore(self) -> str:
        self.restored += 1
        return "restored"

    def log(self, event: dict) -> None:
        self.events.append(event)

    def clock(self) -> float:
        return self.now


def _console(rig: _Rig) -> DriveConsole:
    return DriveConsole(
        CIO_2026_09_27_STEPS,
        applyFn=rig.apply,
        restoreFn=rig.restore,
        logFn=rig.log,
        clockFn=rig.clock,
        utcFn=lambda: "2026-09-27T18:00:00Z",
        runInline=True,
    )


def _pressAll(c: DriveConsole, n: int) -> None:
    for _ in range(n):
        assert c.press() is True


# -- the sequence ---------------------------------------------------------------

def test_theButtons_areTheCiosSequence() -> None:
    assert [s.button for s in CIO_2026_09_27_STEPS] == [
        "BEGIN", "START TEST A", "STOP TEST A", "START TEST B", "STOP TEST B"]


def test_theMechanisms_areOriginalBypass_ABypass_BMaster_thenBackToBypass() -> None:
    """CIO ruling 2026-09-27: original = bypass, A = bypass, B = master; STOP A is
    a mark only; STOP B returns to the original."""
    assert [s.mechanism for s in CIO_2026_09_27_STEPS] == [
        MECH_ORIGINAL, None, None, MECH_KEEPALIVE, MECH_ORIGINAL]


def test_beforeBegin_nothingIsApplied_andTheButtonSaysBEGIN() -> None:
    rig = _Rig()
    c = _console(rig)
    assert rig.applied == []
    s = c.status()
    assert s["button"] == "BEGIN" and s["state"] == "ready"
    assert s["nextSwitches"] is True


def test_theFullSequence_switchesOnlyWhereItMust() -> None:
    rig = _Rig()
    c = _console(rig)
    _pressAll(c, 5)
    assert rig.applied == [MECH_ORIGINAL, MECH_KEEPALIVE, MECH_ORIGINAL]
    s = c.status()
    assert s["button"] == "DONE" and s["magMode"] == "bypass"


def test_markerPresses_areInstant_andLogged() -> None:
    rig = _Rig()
    c = _console(rig)
    _pressAll(c, 3)  # BEGIN, START A, STOP A
    assert rig.applied == [MECH_ORIGINAL], "a marker must never restart the collector"
    marks = [e for e in rig.events if e["event"] == "mark"]
    assert [m["button"] for m in marks] == ["START TEST A", "STOP TEST A"]
    assert all(m["magMode"] == "bypass" for m in marks)
    assert c.status()["nextSwitches"] is True  # START TEST B is next


def test_everyPress_isLoggedWithUtc_inOrder() -> None:
    rig = _Rig()
    c = _console(rig)
    _pressAll(c, 5)
    pressed = [e["button"] for e in rig.events if e["event"] == "press"]
    assert pressed == ["BEGIN", "START TEST A", "STOP TEST A", "START TEST B", "STOP TEST B"]
    assert all(e["utc"] == "2026-09-27T18:00:00Z" for e in rig.events)


def test_aSwitchIsLoggedRequestedBeforeVerified() -> None:
    """The request lands FIRST, so a hard cut mid-switch still bounds the window."""
    rig = _Rig()
    c = _console(rig)
    c.press()
    kinds = [e["event"] for e in rig.events]
    assert kinds.index("switch_requested") < kinds.index("switch_verified")


def test_pastTheLastStep_theButtonIsRefused() -> None:
    rig = _Rig()
    c = _console(rig)
    _pressAll(c, 5)
    assert c.press() is False


def test_aPressWhileSwitching_isIgnored() -> None:
    rig = _Rig()
    c = _console(rig)
    c._state = "switching"
    assert c.press() is False
    assert rig.applied == []


# -- failure --------------------------------------------------------------------

def test_aFailedDraw_showsFailed_andRETRYRepeatsTheSAMEStep() -> None:
    rig = _Rig(failFor={1})  # START TEST B's switch to master fails once
    c = _console(rig)
    _pressAll(c, 4)
    s = c.status()
    assert s["state"] == "failed" and s["button"] == "RETRY"
    assert s["magMode"] is None, "an unverified switch must not claim a mode"
    assert any(e["event"] == "switch_failed" for e in rig.events)
    assert c.press() is True
    assert rig.applied == [MECH_ORIGINAL, MECH_KEEPALIVE, MECH_KEEPALIVE]
    s = c.status()
    assert s["state"] == "recording" and s["button"] == "STOP TEST B"


def test_aFailedSwitch_isNeverLoggedAsVerified() -> None:
    rig = _Rig(failFor={1})
    c = _console(rig)
    _pressAll(c, 4)
    verified = [e["mechanism"] for e in rig.events if e["event"] == "switch_verified"]
    assert verified == [MECH_ORIGINAL]


# -- end -------------------------------------------------------------------------

def test_end_restoresExactlyOnce_andLogs() -> None:
    rig = _Rig()
    c = _console(rig)
    c.press()
    c.end()
    c.end()
    assert rig.restored == 1
    assert c.status()["sessionOver"] is True
    assert any(e["event"] == "session_end" for e in rig.events)


def test_end_stillRestores_afterAFailedSwitch() -> None:
    rig = _Rig(failFor={0})
    c = _console(rig)
    c.press()
    assert c.status()["state"] == "failed"
    c.end()
    assert rig.restored == 1


# -- the screen -------------------------------------------------------------------

def test_status_carriesWhatTheScreenNeeds() -> None:
    rig = _Rig()
    c = _console(rig)
    c.press()
    rig.now += 75.0
    s = c.status()
    for key in ("stepIndex", "stepTotal", "phaseLabel", "magMode", "state", "button",
                "nextSwitches", "attempt", "elapsedInPhaseS", "sessionOver", "error"):
        assert key in s, key
    assert s["magMode"] == "bypass"
    assert s["elapsedInPhaseS"] == pytest.approx(75.0)
    assert s["button"] == "START TEST A"
    assert s["nextSwitches"] is False


def test_theElapsedTimer_restartsAtAMarker_soItTimesTheLoop() -> None:
    rig = _Rig()
    c = _console(rig)
    c.press()          # BEGIN
    rig.now += 300.0
    c.press()          # START TEST A
    rig.now += 42.0
    assert c.status()["elapsedInPhaseS"] == pytest.approx(42.0)


def test_theLogEvents_areJsonSerialisable() -> None:
    rig = _Rig(failFor={1})
    c = _console(rig)
    _pressAll(c, 4)
    c.end()
    for e in rig.events:
        json.dumps(e)


# ============ ATTACH JUDGEMENT (garage dry run, 2026-09-27) ===================
#
# 🔴 THE DRY RUN CAUGHT THIS. The first verify gated on HEADING QUALITY (>= 80 %
# non-null, >= 2 distinct). On master it read 15 % non-null -- which is master's
# NORMAL behaviour: the freeze gate nulls the heading between keep-alive repairs.
# Gating on it would have rejected master four times and shown NOT RECORDING,
# or passed only its lucky draws. **Either way it biases the very comparison the
# drive exists to make.** Verify proves the mechanism ATTACHED; how well it
# performs is the MEASUREMENT, and is logged as evidence, never gated on.

from tools.imu.drive_console import judgeAttach  # noqa: E402

_BYPASS_OK = "AK09916 configured over I2C bypass: CNTL2=0x08 (verified by readback)"
_BYPASS_FAIL = ("IMU magnetometer bypass unavailable (OSError) -- mag source is "
                "'icm_shadow', NOT 'bypass'.")
_MASTER_OK = "IMU magnetometer: MASTER mode ('master') -- bypass not attempted"


def test_masterWithAMostlyNullHeading_IS_attached() -> None:
    """The exact dry-run case. 3 of 20 non-null is master performing, not failing."""
    ok, ev = judgeAttach("master", _MASTER_OK, [None] * 17 + [310.0, 311.0, 312.0],
                         stateFresh=True)
    assert ok is True
    assert ev["headingNonNullFrac"] == 0.15  # recorded as evidence


def test_bypassThatFellBackToIcmShadow_isNOTAttached() -> None:
    """The real failed draw (~25 %/start): the collector says so in its own log."""
    ok, _ = judgeAttach("bypass", _BYPASS_OK + "\n" + _BYPASS_FAIL, [None] * 20,
                        stateFresh=True)
    assert ok is False


def test_theWrongMechanismsAttachLine_doesNotCount() -> None:
    """A master line cannot prove bypass, and vice versa."""
    assert judgeAttach("bypass", _MASTER_OK, [1.0, 2.0], stateFresh=True)[0] is False
    assert judgeAttach("master", _BYPASS_OK, [1.0, 2.0], stateFresh=True)[0] is False


def test_noAttachLine_isNOTAttached_evenWithALiveHeading() -> None:
    ok, _ = judgeAttach("bypass", "", [1.0, 2.0, 3.0], stateFresh=True)
    assert ok is False


def test_aStaleStateFile_isNOTAttached() -> None:
    """A collector that attached and then died leaves a correct log line and a
    frozen state file."""
    ok, _ = judgeAttach("bypass", _BYPASS_OK, [1.0, 2.0], stateFresh=False)
    assert ok is False


def test_bypassHealthy_isAttached_andItsHeadingIsEvidenceOnly() -> None:
    ok, ev = judgeAttach("bypass", _BYPASS_OK, [300.0] * 20, stateFresh=True)
    assert ok is True, "a frozen heading is a MEASUREMENT of bypass, not a failed attach"
    assert ev["headingDistinct"] == 1


def test_anUnknownMode_raises_ratherThanDefaulting() -> None:
    with pytest.raises(KeyError):
        judgeAttach("drdy", _MASTER_OK, [], stateFresh=True)


# ============ MAIN WIRING GUARD (garage dry run 3, 2026-09-27) ================
# 🔴 main() is hardware glue and not unit-tested -- and it crashed on the Pi
# calling console.start(), a method the step rework had removed. The crash also
# left the kiosk taken with NO restore. This pins every console.<attr> main()
# uses to a real attribute, and that main() restores on ANY exception.

import inspect  # noqa: E402
import re  # noqa: E402

from tools.imu import drive_console as _dc  # noqa: E402


def test_everyConsoleMethodMainCalls_exists() -> None:
    src = inspect.getsource(_dc.main)
    used = set(re.findall(r"\bconsole\.(\w+)", src))
    assert used, "main() no longer drives the console at all?"
    missing = sorted(a for a in used if not hasattr(DriveConsole, a))
    assert not missing, f"main() calls DriveConsole.{missing}, which do not exist"


def test_mainRestoresTheCar_onAnyException() -> None:
    src = inspect.getsource(_dc.main)
    assert "finally:" in src and "console.end()" in src.split("finally:")[-1], (
        "main() must call console.end() in a finally -- a crash after the kiosk "
        "takeover otherwise leaves the dashboard and watchdog stopped")
