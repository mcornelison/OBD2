################################################################################
# File Name: characterize_magnetometer.py
# Purpose/Description: US-565 EMPIRICAL characterization harness for the latched
#                      AK09916 magnetometer behind the ICM-20948's auxiliary I2C
#                      master. Sweeps candidate acquisition levers on the REAL
#                      chip and reports, per trial, the DISTINCT-value count of
#                      every magnetometer axis alongside accel/gyro as LIVE
#                      CONTROL channels. Exists because US-565 forbids a guessed
#                      CNTL2 value: in this subsystem a plausible-looking number
#                      has lied three times in one week, so the setting must be
#                      chosen by measurement and the measurement must be
#                      reproducible by anyone. Read-only with respect to the
#                      repo; it writes nothing but its own JSON report.
#
#                      SAFETY: refuses to run while eclipse-obd.service is active.
#                      The ICM-20948 is BANK-SWITCHED, so two processes driving it
#                      concurrently read each other's bank and can wedge the bus --
#                      that is not a hypothetical, it happened on 2026-08-20.
#
#                      Usage (on the Pi, service stopped):
#                        sudo systemctl stop eclipse-obd
#                        ~/obd2-venv/bin/python characterize_magnetometer.py \
#                            --seconds 20 --out /tmp/mag-characterization.json
#                        sudo systemctl start eclipse-obd
# Author: Rex (US-565)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-565) | Initial -- lever sweep (CNTL2 rate, aux-master
#               |              | duty-cycle bit, slave0 re-arm ordering), direct
#               |              | CNTL2 readback, live control channels.
# 2026-08-21    | Rex (US-565) | Run 1 INVALIDATED ITSELF: every slave4 readback
#               |              | reported "transfer did not finish", so the CNTL2
#               |              | WRITES on that same path had not landed either
#               |              | and the rate levers measured nothing. Slave4 is
#               |              | now driven with slave0 quiesced, every write is
#               |              | VERIFIED by readback, and change-index tracking
#               |              | separates "a few updates at init" from "updating".
# ================================================================================
################################################################################

"""Sweep magnetometer acquisition levers on the real ICM-20948 and measure them."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

# --- AK09916 registers (datasheet SMDSW.020-2OZ page 9; the same values the
# --- adafruit driver uses, restated here so this probe does not depend on the
# --- private names of a library whose behaviour is itself under investigation.
AK09916_WIA2 = 0x01
AK09916_ST1 = 0x10
AK09916_HXL = 0x11
AK09916_HXH = 0x12
AK09916_ST2 = 0x18
AK09916_CNTL2 = 0x31
AK09916_CNTL3 = 0x32
AK09916_MODE_SHUTDOWN = 0x00
AK09916_MODE_SINGLE = 0x01
AK09916_MODE_10HZ = 0x02
AK09916_MODE_20HZ = 0x04
AK09916_MODE_50HZ = 0x06
AK09916_MODE_100HZ = 0x08

MODE_NAMES = {
    AK09916_MODE_SHUTDOWN: "shutdown",
    AK09916_MODE_SINGLE: "single",
    AK09916_MODE_10HZ: "10Hz",
    AK09916_MODE_20HZ: "20Hz",
    AK09916_MODE_50HZ: "50Hz",
    AK09916_MODE_100HZ: "100Hz",
}

AK09916_I2C_ADDRESS = 0x0C
AK09916_WHO_AM_I = 0x09
# Datasheet sensitivity: 0.15 uT/LSB (the same constant the adafruit driver uses).
UT_PER_LSB = 0.15

IMU_I2C_ADDRESS = 0x69
SHARED_BUS_SERVICE = "eclipse-obd.service"

DEFAULT_TRIAL_SECONDS = 20.0
DEFAULT_SAMPLE_HZ = 25.0


def assertBusNotShared() -> None:
    """Refuse to touch the IMU while the capture service owns it.

    The ICM-20948 selects its register bank through a stateful write, so a
    concurrent reader can switch the bank between this process's bank-select and
    its read. Atlas wedged the I2C bus this exact way on 2026-08-20 -- a
    read-only command is NOT a safe command when the resource is shared.

    Raises:
        SystemExit: when the capture service is active (exit code 1).
    """
    probe = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["systemctl", "is-active", SHARED_BUS_SERVICE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    state = probe.stdout.strip()
    if state == "active":
        raise SystemExit(
            f"REFUSED: {SHARED_BUS_SERVICE} is active and owns the I2C bus.\n"
            f"  sudo systemctl stop eclipse-obd   # then re-run\n"
            f"  sudo systemctl start eclipse-obd  # ALWAYS restart when done"
        )
    print(f"[safety] {SHARED_BUS_SERVICE} is '{state}' -- bus is ours.")


def makeI2cBus() -> Any:
    """Open the Pi's primary I2C bus."""
    import board
    import busio

    return busio.I2C(board.SCL, board.SDA)


def makeDeviceOnBus(i2cBus: Any) -> Any:
    """Construct a FRESH ICM20948 handle on a bus the caller also holds.

    The bus is passed in rather than opened internally because the bypass lever
    needs to address the AK09916 as its OWN I2C device at 0x0C, on the same bus,
    once the ICM-20948 stops shadowing it.
    """
    import adafruit_icm20x

    return adafruit_icm20x.ICM20948(i2cBus, address=IMU_I2C_ADDRESS)


def makeDevice() -> Any:
    """Construct a FRESH ICM20948 handle on a freshly opened bus."""
    return makeDeviceOnBus(makeI2cBus())


def disableSlave0(dev: Any) -> None:
    """Quiesce the cyclic slave0 readout so an on-demand slave4 transfer can run.

    MEASURED 2026-08-21: with slave0 enabled and cycling, EVERY slave4 transfer
    reported not-finished -- reads AND writes. The driver only gets away with it
    because it does all of its slave4 work during init, BEFORE it enables slave0;
    anything that touches a magnetometer control register afterwards is talking
    to a channel that is not running. This is why run 1 of this probe invalidated
    itself and why "just set CNTL2 at runtime" cannot work.
    """
    dev._bank = 3  # noqa: SLF001
    time.sleep(0.005)
    dev._slave0_ctrl = 0x00  # noqa: SLF001 -- clear EN
    time.sleep(0.010)


def rearmSlave0Readout(dev: Any) -> None:
    """Re-run the driver's slave0 burst-readout setup (bank 3, 9 bytes from HXL).

    Nine bytes spans HXL..CNTL1, which INCLUDES ST2 -- reading ST2 is what
    releases the AK09916's measurement-data latch. Re-armed after any lever that
    reconfigures the aux master, so a trial never measures a half-configured chip.
    """
    dev._setup_mag_readout()  # noqa: SLF001
    time.sleep(0.010)


def readMagRegister(dev: Any, register: int) -> int | None:
    """Read one AK09916 register directly, with slave0 quiesced for the transfer.

    US-565 AC-4 forbids ``adafruit_icm20x.magnetometer_data_rate`` as a verifier:
    that getter reads CNTL2 and then falls off the end of the function without a
    ``return``, so it reports ``None`` for every possible mode. The private
    ``_read_mag_register`` it delegates to DOES return -- but only completes when
    slave0 is not cycling, so the quiesce/re-arm is part of the read.

    Args:
        dev: A constructed ICM20948 handle.
        register: The AK09916 register address.

    Returns:
        The register byte, or None when the slave4 transfer did not complete.
    """
    disableSlave0(dev)
    value = dev._read_mag_register(register)  # noqa: SLF001 -- the public getter is broken
    rearmSlave0Readout(dev)
    return value


def writeCntl2Verified(dev: Any, mode: int) -> dict[str, Any]:
    """Set the AK09916 operating mode and PROVE it landed by reading it back.

    The datasheet requires a transit through power-down before any mode change
    (Twait >= 100 us). ``_write_mag_register`` returns whether the transfer
    finished and the adafruit driver DISCARDS that return -- which is how a mode
    change that never reached the chip still looks like a successful config. Both
    the transfer flag and the readback are reported here, and the readback is the
    one that counts: a finished transfer to a chip in the wrong state still lies.

    Args:
        dev: A constructed ICM20948 handle.
        mode: One of the AK09916_MODE_* constants.

    Returns:
        The write-transfer flags, the readback byte and whether it matched.
    """
    disableSlave0(dev)
    shutdownOk = dev._write_mag_register(AK09916_CNTL2, AK09916_MODE_SHUTDOWN)  # noqa: SLF001
    time.sleep(0.010)
    writeOk = dev._write_mag_register(AK09916_CNTL2, mode)  # noqa: SLF001
    time.sleep(0.010)
    readback = dev._read_mag_register(AK09916_CNTL2)  # noqa: SLF001
    rearmSlave0Readout(dev)
    return {
        "requested": mode,
        "requestedName": MODE_NAMES.get(mode, "unknown"),
        "shutdownTransferFinished": bool(shutdownOk),
        "writeTransferFinished": bool(writeOk),
        "readback": readback,
        "readbackName": MODE_NAMES.get(readback, "unknown") if readback is not None else None,
        "verified": readback == mode,
    }


def setAuxMasterDutyCycled(dev: Any, dutyCycled: bool) -> None:
    """Set/clear LP_CONFIG.I2C_MST_CYCLE (bank 0 reg 0x05 bit 6).

    This is the lever the adafruit driver defines (``_i2c_master_cycle_en``) and
    then NEVER writes, leaving the chip on its power-on default. In duty-cycled
    mode the auxiliary I2C master is triggered by the low-power sample clock
    rather than running continuously -- a plausible mechanism for slave0
    transfers stopping after init while EXT_SLV_SENS_DATA retains the last
    transfer indefinitely. Named as a hypothesis under test, not as the fix.
    """
    dev._bank = 0  # noqa: SLF001
    time.sleep(0.005)
    dev._i2c_master_cycle_en = dutyCycled  # noqa: SLF001
    time.sleep(0.010)


def softResetMagnetometer(dev: Any) -> None:
    """Assert AK09916 CNTL3.SRST and wait for the chip to come back."""
    dev._write_mag_register(AK09916_CNTL3, 0x01)  # noqa: SLF001
    time.sleep(0.100)


def sampleChannels(
    dev: Any, *, seconds: float, sampleHz: float
) -> dict[str, list[float]]:
    """Poll magnetic + acceleration + gyro at a fixed cadence for a fixed window.

    Accel and gyro are sampled as LIVE CONTROL channels, not as decoration. A
    magnetometer trial that reports "no variation" is uninterpretable on its own:
    it means the same thing whether the mag is latched or the whole I2C bus has
    wedged. Channels that are known to dither on this die (743 distinct accel
    values in 90 s stationary, 2026-08-21 capture) separate those two cases
    inside every trial.

    Args:
        dev: A constructed ICM20948 handle.
        seconds: Length of the sampling window.
        sampleHz: Polling cadence within the window.

    Returns:
        Channel name -> the raw sample series, in acquisition order.
    """
    period = 1.0 / sampleHz
    series: dict[str, list[float]] = {
        "mag_x": [],
        "mag_y": [],
        "mag_z": [],
        "accel_x": [],
        "gyro_z": [],
    }
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        magX, magY, magZ = dev.magnetic
        accelX = dev.acceleration[0]
        gyroZ = dev.gyro[2]
        series["mag_x"].append(magX)
        series["mag_y"].append(magY)
        series["mag_z"].append(magZ)
        series["accel_x"].append(accelX)
        series["gyro_z"].append(gyroZ)
        time.sleep(period)
    return series


def summarizeSeries(series: dict[str, list[float]]) -> dict[str, dict[str, Any]]:
    """Reduce each channel to the facts the acceptance criterion is stated in.

    Reports DISTINCT counts (US-565: acceptance is "N distinct values", never "it
    changed once"), plus min/max/first so an all-zeros trial is distinguishable
    from a latched-nonzero one -- the 100 Hz probe on 2026-08-20 produced zeros,
    which a distinct-count alone would have scored identically to a good latch.
    """
    summary: dict[str, dict[str, Any]] = {}
    for name, values in series.items():
        # WHERE the changes fall is the whole diagnosis. "3 distinct values" means
        # something completely different if all three land in the first second
        # (conversions left over from init, then a freeze) than if they are spread
        # across the window (a slow but LIVE channel). A distinct count alone
        # cannot tell those apart, and the difference is exactly what US-565 is
        # about, so the indices ride along with the count.
        changeIndices = [i for i in range(1, len(values)) if values[i] != values[i - 1]]
        summary[name] = {
            "samples": len(values),
            "distinct": len(set(values)),
            "changes": len(changeIndices),
            "firstChangeIndex": changeIndices[0] if changeIndices else None,
            "lastChangeIndex": changeIndices[-1] if changeIndices else None,
            "first": values[0] if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "allZero": bool(values) and all(v == 0.0 for v in values),
        }
    return summary


# --- Levers under test ---------------------------------------------------------
# Each entry is (name, description, applyFn). applyFn runs against a FRESH device
# that the adafruit driver has already reset + initialised, so every trial starts
# from the same production baseline and differs only in the lever.


def _leverStock(dev: Any) -> dict[str, Any] | None:
    """Production baseline: whatever the driver's own _magnetometer_init left."""
    return None


def _leverRate(mode: int) -> Callable[[Any], dict[str, Any] | None]:
    """Set CNTL2 to one mode with slave0 quiesced, verifying the write landed."""

    def apply(dev: Any) -> dict[str, Any] | None:
        return writeCntl2Verified(dev, mode)

    return apply


def _leverContinuousMaster(dev: Any) -> dict[str, Any] | None:
    """Clear the aux-master duty-cycle bit; leave the driver's own 100 Hz mode."""
    setAuxMasterDutyCycled(dev, False)
    rearmSlave0Readout(dev)
    return None


def _leverContinuousMasterPlusRate(mode: int) -> Callable[[Any], dict[str, Any] | None]:
    """Clear the duty-cycle bit AND set an explicit CNTL2 mode."""

    def apply(dev: Any) -> dict[str, Any] | None:
        setAuxMasterDutyCycled(dev, False)
        return writeCntl2Verified(dev, mode)

    return apply


def _leverSoftResetThenRate(mode: int) -> Callable[[Any], dict[str, Any] | None]:
    """Soft-reset the AK09916 first, then configure it from a known state."""

    def apply(dev: Any) -> dict[str, Any] | None:
        disableSlave0(dev)
        softResetMagnetometer(dev)
        rearmSlave0Readout(dev)
        return writeCntl2Verified(dev, mode)

    return apply


LEVERS: list[tuple[str, str, Callable[[Any], dict[str, Any] | None]]] = [
    ("stock", "production baseline -- driver init only", _leverStock),
    ("rate_10hz", "CNTL2=10Hz (verified write)", _leverRate(AK09916_MODE_10HZ)),
    ("rate_50hz", "CNTL2=50Hz (verified write)", _leverRate(AK09916_MODE_50HZ)),
    ("rate_100hz", "CNTL2=100Hz (verified write)", _leverRate(AK09916_MODE_100HZ)),
    ("master_continuous", "LP_CONFIG.I2C_MST_CYCLE=0, driver rate", _leverContinuousMaster),
    (
        "master_continuous_100hz",
        "I2C_MST_CYCLE=0 + CNTL2=100Hz",
        _leverContinuousMasterPlusRate(AK09916_MODE_100HZ),
    ),
    (
        "master_continuous_50hz",
        "I2C_MST_CYCLE=0 + CNTL2=50Hz",
        _leverContinuousMasterPlusRate(AK09916_MODE_50HZ),
    ),
    (
        "softreset_continuous_100hz",
        "CNTL3 soft reset + I2C_MST_CYCLE=0 + CNTL2=100Hz",
        _leverSoftResetThenRate(AK09916_MODE_100HZ),
    ),
]


def runTrial(
    name: str,
    description: str,
    apply: Callable[[Any], dict[str, Any] | None],
    *,
    seconds: float,
    sampleHz: float,
) -> dict[str, Any]:
    """Run one lever end to end on a fresh device and return its measured record."""
    print(f"\n=== {name}: {description}")
    record: dict[str, Any] = {"lever": name, "description": description}
    try:
        dev = makeDevice()
        record["cntl2Before"] = readMagRegister(dev, AK09916_CNTL2)
        record["write"] = apply(dev)
        series = sampleChannels(dev, seconds=seconds, sampleHz=sampleHz)
        record["channels"] = summarizeSeries(series)
        cntl2 = readMagRegister(dev, AK09916_CNTL2)
        record["cntl2After"] = cntl2
        record["cntl2AfterName"] = (
            MODE_NAMES.get(cntl2, "unknown") if cntl2 is not None else None
        )
    except Exception as exc:  # noqa: BLE001 -- a probe must report faults, not die
        record["error"] = f"{type(exc).__name__}: {exc}"
        print(f"  ERROR: {record['error']}")
        return record

    write = record["write"]
    if write is not None:
        print(
            f"  write {write['requestedName']}:"
            f" transferFinished={write['writeTransferFinished']}"
            f" readback={write['readback']} verified={write['verified']}"
        )
    print(
        f"  CNTL2 before={record['cntl2Before']} after={cntl2} ({record['cntl2AfterName']})"
    )
    for channel in ("mag_x", "accel_x"):
        stats = record["channels"][channel]
        print(
            f"  {channel:<8} distinct={stats['distinct']:>5} / {stats['samples']}"
            f"  changes={stats['changes']:>4}"
            f"  changeIdx=[{stats['firstChangeIndex']}..{stats['lastChangeIndex']}]"
            f"  allZero={stats['allZero']}"
        )
    return record


def diagnoseConversion(*, samples: int, intervalSeconds: float) -> dict[str, Any]:
    """Ask the AK09916 directly whether it is converting, bypassing the burst path.

    The lever sweep leaves two candidate faults that a magnetic reading alone
    cannot separate: the chip has stopped CONVERTING, or the chip is converting
    fine and the ICM-20948's cyclic slave0 readout has stopped TRANSFERRING. Both
    present identically as a frozen ``dev.magnetic``.

    This reads the measurement registers one at a time over slave4 with slave0
    quiesced -- a completely different data path -- and reads ST1 (which carries
    DRDY) that the driver's 9-byte burst starting at HXL never sees. ST2 is read
    last on every pass because that read is what releases the AK09916's data
    latch and permits the next conversion to land.

    Args:
        samples: How many passes to take.
        intervalSeconds: Delay between passes.

    Returns:
        The per-pass register readings plus derived distinct counts.
    """
    dev = makeDevice()
    disableSlave0(dev)
    passes: list[dict[str, Any]] = []
    for _ in range(samples):
        st1 = dev._read_mag_register(AK09916_ST1)  # noqa: SLF001
        hxl = dev._read_mag_register(AK09916_HXL)  # noqa: SLF001
        hxh = dev._read_mag_register(AK09916_HXH)  # noqa: SLF001
        st2 = dev._read_mag_register(AK09916_ST2)  # noqa: SLF001 -- releases the latch
        passes.append({"st1": st1, "hxl": hxl, "hxh": hxh, "st2": st2})
        time.sleep(intervalSeconds)
    cntl2 = dev._read_mag_register(AK09916_CNTL2)  # noqa: SLF001
    whoami = dev._read_mag_register(AK09916_WIA2)  # noqa: SLF001

    raw = [
        None if p["hxl"] is None or p["hxh"] is None else (p["hxh"] << 8) | p["hxl"]
        for p in passes
    ]
    result = {
        "mode": "diagnose-direct-slave4",
        "whoAmI": whoami,
        "cntl2": cntl2,
        "cntl2Name": MODE_NAMES.get(cntl2, "unknown") if cntl2 is not None else None,
        "passes": passes,
        "distinctRawX": len({v for v in raw if v is not None}),
        "distinctSt1": len({p["st1"] for p in passes if p["st1"] is not None}),
        "readFailures": sum(1 for p in passes if p["hxl"] is None),
    }
    print(f"  WIA2 (expect 0x09) = {whoami}")
    print(f"  CNTL2 = {cntl2} ({result['cntl2Name']})")
    for index, (p, value) in enumerate(zip(passes, raw, strict=True)):
        print(f"  pass {index:>2}: ST1={p['st1']} rawX={value} ST2={p['st2']}")
    print(
        f"  distinct rawX = {result['distinctRawX']} / {samples}"
        f" | distinct ST1 = {result['distinctSt1']} | read failures = {result['readFailures']}"
    )
    return result


def writeCaptureCsv(path: str, series: dict[str, list[float]], report: dict[str, Any]) -> None:
    """Write the bypass capture as a self-describing CSV fixture.

    The header records the command, the date, the row count and the per-channel
    distinct counts DERIVED FROM THE DATA, so a later test can re-derive them and
    fail loudly if the file is ever regenerated rounded, truncated or synthetic.
    Rounding would be especially destructive here: it would manufacture the very
    bit-identity that US-564's invariance gate exists to detect.
    """
    channels = ["mag_x", "mag_y", "mag_z", "accel_x"]
    rows = len(series["mag_x"])
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(
            "# REAL CAPTURED MAGNETOMETER DATA via I2C BYPASS -- not synthetic. US-565.\n"
            "# Source: chi-eclipse-01, AK09916 read as its own I2C device at 0x0C with\n"
            "#   the ICM-20948 aux master DISABLED and INT_PIN_CFG.BYPASS_EN set.\n"
            "#   characterize_magnetometer.py --bypass --csv\n"
            f"# Captured by Rex {time.strftime('%Y-%m-%d', time.gmtime())}."
            " Board STATIONARY on the bench.\n"
            f"# CNTL2 read back directly = 0x{report['cntl2']:02X} ({report['cntl2Name']});"
            f" WIA2 = 0x{report['whoAmI']:02X}.\n"
            f"# DRDY was set on {report['drdySeen']} of {rows} reads.\n"
            "# MEASURED distinct-value counts over this exact window:\n"
            "#   "
            + "   ".join(
                f"{name} {report['channels'][name]['distinct']} / {rows}" for name in channels
            )
            + "\n"
            "# accel_x is the CONTROL channel: it is known to dither on this die, so a\n"
            "# capture where mag varies AND accel varies proves acquisition, while a\n"
            "# capture where neither varies would only prove the bus had wedged.\n"
            "# DO NOT round or reformat these values -- bit-identity is the property\n"
            "# under test, and rounding would manufacture the invariance it detects.\n"
            f"# columns: {','.join(channels)}\n"
        )
        for index in range(rows):
            handle.write(",".join(repr(series[name][index]) for name in channels) + "\n")
    print(f"wrote {path} ({rows} rows)")


def probeBypassDirect(
    *, seconds: float, sampleHz: float, csvPath: str | None = None
) -> dict[str, Any]:
    """Measure the AK09916 read as its OWN I2C device, with the aux master off.

    The evidence that motivates this path: the AK09916 converts correctly and
    dithers (proved by the direct slave4 probe), while the ICM-20948's cyclic
    slave0 shadow performs a single transfer and then stops. If the chip is
    healthy and only the shadowing is broken, then removing the shadow -- I2C
    bypass, so the magnetometer answers on the Pi's own bus at 0x0C -- should
    yield a live channel at full polling speed. Slave4 is NOT a candidate for
    production: it costs ~25 ms per register and it wedged after 11 passes.

    Reads ST1..ST2 in ONE 10-byte transaction. ST1 carries DRDY, and the read
    MUST extend through ST2 because that final byte is what releases the
    AK09916's data latch and lets the next conversion land.

    Args:
        seconds: Length of the sampling window.
        sampleHz: Polling cadence within the window.

    Returns:
        Distinct counts for the magnetometer and for accel as a control channel.
    """
    from adafruit_bus_device import i2c_device

    i2cBus = makeI2cBus()
    dev = makeDeviceOnBus(i2cBus)

    # Hand the magnetometer back to the primary bus: master off, bypass on.
    dev._bank = 0  # noqa: SLF001
    time.sleep(0.010)
    dev._i2c_master_enable = False  # noqa: SLF001
    time.sleep(0.010)
    dev._bypass_i2c_master = True  # noqa: SLF001
    time.sleep(0.050)

    mag = i2c_device.I2CDevice(i2cBus, AK09916_I2C_ADDRESS)
    whoAmI = bytearray(1)
    with mag:
        mag.write_then_readinto(bytes([AK09916_WIA2]), whoAmI)

    # Configure the chip ourselves now that we can reach it: power-down transit
    # then continuous 100 Hz, and read CNTL2 back rather than trusting the write.
    with mag:
        mag.write(bytes([AK09916_CNTL2, AK09916_MODE_SHUTDOWN]))
    time.sleep(0.010)
    with mag:
        mag.write(bytes([AK09916_CNTL2, AK09916_MODE_100HZ]))
    time.sleep(0.020)
    cntl2 = bytearray(1)
    with mag:
        mag.write_then_readinto(bytes([AK09916_CNTL2]), cntl2)

    period = 1.0 / sampleHz
    frame = bytearray(10)  # ST1(0x10) .. ST2(0x18) inclusive
    series: dict[str, list[float]] = {"mag_x": [], "mag_y": [], "mag_z": [], "accel_x": []}
    drdySeen = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with mag:
            mag.write_then_readinto(bytes([AK09916_ST1]), frame)
        if frame[0] & 0x01:
            drdySeen += 1
        series["mag_x"].append(int.from_bytes(frame[1:3], "little", signed=True) * UT_PER_LSB)
        series["mag_y"].append(int.from_bytes(frame[3:5], "little", signed=True) * UT_PER_LSB)
        series["mag_z"].append(int.from_bytes(frame[5:7], "little", signed=True) * UT_PER_LSB)
        series["accel_x"].append(dev.acceleration[0])
        time.sleep(period)

    report = {
        "mode": "bypass-direct",
        "whoAmI": whoAmI[0],
        "whoAmIExpected": AK09916_WHO_AM_I,
        "cntl2": cntl2[0],
        "cntl2Name": MODE_NAMES.get(cntl2[0], "unknown"),
        "drdySeen": drdySeen,
        "channels": summarizeSeries(series),
    }
    print(f"  WIA2 = 0x{whoAmI[0]:02X} (expect 0x{AK09916_WHO_AM_I:02X})")
    print(f"  CNTL2 readback = 0x{cntl2[0]:02X} ({report['cntl2Name']})")
    print(f"  DRDY set on {drdySeen} of {len(series['mag_x'])} reads")
    for channel in ("mag_x", "mag_y", "mag_z", "accel_x"):
        stats = report["channels"][channel]
        print(
            f"  {channel:<8} distinct={stats['distinct']:>5} / {stats['samples']}"
            f"  changes={stats['changes']:>4}"
            f"  range=[{stats['min']}, {stats['max']}]"
        )
    if csvPath:
        writeCaptureCsv(csvPath, series, report)
    return report


def main(argv: list[str] | None = None) -> int:
    """Sweep every lever and write a JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=DEFAULT_TRIAL_SECONDS)
    parser.add_argument("--sample-hz", type=float, default=DEFAULT_SAMPLE_HZ)
    parser.add_argument("--out", default="/tmp/mag-characterization.json")
    parser.add_argument("--lever", action="append", help="run only these levers (repeatable)")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="poll the AK09916 measurement registers directly over slave4 instead",
    )
    parser.add_argument(
        "--bypass",
        action="store_true",
        help="read the AK09916 as its own I2C device at 0x0C with the aux master off",
    )
    parser.add_argument("--csv", help="also write the bypass capture as a CSV fixture")
    args = parser.parse_args(argv)

    assertBusNotShared()

    if args.bypass:
        print("\n=== BYPASS probe: AK09916 as its own I2C device at 0x0C ===")
        report = probeBypassDirect(
            seconds=args.seconds, sampleHz=args.sample_hz, csvPath=args.csv
        )
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        print(f"\nwrote {args.out}")
        return 0

    if args.diagnose:
        print("\n=== DIRECT slave4 conversion probe (slave0 quiesced) ===")
        report = diagnoseConversion(samples=20, intervalSeconds=0.5)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        print(f"\nwrote {args.out}")
        return 0

    levers = LEVERS
    if args.lever:
        wanted = set(args.lever)
        levers = [entry for entry in LEVERS if entry[0] in wanted]
        if not levers:
            raise SystemExit(f"no lever matched {sorted(wanted)}")

    trials = [
        runTrial(name, desc, apply, seconds=args.seconds, sampleHz=args.sample_hz)
        for name, desc, apply in levers
    ]

    report = {
        "capturedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "trialSeconds": args.seconds,
        "sampleHz": args.sample_hz,
        "trials": trials,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(f"\nwrote {args.out}")

    print("\n--- SUMMARY (distinct values per trial) ---")
    print(
        f"{'lever':<28} {'CNTL2':<10} {'mag_x':>7} {'mag_y':>7}"
        f" {'mag_z':>7} {'accel_x':>8}  {'magChangeIdx':>14}"
    )
    for trial in trials:
        if "error" in trial:
            print(f"{trial['lever']:<28} ERROR {trial['error']}")
            continue
        ch = trial["channels"]
        cntl2 = trial["cntl2AfterName"] or "?"
        span = f"{ch['mag_x']['firstChangeIndex']}..{ch['mag_x']['lastChangeIndex']}"
        print(
            f"{trial['lever']:<28} {cntl2:<10}"
            f" {ch['mag_x']['distinct']:>7} {ch['mag_y']['distinct']:>7}"
            f" {ch['mag_z']['distinct']:>7} {ch['accel_x']['distinct']:>8}  {span:>14}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
