################################################################################
# File Name: test_light_autorange.py
# Purpose/Description: US-731 -- the TSL2591 reads daylight. Auto-range between
#                      LOW and MEDIUM gain (CIO 2026-10-06: never above medium,
#                      so night readings stay as today), and compute lux with the
#                      DATASHEET's gain multipliers (CIO 2026-10-06) instead of the
#                      library's. Four sensor reads per sample stay four (CIO).
# Author: Atlas (architect)
# Creation Date: 2026-10-06
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-06    | Atlas        | US-731 (CIO-directed build, charter override).
#                               Source: ams TSL2591 datasheet v3-00 (2023-02-08),
#                               hardware/datasheets/tsl2591/.
# ================================================================================
################################################################################
"""US-731: auto-ranging LOW<->MEDIUM; lux from counts with the datasheet's gains."""

from __future__ import annotations

import pytest

import pi.sensors.sensor_reader as sr  # the siblings' path (one module identity)
from pi.bus.bus import SampleBus
from pi.bus.sample import QoS
from pi.sensors.sensor_reader import LightReader, _luxFromCounts

LOW, MED, HIGH, MAX = 0x00, 0x10, 0x20, 0x30  # ams datasheet, CONTROL 0x01, AGAIN bits 5:4
IT_100MS, IT_200MS = 0, 1                       # ATIME 000b / 001b


class FakeTsl:
    """The adafruit_tsl2591.TSL2591 surface the reader uses (library 1.4.8).

    ``raw_luminosity`` -> (CH0 = full spectrum, CH1 = infrared); ``full_spectrum``
    is CH0, ``infrared`` is CH1, ``visible`` is CH0 - CH1 (read from the installed
    library on the car, 2026-10-06). Each property re-reads the current counts.
    """

    def __init__(self, counts, *, gain=MED, integration=IT_100MS, failGainWrite=False):
        self._seq = list(counts)
        self._cur = self._seq[0]
        self._gain = gain
        self.integration_time = integration
        self._fail = failGainWrite
        self.gainWrites: list[int] = []

    def advance(self) -> None:
        if len(self._seq) > 1:
            self._seq.pop(0)
        self._cur = self._seq[0]

    @property
    def gain(self) -> int:
        return self._gain

    @gain.setter
    def gain(self, value: int) -> None:
        self.gainWrites.append(value)
        if self._fail:
            raise OSError("I2C write failed")
        self._gain = value

    @property
    def raw_luminosity(self):
        return self._cur

    @property
    def full_spectrum(self) -> int:
        return self._cur[0]

    @property
    def infrared(self) -> int:
        return self._cur[1]

    @property
    def visible(self) -> int:
        return self._cur[0] - self._cur[1]


def _expectedLux(ch0: float, ch1: float, gain: float, atimeMs: float = 100.0) -> float:
    """The equation, written out independently: Adafruit's (DF 408, B 1.64, C 0.59, D 0.86)."""
    cpl = atimeMs * gain / 408.0
    return max((ch0 - 1.64 * ch1) / cpl, (0.59 * ch0 - 0.86 * ch1) / cpl)


# =============================================================================
# Lux from counts, with the DATASHEET's gains
# =============================================================================


class TestLuxUsesTheDatasheetGains:

    def test_medium_is24point5_notTheLibrarys25(self) -> None:
        lux = _luxFromCounts(10000, 2000, MED, IT_100MS)
        assert lux == pytest.approx(_expectedLux(10000, 2000, 24.5), rel=1e-9)
        assert lux != pytest.approx(_expectedLux(10000, 2000, 25.0), rel=1e-6)

    def test_low_isUnity_andReadsDaylight(self) -> None:
        """30,000 / 6,000 counts at LOW gain is ~82,000 lux: full sun through glass."""
        lux = _luxFromCounts(30000, 6000, LOW, IT_100MS)
        assert lux == pytest.approx(_expectedLux(30000, 6000, 1.0), rel=1e-9)
        assert 50_000 < lux < 100_000

    def test_saturatedAt100ms_isNone(self) -> None:
        """36,863 is the documented max count at 100 ms -- a saturated read is not a reading."""
        assert _luxFromCounts(36863, 1000, MED, IT_100MS) is None
        assert _luxFromCounts(1000, 36863, MED, IT_100MS) is None

    def test_longerIntegration_hasThe65535Ceiling(self) -> None:
        lux = _luxFromCounts(40000, 2000, MED, IT_200MS)
        assert lux == pytest.approx(_expectedLux(40000, 2000, 24.5, 200.0), rel=1e-9)

    def test_maxGain_isNotComputed(self) -> None:
        """MAX's documented gain differs by channel (9,200 vs 9,900); one multiplier would be a guess."""
        assert _luxFromCounts(100, 10, MAX, IT_100MS) is None

    def test_unknownGainOrIntegration_isNone(self) -> None:
        assert _luxFromCounts(100, 10, 0x40, IT_100MS) is None
        assert _luxFromCounts(100, 10, MED, 9) is None

    def test_irDominated_negative_isNone_notZero(self) -> None:
        """ARCH-010 still holds: low sun through glass computes negative -> None, never clamped to 0."""
        assert _luxFromCounts(1000, 900, MED, IT_100MS) is None

    def test_trueDarkZero_isAReading(self) -> None:
        assert _luxFromCounts(0, 0, MED, IT_100MS) == 0.0

    def test_theReaderPublishesTheCountsLux(self) -> None:
        """The device path end to end: one raw read, the device's own range, datasheet gain."""
        samples = _poll(FakeTsl([(10000, 2000)], gain=MED), 1)
        assert samples[0]["lux"] == pytest.approx(_expectedLux(10000, 2000, 24.5), rel=1e-9)


# =============================================================================
# Auto-ranging, LOW <-> MEDIUM only
# =============================================================================


def _poll(dev: FakeTsl, n: int) -> list[dict]:
    """Run ``n`` reader polls; return per-sample {lux, gain} as published on the bus."""
    bus = SampleBus()
    sub = bus.subscribe(["raw.light.*"], QoS.LOSSY, "t")
    reader = LightReader(bus, deviceFactory=lambda: dev)
    reader.probe()
    out: list[dict] = []
    for _ in range(n):
        reader.pollOnce()
        sample: dict = {}
        while (s := sub.poll()) is not None:
            if s.topic == sr.TOPIC_LIGHT_LUX:
                sample["lux"] = s.value
            elif s.topic == sr.TOPIC_LIGHT_RANGE:
                sample["gain"] = s.value[0]
        out.append(sample)
        dev.advance()
    return out


class TestAutoRange:

    def test_daylight_saturatedThenReadAtLowGain(self) -> None:
        """
        🔴 THE US-731 DEFECT. Full sun at medium gain saturates (lux NULL, as on every
        sunny drive to date). The reader steps to LOW; the NEXT sample is a real
        daylight lux. Today the gain never changes and every sample stays NULL.
        """
        dev = FakeTsl([(36863, 9000), (30000, 6000)], gain=MED)

        samples = _poll(dev, 2)

        assert samples[0] == {"lux": None, "gain": MED}
        assert samples[1]["gain"] == LOW
        assert samples[1]["lux"] == pytest.approx(_expectedLux(30000, 6000, 1.0), rel=1e-9)

    def test_nearSaturation_stepsDownBeforeOverflow(self) -> None:
        """At >= 90 % of the max count the reading is still valid AND the gain steps down."""
        dev = FakeTsl([(34000, 3000)], gain=MED)

        samples = _poll(dev, 1)

        assert samples[0]["lux"] is not None
        assert dev.gain == LOW

    def test_darkAtLow_stepsBackUpToMedium(self) -> None:
        """600 counts at LOW is < 50 % of full scale even at the datasheet's worst-case 27x."""
        dev = FakeTsl([(600, 100)], gain=LOW)

        _poll(dev, 1)

        assert dev.gain == MED

    def test_hysteresis_noFlapping(self) -> None:
        """1,000 counts at LOW would be up to 27,000 at MED -- too close to the step-down: stay LOW.
        20,000 at MED is below the step-down: stay MED."""
        low = FakeTsl([(1000, 100)], gain=LOW)
        med = FakeTsl([(20000, 2000)], gain=MED)

        _poll(low, 1)
        _poll(med, 1)

        assert low.gainWrites == [] and med.gainWrites == []

    def test_neverRangesAboveMedium(self) -> None:
        """CIO 2026-10-06: night readings stay exactly as today (medium)."""
        dev = FakeTsl([(5, 1)], gain=MED)

        _poll(dev, 3)

        assert dev.gainWrites == []

    def test_sunToTunnelToSun_settlesEachTime(self) -> None:
        dev = FakeTsl(
            [(36863, 9000), (30000, 6000), (400, 50), (12000, 2000), (36863, 9000), (28000, 5000)],
            gain=MED,
        )

        samples = _poll(dev, 6)

        assert [s["gain"] for s in samples] == [MED, LOW, LOW, MED, MED, LOW]
        assert dev.gainWrites == [LOW, MED, LOW]

    def test_aFailedGainWrite_neverStopsTheReading(self) -> None:
        dev = FakeTsl([(36863, 9000), (36863, 9000)], gain=MED, failGainWrite=True)

        samples = _poll(dev, 2)

        assert len(samples) == 2 and all(s["gain"] == MED for s in samples)
        assert dev.gainWrites == [LOW, LOW]  # retried next sample, never raised
