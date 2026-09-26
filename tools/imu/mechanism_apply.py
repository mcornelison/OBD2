################################################################################
# File Name: mechanism_apply.py
# Purpose/Description: ARCH-058 -- bind a drive phase to the hardware. Sets the
#   acquisition mode, restarts the collector, VERIFIES the attach, and RETRIES.
# Author: Atlas (architect) -- CIO-directed build; override recorded on ARCH-058
# Creation Date: 2026-09-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-26    | Atlas          | Initial -- retry-on-failed-attach; unwired
#               | (ARCH-058)     | mechanisms REFUSE rather than no-op.
# ================================================================================
################################################################################
"""Turn "phase N should be running mechanism M" into hardware that is doing it.

``drive_phases`` deliberately decides nothing about hardware. This is the other
half: it writes the mode, restarts the collector, and **proves the channel came
back** before reporting success.

🔴 WHY THE RETRY IS THE WHOLE MODULE. The startup hand-over is PROBABILISTIC.
ARCH-032 measured it at **~73-80 % per start** (n=20 per arm, interleaved) and the
mechanism is still unexplained. MEASURED again 2026-09-26: arming bypass took
**two** restarts -- the first came up on ``icm_shadow`` with ``headingDeg: null``.
⇒ A set-and-hope applier hands the operator a dead lap about one time in four.
**He is mid-errand, off WiFi, with no keyboard.** Nothing can rescue him but the
applier itself, so the applier retries and, if it cannot, says so loudly enough to
reach the screen.

🔴 WHY AN UNWIRED MECHANISM RAISES. ``MECH_KEEPALIVE_DRDY`` requires master's
slave-0 burst to start at **ST1 (0x10)** instead of **HXL (0x11)** so DRDY and HOFL
are actually read. That constant lives in ``src/pi/sensors/``, **outside this
bench's declared surface** (``tools/imu/**``, ``tests/tools/**``). Accepting the
mechanism and switching only the phase LABEL would be an inert guard wearing a
button -- the screen advances, nothing changes, and the comparison is silently
void. **It refuses, and the message names what is missing.**
⚠️ The bypass path ALREADY reads ST1..ST2 inclusive (``ak09916_bypass.py``:
``FRAME_START_REGISTER = REG_ST1``, 9-byte frame). DRDY is a property that path
already has; the open work is giving it to MASTER. Filed separately.

⚠️ WHY THE MODE IS WRITTEN ONCE AND ONLY THE RESTART REPEATS. Rewriting config on
every retry multiplies the chance of a torn file on a share with no undo, and the
config is not what failed -- the hand-over is.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from tools.imu.drive_phases import MECH_KEEPALIVE, MECH_ORIGINAL

__all__ = [
    "ApplyResult",
    "AttachNotVerified",
    "DEFAULT_ATTEMPTS",
    "DEFAULT_SETTLE_S",
    "MAG_MODE_FOR_MECHANISM",
    "MechanismNotWired",
    "applyMechanism",
]

#: Mechanism -> the ``pi.sensors.imu.magMode`` value that selects it.
#:
#: 🔴 MEMBERSHIP IS THE CONTRACT. A mechanism absent from this map is one this
#: harness cannot actually produce, and ``applyMechanism`` refuses it. Do not add
#: a row here until the code behind it exists -- a row is a promise the button
#: makes to the driver.
MAG_MODE_FOR_MECHANISM: dict[str, str] = {
    MECH_ORIGINAL: "bypass",
    MECH_KEEPALIVE: "master",
}

#: Restart attempts before giving up. At a ~75 % per-start hand-over, four
#: attempts leave roughly a 0.4 % chance of an unnecessary failure; one attempt
#: would leave ~25 %. MEASURED 2026-09-26: the real arming took two.
DEFAULT_ATTEMPTS: int = 4

#: Settle between restart and verify. MEASURED 2026-09-20: the OBD initial
#: connect times out at **30 s**, and a measurement taken sooner is dominated by
#: the startup transient -- a whole sampleHz sweep came back VOID that way.
DEFAULT_SETTLE_S: float = 45.0


class MechanismNotWired(RuntimeError):
    """The mechanism is unknown, or known but not producible by this harness.

    Raised rather than returned so no unapplied mechanism can reach the screen
    wearing the shape of an applied one.
    """


class AttachNotVerified(RuntimeError):
    """The mode was written and the collector restarted, but the channel never
    came back within the allowed attempts.

    ⚠️ This is NOT "the mechanism is bad" -- it is "we could not get it running
    this time". The caller must surface it; a phase silently running on the wrong
    channel produces data that looks fine and means nothing.
    """


@dataclass(frozen=True)
class ApplyResult:
    """What actually happened, in the operator's terms.

    Attributes:
        mechanism: The ``MECH_*`` requested.
        magMode: The config value written for it.
        attempts: Restarts spent, including the successful one. >1 is normal.
        verified: Always True on return -- a False would have raised.
    """

    mechanism: str
    magMode: str
    attempts: int
    verified: bool


def applyMechanism(
    mechanism: str,
    *,
    setModeFn: Callable[[str], None],
    restartFn: Callable[[], None],
    verifyFn: Callable[[], bool],
    attempts: int = DEFAULT_ATTEMPTS,
    settleSeconds: float = DEFAULT_SETTLE_S,
    sleepFn: Callable[[float], None] = time.sleep,
) -> ApplyResult:
    """Put the hardware onto ``mechanism`` and prove it took.

    Args:
        mechanism: One of the ``MECH_*`` constants from ``drive_phases``.
        setModeFn: Writes ``pi.sensors.imu.magMode``. Called exactly once.
        restartFn: Restarts the collector. Called once per attempt.
        verifyFn: True when the channel is attached and publishing. Must be
            independent of the thing it is checking -- a post-check that reads
            through the driver it just wrote to cannot rule out "the fix looks
            successful to itself".
        attempts: Restarts to spend before raising. Must be >= 1.
        settleSeconds: Waited after each restart, before verifying.
        sleepFn: Injected for tests.

    Returns:
        ApplyResult, only ever with ``verified=True``.

    Raises:
        MechanismNotWired: unknown mechanism, or one this harness cannot produce.
        AttachNotVerified: every attempt restarted but the channel never came back.
        ValueError: ``attempts`` below 1.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be >= 1, got {attempts!r}")

    # 🔴 RAISE on a missing key -- never default. A default converts a typo into a
    # plausible run under the wrong mechanism, and a plausible datum is not
    # reviewable. (design-patterns: a lookup in measurement code must raise.)
    if mechanism not in MAG_MODE_FOR_MECHANISM:
        wired = sorted(MAG_MODE_FOR_MECHANISM)
        raise MechanismNotWired(
            f"mechanism {mechanism!r} is not wired in this harness. Wired: {wired}. "
            "keepalive_drdy specifically needs master's slave-0 burst to start at "
            "ST1 (0x10) rather than HXL (0x11), which lives in src/pi/sensors/ -- "
            "outside this bench's declared surface, so it is filed separately "
            "rather than faked here."
        )

    magMode = MAG_MODE_FOR_MECHANISM[mechanism]
    setModeFn(magMode)  # once -- see the module docstring

    for attempt in range(1, attempts + 1):
        restartFn()
        sleepFn(settleSeconds)
        if verifyFn():
            return ApplyResult(
                mechanism=mechanism,
                magMode=magMode,
                attempts=attempt,
                verified=True,
            )

    raise AttachNotVerified(
        f"mechanism {mechanism!r} (magMode={magMode!r}) did not verify after "
        f"{attempts} restart attempt(s). "
        "The hand-over is ~73-80% per start (ARCH-032) and still unexplained; "
        "this is a failed draw, not evidence about the mechanism itself. "
        "DO NOT record a lap under it."
    )
