################################################################################
# File Name: test_temp_register_probe.py
# Purpose/Description: ARCH-046 -- pin the ICM-20948 temperature conversion to
#                      the datasheet, and pin the probe's verdict logic so a
#                      frozen read path can never be reported as a dead register.
# Author: Atlas (ARCH-046)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Tests for the ICM-20948 temperature-register probe (ARCH-046)."""

from __future__ import annotations

from tools.imu.temp_register_probe import ROOM_TEMP_C, _s16, summarise, tempDegC


class TestTempConversion:
    """DS-000189 rev 1.3 section 8.31, held at hardware/datasheets/icm-20948/."""

    def test_zeroRaw_isRoomTempOffsetPoint(self) -> None:
        """TEMP_degC = ((TEMP_OUT - 0) / 333.87) + 21, so raw 0 is exactly 21 C."""
        assert tempDegC(0) == ROOM_TEMP_C

    def test_measuredRange_convertsToThePlausibleValuesObserved(self) -> None:
        """The 2026-09-22 probe read raw 1408..1648 on a powered board indoors."""
        assert round(tempDegC(1408), 3) == 25.217
        assert round(tempDegC(1648), 3) == 25.936

    def test_sensitivityIsTheDatasheetValue_notARoundedOne(self) -> None:
        """One degree is 333.87 LSB. A rounded 334 would drift ~0.04 C at 25 C."""
        assert round(tempDegC(333.87) - tempDegC(0), 6) == 1.0


class TestSignedDecode:
    def test_negativeTwosComplement(self) -> None:
        assert _s16(0xFF, 0xFF) == -1
        assert _s16(0x80, 0x00) == -32768
        assert _s16(0x7F, 0xFF) == 32767


class TestVerdictLogic:
    """The verdict must never call a broken read path a dead register."""

    def _samples(self, temps: list[int], moving: bool) -> list[dict]:
        return [
            {
                "t": float(i),
                "accel": [i if moving else 1, 0, 0],
                "gyro": [i if moving else 1, 0, 0],
                "tempRaw": t,
                "tempC": tempDegC(t),
            }
            for i, t in enumerate(temps)
        ]

    def test_frozenTempWithFrozenControl_isVOID_notDead(self) -> None:
        """🔴 THE ONE THAT MATTERS. If accel and gyro are frozen too, the bus is
        broken and a frozen temp says NOTHING about temp. Reporting 'dead
        register' here would be the whole investigation's failure mode.
        """
        out = {"samples": self._samples([0, 0, 0], moving=False), "tempDisBitSet": False}
        assert summarise(out)["verdict"].startswith("VOID")

    def test_frozenTempWithLIVEControl_isDEAD(self) -> None:
        out = {"samples": self._samples([0, 0, 0], moving=True), "tempDisBitSet": False}
        assert summarise(out)["verdict"].startswith("DEAD")

    def test_varyingTempWithLiveControl_isEXISTS_AND_WORKS(self) -> None:
        out = {"samples": self._samples([1408, 1500, 1648], moving=True), "tempDisBitSet": False}
        assert summarise(out)["verdict"].startswith("EXISTS AND WORKS")

    def test_tempDisSet_reportsDISABLED_evenWhenFrozen(self) -> None:
        """Disabled is a THIRD answer -- not a dead part and not a driver gap."""
        out = {"samples": self._samples([0, 0, 0], moving=True), "tempDisBitSet": True}
        assert summarise(out)["verdict"].startswith("EXISTS BUT DISABLED")
