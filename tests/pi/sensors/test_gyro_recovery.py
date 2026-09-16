"""ARCH-027 / A-34: tests for the gyro latched-fault detector and recovery.

The ICM-20948's gyro channel can enter a latched analog state that reports a
constant 14-30 deg/s on a motionless car. Measured 2026-09-14 and again live on
2026-09-15:

* it SURVIVES ``DEVICE_RESET`` (0 of 16 inits cleared it),
* it fails the factory self-test (0.062-0.126 against a 0.5 floor),
* the same silicon passes (1.007-1.016) once recovered,
* a ``PWR_MGMT_2`` gyro off/on cleared it 3 of 3 times.

So the recovery cannot be expressed as "reset harder". It is a specific register
sequence, and the driver exposes no symbol for that register at all.

The fakes here mirror `tests/pi/sensors/test_sensor_reader.py`'s `FakeImu`
style: plain attribute stubs, dependency-injected, no hardware.
"""

from __future__ import annotations

from pi.sensors.gyro_recovery import (
    GYRO_FAULT_MIN_RAD_S,
    PWR_MGMT_2_ALL_ON,
    PWR_MGMT_2_GYRO_OFF,
    REG_PWR_MGMT_2,
    GyroRecoveryOutcome,
    gyroLooksFaulted,
    recoverGyroIfFaulted,
)
from pi.sensors.sensor_reader import _recoverGyro


class FakeI2cDevice:
    """Records register writes; mimics adafruit's I2CDevice context manager."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, int]] = []

    def __enter__(self) -> FakeI2cDevice:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def write(self, payload: bytes) -> None:
        self.writes.append((payload[0], payload[1]))


class FakeIcm:
    """An ICM-20948 whose gyro state changes when the power cycle actually happens.

    Phase-driven, not sample-counted: it reads `gyroSequence[0]` until a
    PWR_MGMT_2 write is observed, then `gyroSequence[-1]`. That mirrors the real
    device's causality -- the state changes BECAUSE the register was written --
    so a fake can never report a recovery that the code did not perform.

    (An earlier version of this fake popped one reading per access, which made
    19 of 20 startup samples healthy and pulled the mean below the threshold.
    The detector then correctly reported "healthy" and skipped the recovery,
    and two tests failed. The fake was wrong, not the detector -- and averaging
    is precisely the property that made the bad fake fail.)
    """

    def __init__(self, gyroSequence: list[tuple[float, float, float]]) -> None:
        self._before = gyroSequence[0]
        self._after = gyroSequence[-1]
        self.i2c_device = FakeI2cDevice()
        self.acceleration = (0.3, -0.1, 9.98)
        self._bank = 0

    @property
    def gyro(self) -> tuple[float, float, float]:
        return self._after if self.i2c_device.writes else self._before


FAULTED = (0.243, -0.541, -0.337)
HEALTHY = (0.0003, 0.0128, 0.0029)


class TestGyroLooksFaulted:
    def test_liveFaultedVector_isFaulted(self) -> None:
        """Measured on the live sensor 2026-09-15T22:17-22:39Z."""
        assert gyroLooksFaulted([FAULTED] * 20) is True

    def test_healthyVector_isNotFaulted(self) -> None:
        assert gyroLooksFaulted([HEALTHY] * 20) is False

    def test_usesTheMeanSoOneSpikeDoesNotTrip(self) -> None:
        """A single bad sample is noise. The fault is a sustained offset."""
        readings = [HEALTHY] * 19 + [(0.9, 0.9, 0.9)]
        assert gyroLooksFaulted(readings) is False

    def test_sustainedOffsetTrips_evenBelowTheWorstObservedFault(self) -> None:
        justOver = (0.0, GYRO_FAULT_MIN_RAD_S + 0.01, 0.0)
        assert gyroLooksFaulted([justOver] * 20) is True

    def test_emptyReadings_isNotFaulted_becauseAbsenceIsNotEvidence(self) -> None:
        """No samples means we do not know. Claiming a fault would be a guess,
        and it would trigger a power cycle on no evidence at all."""
        assert gyroLooksFaulted([]) is False


class TestRecoverGyroIfFaulted:
    def test_healthyGyro_isLeftAlone(self) -> None:
        """No register writes at all on a healthy sensor. The recovery is not
        free -- it costs a settle and disturbs the chip -- so it must not run
        prophylactically."""
        icm = FakeIcm([HEALTHY])
        outcome = recoverGyroIfFaulted(icm, sampleCount=10, settleS=0.0)
        assert outcome.attempted is False
        assert outcome.before == "healthy"
        assert icm.i2c_device.writes == []

    def test_faultedGyro_triggersThePowerCycleSequence(self) -> None:
        icm = FakeIcm([FAULTED, HEALTHY])
        recoverGyroIfFaulted(icm, sampleCount=10, settleS=0.0)
        assert icm.i2c_device.writes == [
            (REG_PWR_MGMT_2, PWR_MGMT_2_GYRO_OFF),
            (REG_PWR_MGMT_2, PWR_MGMT_2_ALL_ON),
        ]

    def test_successfulRecovery_isReportedAsRecovered(self) -> None:
        icm = FakeIcm([FAULTED, HEALTHY])
        outcome = recoverGyroIfFaulted(icm, sampleCount=10, settleS=0.0)
        assert outcome.attempted is True
        assert outcome.before == "faulted"
        assert outcome.after == "healthy"
        assert outcome.recovered is True

    def test_failedRecovery_isReportedHonestly_notAssumed(self) -> None:
        """🔴 Writing the register is not evidence the gyro recovered.

        The sequence cleared it 3 of 3 times in testing, which is not 'always'.
        If the post-check still reads faulted, that must surface as recovered =
        False so the plausibility guard keeps withholding pitch and grade.
        """
        icm = FakeIcm([FAULTED, FAULTED])
        outcome = recoverGyroIfFaulted(icm, sampleCount=10, settleS=0.0)
        assert outcome.attempted is True
        assert outcome.recovered is False
        assert outcome.after == "faulted"

    def test_returnsToBankZero_soLaterMagnetometerBypassIsUndisturbed(self) -> None:
        """The bypass sets bank 0 itself, but leaving the chip on another bank
        would break any caller that does not. Ordering bugs of this kind are
        invisible until something else moves."""
        icm = FakeIcm([FAULTED, HEALTHY])
        recoverGyroIfFaulted(icm, sampleCount=10, settleS=0.0)
        assert icm._bank == 0

    def test_busErrorDuringRecovery_degradesRatherThanKillingTheImu(self) -> None:
        """A failed recovery must not cost accel, gyro and mag.

        Same principle as _attachDirectMagnetometer: losing the whole IMU to fix
        one channel throws away valid data to punish a broken one.
        """

        class ExplodingDevice(FakeI2cDevice):
            def write(self, payload: bytes) -> None:
                raise OSError(121, "Remote I/O error")

        icm = FakeIcm([FAULTED, FAULTED])
        icm.i2c_device = ExplodingDevice()
        outcome = recoverGyroIfFaulted(icm, sampleCount=10, settleS=0.0)
        assert outcome.recovered is False
        assert outcome.error is not None

    def test_readErrorWhileSampling_doesNotClaimAFault(self) -> None:
        """If we cannot read the gyro we do not know its state. Power-cycling on
        a read failure would be acting on absence of evidence."""

        class UnreadableIcm(FakeIcm):
            @property
            def gyro(self) -> tuple[float, float, float]:
                raise OSError(121, "Remote I/O error")

        icm = UnreadableIcm([FAULTED])
        outcome = recoverGyroIfFaulted(icm, sampleCount=10, settleS=0.0)
        assert outcome.attempted is False
        assert outcome.before == "unknown"
        assert icm.i2c_device.writes == []


class TestOutcomeReporting:
    def test_outcomeSummarisesForTheLog(self) -> None:
        outcome = GyroRecoveryOutcome(
            attempted=True, before="faulted", after="healthy", recovered=True, error=None
        )
        assert "faulted" in outcome.describe()
        assert "healthy" in outcome.describe()

    def test_notAttemptedReadsClearly(self) -> None:
        outcome = GyroRecoveryOutcome(
            attempted=False, before="healthy", after="healthy", recovered=False, error=None
        )
        assert "no recovery" in outcome.describe().lower()


class TestStartupWiring:
    """The seam in `sensor_reader._recoverGyro`.

    Same shape and same reason as `_attachDirectMagnetometer`: hardware-only glue
    with an injected factory, so the behavioural claim is reachable by test
    instead of living as a try/except nothing enforces.
    """

    def test_recoveryIsInvokedWithTheConstructedIcm(self) -> None:
        icm = FakeIcm([HEALTHY])
        seen: list[object] = []

        def fakeRecovery(device: object) -> GyroRecoveryOutcome:
            seen.append(device)
            return GyroRecoveryOutcome(
                attempted=False, before="healthy", after="healthy", recovered=False, error=None
            )

        _recoverGyro(icm, recoveryFn=fakeRecovery)

        assert seen == [icm]

    def test_raisingRecovery_doesNotCostTheImu(self) -> None:
        """🔴 A broken recovery must never take accel, gyro and mag with it.

        The magnetometer path already holds this line; the gyro path has to hold
        it too, or a bad startup check becomes a worse defect than the fault it
        was added to clear.
        """

        def explodingRecovery(_device: object) -> GyroRecoveryOutcome:
            raise OSError(121, "Remote I/O error")

        assert _recoverGyro(FakeIcm([FAULTED]), recoveryFn=explodingRecovery) is None

    def test_outcomeIsReturnedForTheCaller(self) -> None:
        outcome = GyroRecoveryOutcome(
            attempted=True, before="faulted", after="healthy", recovered=True, error=None
        )
        assert _recoverGyro(FakeIcm([HEALTHY]), recoveryFn=lambda _d: outcome) is outcome


class TestThresholdProvenance:
    def test_faultThresholdSitsInTheMeasuredEmptyGap(self) -> None:
        """Quiet minutes measured 0.013-0.015 rad/s, faulted 0.487-0.553, with
        NOTHING observed between. The cut belongs in that gap, well clear of
        both -- and well below the fault so a bias learner can never absorb it.
        """
        assert 0.02 < GYRO_FAULT_MIN_RAD_S < 0.4
