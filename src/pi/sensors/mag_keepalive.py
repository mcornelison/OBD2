################################################################################
# File Name: mag_keepalive.py
# Purpose/Description: ARCH-057 -- the magnetometer RUNTIME keep-alive. Detects a
#   frozen AK09916 channel by repeated-triple dwell and revives it by re-running
#   the magnetometer init, VERIFIED BY SAMPLING rather than by a return value.
# Author: Atlas (architect) -- CIO-directed build; override recorded on ARCH-057
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-25    | Atlas          | Initial -- ported from the 2026-09-18 drive-test
#               | (ARCH-057)     | console, where it MEASURED 20/20.
# ================================================================================
################################################################################
"""Keep the magnetometer demonstrably alive, or say so.

🔴 WHY THIS SHIPS NOW, AND THE HONEST HISTORY. This repair was written and MEASURED
on 2026-09-18 and then sat in ``offices/architect/evidence/`` and on the Pi as a
scratch file for a week, while production ran at **0/20**. The CIO believed it had
merged, because he had been told it was fixed -- and it was, in a harness that
nothing called. Same shape as ``pollingTiers`` (A-28) and the carousel emitters
(A-16): a complete, correct implementation with no caller. Recorded here rather
than presented as new work.

MEASURED on this hardware, 2026-09-18:

    do nothing (production today)      0 / 20
    re-init once                      17 / 20 = 85%
    re-init + verify + retry x3       20 / 20 = 100%

🔴 THE INIT'S RETURN VALUE IS NOT EVIDENCE. ``_magnetometer_init()`` returned True
on every hand run INCLUDING the one where the sensor stayed frozen. Liveness is
therefore established by SAMPLING -- the readings must CHANGE -- and never by a
success flag. This is the same rule as ``specs/anti-patterns.md``'s inert guard:
the presence of a check is evidence about intent, never about enforcement.

🔴 IT MUST BE A RUNTIME WATCHDOG, NOT A STARTUP FIX. The freeze arrives AFTER a
period of good readings (0.1-1.2 s in both bench runs), so a startup-only probe
passes and then dies one second into the drive.

⚠️ WHAT THIS DOES NOT DO. It does not calibrate anything: a live channel with the
measured 17.59 uT hard-iron offset -- which EXCEEDS the 16.43 uT rotating radius --
still reads about 100 deg wrong. Liveness and accuracy are different jobs; US-695
owns the second one.

⚠️ AND THE 20/20 IS AN UNCONTENDED NUMBER. It was measured with ``eclipse-obd``
STOPPED, i.e. sole owner of the I2C bus. ARCH-032 separately measured contention
taking the magnetometer hand-over from ~80% to ~12%. **This has not yet been
demonstrated on a contended bus, and nothing here should be read as claiming it.**
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from enum import Enum

logger = logging.getLogger(__name__)

__all__ = [
    "MAG_FROZEN_DWELL_S",
    "MAG_PLAUSIBLE_MAX_UT",
    "MagKeepAlive",
    "RestoreOutcome",
    "frozenRepeatsForRate",
]

#: How long a run of BIT-IDENTICAL triples must persist before the channel is
#: treated as frozen.
#:
#: 🔴 EXPRESSED IN SECONDS, AND THE COUNT IS DERIVED FROM THE RATE. The 2026-09-18
#: console used a bare count of 20, which was 2 s at its 10 Hz. Production polls at
#: 4 Hz, where the same 20 would be 5 s -- the threshold would have silently
#: changed meaning with a rate it has nothing to do with. That is exactly the
#: defect shape ruled on in US-803-b the day before this shipped, so the invariant
#: kept here is the WALL CLOCK.
#:
#: Basis for 2 s: the AK09916 runs continuous at 100 Hz, so between two polls at
#: any production rate there are many conversions and a real sensor dithers by
#: +/-1 LSB. A bit-identical run lasting 2 s is far beyond any honest repeat and
#: far below the 237 consecutive identical triples measured when the sensor was
#: actually dead.
MAG_FROZEN_DWELL_S: float = 2.0

#: ⚠️ ARCH-057's MAG_LIVENESS_SAMPLES / MAG_LIVENESS_GAP_S ARE GONE, deliberately.
#: They drove an 8 x 30 ms = 240 ms BLOCKING sample loop on the poll thread to
#: verify a repair. The poll loop already samples at 4 Hz and IS a liveness test,
#: so that verification was redundant and -- at 4 Hz -- expensive. Liveness is now
#: judged by whether the dwell RECURS.
#:
#: The CEILING for a real magnetometer reading. Earth's total field is 25-65 uT
#: globally and the AK09916's full scale is +/-4912 uT, so 250 uT sits far above
#: any real reading and far below saturation -- it catches the 18 overflow rows
#: measured on drive 84 without clipping anything real.
#:
#: ⚠️ DECLARED HERE, ENFORCED IN plausibility_gate.magnitudeAtMost. There is no
#: second predicate in this module: the reader gates through the existing
#: US-564 mechanism, and a private copy of one rule with no caller is the A-28
#: shape. NO FLOOR, deliberately -- a stuck-at-zero channel is already caught
#: by invariance, and a field floor would be invented physics.
MAG_PLAUSIBLE_MAX_UT: float = 250.0

#: Never derive a threshold below this. A zero or one-sample threshold would fire
#: on every poll and stall the loop in a permanent restore cycle -- the watchdog
#: becoming the outage.
_MIN_FROZEN_REPEATS: int = 2

#: A magnetometer cannot read exactly zero on all three axes: Earth's field is
#: never zero. It is what an uninitialised AK09916 reports, and the measured
#: source of the 98 all-zero rows in ``edr_imu_sample``.
_IMPOSSIBLE_TRIPLE = (0.0, 0.0, 0.0)


def frozenRepeatsForRate(sampleHz: float | None) -> int:
    """Consecutive identical triples that constitute :data:`MAG_FROZEN_DWELL_S`.

    Args:
        sampleHz: The reader's poll rate. A missing, non-finite or non-positive
            rate falls back to the floor rather than producing a threshold of
            zero.

    Returns:
        The repeat count, never below :data:`_MIN_FROZEN_REPEATS`.
    """
    if sampleHz is None or not math.isfinite(sampleHz) or sampleHz <= 0.0:
        return _MIN_FROZEN_REPEATS
    return max(_MIN_FROZEN_REPEATS, int(round(MAG_FROZEN_DWELL_S * sampleHz)))


class RestoreOutcome(Enum):
    """What :meth:`MagKeepAlive.requestRestore` did.

    Three values, because collapsing them would make the counters useless as a
    health signal: SUPPRESSED and BUSY are both "not attempted", for different
    reasons, and neither is a failure.
    """

    STARTED = "started"
    BUSY = "busy"
    SUPPRESSED = "suppressed"


class MagKeepAlive:
    """Notice a frozen mag channel, and repair it WITHOUT blocking the caller.

    🔴 THE DESIGN CONSTRAINT, AND IT IS THE WHOLE TICKET. ARCH-057 ran the repair
    inline on the IMU poll thread: three attempts x (adafruit's ~4 s
    reset-and-settle + a 240 ms blocking liveness loop) = the ~12.4 s stalls
    measured on drive 84, which cost 87% of that drive's samples and 90% of the
    CIO's deliberate calibration circles.

    ⇒ Here the caller only does bookkeeping. One background worker performs at
    most one re-init. Verification is the POLL LOOP itself: after a repair the
    dwell is cleared and the next window decides, so a check that used to cost
    240 ms of sleep now costs nothing.

    Not thread-safe for concurrent CALLERS by design -- one reader thread owns the
    sensor, and a lock here would only hide a second one.
    """

    #: One attempt. With verification off the hot path, retrying inline buys
    #: nothing: if the channel is still frozen the dwell fires again and the next
    #: request past the cooldown IS the retry.
    ATTEMPTS: int = 1

    #: Minimum gap between repairs. Bounds how often a dead sensor can schedule
    #: work, and leaves the poll loop several windows to judge the last repair.
    COOLDOWN_S: float = 5.0

    def __init__(
        self,
        *,
        reinitFn: Callable[[], None],
        monotonicFn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._reinit = reinitFn
        self._monotonic = monotonicFn
        self.repairsIssued = 0
        self.failures = 0
        self.suppressed = 0
        self.busy = 0
        self._lastRepair: float | None = None
        self._worker: threading.Thread | None = None
        self._lastTriple: tuple[float, float, float] | None = None
        self._repeats = 0

    # -- detection (runs on EVERY poll -- bookkeeping only) ---------------------
    def noteSample(
        self, triple: tuple[float, float, float] | None, *, sampleHz: float | None
    ) -> bool:
        """Fold one reading in; True when the frozen dwell has been reached.

        ⚠️ A ``None`` sample is NOT a repeat. Absence and unchanging-ness are
        different facts, and counting absence as repetition would schedule a
        repair for a channel that is missing rather than frozen.
        """
        if triple is None:
            return False
        if triple == self._lastTriple:
            self._repeats += 1
        else:
            self._lastTriple = triple
            self._repeats = 1
            return False
        return self._repeats >= frozenRepeatsForRate(sampleHz)

    def forget(self) -> None:
        """Drop the repeat run so the next window judges the repaired channel."""
        self._lastTriple = None
        self._repeats = 0

    # -- repair (NEVER blocks the caller) --------------------------------------
    def requestRestore(self, why: str) -> RestoreOutcome:
        """Ask for a repair. Returns immediately, always.

        Args:
            why: Recorded in the log so the journal says what prompted it.

        Returns:
            ``STARTED`` when a worker was launched, ``BUSY`` when one is already
            running, ``SUPPRESSED`` when inside the cooldown.

        🔴 BUSY IS NOT A QUEUE. Queueing would let a permanently frozen sensor
        schedule dozens of re-inits -- the ARCH-057 failure wearing a thread pool.
        """
        if self._worker is not None and self._worker.is_alive():
            self.busy += 1
            return RestoreOutcome.BUSY
        now = self._monotonic()
        if self._lastRepair is not None and (now - self._lastRepair) < self.COOLDOWN_S:
            self.suppressed += 1
            return RestoreOutcome.SUPPRESSED
        self._lastRepair = now
        # Cleared HERE rather than in the worker, so the poll loop stops re-firing
        # the dwell the instant a repair is scheduled, not several polls later.
        self.forget()
        self._worker = threading.Thread(
            target=self._repair, args=(why,), name="mag-keepalive", daemon=True
        )
        self._worker.start()
        return RestoreOutcome.STARTED

    def join(self, timeout: float | None = None) -> None:
        """Wait for an in-flight repair. Tests and orderly shutdown ONLY -- the
        poll loop must never call this, which is the point of the whole ticket."""
        w = self._worker
        if w is not None:
            w.join(timeout)

    def _repair(self, why: str) -> None:
        """The off-thread repair. Never raises; this thread is the only victim."""
        try:
            self._reinit()
        except Exception as exc:  # noqa: BLE001 -- a watchdog must not raise
            self.failures += 1
            logger.error(
                "mag keep-alive (%s): re-init FAILED with %s: %s -- heading from "
                "this channel is not trustworthy (%d failure(s) this run)",
                why, type(exc).__name__, exc, self.failures,
            )
            return
        self.repairsIssued += 1
        logger.warning(
            "mag keep-alive (%s): re-init issued off-thread (%d this run); "
            "liveness is judged by the next dwell window, not by this call",
            why, self.repairsIssued,
        )
