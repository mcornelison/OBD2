################################################################################
# File Name: test_bus_state.py
# Purpose/Description: Tests for SampleBus STATE retained topics (last-value-cache
#     + replay-on-subscribe). EDR slice 1, US-382 (plan Task 4).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""STATE retained-topic behavior for the SampleBus."""

from pi.bus.bus import SampleBus
from pi.bus.sample import QoS, Sample


def _state(topic, value, seq=1):
    return Sample(
        topic=topic,
        source="config",
        value=value,
        unit=None,
        tsUtc="2026-06-18T00:00:00Z",
        tsCapture=float(seq),
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def test_state_lateSubscriberGetsRetainedValue():
    bus = SampleBus()
    bus.publish(_state("state.config.serverHost", 1.0), retain=True)
    sub = bus.subscribe(["state.config.*"], QoS.LOSSLESS, "late")
    got = sub.poll()
    assert got is not None and got.topic == "state.config.serverHost"


def test_state_retainsLatestOnly():
    bus = SampleBus()
    bus.publish(_state("state.x", 1.0, seq=1), retain=True)
    bus.publish(_state("state.x", 2.0, seq=2), retain=True)
    sub = bus.subscribe(["state.*"], QoS.LOSSLESS, "s")
    got = sub.poll()
    assert got.seq == 2  # only the latest is replayed
    assert sub.poll() is None


def test_stream_isNotRetained():
    bus = SampleBus()
    bus.publish(_state("raw.obd.RPM", 1.0), retain=False)
    sub = bus.subscribe(["raw.*"], QoS.LOSSLESS, "s")
    assert sub.poll() is None  # streams have no replay
