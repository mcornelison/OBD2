################################################################################
# File Name: test_bus_integrity_gap.py
# Purpose/Description: Tests for the SampleBus honest-instrument integrity-gap
#     marker: a LOSSLESS overflow publishes event.integrity.gap rather than
#     silently dropping. EDR slice 1, US-382 (plan Task 5).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Integrity-gap marker emission on LOSSLESS subscription overflow."""

from pi.bus.bus import SampleBus
from pi.bus.sample import QoS, Sample


def _s(seq, topic="raw.obd.RPM"):
    return Sample(
        topic=topic,
        source="obd",
        value=float(seq),
        unit=None,
        tsUtc="2026-06-18T00:00:00Z",
        tsCapture=float(seq),
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def test_losslessOverflow_emitsIntegrityGapMarker():
    bus = SampleBus()
    # A tiny lossless consumer that will overflow, plus a watcher for markers.
    victim = bus.subscribe(["raw.obd.RPM"], QoS.LOSSLESS, "victim", maxQueue=1)
    watcher = bus.subscribe(["event.integrity.gap"], QoS.LOSSLESS, "watch")

    bus.publish(_s(1))  # fills victim
    bus.publish(_s(2))  # overflow -> gap marker

    marker = watcher.poll()
    assert marker is not None
    assert marker.topic == "event.integrity.gap"
    assert marker.source == "bus"
    assert marker.unit == "victim"  # which subscription lost data
    assert marker.seq == 2  # the lost sample's seq

    # The watcher must not have been handed the raw victim sample.
    assert watcher.poll() is None
    # The victim keeps the one sample it had room for (lossless preserves it).
    assert victim.poll().seq == 1


def test_noOverflow_noMarker():
    bus = SampleBus()
    bus.subscribe(["raw.obd.RPM"], QoS.LOSSLESS, "ok", maxQueue=10)
    watcher = bus.subscribe(["event.integrity.gap"], QoS.LOSSLESS, "watch")
    bus.publish(_s(1))
    assert watcher.poll() is None
