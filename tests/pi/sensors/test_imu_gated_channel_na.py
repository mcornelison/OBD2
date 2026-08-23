################################################################################
# File Name: test_imu_gated_channel_na.py
# Purpose/Description: US-564 -- "a derived field goes typed-NA WITH ITS INPUT".
#   Pins the consumer half of the plausibility gate: when the reader gates a raw
#   channel, every states/imu field DERIVED from that channel publishes typed
#   NULL carrying the gate's own reason (sensor_mute / sensor_stale), never a
#   number computed from a value that has been proven not to be a measurement.
#
#   The concrete defect: the F-127 Home face rendered `236.9` to a tenth of a
#   degree off a magnetometer that had served one bit-identical value since boot
#   (drive 40: 29,148 samples, 1 distinct value).
#
#   Both directions are pinned everywhere. "headingDeg is null when mag is
#   gated" is the easy half; "gLat/gLon/gMag are STILL REAL while mag is gated"
#   is the half that matters, because Atlas measured accel + gyro as HEALTHY and
#   a guard that greys the whole instrument costs more than the fault.
# Author: Rex (US-564)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-564) | Initial -- gated-channel -> derived-field NA,
#               |              | held-value drop, recovery, absence precedence.
# ================================================================================
################################################################################

"""Tests for US-564 gated-channel propagation into the states/imu view."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pi.bus.sample import Sample
from pi.sensors.imu_state_bridge import (
    CHANNEL_STATE_ACCEL,
    CHANNEL_STATE_GYRO,
    CHANNEL_STATE_MAG,
    IMU_STATE_FILENAME,
    REASON_NO_MAG,
    REASON_SENSOR_ABSENT,
    STANDARD_GRAVITY_MS2,
    STATE_IMU_PRESENCE,
    TOPIC_IMU_ACCEL,
    TOPIC_IMU_MAG,
    ImuStateBridge,
    buildImuState,
)
from pi.sensors.plausibility_gate import (
    GATE_OK,
    REASON_SENSOR_MUTE,
    REASON_SENSOR_STALE,
)

G = STANDARD_GRAVITY_MS2


def _sample(topic: str, value, *, unit: str = "", capture: float = 0.0) -> Sample:
    """A minimal bus Sample for direct handleSample() calls."""
    return Sample(
        topic=topic,
        source="imu",
        value=value,
        unit=unit,
        tsUtc="2026-08-21T12:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=1,
    )


def _gateMarker(topic: str, reason: str | None) -> Sample:
    """The retained per-channel gate STATE the reader publishes on a transition."""
    return _sample(topic, 0.0 if reason else 1.0, unit=reason or GATE_OK)


def _bridge(tmp_path: Path) -> ImuStateBridge:
    """A bridge writing into a temp states dir, driven directly (no thread)."""
    return ImuStateBridge(None, str(tmp_path), stateHz=1000)


def _readState(tmp_path: Path) -> dict:
    return json.loads((tmp_path / IMU_STATE_FILENAME).read_text(encoding="utf-8"))


def _feedLevelBurst(bridge: ImuStateBridge, capture: float = 1.0) -> None:
    """One accel burst from a level, stationary board (drives the write)."""
    bridge.handleSample(_sample(TOPIC_IMU_ACCEL, (0.0, 0.0, G), capture=capture))


class TestMagGateTakesHeadingWithIt:
    """The magnetometer case -- the defect that motivated the story."""

    def test_magGated_headingIsNullWithTheGateReason(self, tmp_path):
        """
        Given: the reader reports raw.imu.mag gated as sensor_stale
        When: the next burst is published
        Then: headingDeg is null and its reason is the GATE's reason -- not the
              generic no_mag_reading, which would say "the pairing window
              lapsed" when the truth is "this chip has not measured since boot"
        """
        bridge = _bridge(tmp_path)
        bridge.handleSample(_sample(TOPIC_IMU_MAG, (-26.7, 11.4, -40.2), capture=1.0))
        bridge.handleSample(_gateMarker(CHANNEL_STATE_MAG, REASON_SENSOR_STALE))
        _feedLevelBurst(bridge)

        state = _readState(tmp_path)
        assert state["headingDeg"] is None
        assert state["reasons"]["headingDeg"] == REASON_SENSOR_STALE

    def test_magGated_gForceFieldsStayReal(self, tmp_path):
        """
        Given: mag gated while accel is healthy (the 08-20 measurement exactly)
        When: the state is published
        Then: gLat/gLon/gMag are still real numbers and the instrument is still
              available. Greying the whole card would discard valid data and
              would make the guard more expensive than the defect.
        """
        bridge = _bridge(tmp_path)
        bridge.handleSample(_gateMarker(CHANNEL_STATE_MAG, REASON_SENSOR_STALE))
        _feedLevelBurst(bridge)

        state = _readState(tmp_path)
        assert state["available"] is True
        assert state["gMag"] is not None
        assert state["gLat"] is not None
        assert state["gLon"] is not None

    def test_magGated_dropsTheHeldReadingImmediately(self, tmp_path):
        """
        Given: a fresh magnetometer reading already held for pairing
        When: the gate marker arrives IN THE SAME pairing window
        Then: no heading is published. Without dropping the held value the
              pairing window would carry one last bearing -- fabricated, and
              wearing a fresh timestamp, which is the worst possible shape.
        """
        bridge = _bridge(tmp_path)
        bridge.handleSample(_sample(TOPIC_IMU_MAG, (20.0, 0.0, -40.0), capture=1.0))
        bridge.handleSample(_gateMarker(CHANNEL_STATE_MAG, REASON_SENSOR_STALE))
        _feedLevelBurst(bridge, capture=1.001)

        assert _readState(tmp_path)["headingDeg"] is None

    def test_magNotGated_headingStillPublishes(self, tmp_path):
        """
        Given: a healthy magnetometer and no gate marker
        When: a paired burst arrives
        Then: a heading IS published -- the control case. Without it every
              assertion above would also pass on a bridge that never produces
              a heading at all.
        """
        bridge = _bridge(tmp_path)
        bridge.handleSample(_sample(TOPIC_IMU_MAG, (20.0, 0.0, -40.0), capture=1.0))
        _feedLevelBurst(bridge, capture=1.001)

        assert _readState(tmp_path)["headingDeg"] is not None

    def test_magGateCleared_headingRecovers(self, tmp_path):
        """
        Given: a gated magnetometer that the reader then reports OK (US-565)
        When: a fresh reading and burst arrive
        Then: the heading publishes again -- the NA is a live verdict, not a
              one-way latch that would outlive the fix
        """
        bridge = _bridge(tmp_path)
        bridge.handleSample(_gateMarker(CHANNEL_STATE_MAG, REASON_SENSOR_STALE))
        bridge.handleSample(_gateMarker(CHANNEL_STATE_MAG, None))
        bridge.handleSample(_sample(TOPIC_IMU_MAG, (20.0, 0.0, -40.0), capture=1.0))
        _feedLevelBurst(bridge, capture=1.001)

        assert _readState(tmp_path)["headingDeg"] is not None


class TestGyroGateTakesPitchAndGrade:
    """pitchDeg/gradePct are read off the gyro-fused estimate (US-521)."""

    def test_gyroGated_pitchAndGradeAreNullWithTheReason(self, tmp_path):
        """
        Given: the gyro channel gated
        When: the state is published
        Then: BOTH pitchDeg and gradePct carry the gate reason. gradePct is
              derived from pitchDeg which is derived from the gyro -- the rule
              follows the chain, it does not stop at the first hop.
        """
        bridge = _bridge(tmp_path)
        bridge.handleSample(_gateMarker(CHANNEL_STATE_GYRO, REASON_SENSOR_STALE))
        _feedLevelBurst(bridge)

        state = _readState(tmp_path)
        assert state["pitchDeg"] is None
        assert state["gradePct"] is None
        assert state["reasons"]["pitchDeg"] == REASON_SENSOR_STALE
        assert state["reasons"]["gradePct"] == REASON_SENSOR_STALE

    def test_gyroGated_headingIsUntouched(self, tmp_path):
        """
        Given: the gyro gated while the magnetometer is healthy
        When: a paired burst arrives
        Then: the heading still publishes -- gating must follow the DERIVATION
              graph, not blank every field on the same chip
        """
        bridge = _bridge(tmp_path)
        bridge.handleSample(_gateMarker(CHANNEL_STATE_GYRO, REASON_SENSOR_STALE))
        bridge.handleSample(_sample(TOPIC_IMU_MAG, (20.0, 0.0, -40.0), capture=1.0))
        _feedLevelBurst(bridge, capture=1.001)

        assert _readState(tmp_path)["headingDeg"] is not None


class TestAccelGateBlanksTheInstrument:
    """Accel is the gravity reference under every derived field."""

    def test_accelGated_writesUnavailableImmediately(self, tmp_path):
        """
        Given: a healthy card, then the accel channel gated as sensor_mute
        When: the marker arrives
        Then: the state file is rewritten AT ONCE as unavailable with that
              reason -- it does not wait for the next display-cadence window,
              because the alternative is the last live g reading sitting on the
              card looking current while nothing behind it is reading
        """
        bridge = _bridge(tmp_path)
        _feedLevelBurst(bridge)
        assert _readState(tmp_path)["available"] is True

        bridge.handleSample(_gateMarker(CHANNEL_STATE_ACCEL, REASON_SENSOR_MUTE))

        state = _readState(tmp_path)
        assert state["available"] is False
        assert state["gMag"] is None
        assert state["reasons"]["gMag"] == REASON_SENSOR_MUTE

    def test_accelGated_dropsTheGravityEstimate(self, tmp_path):
        """
        Given: a converged gravity estimate
        When: accel is gated
        Then: the estimate is discarded, so the first burst after a recovery
              re-seeds from a real reading instead of resuming a filter whose
              memory is made of samples the gate has disowned
        """
        bridge = _bridge(tmp_path)
        _feedLevelBurst(bridge)
        bridge.handleSample(_gateMarker(CHANNEL_STATE_ACCEL, REASON_SENSOR_MUTE))

        assert bridge._gravity is None


class TestAbsencePrecedence:
    """`sensor_absent` is the more fundamental fact and must out-rank a gate."""

    def test_presenceAbsent_clearsGatedChannels(self, tmp_path):
        """
        Given: a channel gated stale, then the sensor unplugged entirely
        When: the sensor is replugged and reads normally
        Then: no stale gate verdict survives the unplug -- otherwise a marker
              from before the gap would keep greying a channel that is now fine
        """
        bridge = _bridge(tmp_path)
        bridge.handleSample(_gateMarker(CHANNEL_STATE_MAG, REASON_SENSOR_STALE))
        bridge.handleSample(_sample(STATE_IMU_PRESENCE, 0.0, unit="absent"))

        bridge.handleSample(_sample(TOPIC_IMU_MAG, (20.0, 0.0, -40.0), capture=1.0))
        _feedLevelBurst(bridge, capture=1.001)

        assert _readState(tmp_path)["headingDeg"] is not None

    def test_presenceAbsent_stillReportsSensorAbsent(self, tmp_path):
        """
        Given: an unplug after a gate marker
        When: the unavailable state is written
        Then: the reason is sensor_absent, not the gate reason -- "not wired"
              and "wired but not measuring" are different facts and the more
              fundamental one wins
        """
        bridge = _bridge(tmp_path)
        bridge.handleSample(_gateMarker(CHANNEL_STATE_MAG, REASON_SENSOR_STALE))
        bridge.handleSample(_sample(STATE_IMU_PRESENCE, 0.0, unit="absent"))

        assert _readState(tmp_path)["reasons"]["gMag"] == REASON_SENSOR_ABSENT


class TestSubscriptionAndTopicWiring:
    """A marker nobody subscribes to is a marker nobody receives."""

    def test_handleSample_claimsTheGateStateTopics(self, tmp_path):
        """
        Given: each of the three gate-state topics
        When: handleSample sees them
        Then: it returns True (claimed). A False here would mean the bridge
              silently ignored the marker while every unit test that calls
              handleSample directly still passed.
        """
        bridge = _bridge(tmp_path)
        for topic in (CHANNEL_STATE_ACCEL, CHANNEL_STATE_GYRO, CHANNEL_STATE_MAG):
            assert bridge.handleSample(_gateMarker(topic, REASON_SENSOR_STALE)) is True

    def test_factory_subscribesToTheGateStateTopics(self):
        """
        Given: the config factory building a live bridge
        When: its subscription is inspected
        Then: all three gate topics are in it. The bridge could handle every
              marker perfectly and still never see one -- this is the seam that
              would fail silently.
        """
        captured: dict = {}

        class _Bus:
            def subscribe(self, topics, qos, name):
                captured["topics"] = list(topics)
                return None

        config = {
            "pi": {
                "bus": {"enabled": True},
                "sensors": {"imu": {"enabled": True}},
            }
        }
        from pi.sensors.imu_state_bridge import createImuStateBridgeFromConfig

        createImuStateBridgeFromConfig(config, _Bus())

        assert CHANNEL_STATE_ACCEL in captured["topics"]
        assert CHANNEL_STATE_GYRO in captured["topics"]
        assert CHANNEL_STATE_MAG in captured["topics"]

    def test_gateStateTopics_embedTheirRawTopic(self):
        """
        Given: the derived gate-state topic names
        When: compared with the raw topics
        Then: each embeds its raw topic, so producer and consumer cannot bind to
              two different spellings of the same channel
        """
        assert CHANNEL_STATE_MAG.endswith(TOPIC_IMU_MAG)
        assert CHANNEL_STATE_ACCEL.endswith(TOPIC_IMU_ACCEL)


class TestFieldReasonsAreAppliedLast:
    """A gated source must beat a value the arithmetic was still able to produce."""

    def test_buildImuState_fieldReasonOverridesAComputedHeading(self):
        """
        Given: a perfectly derivable heading AND a gate reason for that field
        When: the state is assembled
        Then: the gate wins. The maths working is not evidence that the input
              was real -- that is the entire lesson of the latched magnetometer.
        """
        state = buildImuState(
            tsUtc="2026-08-21T12:00:00Z",
            gravity=(0.0, 0.0, G),
            linear=(0.0, 0.0, 0.0),
            mag=(20.0, 0.0, -40.0),
            fieldReasons={"headingDeg": REASON_SENSOR_STALE},
        )

        assert state["headingDeg"] is None
        assert state["reasons"]["headingDeg"] == REASON_SENSOR_STALE

    def test_buildImuState_fieldReasonOverridesEvenTheBlanketPath(self):
        """
        Given: an already-unavailable instrument plus a per-field gate reason
        When: the state is assembled
        Then: the field carries the SPECIFIC gate reason rather than the blanket
              one -- the more precise diagnosis is not lost to the coarser one
        """
        state = buildImuState(
            tsUtc="2026-08-21T12:00:00Z",
            unavailableReason=REASON_SENSOR_ABSENT,
            fieldReasons={"headingDeg": REASON_SENSOR_MUTE},
        )

        assert state["reasons"]["headingDeg"] == REASON_SENSOR_MUTE
        assert state["reasons"]["gMag"] == REASON_SENSOR_ABSENT

    def test_buildImuState_unknownFieldNameIsIgnored(self):
        """
        Given: a caller passing a field name that is not in the contract
        When: the state is assembled
        Then: no crash and no new key -- this runs inside a sensor thread, and a
              typo must not take the instrument down or invent a payload field
        """
        state = buildImuState(
            tsUtc="2026-08-21T12:00:00Z",
            gravity=(0.0, 0.0, G),
            fieldReasons={"headingDeGREES": REASON_SENSOR_STALE},
        )

        assert "headingDeGREES" not in state
        assert "headingDeGREES" not in state["reasons"]

    def test_buildImuState_noFieldReasons_isUnchanged(self):
        """
        Given: no gate reasons at all (every pre-US-564 caller)
        When: the state is assembled
        Then: the payload is identical to the ungated call -- the new parameter
              is inert unless something is actually gated
        """
        common = {
            "tsUtc": "2026-08-21T12:00:00Z",
            "gravity": (0.0, 0.0, G),
            "linear": (0.1, 0.0, 0.0),
            "mag": (20.0, 0.0, -40.0),
        }

        assert buildImuState(**common) == buildImuState(**common, fieldReasons={})
        assert buildImuState(**common) == buildImuState(**common, fieldReasons=None)


class TestDerivedFieldMapIsPinned:
    """Which field dies with which channel is a CONTRACT, not an implementation."""

    @pytest.mark.parametrize(
        "stateTopic,expectedFields",
        [
            (CHANNEL_STATE_MAG, {"headingDeg"}),
            (CHANNEL_STATE_GYRO, {"pitchDeg", "gradePct"}),
        ],
    )
    def test_gatedChannel_nullsExactlyItsOwnDerivedFields(
        self, tmp_path, stateTopic, expectedFields
    ):
        """
        Given: one channel gated
        When: the published state is inspected
        Then: exactly its own derived fields are null-with-that-reason. Pinning
              the EXACT set both ways catches an over-broad gate (blanking a
              field it does not feed) and an under-broad one in one assertion.
        """
        bridge = _bridge(tmp_path)
        bridge.handleSample(_gateMarker(stateTopic, REASON_SENSOR_STALE))
        bridge.handleSample(_sample(TOPIC_IMU_MAG, (20.0, 0.0, -40.0), capture=1.0))
        _feedLevelBurst(bridge, capture=1.001)

        reasons = _readState(tmp_path)["reasons"]
        gated = {f for f, r in reasons.items() if r == REASON_SENSOR_STALE}
        assert gated == expectedFields

    def test_noGate_headingUsesTheOriginalNoMagReason(self, tmp_path):
        """
        Given: NO gate, but a magnetometer reading too old to pair
        When: the state is published
        Then: the reason is still the pre-existing no_mag_reading. US-564 adds a
              vocabulary, it does not replace the freshness one -- a lapsed
              pairing window and a dead chip stay distinguishable.
        """
        bridge = _bridge(tmp_path)
        bridge.handleSample(_sample(TOPIC_IMU_MAG, (20.0, 0.0, -40.0), capture=1.0))
        _feedLevelBurst(bridge, capture=99.0)

        assert _readState(tmp_path)["reasons"]["headingDeg"] == REASON_NO_MAG
