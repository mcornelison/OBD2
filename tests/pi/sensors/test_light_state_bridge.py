################################################################################
# File Name: test_light_state_bridge.py
# Purpose/Description: Unit tests for the light -> states/light bridge (US-483-a,
#     F-121). Drains raw.light.lux off the F-110 SampleBus and mirrors it into the
#     dashboard states/light file ({lux, ts}), the pure-consumer state file the
#     US-483-b brightness consumer reads (Atlas DELTA-2). Honest-instrument: a
#     saturated read (lux=None) is written as JSON null, never inf/fabricated; the
#     freshness ts is the sample's own read-time so a dead feed goes honestly
#     stale. Gated behind pi.bus.enabled + pi.sensors.light.enabled (ships dark).
#     US-878-a: the bridge pairs lux, raw and range by Sample.seq and writes
#     the raw counts, gain label, integration ms and channelAtLimit.
#     US-878-b: states/light gains brightnessLevel / brightnessMode; the
#     exact-payload pins below gain the two keys, and the autoDim re-read on a
#     config.json / config.local.json mtime change is tested on a fake clock.
#     US-893-a: states/light gains lightBand, curve, reasons and atLimit, and a
#     null lux publishes brightnessMode 'default'. MOVED PIN (US-893-a): the
#     key set and the two exact-payload pins gain the four keys.
#     US-869-a: the bridge subscribes to the retained presence STATE; on ABSENT
#     it writes states/light once with reason sensor_absent and exposes
#     presenceFault. The fixture gains a sensor-absent case (5 cases).
# Author: Rex (US-483-a)
# Creation Date: 2026-07-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Unit tests for the light-state bridge (one reader burst -> states/light)."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from pi.bus.bus import SampleBus
from pi.bus.sample import QoS, Sample
from pi.sensors.light_state_bridge import (
    LIGHT_REASON_SENSOR_ABSENT,
    LIGHT_STATE_FILENAME,
    LightStateBridge,
    brightnessCurvePoints,
    brightnessKnee,
    brightnessLevel,
    buildLightState,
    createLightStateBridgeFromConfig,
    lightBand,
)
from pi.sensors.sensor_reader import (
    ABSENT,
    PRESENT,
    STATE_LIGHT,
    TOPIC_LIGHT_LUX,
    TOPIC_LIGHT_RANGE,
    TOPIC_LIGHT_RAW,
    TSL_GAIN_LOW,
    TSL_GAIN_MED,
)

_FIXTURE = (
    Path(__file__).resolve().parents[2] / "ui" / "fixtures" / "states" / "light.json"
)

_T = "2026-10-20T15:02:11.3Z"

# MOVED PIN (US-893-a): gains lightBand, curve, reasons and atLimit.
_STATE_KEYS = {
    "lux", "visibleCount", "irCount", "fullCount", "gain", "integrationMs",
    "channelAtLimit", "atLimit", "lightBand", "brightnessLevel", "brightnessMode",
    "curve", "reasons", "ts",
}

# Validator-default levels for the lux values the exact pins below use (the
# curve itself is pinned by tests/pi/sensors/test_brightness_golden.py).
_LEVEL_120_5 = 0.635728449174043
_LEVEL_80 = brightnessLevel(80.0, None)

# The curve every validator-default write publishes (its points are pinned by
# the curve tests below, not restated in each exact-payload pin).
_CURVE_DEFAULTS = brightnessCurvePoints(None)

# pi.display.autoDim as shipped on this car (Atlas MEASURED 2026-10-14).
_SHIPPED_AUTODIM = {
    "luxMin": 3.0, "luxFull": 300.0, "minLevel": 0.75, "defaultLevel": 1.0,
    "luxStaleSec": 10, "curve": "logarithmic",
}


def _sample(topic: str, value, seq: int, *, ts: str = _T) -> Sample:
    """One light-channel bus sample of burst ``seq``."""
    return Sample(
        topic=topic,
        source="light",
        value=value,
        unit="",
        tsUtc=ts,
        tsCapture=float(seq),
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _lux(value, seq: int = 1, *, ts: str = "2026-07-22T00:00:00Z") -> Sample:
    """Build one raw.light.lux sample carrying ``value`` (float or None)."""
    return _sample(TOPIC_LIGHT_LUX, value, seq, ts=ts)


def _burst(seq: int, lux, raw, rangeCtx, *, ts: str = _T) -> list[Sample]:
    """The reader's burst: lux, raw, range in publish order under one seq."""
    return [
        _sample(TOPIC_LIGHT_LUX, lux, seq, ts=ts),
        _sample(TOPIC_LIGHT_RAW, raw, seq, ts=ts),
        _sample(TOPIC_LIGHT_RANGE, rangeCtx, seq, ts=ts),
    ]


class _RecordingBridge(LightStateBridge):
    """The real bridge, recording each payload it writes (no filesystem)."""

    def __init__(self) -> None:
        super().__init__(None, "unused")
        self.writes: list[dict] = []

    def _writeState(self, payload: dict) -> None:
        self.writes.append(payload)


def _readState(statesDir: Path) -> dict:
    """Load the written states/light JSON."""
    return json.loads((statesDir / LIGHT_STATE_FILENAME).read_text(encoding="utf-8"))


# --------------------------------------------------------------- buildLightState


def test_buildLightState_realReading_carriesFloatLuxAndTs():
    """
    Given: a real lux reading + a read-time ts
    When: buildLightState assembles the payload
    Then: lux and ts carry today's meaning, alongside the US-878-a keys
    """
    state = buildLightState(lux=123.5, tsUtc="2026-07-22T01:02:03Z")

    assert set(state) == _STATE_KEYS
    assert state["lux"] == 123.5
    assert state["ts"] == "2026-07-22T01:02:03Z"
    assert isinstance(state["lux"], float)


def test_buildLightState_saturatedReading_luxIsNullNeverFabricated():
    """
    Given: a saturated read (lux=None per sensor_reader honest-instrument)
    When: buildLightState assembles the payload
    Then: lux is None (JSON null) -- never a fabricated 0.0 or inf
    """
    state = buildLightState(lux=None, tsUtc="2026-07-22T01:02:03Z")

    assert state["lux"] is None


def test_buildLightState_nonFiniteReading_coercedToNull():
    """
    Given: a non-finite lux slips through (defense-in-depth)
    When: buildLightState assembles the payload
    Then: it is coerced to None -- an inf/nan never lands in the state file
    """
    assert buildLightState(lux=float("inf"), tsUtc="t")["lux"] is None
    assert buildLightState(lux=float("nan"), tsUtc="t")["lux"] is None


def test_buildLightState_negativeVisible_isNull_irAndFullAsRead():
    """
    Given: raw (-1, 5, 4) -- visible = full - infrared on a failed read
    When: buildLightState assembles the payload
    Then: visibleCount null; irCount 5; fullCount 4
    """
    state = buildLightState(
        lux=None, tsUtc=_T, rawCounts=(-1, 5, 4), rangeContext=(TSL_GAIN_MED, 100)
    )

    assert state["visibleCount"] is None
    assert state["irCount"] == 5
    assert state["fullCount"] == 4


def test_buildLightState_fullAtCeiling_channelAtLimit_luxNull():
    """
    Given: integrationMs 100 and full 36863 (the 100 ms ceiling)
    When: buildLightState assembles the payload, even with a lux passed in
    Then: channelAtLimit true and lux null
    """
    state = buildLightState(
        lux=55.0, tsUtc=_T, rawCounts=(2100, 34763, 36863), rangeContext=(TSL_GAIN_LOW, 100)
    )

    assert state["channelAtLimit"] is True
    assert state["lux"] is None


def test_buildLightState_irAtCeiling_channelAtLimit():
    """An infrared channel at the ceiling is saturation too."""
    state = buildLightState(
        lux=None, tsUtc=_T, rawCounts=(0, 65535, 65535), rangeContext=(TSL_GAIN_LOW, 200)
    )

    assert state["channelAtLimit"] is True


def test_buildLightState_unknownMsAndGainCode_areNull():
    """
    Given: integrationMs 150 (no ceiling) and gain code 0x40
    When: buildLightState assembles the payload
    Then: channelAtLimit null; gain null; integrationMs published as read
    """
    state = buildLightState(
        lux=10.0, tsUtc=_T, rawCounts=(900, 300, 1200), rangeContext=(0x40, 150)
    )

    assert state["channelAtLimit"] is None
    assert state["gain"] is None
    assert state["integrationMs"] == 150


def test_buildLightState_gainIsALabelNeverARegisterCode():
    """Each AGAIN register code publishes as its label."""
    labels = [
        buildLightState(lux=None, tsUtc=_T, rangeContext=(code, 100))["gain"]
        for code in (0x00, 0x10, 0x20, 0x30)
    ]

    assert labels == ["low", "med", "high", "max"]


def test_buildLightState_rawLost_channelAtLimitNull():
    """A known ceiling with no counts read cannot say the channel is below it."""
    state = buildLightState(lux=1.0, tsUtc=_T, rangeContext=(TSL_GAIN_MED, 100))

    assert state["channelAtLimit"] is None


# ------------------------------------------- US-893-a: band, mode, reasons, atLimit


def test_lightBand_belowLuxMin_isNight_andModeAuto():
    """VC: lux 0.6, luxMin 3, luxFull 300 -> lightBand 'night', mode 'auto'."""
    state = buildLightState(lux=0.6, tsUtc=_T, autoDim=_SHIPPED_AUTODIM)

    assert state["lightBand"] == "night"
    assert state["brightnessMode"] == "auto"


def test_buildLightState_nullLux_bandNull_levelDefault_modeDefault():
    """VC: lux null, defaultLevel 1.0 -> lightBand null, level 1.0, mode 'default'."""
    state = buildLightState(lux=None, tsUtc=_T, autoDim=_SHIPPED_AUTODIM)

    assert state["lightBand"] is None
    assert state["brightnessLevel"] == 1.0
    assert state["brightnessMode"] == "default"


@pytest.mark.parametrize(
    ("lux", "band"),
    [(0.0, "night"), (2.999, "night"), (3.0, "dusk"), (299.9, "dusk"),
     (300.0, "day"), (30000.0, "day")],
)
def test_lightBand_boundaries_dayInclusiveAtLuxFull_nightExclusiveAtLuxMin(lux, band):
    """lux < luxMin is night, lux >= luxFull is day, between is dusk."""
    assert lightBand(lux, _SHIPPED_AUTODIM) == band


@pytest.mark.parametrize("lux", [None, -1.0, -0.001, float("nan"), float("inf"), "x"])
def test_lightBand_notAReading_isNull(lux):
    """The one lux predicate (Atlas A3): not finite-and->=0 -> no band."""
    assert lightBand(lux, _SHIPPED_AUTODIM) is None


def test_lightBand_degenerateRange_isDayAtLuxFull_neverDusk():
    """luxFull <= luxMin: day is tested first, so dusk is unreachable."""
    autoDim = dict(_SHIPPED_AUTODIM, luxMin=100.0, luxFull=100.0)

    assert lightBand(50.0, autoDim) == "night"
    assert lightBand(100.0, autoDim) == "day"
    assert brightnessLevel(100.0, autoDim) == 1.0


def test_lightBand_nonPositiveLuxMin_hasNoNight():
    """With luxMin <= 0 no reading (>= 0) is below it."""
    autoDim = dict(_SHIPPED_AUTODIM, luxMin=0.0)

    assert lightBand(0.0, autoDim) == "dusk"


def test_buildLightState_negativeLux_publishesNull_modeDefault():
    """Atlas A3: -1 is a failed read, published null, never a number."""
    state = buildLightState(lux=-1.0, tsUtc=_T, autoDim=_SHIPPED_AUTODIM)

    assert state["lux"] is None
    assert state["brightnessMode"] == "default"
    assert state["lightBand"] is None
    assert state["reasons"] == {"lux": "no_reading"}


def test_buildLightState_reasons_atLimitWhenSaturated():
    """L1: a null lux from a channel at the ceiling says at_limit."""
    state = buildLightState(
        lux=55.0, tsUtc=_T, rawCounts=(2100, 34763, 36863), rangeContext=(TSL_GAIN_LOW, 100)
    )

    assert state["reasons"] == {"lux": "at_limit"}


def test_buildLightState_reasons_noReadingWhenAbsent_emptyWhenRead():
    """L1: present only when lux is null; no_reading when not at the limit."""
    assert buildLightState(lux=None, tsUtc=_T)["reasons"] == {"lux": "no_reading"}
    assert buildLightState(lux=12.0, tsUtc=_T)["reasons"] == {}


def test_buildLightState_atLimit_isPerChannel():
    """L2: ir at the 200 ms ceiling, full below it -> {ir: true, full: false}."""
    state = buildLightState(
        lux=None, tsUtc=_T, rawCounts=(0, 65535, 60000), rangeContext=(TSL_GAIN_LOW, 200)
    )

    assert state["atLimit"] == {"ir": True, "full": False}
    assert state["channelAtLimit"] is True


def test_buildLightState_atLimit_unknownCeilingOrCount_isNull():
    """L2: an unknown ceiling or a lost count is null, never a guess."""
    noCeiling = buildLightState(
        lux=1.0, tsUtc=_T, rawCounts=(9, 1, 10), rangeContext=(TSL_GAIN_MED, 150)
    )
    noIr = buildLightState(
        lux=1.0, tsUtc=_T, rawCounts=(9, None, 10), rangeContext=(TSL_GAIN_MED, 100)
    )

    assert noCeiling["atLimit"] == {"ir": None, "full": None}
    assert noIr["atLimit"] == {"ir": None, "full": False}


# ------------------------------------------------------------ US-893-a: the curve


def test_curve_shippedConfig_kneeAt94_9IsMinLevel_and300IsFull():
    """VC: the point at ~94.9 lux has level 0.75; the point at 300 has 1.0."""
    curve = buildLightState(lux=22.0, tsUtc=_T, autoDim=_SHIPPED_AUTODIM)["curve"]
    byLux = {lux: level for lux, level in curve["points"]}
    knee = [lux for lux in byLux if 94.0 < lux < 95.5]

    assert knee == [pytest.approx(94.8683298050514, abs=1e-9)]
    assert byLux[knee[0]] == pytest.approx(0.75, abs=1e-9)
    assert byLux[300.0] == 1.0


def test_curve_shippedConfig_is51SortedListPointsWithExactBreakpoints():
    """A4: 51 points; luxMin, luxFull and the knee are published exactly."""
    curve = brightnessCurvePoints(_SHIPPED_AUTODIM)
    luxes = [p[0] for p in curve["points"]]

    assert len(curve["points"]) == 51
    assert all(isinstance(p, list) and len(p) == 2 for p in curve["points"])
    assert luxes == sorted(luxes)
    assert len(set(luxes)) == len(luxes)
    assert 3.0 in luxes
    assert 300.0 in luxes
    assert brightnessKnee(_SHIPPED_AUTODIM) in luxes
    assert luxes[0] == pytest.approx(0.3)
    assert luxes[-1] == pytest.approx(30000.0)
    assert (curve["luxMin"], curve["luxFull"], curve["minLevel"]) == (3.0, 300.0, 0.75)


def test_curve_everyLevelIsBrightnessLevelExactly():
    """A4: each level is brightnessLevel(lux, the same autoDim), exactly."""
    for lux, level in brightnessCurvePoints(_SHIPPED_AUTODIM)["points"]:
        assert level == brightnessLevel(lux, _SHIPPED_AUTODIM), lux


def test_curve_gridPointOneUlpFromTheKnee_isDroppedForTheBreakpoint():
    """A4: the grid's 94.86832980505139 is dropped; the exact knee is kept."""
    luxes = [p[0] for p in brightnessCurvePoints(_SHIPPED_AUTODIM)["points"]]
    gridNeighbour = 0.3 * 10 ** (25 / 10)

    assert gridNeighbour != brightnessKnee(_SHIPPED_AUTODIM)
    assert gridNeighbour not in luxes


def test_curve_validatorDefaults_addLuxFullAndKneeOffTheGrid():
    """luxFull 1000 and its knee are off the grid, so both are added (53)."""
    luxes = [p[0] for p in brightnessCurvePoints(None)["points"]]

    assert 1000.0 in luxes
    assert brightnessKnee(None) in luxes
    assert len(luxes) == 53


def test_knee_minLevelZero_none():
    """VC: minLevel 0 -> no knee point."""
    autoDim = dict(_SHIPPED_AUTODIM, minLevel=0.0)

    assert brightnessKnee(autoDim) is None
    assert len(brightnessCurvePoints(autoDim)["points"]) == 51


def test_knee_minLevelOne_none():
    """A5: minLevel >= 1 clamps the curve to 1 everywhere -- no knee."""
    assert brightnessKnee(dict(_SHIPPED_AUTODIM, minLevel=1.0)) is None


def test_knee_degenerateRange_none():
    """A5: luxFull <= luxMin is 1.0 everywhere -- no knee."""
    assert brightnessKnee(dict(_SHIPPED_AUTODIM, luxMin=300.0, luxFull=300.0)) is None


def test_knee_linearCurve_isLinearInterpolation():
    """A5: linear -> luxMin + minLevel * (luxFull - luxMin)."""
    autoDim = dict(_SHIPPED_AUTODIM, curve="linear")

    assert brightnessKnee(autoDim) == pytest.approx(3.0 + 0.75 * 297.0)


def test_knee_nonPositiveLuxMin_isLinear_andLuxMinNotABreakpoint():
    """A5: luxMin <= 0 -> linear; a non-positive luxMin is not published."""
    autoDim = dict(_SHIPPED_AUTODIM, luxMin=0.0)
    luxes = [p[0] for p in brightnessCurvePoints(autoDim)["points"]]

    assert brightnessKnee(autoDim) == pytest.approx(0.75 * 300.0)
    assert 0.0 not in luxes


def test_knee_logCurve_isGeometric():
    """A5: log -> luxMin * (luxFull / luxMin) ** minLevel."""
    assert brightnessKnee(_SHIPPED_AUTODIM) == pytest.approx(3.0 * 100.0 ** 0.75)


def test_buildLightState_freshCurveListsEveryCall():
    """A6: no write can mutate another write's curve."""
    first = buildLightState(lux=1.0, tsUtc=_T)
    first["curve"]["points"][0][1] = -5.0
    first["curve"]["points"].clear()

    second = buildLightState(lux=1.0, tsUtc=_T)

    assert len(second["curve"]["points"]) == 53
    assert second["curve"]["points"][0][1] >= 0.0


def test_buildLightState_levelBandAndCurve_shareOneAutoDim():
    """A6: level, band and curve come from the same resolved autoDim."""
    autoDim = dict(_SHIPPED_AUTODIM, luxFull=50.0)
    state = buildLightState(lux=60.0, tsUtc=_T, autoDim=autoDim)

    assert state["lightBand"] == "day"
    assert state["brightnessLevel"] == 1.0
    assert state["curve"]["luxFull"] == 50.0


# ------------------------------------------------------- fixture conformance (R29)

# The producer inputs behind every named case of tests/ui/fixtures/states/light.json.
_FIXTURE_INPUTS: dict[str, dict] = {
    "normal": {
        "lux": 120.5, "tsUtc": "2026-10-20T15:02:11.3Z",
        "rawCounts": (900, 300, 1200), "rangeContext": (TSL_GAIN_MED, 100),
    },
    "saturated": {
        "lux": None, "tsUtc": "2026-10-20T15:02:11.3Z",
        "rawCounts": (2100, 34763, 36863), "rangeContext": (TSL_GAIN_LOW, 100),
    },
    "dark-failed-read": {
        "lux": None, "tsUtc": "2026-10-20T03:40:02.9Z",
        "rawCounts": (-1, 5, 4), "rangeContext": (TSL_GAIN_MED, 100),
    },
    "partial-burst": {
        "lux": 120.5, "tsUtc": "2026-10-20T15:02:12.3Z",
        "rawCounts": None, "rangeContext": (TSL_GAIN_MED, 100),
    },
    # MOVED PIN (US-869-a): the presence-ABSENT case (no light sample at all).
    "sensor-absent": {
        "lux": None, "tsUtc": "2026-10-20T15:02:10.0Z",
        "unavailableReason": LIGHT_REASON_SENSOR_ABSENT,
    },
}


def test_fixture_namesEveryRequiredCase():
    """The fixture is an object of the five named states/light payloads."""
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    assert set(fixture) == set(_FIXTURE_INPUTS)


@pytest.mark.parametrize("name", sorted(_FIXTURE_INPUTS))
def test_fixture_caseIsExactlyWhatTheProducerBuilds(name: str):
    """
    Given: a named fixture case and the producer inputs behind it
    When: buildLightState builds the payload
    Then: it equals the fixture case key for key (R29)
    """
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    assert buildLightState(**_FIXTURE_INPUTS[name]) == fixture[name]


# --------------------------------------------------------- burst pairing (seq)


def test_handleSample_oneBurst_writesOnceOnTheRangeSample():
    """
    Given: one burst seq=7: lux 120.5, raw (900, 300, 1200), range (0x10, 100)
    When: the three samples are handled in publish order
    Then: one write, on the range sample, carrying every field of the burst
    """
    bridge = _RecordingBridge()
    lux, raw, rangeSample = _burst(7, 120.5, (900, 300, 1200), (TSL_GAIN_MED, 100))

    bridge.handleSample(lux)
    bridge.handleSample(raw)
    assert bridge.writes == []
    bridge.handleSample(rangeSample)

    # MOVED PIN (US-893-a): + atLimit, lightBand, curve, reasons.
    assert bridge.writes == [{
        "lux": 120.5, "visibleCount": 900, "irCount": 300, "fullCount": 1200,
        "gain": "med", "integrationMs": 100, "channelAtLimit": False,
        "atLimit": {"ir": False, "full": False}, "lightBand": "dusk",
        "brightnessLevel": _LEVEL_120_5, "brightnessMode": "auto",
        "curve": _CURVE_DEFAULTS, "reasons": {}, "ts": _T,
    }]


def test_handleSample_saturatedBurst_channelAtLimitTrue_luxNull():
    """A burst at integrationMs 100 with full 36863 and lux None."""
    bridge = _RecordingBridge()
    for sample in _burst(3, None, (2100, 34763, 36863), (TSL_GAIN_LOW, 100)):
        bridge.handleSample(sample)

    assert bridge.writes[-1]["channelAtLimit"] is True
    assert bridge.writes[-1]["lux"] is None


def test_handleSample_rangeDropped_burstWrittenWhenNewerSeqArrives_neverBorrowed():
    """
    Given: a complete burst seq=7, then lux and raw for seq=8 (range dropped)
    When: lux for seq=9 arrives
    Then: seq=8 is written with gain, integrationMs, channelAtLimit null --
        never seq=7's values
    """
    bridge = _RecordingBridge()
    for sample in _burst(7, 120.5, (900, 300, 1200), (TSL_GAIN_MED, 100)):
        bridge.handleSample(sample)
    seq8 = "2026-10-20T15:02:12.3Z"
    bridge.handleSample(_sample(TOPIC_LIGHT_LUX, 80.0, 8, ts=seq8))
    bridge.handleSample(_sample(TOPIC_LIGHT_RAW, (600, 200, 800), 8, ts=seq8))
    assert len(bridge.writes) == 1

    bridge.handleSample(_sample(TOPIC_LIGHT_LUX, 81.0, 9, ts="2026-10-20T15:02:13.3Z"))

    assert len(bridge.writes) == 2
    # MOVED PIN (US-893-a): + atLimit, lightBand, curve, reasons.
    assert bridge.writes[1] == {
        "lux": 80.0, "visibleCount": 600, "irCount": 200, "fullCount": 800,
        "gain": None, "integrationMs": None, "channelAtLimit": None,
        "atLimit": {"ir": None, "full": None}, "lightBand": "dusk",
        "brightnessLevel": _LEVEL_80, "brightnessMode": "auto",
        "curve": _CURVE_DEFAULTS, "reasons": {}, "ts": seq8,
    }


def test_handleSample_luxDropped_tsIsTheBurstsOwnEventTime():
    """A burst whose lux was dropped still writes the burst's own event ts."""
    bridge = _RecordingBridge()
    bridge.handleSample(_sample(TOPIC_LIGHT_RAW, (900, 300, 1200), 4, ts="2026-10-20T01:00:00Z"))
    bridge.handleSample(_sample(TOPIC_LIGHT_RANGE, (TSL_GAIN_MED, 100), 4, ts="t2"))

    assert bridge.writes[0]["lux"] is None
    assert bridge.writes[0]["ts"] == "2026-10-20T01:00:00Z"


def test_handleSample_emptyTs_isNullNeverTheClock():
    """US-809-c: a burst with no event ts writes ts null."""
    bridge = _RecordingBridge()
    for sample in _burst(1, 5.0, (900, 300, 1200), (TSL_GAIN_MED, 100), ts=""):
        bridge.handleSample(sample)

    assert bridge.writes[0]["ts"] is None


def test_handleSample_unknownMsAndGain_writesNulls():
    """A burst with integrationMs 150 and gain code 0x40."""
    bridge = _RecordingBridge()
    for sample in _burst(2, 10.0, (900, 300, 1200), (0x40, 150)):
        bridge.handleSample(sample)

    assert bridge.writes[0]["channelAtLimit"] is None
    assert bridge.writes[0]["gain"] is None


def test_handleSample_nonLightTopic_ignoredNoWrite(tmp_path: Path):
    """
    Given: a topic outside the light burst (raw.obd.*) reaches the bridge
    When: it is handled
    Then: it is ignored (False) and no states/light file is written
    """
    bridge = LightStateBridge(None, str(tmp_path))
    obd = Sample(
        topic="raw.obd.RPM", source="obd", value=800.0, unit="rpm",
        tsUtc="t", tsCapture=1.0, driveId=None, dataSource="real", seq=1,
    )

    assert bridge.handleSample(obd) is False
    assert not (tmp_path / LIGHT_STATE_FILENAME).exists()


def test_handleSample_burst_writesStatesLightAtomically(tmp_path: Path):
    """
    Given: a bridge bound to a states dir
    When: a complete burst is handled
    Then: states/light on disk holds the burst with the sample's read-time ts
    """
    bridge = LightStateBridge(None, str(tmp_path))

    for sample in _burst(1, 42.0, (900, 300, 1200), (TSL_GAIN_MED, 100), ts="2026-07-22T05:06:07Z"):
        assert bridge.handleSample(sample) is True

    state = _readState(tmp_path)
    assert state["lux"] == 42.0
    assert state["fullCount"] == 1200
    assert state["ts"] == "2026-07-22T05:06:07Z"


# ------------------------------------------------------------- end-to-end (bus)


# ------------------------------------------------- presence STATE (US-869-a)


def _presence(value: float, *, ts: str = "2026-10-23T08:00:00Z") -> Sample:
    """The reader's retained presence STATE sample (sensor_reader._publishState)."""
    return Sample(
        topic=STATE_LIGHT,
        source="light",
        value=value,
        unit="present" if value else "absent",
        tsUtc=ts,
        tsCapture=0.0,
        driveId=None,
        dataSource="real",
        seq=0,
    )


def test_buildLightState_unavailableReason_luxNullReasonAndTopLevelKey():
    """
    Given: unavailableReason sensor_absent (and even a stray lux)
    When: buildLightState assembles the payload
    Then: lux null, reasons.lux and top-level unavailableReason are sensor_absent,
        and brightness falls back to the default branch
    """
    state = buildLightState(lux=50.0, tsUtc=_T, unavailableReason=LIGHT_REASON_SENSOR_ABSENT)

    assert set(state) == _STATE_KEYS | {"unavailableReason"}
    assert state["lux"] is None
    assert state["reasons"] == {"lux": "sensor_absent"}
    assert state["unavailableReason"] == "sensor_absent"
    assert state["lightBand"] is None
    assert state["brightnessMode"] == "default"


def test_buildLightState_noUnavailableReason_hasNoUnavailableReasonKey():
    """Present-path payloads never carry the key (byte-identical to before)."""
    assert "unavailableReason" not in buildLightState(lux=None, tsUtc=_T)
    assert "unavailableReason" not in buildLightState(lux=5.0, tsUtc=_T)


def test_handleSample_presenceAbsent_writesOnceWithSensorAbsent_noSampleNeeded():
    """
    Given: presence STATE ABSENT published, no light sample ever
    When: the bridge handles it (and a duplicate)
    Then: states/light is written ONCE: lux null, reasons.lux and
        unavailableReason sensor_absent, ts the presence sample's; presenceFault set
    """
    bridge = _RecordingBridge()
    assert bridge.presenceFault is None

    assert bridge.handleSample(_presence(ABSENT)) is True
    bridge.handleSample(_presence(ABSENT))

    assert len(bridge.writes) == 1
    written = bridge.writes[0]
    assert written == buildLightState(
        lux=None, tsUtc="2026-10-23T08:00:00Z",
        unavailableReason=LIGHT_REASON_SENSOR_ABSENT,
    )
    assert written["lux"] is None
    assert written["reasons"] == {"lux": "sensor_absent"}
    assert written["unavailableReason"] == "sensor_absent"
    assert bridge.presenceFault == "sensor_absent"


def test_handleSample_presencePresentThenBurst_payloadUnchanged_noFault():
    """
    Given: presence PRESENT, then one burst
    When: the bridge handles them
    Then: PRESENT writes nothing; the burst payload is exactly today's (no
        unavailableReason key); presenceFault stays None
    """
    bridge = _RecordingBridge()

    assert bridge.handleSample(_presence(PRESENT)) is True
    assert bridge.writes == []
    for sample in _burst(7, 120.5, (900, 300, 1200), (TSL_GAIN_MED, 100)):
        bridge.handleSample(sample)

    assert bridge.writes == [
        buildLightState(
            lux=120.5, tsUtc=_T, rawCounts=(900, 300, 1200),
            rangeContext=(TSL_GAIN_MED, 100),
        )
    ]
    assert "unavailableReason" not in bridge.writes[0]
    assert bridge.presenceFault is None


def _waitFor(target: Path) -> None:
    deadline = time.monotonic() + 3.0
    while not target.exists() and time.monotonic() < deadline:
        time.sleep(0.02)


def test_bridge_endToEnd_busPublishWritesStatesLight(tmp_path: Path):
    """
    Given: a bridge subscribed to a live SampleBus + its drain thread running
    When: a burst is published
    Then: states/light is written with the published burst (proves the drain path)
    """
    bus = SampleBus()
    sub = bus.subscribe(
        [TOPIC_LIGHT_LUX, TOPIC_LIGHT_RAW, TOPIC_LIGHT_RANGE], QoS.LOSSY, "light-state"
    )
    bridge = LightStateBridge(sub, str(tmp_path))
    bridge.start()
    try:
        for sample in _burst(1, 88.5, (900, 300, 1200), (TSL_GAIN_MED, 100)):
            bus.publish(sample)
        target = tmp_path / LIGHT_STATE_FILENAME
        _waitFor(target)
        assert target.exists()
        assert _readState(tmp_path)["lux"] == 88.5
    finally:
        bridge.stop()


# ---------------------------------------------------------- config factory gate


def _config(*, busEnabled: bool, lightEnabled: bool) -> dict:
    return {
        "pi": {
            "bus": {"enabled": busEnabled},
            "sensors": {"light": {"enabled": lightEnabled, "sampleHz": 1}},
            "splash": {"statesDir": "/run/eclipse-obd/states"},
        }
    }


def test_factory_subscribesToTheRetainedPresenceState(tmp_path: Path):
    """
    Given: the light reader has published its retained presence STATE ABSENT
    When: the factory builds the bridge and it drains its subscription
    Then: the replayed presence sample reaches the bridge: states/light is
        written with sensor_absent and presenceFault is set
    """
    bus = SampleBus()
    bus.publish(_presence(ABSENT), retain=True)
    cfg = _config(busEnabled=True, lightEnabled=True)
    cfg["pi"]["splash"]["statesDir"] = str(tmp_path)

    bridge = createLightStateBridgeFromConfig(cfg, bus)
    assert isinstance(bridge, LightStateBridge)
    sample = bridge._sub.poll()
    assert sample is not None and sample.topic == STATE_LIGHT
    assert bridge.handleSample(sample) is True

    assert _readState(tmp_path)["unavailableReason"] == "sensor_absent"
    assert bridge.presenceFault == "sensor_absent"


def test_factory_busOff_returnsNone():
    """The bridge ships dark: bus disabled -> nothing built."""
    bus = SampleBus()
    assert createLightStateBridgeFromConfig(
        _config(busEnabled=False, lightEnabled=True), bus
    ) is None


def test_factory_lightOff_returnsNone():
    """Light sensor disabled -> nothing built even with the bus on."""
    bus = SampleBus()
    assert createLightStateBridgeFromConfig(
        _config(busEnabled=True, lightEnabled=False), bus
    ) is None


def test_factory_bothOn_buildsBridgeSubscribedToTheWholeBurst(tmp_path: Path):
    """Bus + light both on -> a bridge draining lux, raw and range is built."""
    bus = SampleBus()
    cfg = _config(busEnabled=True, lightEnabled=True)
    cfg["pi"]["splash"]["statesDir"] = str(tmp_path)

    bridge = createLightStateBridgeFromConfig(cfg, bus)

    assert isinstance(bridge, LightStateBridge)
    bridge.start()
    try:
        for sample in _burst(1, 7.25, (900, 300, 1200), (TSL_GAIN_LOW, 100)):
            bus.publish(sample)
        target = tmp_path / LIGHT_STATE_FILENAME
        _waitFor(target)
        state = _readState(tmp_path)
        assert state["lux"] == 7.25
        assert state["gain"] == "low"
        assert state["integrationMs"] == 100
    finally:
        bridge.stop()


def test_bridgeHoldsNoTopicCopy():
    """The topic strings come from sensor_reader, the producer-side SSOT."""
    import pi.sensors.light_state_bridge as bridgeModule

    source = Path(bridgeModule.__file__).read_text(encoding="utf-8")

    assert '"raw.light.' not in source
    assert "TOPIC_LIGHT_LUX" not in bridgeModule.__all__


# -------------------------------------------- autoDim re-read (US-878-b, Atlas B)

# A lux inside the curve, so luxFull changes the level.
_PROBE_LUX = 100.0


class _Clock:
    """A fake monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _writeJson(path: Path, payload: dict, *, mtimeNs: int) -> None:
    """Write ``payload`` and pin the file's mtime (no clock-tick flakiness)."""
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(path, ns=(mtimeNs, mtimeNs))


def _autoDimConfig(luxFull: float) -> dict:
    return {"pi": {"display": {"autoDim": {"luxFull": luxFull}}}}


def _levelFor(luxFull: float) -> float:
    return brightnessLevel(_PROBE_LUX, {"luxFull": luxFull})


def _burstLevel(bridge: _RecordingBridge, seq: int) -> float:
    for sample in _burst(seq, _PROBE_LUX, (900, 300, 1200), (TSL_GAIN_MED, 100)):
        bridge.handleSample(sample)
    return bridge.writes[-1]["brightnessLevel"]


class _ConfiguredBridge(_RecordingBridge):
    """The real bridge bound to a config path and a fake clock."""

    def __init__(self, configPath: str | None, clock: _Clock, autoDim: dict) -> None:
        LightStateBridge.__init__(
            self, None, "unused", autoDim=autoDim, configPath=configPath, monotonicFn=clock,
        )
        self.writes = []


def test_configJsonLuxFullChange_reReadAfterOneSecond_notAtHalf(tmp_path: Path):
    """
    Given: a bridge started on luxFull 1000 with config.json at that value
    When: config.json is rewritten with luxFull 500 and a burst is fed at
        +0.5 s, then at +1.1 s on the fake clock
    Then: the 0.5 s burst still uses 1000; the 1.1 s burst uses 500
    """
    configPath = tmp_path / "config.json"
    _writeJson(configPath, _autoDimConfig(1000.0), mtimeNs=1_000_000_000)
    clock = _Clock()
    bridge = _ConfiguredBridge(str(configPath), clock, {"luxFull": 1000.0})

    _writeJson(configPath, _autoDimConfig(500.0), mtimeNs=2_000_000_000)
    clock.now = 0.5
    atHalf = _burstLevel(bridge, 1)
    clock.now = 1.1
    atOnePointOne = _burstLevel(bridge, 2)

    assert atHalf == _levelFor(1000.0)
    assert atOnePointOne == _levelFor(500.0)
    assert _levelFor(500.0) != _levelFor(1000.0)


def test_luxFullInConfigLocalJsonOnly_isApplied(tmp_path: Path):
    """
    Given: config.json carries luxFull 1000
    When: config.local.json alone sets pi.display.autoDim.luxFull 500 and the
        mtime check runs
    Then: APPLIED -- the next burst uses 500 (US-895-b: the CIO reversed Atlas
        ruling B 2026-10-19, so luxFull is in the overlay allow-list)
    """
    # MOVED PIN (US-895-b): was test_luxFullInConfigLocalJsonOnly_isIgnored.
    configPath = tmp_path / "config.json"
    _writeJson(configPath, _autoDimConfig(1000.0), mtimeNs=1_000_000_000)
    clock = _Clock()
    bridge = _ConfiguredBridge(str(configPath), clock, {"luxFull": 1000.0})

    _writeJson(
        tmp_path / "config.local.json",
        {"pi.display.autoDim.luxFull": 500.0},
        mtimeNs=2_000_000_000,
    )
    clock.now = 1.1

    assert _burstLevel(bridge, 1) == _levelFor(500.0)
    assert bridge.autoDim["luxFull"] == 500.0


def test_aCrossingLuxFullInConfigLocalJson_isDropped_withTheRuleNamed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """
    Given: config.json carries luxMin 3, luxFull 1000
    When: config.local.json alone sets luxFull 2 (below luxMin) and the mtime
        check runs
    Then: the bridge keeps the config.json luxFull, and exactly one WARNING
        names the rule 'luxFull > luxMin' (US-895-b, Atlas S110 r2)
    """
    configPath = tmp_path / "config.json"
    _writeJson(
        configPath,
        {"pi": {"display": {"autoDim": {"luxMin": 3.0, "luxFull": 1000.0}}}},
        mtimeNs=1_000_000_000,
    )
    clock = _Clock()
    bridge = _ConfiguredBridge(str(configPath), clock, {"luxMin": 3.0, "luxFull": 1000.0})

    _writeJson(
        tmp_path / "config.local.json",
        {"pi.display.autoDim.luxFull": 2.0},
        mtimeNs=2_000_000_000,
    )
    clock.now = 1.1
    with caplog.at_level(logging.WARNING):
        _burstLevel(bridge, 1)

    assert bridge.autoDim["luxFull"] == 1000.0
    named = [r for r in caplog.records if "luxFull > luxMin" in r.getMessage()]
    assert len(named) == 1


def test_noConfigPath_startConfigStands(tmp_path: Path):
    """configPath None -> no re-read: a later config.json change is not seen."""
    configPath = tmp_path / "config.json"
    _writeJson(configPath, _autoDimConfig(1000.0), mtimeNs=1_000_000_000)
    clock = _Clock()
    bridge = _ConfiguredBridge(None, clock, {"luxFull": 1000.0})

    _writeJson(configPath, _autoDimConfig(500.0), mtimeNs=2_000_000_000)
    clock.now = 5.0

    assert _burstLevel(bridge, 1) == _levelFor(1000.0)


def test_malformedConfigJson_keepsCurrent_retriesOnTheNextCheck(tmp_path: Path):
    """
    Given: config.json is caught half-written (malformed JSON)
    When: the check runs, then the file is completed and the next check runs
    Then: the first keeps the current autoDim; the second picks up the value
    """
    configPath = tmp_path / "config.json"
    _writeJson(configPath, _autoDimConfig(1000.0), mtimeNs=1_000_000_000)
    clock = _Clock()
    bridge = _ConfiguredBridge(str(configPath), clock, {"luxFull": 1000.0})

    configPath.write_text('{"pi": {"display"', encoding="utf-8")
    os.utime(configPath, ns=(2_000_000_000, 2_000_000_000))
    clock.now = 1.1
    assert _burstLevel(bridge, 1) == _levelFor(1000.0)

    # Same mtime as the failed read: a retry must not depend on a new mtime.
    configPath.write_text(json.dumps(_autoDimConfig(500.0)), encoding="utf-8")
    os.utime(configPath, ns=(2_000_000_000, 2_000_000_000))
    clock.now = 2.2
    assert _burstLevel(bridge, 2) == _levelFor(500.0)


def test_factory_startAutoDim_isTheConfigSection():
    """The factory hands the bridge the config's pi.display.autoDim."""
    cfg = _config(busEnabled=True, lightEnabled=True)
    cfg["pi"]["display"] = {"autoDim": {"luxFull": 500.0, "curve": "linear"}}

    bridge = createLightStateBridgeFromConfig(cfg, SampleBus())

    assert bridge is not None
    assert bridge.autoDim["luxFull"] == 500.0
    assert bridge.autoDim["curve"] == "linear"
    assert bridge.autoDim["minLevel"] == 0.15


class _StubStartable:
    def start(self) -> None:
        pass

    def stop(self, *args: object) -> None:
        pass


def test_lifecycleWiring_realFactory_picksUpConfigLocalJsonChangeAfterOneSecond(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    Given: the bridge built by the REAL lifecycle._startEdrSensorPath through
        the real factory, with the host's _configPath
    When: config.json's luxFull is changed with its mtime held (so only a
        config.local.json change can reveal it), then config.local.json is
        written and the fake clock passes 1 s
    Then: the factory received the host's config path, and the bridge
        re-reads on the config.local.json change: luxFull 500 is used after
        1 s, not before
    """
    import pi.bus.edr_persistence_subscriber as edrSub
    import pi.sensors.imu_state_bridge as imuBridge
    import pi.sensors.light_state_bridge as lightBridge
    import pi.sensors.sensor_reader as sensorReader
    from pi.obdii.orchestrator.lifecycle import LifecycleMixin

    configPath = tmp_path / "config.json"
    _writeJson(configPath, _autoDimConfig(1000.0), mtimeNs=1_000_000_000)
    clock = _Clock()
    realFactory = lightBridge.createLightStateBridgeFromConfig
    seen: dict = {}

    def _factory(config, bus, **kwargs):
        seen.update(kwargs)
        return realFactory(config, bus, monotonicFn=clock, **kwargs)

    monkeypatch.setattr(sensorReader, "createSensorReadersFromConfig", lambda c, b: [_StubStartable()])
    monkeypatch.setattr(
        edrSub, "createEdrPersistenceSubscriberFromConfig", lambda *a, **k: _StubStartable()
    )
    monkeypatch.setattr(imuBridge, "createImuStateBridgeFromConfig", lambda c, b: None)
    monkeypatch.setattr(lightBridge, "createLightStateBridgeFromConfig", _factory)

    cfg = _config(busEnabled=True, lightEnabled=True)
    cfg["pi"]["splash"]["statesDir"] = str(tmp_path / "states")
    cfg["pi"]["display"] = {"autoDim": {"luxFull": 1000.0}}
    host = SimpleNamespace(
        _config=cfg, _database=None, _driveDetector=None, _configPath=str(configPath),
    )
    LifecycleMixin._startEdrSensorPath(host, SampleBus())  # type: ignore[arg-type]
    bridge = host._lightStateBridge
    assert isinstance(bridge, LightStateBridge)
    try:
        assert seen["configPath"] == str(configPath)
        _writeJson(configPath, _autoDimConfig(500.0), mtimeNs=1_000_000_000)
        _writeJson(
            tmp_path / "config.local.json",
            {"pi.calibration.mode": True},
            mtimeNs=2_000_000_000,
        )

        recorder = []
        monkeypatch.setattr(bridge, "_writeState", recorder.append)
        clock.now = 0.5
        for sample in _burst(1, _PROBE_LUX, (900, 300, 1200), (TSL_GAIN_MED, 100)):
            bridge.handleSample(sample)
        clock.now = 1.1
        for sample in _burst(2, _PROBE_LUX, (900, 300, 1200), (TSL_GAIN_MED, 100)):
            bridge.handleSample(sample)

        assert recorder[0]["brightnessLevel"] == _levelFor(1000.0)
        assert recorder[1]["brightnessLevel"] == _levelFor(500.0)
    finally:
        bridge.stop()
