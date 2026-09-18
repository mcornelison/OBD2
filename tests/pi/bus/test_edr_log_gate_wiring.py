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


def _sample(topic: str, value: Any, seq: int) -> Sample:
    return Sample(
        topic=topic, source=topic.split(".")[1], value=value, unit="x",
        tsUtc=f"2026-09-18T12:00:{seq % 60:02d}Z", tsCapture=float(seq),
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


def _config() -> dict:
    return {"pi": {"bus": {"enabled": True}, "sensors": {
        "imu": {"enabled": True, "sampleHz": 50, "persistHz": 25},
        "light": {"enabled": True, "sampleHz": 1},
        "retentionDays": 45,
        "logGate": {"enabled": True, "preRollSec": 45, "holdSec": 200},
    }}}


class _Reader:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


@pytest.fixture()
def lifecycleSubscriber(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Run the REAL lifecycle._startEdrSensorPath with hardware stubbed out."""
    import pi.sensors.imu_state_bridge as imuBridge
    import pi.sensors.light_state_bridge as lightBridge
    import pi.sensors.sensor_reader as sensorReader

    monkeypatch.setattr(sensorReader, "createSensorReadersFromConfig", lambda c, b: [_Reader()])
    monkeypatch.setattr(lightBridge, "createLightStateBridgeFromConfig", lambda c, b: None)
    monkeypatch.setattr(imuBridge, "createImuStateBridgeFromConfig", lambda c, b: None)

    host = SimpleNamespace(
        _config=_config(), _database=_db(tmp_path, "lifecycle.db"), _driveDetector=None,
    )
    LifecycleMixin._startEdrSensorPath(host, SampleBus())  # type: ignore[arg-type]
    sub = getattr(host, "_edrPersistenceSubscriber", None)
    assert sub is not None, "lifecycle did not build the EDR subscriber"
    yield sub, host._database
    sub.stop()


class TestLifecyclePassThrough:
    def test_lifecycle_handsAGateToTheSubscriber_disabled(self, lifecycleSubscriber) -> None:
        """
        Given: the production EDR start path with pi.sensors.logGate in config
        When: it builds the subscriber
        Then: the subscriber holds an EdrLogGate that is disabled (always OPEN)
            with the configured windows -- US-767-c turns it on
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
        Given: a subscriber whose gate is enabled and the link genuinely down
        When: rows arrive, then the link opens
        Then: nothing lands while CLOSED; on opening the buffered rows land in
            order, before the live one
        """
        db = _db(tmp_path, "route.db")
        clock = [0.0]
        link = SimpleNamespace(connected=False, signalReadable=True)
        gate = EdrLogGate(lambda: link, enabled=True, monotonicFn=lambda: clock[0])
        sub = EdrPersistenceSubscriber(None, db, imuSampleHz=50, imuPersistHz=50, logGate=gate)

        _run(sub, 3)
        sub.flushPending()
        assert _rows(db) == ([], [])
        assert gate.state == GATE_CLOSED

        link.connected = True
        clock[0] = 1.0
        sub.handleSample(_sample("raw.light.lux", 99.0, 3))
        sub.flushPending()
        sub.closeWriteConnection()

        imu, light = _rows(db)
        assert [r[3] for r in imu] == [0, 1, 2]  # seq column, in order
        assert [r[3] for r in light] == [0, 3]
