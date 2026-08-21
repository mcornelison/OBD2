################################################################################
# File Name: test_plausibility_gate.py
# Purpose/Description: US-564 gate for the sensor plausibility/invariance guard
#   (src/pi/sensors/plausibility_gate.py). Pins the two checks Atlas specified:
#   implausible MAGNITUDE (catches an all-zero IMU frame) and BIT-IDENTICAL
#   invariance (catches the latched magnetometer), plus the anti-false-positive
#   guarantee that a genuinely stationary vehicle never trips check 2.
#
#   The load-bearing pin is NEGATIVE and it runs on REAL HARDWARE DATA:
#   `TestAgainstRealCapturedStationaryData` replays 90 s of genuinely captured
#   parked-car samples (tests/fixtures/imu_stationary_90s_2026-08-21.csv, pulled
#   off chi-eclipse-01's edr_imu_sample) and asserts the gate never refuses the
#   accel/gyro channels while it DOES refuse the latched magnetometer. A gate
#   that has never been SEEN to hold its fire on real stationary data is not
#   known to be false-positive-free.
#
#   Why real data and not just constructed dither: a fixture that ASSERTS a
#   hardware fact makes its own suite unfalsifiable -- the finding that refuted
#   US-560 earlier in this same sprint (BL-034, the fabricated PANEL_MODES).
#   The synthetic +/-1-ULP test is kept as a BOUNDARY pin and is labelled
#   synthetic; it cannot witness that the real chip dithers, because
#   `math.nextafter` never repeats by construction.
# Author: Rex (US-564)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-564) | Initial -- checks 1+2, run limit derivation,
#               |              | recovery, bit-identity vs numeric equality.
# 2026-08-21    | Rex (US-564) | Wire the REAL captured stationary-vehicle
#               |              | fixture in (validationCriteria #2 evidence);
#               |              | relabel the synthetic ULP pin as synthetic.
# ================================================================================
################################################################################

"""Tests for the US-564 sensor plausibility/invariance gate."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from pi.sensors.plausibility_gate import (
    DEFAULT_INVARIANT_DWELL_S,
    GATE_OK,
    MIN_INVARIANT_RUN,
    REASON_SENSOR_MUTE,
    REASON_SENSOR_STALE,
    ChannelPolicy,
    PlausibilityGate,
    bitKey,
    channelStateTopic,
    magnitudeAtLeast,
)

_ACCEL = "raw.imu.accel"
_GYRO = "raw.imu.gyro"
_MAG = "raw.imu.mag"
_LUX = "raw.light.lux"

# -- the real-hardware capture ------------------------------------------------
# tests/pi/sensors/ -> tests/fixtures/. Real rows pulled off chi-eclipse-01's
# edr_imu_sample; see the CSV's own header block for the query and provenance.
_FIXTURE = Path(__file__).parents[2] / "fixtures" / "imu_stationary_90s_2026-08-21.csv"

# The distinct-value counts MEASURED over this exact window, quoted from the
# fixture header. Re-derived from the data by test, so a regenerated or rounded
# capture goes RED instead of silently weakening every assertion below it.
_MEASURED_ROWS = 1845
_MEASURED_DISTINCT = {_ACCEL: 1821, _GYRO: 1845, _MAG: 1}

# The capture's real rate: 1845 rows / 90 s (the decimated persistHz stream).
# Used instead of the reader's 50 Hz so the dwell spans the wall-clock time it
# would on this data, rather than a sample count borrowed from another stream.
_FIXTURE_HZ = 20.5

# A stationary 1 g reading with the board flat (the accel check-1 floor is 0.5).
_RESTING = (0.03, -0.01, 9.81)


def _imuPolicies() -> dict[str, ChannelPolicy]:
    """The IMU channel policy set under test (accel magnitude-checked)."""
    return {
        _ACCEL: ChannelPolicy(plausible=magnitudeAtLeast(0.5), invariance=True),
        _MAG: ChannelPolicy(invariance=True),
    }


def _gate(**kw) -> PlausibilityGate:
    """Build a gate over the IMU policies at the reader's 50 Hz burst rate."""
    kw.setdefault("sampleHz", 50)
    kw.setdefault("policies", _imuPolicies())
    return PlausibilityGate(**kw)


def _loadCapture() -> dict[str, list[tuple[float, float, float]]]:
    """Load the real stationary-vehicle capture into per-channel sample lists.

    Parsed with ``splitlines()`` rather than the ``csv`` module so no newline
    handling is involved -- and the values are kept as full-precision floats,
    NEVER rounded, because bit-identity is the property under test and rounding
    would manufacture the exact invariance the gate is supposed to detect.

    Returns:
        ``{topic: [(x, y, z), ...]}`` for accel, gyro and mag, in capture order.

    Raises:
        AssertionError: If the fixture is missing. Deliberately a FAILURE and
            not a ``skip``: this file is the only hardware evidence that a real
            sensor dithers, and the whole no-threshold design rests on it. A
            skip would quietly restore the unfalsifiable state that this test
            exists to end, and it would do it while the suite still read green.
    """
    assert _FIXTURE.is_file(), (
        f"missing the real-hardware capture at {_FIXTURE} -- the anti-false-positive "
        "guarantee cannot be evidenced without it; re-extract it from the Pi rather "
        "than deleting or skipping this test (see the CSV header for the query)"
    )
    out: dict[str, list[tuple[float, float, float]]] = {_ACCEL: [], _GYRO: [], _MAG: []}
    for line in _FIXTURE.read_text(encoding="utf-8").splitlines():
        row = line.strip()
        if not row or row.startswith("#"):
            continue
        parts = [float(p) for p in row.split(",")]
        out[_ACCEL].append((parts[0], parts[1], parts[2]))
        out[_GYRO].append((parts[3], parts[4], parts[5]))
        out[_MAG].append((parts[6], parts[7], parts[8]))
    return out


def _realDataGate() -> PlausibilityGate:
    """A gate carrying the IMU's real policy set at the capture's own rate."""
    return PlausibilityGate(
        sampleHz=_FIXTURE_HZ,
        policies={
            _ACCEL: ChannelPolicy(plausible=magnitudeAtLeast(0.5), invariance=True),
            _GYRO: ChannelPolicy(invariance=True),
            _MAG: ChannelPolicy(invariance=True),
        },
    )


class TestCheckOneImplausibleMagnitude:
    """Check 1 -- a frame whose magnitude is below the floor is not a reading."""

    def test_check_allZeroAccelFrame_isMuted(self):
        """
        Given: the IMU returns a bit-exact all-zero acceleration vector
        When: the gate inspects it
        Then: it is REFUSED as sensor_mute (43,203 such rows landed on 08-17)
        """
        verdict = _gate().check(_ACCEL, (0.0, 0.0, 0.0))
        assert verdict.ok is False
        assert verdict.reason == REASON_SENSOR_MUTE

    def test_check_restingOneGFrame_passes(self):
        """
        Given: a stationary sensor reading ~9.81 m/s^2
        When: the gate inspects it
        Then: it passes -- the floor must not gate a real resting frame
        """
        verdict = _gate().check(_ACCEL, _RESTING)
        assert verdict.ok is True
        assert verdict.reason is None

    def test_check_nonFiniteAccel_isMuted(self):
        """
        Given: a burst carrying NaN (a garbage read, not a measurement)
        When: the gate inspects it
        Then: sensor_mute -- a non-finite value can never be a reading
        """
        verdict = _gate().check(_ACCEL, (float("nan"), 0.0, 9.8))
        assert verdict.ok is False
        assert verdict.reason == REASON_SENSOR_MUTE

    def test_check_channelWithNoPlausibilityPolicy_isNotMagnitudeChecked(self):
        """
        Given: a channel with NO declared magnitude predicate (the magnetometer)
        When: it reports a small-but-real field
        Then: it passes -- the gate never invents physics it was not given.
              Enrolling a channel is an EVIDENCE decision, not a default.
        """
        verdict = _gate().check(_MAG, (0.1, 0.0, 0.0))
        assert verdict.ok is True

    def test_check_mutePrecedesStale_onAnAllZeroRun(self):
        """
        Given: an all-zero accel frame repeated past the invariance run limit
        When: the gate inspects each one
        Then: the reason stays sensor_mute -- an implausible value is reported as
              implausible, not re-labelled "stale" once it has repeated enough.
              The two reasons name different faults and must not blur.
        """
        gate = _gate()
        for _ in range(gate.invariantRunLimit + 5):
            verdict = gate.check(_ACCEL, (0.0, 0.0, 0.0))
        assert verdict.reason == REASON_SENSOR_MUTE


class TestCheckTwoBitIdenticalInvariance:
    """Check 2 -- N consecutive BIT-IDENTICAL samples means the channel is dead."""

    def test_check_latchedMagnetometer_goesStaleAtTheRunLimit(self):
        """
        Given: the AK09916 serving one value forever (drive 40: 29,148 samples,
               1 distinct value)
        When: the gate sees `invariantRunLimit` consecutive identical vectors
        Then: it REFUSES as sensor_stale, and not one sample earlier
        """
        gate = _gate()
        latched = (-26.7, 11.4, -40.2)
        limit = gate.invariantRunLimit
        for i in range(limit - 1):
            assert gate.check(_MAG, latched).ok is True, f"tripped early at sample {i + 1}"
        verdict = gate.check(_MAG, latched)
        assert verdict.ok is False
        assert verdict.reason == REASON_SENSOR_STALE

    def test_check_syntheticUlpDither_neverStale(self):
        """
        Given: SYNTHETIC +/-1-ULP dither -- the tightest possible non-identical
               signal, constructed to sit exactly on the bit-identity boundary
        When: the gate sees far MORE samples than the run limit
        Then: it never fires. This pins the BOUNDARY: even a difference of one
              representable float step is a difference, so the check cannot be
              quietly loosened into a tolerance comparison.

        DELIBERATELY LABELLED SYNTHETIC. This data is generated, so it cannot
        witness the claim the design rests on -- that the REAL ICM-20948
        dithers. `math.nextafter` never repeats by construction, so this test
        could not fail even if the hardware were latched. The real-hardware
        evidence is `TestAgainstRealCapturedStationaryData` below; this is the
        boundary unit test standing beside it, not a substitute for it.
        (US-560's fabricated PANEL_MODES is what this labelling exists to stop.)
        """
        gate = _gate()
        base = 9.81
        for i in range(gate.invariantRunLimit * 4):
            # +/-1 ULP dither around a constant field -- numerically identical to
            # three decimals, never bit-identical.
            jittered = math.nextafter(base, math.inf if i % 2 else -math.inf)
            verdict = gate.check(_ACCEL, (0.03, -0.01, jittered))
            assert verdict.ok is True, f"false positive at sample {i + 1}"

    def test_check_oneDifferentSample_resetsTheRun(self):
        """
        Given: a long identical run broken by ONE genuinely different sample
        When: the run resumes
        Then: the gate needs a FULL fresh run to fire -- a stale verdict must
              require UNBROKEN invariance, never an accumulation of separate
              quiet spells (the never-flap rule).
        """
        gate = _gate()
        latched = (-26.7, 11.4, -40.2)
        for _ in range(gate.invariantRunLimit - 1):
            gate.check(_MAG, latched)
        assert gate.check(_MAG, (-26.8, 11.4, -40.2)).ok is True
        for _ in range(gate.invariantRunLimit - 1):
            assert gate.check(_MAG, latched).ok is True
        assert gate.check(_MAG, latched).ok is False

    def test_check_recoversAndReportsTheChange(self):
        """
        Given: a channel already gated as stale
        When: a genuinely new value arrives
        Then: it is OK again and the transition is flagged, so the reader can
              publish the recovery instead of leaving a stale marker retained
        """
        gate = _gate()
        latched = (-26.7, 11.4, -40.2)
        for _ in range(gate.invariantRunLimit):
            gate.check(_MAG, latched)
        verdict = gate.check(_MAG, (-26.8, 11.4, -40.2))
        assert verdict.ok is True
        assert verdict.changed is True
        assert verdict.reason is None

    def test_check_firstRefusalIsFlaggedChangedExactlyOnce(self):
        """
        Given: a channel that stays latched well past the limit
        When: the gate keeps inspecting it
        Then: `changed` is True on the FIRST refusal only -- the retained state
              topic is a transition marker, not a per-sample stream at 50 Hz
        """
        gate = _gate()
        latched = (-26.7, 11.4, -40.2)
        flags = [gate.check(_MAG, latched).changed for _ in range(gate.invariantRunLimit + 10)]
        assert flags.count(True) == 1
        assert flags[gate.invariantRunLimit - 1] is True

    def test_check_channelWithoutInvariancePolicy_isNeverStale(self):
        """
        Given: a channel NOT enrolled in check 2 (the TSL2591 photon counts,
               which can legitimately read a bit-exact zero in darkness)
        When: it repeats one value indefinitely
        Then: the gate stays silent -- enrolling a channel whose dither has
              never been measured would repeat the very assumption this story
              exists to delete.
        """
        gate = _gate()
        for _ in range(gate.invariantRunLimit * 3):
            assert gate.check(_LUX, 0.0).ok is True


class TestBitIdentityIsNotNumericEquality:
    """The comparison is over BIT PATTERNS -- the story's own load-bearing word."""

    def test_bitKey_negativeZeroDiffersFromPositiveZero(self):
        """
        Given: 0.0 and -0.0, which compare EQUAL under `==`
        When: their bit keys are taken
        Then: they differ -- a sign-bit flip is a real ADC transition, and an
              `==` comparison would have called that channel latched
        """
        assert bitKey((0.0, 0.0, 0.0)) != bitKey((-0.0, 0.0, 0.0))

    def test_bitKey_identicalVectorsMatch(self):
        """
        Given: two separately-constructed but identical vectors
        When: their bit keys are taken
        Then: they match (the key is a value, not an identity, comparison)
        """
        assert bitKey((1.5, -2.5, 3.5)) == bitKey((1.5, -2.5, 3.5))

    def test_bitKey_scalarAndNone_areDistinguishable(self):
        """
        Given: a scalar channel and an unreadable (None) sample
        When: their bit keys are taken
        Then: None yields no key at all, so an absent reading can never form an
              invariant run with a real one
        """
        assert bitKey(0.0) is not None
        assert bitKey(None) is None

    def test_check_noneValue_isNeverGated(self):
        """
        Given: a channel publishing None (already-honest silence, e.g. saturated
               lux or a missing temp)
        When: the gate inspects it
        Then: it passes untouched -- the gate guards the SUCCESS path only and
              must not re-classify an already-honest absence
        """
        gate = _gate()
        for _ in range(gate.invariantRunLimit * 2):
            assert gate.check(_MAG, None).ok is True


class TestRunLimitDerivation:
    """The run limit is a DWELL, not a magic count -- derived from sample rate."""

    def test_invariantRunLimit_isTheDwellAtTheChannelSampleRate(self):
        """
        Given: the IMU's 50 Hz burst rate and the default dwell
        When: the run limit is derived
        Then: it equals dwell * sampleHz -- so the gate fires after a fixed
              WALL-CLOCK stall regardless of how fast the channel is polled
        """
        gate = _gate(sampleHz=50)
        assert gate.invariantRunLimit == int(math.ceil(50 * DEFAULT_INVARIANT_DWELL_S))

    def test_invariantRunLimit_scalesWithSampleRate(self):
        """
        Given: two readers at different rates
        When: their limits are derived
        Then: the faster reader needs more samples for the same dwell -- a count
              retyped as a constant would mean two different dwells
        """
        assert _gate(sampleHz=100).invariantRunLimit == 2 * _gate(sampleHz=50).invariantRunLimit

    def test_invariantRunLimit_neverBelowTheFloor(self):
        """
        Given: a 1 Hz channel and a short dwell
        When: the limit is derived
        Then: it is at least MIN_INVARIANT_RUN -- a limit of 1 would call the
              very first sample of a channel "invariant" with nothing to compare
        """
        gate = _gate(sampleHz=1, invariantDwellSeconds=0.1)
        assert gate.invariantRunLimit >= MIN_INVARIANT_RUN

    def test_invariantRunLimit_nonPositiveSampleHz_fallsBackNotCrashes(self):
        """
        Given: a defensive non-positive rate slipping through
        When: the limit is derived
        Then: it is a usable floor, not a ZeroDivisionError in a sensor thread
        """
        assert _gate(sampleHz=0).invariantRunLimit >= MIN_INVARIANT_RUN


class TestGateVocabularyAndTopics:
    """The reason vocabulary must stay DISTINCT from the absence vocabulary."""

    def test_reasons_areDistinctFromSensorAbsent(self):
        """
        Given: the gate's two reasons
        When: compared with the existing absence reason
        Then: all three differ -- the chip IS enumerated and responding, which
              is a different fact from "not wired", and the card must be able to
              say which
        """
        from pi.sensors.imu_state_bridge import REASON_SENSOR_ABSENT

        assert len({REASON_SENSOR_MUTE, REASON_SENSOR_STALE, REASON_SENSOR_ABSENT}) == 3

    def test_channelStateTopic_isDerivedFromTheRawTopic(self):
        """
        Given: a raw bus topic
        When: its channel-state topic is derived
        Then: the raw topic is embedded, so a subscriber cannot bind to a
              hand-typed second spelling of the same channel
        """
        assert channelStateTopic(_MAG).endswith(_MAG)
        assert channelStateTopic(_MAG) != _MAG

    def test_gateOk_isNotOneOfTheRefusalReasons(self):
        """
        Given: the retained-state OK label
        When: compared to the refusal reasons
        Then: it is distinct -- a recovery marker must not read as a fault
        """
        assert GATE_OK not in (REASON_SENSOR_MUTE, REASON_SENSOR_STALE)


class TestGateIsolationBetweenChannels:
    """One channel's fault must never gate its neighbour on the same die."""

    def test_check_latchedMagDoesNotGateHealthyAccel(self):
        """
        Given: the 08-20 reality -- mag latched, accel + gyro HEALTHY
        When: both channels are fed through one gate
        Then: only the magnetometer is refused. Gating the whole IMU would
              discard the gMag/pitch/grade data Atlas confirmed is valid.
        """
        gate = _gate()
        latched = (-26.7, 11.4, -40.2)
        accelOk = True
        for i in range(gate.invariantRunLimit + 3):
            gate.check(_MAG, latched)
            jittered = math.nextafter(9.81, math.inf if i % 2 else -math.inf)
            accelOk = accelOk and gate.check(_ACCEL, (0.03, -0.01, jittered)).ok
        assert accelOk is True
        assert gate.check(_MAG, latched).ok is False

    def test_reset_clearsEveryChannelRun(self):
        """
        Given: a gate carrying an in-progress invariant run
        When: the reader resets it (sensor unplugged / re-probed)
        Then: the runs are cleared, so a pre-unplug value cannot pair with a
              post-replug one to manufacture a stale verdict across the gap
        """
        gate = _gate()
        latched = (-26.7, 11.4, -40.2)
        for _ in range(gate.invariantRunLimit - 1):
            gate.check(_MAG, latched)
        gate.reset()
        for _ in range(gate.invariantRunLimit - 1):
            assert gate.check(_MAG, latched).ok is True


class TestMagnitudePredicateFactory:
    """`magnitudeAtLeast` is the ONE spelling of check 1 -- pinned directly."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ((0.0, 0.0, 0.0), False),
            ((0.0, 0.0, 0.49), False),
            ((0.0, 0.0, 0.5), True),
            ((0.0, 0.0, -9.81), True),
            ((3.0, 4.0, 0.0), True),
            (None, False),
            ((1.0, 2.0), False),
            (("a", "b", "c"), False),
        ],
    )
    def test_magnitudeAtLeast_boundaryAndMalformed(self, value, expected):
        """
        Given: vectors on both sides of the 0.5 floor, plus malformed shapes
        When: the predicate is applied
        Then: the floor is inclusive and malformed input is implausible, never
              an exception escaping into a 50 Hz sensor thread
        """
        assert magnitudeAtLeast(0.5)(value) is expected


class TestAgainstRealCapturedStationaryData:
    """The gate run against REAL hardware, not a fixture that asserts hardware.

    Every test above feeds the gate values chosen BY the test. That proves the
    mechanism and proves nothing about the ICM-20948 -- and "a fixture that
    asserts a hardware fact makes its own suite unfalsifiable" is the finding
    that refuted US-560 earlier in this very sprint (BL-034, the fabricated
    PANEL_MODES). So this class replays 90 s of genuinely captured parked-car
    samples off chi-eclipse-01 and lets the hardware answer.

    ONE capture proves BOTH directions, which is what makes it evidence rather
    than illustration: on the same rows, through the same gate, accel and gyro
    are never refused while the magnetometer is. A gate that fired on nothing
    would pass the first half; a gate that fired on everything would pass the
    second; only a working discriminator passes both.
    """

    def test_capture_matchesItsDocumentedProvenance(self):
        """
        Given: the fixture's header states 1845 rows and the distinct-value
               counts measured over that window (accel 1821, gyro 1845, mag 1)
        When: those figures are re-derived from the data itself
        Then: they agree. This makes the fixture SELF-VERIFYING: regenerating it
              rounded, truncated or synthetic goes red HERE, loudly, instead of
              silently weakening every assertion in this class. The prose header
              and the bytes cannot drift apart unnoticed.
        """
        capture = _loadCapture()
        for topic, samples in capture.items():
            assert len(samples) == _MEASURED_ROWS, f"{topic} row count moved"
            assert len(set(samples)) == _MEASURED_DISTINCT[topic], (
                f"{topic} distinct-value count no longer matches the fixture header"
            )

    def test_check_realStationaryAccelAndGyro_neverRefused(self):
        """
        Given: 90 s of REAL parked-car accel + gyro (the vehicle genuinely still)
        When: every captured sample is replayed through the gate
        Then: not one is refused -- validationCriteria #2, and the whole reason
              bit-identity beats `variance < threshold`. A variance test would
              need a tuned constant and WOULD fire on this data: a parked car is
              *nearly* constant. Bit-identity needs no constant and holds fire.

        Note the accel channel repeats 24 values across the window (1821 distinct
        of 1845) and STILL never trips, because the check requires a CONSECUTIVE
        run. That is the margin doing its job on real data.
        """
        capture = _loadCapture()
        gate = _realDataGate()
        for i, (accel, gyro) in enumerate(zip(capture[_ACCEL], capture[_GYRO])):
            accelVerdict = gate.check(_ACCEL, accel)
            gyroVerdict = gate.check(_GYRO, gyro)
            assert accelVerdict.ok is True, (
                f"FALSE POSITIVE: accel refused as {accelVerdict.reason} at real "
                f"sample {i + 1}/{_MEASURED_ROWS} ({accel})"
            )
            assert gyroVerdict.ok is True, (
                f"FALSE POSITIVE: gyro refused as {gyroVerdict.reason} at real "
                f"sample {i + 1}/{_MEASURED_ROWS} ({gyro})"
            )

    def test_check_realLatchedMagnetometer_isRefused(self):
        """
        Given: the magnetometer rows from that SAME capture -- 1 distinct value
               across all 1845 samples (the AK09916 single-measurement latch)
        When: they are replayed through the gate
        Then: it refuses as sensor_stale, and does so within the dwell rather
              than eventually. This is the positive half: the gate catches the
              real, independently-measured fault that motivated the story.
        """
        capture = _loadCapture()
        gate = _realDataGate()
        firstRefusalAt = None
        for i, mag in enumerate(capture[_MAG]):
            if not gate.check(_MAG, mag).ok:
                firstRefusalAt = i + 1
                break
        assert firstRefusalAt == gate.invariantRunLimit, (
            "the real latched magnetometer must be refused exactly at the run "
            f"limit ({gate.invariantRunLimit}), got {firstRefusalAt}"
        )
        assert gate.check(_MAG, capture[_MAG][-1]).reason == REASON_SENSOR_STALE

    def test_check_realCapture_refusesMagWhileKeepingAccelAndGyro(self):
        """
        Given: all three channels of the real capture through ONE gate together
        When: they are replayed exactly as the reader would publish them
        Then: mag is refused and accel/gyro are not -- the discrimination that
              matters operationally, on real rows. Atlas confirmed accel + gyro
              are HEALTHY while mag is latched, so gating the whole IMU would
              throw away the valid gMag / pitch / grade data, and gating nothing
              would keep publishing a fabricated heading.
        """
        capture = _loadCapture()
        gate = _realDataGate()
        refusedMag = 0
        for accel, gyro, mag in zip(capture[_ACCEL], capture[_GYRO], capture[_MAG]):
            assert gate.check(_ACCEL, accel).ok is True
            assert gate.check(_GYRO, gyro).ok is True
            if not gate.check(_MAG, mag).ok:
                refusedMag += 1
        # Every sample past the run limit is refused; none before it.
        assert refusedMag == _MEASURED_ROWS - (gate.invariantRunLimit - 1)
