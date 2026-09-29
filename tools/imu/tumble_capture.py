"""ARCH-064 Task 6b: guided hand-tumble capture for the accel + mag calibrations.

ONE capture feeds TWO calibrations (Ruling 27): the six still faces feed the
accelerometer ellipsoid (``accel_cal_cli --ellipsoid``), and the whole capture
-- faces and the slow tumble -- feeds the sensor-intrinsic magnetometer
ellipsoid (``fit_mag_tumble``). Physics: the sensor's own iron and gain errors
rotate WITH the sensor, the car's do not, so a tumble IN PLACE measures only
the sensor's own terms. It must be ROTATION in place: carrying the sensor
through a field gradient (walking it around the car) breaks that.

THE DRIVER (Ruling 30, binding). Samples are read through the PRODUCTION
ARCH-064 build, ``sensor_reader._makeIcm20948Direct`` ->
``icm20948_direct.makeIcm20948Direct``: clean software reset, the ICM's I2C
master NEVER enabled, the AK09916 read directly in bypass, A-34 gyro recovery
run after. The AK09916 triple is mapped into the ICM frame with
``ak09916_bypass.toIcmFrame`` -- the same single seam ``sensor_reader`` applies
it at -- so the captured DEVICE frame is exactly the frame the pipeline
publishes. The older ARCH-027 probe tools are NOT used: they assume the
collector left bypass enabled (false under the deployed master mode) and their
magnetometer frame is not the ARCH-064 axis map.

THE BUS. The collector (``eclipse-obd``) must be STOPPED: two I2C masters
interleaving bank switches produce readings that look plausible and are not.
This tool refuses unless ``systemctl is-active eclipse-obd`` reports
``inactive`` or ``failed`` -- and refuses if it cannot ask.

OUTPUT. A CSV with the real ``edr_imu_sample`` column names (Ruling 20) plus
``phase``, in the DEVICE frame, units m/s^2, rad/s, uT. A magnetometer read
that fails (ST2 overflow, a bus error) leaves the mag columns EMPTY for that
row rather than repeating or zeroing them -- a fabricated value would enter the
fit as data. A JSON summary goes to stdout; prompts and warnings to stderr.

Usage on chi-eclipse-01, from the ARCH-064 checkout, with its venv::

    sudo systemctl stop eclipse-obd
    PYTHONPATH=src:. ~/arch064-venv/bin/python -m tools.imu.tumble_capture \\
        --out ~/arch064/tumble.csv
    sudo systemctl start eclipse-obd

Then, off the Pi or on it::

    python -m tools.imu.accel_cal_cli ~/arch064/tumble.csv --ellipsoid
    python -m tools.imu.fit_mag_tumble ~/arch064/tumble.csv > sensor_mag_cal.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TextIO

from pi.sensors.accel_cal import DEFAULT_MAX_GYRO_RAD_S
from pi.sensors.ak09916_bypass import toIcmFrame

SERVICE_NAME = "eclipse-obd"

# ``systemctl is-active`` states in which the collector holds no bus.
_STOPPED_STATES = frozenset({"inactive", "failed"})

CSV_COLUMNS = (
    "ts_capture",
    "phase",
    "accel_x",
    "accel_y",
    "accel_z",
    "gyro_x",
    "gyro_y",
    "gyro_z",
    "mag_x",
    "mag_y",
    "mag_z",
)

FACE_PHASES = (
    ("face_+x_up", "Hold the enclosure STILL with its +X axis pointing UP"),
    ("face_-x_up", "Hold the enclosure STILL with its -X axis pointing UP"),
    ("face_+y_up", "Hold the enclosure STILL with its +Y axis pointing UP"),
    ("face_-y_up", "Hold the enclosure STILL with its -Y axis pointing UP"),
    ("face_+z_up", "Hold the enclosure STILL with its +Z axis pointing UP"),
    ("face_-z_up", "Hold the enclosure STILL with its -Z axis pointing UP"),
)
PHASE_TUMBLE = "tumble"
_TUMBLE_PROMPT = (
    "TUMBLE: rotate the enclosure SLOWLY and continuously through ALL axes -- "
    "every face toward the sky and the ground, and every heading. Rotate it IN "
    "PLACE: do not walk it around the car."
)

DEFAULT_FACE_S = 10.0
DEFAULT_TUMBLE_S = 180.0
DEFAULT_SETTLE_S = 5.0
DEFAULT_HZ = 50.0

# ARCH-057's frozen-magnetometer rule: a bit-identical reading held for 2 s of
# wall clock is a frozen sensor, not a field.
FROZEN_MAG_DWELL_S = 2.0

# A face in which fewer than this fraction of samples were still (gyro under
# the accel calibration's own quasi-static threshold) will mostly be discarded
# by the accel fit -- the operator is told while they can still redo it.
MIN_STILL_FRACTION = 0.5


@dataclass(frozen=True)
class Phase:
    """One guided step: a name written to every row, a prompt, a duration."""

    name: str
    prompt: str
    durationS: float


def phaseSchedule(
    faceSeconds: float = DEFAULT_FACE_S, tumbleSeconds: float = DEFAULT_TUMBLE_S
) -> list[Phase]:
    """(a) six faces x ``faceSeconds`` still, then (b) ``tumbleSeconds`` of tumbling."""
    phases = [Phase(name, prompt, faceSeconds) for name, prompt in FACE_PHASES]
    phases.append(Phase(PHASE_TUMBLE, _TUMBLE_PROMPT, tumbleSeconds))
    return phases


def collectorStopped(
    serviceName: str = SERVICE_NAME, runner: Callable[..., Any] = subprocess.run
) -> tuple[bool, str]:
    """(stopped, reason). Stopped only on a POSITIVE answer; unknowable is not stopped."""
    try:
        result = runner(
            ["systemctl", "is-active", serviceName],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"cannot ask systemctl whether {serviceName} is running ({exc})"
    state = (result.stdout or "").strip()
    if state in _STOPPED_STATES:
        return True, f"{serviceName} is {state}"
    return False, f"{serviceName} is {state or 'in an unknown state'}; stop it first"


def _readSample(device: Any) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...] | None]:
    """One burst: accel first (it triggers the ICM read gyro reuses), then mag."""
    accel = tuple(float(v) for v in device.acceleration)
    gyro = tuple(float(v) for v in device.gyro)
    try:
        mag: tuple[float, ...] | None = toIcmFrame(tuple(float(v) for v in device.magnetic))
    except Exception:  # noqa: BLE001 -- a mag fault must not cost the accel/gyro row
        mag = None
    return accel, gyro, mag


class _PhaseStats:
    def __init__(self) -> None:
        self.rows = 0
        self.still = 0
        self.magMissing = 0
        self.accelNormSum = 0.0

    def add(self, accel, gyro, mag) -> None:
        self.rows += 1
        self.accelNormSum += math.sqrt(sum(v * v for v in accel))
        if math.sqrt(sum(v * v for v in gyro)) <= DEFAULT_MAX_GYRO_RAD_S:
            self.still += 1
        if mag is None:
            self.magMissing += 1

    def toDict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "stillFraction": round(self.still / self.rows, 3) if self.rows else 0.0,
            "meanAccelNormMs2": round(self.accelNormSum / self.rows, 4) if self.rows else None,
            "magMissingRows": self.magMissing,
        }


def capture(
    device: Any,
    schedule: list[Phase],
    out: TextIO,
    *,
    hz: float = DEFAULT_HZ,
    settleS: float = DEFAULT_SETTLE_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    log: TextIO = sys.stderr,
) -> dict[str, Any]:
    """Run the guided schedule, writing one CSV row per sample to ``out``.

    Returns the summary dict (also the stdout JSON of :func:`main`).
    """
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    period = 1.0 / hz
    perPhase: dict[str, _PhaseStats] = {}
    warnings: list[str] = []
    lastMag: tuple[float, ...] | None = None
    frozenSince: float | None = None
    longestFrozenS = 0.0

    for index, phase in enumerate(schedule, start=1):
        print(f"\n[{index}/{len(schedule)}] {phase.prompt}", file=log)
        remaining = settleS
        while remaining > 0:
            print(f"  starting in {remaining:.0f} s ...", file=log)
            step = min(1.0, remaining)
            sleep(step)
            remaining -= step
        print(f"  RECORDING {phase.name} for {phase.durationS:.0f} s", file=log)
        stats = perPhase.setdefault(phase.name, _PhaseStats())
        start = clock()
        nextReport = start + 30.0
        for k in range(int(round(phase.durationS * hz))):
            target = start + k * period
            now = clock()
            if target > now:
                sleep(target - now)
            ts = clock()
            accel, gyro, mag = _readSample(device)
            stats.add(accel, gyro, mag)
            writer.writerow(
                [repr(ts), phase.name, *map(repr, accel), *map(repr, gyro)]
                + (list(map(repr, mag)) if mag is not None else ["", "", ""])
            )
            if mag is not None and mag == lastMag:
                frozenSince = ts if frozenSince is None else frozenSince
                longestFrozenS = max(longestFrozenS, ts - frozenSince)
            elif mag is not None:
                frozenSince = None
            if mag is not None:
                lastMag = mag
            if ts >= nextReport:
                print(f"  ... {phase.durationS - (ts - start):.0f} s left", file=log)
                nextReport += 30.0
        print(f"  done: {phase.name}", file=log)
        if phase.name != PHASE_TUMBLE and stats.rows and stats.still / stats.rows < MIN_STILL_FRACTION:
            warnings.append(
                f"{phase.name}: only {stats.still}/{stats.rows} samples were still "
                f"(gyro <= {DEFAULT_MAX_GYRO_RAD_S} rad/s); the accel fit will discard "
                "the rest -- redo the capture holding that face steadier"
            )

    if longestFrozenS >= FROZEN_MAG_DWELL_S:
        warnings.append(
            f"magnetometer reading was bit-identical for {longestFrozenS:.1f} s "
            f"(>= {FROZEN_MAG_DWELL_S} s): the AK09916 looks frozen -- the mag fit "
            "is not valid on this capture"
        )
    for warning in warnings:
        print(f"WARNING: {warning}", file=log)

    return {
        "rows": sum(s.rows for s in perPhase.values()),
        "magMissingRows": sum(s.magMissing for s in perPhase.values()),
        "longestFrozenMagS": round(longestFrozenS, 3),
        "hz": hz,
        "frame": "device",
        "phases": {name: s.toDict() for name, s in perPhase.items()},
        "warnings": warnings,
    }


def _productionDevice() -> Any:  # pragma: no cover -- real-hardware glue (Pi only)
    """The ARCH-064 direct build, exactly as the collector constructs it."""
    from pi.sensors.sensor_reader import _makeIcm20948Direct

    return _makeIcm20948Direct()


# Module-level so a test can substitute a fake clock for main().
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep


def main(
    argv: list[str] | None = None,
    *,
    runner: Callable[..., Any] = subprocess.run,
    deviceFactory: Callable[[], Any] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Guided hand-tumble IMU capture (ARCH-064 Task 6b)")
    parser.add_argument("--out", required=True, help="CSV path for the raw DEVICE-frame samples")
    parser.add_argument("--face-seconds", type=float, default=DEFAULT_FACE_S)
    parser.add_argument("--tumble-seconds", type=float, default=DEFAULT_TUMBLE_S)
    parser.add_argument("--settle-seconds", type=float, default=DEFAULT_SETTLE_S)
    parser.add_argument("--hz", type=float, default=DEFAULT_HZ)
    args = parser.parse_args(argv)

    stopped, reason = collectorStopped(runner=runner)
    if not stopped:
        print(json.dumps({"refused": reason}, indent=2))
        return 2

    device = (deviceFactory or _productionDevice)()
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        summary = capture(
            device,
            phaseSchedule(args.face_seconds, args.tumble_seconds),
            handle,
            hz=args.hz,
            settleS=args.settle_seconds,
            clock=_clock,
            sleep=_sleep,
        )
    summary["out"] = args.out
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
