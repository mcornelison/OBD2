################################################################################
# File Name: test_light_state_bridge.py
# Purpose/Description: Unit tests for the light -> states/light bridge (US-483-a,
#     F-121). Drains raw.light.lux off the F-110 SampleBus and mirrors it into the
#     dashboard states/light file ({lux, ts}), the pure-consumer state file the
#     US-483-b brightness consumer reads (Atlas DELTA-2). Honest-instrument: a
#     saturated read (lux=None) is written as JSON null, never inf/fabricated; the
#     freshness ts is the sample's own read-time so a dead feed goes honestly
#     stale. Gated behind pi.bus.enabled + pi.sensors.light.enabled (ships dark).
# Author: Rex (US-483-a)
# Creation Date: 2026-07-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Unit tests for the light-state bridge (bus raw.light.lux -> states/light)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from pi.bus.bus import SampleBus
from pi.bus.sample import QoS, Sample
from pi.sensors.light_state_bridge import (
    LIGHT_STATE_FILENAME,
    LightStateBridge,
    buildLightState,
    createLightStateBridgeFromConfig,
)


def _lux(value, seq: int = 1, *, ts: str = "2026-07-22T00:00:00Z") -> Sample:
    """Build one raw.light.lux sample carrying ``value`` (float or None)."""
    return Sample(
        topic="raw.light.lux",
        source="light",
        value=value,
        unit="lux",
        tsUtc=ts,
        tsCapture=float(seq),
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _readState(statesDir: Path) -> dict:
    """Load the written states/light JSON."""
    return json.loads((statesDir / LIGHT_STATE_FILENAME).read_text(encoding="utf-8"))


# --------------------------------------------------------------- buildLightState


def test_buildLightState_realReading_carriesFloatLuxAndTs():
    """
    Given: a real lux reading + a read-time ts
    When: buildLightState assembles the payload
    Then: it is exactly {lux: <float>, ts: <ts>}
    """
    state = buildLightState(lux=123.5, tsUtc="2026-07-22T01:02:03Z")

    assert state == {"lux": 123.5, "ts": "2026-07-22T01:02:03Z"}
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


# ----------------------------------------------------------- handleSample write


def test_handleSample_luxTopic_writesStatesLightAtomically(tmp_path: Path):
    """
    Given: a bridge bound to a states dir
    When: a raw.light.lux sample is handled
    Then: states/light holds {lux, ts} with the sample's read-time ts
    """
    bridge = LightStateBridge(None, str(tmp_path))

    handled = bridge.handleSample(_lux(42.0, ts="2026-07-22T05:06:07Z"))

    assert handled is True
    state = _readState(tmp_path)
    assert state["lux"] == 42.0
    assert state["ts"] == "2026-07-22T05:06:07Z"


def test_handleSample_saturated_writesNullLux(tmp_path: Path):
    """
    Given: a saturated lux sample (value=None)
    When: it is handled
    Then: states/light lux is null (honest), file still written + fresh ts
    """
    bridge = LightStateBridge(None, str(tmp_path))

    bridge.handleSample(_lux(None))

    state = _readState(tmp_path)
    assert state["lux"] is None
    assert state["ts"] == "2026-07-22T00:00:00Z"


def test_handleSample_nonLightTopic_ignoredNoWrite(tmp_path: Path):
    """
    Given: a non-lux topic (raw.light.raw / raw.obd.*) reaches the bridge
    When: it is handled
    Then: it is ignored (False) and no states/light file is written
    """
    bridge = LightStateBridge(None, str(tmp_path))

    raw = Sample(
        topic="raw.light.raw", source="light", value=(1, 2, 3), unit="count",
        tsUtc="t", tsCapture=1.0, driveId=None, dataSource="real", seq=1,
    )
    obd = Sample(
        topic="raw.obd.RPM", source="obd", value=800.0, unit="rpm",
        tsUtc="t", tsCapture=1.0, driveId=None, dataSource="real", seq=1,
    )

    assert bridge.handleSample(raw) is False
    assert bridge.handleSample(obd) is False
    assert not (tmp_path / LIGHT_STATE_FILENAME).exists()


# ------------------------------------------------------------- end-to-end (bus)


def test_bridge_endToEnd_busPublishWritesStatesLight(tmp_path: Path):
    """
    Given: a bridge subscribed to a live SampleBus + its drain thread running
    When: a raw.light.lux sample is published
    Then: states/light is written with the published lux (proves the drain path)
    """
    bus = SampleBus()
    sub = bus.subscribe(["raw.light.lux"], QoS.LOSSY, "light-state")
    bridge = LightStateBridge(sub, str(tmp_path))
    bridge.start()
    try:
        bus.publish(_lux(88.5, ts="2026-07-22T09:09:09Z"))
        target = tmp_path / LIGHT_STATE_FILENAME
        deadline = time.monotonic() + 3.0
        while not target.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
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


def test_factory_bothOn_buildsBridgeSubscribedToLux(tmp_path: Path):
    """Bus + light both on -> a bridge subscribed to raw.light.lux is built."""
    bus = SampleBus()
    cfg = _config(busEnabled=True, lightEnabled=True)
    cfg["pi"]["splash"]["statesDir"] = str(tmp_path)

    bridge = createLightStateBridgeFromConfig(cfg, bus)

    assert isinstance(bridge, LightStateBridge)
    bridge.start()
    try:
        bus.publish(_lux(7.25))
        target = tmp_path / LIGHT_STATE_FILENAME
        deadline = time.monotonic() + 3.0
        while not target.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert _readState(tmp_path)["lux"] == 7.25
    finally:
        bridge.stop()
