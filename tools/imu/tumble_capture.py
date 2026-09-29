"""ARCH-064 Task 6b: guided hand-tumble capture for the accel + mag calibrations.

ONE capture feeds TWO calibrations (Ruling 27): the still HOLDS -- six faces and
eight corners -- feed the accelerometer ellipsoid (``accel_cal_cli
--ellipsoid``), and the whole capture -- holds and the slow tumble -- feeds the
sensor-intrinsic magnetometer ellipsoid (``fit_mag_tumble``). Physics: the
sensor's own iron and gain errors rotate WITH the sensor, the car's do not, so
a tumble IN PLACE measures only the sensor's own terms. It must be ROTATION in
place: carrying the sensor through a field gradient (walking it around the
car) breaks that.

WHY CORNERS (Ruling 31). Six axis-aligned faces fix the accel offset and
per-axis gain but leave the CROSS-AXIS terms unobserved (MEASURED: they wander
+/-0.01 between interleaved subsets; off-axis |a| errs up to ~1 %). Eight
still corner holds -- (+/-1, +/-1, +/-1)/sqrt(3) up -- make them observable
(MEASURED: every orientation within 0.3 % of g).

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

WARNINGS (stderr, and in the summary), so the operator can redo a step while
still at the car:

* a hold that was not still -- judged by the gyro's VARIATION within the hold
  (deviation from the hold's own median rate), never its raw magnitude, so an
  A-34 faulted gyro offset does not condemn every hold;
* a gyro offset that looks faulted (A-34): median raw |gyro| over the holds
  above ``FAULTED_GYRO_OFFSET_RAD_S``;
* a smaller gyro offset that the accel FITTER will still refuse: median raw
  |gyro| above ``accel_cal.DEFAULT_MAX_GYRO_RAD_S`` (0.05) -- the fitter's
  quasi-static gate rejects such holds (ARCH-064 Ruling 35, T6b);
* a hold whose mean gravity direction is more than ``WRONG_HOLD_DEG`` from the
  one its prompt asked for (held the wrong way up);
* a magnetometer bit-identical for >= 2 s (frozen, ARCH-057);
* any row whose magnetometer read failed.

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
import statistics
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

_S3 = 1.0 / math.sqrt(3.0)

# (name, prompt, expected UP direction in the DEVICE frame). At rest the
# accelerometer reads +g along whichever device direction points UP.
FACE_PHASES = (
    ("face_+x_up", "Hold the enclosure STILL with its +X axis pointing UP", (1.0, 0.0, 0.0)),
    ("face_-x_up", "Hold the enclosure STILL with its -X axis pointing UP", (-1.0, 0.0, 0.0)),
    ("face_+y_up", "Hold the enclosure STILL with its +Y axis pointing UP", (0.0, 1.0, 0.0)),
    ("face_-y_up", "Hold the enclosure STILL with its -Y axis pointing UP", (0.0, -1.0, 0.0)),
    ("face_+z_up", "Hold the enclosure STILL with its +Z axis pointing UP", (0.0, 0.0, 1.0)),
    ("face_-z_up", "Hold the enclosure STILL with its -Z axis pointing UP", (0.0, 0.0, -1.0)),
)


def _cornerPhase(sx: int, sy: int, sz: int) -> tuple[str, str, tuple[float, float, float]]:
    def tag(sign: int, axis: str) -> str:
        return f"{'+' if sign > 0 else '-'}{axis}"

    label = f"{tag(sx, 'x')} {tag(sy, 'y')} {tag(sz, 'z')}"
    return (
        f"corner_{label.replace(' ', '')}",
        f"CORNER: hold STILL with {label} all tilted UP equally -- the "
        f"({label}) corner pointing straight at the sky, the opposite corner at the ground",
        (sx * _S3, sy * _S3, sz * _S3),
    )


CORNER_PHASES = tuple(
    _cornerPhase(sx, sy, sz) for sx in (1, -1) for sy in (1, -1) for sz in (1, -1)
)

PHASE_TUMBLE = "tumble"
_TUMBLE_PROMPT = (
    "TUMBLE: rotate the enclosure SLOWLY and continuously through ALL axes -- "
    "every face toward the sky and the ground, and every heading. Rotate it IN "
    "PLACE: do not walk it around the car."
)

DEFAULT_FACE_S = 10.0
DEFAULT_CORNER_S = 10.0
DEFAULT_TUMBLE_S = 180.0
DEFAULT_SETTLE_S = 5.0
DEFAULT_HZ = 50.0

# ARCH-057's frozen-magnetometer rule: a bit-identical reading held for 2 s of
# wall clock is a frozen sensor, not a field.
FROZEN_MAG_DWELL_S = 2.0

# A hold in which fewer than this fraction of samples were still will mostly
# be discarded by the accel fit -- the operator is told while they can redo it.
MIN_STILL_FRACTION = 0.5

# A-34: a healthy gyro at rest reads ~0.015 rad/s; a latched fault sits at
# ~0.5 rad/s. 0.1 is well clear of both.
FAULTED_GYRO_OFFSET_RAD_S = 0.1

# A hold's mean gravity direction further than this from the prompt's is the
# enclosure held the wrong way up. Faces and corners are >= 54.7 degrees
# apart, so 30 cannot confuse one for its neighbour, and it tolerates a hand
# that holds a face 10-15 degrees off.
WRONG_HOLD_DEG = 30.0


@dataclass(frozen=True)
class Phase:
    """One guided step. ``upDevice`` is the expected gravity direction for a
    still hold; None for the tumble."""

    name: str
    prompt: str
    durationS: float
    upDevice: tuple[float, float, float] | None = None


def phaseSchedule(
    faceSeconds: float = DEFAULT_FACE_S,
    tumbleSeconds: float = DEFAULT_TUMBLE_S,
    cornerSeconds: float = DEFAULT_CORNER_S,
) -> list[Phase]:
    """(a) six faces, (b) eight corners, each still; then (c) the tumble."""
    phases = [Phase(n, p, faceSeconds, up) for n, p, up in FACE_PHASES]
    phases += [Phase(n, p, cornerSeconds, up) for n, p, up in CORNER_PHASES]
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


def _norm(v) -> float:
    return math.sqrt(sum(c * c for c in v))


class _PhaseStats:
    def __init__(self) -> None:
        self.accel: list[tuple[float, ...]] = []
        self.gyro: list[tuple[float, ...]] = []
        self.magMissing = 0

    def add(self, accel, gyro, mag) -> None:
        self.accel.append(accel)
        self.gyro.append(gyro)
        if mag is None:
            self.magMissing += 1

    @property
    def rows(self) -> int:
        return len(self.accel)

    def stillFraction(self) -> float:
        """Fraction of samples whose rate deviates from the hold's OWN median
        rate by at most the quasi-static threshold -- variation, not magnitude."""
        if not self.gyro:
            return 0.0
        median = [statistics.median(g[i] for g in self.gyro) for i in range(3)]
        still = sum(
            1 for g in self.gyro if _norm([g[i] - median[i] for i in range(3)]) <= DEFAULT_MAX_GYRO_RAD_S
        )
        return still / len(self.gyro)

    def meanUp(self) -> tuple[float, float, float] | None:
        if not self.accel:
            return None
        mean = [sum(a[i] for a in self.accel) / len(self.accel) for i in range(3)]
        n = _norm(mean)
        return None if n == 0.0 else (mean[0] / n, mean[1] / n, mean[2] / n)

    def toDict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "stillFraction": round(self.stillFraction(), 3),
            "meanAccelNormMs2": round(sum(_norm(a) for a in self.accel) / self.rows, 4) if self.rows else None,
            "magMissingRows": self.magMissing,
        }


def _holdWarnings(schedule: list[Phase], perPhase: dict[str, _PhaseStats]) -> list[str]:
    warnings: list[str] = []
    holdGyroNorms: list[float] = []
    for phase in schedule:
        stats = perPhase.get(phase.name)
        if phase.upDevice is None or stats is None or not stats.rows:
            continue
        holdGyroNorms.extend(_norm(g) for g in stats.gyro)
        still = stats.stillFraction()
        if still < MIN_STILL_FRACTION:
            warnings.append(
                f"{phase.name}: only {100.0 * still:.0f} % of samples were still (gyro "
                f"varied by more than {DEFAULT_MAX_GYRO_RAD_S} rad/s about its own median); "
                "redo the capture holding that orientation steadier"
            )
        up = stats.meanUp()
        if up is not None:
            dot = max(-1.0, min(1.0, sum(u * e for u, e in zip(up, phase.upDevice, strict=True))))
            angle = math.degrees(math.acos(dot))
            if angle > WRONG_HOLD_DEG:
                warnings.append(
                    f"{phase.name}: gravity was {angle:.0f} degrees from the requested "
                    f"orientation (> {WRONG_HOLD_DEG:.0f}) -- the enclosure was held the "
                    "wrong way; redo that hold"
                )
    medianGyro = statistics.median(holdGyroNorms) if holdGyroNorms else None
    if medianGyro is not None and medianGyro > FAULTED_GYRO_OFFSET_RAD_S:
        warnings.append(
            f"gyro offset looks faulted (A-34): median raw |gyro| during the still holds "
            f"was {medianGyro:.3f} rad/s (> {FAULTED_GYRO_OFFSET_RAD_S}); "
            "the accel fit's quasi-static gate will reject the holds -- restart the "
            "capture so A-34 recovery runs"
        )
    elif medianGyro is not None and medianGyro > DEFAULT_MAX_GYRO_RAD_S:
        # ARCH-064 Ruling 35 (T6b): accel_cal_cli drops every hold whose RAW
        # |gyro| exceeds DEFAULT_MAX_GYRO_RAD_S (0.05), but the A-34 warning
        # above starts at 0.1 -- between the two, every hold was silently thrown
        # away by the fitter with nothing said at capture time.
        warnings.append(
            f"median raw |gyro| during the still holds was {medianGyro:.3f} rad/s "
            f"(> {DEFAULT_MAX_GYRO_RAD_S}, the accel fitter's limit): the fitter's "
            "quasi-static gate will reject these holds; recover the gyro and re-run"
        )
    return warnings


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

    warnings = _holdWarnings(schedule, perPhase)
    if longestFrozenS >= FROZEN_MAG_DWELL_S:
        warnings.append(
            f"magnetometer reading was bit-identical for {longestFrozenS:.1f} s "
            f"(>= {FROZEN_MAG_DWELL_S} s): the AK09916 looks frozen -- the mag fit "
            "is not valid on this capture"
        )
    magMissing = sum(s.magMissing for s in perPhase.values())
    if magMissing > 0:
        warnings.append(
            f"{magMissing} row(s) have no magnetometer reading (read failed or ST2 "
            "overflow); the mag fit skips them -- many means a bus or sensor fault"
        )
    for warning in warnings:
        print(f"WARNING: {warning}", file=log)

    return {
        "rows": sum(s.rows for s in perPhase.values()),
        "magMissingRows": magMissing,
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
    parser.add_argument("--corner-seconds", type=float, default=DEFAULT_CORNER_S)
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
            phaseSchedule(args.face_seconds, args.tumble_seconds, args.corner_seconds),
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
