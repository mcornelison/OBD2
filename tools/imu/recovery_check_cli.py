"""ARCH-027 / A-34: exercise the PRODUCTION gyro recovery against real hardware.

Unit tests prove the logic against fakes. They cannot prove that
``icm.i2c_device`` accepts the write, that the register address is right, or
that the driver's private ``_bank`` setter behaves as assumed on real silicon.
Only the chip can answer that, so this runs the real
``pi.sensors.gyro_recovery.recoverGyroIfFaulted`` against a real ICM-20948.

⚠️ It imports the PRODUCTION module deliberately. A re-implementation here would
prove that a copy works, which is worth nothing.

Usage on chi-eclipse-01, with the collector stopped:

    sudo systemctl stop eclipse-obd
    /home/mcornelison/obd2-venv/bin/python tools/imu/recovery_check_cli.py
    sudo systemctl start eclipse-obd

Expected on a HEALTHY gyro: ``attempted=false`` and ``registerWrites=0``. A
recovery that fires on a healthy sensor is a defect, not a feature -- the power
cycle is not free, so the no-op path is the one that needs proving most.
"""

from __future__ import annotations

import json
import sys
import time


def main() -> int:
    import adafruit_icm20x
    import board
    import busio

    from pi.sensors.gyro_recovery import recoverGyroIfFaulted

    i2c = busio.I2C(board.SCL, board.SDA)
    icm = adafruit_icm20x.ICM20948(i2c, address=0x69)

    # Count real register writes by wrapping the driver's own I2C device, so the
    # "healthy sensors are left alone" claim is MEASURED rather than asserted.
    #
    # ⚠️ The wrapper must pass EVERY argument through untouched. adafruit_register
    # calls `write(buffer, end=N)`, and a first version of this shim accepted only
    # a positional payload -- which crashed inside `icm.gyro`, before the recovery
    # was ever reached. An instrument that changes the behaviour it is measuring
    # is worse than no instrument.
    allWrites: list[list[int]] = []
    realDevice = icm.i2c_device

    class CountingDevice:
        def __enter__(self):  # noqa: ANN204
            realDevice.__enter__()
            return self

        def __exit__(self, *exc: object) -> bool:
            return bool(realDevice.__exit__(*exc))

        def write(self, buffer: bytes, *args: object, **kwargs: object) -> None:
            end = kwargs.get("end")
            extent = int(end) if isinstance(end, int) else len(buffer)
            allWrites.append(list(buffer[:extent]))
            realDevice.write(buffer, *args, **kwargs)

        def write_then_readinto(self, *args: object, **kwargs: object) -> None:
            realDevice.write_then_readinto(*args, **kwargs)

        def readinto(self, *args: object, **kwargs: object) -> None:
            realDevice.readinto(*args, **kwargs)

    icm.i2c_device = CountingDevice()

    before = [round(value, 6) for value in icm.gyro]
    outcome = recoverGyroIfFaulted(icm)
    time.sleep(0.2)
    after = [round(value, 6) for value in icm.gyro]

    print(
        json.dumps(
            {
                "tsUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "gyroBeforeRadS": before,
                "gyroAfterRadS": after,
                "outcome": {
                    "attempted": outcome.attempted,
                    "before": outcome.before,
                    "after": outcome.after,
                    "recovered": outcome.recovered,
                    "error": outcome.error,
                    "describe": outcome.describe(),
                },
                # Only PWR_MGMT_2 (0x07) writes answer the question. The driver
                # writes REG_BANK_SEL constantly as housekeeping, so counting
                # every write would drown the signal and make "zero writes"
                # unfalsifiable.
                "pwrMgmt2Writes": len([w for w in allWrites if w and w[0] == 0x07]),
                "pwrMgmt2Payloads": [
                    [hex(b) for b in w] for w in allWrites if w and w[0] == 0x07
                ],
                "totalBusWrites": len(allWrites),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
