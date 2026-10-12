################################################################################
# File Name: test_persistence_subscriber.py
# Purpose/Description: Unit tests for PersistenceSubscriber.handleSample -- it
#     reconstructs a LoggedReading from a raw.obd.* Sample and delegates to the
#     existing ObdDataLogger.logReading path; non-raw.obd.* topics are ignored.
#     EDR slice 1, US-383.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Per-sample handler tests for the bus PersistenceSubscriber."""

from unittest.mock import MagicMock

from pi.bus.bus import SampleBus
from pi.bus.persistence_subscriber import PersistenceSubscriber
from pi.bus.sample import QoS, Sample
from pi.obdii.data.types import LoggedReading


def _s(topic="raw.obd.RPM", value=3500.0, unit="rpm", seq=1):
    return Sample(
        topic=topic,
        source="obd",
        value=value,
        unit=unit,
        tsUtc="2026-06-18T00:00:00Z",
        tsCapture=float(seq),
        driveId=27,
        dataSource="real",
        seq=seq,
    )


def test_handleSample_reconstructsLoggedReadingAndDelegatesToLogReading():
    logger = MagicMock()
    sub = SampleBus().subscribe(["raw.obd.*"], QoS.LOSSLESS, "persistence")
    ps = PersistenceSubscriber(sub, logger)

    assert ps.handleSample(_s(topic="raw.obd.RPM", value=3500.0, unit="rpm")) is True

    assert logger.logReading.call_count == 1
    reading = logger.logReading.call_args.args[0]
    assert isinstance(reading, LoggedReading)
    assert reading.parameterName == "RPM"
    assert reading.value == 3500.0
    assert reading.unit == "rpm"


def test_handleSample_derivesParameterNameFromTopicTail():
    logger = MagicMock()
    ps = PersistenceSubscriber(MagicMock(), logger)
    ps.handleSample(_s(topic="raw.obd.COOLANT_TEMP", value=92.0, unit="degC"))
    assert logger.logReading.call_args.args[0].parameterName == "COOLANT_TEMP"


def test_handleSample_ignoresNonRawObdTopics():
    logger = MagicMock()
    ps = PersistenceSubscriber(MagicMock(), logger)
    assert ps.handleSample(_s(topic="derived.gear", value=3.0)) is False
    logger.logReading.assert_not_called()
