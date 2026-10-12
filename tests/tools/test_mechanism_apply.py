################################################################################
# File Name: test_mechanism_apply.py
# Purpose/Description: ARCH-058 -- the mechanism applier. Binding a phase to the
#   hardware: set the mode, restart the collector, VERIFY the attach, and RETRY.
# Author: Atlas (architect) -- CIO-directed build; override recorded on ARCH-058
# Creation Date: 2026-09-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-26    | Atlas          | Initial -- retry-on-failed-attach is the whole
#               | (ARCH-058)     | point; a silent no-op would strand the driver.
# ================================================================================
################################################################################
"""Why this module has tests before it has code.

🔴 THE FAILURE THIS GUARDS AGAINST IS MEASURED, NOT HYPOTHETICAL. Arming bypass
on 2026-09-26 took **two** restarts -- the first came up on ``icm_shadow`` with
``headingDeg: null``. ARCH-032 puts the startup hand-over at **~73-80 % per
start**, mechanism unexplained. ⇒ An applier that sets a mode, restarts, and
assumes it worked will hand the operator a dead lap roughly one time in four,
**and he is mid-errand with no keyboard and no network.**

🔴 AND A MECHANISM WE CANNOT ACTUALLY APPLY MUST REFUSE LOUDLY. ``MECH_KEEPALIVE_DRDY``
needs master's slave-0 burst to start at ST1 (0x10) rather than HXL (0x11), which
lives in ``src/pi/sensors/`` -- outside this bench's declared surface. Accepting it
and changing only the phase LABEL would be an inert guard wearing a button: the
screen would advance, nothing would switch, and the run would be silently void.
"""
from __future__ import annotations

import pytest

from tools.imu.drive_phases import (
    MECH_KEEPALIVE,
    MECH_KEEPALIVE_DRDY,
    MECH_ORIGINAL,
)
from tools.imu.mechanism_apply import (
    MAG_MODE_FOR_MECHANISM,
    ApplyResult,
    AttachNotVerified,
    MechanismNotWired,
    applyMechanism,
)


class _Rig:
    """Records what the applier did, and fails the attach on demand."""

    def __init__(self, verifyPattern: list[bool]) -> None:
        self.modes: list[str] = []
        self.restarts = 0
        self._pattern = list(verifyPattern)
        self.slept: list[float] = []

    def setMode(self, magMode: str) -> None:
        self.modes.append(magMode)

    def restart(self) -> None:
        self.restarts += 1

    def verify(self) -> bool:
        return self._pattern.pop(0) if self._pattern else False

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


# ------------------------------------------------------------------ mapping


def test_theMechanismMapCoversExactlyTheWiredMechanisms() -> None:
    """ORIGINAL and KEEPALIVE are wired; DRDY deliberately is not."""
    assert MAG_MODE_FOR_MECHANISM[MECH_ORIGINAL] == "bypass"
    assert MAG_MODE_FOR_MECHANISM[MECH_KEEPALIVE] == "master"
    assert MECH_KEEPALIVE_DRDY not in MAG_MODE_FOR_MECHANISM


def test_anUnwiredMechanismRAISESRatherThanSilentlyDoingNothing() -> None:
    """The inert-guard case: the button must not 'work' while nothing switches."""
    rig = _Rig([True])
    with pytest.raises(MechanismNotWired) as excinfo:
        applyMechanism(
            MECH_KEEPALIVE_DRDY,
            setModeFn=rig.setMode,
            restartFn=rig.restart,
            verifyFn=rig.verify,
            sleepFn=rig.sleep,
        )
    # the reason must name what is missing, not just say "no"
    assert "slave-0" in str(excinfo.value) or "ST1" in str(excinfo.value)
    assert rig.modes == [], "must not touch config for a mechanism it cannot apply"
    assert rig.restarts == 0, "must not restart the collector for a no-op"


def test_anUnknownMechanismRAISESInsteadOfDefaulting() -> None:
    """A lookup in safety/measurement code raises on a missing key.

    A default would turn a typo into a plausible run under the wrong mechanism,
    and a plausible datum is not reviewable.
    """
    rig = _Rig([True])
    with pytest.raises(MechanismNotWired):
        applyMechanism(
            "not_a_mechanism",
            setModeFn=rig.setMode,
            restartFn=rig.restart,
            verifyFn=rig.verify,
            sleepFn=rig.sleep,
        )


# ------------------------------------------------------------------ happy path


def test_aCleanAttachSetsTheModeRestartsOnceAndReportsVerified() -> None:
    rig = _Rig([True])
    result = applyMechanism(
        MECH_ORIGINAL,
        setModeFn=rig.setMode,
        restartFn=rig.restart,
        verifyFn=rig.verify,
        sleepFn=rig.sleep,
    )
    assert isinstance(result, ApplyResult)
    assert result.mechanism == MECH_ORIGINAL
    assert result.magMode == "bypass"
    assert result.attempts == 1
    assert result.verified is True
    assert rig.modes == ["bypass"]
    assert rig.restarts == 1


# ------------------------------------------------------- the retry, the point


def test_aFailedAttachIsRETRIEDAndTheAttemptCountIsReported() -> None:
    """MEASURED 2026-09-26: bypass needed two restarts. One retry is not enough
    margin against a ~73-80 % per-start hand-over, so the default allows more."""
    rig = _Rig([False, False, True])
    result = applyMechanism(
        MECH_ORIGINAL,
        setModeFn=rig.setMode,
        restartFn=rig.restart,
        verifyFn=rig.verify,
        sleepFn=rig.sleep,
    )
    assert result.attempts == 3
    assert result.verified is True
    assert rig.restarts == 3
    # the mode is written once; only the restart is repeated
    assert rig.modes == ["bypass"]


def test_theModeIsWrittenOnceEvenAcrossRetries() -> None:
    rig = _Rig([False, True])
    applyMechanism(
        MECH_KEEPALIVE,
        setModeFn=rig.setMode,
        restartFn=rig.restart,
        verifyFn=rig.verify,
        sleepFn=rig.sleep,
    )
    assert rig.modes == ["master"], "rewriting config per retry invites a torn file"


def test_anAttachThatNeverVerifiesRAISESWithTheAttemptCount() -> None:
    """Silence is not success. The operator must be told, on the screen."""
    rig = _Rig([False, False, False, False])
    with pytest.raises(AttachNotVerified) as excinfo:
        applyMechanism(
            MECH_ORIGINAL,
            setModeFn=rig.setMode,
            restartFn=rig.restart,
            verifyFn=rig.verify,
            attempts=4,
            sleepFn=rig.sleep,
        )
    assert "4" in str(excinfo.value)
    assert rig.restarts == 4


def test_theSettleIsHonouredBetweenRestartAndVerify() -> None:
    """MEASURED: the OBD connect timeout is 30 s, so any check taken sooner than
    ~45 s after a restart is dominated by the startup transient (2026-09-20)."""
    rig = _Rig([True])
    applyMechanism(
        MECH_ORIGINAL,
        setModeFn=rig.setMode,
        restartFn=rig.restart,
        verifyFn=rig.verify,
        settleSeconds=45.0,
        sleepFn=rig.sleep,
    )
    assert rig.slept == [45.0]


def test_attemptsMustBeAtLeastOne() -> None:
    rig = _Rig([True])
    with pytest.raises(ValueError):
        applyMechanism(
            MECH_ORIGINAL,
            setModeFn=rig.setMode,
            restartFn=rig.restart,
            verifyFn=rig.verify,
            attempts=0,
            sleepFn=rig.sleep,
        )
