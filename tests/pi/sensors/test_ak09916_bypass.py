################################################################################
# File Name: test_ak09916_bypass.py
# Purpose/Description: US-565 tests for direct AK09916 magnetometer acquisition
#   over I2C bypass (F-135).
#
#   THE FAKE MODELS THE CHIP'S LATCH RULE, AND THAT IS THE POINT. The AK09916
#   loads a new measurement into its data registers only once the PREVIOUS one
#   has been consumed by a read that reaches ST2. `FakeAk09916` implements that
#   rule, so shortening the read frame makes the fake latch exactly as the real
#   chip did -- the "read must reach ST2" requirement becomes a test that can
#   FAIL rather than a comment that can be ignored. A fake that always served
#   fresh data would have scored the broken driver and the fixed one identically.
#
#   Read-back verification is tested as its own behaviour because the defect this
#   story fixes was invisible for exactly that reason: the adafruit driver writes
#   CNTL2, DISCARDS the transfer-completion flag its own helper returns, and
#   never reads the register back -- so a configuration that never reached the
#   chip looked indistinguishable from one that did.
#
#   The real-hardware class replays a 90 s bypass capture taken off
#   chi-eclipse-01 (tests/fixtures/mag_bypass_90s_2026-08-21.csv) through the
#   US-564 gate and asserts it is NEVER called stale, against the ORIGINAL
#   latched capture through the SAME gate, which IS. One gate, two real captures,
#   opposite verdicts: a test that fired on nothing would pass the first half and
#   a test that fired on everything would pass the second.
# Author: Rex (US-565)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-565) | Initial -- bypass enable ordering, verified
#               |              | CNTL2 config, ST1..ST2 frame, overflow refusal,
#               |              | device wrapper, real-capture regression.
# ================================================================================
################################################################################

"""Tests for US-565 direct AK09916 acquisition over I2C bypass."""

from __future__ import annotations

from pathlib import Path

import pytest

from pi.sensors.ak09916_bypass import (
    AK09916_I2C_ADDRESS,
    FRAME_LENGTH,
    FRAME_START_REGISTER,
    MODE_CONTINUOUS_100HZ,
    MODE_POWER_DOWN,
    REG_CNTL2,
    REG_ST1,
    REG_ST2,
    REG_WIA2,
    UT_PER_LSB,
    WHO_AM_I_VALUE,
    Ak09916Direct,
    Icm20948DirectMagnetometer,
    MagnetometerConfigError,
    MagnetometerOverflowError,
    enableI2cBypass,
)
from pi.sensors.plausibility_gate import (
    REASON_SENSOR_STALE,
    ChannelPolicy,
    PlausibilityGate,
)
from pi.sensors.sensor_reader import _attachDirectMagnetometer

_MAG_TOPIC = "raw.imu.mag"

# -- the real-hardware captures -------------------------------------------------
# tests/pi/sensors/ -> tests/fixtures/. See each CSV's own header for provenance.
_FIXTURES = Path(__file__).parents[2] / "fixtures"
_BYPASS_FIXTURE = _FIXTURES / "mag_bypass_90s_2026-08-21.csv"
_LATCHED_FIXTURE = _FIXTURES / "imu_stationary_90s_2026-08-21.csv"

# Quoted from the bypass fixture's header block and RE-DERIVED from the data by
# test, so a regenerated or rounded capture goes red here instead of silently
# weakening every assertion built on it.
_BYPASS_ROWS = 2108
_BYPASS_DISTINCT = {"mag_x": 27, "mag_y": 24, "mag_z": 26, "accel_x": 76}

# The capture's real rate: 2108 samples / 90 s. Used so the gate's dwell spans
# the wall-clock time it would on this data rather than a borrowed sample count.
_BYPASS_HZ = 2108 / 90.0

# The latched capture, for the side-by-side comparison (see that file's header).
_LATCHED_ROWS = 1845


def _sample(x: int, y: int, z: int) -> tuple[int, int, int]:
    """One raw 16-bit measurement triple as the chip would hold it."""
    return (x, y, z)


class FakeAk09916:
    """An AK09916 register file that honours the chip's data-latch rule.

    The rule, from the datasheet and confirmed on the bench: a new measurement is
    loaded into HXL..HZH only after the previous one has been released by a read
    that reaches ST2. Modelling it here is what makes "the frame must reach ST2"
    a falsifiable property rather than a comment.

    Attributes:
        writes: Every ``(register, value)`` written, in order.
        reads: Every ``(startRegister, length)`` read, in order.
    """

    def __init__(
        self,
        *,
        whoAmI: int = WHO_AM_I_VALUE,
        samples: list[tuple[int, int, int]] | None = None,
        acceptModeWrites: bool = True,
        dataReady: bool = True,
        overflow: bool = False,
    ) -> None:
        self._whoAmI = whoAmI
        self._samples = list(samples or [_sample(100 + i, 200 + i, -50 - i) for i in range(64)])
        self._index = 0
        self._released = True  # the chip may load the first measurement
        self._acceptModeWrites = acceptModeWrites
        self._dataReady = dataReady
        self._overflow = overflow
        self._cntl2 = MODE_POWER_DOWN
        self._cntl3 = 0x00
        self.writes: list[tuple[int, int]] = []
        self.reads: list[tuple[int, int]] = []
        self.entered = 0

    # -- adafruit I2CDevice surface -------------------------------------------
    def __enter__(self) -> FakeAk09916:
        self.entered += 1
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def write(self, buf: bytes) -> None:
        register, value = buf[0], buf[1]
        self.writes.append((register, value))
        if register == REG_CNTL2 and self._acceptModeWrites:
            self._cntl2 = value
        elif register == 0x32:
            self._cntl3 = value

    def write_then_readinto(self, out: bytes, into: bytearray) -> None:
        start = out[0]
        self.reads.append((start, len(into)))
        for offset in range(len(into)):
            into[offset] = self._registerValue(start + offset)
        # The latch: reaching ST2 releases the measurement, which permits the
        # next conversion to land. A frame that stops short does NOT release it,
        # so the same sample is served again -- the production defect, in a fake.
        if start <= REG_ST2 < start + len(into):
            self._released = True

    # -- register file ---------------------------------------------------------
    def _currentSample(self) -> tuple[int, int, int]:
        if self._released and self._index + 1 < len(self._samples):
            self._index += 1
            self._released = False
        return self._samples[self._index]

    def _registerValue(self, register: int) -> int:
        if register == REG_WIA2:
            return self._whoAmI
        if register == REG_CNTL2:
            return self._cntl2
        if register == 0x32:
            return self._cntl3
        if register == REG_ST1:
            # Reading ST1 is the head of the burst; it is what samples the chip.
            self._pending = self._currentSample()
            return 0x01 if self._dataReady else 0x00
        if REG_ST1 < register <= 0x16:
            values = getattr(self, "_pending", None) or self._samples[self._index]
            raw = values[(register - 0x11) // 2]
            packed = (raw & 0xFFFF).to_bytes(2, "little")
            return packed[(register - 0x11) % 2]
        if register == REG_ST2:
            return 0x08 if self._overflow else 0x00
        return 0x00


def _makeReader(**kw) -> tuple[Ak09916Direct, FakeAk09916]:
    """Build a configured reader over a fake chip."""
    fake = FakeAk09916(**kw)
    return Ak09916Direct(fake), fake


class TestConfigure:
    """Configuration must PROVE it landed, never assume it."""

    def test_configure_correctChip_setsContinuousModeAndVerifies(self):
        """
        Given: an AK09916 answering the expected WHO_AM_I
        When: the reader configures it
        Then: CNTL2 ends in continuous 100 Hz and the reader reports the mode it
              READ BACK, not the one it requested.
        """
        reader, fake = _makeReader()

        assert reader.configure() == MODE_CONTINUOUS_100HZ
        assert fake.writes[-1] == (REG_CNTL2, MODE_CONTINUOUS_100HZ)

    def test_configure_beforeSettingMode_transitsThroughPowerDown(self):
        """
        Given: a chip that may be in any prior mode
        When: the reader configures it
        Then: CNTL2 is written to power-down FIRST. The datasheet requires the
              transit; skipping it leaves the mode change silently ignored, which
              is indistinguishable from a mode change that worked.
        """
        reader, fake = _makeReader()
        reader.configure()

        modeWrites = [value for register, value in fake.writes if register == REG_CNTL2]
        assert modeWrites[0] == MODE_POWER_DOWN
        assert modeWrites[1] == MODE_CONTINUOUS_100HZ

    def test_configure_wrongWhoAmI_raisesRatherThanProceeding(self):
        """
        Given: something other than the AK09916 answering at 0x0C
        When: the reader configures it
        Then: it raises. Bypass mode exposes a new address on the primary bus;
              proceeding against an unidentified device would decode whatever it
              returned into micro-teslas and publish it as a real heading.
        """
        reader, _ = _makeReader(whoAmI=0x00)

        with pytest.raises(MagnetometerConfigError, match="WHO_AM_I"):
            reader.configure()

    def test_configure_modeWriteDoesNotLand_raisesRatherThanLookingConfigured(self):
        """
        Given: a chip whose CNTL2 write silently does not take
        When: the reader configures it
        Then: it raises. THIS IS THE DEFECT CLASS US-565 EXISTS TO CLOSE: the
              adafruit driver writes CNTL2, discards the completion flag and
              never reads back, so a mode that never reached the chip looked
              exactly like one that did -- for months.
        """
        reader, _ = _makeReader(acceptModeWrites=False)

        with pytest.raises(MagnetometerConfigError, match="CNTL2"):
            reader.configure()

    def test_readMode_readsTheRegisterDirectly(self):
        """
        Given: a configured chip
        When: the mode is queried
        Then: the value comes from a real CNTL2 register read.

        US-565 AC-4 forbids `adafruit_icm20x.magnetometer_data_rate` as a
        verifier: that getter reads CNTL2 and then falls off the end of the
        function with no `return`, so it reports None for every possible mode.
        """
        reader, fake = _makeReader()
        reader.configure()
        before = len(fake.reads)

        assert reader.readMode() == MODE_CONTINUOUS_100HZ
        assert (REG_CNTL2, 1) in fake.reads[before:]


class TestMagneticFrame:
    """The burst read is the anti-latch mechanism; pin its shape and its effect."""

    def test_frame_spansSt1ThroughSt2Inclusive(self):
        """
        Given: the module's frame constants
        When: the frame's extent is computed
        Then: it starts at ST1 and reaches ST2.

        A STRUCTURAL pin on purpose. Behaviour alone is not enough here: this is
        the one property whose violation re-creates the original defect silently,
        and the numbers are easy to "tidy" into a 6-byte data-only read that
        looks more efficient and quietly stops the chip converting.
        """
        assert FRAME_START_REGISTER == REG_ST1
        assert FRAME_START_REGISTER + FRAME_LENGTH - 1 == REG_ST2

    def test_magnetic_consecutiveReads_areNotLatched(self):
        """
        Given: a chip that only loads a new measurement once ST2 has been read
        When: the reader is polled repeatedly
        Then: consecutive readings differ.

        Shorten the frame so it stops before ST2 and this test goes red, because
        the fake then re-serves one measurement forever -- which is precisely
        what the production path did across 20,000 real samples.
        """
        reader, _ = _makeReader()
        reader.configure()

        readings = [reader.magnetic for _ in range(8)]

        assert len(set(readings)) == len(readings)

    def test_magnetic_decodesLittleEndianSignedMicroTeslas(self):
        """
        Given: a known raw measurement, including a negative axis
        When: it is read
        Then: each axis is the signed 16-bit little-endian count scaled by the
              datasheet's 0.15 uT/LSB.
        """
        reader, _ = _makeReader(samples=[_sample(0, 0, 0), _sample(1000, -1000, 32767)])
        reader.configure()

        x, y, z = reader.magnetic

        assert x == pytest.approx(1000 * UT_PER_LSB)
        assert y == pytest.approx(-1000 * UT_PER_LSB)
        assert z == pytest.approx(32767 * UT_PER_LSB)

    def test_magnetic_overflowFlagSet_raisesRatherThanReturningTheValue(self):
        """
        Given: a measurement with ST2's overflow flag set
        When: it is read
        Then: it raises rather than returning the number.

        The datasheet declares overflowed data INVALID. Returning it would be a
        new instance of the exact fault this sprint is closing -- a
        non-measurement wearing data_source='real'. Raising routes the poll into
        the reader's existing, already-honest failed-poll path.
        """
        reader, _ = _makeReader(overflow=True)
        reader.configure()

        with pytest.raises(MagnetometerOverflowError):
            _ = reader.magnetic

    def test_magnetic_dataNotReady_isReportedButStillReturned(self):
        """
        Given: a poll that arrives before a new conversion has landed
        When: it is read
        Then: the reading is returned and `lastDataReady` says it was not fresh.

        Deliberately NOT refused here. Staleness is US-564's gate's job, and it
        owns it with a dwell; refusing a single not-yet-fresh sample in the
        acquisition layer would be a second, competing staleness authority for
        the same fact -- and at 50 Hz polling against a 100 Hz conversion rate it
        would fire on ordinary jitter.
        """
        reader, _ = _makeReader(dataReady=False)
        reader.configure()

        reading = reader.magnetic

        assert len(reading) == 3
        assert reader.lastDataReady is False


class TestBypassEnable:
    """Handing the magnetometer back to the primary bus is order-sensitive."""

    def test_enableI2cBypass_disablesMasterBeforeEnablingBypass(self):
        """
        Given: an ICM-20948 shadowing the magnetometer through its aux master
        When: bypass is enabled
        Then: the aux master is disabled FIRST, then bypass is set. Enabling
              bypass while the master is still driving puts two masters on the
              auxiliary bus at once.
        """
        calls: list[tuple[str, object]] = []

        class FakeIcm:
            def __setattr__(self, name: str, value: object) -> None:
                calls.append((name, value))

        enableI2cBypass(FakeIcm())

        assert ("_i2c_master_enable", False) in calls
        assert ("_bypass_i2c_master", True) in calls
        assert calls.index(("_i2c_master_enable", False)) < calls.index(
            ("_bypass_i2c_master", True)
        )

    def test_addressConstant_isTheMagnetometersOwnAddress(self):
        """
        Given: bypass mode
        When: the magnetometer is addressed
        Then: it is at 0x0C -- its own address on the primary bus, NOT the
              ICM-20948's 0x69. MEASURED: WIA2 read 0x09 there on 2026-08-21.
        """
        assert AK09916_I2C_ADDRESS == 0x0C
        assert WHO_AM_I_VALUE == 0x09


class TestIcm20948DirectMagnetometer:
    """The wrapper swaps ONE channel and must not disturb the others."""

    class FakeIcm:
        acceleration = (0.1, 0.2, 9.8)
        gyro = (0.01, 0.02, 0.03)
        temperature = 31.5
        magnetic = (-1.0, -2.0, -3.0)  # the latched shadow -- must NOT be used

    def test_magnetic_comesFromTheDirectReaderNotTheShadow(self):
        """
        Given: an ICM whose own `.magnetic` still serves the latched shadow
        When: the wrapper is read
        Then: the value comes from the direct AK09916 reader.
        """
        reader, _ = _makeReader(samples=[_sample(10, 20, 30), _sample(40, 50, 60)])
        reader.configure()
        device = Icm20948DirectMagnetometer(self.FakeIcm(), reader)

        assert device.magnetic == pytest.approx(
            (40 * UT_PER_LSB, 50 * UT_PER_LSB, 60 * UT_PER_LSB)
        )

    def test_accelGyroAndTemp_passThroughUntouched(self):
        """
        Given: the wrapper
        When: the other channels are read
        Then: they are the ICM's own values. Atlas measured accel and gyro as
              HEALTHY while the magnetometer was latched, so this fix must be
              provably confined to the one broken channel.
        """
        reader, _ = _makeReader()
        reader.configure()
        icm = self.FakeIcm()
        device = Icm20948DirectMagnetometer(icm, reader)

        assert device.acceleration == icm.acceleration
        assert device.gyro == icm.gyro
        assert device.temperature == icm.temperature

    def test_missingTemperature_stillRaisesAttributeError(self):
        """
        Given: a genuine ICM20948, which has NO `.temperature` (US-500)
        When: the wrapper's temperature is read
        Then: AttributeError propagates, because ImuReader catches exactly that
              to degrade temp to an honest null. A wrapper that swallowed it into
              a default would fabricate a temperature.
        """

        class NoTemp:
            acceleration = (0.0, 0.0, 9.8)
            gyro = (0.0, 0.0, 0.0)

        reader, _ = _makeReader()
        reader.configure()
        device = Icm20948DirectMagnetometer(NoTemp(), reader)

        with pytest.raises(AttributeError):
            _ = device.temperature


class TestAttachDirectMagnetometer:
    """A magnetometer fault must cost the magnetometer, and nothing else."""

    class FakeIcm:
        acceleration = (0.0, 0.0, 9.81)
        gyro = (0.0, 0.0, 0.0)

    def test_bypassSucceeds_returnsTheWrappedDevice(self):
        """
        Given: a magnetometer that identifies and verifies
        When: the device is built
        Then: the wrapped device is returned.
        """
        icm = self.FakeIcm()
        wrapped = object()

        result = _attachDirectMagnetometer(icm, object(), lambda _icm, _bus: wrapped)

        assert result is wrapped

    @pytest.mark.parametrize(
        "failure",
        [
            MagnetometerConfigError("WHO_AM_I mismatch"),
            OSError(121, "Remote I/O error"),
            ValueError("no device at 0x0C"),
        ],
    )
    def test_bypassFails_stillReturnsAWorkingAccelAndGyro(self, failure):
        """
        Given: the magnetometer cannot be identified or verified
        When: the device is built
        Then: the bare ICM comes back, so accel and gyro keep flowing.

        Atlas measured accel and gyro as HEALTHY while the magnetometer was
        latched, and they carry gMag, pitch, grade and the g-trail. Failing the
        whole IMU over one channel would discard valid data to punish a broken
        one. The latched mag that comes back with it is not published as a
        reading -- the US-564 gate refuses it as sensor_stale.
        """

        def boom(_icm, _bus):
            raise failure

        icm = self.FakeIcm()

        result = _attachDirectMagnetometer(icm, object(), boom)

        assert result is icm
        assert result.acceleration == (0.0, 0.0, 9.81)


def _loadCapture(path: Path, columns: list[str]) -> dict[str, list[float]]:
    """Load a real capture into per-column series, at FULL precision.

    Values are never rounded: bit-identity is the property under test downstream,
    and rounding would manufacture the very invariance the gate detects.

    Raises:
        AssertionError: If the fixture is missing. A FAILURE, not a skip -- these
            files are the only hardware evidence that the fix works, and a skip
            would restore the unfalsifiable state while the suite still read
            green.
    """
    assert path.is_file(), (
        f"missing the real-hardware capture at {path} -- US-565's acquisition fix "
        "cannot be evidenced without it; re-capture it from the Pi rather than "
        "deleting or skipping this test (see the CSV header for the command)"
    )
    series: dict[str, list[float]] = {name: [] for name in columns}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = line.strip()
        if not row or row.startswith("#"):
            continue
        parts = [float(p) for p in row.split(",")]
        for index, name in enumerate(columns):
            series[name].append(parts[index])
    return series


def _longestIdenticalRun(values: list[float]) -> int:
    """The longest run of consecutive bit-identical samples in a series."""
    longest = 1
    run = 1
    for index in range(1, len(values)):
        run = run + 1 if values[index] == values[index - 1] else 1
        longest = max(longest, run)
    return longest


class TestAgainstRealBypassCapture:
    """The evidence half: two real captures, one gate, opposite verdicts."""

    def test_capture_matchesItsDocumentedProvenance(self):
        """
        Given: the bypass capture
        When: its row and distinct-value counts are re-derived FROM THE DATA
        Then: they match the counts its own header block claims.

        Regenerate it rounded, truncated or synthetic and it goes red HERE,
        loudly, instead of silently weakening every assertion in this class.
        """
        series = _loadCapture(_BYPASS_FIXTURE, ["mag_x", "mag_y", "mag_z", "accel_x"])

        for name, expected in _BYPASS_DISTINCT.items():
            assert len(series[name]) == _BYPASS_ROWS, f"{name} row count moved"
            assert len(set(series[name])) == expected, (
                f"{name} distinct-value count no longer matches the fixture header"
            )

    def test_bypassCapture_isNeverCalledStale(self):
        """
        Given: 90 s of REAL bypass-acquired magnetometer data, board stationary
        When: every sample is replayed through the US-564 invariance gate
        Then: not one is refused.

        Stationary is the HARD case for this direction: there is no motion to
        force variation, so anything that survives is genuine sensor dither.
        """
        series = _loadCapture(_BYPASS_FIXTURE, ["mag_x", "mag_y", "mag_z", "accel_x"])
        gate = PlausibilityGate(
            sampleHz=_BYPASS_HZ,
            policies={_MAG_TOPIC: ChannelPolicy(invariance=True)},
        )
        samples = list(zip(series["mag_x"], series["mag_y"], series["mag_z"]))

        for index, mag in enumerate(samples):
            verdict = gate.check(_MAG_TOPIC, mag)
            assert verdict.ok is True, (
                f"the FIXED magnetometer was refused as {verdict.reason} at real "
                f"sample {index + 1}/{_BYPASS_ROWS} ({mag})"
            )

    def test_bypassCapture_longestIdenticalRun_isFarBelowTheDwell(self):
        """
        Given: the bypass capture and the gate's derived run limit
        When: the longest consecutive bit-identical run is measured
        Then: it sits well under the limit -- margin, not a near miss.

        Passing the previous test by one sample would be luck. This states how
        much room the fix actually has, so a future regression that halves the
        dither is visible before it starts refusing real data.
        """
        series = _loadCapture(_BYPASS_FIXTURE, ["mag_x", "mag_y", "mag_z", "accel_x"])
        gate = PlausibilityGate(
            sampleHz=_BYPASS_HZ,
            policies={_MAG_TOPIC: ChannelPolicy(invariance=True)},
        )
        samples = list(zip(series["mag_x"], series["mag_y"], series["mag_z"]))

        longest = _longestIdenticalRun(samples)

        assert longest < gate.invariantRunLimit / 2, (
            f"longest identical run {longest} is uncomfortably close to the run "
            f"limit {gate.invariantRunLimit}"
        )

    def test_theSameGateStillRefusesTheOldLatchedCapture(self):
        """
        Given: the ORIGINAL latched capture and the SAME gate configuration
        When: it is replayed
        Then: it IS refused as stale.

        This is the control. Without it, the previous test is satisfied by a gate
        that refuses nothing at all, and the whole class would prove only that
        two CSVs parse.
        """
        series = _loadCapture(
            _LATCHED_FIXTURE,
            [
                "accel_x",
                "accel_y",
                "accel_z",
                "gyro_x",
                "gyro_y",
                "gyro_z",
                "mag_x",
                "mag_y",
                "mag_z",
            ],
        )
        gate = PlausibilityGate(
            sampleHz=_LATCHED_ROWS / 90.0,
            policies={_MAG_TOPIC: ChannelPolicy(invariance=True)},
        )
        samples = list(zip(series["mag_x"], series["mag_y"], series["mag_z"]))
        assert len(samples) == _LATCHED_ROWS

        reasons = {gate.check(_MAG_TOPIC, mag).reason for mag in samples}

        assert REASON_SENSOR_STALE in reasons
