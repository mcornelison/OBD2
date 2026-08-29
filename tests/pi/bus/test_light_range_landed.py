################################################################################
# File Name: test_light_range_landed.py
# Purpose/Description: ARCH-009 -- land the gain + integration time a light
#   reading was taken under. Rule A (CIO): if we observe, read, or have access
#   to any data point, we land it, store it, timestamp it.
# Author: Atlas (Architect)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-08-29    | Atlas   | ARCH-009: land the reading's range context
# ================================================================================
################################################################################

"""Acceptance tests for landing the light reading's range context.

**The gap.** `edr_light_sample` has carried `gain` and `integration_ms` columns
since it was designed -- the schema even documents their intent:

    gain           TEXT,     -- 'low'|'med'|'high'|'max' -- the reading's gain context
    integration_ms INTEGER,  -- integration time at read

They were **populated in 0 of 235,795 rows**. The columns were designed to the
rule and the writer was never wired to them.

**Why it is not cosmetic.** The driver MUST set gain and integration time to read
the TSL2591 at all, so the values are in hand at read time -- observed, accessible,
discarded. And they are the two values that distinguish *"the sensor was
mis-ranged"* from *"the IR-subtraction limit was reached"* for the negative-lux
defect (ARCH-010). That diagnosis is currently impossible because the answer was
thrown away.

**Design note on why this is a third field on the SAME burst.** Gain and
integration are published in the same `_publishBurst` as lux and raw, so either
all three arrive or none do. A separate publish would have made a diagnostic
field able to delay or block a capture row -- and an instrument must never be
able to take down the thing it measures.
"""

import pytest

from src.pi.bus.edr_persistence_subscriber import _gainLabel


class TestGainLabelMapping:
    """The schema stores a LABEL, the chip reports a register code."""

    @pytest.mark.parametrize("code,label", [
        (0x00, "low"), (0x10, "med"), (0x20, "high"), (0x30, "max"),
    ])
    def test_knownGainCodesMapToTheSchemaLabels(self, code, label):
        assert _gainLabel(code) == label

    def test_anUnknownCodeIsNullNotAGuess(self):
        """A code we do not recognise is not evidence of a gain setting.
        Inventing 'low' for it would be a fabricated context -- the exact
        defect class this story exists to close."""
        assert _gainLabel(0x99) is None

    def test_aMissingCodeIsNull(self):
        assert _gainLabel(None) is None


class TestTheRowCarriesTheContext:
    def test_writeLightRowPersistsGainAndIntegration(self, tmp_path):
        from src.pi.bus.edr_persistence_subscriber import EdrPersistenceSubscriber
        rows = []

        class _Conn:
            def execute(self, sql, params): rows.append((sql, params))
            def __enter__(self): return self
            def __exit__(self, *a): return False

        class _Db:
            def connect(self): return _Conn()

        sub = EdrPersistenceSubscriber.__new__(EdrPersistenceSubscriber)
        sub._database = _Db()
        buf = {
            "seq": 7, "tsUtc": "2026-08-29T18:00:00Z", "tsCapture": 1.0,
            "dataSource": "real",
            "fields": {"lux": 209.0, "raw": (5884, 29230, 35114), "range": (0x10, 100)},
        }
        sub._writeLightRow(buf, driveId=51)

        sql, params = rows[0]
        assert "gain" in sql and "integration_ms" in sql, (
            "the INSERT must name the columns -- they existed and were omitted"
        )
        assert "med" in params, "gain code 0x10 must land as its schema label"
        assert 100 in params, "integration_ms must land"

    def test_anAbsentRangeStillWritesTheRow(self, tmp_path):
        """The context is diagnostic. Its absence must never cost us the READING
        -- a partial burst persists as NULL, an honest gap, not a lost sample."""
        from src.pi.bus.edr_persistence_subscriber import EdrPersistenceSubscriber
        rows = []

        class _Conn:
            def execute(self, sql, params): rows.append((sql, params))
            def __enter__(self): return self
            def __exit__(self, *a): return False

        class _Db:
            def connect(self): return _Conn()

        sub = EdrPersistenceSubscriber.__new__(EdrPersistenceSubscriber)
        sub._database = _Db()
        buf = {
            "seq": 8, "tsUtc": "2026-08-29T18:00:01Z", "tsCapture": 2.0,
            "dataSource": "real",
            "fields": {"lux": 209.0, "raw": (1, 2, 3)},   # no range field
        }
        sub._writeLightRow(buf, driveId=None)

        assert len(rows) == 1, "the reading is written even with no range context"
        _, params = rows[0]
        assert None in params


class TestTheReaderPublishesIt:
    def test_lightReaderPublishesRangeAlongsideLuxAndRaw(self):
        """Same burst, so either all three arrive or none do."""
        from src.pi.sensors.sensor_reader import (
            TOPIC_LIGHT_LUX,
            TOPIC_LIGHT_RANGE,
            TOPIC_LIGHT_RAW,
            LightReader,
        )
        published = []

        class _Dev:
            visible, infrared, full_spectrum = 5884, 29230, 35114
            lux = 209.0
            gain = 0x10
            integration_time = 1          # index, not milliseconds

        r = LightReader.__new__(LightReader)
        r._device = _Dev()
        r._publishBurst = lambda items, seq: published.extend(items)
        r._readAndPublish(3)

        topics = [t for t, _v, _u in published]
        assert TOPIC_LIGHT_LUX in topics and TOPIC_LIGHT_RAW in topics
        assert TOPIC_LIGHT_RANGE in topics, "the range context must ride the same burst"
        rng = next(v for t, v, _u in published if t == TOPIC_LIGHT_RANGE)
        assert rng[0] == 0x10
        assert rng[1] == 200, "integration index 1 -> 200 ms (chip step is 100ms)"
