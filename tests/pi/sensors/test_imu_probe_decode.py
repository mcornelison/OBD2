"""ARCH-027: pure decode/classify helpers behind the live IMU probe.

These are the parts of the probe that can be tested without an I2C bus, so they
are tested. The bus-facing half of `tools/imu/imu_probe.py` is exercised against
the real sensor on the Pi and reports its own evidence.

Register semantics are the ICM-20948 datasheet (bank 2 `ACCEL_CONFIG` 0x14,
`GYRO_CONFIG_1` 0x01). The concrete byte values asserted here are the ones read
off the live sensor on 2026-09-14 (`ACCEL_CONFIG 0x05`, `GYRO_CONFIG_1 0x03`),
so a decoder change that breaks the reading of our own hardware fails loudly.
"""

from __future__ import annotations

import math

import pytest

from tools.imu.imu_probe import (
    aliasingRisk,
    alignMagToImuFrame,
    classifyGyroHealth,
    decodeAccelConfig,
    decodeGyroConfig,
    decodeMagTriple,
    fieldMagnitudeUt,
    magDataReady,
    magOverflowed,
    odrHzFromDivider,
    selfTestRatio,
    selfTestVerdict,
    stOtpFromCode,
)


class TestDecodeAccelConfig:
    def test_liveSensorByte_decodesToPlusMinus8g(self) -> None:
        """0x05 is what our Pi actually runs. FS_SEL=2 => +/-8 g."""
        cfg = decodeAccelConfig(0x05)
        assert cfg.fullScaleG == 8
        assert cfg.lsbPerG == 4096

    def test_liveSensorByte_hasDlpfEnabledAtWidestBandwidth(self) -> None:
        """FCHOICE=1 means the DLPF is ENGAGED; DLPFCFG=0 is its widest setting.

        Getting this backwards was a real error in my own notes: 'DLPF bypassed'
        and 'DLPF enabled at 246 Hz' imply different fixes.
        """
        cfg = decodeAccelConfig(0x05)
        assert cfg.dlpfEnabled is True
        assert cfg.dlpfConfig == 0
        assert cfg.bandwidthHz == pytest.approx(246.0)

    def test_dlpfConfig4_isTheAntiAliasCandidate(self) -> None:
        """cfg 4 = 23.9 Hz, the setting that suits a 50 Hz read."""
        cfg = decodeAccelConfig(0b100_10_1)
        assert cfg.dlpfConfig == 4
        assert cfg.bandwidthHz == pytest.approx(23.9)

    def test_fchoiceZero_reportsDlpfDisabled(self) -> None:
        cfg = decodeAccelConfig(0b000_00_0)
        assert cfg.dlpfEnabled is False
        assert cfg.fullScaleG == 2

    @pytest.mark.parametrize(
        "fsSel,expectedG,expectedLsb",
        [(0, 2, 16384), (1, 4, 8192), (2, 8, 4096), (3, 16, 2048)],
    )
    def test_allFullScaleRanges(self, fsSel: int, expectedG: int, expectedLsb: int) -> None:
        cfg = decodeAccelConfig((fsSel << 1) | 0x01)
        assert cfg.fullScaleG == expectedG
        assert cfg.lsbPerG == expectedLsb


class TestDecodeGyroConfig:
    def test_liveSensorByte_decodesToPlusMinus500Dps(self) -> None:
        cfg = decodeGyroConfig(0x03)
        assert cfg.fullScaleDps == 500
        assert cfg.lsbPerDps == pytest.approx(65.5)

    def test_liveSensorByte_hasDlpfEnabledAt196Hz(self) -> None:
        cfg = decodeGyroConfig(0x03)
        assert cfg.dlpfEnabled is True
        assert cfg.bandwidthHz == pytest.approx(196.6)

    def test_dlpfConfig4_is23_9Hz(self) -> None:
        cfg = decodeGyroConfig(0b100_01_1)
        assert cfg.bandwidthHz == pytest.approx(23.9)

    @pytest.mark.parametrize(
        "fsSel,expectedDps,expectedLsb",
        [(0, 250, 131.0), (1, 500, 65.5), (2, 1000, 32.8), (3, 2000, 16.4)],
    )
    def test_allFullScaleRanges(self, fsSel: int, expectedDps: int, expectedLsb: float) -> None:
        cfg = decodeGyroConfig((fsSel << 1) | 0x01)
        assert cfg.fullScaleDps == expectedDps
        assert cfg.lsbPerDps == pytest.approx(expectedLsb)


class TestOdrFromDivider:
    def test_liveDividerTen_givesAboutOneHundredHz(self) -> None:
        """SRD 10 was read live on 2026-09-14: 1125/(1+10) = 102.3 Hz."""
        assert odrHzFromDivider(10) == pytest.approx(102.27, abs=0.01)

    def test_dividerZero_isTheBaseRate(self) -> None:
        assert odrHzFromDivider(0) == pytest.approx(1125.0)

    def test_dividerTwentyTwo_isAboutFiftyHz(self) -> None:
        """The candidate divider for a 50 Hz read."""
        assert odrHzFromDivider(22) == pytest.approx(48.9, abs=0.1)


class TestAliasingRisk:
    def test_shippedConfiguration_isAtRisk(self) -> None:
        """196.6 Hz of signal bandwidth sampled at 50 Hz folds back into the band."""
        assert aliasingRisk(bandwidthHz=196.6, sampleHz=50.0) is True

    def test_matchedFilter_isNotAtRisk(self) -> None:
        assert aliasingRisk(bandwidthHz=23.9, sampleHz=50.0) is False

    def test_exactlyNyquist_isNotFlagged(self) -> None:
        assert aliasingRisk(bandwidthHz=25.0, sampleHz=50.0) is False


class TestClassifyGyroHealth:
    """The 0.10 rad/s cut comes from a measured bimodal distribution:
    quiet minutes at 0.013-0.015 rad/s, faulted at 0.487-0.553, nothing between.
    """

    def test_healthyRestVector_classifiesHealthy(self) -> None:
        assert classifyGyroHealth((0.002, 0.014, 0.004)) == "healthy"

    def test_liveFaultedVector_classifiesFaulted(self) -> None:
        """Measured on the live sensor 2026-09-15T22:17-22:39Z."""
        assert classifyGyroHealth((0.239, -0.543, -0.337)) == "faulted"

    def test_variantA_fromTheRcaAlsoClassifiesFaulted(self) -> None:
        assert classifyGyroHealth((0.246, -0.51, -0.31)) == "faulted"

    def test_theGapBetweenModes_isIndeterminateNotHealthy(self) -> None:
        """An unclassifiable reading must not be silently called healthy."""
        assert classifyGyroHealth((0.05, 0.05, 0.02)) == "indeterminate"

    def test_realRotationIsNotClassified_becauseTheCallerMustGateOnStillness(self) -> None:
        """A car turning at 30 deg/s looks exactly like a fault to this function.

        The classifier is only meaningful on a confirmed-stationary window; that
        precondition belongs to the caller, so this test pins the docstring
        contract rather than inventing a motion check here.
        """
        turning = classifyGyroHealth((0.0, 0.0, 0.52))
        assert turning == "faulted"


class TestSelfTestRatio:
    """Pass/fail follows InvenSense: response vs factory trim, >= 0.5 passes."""

    def test_healthyGyroRatio_passes(self) -> None:
        ratio = selfTestRatio(response=1000.0, factoryTrim=1000.0)
        assert ratio == pytest.approx(1.0)

    def test_faultedGyroRatio_fails(self) -> None:
        """Measured faulted gyro: 0.062-0.126 against a 0.5 floor."""
        ratio = selfTestRatio(response=62.0, factoryTrim=1000.0)
        assert ratio == pytest.approx(0.062)

    def test_zeroFactoryTrim_isNotADivideByZero(self) -> None:
        """An unprogrammed OTP must report absence, never a fabricated ratio."""
        assert selfTestRatio(response=100.0, factoryTrim=0.0) is None

    def test_negativeResponse_keepsItsSignAsMagnitude(self) -> None:
        ratio = selfTestRatio(response=-900.0, factoryTrim=1000.0)
        assert ratio is not None and math.isclose(ratio, 0.9)


class TestStOtpFromCode:
    """ST_OTP = 2620 / 2^FS * 1.01^(code - 1), per InvenSense's own driver
    (Icm20948SelfTest.c, which precomputes it as a 256-entry lookup table).
    """

    def test_codeOne_atFullScaleZero_isTheBaseConstant(self) -> None:
        assert stOtpFromCode(1, fullScaleSelect=0) == pytest.approx(2620.0)

    def test_codeTwo_appliesOnePercentStep(self) -> None:
        assert stOtpFromCode(2, fullScaleSelect=0) == pytest.approx(2646.2)

    def test_fullScaleSelect_halvesTheValuePerStep(self) -> None:
        assert stOtpFromCode(1, fullScaleSelect=1) == pytest.approx(1310.0)
        assert stOtpFromCode(1, fullScaleSelect=2) == pytest.approx(655.0)

    def test_codeZero_isAnUnprogrammedOtp_notAValue(self) -> None:
        """Code 0 means the OTP was never programmed. It is zero, not 2620/1.01."""
        assert stOtpFromCode(0, fullScaleSelect=0) == 0.0


class TestSelfTestVerdict:
    """Vendor criteria, verified against InvenSense's driver rather than recalled:
    gyro fails below 0.5x the factory trim, accel fails above 1.5x, and a ZERO
    OTP fails outright.
    """

    def test_healthyGyro_passes(self) -> None:
        assert selfTestVerdict(response=1000.0, factoryTrim=1000.0, channel="gyro") == "pass"

    def test_faultedGyro_fails(self) -> None:
        """The measured A-34 faulted gyro: ratios 0.062-0.126."""
        assert selfTestVerdict(response=62.0, factoryTrim=1000.0, channel="gyro") == "fail"

    def test_gyroExactlyAtTheLowerBound_passes(self) -> None:
        """The driver fails when BELOW the bound, so the boundary itself passes."""
        assert selfTestVerdict(response=500.0, factoryTrim=1000.0, channel="gyro") == "pass"

    def test_accelAboveUpperBound_fails(self) -> None:
        assert selfTestVerdict(response=1600.0, factoryTrim=1000.0, channel="accel") == "fail"

    def test_healthyAccel_passes(self) -> None:
        """Our measured healthy accel ratios were 1.003 / 1.005 / 0.991."""
        assert selfTestVerdict(response=1003.0, factoryTrim=1000.0, channel="accel") == "pass"

    def test_zeroFactoryTrim_failsRatherThanReturningNoVerdict(self) -> None:
        """🔴 This CONTRADICTS my first implementation, and the vendor is right.

        I coded an unread OTP as 'absence, therefore no verdict'. InvenSense
        fails it: a part whose trim cannot be read has not been validated, and
        'unvalidated' is not 'fine'. Honest absence is the correct default for a
        MEASUREMENT; it is the wrong default for a SAFETY CHECK.
        """
        assert selfTestVerdict(response=5000.0, factoryTrim=0.0, channel="gyro") == "fail"


class TestDecodeMagTriple:
    """AK09916: little-endian signed 16-bit, 0.15 uT/LSB."""

    def test_positiveValue_scalesToMicrotesla(self) -> None:
        # 1000 LSB little-endian = 0xE8 0x03 -> 150.0 uT
        assert decodeMagTriple([0xE8, 0x03, 0x00, 0x00, 0x00, 0x00])[0] == pytest.approx(150.0)

    def test_negativeValue_usesTwosComplement(self) -> None:
        # -1000 LSB = 0x18 0xFC
        assert decodeMagTriple([0x18, 0xFC, 0x00, 0x00, 0x00, 0x00])[0] == pytest.approx(-150.0)

    def test_allThreeAxesDecodeIndependently(self) -> None:
        decoded = decodeMagTriple([0x0A, 0x00, 0x14, 0x00, 0x1E, 0x00])
        assert decoded == pytest.approx((1.5, 3.0, 4.5))

    def test_wrongByteCount_raisesRatherThanGuessing(self) -> None:
        with pytest.raises(ValueError):
            decodeMagTriple([0x00, 0x01, 0x02])


class TestMagStatusBits:
    def test_dataReadyBitSet(self) -> None:
        assert magDataReady(0x01) is True

    def test_dataReadyBitClear(self) -> None:
        assert magDataReady(0x00) is False

    def test_overflowBitSet(self) -> None:
        """HOFL (0x08) means the reading saturated and MUST NOT be published."""
        assert magOverflowed(0x08) is True

    def test_overflowBitClear(self) -> None:
        assert magOverflowed(0x00) is False


class TestAlignMagToImuFrame:
    """The AK09916 die does not share the accel/gyro axes inside the package.

    ⚠️ PROVENANCE, stated because it is weaker than I would like: I could not
    retrieve the datasheet's own orientation figure (six fetch attempts: 403,
    a navigation page, and PDFs whose text would not extract). What supports
    this transform is (a) two independent implementations applying exactly
    `my = -my; mz = -mz`, one of them noting the datasheet illustration only
    *implies* it, and (b) our own out-of-sample GPS score: 4.1 deg and 6.8 deg
    median heading error with this transform plus a hard-iron offset, against
    62.7 deg and 101.8 deg as shipped. That is measurement, not authority.
    """

    def test_yAndZAreNegated_xIsUnchanged(self) -> None:
        assert alignMagToImuFrame((10.0, 20.0, 30.0)) == pytest.approx((10.0, -20.0, -30.0))

    def test_transformIsItsOwnInverse(self) -> None:
        once = alignMagToImuFrame((3.0, -4.0, 5.0))
        assert alignMagToImuFrame(once) == pytest.approx((3.0, -4.0, 5.0))

    def test_magnitudeIsPreserved(self) -> None:
        """A sign flip cannot change field strength. If it does, it is a bug."""
        raw = (16.34, 15.98, 36.72)
        assert fieldMagnitudeUt(alignMagToImuFrame(raw)) == pytest.approx(fieldMagnitudeUt(raw))


class TestFieldMagnitudeUt:
    def test_threeFourFive(self) -> None:
        assert fieldMagnitudeUt((3.0, 4.0, 0.0)) == pytest.approx(5.0)

    def test_liveDashMountReading(self) -> None:
        """Measured on the Pi 2026-09-15: ~43.2 uT against Earth's ~52 uT here.

        Pinned so that a decode regression that halves or doubles the field is
        caught by a number someone actually observed.
        """
        assert fieldMagnitudeUt((16.34, 15.98, 36.72)) == pytest.approx(43.2, abs=0.1)
