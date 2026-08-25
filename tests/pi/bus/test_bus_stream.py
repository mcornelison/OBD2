################################################################################
# File Name: test_bus_stream.py
# Purpose/Description: SampleBus core tests (EDR slice 1, US-381): subscribe()
#     returns a usable Subscription; publish() fans out to matching subscribers
#     only; STREAM topics have no history (late subscriber misses prior sample);
#     publish() never blocks on an undrained subscriber. See $FLEET_SHARE/knowledge/superpowers/
#     plans/2026-06-18-edr-bus-slice1-dedicated-reader.md Task 3.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-19    | Rex          | Initial implementation for US-381 (SampleBus core)
# ================================================================================
################################################################################

"""SampleBus subscribe/publish fan-out + STREAM (no-history) + never-block tests."""

from pi.bus.bus import SampleBus
from pi.bus.sample import QoS, Sample


def _sample(topic="raw.obd.RPM", seq=1, value=1.0, source="obd"):
    return Sample(topic=topic, source=source, value=value, unit=None,
                  tsUtc="2026-06-18T00:00:00Z", tsCapture=float(seq),
                  driveId=None, dataSource="real", seq=seq)


def test_publish_fansOutToMatchingSubscribersOnly():
    bus = SampleBus()
    raw = bus.subscribe(["raw.*"], QoS.LOSSLESS, "raw")
    obd = bus.subscribe(["raw.obd.RPM"], QoS.LOSSLESS, "rpm")
    derived = bus.subscribe(["derived.*"], QoS.LOSSY, "derived")

    bus.publish(_sample(topic="raw.obd.RPM", seq=1))

    assert raw.poll().seq == 1
    assert obd.poll().seq == 1
    assert derived.poll() is None  # no match


def test_publish_deliversAfterSubscribeOnly_streamHasNoHistory():
    bus = SampleBus()
    bus.publish(_sample(seq=1))                 # before any subscriber
    sub = bus.subscribe(["raw.*"], QoS.LOSSLESS, "late")
    bus.publish(_sample(seq=2))
    assert sub.poll().seq == 2                  # only the post-subscribe sample
    assert sub.poll() is None


def test_subscribe_returnsUsableSubscription():
    bus = SampleBus()
    sub = bus.subscribe(["raw.obd.*"], QoS.LOSSY, "x")
    assert sub.qos == QoS.LOSSY
    assert sub.topics == ["raw.obd.*"]


def test_publish_doesNotBlockWhenSubscriberNeverDrains():
    # The load-bearing invariant: a consumer that never drains cannot stall the
    # producer. publish() uses only non-blocking enqueue, so this must return.
    bus = SampleBus()
    bus.subscribe(["raw.*"], QoS.LOSSY, "wedged", maxQueue=2)
    bus.subscribe(["raw.*"], QoS.LOSSLESS, "wedgedLossless", maxQueue=2)
    for i in range(1000):
        bus.publish(_sample(seq=i))   # far exceeds both queues; must not hang
    # Reaching here proves publish never blocked on a full/undrained queue.
