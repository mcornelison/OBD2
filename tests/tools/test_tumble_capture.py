"""ARCH-064 Task 6b / Ruling 30: the tumble capture's pure logic, off-Pi.

The real device, the bus and the clock are all injected: a fake driver, a fake
``systemctl`` runner and a fake monotonic clock whose ``sleep`` advances it.
"""

from __future__ import annotations

import csv
import io
import json
import subprocess

import pytest

import tools.imu.tumble_capture as tumble_capture
from pi.sensors.ak09916_bypass import MagnetometerOverflowError, toIcmFrame
from tools.imu.tumble_capture import (
    CSV_COLUMNS,
    FACE_PHASES,
    PHASE_TUMBLE,
    capture,
    collectorStopped,
    main,
    phaseSchedule,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


class FakeDevice:
    """Icm20948Direct-shaped: accel (m/s^2), gyro (rad/s), magnetic (RAW AK uT)."""

    def __init__(self, clock: FakeClock, *, overflowEvery: int = 0) -> None:
        self.clock = clock
        self.reads = 0
        self.overflowEvery = overflowEvery

    @property
    def acceleration(self):
        self.reads += 1
        return (0.1, -0.2, 9.8)

    @property
    def gyro(self):
        return (0.001, -0.002, 0.003)

    @property
    def magnetic(self):
        if self.overflowEvery and self.reads % self.overflowEvery == 0:
            raise MagnetometerOverflowError("HOFL")
        return (11.0, 22.0, 33.0)


def _runner(state: str):
    def run(args, **kwargs):
        assert args[:2] == ["systemctl", "is-active"]
        return subprocess.CompletedProcess(args, 0 if state == "active" else 3, stdout=state + "\n", stderr="")

    return run


# --- phase schedule ---------------------------------------------------------------


def test_scheduleIsSixFacesThenTheTumble():
    schedule = phaseSchedule()
    assert [p.name for p in schedule] == [name for name, _ in FACE_PHASES] + [PHASE_TUMBLE]
    assert [p.durationS for p in schedule] == [10.0] * 6 + [180.0]
    assert [name for name, _ in FACE_PHASES] == [
        "face_+x_up", "face_-x_up", "face_+y_up", "face_-y_up", "face_+z_up", "face_-z_up",
    ]


def test_scheduleDurationsAreConfigurable():
    schedule = phaseSchedule(faceSeconds=2.0, tumbleSeconds=5.0)
    assert [p.durationS for p in schedule] == [2.0] * 6 + [5.0]


# --- collector refusal ------------------------------------------------------------


@pytest.mark.parametrize("state", ["inactive", "failed"])
def test_collectorStoppedWhenInactiveOrFailed(state):
    stopped, reason = collectorStopped(runner=_runner(state))
    assert stopped is True
    assert state in reason


@pytest.mark.parametrize("state", ["active", "activating", "reloading", "deactivating", ""])
def test_collectorNotStoppedOtherwise(state):
    stopped, _ = collectorStopped(runner=_runner(state))
    assert stopped is False


def test_collectorStateUnknowableIsNotStopped():
    def missing(args, **kwargs):
        raise FileNotFoundError("systemctl")

    stopped, reason = collectorStopped(runner=missing)
    assert stopped is False
    assert "systemctl" in reason


def test_mainRefusesWhileTheCollectorRunsAndNeverTouchesTheBus(tmp_path, capsys):
    built = []
    code = main(
        ["--out", str(tmp_path / "t.csv")],
        runner=_runner("active"),
        deviceFactory=lambda: built.append(1),
    )
    assert code == 2
    assert built == []  # the device (and so the bus) was never opened
    assert "refused" in json.loads(capsys.readouterr().out)
    assert not (tmp_path / "t.csv").exists()


# --- capture ----------------------------------------------------------------------


def _capture(device=None, faceSeconds=1.0, tumbleSeconds=2.0, hz=10.0):
    clock = FakeClock()
    device = device or FakeDevice(clock)
    out = io.StringIO()
    err = io.StringIO()
    summary = capture(
        device,
        phaseSchedule(faceSeconds=faceSeconds, tumbleSeconds=tumbleSeconds),
        out,
        hz=hz,
        settleS=3.0,
        clock=clock,
        sleep=clock.sleep,
        log=err,
    )
    rows = list(csv.DictReader(io.StringIO(out.getvalue())))
    return summary, rows, err.getvalue()


def test_csvHeaderIsTheRealEdrImuSampleNamesPlusPhase():
    _, rows, _ = _capture()
    assert tuple(rows[0].keys()) == CSV_COLUMNS
    assert CSV_COLUMNS == (
        "ts_capture", "phase",
        "accel_x", "accel_y", "accel_z",
        "gyro_x", "gyro_y", "gyro_z",
        "mag_x", "mag_y", "mag_z",
    )


def test_eachPhaseGetsItsDurationAtTheRequestedRate():
    summary, rows, _ = _capture(faceSeconds=1.0, tumbleSeconds=2.0, hz=10.0)
    counts = {}
    for row in rows:
        counts[row["phase"]] = counts.get(row["phase"], 0) + 1
    assert counts == {**{name: 10 for name, _ in FACE_PHASES}, PHASE_TUMBLE: 20}
    assert summary["rows"] == 80


def test_settleTimeIsNotRecorded():
    """The operator re-orients during the settle countdown: those samples are
    mid-motion and belong to no face, so none is written."""
    _, rows, _ = _capture(faceSeconds=1.0, tumbleSeconds=1.0, hz=10.0)
    ts = [float(r["ts_capture"]) for r in rows]
    faceA = [t for t, r in zip(ts, rows, strict=True) if r["phase"] == "face_+x_up"]
    faceB = [t for t, r in zip(ts, rows, strict=True) if r["phase"] == "face_-x_up"]
    assert min(faceB) - max(faceA) >= 3.0 - 1e-9


def test_rowsAreDeviceFrameWithTheAkMapApplied():
    """accel/gyro verbatim (device frame, no mount); mag through toIcmFrame
    exactly once -- the seam sensor_reader applies it at."""
    _, rows, _ = _capture()
    row = rows[0]
    assert (float(row["accel_x"]), float(row["accel_y"]), float(row["accel_z"])) == (0.1, -0.2, 9.8)
    assert (float(row["gyro_x"]), float(row["gyro_y"]), float(row["gyro_z"])) == (0.001, -0.002, 0.003)
    mag = (float(row["mag_x"]), float(row["mag_y"]), float(row["mag_z"]))
    assert mag == pytest.approx(toIcmFrame((11.0, 22.0, 33.0)))
    assert mag != pytest.approx((11.0, 22.0, 33.0))  # guard: the AK map is not the identity


def test_timestampsAreMonotonicCaptureTimes():
    _, rows, _ = _capture()
    ts = [float(r["ts_capture"]) for r in rows]
    assert ts == sorted(ts)
    assert ts[0] >= 1000.0


def test_magOverflowBlanksTheMagButKeepsTheRow():
    clock = FakeClock()
    summary, rows, _ = _capture(device=FakeDevice(clock, overflowEvery=4))
    blanks = [r for r in rows if r["mag_x"] == ""]
    assert blanks and all(r["accel_x"] != "" for r in blanks)
    assert summary["magMissingRows"] == len(blanks)


def test_promptsNameEachFaceOnStderr():
    _, _, err = _capture()
    for _, prompt in FACE_PHASES:
        assert prompt in err
    assert "tumble" in err.lower()


def test_aFrozenMagnetometerIsReported():
    """A constant mag through a tumble is a frozen sensor (A-37/ARCH-057), not
    a field: the summary counts repeats and warns."""
    _, _, err = _capture()  # FakeDevice's mag never changes
    assert "WARNING" in err and "frozen" in err


def test_mainWritesTheCsvAndASummary(tmp_path, capsys, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(tumble_capture, "_clock", clock)
    monkeypatch.setattr(tumble_capture, "_sleep", clock.sleep)
    out = tmp_path / "tumble.csv"
    code = main(
        ["--out", str(out), "--face-seconds", "0.5", "--tumble-seconds", "1", "--settle-seconds", "0"],
        runner=_runner("inactive"),
        deviceFactory=lambda: FakeDevice(clock),
    )
    assert code == 0
    with open(out, newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 6 * 25 + 50
    summary = json.loads(capsys.readouterr().out)
    assert summary["rows"] == 200
    assert summary["out"] == str(out)


def test_productionDeviceIsTheArch064DirectDriver(monkeypatch):
    """Ruling 30: the capture MUST read through the production ARCH-064 build
    (sensor_reader._makeIcm20948Direct -> makeIcm20948Direct: clean reset,
    master never enabled, bypass), never imu_probe/capture_cli."""
    import pi.sensors.sensor_reader as sensor_reader

    sentinel = object()
    monkeypatch.setattr(sensor_reader, "_makeIcm20948Direct", lambda: sentinel)
    assert tumble_capture._productionDevice() is sentinel
    source = open(tumble_capture.__file__, encoding="utf-8").read()
    assert "imu_probe" not in source.split('"""', 2)[2]  # not imported anywhere below the docstring
    assert "capture_cli" not in source.split('"""', 2)[2]
