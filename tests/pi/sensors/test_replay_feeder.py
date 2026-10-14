################################################################################
# File Name: test_replay_feeder.py
# Purpose/Description: US-900 -- a recorded drive's IMU and light rows replayed
#                      onto the SampleBus in place of the hardware readers.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-900) | Initial implementation
# ================================================================================
################################################################################

"""Tests for :mod:`pi.sensors.replay_feeder` (US-900)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from common.edr.sensor_schema import EDR_SCHEMAS
from pi.bus.bus import SampleBus
from pi.bus.sample import QoS, Sample
from pi.sensors.light_state_bridge import createLightStateBridgeFromConfig
from pi.sensors.replay_feeder import (
    REPLAY_DATA_SOURCE,
    SensorReplayFeeder,
    createSensorReplayFeederFromConfig,
)

# ================================================================================
# Fixtures
# ================================================================================

_DRIVE_ID = 117

# The replayed drive's window is its first to last realtime_data row.
_DRIVE_START = "2026-10-01T12:00:10Z"
_DRIVE_END = "2026-10-01T12:00:20Z"


class _FakeClock:
    """Monotonic stand-in the test advances by hand."""

    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now


def _imuRow(tsUtc: str, tsCapture: float, accelZ: float, mag: Any = (1.0, 2.0, 3.0)) -> dict:
    return {"ts_utc": tsUtc, "ts_capture": tsCapture, "accel": (0.1, 0.2, accelZ),
            "gyro": (0.01, 0.02, 0.03), "mag": mag}


def _lightRow(
    tsUtc: str,
    tsCapture: float,
    lux: float | None,
    *,
    gain: str | None = None,
    integrationMs: int | None = None,
) -> dict:
    return {"ts_utc": tsUtc, "ts_capture": tsCapture, "lux": lux, "raw": (100, 20, 120),
            "gain": gain, "integration_ms": integrationMs}


def _makeSourceDb(
    path: Path,
    *,
    imu: list[dict] | None = None,
    light: list[dict] | None = None,
    withRealtime: bool = True,
) -> str:
    """Write a source database holding one drive and the given sensor rows."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE realtime_data (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " timestamp DATETIME NOT NULL, parameter_name TEXT NOT NULL,"
            " value REAL NOT NULL, unit TEXT, drive_id INTEGER)"
        )
        if withRealtime:
            conn.executemany(
                "INSERT INTO realtime_data (timestamp, parameter_name, value, drive_id)"
                " VALUES (?, 'RPM', 800, ?)",
                [(_DRIVE_START, _DRIVE_ID), (_DRIVE_END, _DRIVE_ID)],
            )
        for _, ddl in EDR_SCHEMAS:
            conn.execute(ddl)
        for seq, row in enumerate(imu or []):
            accel, gyro, mag = row["accel"], row["gyro"], row["mag"] or (None, None, None)
            conn.execute(
                "INSERT INTO edr_imu_sample (ts_utc, ts_capture, seq, accel_x, accel_y,"
                " accel_z, gyro_x, gyro_y, gyro_z, mag_x, mag_y, mag_z, temp_c)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 30.0)",
                (row["ts_utc"], row["ts_capture"], seq, *accel, *gyro, *mag),
            )
        for seq, row in enumerate(light or []):
            conn.execute(
                "INSERT INTO edr_light_sample (ts_utc, ts_capture, seq, lux, visible,"
                " infrared, full_spectrum, gain, integration_ms)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row["ts_utc"], row["ts_capture"], seq, row["lux"], *row["raw"],
                 row["gain"], row["integration_ms"]),
            )
        conn.commit()
    finally:
        conn.close()
    return str(path)


def _drain(sub: Any) -> list[Sample]:
    out = []
    while (sample := sub.poll()) is not None:
        out.append(sample)
    return out


def _config(sourcePath: str, statesDir: str, *, imu: bool = True, light: bool = True,
            active: bool = True, bus: bool = True) -> dict:
    return {"pi": {
        "bus": {"enabled": bus},
        "sensors": {"imu": {"enabled": imu}, "light": {"enabled": light}},
        "replay": {"active": active, "sourcePath": sourcePath, "driveId": _DRIVE_ID},
        "splash": {"statesDir": statesDir},
    }}


# ================================================================================
# Validation criterion: 3 light + 3 IMU rows on a fake clock
# ================================================================================


class TestReplayWindow:
    def test_threeLightAndThreeImuRows_lightStateCarriesEachLuxInOrder_taggedReplay(
        self, tmp_path: Path
    ) -> None:
        """
        Given: a recording with 3 light rows and 3 IMU rows inside the drive's
            window, one of each before it and one of each after it
        When: the feeder replays it on a fake clock through the real light bridge
        Then: states/light carries each lux in recorded order, and every sample
            the feeder published carries dataSource 'replay'
        """
        source = _makeSourceDb(
            tmp_path / "src.db",
            imu=[
                _imuRow("2026-10-01T12:00:05Z", 95.0, 1.0),  # before the window
                _imuRow("2026-10-01T12:00:10Z", 100.0, 9.7),
                _imuRow("2026-10-01T12:00:11Z", 101.0, 9.8),
                _imuRow("2026-10-01T12:00:12Z", 102.0, 9.9),
                _imuRow("2026-10-01T12:00:25Z", 115.0, 1.0),  # after the window
            ],
            light=[
                _lightRow("2026-10-01T12:00:04Z", 94.0, 999.0),
                _lightRow("2026-10-01T12:00:10Z", 100.0, 11.0),
                _lightRow("2026-10-01T12:00:12Z", 102.0, 22.0),
                _lightRow("2026-10-01T12:00:14Z", 104.0, 33.0),
                _lightRow("2026-10-01T12:00:21Z", 111.0, 999.0),
            ],
        )
        statesDir = tmp_path / "states"
        bus = SampleBus()
        bridge = createLightStateBridgeFromConfig(
            _config(source, str(statesDir)), bus
        )
        assert bridge is not None
        tap = bus.subscribe(["raw.imu.*", "raw.light.*"], QoS.LOSSLESS, "tap")
        clock = _FakeClock()
        feeder = SensorReplayFeeder(bus, source, _DRIVE_ID, clock=clock)

        luxSeen: list[float | None] = []
        published: list[Sample] = []
        feeder.begin()
        for step in range(0, 6):
            clock.now = 500.0 + step
            feeder.publishDue()
            drained = _drain(bridge._sub)  # noqa: SLF001 -- drain by hand
            for sample in drained:
                bridge.handleSample(sample)
            if drained:
                payload = json.loads((statesDir / "light").read_text(encoding="utf-8"))
                luxSeen.append(payload["lux"])
            published.extend(_drain(tap))

        assert luxSeen == [11.0, 22.0, 33.0]
        assert published
        assert {s.dataSource for s in published} == {REPLAY_DATA_SOURCE}
        assert REPLAY_DATA_SOURCE == "replay"
        accelZ = [s.value[2] for s in published if s.topic == "raw.imu.accel"]
        assert accelZ == [9.7, 9.8, 9.9]
        assert feeder.isFinished()

    def test_rowsPublish_onTheirOriginalRelativeTiming(self, tmp_path: Path) -> None:
        """
        Given: light rows 2 s into the drive and IMU rows 40 ms apart inside one
            whole second of ts_utc
        When: the fake clock is advanced
        Then: each row publishes only once its own offset has been reached; the
            sub-second spacing comes from the recorded ts_capture
        """
        source = _makeSourceDb(
            tmp_path / "src.db",
            imu=[
                _imuRow("2026-10-01T12:00:11Z", 300.00, 9.70),
                _imuRow("2026-10-01T12:00:11Z", 300.04, 9.71),
            ],
            light=[_lightRow("2026-10-01T12:00:12Z", 301.0, 5.0)],
        )
        bus = SampleBus()
        tap = bus.subscribe(["raw.imu.accel", "raw.light.lux"], QoS.LOSSLESS, "tap")
        clock = _FakeClock()
        feeder = SensorReplayFeeder(bus, source, _DRIVE_ID, clock=clock)
        feeder.begin()

        clock.now = 500.99
        feeder.publishDue()
        assert _drain(tap) == []

        clock.now = 501.0
        feeder.publishDue()
        assert [s.value[2] for s in _drain(tap)] == [9.70]

        clock.now = 501.039
        feeder.publishDue()
        assert _drain(tap) == []

        clock.now = 501.041
        feeder.publishDue()
        assert [s.value[2] for s in _drain(tap)] == [9.71]

        clock.now = 502.0
        feeder.publishDue()
        assert [s.value for s in _drain(tap)] == [5.0]
        assert feeder.isFinished()

    def test_publishesTheFiveTopics_withReaderUnits_andOneSeqPerBurst(
        self, tmp_path: Path
    ) -> None:
        """
        Given: one IMU row and one light row
        When: they are replayed
        Then: accel/gyro/mag share one seq, lux/raw share one seq, and the
            units and value shapes are the live readers'
        """
        from pi.sensors import sensor_reader as sr

        source = _makeSourceDb(
            tmp_path / "src.db",
            imu=[_imuRow(_DRIVE_START, 1.0, 9.8)],
            light=[_lightRow(_DRIVE_START, 1.0, 7.5)],
        )
        bus = SampleBus()
        tap = bus.subscribe(["raw.imu.*", "raw.light.*"], QoS.LOSSLESS, "tap")
        clock = _FakeClock()
        feeder = SensorReplayFeeder(bus, source, _DRIVE_ID, clock=clock)
        feeder.begin()
        feeder.publishDue()

        byTopic = {s.topic: s for s in _drain(tap)}
        assert set(byTopic) == {
            sr.TOPIC_IMU_ACCEL, sr.TOPIC_IMU_GYRO, sr.TOPIC_IMU_MAG,
            sr.TOPIC_LIGHT_LUX, sr.TOPIC_LIGHT_RAW, sr.TOPIC_LIGHT_RANGE,
        }
        assert byTopic[sr.TOPIC_IMU_ACCEL].unit == sr.UNIT_ACCEL
        assert byTopic[sr.TOPIC_IMU_GYRO].unit == sr.UNIT_GYRO
        assert byTopic[sr.TOPIC_IMU_MAG].unit == sr.UNIT_MAG
        assert byTopic[sr.TOPIC_LIGHT_LUX].unit == sr.UNIT_LUX
        assert byTopic[sr.TOPIC_LIGHT_RAW].unit == sr.UNIT_COUNT
        assert byTopic[sr.TOPIC_IMU_GYRO].value == (0.01, 0.02, 0.03)
        assert byTopic[sr.TOPIC_LIGHT_RAW].value == (100, 20, 120)
        imuSeqs = {byTopic[t].seq for t in (sr.TOPIC_IMU_ACCEL, sr.TOPIC_IMU_GYRO, sr.TOPIC_IMU_MAG)}
        assert len(imuSeqs) == 1
        assert byTopic[sr.TOPIC_LIGHT_LUX].seq == byTopic[sr.TOPIC_LIGHT_RAW].seq
        assert byTopic[sr.TOPIC_IMU_ACCEL].tsCapture == clock.now

    def test_nullsAreNotRead_saturatedLuxIsNone_absentMagIsNotPublished(
        self, tmp_path: Path
    ) -> None:
        """
        Given: a light row with NULL lux (saturated) and an IMU row with NULL mag
        When: they are replayed
        Then: lux is published as None, exactly as the live reader does, and the
            mag topic is not published at all -- never a 0 standing in
        """
        source = _makeSourceDb(
            tmp_path / "src.db",
            imu=[_imuRow(_DRIVE_START, 1.0, 9.8, mag=None)],
            light=[_lightRow(_DRIVE_START, 1.0, None)],
        )
        bus = SampleBus()
        tap = bus.subscribe(["raw.imu.*", "raw.light.*"], QoS.LOSSLESS, "tap")
        feeder = SensorReplayFeeder(bus, source, _DRIVE_ID, clock=_FakeClock())
        feeder.begin()
        feeder.publishDue()

        byTopic = {s.topic: s for s in _drain(tap)}
        assert "raw.imu.mag" not in byTopic
        assert "raw.imu.accel" in byTopic
        assert byTopic["raw.light.lux"].value is None


class TestLightRangeBurst:
    """US-878-a: every replayed light row publishes range LAST, so it is written."""

    def test_rangeIsPublishedLast_withTheStoredGainAsItsCode(self, tmp_path: Path) -> None:
        """
        Given: one light row stored with gain 'med' and integration_ms 100
        When: it is replayed
        Then: lux, raw, range publish in that order under one seq, and range
            carries (0x10, 100) -- the register code the live reader publishes
        """
        from pi.sensors import sensor_reader as sr

        source = _makeSourceDb(
            tmp_path / "src.db",
            light=[_lightRow(_DRIVE_START, 1.0, 7.5, gain="med", integrationMs=100)],
        )
        bus = SampleBus()
        tap = bus.subscribe(["raw.light.*"], QoS.LOSSLESS, "tap")
        feeder = SensorReplayFeeder(bus, source, _DRIVE_ID, clock=_FakeClock())
        feeder.begin()
        feeder.publishDue()

        samples = _drain(tap)
        assert [s.topic for s in samples] == [
            sr.TOPIC_LIGHT_LUX, sr.TOPIC_LIGHT_RAW, sr.TOPIC_LIGHT_RANGE,
        ]
        assert len({s.seq for s in samples}) == 1
        assert samples[-1].value == (sr.TSL_GAIN_MED, 100)
        assert samples[-1].unit == sr.UNIT_RANGE

    def test_threeRows_writeStatesLightThreeTimes_lastRowWritten(self, tmp_path: Path) -> None:
        """
        Given: three light rows inside the window
        When: all three are replayed in one step through the real bridge
        Then: states/light is written three times, and the file holds the last row
        """
        source = _makeSourceDb(
            tmp_path / "src.db",
            light=[
                _lightRow("2026-10-01T12:00:10Z", 100.0, 11.0, gain="low", integrationMs=100),
                _lightRow("2026-10-01T12:00:11Z", 101.0, 22.0, gain="low", integrationMs=100),
                _lightRow("2026-10-01T12:00:12Z", 102.0, 33.0, gain="high", integrationMs=200),
            ],
        )
        statesDir = tmp_path / "states"
        bus = SampleBus()
        bridge = createLightStateBridgeFromConfig(_config(source, str(statesDir)), bus)
        assert bridge is not None
        writes: list[dict] = []
        realWrite = bridge._writeState  # noqa: SLF001 -- count the real writes

        def _recordingWrite(payload: dict) -> None:
            writes.append(payload)
            realWrite(payload)

        bridge._writeState = _recordingWrite  # type: ignore[method-assign]  # noqa: SLF001
        clock = _FakeClock()
        feeder = SensorReplayFeeder(bus, source, _DRIVE_ID, clock=clock)
        feeder.begin()
        clock.now += 10.0
        assert feeder.publishDue() == 3
        for sample in _drain(bridge._sub):  # noqa: SLF001 -- drain by hand
            bridge.handleSample(sample)

        assert [w["lux"] for w in writes] == [11.0, 22.0, 33.0]
        payload = json.loads((statesDir / "light").read_text(encoding="utf-8"))
        assert payload["lux"] == 33.0
        assert payload["gain"] == "high"
        assert payload["integrationMs"] == 200

    def test_nullGainRow_isStillWritten_withGainNull(self, tmp_path: Path) -> None:
        """
        Given: a light row whose gain and integration_ms were never recorded
        When: it is replayed through the real bridge
        Then: range still publishes (gain None), so states/light is written,
            with gain and integrationMs null -- as live does for an unread gain
        """
        source = _makeSourceDb(
            tmp_path / "src.db",
            light=[_lightRow(_DRIVE_START, 1.0, 7.5)],
        )
        statesDir = tmp_path / "states"
        bus = SampleBus()
        bridge = createLightStateBridgeFromConfig(_config(source, str(statesDir)), bus)
        assert bridge is not None
        feeder = SensorReplayFeeder(bus, source, _DRIVE_ID, clock=_FakeClock())
        feeder.begin()
        feeder.publishDue()
        for sample in _drain(bridge._sub):  # noqa: SLF001 -- drain by hand
            bridge.handleSample(sample)

        payload = json.loads((statesDir / "light").read_text(encoding="utf-8"))
        assert payload["lux"] == 7.5
        assert payload["gain"] is None
        assert payload["integrationMs"] is None
        assert payload["fullCount"] == 120


class TestNoSensorRows:
    def test_recordingWithNoSensorRows_publishesNothing_bridgeKeepsNoDataState(
        self, tmp_path: Path
    ) -> None:
        """
        Given: a recording whose window holds no IMU or light rows
        When: the feeder replays it to the end
        Then: nothing is published, it reports finished, and states/light is
            never written (the bridge's existing no-data state)
        """
        source = _makeSourceDb(
            tmp_path / "src.db",
            light=[_lightRow("2026-10-01T11:00:00Z", 1.0, 5.0)],  # outside the window
        )
        statesDir = tmp_path / "states"
        bus = SampleBus()
        bridge = createLightStateBridgeFromConfig(_config(source, str(statesDir)), bus)
        assert bridge is not None
        tap = bus.subscribe(["raw.*"], QoS.LOSSLESS, "tap")
        clock = _FakeClock()
        feeder = SensorReplayFeeder(bus, source, _DRIVE_ID, clock=clock)
        feeder.begin()
        clock.now += 60.0
        assert feeder.publishDue() == 0

        assert _drain(tap) == []
        assert feeder.isFinished()
        assert not (statesDir / "light").exists()

    def test_sourceWithoutEdrTables_publishesNothing(self, tmp_path: Path) -> None:
        """A recording made before the EDR tables existed has no sensor rows."""
        path = tmp_path / "old.db"
        conn = sqlite3.connect(str(path))
        conn.execute(
            "CREATE TABLE realtime_data (id INTEGER PRIMARY KEY, timestamp TEXT,"
            " parameter_name TEXT, value REAL, drive_id INTEGER)"
        )
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value, drive_id)"
            " VALUES (?, 'RPM', 800, ?)", (_DRIVE_START, _DRIVE_ID)
        )
        conn.commit()
        conn.close()
        bus = SampleBus()
        tap = bus.subscribe(["raw.*"], QoS.LOSSLESS, "tap")
        feeder = SensorReplayFeeder(bus, str(path), _DRIVE_ID, clock=_FakeClock())
        feeder.begin()
        assert feeder.publishDue() == 0
        assert _drain(tap) == []
        assert feeder.isFinished()

    def test_driveWithNoRealtimeRows_hasNoWindow_publishesNothing(self, tmp_path: Path) -> None:
        """No realtime_data rows for the drive -> no window -> nothing replayed."""
        source = _makeSourceDb(
            tmp_path / "src.db",
            light=[_lightRow(_DRIVE_START, 1.0, 5.0)],
            withRealtime=False,
        )
        bus = SampleBus()
        tap = bus.subscribe(["raw.*"], QoS.LOSSLESS, "tap")
        feeder = SensorReplayFeeder(bus, source, _DRIVE_ID, clock=_FakeClock())
        feeder.begin()
        assert feeder.publishDue() == 0
        assert _drain(tap) == []


class TestSensorSelection:
    def test_lightOnly_publishesNoImuTopics(self, tmp_path: Path) -> None:
        """A disabled sensor is not replayed, as a disabled reader is not built."""
        source = _makeSourceDb(
            tmp_path / "src.db",
            imu=[_imuRow(_DRIVE_START, 1.0, 9.8)],
            light=[_lightRow(_DRIVE_START, 1.0, 5.0)],
        )
        bus = SampleBus()
        tap = bus.subscribe(["raw.*"], QoS.LOSSLESS, "tap")
        feeder = SensorReplayFeeder(
            bus, source, _DRIVE_ID, imu=False, light=True, clock=_FakeClock()
        )
        feeder.begin()
        feeder.publishDue()
        assert {s.topic for s in _drain(tap)} == {
            "raw.light.lux", "raw.light.raw", "raw.light.range",
        }


class TestThread:
    def test_startAndStop_replaysOnItsOwnThread(self, tmp_path: Path) -> None:
        """
        Given: a feeder whose clock is already past the last row
        When: it is started like a reader
        Then: its thread publishes every row and ends; stop() joins cleanly
        """
        source = _makeSourceDb(
            tmp_path / "src.db",
            light=[_lightRow(_DRIVE_START, 1.0, 5.0), _lightRow(_DRIVE_END, 11.0, 6.0)],
        )
        bus = SampleBus()
        tap = bus.subscribe(["raw.light.lux"], QoS.LOSSLESS, "tap")
        clock = _FakeClock()
        feeder = SensorReplayFeeder(bus, source, _DRIVE_ID, clock=clock)

        feeder.begin()
        clock.now += 3600.0
        feeder.start()
        feeder._thread.join(timeout=5.0)  # noqa: SLF001 -- wait for the end
        feeder.stop()

        assert [tap.get(timeoutS=1.0).value, tap.get(timeoutS=1.0).value] == [5.0, 6.0]
        assert feeder.isFinished()


class TestFactory:
    def test_replayActive_buildsFeederForTheEnabledSensors(self, tmp_path: Path) -> None:
        source = _makeSourceDb(tmp_path / "src.db")
        feeder = createSensorReplayFeederFromConfig(
            _config(source, str(tmp_path), imu=False), SampleBus()
        )
        assert isinstance(feeder, SensorReplayFeeder)
        assert feeder.sourcePath == source
        assert feeder.driveId == _DRIVE_ID
        assert feeder.replaysImu is False
        assert feeder.replaysLight is True

    @pytest.mark.parametrize(
        "overrides",
        [
            {"active": False},
            {"bus": False},
            {"imu": False, "light": False},
        ],
    )
    def test_nothingToReplay_returnsNone(self, tmp_path: Path, overrides: dict) -> None:
        source = _makeSourceDb(tmp_path / "src.db")
        assert createSensorReplayFeederFromConfig(
            _config(source, str(tmp_path), **overrides), SampleBus()
        ) is None
