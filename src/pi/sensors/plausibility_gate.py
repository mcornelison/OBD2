################################################################################
# File Name: plausibility_gate.py
# Purpose/Description: US-564 sensor plausibility/invariance gate (F-135) -- the
#   general guard that stops a NON-MEASUREMENT wearing data_source='real'.
#
#   Three defects found in one week are ONE defect: an all-zero IMU frame
#   (43,203 rows, 08-17), a latched magnetometer (~3 real reads then the same
#   value forever, 08-20), and a syncPending count nobody measured. Each looked
#   fresh, finite and plausible sample-by-sample. This module is the part that
#   catches the middle one -- and, deliberately, the NEXT one, whatever it is.
#
#   TWO INDEPENDENT CHECKS, ON THE SUCCESS PATH ONLY. The absence path (sensor
#   not wired -> retained state=absent + silence) and the error path (read raises
#   -> "no sample this poll") are both proven honest and are NOT touched here.
#
#   Check 1 -- IMPLAUSIBLE MAGNITUDE. A frame whose vector magnitude is below a
#   declared floor is not a reading (a stationary accelerometer must read
#   ~9.81 m/s^2; a moving one reads more, never ~0). Reported as `sensor_mute`.
#
#   Check 2 -- INVARIANCE, AND IT TESTS BIT-IDENTITY, NOT LOW VARIANCE. This is
#   the load-bearing design choice and it is the whole reason the gate needs no
#   magic number. Every real sensor dithers +/-1 LSB from thermal noise and ADC
#   quantization even in a perfectly constant field, so N consecutive
#   BIT-IDENTICAL samples cannot occur naturally -- measured 2026-08-20, a
#   stationary vehicle's accelerometer produced 743 distinct values in 90 s while
#   the magnetometer produced 1. A `variance < threshold` test would need a tuned
#   constant AND would false-positive on a genuinely still car; bit-identity
#   needs no threshold and cannot. Reported as `sensor_stale`.
#
#   ENROLMENT IS AN EVIDENCE DECISION, NEVER A DEFAULT. This module is
#   deliberately topic-agnostic: it owns the MECHANISM, and each reader declares
#   the PHYSICS for its own channels via ChannelPolicy. A channel with no
#   declared magnitude predicate is not magnitude-checked, and a channel not
#   enrolled in check 2 is never called stale -- because applying either check to
#   a channel whose real behaviour nobody has measured would repeat the exact
#   unmeasured-assumption that produced these three defects.
#
#   The reason vocabulary is DISTINCT from `sensor_absent` on purpose: the chip
#   IS enumerated and IS responding, which is a different fact from "not wired",
#   and the operator needs to be able to tell them apart.
# Author: Rex (US-564)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-564) | Initial -- checks 1+2, per-channel policy,
#               |              | dwell-derived run limit, transition flagging.
# ================================================================================
################################################################################

"""Plausibility + invariance gate: a non-measurement never passes as a reading."""

from __future__ import annotations

import math
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

__all__ = [
    "CHANNEL_STATE_PREFIX",
    "DEFAULT_INVARIANT_DWELL_S",
    "GATE_OK",
    "MIN_INVARIANT_RUN",
    "REASON_SENSOR_MUTE",
    "REASON_SENSOR_STALE",
    "ChannelPolicy",
    "GateVerdict",
    "PlausibilityGate",
    "bitKey",
    "channelStateTopic",
    "magnitudeAtLeast",
]

# The refusal vocabulary. Both are deliberately DISTINCT from the existing
# `sensor_absent`: absent means "not wired"; these mean "wired, enumerated,
# answering -- and not measuring".
REASON_SENSOR_MUTE = "sensor_mute"
REASON_SENSOR_STALE = "sensor_stale"

# The retained-state label for a channel that is reading normally. Distinct from
# both refusal reasons so a recovery marker can never be read as a fault.
GATE_OK = "ok"

# Retained per-channel gate STATE topics are derived from the raw topic they
# describe (`state.channel.raw.imu.mag`), so a subscriber binds to the channel it
# already knows rather than to a second hand-typed spelling of it.
CHANNEL_STATE_PREFIX = "state.channel."

# How long a channel must stay BIT-IDENTICAL before it is called stale.
#
# This is a DWELL, not a physical threshold, and the distinction matters: because
# bit-identity is a PROOF rather than a statistic, any run of 2 is already
# evidence a real sensor cannot produce. The dwell is pure margin against a
# scheduler hiccup or a driver re-serving one buffered frame, and it is expressed
# in SECONDS so a 50 Hz channel and a 1 Hz channel wait the same wall-clock time
# rather than sharing a retyped sample count that would mean two different waits.
# Overridable per reader via pi.sensors.<x>.invariantDwellSeconds.
DEFAULT_INVARIANT_DWELL_S = 2.0

# A run limit of 1 would call a channel's very FIRST sample invariant -- there is
# nothing to compare it against. Two is the smallest run that is a comparison.
MIN_INVARIANT_RUN = 2

# Fallback rate when a non-positive sampleHz slips through (defensive: the
# validated config always carries a positive rate, and a ZeroDivisionError in a
# 50 Hz sensor thread is not an acceptable way to find that out).
_FALLBACK_SAMPLE_HZ = 1.0


def channelStateTopic(topic: str) -> str:
    """Derive the retained gate-state topic for a raw channel.

    Args:
        topic: The raw bus topic (e.g. ``"raw.imu.mag"``).

    Returns:
        The retained STATE topic carrying that channel's gate verdict.
    """
    return f"{CHANNEL_STATE_PREFIX}{topic}"


def bitKey(value: Any) -> bytes | None:
    """Pack a sample into its exact IEEE-754 bit pattern for identity testing.

    Bit patterns, NOT ``==``: ``0.0 == -0.0`` is True, so an equality comparison
    would call a channel latched across a real sign-bit transition, and NaN
    compares unequal to itself, which would hide a genuinely stuck garbage read.
    The packed bytes answer the only question check 2 asks -- did a single bit
    move?

    Args:
        value: A scalar or an iterable of numbers, as published on the bus.

    Returns:
        The packed bytes, or None when the value is not a numeric reading (None
        included). A key of None never forms part of an invariant run: an
        already-honest absence must not be re-classified as a fault.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return struct.pack("<d", float(value))
    try:
        parts = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    if not parts:
        return None
    return struct.pack(f"<{len(parts)}d", *parts)


def magnitudeAtLeast(floor: float) -> Callable[[Any], bool]:
    """Build a check-1 predicate: the vector's length must reach ``floor``.

    Args:
        floor: The smallest magnitude that can be a real reading, inclusive.

    Returns:
        A predicate that is False for a short, non-finite or malformed vector,
        and never raises -- it runs inside a 50 Hz sensor thread.
    """

    def _plausible(value: Any) -> bool:
        try:
            parts = [float(v) for v in value]
        except (TypeError, ValueError):
            return False
        if len(parts) != 3 or not all(math.isfinite(p) for p in parts):
            return False
        return math.sqrt(sum(p * p for p in parts)) >= floor

    return _plausible


@dataclass(frozen=True)
class ChannelPolicy:
    """What the gate is allowed to assert about ONE channel.

    Attributes:
        plausible: Check-1 predicate, or None when this channel's physics have
            not been established. None means NOT magnitude-checked -- the gate
            never invents a floor it was not given.
        invariance: Whether check 2 applies. Enrol a channel only with evidence
            that it dithers (the ICM-20948's accel/gyro/mag do; a photon-counting
            light sensor can legitimately read a bit-exact zero in darkness).
    """

    plausible: Callable[[Any], bool] | None = None
    invariance: bool = False


@dataclass(frozen=True)
class GateVerdict:
    """One channel's verdict for one sample.

    Attributes:
        ok: False when the sample must NOT be published as a reading.
        reason: The refusal reason (``sensor_mute`` / ``sensor_stale``), or None.
        changed: True only on the sample where the channel's gate state
            TRANSITIONED. The retained state topic is a transition marker, not a
            50 Hz stream.
    """

    ok: bool = True
    reason: str | None = None
    changed: bool = False


class PlausibilityGate:
    """Per-channel plausibility + invariance state for one sensor reader.

    Single-threaded by contract: only the owning reader's poll thread calls
    :meth:`check`, exactly as the reader's own ``seq`` counter is.
    """

    def __init__(
        self,
        *,
        sampleHz: float = _FALLBACK_SAMPLE_HZ,
        policies: dict[str, ChannelPolicy] | None = None,
        invariantDwellSeconds: float = DEFAULT_INVARIANT_DWELL_S,
    ) -> None:
        """Bind the gate to one reader's channel set and poll rate.

        Args:
            sampleHz: The reader's poll rate; the invariant run limit is derived
                from it so the dwell is wall-clock, not sample-count.
            policies: Per-topic ChannelPolicy. A topic absent from this map is
                passed through unchecked.
            invariantDwellSeconds: How long a channel must stay bit-identical
                before check 2 refuses it.
        """
        self._policies = dict(policies or {})
        rate = sampleHz if sampleHz and sampleHz > 0 else _FALLBACK_SAMPLE_HZ
        dwell = (
            invariantDwellSeconds
            if invariantDwellSeconds and invariantDwellSeconds > 0
            else DEFAULT_INVARIANT_DWELL_S
        )
        self._runLimit = max(MIN_INVARIANT_RUN, int(math.ceil(rate * dwell)))
        # Per-topic running state: the last bit key, how many consecutive samples
        # have carried it, and the reason currently published for the channel.
        self._lastKey: dict[str, bytes | None] = {}
        self._runLength: dict[str, int] = {}
        self._reason: dict[str, str | None] = {}

    @property
    def invariantRunLimit(self) -> int:
        """Consecutive bit-identical samples that constitute a stale channel."""
        return self._runLimit

    def check(self, topic: str, value: Any) -> GateVerdict:
        """Inspect one successful read and decide whether it is a measurement.

        Args:
            topic: The raw bus topic the value would be published on.
            value: The value as read from the device.

        Returns:
            A GateVerdict. ``ok=False`` means the caller must publish NOTHING for
            this channel this poll -- routing it into the existing failed-poll
            path rather than into a new silence mechanism.
        """
        policy = self._policies.get(topic)
        if policy is None:
            return self._settle(topic, None)

        # Check 1 runs FIRST and its verdict is final for this sample. An
        # implausible value that happens to repeat is still implausible: the two
        # reasons name different faults, and letting a run of zeros be re-labelled
        # "stale" would lose the fact that the values were never possible.
        if policy.plausible is not None and value is not None and not policy.plausible(value):
            self._noteKey(topic, bitKey(value))
            return self._settle(topic, REASON_SENSOR_MUTE)

        key = bitKey(value)
        run = self._noteKey(topic, key)
        # A None key is an already-honest absence (saturated lux, missing temp).
        # It is passed through untouched and never accrues a run.
        if policy.invariance and key is not None and run >= self._runLimit:
            return self._settle(topic, REASON_SENSOR_STALE)
        return self._settle(topic, None)

    def reset(self) -> None:
        """Clear every channel's run and published reason.

        Called when the reader re-probes or the sensor is unplugged: a value read
        before the gap must not pair with one read after it to manufacture an
        invariant run across a period when nothing was reading at all.
        """
        self._lastKey.clear()
        self._runLength.clear()
        self._reason.clear()

    # -- internals -------------------------------------------------------------
    def _noteKey(self, topic: str, key: bytes | None) -> int:
        """Fold one sample's bit key into the channel's run, returning its length.

        A None key BREAKS the run rather than extending it -- an absent reading
        is not evidence that the channel is stuck.
        """
        if key is None:
            self._lastKey[topic] = None
            self._runLength[topic] = 0
            return 0
        if self._lastKey.get(topic) == key:
            run = self._runLength.get(topic, 0) + 1
        else:
            run = 1
        self._lastKey[topic] = key
        self._runLength[topic] = run
        return run

    def _settle(self, topic: str, reason: str | None) -> GateVerdict:
        """Compare this sample's reason with the channel's published one.

        Returns:
            The verdict, with ``changed`` set only on a genuine transition (into
            a fault, out of one, or between the two reasons) so the reader emits
            one retained marker per state change instead of one per poll.
        """
        changed = self._reason.get(topic) != reason
        self._reason[topic] = reason
        return GateVerdict(ok=reason is None, reason=reason, changed=changed)
