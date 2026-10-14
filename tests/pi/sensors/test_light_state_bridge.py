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
# Author: Rex (US-483-a)
# Creation Date: 2026-07-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Unit tests for the light-state bridge (one reader burst -> states/light)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from pi.bus.bus import SampleBus
from pi.bus.sample import QoS, Sample
from pi.sensors.light_state_bridge import (
    LIGHT_STATE_FILENAME,
    LightStateBridge,
    brightnessLevel,
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
    "channelAtLimit", "brightnessLevel", "brightnessMode", "ts",
}

# Validator-default levels for the lux values the exact pins below use (the
# curve itself is pinned by tests/pi/sensors/test_brightness_golden.py).
_LEVEL_120_5 = 0.635728449174043
_LEVEL_80 = brightnessLevel(80.0, None)


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
        "gain": "med", "integrationMs": 100, "channelAtLimit": False,
        "brightnessLevel": _LEVEL_120_5, "brightnessMode": "auto", "ts": _T,
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
        "gain": None, "integrationMs": None, "channelAtLimit": None,
        "brightnessLevel": _LEVEL_80, "brightnessMode": "auto", "ts": seq8,
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


def test_luxFullInConfigLocalJsonOnly_isIgnored(tmp_path: Path):
    """
    Given: config.json carries luxFull 1000
    When: config.local.json alone sets pi.display.autoDim.luxFull 500 and the
        mtime check runs
    Then: IGNORED -- the bridge keeps the config.json value (autoDim is not
        in the overlay allow-list; Atlas ruled B)
    """
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

    assert _burstLevel(bridge, 1) == _levelFor(1000.0)
    assert bridge.autoDim["luxFull"] == 1000.0


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
