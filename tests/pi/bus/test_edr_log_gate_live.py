################################################################################
# File Name: test_edr_log_gate_live.py
# Purpose/Description: US-767-c -- the live EDR path uses the log gate.
#                      lifecycle._startEdrSensorPath hands the gate a lazy
#                      callable over ObdConnection.getStatus() (the PRODUCER, a
#                      real ObdConnection here with only python-obd faked), honours
#                      pi.sensors.logGate.enabled, and the subscriber publishes the
#                      gate's state to states/edr-log-gate. Includes the mutation
#                      test for the fail-OPEN branch.
# Author: Rex (US-767-c)
# Creation Date: 2026-09-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-18    | Rex (US-767-c) | Initial -- live signal, publish, mutation.
# ================================================================================
################################################################################
"""Tests for the live EDR log gate (US-767-c)."""

from __future__ import annotations

import builtins
import inspect
import json
import logging
import types
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import pi.bus.edr_log_gate as edrLogGateModule
from pi.bus.bus import SampleBus
from pi.bus.edr_log_gate import GATE_CLOSED, GATE_HOLD, GATE_OPEN, EdrLogGate
from pi.bus.edr_persistence_subscriber import (
    EDR_LOG_GATE_STATE_FILENAME,
    EdrPersistenceSubscriber,
)
from pi.bus.sample import Sample
from pi.obdii.database import ObdDatabase
from pi.obdii.obd_connection import ObdConnection
from pi.obdii.orchestrator.lifecycle import LifecycleMixin

# 500 bursts at a 50 Hz bus decimated to 25 Hz persist, light every 50th seq.
_BURSTS = 500
_EXPECTED_IMU_ROWS = 250
_EXPECTED_LIGHT_ROWS = 10

# The fail-OPEN return in EdrLogGate._readLink, and its deliberate inversion.
_FAIL_OPEN_LINE = 'return True, "signal_unreadable"'
_FAIL_CLOSED_LINE = 'return False, "signal_unreadable"'


class _FakeObd:
    """A python-obd double whose ``is_connected()`` returns or raises."""

    def __init__(self, result: Any) -> None:
        self.result = result

    def is_connected(self) -> bool:
        if isinstance(self.result, BaseException):
            raise self.result
        return bool(self.result)


def _connection(result: Any) -> ObdConnection:
    """A REAL ObdConnection (the producer) over a faked python-obd object."""
    conn = ObdConnection({"pi": {"bluetooth": {"macAddress": "00:11:22:33:44:55"}}})
    conn.obd = _FakeObd(result)
    return conn


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


def _run(sub: EdrPersistenceSubscriber, bursts: int = _BURSTS, start: int = 0) -> None:
    """Feed IMU bursts and a light burst every 50th seq, then flush."""
    for seq in range(start, start + bursts):
        sub.handleSample(_sample("raw.imu.accel", (1.0, 2.0, float(seq)), seq))
        sub.handleSample(_sample("raw.imu.gyro", (4.0, 5.0, 6.0), seq))
        sub.handleSample(_sample("raw.imu.mag", (7.0, 8.0, 9.0), seq))
        sub.handleSample(_sample("raw.imu.temp", 25.0, seq))
        if seq % 50 == 0:
            sub.handleSample(_sample("raw.light.lux", 10.0 + seq, seq))
            sub.handleSample(_sample("raw.light.raw", (1, 2, 3), seq))
            sub.handleSample(_sample("raw.light.range", (0x10, 100), seq))
    sub.flushPending()


def _rows(sub: EdrPersistenceSubscriber, db: ObdDatabase) -> tuple[list, list]:
    sub.closeWriteConnection()
    with db.connect() as conn:
        imu = [tuple(r) for r in conn.execute("SELECT * FROM edr_imu_sample ORDER BY id")]
        light = [tuple(r) for r in conn.execute("SELECT * FROM edr_light_sample ORDER BY id")]
    return imu, light


def _readGateState(statesDir: Path) -> dict:
    return json.loads((statesDir / EDR_LOG_GATE_STATE_FILENAME).read_text(encoding="utf-8"))


class _Reader:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _Live:
    """The production EDR start path, started against one connection."""

    def __init__(self, tmp_path: Path, connection: Any, gateEnabled: bool = True) -> None:
        self.statesDir = tmp_path / "states"
        self.db = _db(tmp_path, "live.db")
        config = {"pi": {
            "bus": {"enabled": True},
            "sensors": {
                "imu": {"enabled": True, "sampleHz": 50, "persistHz": 25},
                "light": {"enabled": True, "sampleHz": 1},
                "retentionDays": 45,
                "logGate": {"enabled": gateEnabled, "preRollSec": 60, "holdSec": 300},
            },
            "splash": {"statesDir": str(self.statesDir)},
        }}
        self.host = SimpleNamespace(
            _config=config, _database=self.db, _driveDetector=None, _connection=connection,
        )
        LifecycleMixin._startEdrSensorPath(self.host, SampleBus())  # type: ignore[arg-type]
        self.sub: EdrPersistenceSubscriber = self.host._edrPersistenceSubscriber
        assert self.sub is not None, "lifecycle did not build the EDR subscriber"

    def stop(self) -> None:
        self.sub.stop()


@pytest.fixture()
def startLive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Factory for the live path with the sensor hardware stubbed out."""
    import pi.sensors.imu_state_bridge as imuBridge
    import pi.sensors.light_state_bridge as lightBridge
    import pi.sensors.sensor_reader as sensorReader

    monkeypatch.setattr(sensorReader, "createSensorReadersFromConfig", lambda c, b: [_Reader()])
    monkeypatch.setattr(lightBridge, "createLightStateBridgeFromConfig", lambda c, b: None)
    monkeypatch.setattr(imuBridge, "createImuStateBridgeFromConfig", lambda c, b: None)

    started: list[_Live] = []

    def _start(connection: Any, **kwargs: Any) -> _Live:
        live = _Live(tmp_path, connection, **kwargs)
        started.append(live)
        return live

    yield _start
    for live in started:
        live.stop()


def _plainRows(tmp_path: Path) -> tuple[list, list]:
    """The same run through a subscriber with no gate at all."""
    db = _db(tmp_path, "plain.db")
    plain = EdrPersistenceSubscriber(None, db, imuSampleHz=50, imuPersistHz=25)
    _run(plain)
    return _rows(plain, db)


# --------------------------------------------------------------------- wiring


class TestLifecycleSignal:
    def test_gateIsEnabled_andReadsTheProducer(self, startLive) -> None:
        """
        Given: pi.sensors.logGate.enabled true and a live ObdConnection
        When: the production EDR path is started and rows arrive
        Then: the subscriber's gate is enabled and every admit reads
            ObdConnection.getStatus()
        """
        conn = _connection(True)
        calls: list[int] = []
        realGetStatus = conn.getStatus

        def countingGetStatus() -> Any:
            calls.append(1)
            return realGetStatus()

        conn.getStatus = countingGetStatus  # type: ignore[method-assign]
        live = startLive(conn)

        gate = live.sub._logGate  # noqa: SLF001 -- the wiring IS the assertion
        assert isinstance(gate, EdrLogGate)
        assert gate.enabled is True
        _run(live.sub, bursts=10)
        assert len(calls) > 0

    def test_signalIsLazy_aRebuiltConnectionIsHonoured(self, startLive) -> None:
        """
        Given: the path started on a linked connection
        When: the orchestrator's connection is replaced by one whose link is down
        Then: the gate follows the NEW connection (resolved per row, not captured)
        """
        live = startLive(_connection(True))
        _run(live.sub, bursts=4)
        assert live.sub._logGate.state == GATE_OPEN  # noqa: SLF001

        live.host._connection = _connection(False)
        # The hold keeps writing after the drop; only the gate's read matters here.
        _run(live.sub, bursts=4, start=4)
        assert live.sub._logGate.lastTransition[1] == GATE_HOLD  # noqa: SLF001

    def test_noConnectionObject_failsOpen(self, startLive) -> None:
        """
        Given: the orchestrator has no connection object
        When: rows arrive
        Then: the gate cannot read its signal and fails OPEN -- rows land
        """
        live = startLive(None)
        _run(live.sub, bursts=4)
        imu, _ = _rows(live.sub, live.db)
        assert len(imu) == 2
        assert _readGateState(live.statesDir)["state"] == "OPEN"

    def test_noRenderedOrDerivedUiValueIsRead(
        self, startLive, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: states/ files that all CLAIM the link is up (the rendered and
            derived values a gate must never read), and a producer that says the
            link is genuinely down
        When: rows arrive
        Then: the gate follows the producer (zero rows, CLOSED), and no file in
            the states dir is opened for reading
        """
        live = startLive(_connection(False))
        live.statesDir.mkdir(parents=True, exist_ok=True)
        for name, payload in {
            "system-status": {"obdConnected": True, "linkState": "connected"},
            "capture-health": {"state": "ok"},
            EDR_LOG_GATE_STATE_FILENAME: {"state": "OPEN"},
        }.items():
            (live.statesDir / name).write_text(json.dumps(payload), encoding="utf-8")

        reads: list[str] = []
        statesRoot = str(live.statesDir)
        realOpen = builtins.open
        realReadText = Path.read_text
        realReadBytes = Path.read_bytes

        def spyOpen(file: Any, mode: str = "r", *a: Any, **k: Any) -> Any:
            if "r" in mode and str(file).startswith(statesRoot):
                reads.append(str(file))
            return realOpen(file, mode, *a, **k)

        def spyReadText(self: Path, *a: Any, **k: Any) -> str:
            if str(self).startswith(statesRoot):
                reads.append(str(self))
            return realReadText(self, *a, **k)

        def spyReadBytes(self: Path) -> bytes:
            if str(self).startswith(statesRoot):
                reads.append(str(self))
            return realReadBytes(self)

        monkeypatch.setattr(builtins, "open", spyOpen)
        monkeypatch.setattr(Path, "read_text", spyReadText)
        monkeypatch.setattr(Path, "read_bytes", spyReadBytes)
        _run(live.sub, bursts=20)
        monkeypatch.undo()

        assert reads == []
        assert _rows(live.sub, live.db) == ([], [])
        assert _readGateState(live.statesDir)["state"] == "CLOSED"


# ----------------------------------------------------------- validation criteria


class TestRowCounts:
    def test_fullyLinkedRun_sameRowsAsWithoutTheGate(self, startLive, tmp_path: Path) -> None:
        """
        Given: the live path on a linked producer, and a subscriber with no gate
        When: both are fed the same run
        Then: the same row count -- and the same rows -- land in both
        """
        live = startLive(_connection(True))
        _run(live.sub)

        gatedImu, gatedLight = _rows(live.sub, live.db)
        plainImu, plainLight = _plainRows(tmp_path)
        assert len(plainImu) == _EXPECTED_IMU_ROWS
        assert len(plainLight) == _EXPECTED_LIGHT_ROWS
        assert gatedImu == plainImu
        assert gatedLight == plainLight
        assert _readGateState(live.statesDir)["state"] == "OPEN"

    def test_unlinkedReadableRun_writesNothing_andPublishesClosed(self, startLive) -> None:
        """
        Given: the live path on a producer whose link is down and readable
        When: a run is fed
        Then: zero rows are written and states/edr-log-gate reads CLOSED
        """
        live = startLive(_connection(False))
        _run(live.sub)

        assert _rows(live.sub, live.db) == ([], [])
        state = _readGateState(live.statesDir)
        assert state["state"] == "CLOSED"
        assert state["enabled"] is True
        assert state["from"] is None  # it never left CLOSED

    def test_gateDisabledInConfig_isPassThrough(self, startLive, tmp_path: Path) -> None:
        """
        Given: pi.sensors.logGate.enabled false and a DOWN link
        When: a run is fed
        Then: every row lands (the switch is honoured) and the file reads OPEN
        """
        live = startLive(_connection(False), gateEnabled=False)
        _run(live.sub)
        assert _rows(live.sub, live.db) == _plainRows(tmp_path)
        state = _readGateState(live.statesDir)
        assert state["state"] == "OPEN"
        assert state["enabled"] is False


# ------------------------------------------------------------------- publishing


class TestPublish:
    def test_closedToOpen_isLoggedAndPublished(
        self, startLive, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: the gate CLOSED on a down link, with the file reading CLOSED
        When: the link opens and a row arrives
        Then: the transition is logged and states/edr-log-gate reads OPEN, from
            CLOSED, reason link_linked; the pre-roll lands before the live row
        """
        conn = _connection(False)
        live = startLive(conn)
        _run(live.sub, bursts=4)
        assert _readGateState(live.statesDir)["state"] == "CLOSED"

        conn.obd.result = True
        with caplog.at_level(logging.INFO, logger="pi.bus.edr_log_gate"):
            _run(live.sub, bursts=2, start=4)

        state = _readGateState(live.statesDir)
        assert state["state"] == "OPEN"
        assert state["from"] == "CLOSED"
        assert state["reason"] == "link_linked"
        assert any("CLOSED->OPEN" in r.getMessage() for r in caplog.records)
        imu, _ = _rows(live.sub, live.db)
        assert [r[3] for r in imu] == [0, 2, 4]  # seq, pre-roll first, in order

    def test_publishFailure_neverCostsARow(self, tmp_path: Path) -> None:
        """
        Given: a gate-state publisher that raises
        When: rows arrive on a linked gate
        Then: every row still lands
        """
        link = SimpleNamespace(connected=True, signalReadable=True)
        gate = EdrLogGate(lambda: link, enabled=True)

        def boom(_gate: EdrLogGate) -> None:
            raise OSError("tmpfs gone")

        db = _db(tmp_path, "boom.db")
        sub = EdrPersistenceSubscriber(
            None, db, imuSampleHz=50, imuPersistHz=25, logGate=gate, gateStateEmitFn=boom,
        )
        _run(sub, bursts=10)
        imu, _ = _rows(sub, db)
        assert len(imu) == 5

    def test_publishesOnlyOnStateChange(self, tmp_path: Path) -> None:
        """
        Given: a linked gate
        When: many rows arrive
        Then: the state is published once, not once per row
        """
        link = SimpleNamespace(connected=True, signalReadable=True)
        gate = EdrLogGate(lambda: link, enabled=True)
        published: list[str] = []
        sub = EdrPersistenceSubscriber(
            None, _db(tmp_path, "once.db"), imuSampleHz=50, imuPersistHz=25,
            logGate=gate, gateStateEmitFn=lambda g: published.append(g.state),
        )
        _run(sub, bursts=100)
        sub.closeWriteConnection()
        assert published == [GATE_OPEN]


# ------------------------------------------------------------ mutation (fail-OPEN)


def _mutantGateClass() -> type:
    """EdrLogGate compiled from source with the fail-OPEN return inverted."""
    source = inspect.getsource(edrLogGateModule)
    assert source.count(_FAIL_OPEN_LINE) == 1, "fail-OPEN line moved; update the mutation"
    mutated = source.replace(_FAIL_OPEN_LINE, _FAIL_CLOSED_LINE)
    assert mutated != source
    module = types.ModuleType("pi.bus.edr_log_gate_mutant")
    exec(compile(mutated, "<edr_log_gate mutant>", "exec"), module.__dict__)  # noqa: S102
    mutant = module.EdrLogGate
    # The mutation is APPLIED, not just written: the compiled gate closes on an
    # unreadable signal, where the shipped one opens.
    probe = mutant(lambda: SimpleNamespace(connected=False, signalReadable=False), enabled=True)
    assert probe._readLink(0.0) == (False, "signal_unreadable")  # noqa: SLF001
    return mutant


def _unreadableRunKeepsRecording(
    startLive: Callable[..., _Live], expectGateCls: type
) -> bool:
    """Run the live path on an UNREADABLE signal; did the fail-OPEN invariant hold?

    The invariant: after the first row the gate is never CLOSED, every row
    lands, and states/edr-log-gate never reads CLOSED.
    """
    live = startLive(_connection(RuntimeError("port gone")))
    gate = live.sub._logGate  # noqa: SLF001
    assert type(gate) is expectGateCls, "the live path did not build the gate under test"

    statesSeen: list[str] = []
    realAdmit = gate.admit

    def recordingAdmit(table: str, row: Any) -> list:
        out = realAdmit(table, row)
        statesSeen.append(gate.state)
        return out

    gate.admit = recordingAdmit  # type: ignore[method-assign]
    _run(live.sub)
    imu, light = _rows(live.sub, live.db)
    published = _readGateState(live.statesDir)["state"]
    return (
        GATE_CLOSED not in statesSeen
        and len(imu) == _EXPECTED_IMU_ROWS
        and len(light) == _EXPECTED_LIGHT_ROWS
        and published != "CLOSED"
    )


class TestFailOpenMutation:
    def test_unreadableSignal_neverCloses_andRowsLand(self, startLive) -> None:
        """
        Given: a producer whose is_connected() raises (signalReadable False)
        When: a full run is fed through the live path
        Then: the gate never goes CLOSED and every row lands
        """
        assert _unreadableRunKeepsRecording(startLive, EdrLogGate) is True

    def test_invertedFailOpenBranch_failsTheSameCheck(
        self, startLive, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: EdrLogGate with its fail-OPEN return deliberately inverted, and
            that mutation proven applied (the compiled gate returns closed on an
            unreadable signal, and the live path builds the mutant)
        When: the same unreadable run is fed
        Then: the same check FAILS -- so it can catch the regression it guards
        """
        mutant = _mutantGateClass()
        monkeypatch.setattr(edrLogGateModule, "EdrLogGate", mutant)
        assert _unreadableRunKeepsRecording(startLive, mutant) is False
