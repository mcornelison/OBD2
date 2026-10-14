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
# Author: Rex (US-483-a)
# Creation Date: 2026-07-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Unit tests for the light-state bridge (one reader burst -> states/light)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from pi.bus.bus import SampleBus
from pi.bus.sample import QoS, Sample
from pi.sensors.light_state_bridge import (
    LIGHT_STATE_FILENAME,
    LightStateBridge,
    buildLightState,
    createLightStateBridgeFromConfig,
)
from pi.sensors.sensor_reader import (
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

_STATE_KEYS = {
    "lux", "visibleCount", "irCount", "fullCount", "gain", "integrationMs",
    "channelAtLimit", "ts",
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
}


def test_fixture_namesEveryRequiredCase():
    """The fixture is an object of the four named states/light payloads."""
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

    assert bridge.writes == [{
        "lux": 120.5, "visibleCount": 900, "irCount": 300, "fullCount": 1200,
        "gain": "med", "integrationMs": 100, "channelAtLimit": False, "ts": _T,
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
    assert bridge.writes[1] == {
        "lux": 80.0, "visibleCount": 600, "irCount": 200, "fullCount": 800,
        "gain": None, "integrationMs": None, "channelAtLimit": None, "ts": seq8,
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
