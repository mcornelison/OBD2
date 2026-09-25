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
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = [
    "MAG_FROZEN_DWELL_S",
    "MAG_LIVENESS_GAP_S",
    "MAG_LIVENESS_SAMPLES",
    "MagKeepAlive",
    "frozenRepeatsForRate",
    "magIsLive",
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

#: Samples taken to decide liveness, and the gap between them. 8 x 30 ms = 240 ms,
#: which spans ~24 conversions at the chip's 100 Hz -- enough that a live sensor
#: must move, short enough that the poll loop barely notices.
MAG_LIVENESS_SAMPLES: int = 8
MAG_LIVENESS_GAP_S: float = 0.03

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


def magIsLive(
    readFn: Callable[[], tuple[float, float, float]],
    *,
    samples: int = MAG_LIVENESS_SAMPLES,
    gapS: float = MAG_LIVENESS_GAP_S,
    sleepFn: Callable[[float], None] = time.sleep,
) -> bool:
    """True only when the readings demonstrably CHANGE and are not all-zero.

    Args:
        readFn: Returns one ``(x, y, z)`` triple. May raise; a raising reader is
            not live.
        samples: How many triples to take.
        gapS: Delay between samples.
        sleepFn: Injected for tests.

    Returns:
        True when at least two distinct, non-all-zero triples were seen.

    A raising reader resolves to NOT live rather than propagating: this runs
    inside a poll loop whose other channels must survive a magnetometer fault.
    """
    seen: list[tuple[float, float, float]] = []
    for _ in range(max(2, samples)):
        try:
            seen.append(tuple(readFn()))  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 -- any read failure means "not live"
            return False
        sleepFn(gapS)
    if all(v == _IMPOSSIBLE_TRIPLE for v in seen):
        return False
    return len(set(seen)) > 1


class MagKeepAlive:
    """Runtime watchdog: notice a frozen channel, re-init it, verify by sampling.

    Stateful but not thread-safe by design -- one reader thread owns the sensor,
    and a lock here would only hide a caller that had introduced a second one
    (the same reasoning as :class:`PitchFusion`).
    """

    #: Re-init attempts per restore. 85% -> 100% came from retrying.
    ATTEMPTS: int = 3

    #: Minimum gap between restores. Without it a genuinely dead sensor triggers
    #: a ~0.7 s stall on every poll and the watchdog becomes the outage.
    COOLDOWN_S: float = 5.0

    def __init__(
        self,
        *,
        reinitFn: Callable[[], None],
        livenessFn: Callable[[], bool],
        monotonicFn: Callable[[], float] = time.monotonic,
        sleepFn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._reinit = reinitFn
        self._liveness = livenessFn
        self._monotonic = monotonicFn
        self._sleep = sleepFn
        self.restores = 0
        self.failures = 0
        self.suppressed = 0
        self._lastRestore: float | None = None
        self._lastTriple: tuple[float, float, float] | None = None
        self._repeats = 0

    # -- detection -------------------------------------------------------------
    def noteSample(
        self, triple: tuple[float, float, float] | None, *, sampleHz: float | None
    ) -> bool:
        """Fold one reading in; True when the frozen dwell has been reached.

        Args:
            triple: The reading, or None when the poll produced nothing.
            sampleHz: The poll rate, so the dwell stays a wall-clock quantity.

        Returns:
            True exactly when this sample completes a frozen run.

        ⚠️ A ``None`` sample is NOT a repeat. An absent reading and an unchanging
        one are different facts, and counting absence as repetition would trigger
        a restore for a channel that is not frozen but missing.
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
        """Drop the repeat run -- called after a restore so the next detection
        starts from the repaired channel rather than from its frozen history."""
        self._lastTriple = None
        self._repeats = 0

    # -- repair ----------------------------------------------------------------
    def restore(self, why: str) -> bool:
        """Re-init until the sensor is demonstrably live. Never raises.

        Args:
            why: Recorded in the log so the journal says what prompted it.

        Returns:
            True when liveness was demonstrated; False when suppressed by the
            cooldown OR when every attempt failed. ⚠️ Those two are different and
            the counters distinguish them -- ``suppressed`` is "not asked", not
            "asked and failed". Collapsing them would make the failure count
            useless as a health signal, the same three-valued discipline as the
            rotation gate's UNDETERMINED.
        """
        now = self._monotonic()
        if self._lastRestore is not None and (now - self._lastRestore) < self.COOLDOWN_S:
            self.suppressed += 1
            return False
        self._lastRestore = now

        for attempt in range(1, self.ATTEMPTS + 1):
            try:
                self._reinit()
            except Exception as exc:  # noqa: BLE001 -- a watchdog must not raise
                logger.warning(
                    "mag keep-alive (%s): re-init attempt %d raised %s: %s",
                    why, attempt, type(exc).__name__, exc,
                )
                continue
            try:
                live = self._liveness()
            except Exception:  # noqa: BLE001
                live = False
            if live:
                self.restores += 1
                self.forget()
                logger.warning(
                    "mag keep-alive (%s): channel LIVE again after attempt %d "
                    "(%d restore(s) this run)", why, attempt, self.restores,
                )
                return True

        self.failures += 1
        logger.error(
            "mag keep-alive (%s): STILL FROZEN after %d attempts -- heading from "
            "this channel is not trustworthy (%d failure(s) this run)",
            why, self.ATTEMPTS, self.failures,
        )
        return False
