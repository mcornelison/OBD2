"""ARCH-064 Task 6b / Rulings 30-31: the tumble capture's pure logic, off-Pi.

The real device, the bus and the clock are all injected: a fake driver, a fake
``systemctl`` runner and a fake monotonic clock whose ``sleep`` advances it.

Fix round 1 (I2): the original FakeDevice's magnetometer never changed, so the
frozen-mag warning could fire ALWAYS and every test still passed -- a test
protecting a defect. ``HonestDevice`` below is a physically plausible operator:
each hold oriented as prompted, gyro noise only, a live noisy magnetometer that
rotates with the enclosure. On it, NO warning may fire; each warning is then
provoked by changing exactly one thing.
"""

from __future__ import annotations

import csv
import io
import json
import math
import subprocess

import numpy as np
import pytest

import tools.imu.tumble_capture as tumble_capture
from pi.sensors.ak09916_bypass import MagnetometerOverflowError, toIcmFrame
from tools.imu.tumble_capture import (
    CORNER_PHASES,
    CSV_COLUMNS,
    FACE_PHASES,
    PHASE_TUMBLE,
    capture,
    collectorStopped,
    main,
    phaseSchedule,
)

G = 9.80665


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


class FakeDevice:
    """Icm20948Direct-shaped: accel (m/s^2), gyro (rad/s), magnetic (RAW AK uT).
    Constant readings -- used where only the plumbing matters."""

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


class HonestDevice:
    """An operator who does exactly what the prompts say.

    ``perHold`` = samples per still hold (the schedule's hold phases in order,
    then the tumble). Overrides let a test break exactly one thing:
    ``gyroOffset`` (A-34 latched offset), ``jitterPhase`` (a hold whose rate
    varies), ``wrongPhase`` (a hold held with +z up instead), ``frozenMag``.
    """

    def __init__(self, perHold: int, *, gyroOffset=(0.0, 0.0, 0.0), jitterPhase=None, wrongPhase=None,
                 frozenMag=False, seed=3) -> None:
        self.rng = np.random.default_rng(seed)
        self.perHold = perHold
        self.holds = [p for p in phaseSchedule() if p.upDevice is not None]
        self.gyroOffset = np.asarray(gyroOffset, dtype=float)
        self.jitterPhase = jitterPhase
        self.wrongPhase = wrongPhase
        self.frozenMag = frozenMag
        self.reads = 0
        self._up = np.array([0.0, 0.0, 1.0])
        self._phase = None

    def _current(self):
        index = self.reads // self.perHold
        if index < len(self.holds):
            phase = self.holds[index]
            up = np.asarray(phase.upDevice)
            if phase.name == self.wrongPhase:
                up = np.array([0.0, 0.0, 1.0]) if abs(up[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
            return phase.name, up
        t = self.reads * 0.02
        up = np.array([math.cos(t) * math.cos(0.7 * t), math.sin(t) * math.cos(0.7 * t), math.sin(0.7 * t)])
        return PHASE_TUMBLE, up

    @property
    def acceleration(self):
        self._phase, self._up = self._current()
        self.reads += 1
        return tuple(G * self._up + self.rng.normal(scale=0.02, size=3))

    @property
    def gyro(self):
        noise = self.rng.normal(scale=0.004, size=3)
        if self._phase == self.jitterPhase:
            noise = noise + self.rng.normal(scale=0.3, size=3)
        return tuple(self.gyroOffset + noise)

    @property
    def magnetic(self):
        if self.frozenMag:
            return (11.0, 22.0, 33.0)
        # The field rotates with the enclosure: a fixed world field seen in the
        # device frame, plus 0.3 uT noise. RAW AK frame (the capture maps it).
        field = 40.0 * self._up + np.array([15.0, -5.0, 0.0])
        return tuple(field + self.rng.normal(scale=0.3, size=3))


def _runner(state: str):
    def run(args, **kwargs):
        assert args[:2] == ["systemctl", "is-active"]
        return subprocess.CompletedProcess(args, 0 if state == "active" else 3, stdout=state + "\n", stderr="")

    return run


# --- phase schedule ---------------------------------------------------------------


def test_scheduleIsSixFacesThenEightCornersThenTheTumble():
    schedule = phaseSchedule()
    assert [p.name for p in schedule] == (
        [n for n, _, _ in FACE_PHASES] + [n for n, _, _ in CORNER_PHASES] + [PHASE_TUMBLE]
    )
    assert [p.durationS for p in schedule] == [10.0] * 14 + [180.0]
    assert [n for n, _, _ in FACE_PHASES] == [
        "face_+x_up", "face_-x_up", "face_+y_up", "face_-y_up", "face_+z_up", "face_-z_up",
    ]


def test_cornersAreTheEightCubeDiagonals():
    ups = {tuple(round(c * math.sqrt(3.0), 9) for c in up) for _, _, up in CORNER_PHASES}
    assert ups == {(sx, sy, sz) for sx in (1.0, -1.0) for sy in (1.0, -1.0) for sz in (1.0, -1.0)}
    for _, prompt, _ in CORNER_PHASES:
        assert "CORNER" in prompt and "sky" in prompt


def test_eachCornerPromptNamesItsOwnSigns():
    for name, prompt, up in CORNER_PHASES:
        signs = ["+" if c > 0 else "-" for c in up]
        label = f"{signs[0]}x {signs[1]}y {signs[2]}z"
        assert label in prompt
        assert name == "corner_" + label.replace(" ", "")


def test_scheduleDurationsAreConfigurable():
    schedule = phaseSchedule(faceSeconds=2.0, tumbleSeconds=5.0, cornerSeconds=3.0)
    assert [p.durationS for p in schedule] == [2.0] * 6 + [3.0] * 8 + [5.0]


def test_onlyHoldsHaveAnExpectedDirection():
    schedule = phaseSchedule()
    assert all(p.upDevice is not None for p in schedule[:-1])
    assert schedule[-1].upDevice is None


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


def _capture(device=None, faceSeconds=1.0, tumbleSeconds=2.0, hz=10.0, cornerSeconds=None):
    clock = FakeClock()
    device = device or FakeDevice(clock)
    out = io.StringIO()
    err = io.StringIO()
    summary = capture(
        device,
        phaseSchedule(
            faceSeconds=faceSeconds,
            tumbleSeconds=tumbleSeconds,
            cornerSeconds=faceSeconds if cornerSeconds is None else cornerSeconds,
        ),
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
    holds = [n for n, _, _ in FACE_PHASES] + [n for n, _, _ in CORNER_PHASES]
    assert counts == {**{name: 10 for name in holds}, PHASE_TUMBLE: 20}
    assert summary["rows"] == 160


def test_settleTimeIsNotRecorded():
    """The operator re-orients during the settle countdown: those samples are
    mid-motion and belong to no hold, so none is written."""
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


def test_promptsNameEachHoldOnStderr():
    _, _, err = _capture()
    for _, prompt, _ in FACE_PHASES + CORNER_PHASES:
        assert prompt in err
    assert "tumble" in err.lower()


# --- warnings: none on an honest capture, each one provoked on its own -------------

_PER_HOLD = 10  # faceSeconds 1.0 x hz 10


def _honest(**kwargs):
    return _capture(device=HonestDevice(_PER_HOLD, **kwargs), faceSeconds=1.0, tumbleSeconds=2.0, hz=10.0)


def test_anHonestCaptureRaisesNoWarningAtAll():
    """The negative control every warning below is measured against: a live,
    varying magnetometer, every hold still and the right way up."""
    summary, _, err = _honest()
    assert summary["warnings"] == []
    assert "WARNING" not in err
    assert summary["magMissingRows"] == 0


def test_aFrozenMagnetometerIsReported():
    """A constant mag through a capture is a frozen sensor (ARCH-057), not a field."""
    summary, _, err = _honest(frozenMag=True)
    assert "WARNING" in err and "frozen" in err
    assert len(summary["warnings"]) == 1


def test_aJitteryHoldIsReportedByName():
    summary, _, _ = _honest(jitterPhase="corner_+x-y+z")
    assert len(summary["warnings"]) == 1
    assert "corner_+x-y+z" in summary["warnings"][0] and "still" in summary["warnings"][0]


def test_aFaultedGyroOffsetIsNamedAndDoesNotCondemnTheHolds():
    """m4: an A-34 latched offset (~0.5 rad/s) is a CONSTANT rate. Steadiness is
    judged on variation, so the holds are still still -- the one warning names
    the fault, not the operator."""
    summary, _, _ = _honest(gyroOffset=(0.5, 0.0, 0.0))
    assert len(summary["warnings"]) == 1
    assert "A-34" in summary["warnings"][0]
    assert all(p["stillFraction"] == 1.0 for n, p in summary["phases"].items() if n != PHASE_TUMBLE)


def test_aHoldHeldTheWrongWayIsReported():
    """m6: -x face held with +z up is 90 degrees off its label."""
    summary, _, _ = _honest(wrongPhase="face_-x_up")
    assert len(summary["warnings"]) == 1
    assert "face_-x_up" in summary["warnings"][0] and "wrong way" in summary["warnings"][0]


def test_aCornerHeldAsAFaceIsReported():
    """A corner is 54.7 degrees from its nearest face, so a corner held flat on
    a face is caught (> 30)."""
    summary, _, _ = _honest(wrongPhase="corner_+x+y+z")
    assert any("corner_+x+y+z" in w and "wrong way" in w for w in summary["warnings"])


def test_missingMagRowsAreWarned():
    clock = FakeClock()
    summary, _, err = _capture(device=FakeDevice(clock, overflowEvery=4))
    assert any("no magnetometer reading" in w for w in summary["warnings"])
    assert "no magnetometer reading" in err


def test_mainWritesTheCsvAndASummary(tmp_path, capsys, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(tumble_capture, "_clock", clock)
    monkeypatch.setattr(tumble_capture, "_sleep", clock.sleep)
    out = tmp_path / "tumble.csv"
    code = main(
        ["--out", str(out), "--face-seconds", "0.5", "--corner-seconds", "0.5", "--tumble-seconds", "1",
         "--settle-seconds", "0"],
        runner=_runner("inactive"),
        deviceFactory=lambda: FakeDevice(clock),
    )
    assert code == 0
    with open(out, newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 14 * 25 + 50
    summary = json.loads(capsys.readouterr().out)
    assert summary["rows"] == 400
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
