################################################################################
# File Name: test_ups_soc_as_read.py
# Purpose/Description: US-685 -- the drain row stores the MAX17048 SOC register
#                      AS THE CHIP REPORTS IT: fraction kept, no clamp at 100.
#                      The display path keeps its whole-number 0-100 rendering.
# Author: Atlas (Architect) -- US-685, CIO-directed build
# Creation Date: 2026-10-07
################################################################################
"""SOC as read (US-685, CIO ruling 2026-10-07).

DOCUMENTED (MAX17048 datasheet 19-6171, SOC Register 0x04): the upper byte is
1 %/LSb and the lower byte "provides additional resolution"; no 100 % cap is
stated. MEASURED: a drain row recorded 100.7 % through the test CLI, while the
production path wrote such a reading as exactly 100 (high byte only, clamped).

The one value that is NOT a reading: ``0xFFFF``, which this silicon returns for
registers it does not back (I2C silicon audit, 2026-09-26). It becomes ``None``
-- a typed absence -- rather than a 255.996 % row.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.pi.hardware.ups_monitor import UpsMonitor


def _monitor(wireWord: int) -> UpsMonitor:
    client = MagicMock()
    client.readWord.return_value = wireWord  # little-endian on the wire
    return UpsMonitor(i2cClient=client, pollInterval=0.05, ext5vReader=lambda: 5.2)


def _wire(chipWord: int) -> int:
    """The little-endian word the bus returns for a big-endian chip value."""
    return ((chipWord & 0xFF) << 8) | (chipWord >> 8)


def test_theFractionIsKept() -> None:
    # chip 0x56A2 = 86 + 0xA2/256 = 86.6328125 %
    assert _monitor(_wire(0x56A2)).getSocPercentAsRead() == 86 + 0xA2 / 256


def test_aReadingAbove100_isNotClamped() -> None:
    # chip 0x64B3 = 100.69921875 % -- the 100.7 the test CLI recorded
    assert _monitor(_wire(0x64B3)).getSocPercentAsRead() == 100 + 0xB3 / 256


def test_theUnbackedSentinel_isNoReading() -> None:
    assert _monitor(0xFFFF).getSocPercentAsRead() is None


def test_theDisplayReadingIsUnchanged() -> None:
    """getBatteryPercentage keeps its whole-number, 0-100 contract."""
    assert _monitor(_wire(0x64B3)).getBatteryPercentage() == 100
    assert _monitor(_wire(0x56A2)).getBatteryPercentage() == 86


def test_bothReadTheSameRegister() -> None:
    client = MagicMock()
    client.readWord.return_value = _wire(0x56A2)
    monitor = UpsMonitor(i2cClient=client, pollInterval=0.05, ext5vReader=lambda: 5.2)

    monitor.getSocPercentAsRead()

    client.readWord.assert_called_once_with(0x36, 0x04)
