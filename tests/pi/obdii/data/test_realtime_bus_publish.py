################################################################################
# File Name: test_realtime_bus_publish.py
# Purpose/Description: Unit tests for the RealtimeDataLogger publish seam -- when
#     a SampleBus is injected, _logReadingSafe publishes a raw.obd.<param>
#     Sample (per-producer monotonic seq) instead of writing the DB; with no bus
#     the inline write path is unchanged. EDR slice 1, US-384.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Producer-side bus publish-seam tests for RealtimeDataLogger."""

from datetime import datetime
from unittest.mock import MagicMock

from pi.obdii.data.realtime import RealtimeDataLogger
from pi.obdii.data.types import LoggedReading


def _logger(bus):
    """Build a RealtimeDataLogger exercising only the publish branch.

    Real wiring is covered by the lifecycle tests (US-385); here we construct
    via ``__new__`` and set only the attributes ``_publishReading`` touches so
    the test is independent of the full constructor.
    """
    rdl = RealtimeDataLogger.__new__(RealtimeDataLogger)
    rdl._bus = bus
    rdl._producerSource = "obd"
    rdl._seq = 0
    rdl._dataSource = "real"
    rdl._stats = MagicMock()
    rdl._markRowWritten = MagicMock()
    return rdl


def test_logReadingSafe_publishesSampleWhenBusPresent():
    bus = MagicMock()
    rdl = _logger(bus)
    reading = LoggedReading("RPM", 3500.0, datetime.now(), "rpm", None)

    assert rdl._logReadingSafe(reading) is True

    assert bus.publish.call_count == 1
    sample = bus.publish.call_args.args[0]
    assert sample.topic == "raw.obd.RPM"
    assert sample.value == 3500.0
    assert sample.unit == "rpm"
    assert sample.source == "obd"
    assert sample.seq == 1  # per-producer monotonic


def test_publishReading_incrementsSeqPerCall():
    bus = MagicMock()
    rdl = _logger(bus)
    rdl._logReadingSafe(LoggedReading("RPM", 1.0, datetime.now(), "rpm", None))
    rdl._logReadingSafe(LoggedReading("SPEED", 2.0, datetime.now(), "km/h", None))
    assert bus.publish.call_args_list[0].args[0].seq == 1
    assert bus.publish.call_args_list[1].args[0].seq == 2
