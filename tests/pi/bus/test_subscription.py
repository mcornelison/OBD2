################################################################################
# File Name: test_subscription.py
# Purpose/Description: Tests for topicMatches() + Subscription (bounded queue,
#     QoS overflow policy, observability stats) -- EDR bus slice 1, US-380.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-19    | Rex          | Initial implementation for US-380
# ================================================================================
################################################################################

"""Unit tests for ``pi.bus.bus`` topic matching + the Subscription queue."""

from pi.bus.bus import Subscription, topicMatches
from pi.bus.sample import QoS, Sample


def _sample(seq=1, topic="raw.obd.RPM", source="obd", value=1.0):
    return Sample(
        topic=topic,
        source=source,
        value=value,
        unit=None,
        tsUtc="2026-06-18T00:00:00Z",
        tsCapture=float(seq),
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def test_topicMatches_wildcardAndExact():
    """
    Given: dotted prefix-wildcard and exact patterns
    When: matched against topics
    Then: trailing '.*' is a segment-prefix match; exact matches only itself
    """
    assert topicMatches("raw.*", "raw.obd.RPM") is True
    assert topicMatches("raw.obd.*", "raw.obd.RPM") is True
    assert topicMatches("raw.obd.RPM", "raw.obd.RPM") is True
    assert topicMatches("raw.*", "derived.gear") is False
    assert topicMatches("derived.*", "derived.gear") is True
    assert topicMatches("raw.obd.RPM", "raw.obd.SPEED") is False


def test_subscription_pollReturnsInOrder():
    """
    Given: two samples offered to a roomy subscription
    When: polled
    Then: they come back FIFO, then None when empty
    """
    sub = Subscription("s", ["raw.*"], QoS.LOSSLESS, maxQueue=10)
    sub._offer(_sample(1))
    sub._offer(_sample(2))
    assert sub.poll().seq == 1
    assert sub.poll().seq == 2
    assert sub.poll() is None  # empty


def test_subscription_lossyDropsOldestWhenFull():
    """
    Given: a LOSSY subscription at maxQueue=2
    When: a third sample is offered
    Then: the oldest is dropped, the two freshest survive, droppedCount bumps
    """
    sub = Subscription("s", ["raw.*"], QoS.LOSSY, maxQueue=2)
    assert sub._offer(_sample(1)) is True
    assert sub._offer(_sample(2)) is True
    assert sub._offer(_sample(3)) is True  # full -> drop oldest (seq=1)
    assert sub.poll().seq == 2
    assert sub.poll().seq == 3
    assert sub.stats().droppedCount == 1


def test_subscription_losslessSignalsOverflow():
    """
    Given: a LOSSLESS subscription at maxQueue=1
    When: a second sample overflows
    Then: _offer returns False (so the bus can mark a gap), the queued sample
          is preserved, and droppedCount bumps -- the call never blocks
    """
    sub = Subscription("s", ["raw.*"], QoS.LOSSLESS, maxQueue=1)
    assert sub._offer(_sample(1)) is True
    assert sub._offer(_sample(2)) is False  # overflow -> bus must mark a gap
    assert sub.stats().droppedCount == 1
    assert sub.poll().seq == 1  # the queued one is preserved


def test_subscription_statsTrackHighWaterAndLastSeq():
    """
    Given: two samples offered from the same source
    When: stats() is read
    Then: depth, highWater, and lastSeqBySource reflect what was offered
    """
    sub = Subscription("s", ["raw.*"], QoS.LOSSLESS, maxQueue=10)
    sub._offer(_sample(5, source="obd"))
    sub._offer(_sample(6, source="obd"))
    st = sub.stats()
    assert st.depth == 2
    assert st.highWater == 2
    assert st.lastSeqBySource["obd"] == 6
