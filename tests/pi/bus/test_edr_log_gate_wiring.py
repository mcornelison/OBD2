################################################################################
# File Name: test_edr_log_gate_wiring.py
# Purpose/Description: US-767-b -- the EDR log gate is REACHED by production as a
#                      pass-through: lifecycle._startEdrSensorPath builds an
#                      EdrLogGate with enabled False and hands it to the EDR
#                      subscriber, which routes every row through admit(). A run
#                      through that production path writes byte-identical rows
#                      to a subscriber built with no gate at all. US-767-c
#                      supplies the link signal and turns the gate on.
# Author: Rex (US-767-b)
# Creation Date: 2026-09-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-18    | Rex (US-767-b) | Initial -- pass-through wiring, routing.
# 2026-09-18    | Rex (US-767-c) | Fixture sets logGate.enabled false (the
#               |                | lifecycle now honours it) and a tmp statesDir.
# 2026-09-21    | Rex (US-793-b) | Routing test drives the gate by reachability.
# 2026-10-14    | Rex (US-900)   | Replay feeder takes the readers' place.
# ================================================================================
################################################################################
"""Tests for the EdrLogGate pass-through wiring (US-767-b)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pi.bus.bus import SampleBus
from pi.bus.edr_log_gate import GATE_CLOSED, GATE_OPEN, EdrLogGate
from pi.bus.edr_persistence_subscriber import (
    EdrPersistenceSubscriber,
    createEdrPersistenceSubscriberFromConfig,
)
from pi.bus.sample import Sample
from pi.obdii.database import ObdDatabase
from pi.obdii.orchestrator.lifecycle import LifecycleMixin


def _db(tmp_path: Path, name: str) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / name), walMode=False)
    db.initialize()
    return db


# ARCH-064d: persistence is a UTC grid keyed on tsCapture, so the fixture is
# stamped at the 50 Hz it claims (it was float(seq): 1 Hz). +5 ms keeps each
# burst clear of a slot boundary; the offset is pinned so the phase is fixed.
_PERIOD_S = 1.0 / 50
_PHASE_S = 0.005


@pytest.fixture(autouse=True)
def _pinWallClockOffset(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setattr(sys.modules[EdrPersistenceSubscriber.__module__], "_wallClockOffsetS", lambda: 0.0)


def _sample(topic: str, value: Any, seq: int) -> Sample:
    return Sample(
        topic=topic, source=topic.split(".")[1], value=value, unit="x",
        tsUtc=f"2026-09-18T12:00:{seq % 60:02d}Z", tsCapture=seq * _PERIOD_S + _PHASE_S,
        driveId=None, dataSource="real", seq=seq,
    )


def _run(sub: EdrPersistenceSubscriber, bursts: int) -> None:
    """Feed ``bursts`` IMU bursts and a light burst every 50th seq."""
    for seq in range(bursts):
        sub.handleSample(_sample("raw.imu.accel", (1.0, 2.0, float(seq)), seq))
        sub.handleSample(_sample("raw.imu.gyro", (4.0, 5.0, 6.0), seq))
        sub.handleSample(_sample("raw.imu.mag", (7.0, 8.0, 9.0), seq))
        sub.handleSample(_sample("raw.imu.temp", 25.0, seq))
        if seq % 50 == 0:
            sub.handleSample(_sample("raw.light.lux", 10.0 + seq, seq))
            sub.handleSample(_sample("raw.light.raw", (1, 2, 3), seq))
            sub.handleSample(_sample("raw.light.range", (0x10, 100), seq))


def _rows(db: ObdDatabase) -> tuple[list, list]:
    with db.connect() as conn:
        imu = [tuple(r) for r in conn.execute("SELECT * FROM edr_imu_sample ORDER BY id")]
        light = [tuple(r) for r in conn.execute("SELECT * FROM edr_light_sample ORDER BY id")]
    return imu, light


def _config(*, gateEnabled: bool = True, statesDir: str | None = None) -> dict:
    config: dict = {"pi": {"bus": {"enabled": True}, "sensors": {
        "imu": {"enabled": True, "sampleHz": 50, "persistHz": 25},
        "light": {"enabled": True, "sampleHz": 1},
        "retentionDays": 45,
        "logGate": {"enabled": gateEnabled, "preRollSec": 45, "holdSec": 200},
    }}}
    if statesDir is not None:
        config["pi"]["splash"] = {"statesDir": statesDir}
    return config


class _Reader:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


@pytest.fixture()
def lifecycleSubscriber(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Run the REAL lifecycle._startEdrSensorPath with hardware stubbed out.

    pi.sensors.logGate.enabled is false here: the pass-through path US-767-b
    built is still what a config with the gate switched off gets (US-767-c's
    enabled path is tested in test_edr_log_gate_live.py).
    """
    import pi.sensors.imu_state_bridge as imuBridge
    import pi.sensors.light_state_bridge as lightBridge
    import pi.sensors.sensor_reader as sensorReader

    monkeypatch.setattr(sensorReader, "createSensorReadersFromConfig", lambda c, b: [_Reader()])
    monkeypatch.setattr(lightBridge, "createLightStateBridgeFromConfig", lambda c, b, **kw: None)
    monkeypatch.setattr(imuBridge, "createImuStateBridgeFromConfig", lambda c, b: None)

    host = SimpleNamespace(
        _config=_config(gateEnabled=False, statesDir=str(tmp_path / "states")),
        _database=_db(tmp_path, "lifecycle.db"), _driveDetector=None,
    )
    LifecycleMixin._startEdrSensorPath(host, SampleBus())  # type: ignore[arg-type]
    sub = getattr(host, "_edrPersistenceSubscriber", None)
    assert sub is not None, "lifecycle did not build the EDR subscriber"
    yield sub, host._database
    sub.stop()


class TestLifecyclePassThrough:
    def test_lifecycle_handsAGateToTheSubscriber_disabled(self, lifecycleSubscriber) -> None:
        """
        Given: the production EDR start path with pi.sensors.logGate.enabled false
        When: it builds the subscriber
        Then: the subscriber holds an EdrLogGate that is disabled (always OPEN)
            with the configured windows
        """
        sub, _ = lifecycleSubscriber
        gate = sub._logGate  # noqa: SLF001 -- the wiring IS the assertion
        assert isinstance(gate, EdrLogGate)
        assert gate.enabled is False
        assert gate.state == GATE_OPEN
        assert gate.preRollSec == 45.0
        assert gate.holdSec == 200.0

    def test_lifecycleRun_rowsByteIdenticalToNoGate(
        self, lifecycleSubscriber, tmp_path: Path
    ) -> None:
        """
        Given: the lifecycle-built (gated, pass-through) subscriber and a
            subscriber built with no gate at all
        When: both are fed the same run
        Then: both EDR tables are byte-identical, row for row
        """
        sub, gatedDb = lifecycleSubscriber
        plainDb = _db(tmp_path, "plain.db")
        plain = EdrPersistenceSubscriber(None, plainDb, imuSampleHz=50, imuPersistHz=25)

        _run(sub, 500)
        _run(plain, 500)
        sub.flushPending()
        plain.flushPending()
        sub.closeWriteConnection()
        plain.closeWriteConnection()

        gatedImu, gatedLight = _rows(gatedDb)
        plainImu, plainLight = _rows(plainDb)
        assert len(plainImu) == 250  # 50 Hz -> 25 Hz decimation
        assert len(plainLight) == 10
        assert gatedImu == plainImu
        assert gatedLight == plainLight


class TestSubscriberRouting:
    def test_factory_passesTheGateThrough(self, tmp_path: Path) -> None:
        """The factory hands the given gate to the subscriber unchanged."""
        gate = EdrLogGate(None)

        class _Bus:
            def subscribe(self, *a: Any, **k: Any) -> None:
                return None

        sub = createEdrPersistenceSubscriberFromConfig(
            _config(), _Bus(), _db(tmp_path, "f.db"), logGate=gate
        )
        assert sub is not None and sub._logGate is gate  # noqa: SLF001

    def test_enabledClosedGate_writesNothing_thenFlushesPreRollInOrder(
        self, tmp_path: Path
    ) -> None:
        """
        Given: a subscriber whose gate is enabled, the link up, the ECU silent
        When: rows arrive, then the ECU answers
        Then: nothing lands while CLOSED; on opening the buffered rows land in
            order, before the live one
        """
        db = _db(tmp_path, "route.db")
        clock = [0.0]
        link = SimpleNamespace(connected=True, reachability="did_not_answer")
        gate = EdrLogGate(lambda: link, enabled=True, monotonicFn=lambda: clock[0])
        sub = EdrPersistenceSubscriber(None, db, imuSampleHz=50, imuPersistHz=50, logGate=gate)

        _run(sub, 3)
        sub.flushPending()
        assert _rows(db) == ([], [])
        assert gate.state == GATE_CLOSED

        link.reachability = "answered"
        clock[0] = 1.0
        sub.handleSample(_sample("raw.light.lux", 99.0, 3))
        sub.flushPending()
        sub.closeWriteConnection()

        imu, light = _rows(db)
        assert [r[3] for r in imu] == [0, 1, 2]  # seq column, in order
        assert [r[3] for r in light] == [0, 3]


class TestReplayFeederWiring:
    """US-900: in replay mode the feeder takes the hardware readers' place."""

    @pytest.fixture()
    def stubs(self, monkeypatch: pytest.MonkeyPatch) -> dict:
        import pi.sensors.imu_state_bridge as imuBridge
        import pi.sensors.light_state_bridge as lightBridge
        import pi.sensors.replay_feeder as replayFeeder
        import pi.sensors.sensor_reader as sensorReader

        calls: dict = {"readers": 0, "feeder": 0, "reader": _Reader(), "feederObj": _Reader()}

        def _readers(c: dict, b: Any) -> list:
            calls["readers"] += 1
            return [calls["reader"]]

        def _feeder(c: dict, b: Any) -> Any:
            calls["feeder"] += 1
            return calls["feederObj"]

        monkeypatch.setattr(sensorReader, "createSensorReadersFromConfig", _readers)
        monkeypatch.setattr(replayFeeder, "createSensorReplayFeederFromConfig", _feeder)
        monkeypatch.setattr(lightBridge, "createLightStateBridgeFromConfig", lambda c, b, **kw: None)
        monkeypatch.setattr(imuBridge, "createImuStateBridgeFromConfig", lambda c, b: None)
        return calls

    def _host(self, tmp_path: Path, *, replayActive: bool | None) -> SimpleNamespace:
        config = _config(gateEnabled=False, statesDir=str(tmp_path / "states"))
        if replayActive is not None:
            config["pi"]["replay"] = {"active": replayActive}
        return SimpleNamespace(
            _config=config, _database=_db(tmp_path, "lifecycle.db"), _driveDetector=None,
        )

    def test_replayActive_startsTheFeederInsteadOfTheReaders(
        self, tmp_path: Path, stubs: dict
    ) -> None:
        """
        Given: pi.replay.active true
        When: the production EDR start path runs
        Then: the replay feeder is built and started in the readers' place, the
            hardware readers are never built, and the EDR subscriber still runs
        """
        host = self._host(tmp_path, replayActive=True)
        LifecycleMixin._startEdrSensorPath(host, SampleBus())  # type: ignore[arg-type]

        assert stubs["readers"] == 0
        assert stubs["feeder"] == 1
        assert stubs["feederObj"].started is True
        assert host._sensorReaders == [stubs["feederObj"]]
        assert host._edrPersistenceSubscriber is not None
        host._edrPersistenceSubscriber.stop()

    @pytest.mark.parametrize("replayActive", [False, None])
    def test_replayInactive_pathUnchanged_readersStart(
        self, tmp_path: Path, stubs: dict, replayActive: bool | None
    ) -> None:
        """With pi.replay.active false or absent the readers start as before."""
        host = self._host(tmp_path, replayActive=replayActive)
        LifecycleMixin._startEdrSensorPath(host, SampleBus())  # type: ignore[arg-type]

        assert stubs["feeder"] == 0
        assert stubs["readers"] == 1
        assert host._sensorReaders == [stubs["reader"]]
        host._edrPersistenceSubscriber.stop()

    def test_replayActive_noSensorToReplay_shipsDark(
        self, tmp_path: Path, stubs: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No feeder (nothing enabled to replay) -> nothing built, as with no readers."""
        import pi.sensors.replay_feeder as replayFeeder

        monkeypatch.setattr(replayFeeder, "createSensorReplayFeederFromConfig", lambda c, b: None)
        host = self._host(tmp_path, replayActive=True)
        LifecycleMixin._startEdrSensorPath(host, SampleBus())  # type: ignore[arg-type]

        assert stubs["readers"] == 0
        assert getattr(host, "_edrPersistenceSubscriber", None) is None
