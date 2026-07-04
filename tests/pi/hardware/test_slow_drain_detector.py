################################################################################
# File Name: test_slow_drain_detector.py
# Purpose/Description: Unit tests for the SlowDrainDetector -- the F-051/US-444
#                      sustained-VCELL-decline health detector with flap-debounce.
#                      Pure state-machine tests driven by an explicit timestamp +
#                      VCELL trace (no hardware, no clock dependency).
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-03    | Rex (US-444) | Initial implementation. Covers: gradual-decline
#                              | -> SLOW_DRAIN; flat/noisy -> STABLE (no false
#                              | alarm); rapid flapping -> no committed on/off
#                              | (debounce); recovery -> STABLE (no stuck state);
#                              | insufficient window -> UNKNOWN (honest instrument);
#                              | debounce-hold timing.
# ================================================================================
################################################################################

"""SlowDrainDetector tests (F-051 / US-444).

The detector is a pure decision layer over a stream of ``(timestamp, VCELL)``
samples.  It carries no hardware and no wall clock -- every test feeds an
explicit monotonic timestamp so the debounce/window behaviour is fully
deterministic.

Grounding for the thresholds under test (F-051 backlog + drain tests 1-4):
- decline ``> 0.005 V`` over a ``300 s`` window is well above the sensor noise
  floor and fires within the first minutes of any real drain;
- a ``30 s`` debounce suppresses the 4-transitions-in-45-seconds flapping seen
  in the 2026-04-29 inverted-power drill.
"""

from __future__ import annotations

# tests/conftest.py puts src/ on sys.path.
from pi.hardware.slow_drain_detector import (
    DEFAULT_SLOW_DRAIN_DEBOUNCE_SECONDS,
    DEFAULT_SLOW_DRAIN_DECLINE_THRESHOLD_V,
    DEFAULT_SLOW_DRAIN_WINDOW_SECONDS,
    DrainState,
    SlowDrainDetector,
)

# ================================================================================
# Helpers
# ================================================================================


def _feed(
    detector: SlowDrainDetector,
    trace: list[tuple[float, float]],
) -> list[DrainState]:
    """Feed a ``(timestamp, vcell)`` trace and return the state after each sample."""
    return [detector.update(ts, vcell) for ts, vcell in trace]


def _countTransitions(states: list[DrainState]) -> int:
    """Count how many times the committed state changed across a sequence."""
    return sum(1 for prev, cur in zip(states, states[1:]) if prev != cur)


# ================================================================================
# Defaults / grounding
# ================================================================================


def test_defaults_matchGroundedF051Values() -> None:
    """
    Given: the module-level defaults
    When:  read directly
    Then:  they match the F-051-grounded values (300 s window, 0.005 V decline,
           30 s debounce) so a config regression is caught at the constant.
    """
    assert DEFAULT_SLOW_DRAIN_WINDOW_SECONDS == 300.0
    assert DEFAULT_SLOW_DRAIN_DECLINE_THRESHOLD_V == 0.005
    assert DEFAULT_SLOW_DRAIN_DEBOUNCE_SECONDS == 30.0


def test_freshDetector_reportsUnknown() -> None:
    """
    Given: a detector that has seen no samples
    When:  its state is queried
    Then:  it is UNKNOWN -- honest instrument, not a confident STABLE.
    """
    detector = SlowDrainDetector()
    assert detector.state is DrainState.UNKNOWN


# ================================================================================
# Slow-drain detection (the primary AC)
# ================================================================================


def test_update_gradualSustainedDecline_flagsSlowDrain() -> None:
    """
    Given: VCELL declining ~0.0015 V every 30 s (a slow gradual drain, well
           above the 0.005 V/window threshold once the window fills)
    When:  the trace is fed through a full 300 s window plus the 30 s debounce
    Then:  the detector commits SLOW_DRAIN -- the sustained decline is caught.
    """
    detector = SlowDrainDetector()
    trace = [(30.0 * i, 4.050 - 0.0015 * i) for i in range(13)]  # 0..360 s

    states = _feed(detector, trace)

    assert states[-1] is DrainState.SLOW_DRAIN
    # Before the window is full it must NOT confidently claim a drain.
    assert states[4] is DrainState.UNKNOWN  # t=120 s, window not yet full


def test_update_flatVoltage_staysStable_noFalseAlarm() -> None:
    """
    Given: a flat VCELL trace (AC-fed float; no drain) over a full window
    When:  fed past the window + debounce
    Then:  the detector commits STABLE and never SLOW_DRAIN -- no false alarm.
    """
    detector = SlowDrainDetector()
    trace = [(30.0 * i, 4.100) for i in range(14)]  # flat 4.10 V

    states = _feed(detector, trace)

    assert states[-1] is DrainState.STABLE
    assert DrainState.SLOW_DRAIN not in states


def test_update_smallNoiseWithinThreshold_staysStable() -> None:
    """
    Given: VCELL wiggling within the noise floor (< 0.005 V swing) but not
           net-declining across the window
    When:  fed past the window + debounce
    Then:  the detector stays STABLE -- sub-threshold noise is not a drain.
    """
    detector = SlowDrainDetector()
    noise = [0.000, 0.002, -0.001, 0.001, -0.002, 0.001, 0.000, 0.002]
    trace = [(30.0 * i, 4.100 + noise[i % len(noise)]) for i in range(16)]

    states = _feed(detector, trace)

    assert states[-1] is DrainState.STABLE
    assert DrainState.SLOW_DRAIN not in states


# ================================================================================
# Flap-debounce (the second AC)
# ================================================================================


def test_update_rapidFlapping_neverCommitsRepeatedOnOff() -> None:
    """
    Given: a raw drain signal that flips faster than the debounce window
           (every 2 s, well under the 30 s debounce) -- the flapping-signal
           case from the 2026-04-29 inverted-power drill
    When:  fed through the detector
    Then:  the committed state never toggles (zero transitions) -- flap
           suppression holds; no repeated on/off.
    """
    # Short window so a single step flips the raw windowed-decline verdict,
    # but a 30 s debounce that no 2 s flip can satisfy.
    detector = SlowDrainDetector(
        windowSeconds=6.0,
        declineThresholdVolts=0.005,
        debounceSeconds=30.0,
        minWindowFraction=0.5,
    )
    trace: list[tuple[float, float]] = []
    for i in range(20):
        t = 2.0 * i
        # Alternate high/low so the windowed decline crosses +/- threshold.
        vcell = 4.000 if i % 2 == 0 else 3.990
        trace.append((t, vcell))

    states = _feed(detector, trace)

    assert _countTransitions(states) == 0
    assert set(states) == {DrainState.UNKNOWN}


def test_update_slowDrainRawHeld_commitsOnlyAfterDebounce() -> None:
    """
    Given: a sustained decline that makes the raw verdict SLOW_DRAIN as soon as
           the window is full
    When:  observed across time
    Then:  the committed state stays UNKNOWN until the raw SLOW_DRAIN has held
           for the full debounce window, then commits -- the debounce is a
           genuine time gate, not instantaneous.
    """
    detector = SlowDrainDetector(
        windowSeconds=60.0,
        declineThresholdVolts=0.005,
        debounceSeconds=30.0,
        minWindowFraction=0.9,
    )
    # 10 s steps, declining 0.002 V/step -> 0.012 V over a full 60 s window.
    trace = [(10.0 * i, 4.050 - 0.002 * i) for i in range(13)]  # 0..120 s

    states = _feed(detector, trace)

    # First determinate (full window, span >= 54 s) is at t=60 s (i=6):
    # raw becomes SLOW_DRAIN there; it must NOT be committed yet.
    assert states[6] is not DrainState.SLOW_DRAIN
    # 30 s later (t=90 s, i=9) the debounce is satisfied -> committed.
    assert states[9] is DrainState.SLOW_DRAIN


# ================================================================================
# Recovery / no stuck state (B-051 residual gap)
# ================================================================================


def test_update_recoveryAfterDrain_returnsToStable_noStuckState() -> None:
    """
    Given: a sustained decline that commits SLOW_DRAIN, followed by a sustained
           recovery (alternator on -> VCELL rises) held past the debounce
    When:  the full trace is fed
    Then:  the detector returns to STABLE -- the flap-debounce does not leave a
           stuck SLOW_DRAIN state.
    """
    detector = SlowDrainDetector(
        windowSeconds=60.0,
        declineThresholdVolts=0.005,
        debounceSeconds=30.0,
        minWindowFraction=0.9,
    )
    # Phase A: decline for 130 s -> commits SLOW_DRAIN.
    declinePhase = [(10.0 * i, 4.050 - 0.002 * i) for i in range(14)]  # 0..130 s
    declineStates = _feed(detector, declinePhase)
    assert declineStates[-1] is DrainState.SLOW_DRAIN

    # Phase B: recovery -- VCELL climbs 0.003 V/step for another 130 s so the
    # whole rolling window is rising (windowed decline goes negative).
    lastT = declinePhase[-1][0]
    lastV = declinePhase[-1][1]
    recoveryPhase = [
        (lastT + 10.0 * i, lastV + 0.003 * i) for i in range(1, 14)
    ]
    recoveryStates = _feed(detector, recoveryPhase)

    assert recoveryStates[-1] is DrainState.STABLE


# ================================================================================
# Honest-instrument / insufficient data
# ================================================================================


def test_update_insufficientWindow_reportsUnknown() -> None:
    """
    Given: only a couple of samples spanning far less than the window
    When:  the detector is updated
    Then:  it reports UNKNOWN, not a confident STABLE or SLOW_DRAIN -- it will
           not judge on a partial window.
    """
    detector = SlowDrainDetector(windowSeconds=300.0)

    assert detector.update(0.0, 4.10) is DrainState.UNKNOWN
    assert detector.update(30.0, 4.05) is DrainState.UNKNOWN  # 30 s << 300 s


def test_update_singleSample_reportsUnknown() -> None:
    """
    Given: exactly one sample
    When:  queried
    Then:  UNKNOWN -- a slope needs two points.
    """
    detector = SlowDrainDetector()
    assert detector.update(0.0, 4.10) is DrainState.UNKNOWN
