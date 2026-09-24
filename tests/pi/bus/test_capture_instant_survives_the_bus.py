################################################################################
# File Name: test_capture_instant_survives_the_bus.py
# Purpose/Description: US-809-c -- the capture instant survives links 1-2 of the
#                      three-link chain. realtime.py publishes the READING's
#                      instant (measured AFTER the round-trip, not before the
#                      query), and the persistence subscriber CARRIES it instead
#                      of manufacturing datetime.now().
# Author: Ralph (US-809-c)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author           | Description
# ================================================================================
# 2026-09-23    | Ralph (US-809-c) | Initial -- producer, subscriber, end-to-end.
# ================================================================================
################################################################################
"""The bus carries the capture instant (US-809-c).

Spec A-double-prime: a row's timestamp column MEANS event time. The bus path
destroyed it two hops before the logger, so no fix at the logger could recover
it -- which is why this lands BEFORE US-809-a rather than after.

THE MEASURED CHAIN, all three links:
  1. realtime.py  discarded ``reading.timestamp`` into ``tsUtc=utcIsoNow()``
  2. persistence_subscriber.py  manufactured ``datetime.now()``
  3. logger.py  restamps again  (US-809-a's job, deliberately NOT this story)

Links 1 and 2 are fixed here. Link 3 still restamps, so the carried value is
discarded exactly as today -- no worse than the status quo, which is what makes
-c-before-a safe and -a-before-c worse than today.
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.pi.bus.sample import Sample

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ZONE_CFG: dict[str, Any] = {"pi": {"time": {"localZone": "America/Chicago"}}}


# ==============================================================================
# Link 1 -- the producer publishes the reading's instant
# ==============================================================================

class TestTheProducerPublishesTheReadingsInstant:
    """Acceptance 1 -- realtime.py:774 carries reading.timestamp, not now()."""

    def test_publishReading_carriesTheReadingsInstant_notTheClock(self) -> None:
        """
        Given: a LoggedReading stamped with a known capture instant
        When:  it is published on the bus
        Then:  the Sample's tsUtc is THAT instant, converted, not utcIsoNow()

        The capture instant chosen is deliberately in the past, so a tsUtc
        produced by reading the clock cannot coincide with it.
        """
        from src.pi.obdii.data.types import LoggedReading

        published: list[Sample] = []
        collector = _collectorStub(published)

        captured = datetime(2026, 9, 23, 12, 0, 0)
        reading = LoggedReading(
            parameterName="RPM", value=3500.0, timestamp=captured, unit="rpm"
        )

        collector._publishReading(reading)

        assert len(published) == 1
        # America/Chicago on 2026-09-23 is CDT (-5), so noon local is 17:00Z.
        assert published[0].tsUtc == "2026-09-23T17:00:00Z"

    def test_pollCycle_stampsAfterTheRoundTrip_notBeforeTheQuery(self) -> None:
        """
        Given: a query whose round-trip takes measurable time
        When:  one poll cycle runs
        Then:  the reading's stamp is LATER than a marker taken before the
               query returned

        realtime.py read the clock ABOVE the Bluetooth round-trip, so the
        stored 'read time' was when we ASKED -- early by the round-trip. This
        is the difference between when we asked and when the ECU answered.
        """
        from src.pi.obdii.data.realtime import RealtimeDataLogger

        markers: dict[str, datetime] = {}

        def slowQuery(paramName: str) -> Any:
            from src.pi.obdii.data.types import LoggedReading

            # The marker is taken INSIDE the round-trip, just before it returns.
            markers["beforeReturn"] = datetime.now()
            return LoggedReading(
                parameterName=paramName,
                value=1234.0,
                timestamp=datetime(1970, 1, 1),  # must be overwritten
                unit="rpm",
            )

        logger = _pollCycleStub(RealtimeDataLogger, slowQuery)
        logger._pollCycle()

        assert logger.loggedReadings, "the cycle logged nothing"
        stamped = logger.loggedReadings[0].timestamp
        assert stamped >= markers["beforeReturn"], (
            "the reading is stamped with when we ASKED, not when the ECU answered"
        )


class TestTheCorrectProducersAreLeftAlone:
    """Acceptance 1 -- the three sensor_reader sites publish AT the read."""

    def test_sensorReader_stillStampsAtTheMomentOfTheRead(self) -> None:
        """
        Given: src/pi/sensors/sensor_reader.py
        When:  its Sample( constructions are read
        Then:  each still takes its own clock reading at publish time

        These three are CORRECT: they publish at the moment of the read, so
        the clock reading IS the capture instant. A change here fails the
        story -- the defect was never 'reads the clock', it was 'reads the
        clock somewhere other than where the reading happened'.
        """
        source = (_REPO_ROOT / "src/pi/sensors/sensor_reader.py").read_text(
            encoding="utf-8"
        )

        assert source.count("tsUtc=utcIsoNow()") == 3, (
            "the three correct producers must keep stamping at the read"
        )


# ==============================================================================
# Link 2 -- the subscriber carries the value instead of manufacturing one
# ==============================================================================

class TestTheSubscriberCarriesTheValue:
    """Acceptance 2 -- no manufactured instant in the subscriber."""

    def test_noDatetimeNowSuppliesAReadingsTimestamp(self) -> None:
        """
        Given: src/pi/bus/persistence_subscriber.py
        When:  its AST is walked for a LoggedReading( construction
        Then:  no timestamp= argument is a datetime.now() call

        Stated as the story states it: a manufactured instant is a
        manufactured reading. The AST is used rather than a grep so the
        confession comment ('logReading restamps utcIsoNow() anyway') can be
        deleted without the guard silently passing on its absence.
        """
        source = (_REPO_ROOT / "src/pi/bus/persistence_subscriber.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)

        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", None) != "LoggedReading":
                continue
            for kw in node.keywords:
                if kw.arg != "timestamp":
                    continue
                if _isDatetimeNow(kw.value):
                    offenders.append(node.lineno)

        assert not offenders, (
            f"persistence_subscriber.py manufactures a reading instant at "
            f"line(s) {offenders}"
        )

    def test_subscriber_reconstructsTheReadingWithTheSamplesInstant(self) -> None:
        """
        Given: a Sample carrying a known capture instant
        When:  the subscriber persists it
        Then:  the LoggedReading it builds carries THAT instant
        """
        from src.pi.bus.persistence_subscriber import PersistenceSubscriber

        seen: list[Any] = []

        class _Logger:
            def logReading(self, reading: Any, capturedDriveId: Any = None) -> None:
                seen.append(reading)

        subscriber = PersistenceSubscriber(_NullSubscription(), _Logger())
        subscriber.handleSample(
            Sample(
                topic="raw.obd.RPM",
                source="obd",
                value=3500.0,
                unit="rpm",
                tsUtc="2026-09-23T17:00:00Z",
                tsCapture=123.0,
                driveId=7,
                dataSource="real",
                seq=1,
            )
        )

        assert len(seen) == 1
        # TZ-AWARE: the wire value is canonical UTC and says so.
        assert seen[0].timestamp == datetime(2026, 9, 23, 17, 0, 0, tzinfo=UTC)


# ==============================================================================
# Acceptance 3 -- tsUtc's definition is stated, not inferred
# ==============================================================================

class TestTsUtcDefinitionIsStated:
    def test_sampleDocstring_saysTsUtcHoldsTheEventInstant(self) -> None:
        """
        Given: src/pi/bus/sample.py
        When:  the Sample docstring is read
        Then:  tsUtc is documented as the EVENT instant, citing the spec

        sample.py (2026-06-19) is OLDER than spec A-double-prime (2026-09-21),
        which already determines this. The field needed its definition stated,
        not a sibling added.
        """
        source = (_REPO_ROOT / "src/pi/bus/sample.py").read_text(encoding="utf-8")

        tsUtcDoc = re.search(r"tsUtc:.*?(?=\n\s+tsCapture:)", source, re.S)
        assert tsUtcDoc, "the tsUtc docstring entry was not found"

        text = tsUtcDoc.group(0)
        assert "event" in text.lower(), "tsUtc does not say it is the event instant"

    def test_noNewFieldWasAddedToSample(self) -> None:
        """
        Given: the Sample dataclass
        When:  its fields are listed
        Then:  they are exactly the nine that existed before

        The design pass found the slot already exists. Bumping a wire contract
        to add a sibling was explicitly out of scope -- if a new field seemed
        necessary the instruction was to STOP AND REPORT.
        """
        assert [f for f in Sample.__dataclass_fields__] == [
            "topic", "source", "value", "unit", "tsUtc",
            "tsCapture", "driveId", "dataSource", "seq",
        ]


# ==============================================================================
# Acceptance 4 -- end to end, the test US-809-a cannot write
# ==============================================================================

class TestEndToEnd:
    def test_publishedThenPersisted_arrivesWithTheProducersInstant(self) -> None:
        """
        Given: a reading published by the producer and drained by the subscriber
        When:  it arrives at the logger boundary
        Then:  it carries the instant the PRODUCER measured

        US-809-a cannot write this: its test constructs a LoggedReading
        directly and never touches links 1-2, so a green -a is compatible with
        the capture time still being lost in production.
        """
        from src.pi.bus.persistence_subscriber import PersistenceSubscriber
        from src.pi.obdii.data.types import LoggedReading

        published: list[Sample] = []
        collector = _collectorStub(published)

        captured = datetime(2026, 9, 23, 12, 0, 0)
        collector._publishReading(
            LoggedReading(
                parameterName="RPM", value=3500.0, timestamp=captured, unit="rpm"
            )
        )

        landed: list[Any] = []

        class _Logger:
            def logReading(self, reading: Any, capturedDriveId: Any = None) -> None:
                landed.append(reading)

        PersistenceSubscriber(_NullSubscription(), _Logger()).handleSample(
            published[0]
        )

        assert len(landed) == 1
        # The producer measured noon CDT; that is the instant that arrives.
        assert landed[0].timestamp == datetime(2026, 9, 23, 17, 0, 0, tzinfo=UTC)


# ==============================================================================
# helpers
# ==============================================================================

class _NullSubscription:
    """A Subscription stand-in: handleSample never touches the drain thread."""


def _isDatetimeNow(node: ast.AST) -> bool:
    """True for ``datetime.now()`` / ``datetime.datetime.now()`` calls."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr == "now"


def _collectorStub(published: list[Sample]) -> Any:
    """A RealtimeDataLogger with just enough wiring to publish one sample."""
    from src.pi.obdii.data.realtime import RealtimeDataLogger

    collector = RealtimeDataLogger.__new__(RealtimeDataLogger)
    collector.config = _ZONE_CFG
    collector._seq = 0
    collector._producerSource = "obd"
    collector._dataSource = "real"

    class _Bus:
        def publish(self, sample: Sample) -> None:
            published.append(sample)

    collector._bus = _Bus()

    class _Stats:
        totalLogged = 0

    collector._stats = _Stats()
    collector._markRowWritten = lambda: None
    return collector


def _pollCycleStub(cls: type, query: Any) -> Any:
    """A RealtimeDataLogger wired for exactly one _pollCycle pass."""
    import threading

    logger = cls.__new__(cls)
    logger.config = _ZONE_CFG
    logger._parameters = ["RPM"]
    logger._stopEvent = threading.Event()
    logger._queryParameterSafe = query
    logger.loggedReadings = []
    logger._logReadingSafe = logger.loggedReadings.append
    logger._onReading = None
    logger._onSuccessfulQuery = lambda: None

    class _Stats:
        totalReadings = 0
        parametersLogged: dict[str, int] = {}

    logger._stats = _Stats()
    return logger
