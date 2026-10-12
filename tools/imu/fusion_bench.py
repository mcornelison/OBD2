"""ARCH-027: compare our shipped pitch filter against imufusion and ahrs, on real drive data.

THE QUESTION THE CIO ASKED: do the libraries that claim high accuracy actually
beat what we ship, once the inputs are CALIBRATED?

That last clause is what makes this different from the 2026-09-15 replay. Every
number in that round came from uncalibrated inputs -- a mis-scaled accelerometer,
an uncorrected gyro bias, and a magnetometer carrying a ~30 uT hard-iron offset.
Ranking estimators on corrupted inputs measures their tolerance for corruption,
not their accuracy.

ESTIMATORS
    shipped      our PitchFusion, imported from src -- never re-implemented. An
                 earlier attempt to re-implement it failed its own equivalence
                 check by 11.6 deg and was discarded.
    imufusion    xio Fusion 1.3.3, default and tuned.
    madgwick     ahrs 0.4.0.
    mahony       ahrs 0.4.0.

⚠️ UNITS ARE A REAL HAZARD HERE. Our data is rad/s and m/s^2; imufusion's
convention is deg/s and g. A units error produces a confident, plausible, wrong
answer -- exactly the failure this project keeps paying for -- so conversion
happens once, at the boundary, and is unit-tested.

⚠️ FAIRNESS. The shipped filter is fed OBD SPEED via observeSpeed, because ZUPT
on a real zero-velocity measurement is its one genuine advantage over libraries
that must infer stillness from the gyro. Removing it would rig the comparison.

⚠️ A-34 CONSTRAINT. imufusion's Bias learner must keep stationary_threshold at
its 3 deg/s default. At 50 deg/s it absorbs the 14-30 deg/s latched fault
entirely and hides it (measured 2026-09-15): a loose bias learner becomes a
fault concealer.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import UTC

import numpy as np

from tools.imu.gps_truth import (
    findClockOffset,
    gradeWindows,
    loadGpx,
    longitudinalAccelFromSpeed,
    scoreGrade,
    scoreHeading,
)

STANDARD_GRAVITY_MS2 = 9.80665
RAD_TO_DEG = 180.0 / math.pi

# Frame B, settled by direct tilt test 2026-09-16 (+Y = tail) and by
# accel_y vs d(SPEED)/dt on drives 71 and 77.
def frameB(vectors: np.ndarray) -> np.ndarray:
    """(fwd, left, up) = (-y, +x, +z) in raw sensor axes."""
    return np.stack([-vectors[:, 1], vectors[:, 0], vectors[:, 2]], axis=1)


@dataclass
class Calibration:
    """Corrections applied to raw sensor vectors before fusion.

    All default to identity, so an uncalibrated run is the same code path with
    no corrections -- not a different one.
    """

    accelScale: float = 1.0
    accelBiasMs2: tuple[float, float, float] = (0.0, 0.0, 0.0)
    gyroBiasRadS: tuple[float, float, float] = (0.0, 0.0, 0.0)
    magOffsetUt: tuple[float, float, float] = (0.0, 0.0, 0.0)
    magAxisFix: bool = False
    label: str = "raw"

    def applyAccel(self, accel: np.ndarray) -> np.ndarray:
        return (accel - np.array(self.accelBiasMs2)) * self.accelScale

    def applyGyro(self, gyro: np.ndarray) -> np.ndarray:
        return gyro - np.array(self.gyroBiasRadS)

    def applyMag(self, mag: np.ndarray) -> np.ndarray:
        out = mag * np.array([1.0, -1.0, -1.0]) if self.magAxisFix else mag
        return out - np.array(self.magOffsetUt)


def toImufusionUnits(gyroRadS: np.ndarray, accelMs2: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """rad/s -> deg/s, m/s^2 -> g. The xio convention, applied once."""
    return gyroRadS * RAD_TO_DEG, accelMs2 / STANDARD_GRAVITY_MS2


@dataclass
class Result:
    """Per-estimator output, aligned to the sample timebase."""

    name: str
    pitchDeg: np.ndarray
    headingDeg: np.ndarray | None = None
    accelIgnoredFraction: float | None = None
    notes: dict[str, object] = field(default_factory=dict)


def loadImu(path: str) -> dict[str, np.ndarray]:
    rows = list(csv.DictReader(open(path, newline="")))
    keep = [r for r in rows if r["accel_x"] and r["gyro_x"]]
    return {
        "tCapture": np.array([float(r["ts_capture"]) for r in keep]),
        "tsUtc": np.array([r["ts_utc"] for r in keep]),
        "accel": np.array(
            [[float(r["accel_x"]), float(r["accel_y"]), float(r["accel_z"])] for r in keep]
        ),
        "gyro": np.array(
            [[float(r["gyro_x"]), float(r["gyro_y"]), float(r["gyro_z"])] for r in keep]
        ),
        "mag": np.array(
            [
                [
                    float(r["mag_x"]) if r["mag_x"] else np.nan,
                    float(r["mag_y"]) if r["mag_y"] else np.nan,
                    float(r["mag_z"]) if r["mag_z"] else np.nan,
                ]
                for r in keep
            ]
        ),
    }


def loadSpeed(path: str) -> list[tuple[str, float]]:
    rows = list(csv.DictReader(open(path, newline="")))
    return [(r["timestamp"], float(r["value"])) for r in rows if r["parameter_name"] == "SPEED"]


def runShipped(
    data: dict[str, np.ndarray], cal: Calibration, speedRows: list[tuple[float, float]]
) -> Result:
    """Our PitchFusion, imported from src. Fed OBD SPEED so ZUPT can work."""
    from pi.sensors.pitch_fusion import PitchFusion

    fusion = PitchFusion()
    accel = frameB(cal.applyAccel(data["accel"]))
    gyro = frameB(cal.applyGyro(data["gyro"]))
    t = data["tCapture"]
    pitch = np.full(len(t), np.nan)
    speedIndex = 0

    for n in range(len(t)):
        while speedIndex < len(speedRows) and speedRows[speedIndex][0] <= t[n]:
            fusion.observeSpeed(speedRows[speedIndex][1], speedRows[speedIndex][0])
            speedIndex += 1
        fusion.update(tuple(accel[n]), tuple(gyro[n]), float(t[n]))
        value = fusion.pitchRad
        pitch[n] = np.nan if value is None else math.degrees(value)

    return Result(name=f"shipped[{cal.label}]", pitchDeg=pitch)


def runImufusion(
    data: dict[str, np.ndarray], cal: Calibration, gain: float, accelRejection: float, useBias: bool
) -> Result:
    import imufusion

    accel = frameB(cal.applyAccel(data["accel"]))
    gyro = frameB(cal.applyGyro(data["gyro"]))
    mag = frameB(cal.applyMag(data["mag"]))
    t = data["tCapture"]

    gyroDeg, accelG = toImufusionUnits(gyro, accel)
    sampleRate = int(round(1.0 / np.median(np.diff(t))))

    settings = imufusion.AhrsSettings()
    settings.convention = imufusion.CONVENTION_NWU
    settings.gain = gain
    settings.acceleration_rejection = accelRejection
    settings.rejection_timeout = 5 * sampleRate
    settings.sample_rate = sampleRate

    ahrs = imufusion.Ahrs()
    ahrs.set_settings(settings)

    bias = imufusion.Bias() if useBias else None
    if bias is not None:
        biasSettings = imufusion.BiasSettings()
        biasSettings.sample_rate = sampleRate
        # 🔴 Left at the 3 deg/s default on purpose. See the module docstring:
        # raising it lets the learner swallow the A-34 latched fault.
        bias.set_settings(biasSettings)

    pitch = np.full(len(t), np.nan)
    heading = np.full(len(t), np.nan)
    ignored = 0

    for n in range(len(t)):
        dt = float(t[n] - t[n - 1]) if n else 1.0 / sampleRate
        if dt <= 0 or dt > 1.0:
            dt = 1.0 / sampleRate
        ahrs.set_sample_period(dt)
        g = gyroDeg[n].astype(float)
        if bias is not None:
            g = bias.update(g)
        a = accelG[n].astype(float)
        m = mag[n].astype(float)
        if np.all(np.isfinite(m)):
            ahrs.update(g, a, m)
        else:
            ahrs.update_no_magnetometer(g, a)
        euler = imufusion.quaternion_to_euler(ahrs.get_quaternion())
        # NWU + our frame B body axes: roll about fwd, pitch about left, yaw about up.
        pitch[n] = euler[1]
        heading[n] = euler[2] % 360.0
        if ahrs.get_internal_states().accelerometer_ignored:
            ignored += 1

    label = f"imufusion[gain={gain},rej={accelRejection},bias={'on' if useBias else 'off'}][{cal.label}]"
    return Result(
        name=label,
        pitchDeg=pitch,
        headingDeg=heading,
        accelIgnoredFraction=ignored / max(1, len(t)),
        notes={"sampleRateHz": sampleRate},
    )


def runAhrsFilter(data: dict[str, np.ndarray], cal: Calibration, which: str) -> Result:
    from ahrs.filters import Madgwick, Mahony

    accel = frameB(cal.applyAccel(data["accel"]))
    gyro = frameB(cal.applyGyro(data["gyro"]))
    t = data["tCapture"]
    frequency = float(1.0 / np.median(np.diff(t)))

    filt = Madgwick(frequency=frequency) if which == "madgwick" else Mahony(frequency=frequency)
    q = np.array([1.0, 0.0, 0.0, 0.0])
    pitch = np.full(len(t), np.nan)

    for n in range(len(t)):
        q = filt.updateIMU(q, gyr=gyro[n], acc=accel[n])
        if q is None:
            break
        w, x, y, z = q
        sinPitch = 2.0 * (w * y - z * x)
        pitch[n] = math.degrees(math.asin(max(-1.0, min(1.0, sinPitch))))

    return Result(name=f"{which}[{cal.label}]", pitchDeg=pitch)


def phantomCoupling(pitchDeg: np.ndarray, longitudinalG: np.ndarray) -> float:
    """Slope of pitch against longitudinal acceleration while moving.

    True grade does not track acceleration, so the ideal is ~0. A filter that
    mistakes braking for a hill scores high here.
    """
    mask = np.isfinite(pitchDeg) & np.isfinite(longitudinalG)
    if mask.sum() < 10:
        return float("nan")
    return float(np.polyfit(longitudinalG[mask], pitchDeg[mask], 1)[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fusion estimator comparison (ARCH-027)")
    parser.add_argument("--imu", required=True)
    parser.add_argument("--speed", required=True)
    parser.add_argument("--gpx", required=True, help="GPS truth track for scoring")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args(argv)

    data = loadImu(args.imu)
    speedRaw = loadSpeed(args.speed)

    # Speed timestamps are wall clock; the IMU timebase is monotonic capture.
    # Map one to the other by their shared start, the same alignment gps_truth.py uses.
    from datetime import datetime

    def epoch(s: str) -> float:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()

    imuEpoch = np.array([epoch(s) for s in data["tsUtc"]])
    offset = float(np.median(imuEpoch - data["tCapture"]))
    speedRows = [(epoch(ts) - offset, value) for ts, value in speedRaw]

    # GPS truth. Both the IMU samples and the OBD speed rows are put on wall
    # clock, then the GPS track is aligned to that clock by matching speed --
    # the only signal both instruments measure independently.
    obdWallTime = np.array([epoch(ts) for ts, _ in speedRaw])
    obdSpeedKph = np.array([value for _, value in speedRaw])
    sampleWallTime = data["tCapture"] + offset
    track = loadGpx(args.gpx)
    clockOffsetS = findClockOffset(track, obdWallTime, obdSpeedKph)

    raw = Calibration(label="raw")
    calibrated = Calibration(
        accelScale=1.0 / 1.0185,
        gyroBiasRadS=(-0.000217, 0.012750, 0.002730),
        magOffsetUt=(-5.65, 13.26, 26.90),
        magAxisFix=True,
        label="cal",
    )

    results: list[Result] = []
    for cal in (raw, calibrated):
        results.append(runShipped(data, cal, speedRows))
        results.append(runImufusion(data, cal, gain=0.5, accelRejection=10.0, useBias=True))
        results.append(runImufusion(data, cal, gain=0.1, accelRejection=10.0, useBias=True))
        results.append(runAhrsFilter(data, cal, "madgwick"))
        results.append(runAhrsFilter(data, cal, "mahony"))

    # 🔴 Longitudinal acceleration comes from d(OBD SPEED)/dt, NOT from the
    # accelerometer. The previous version used the accelerometer's own forward
    # axis, which on a tilted sensor is dominated by gravity -- i.e. by pitch --
    # so the metric regressed pitch against pitch and returned nonsense.
    longitudinalG = longitudinalAccelFromSpeed(obdWallTime, obdSpeedKph, sampleWallTime)

    summary = []
    for result in results:
        finite = np.isfinite(result.pitchDeg)
        gradePct = np.tan(np.radians(result.pitchDeg)) * 100.0
        gradeScore = scoreGrade(
            gradeWindows(track, sampleWallTime, gradePct, clockOffsetS)
        )
        entry: dict[str, object] = {
            "estimator": result.name,
            "validFraction": round(float(finite.mean()), 4),
            "pitchMeanDeg": round(float(np.nanmean(result.pitchDeg)), 3),
            "pitchSdDeg": round(float(np.nanstd(result.pitchDeg)), 3),
            "gradeVsGps": {
                key: (None if isinstance(value, float) and math.isnan(value) else round(value, 3))
                for key, value in gradeScore.items()
            },
            "phantomCouplingDegPerG": round(
                phantomCoupling(result.pitchDeg, longitudinalG), 3
            ),
            "accelIgnoredFraction": (
                None
                if result.accelIgnoredFraction is None
                else round(result.accelIgnoredFraction, 4)
            ),
        }
        if result.headingDeg is not None:
            headingScore = scoreHeading(
                track, sampleWallTime, result.headingDeg, clockOffsetS
            )
            entry["headingVsGps"] = {
                key: (None if isinstance(value, float) and math.isnan(value) else round(value, 3))
                for key, value in headingScore.items()
            }
        if result.notes:
            entry["notes"] = result.notes
        summary.append(entry)

    output = {
        "samples": len(data["tCapture"]),
        "speedRows": len(speedRows),
        "gpsPoints": track.samples,
        "clockOffsetS": round(clockOffsetS, 3),
        "calibration": {
            "accelScale": round(calibrated.accelScale, 5),
            "gyroBiasRadS": calibrated.gyroBiasRadS,
            "magOffsetUt": calibrated.magOffsetUt,
            "magAxisFix": calibrated.magAxisFix,
            "provisional": (
                "mag offset carries soft iron (ellipticity 1.78) and the mount is "
                "temporary; accel scale is a stationary estimate, not a fitted "
                "bias+scale. Relative comparison only."
            ),
        },
        "results": summary,
    }
    text = json.dumps(output, indent=2)
    print(text)
    if args.json_out:
        with open(args.json_out, "w") as handle:
            handle.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
