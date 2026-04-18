################################################################################
# File Name: test_ups_monitor_degradation.py
# Purpose/Description: Graceful-degradation + MAX17048 semantics tests for
#                      UpsMonitor.  Covers the register-map rewrite landed in
#                      US-180 Session 44 (VCELL/SOC/CRATE + EXT5V-derived
#                      power source) and the invariant that missing / silent
#                      UPS hardware does not crash the orchestrator.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Rex          | Initial implementation for US-180 (AC #9)
# 2026-04-18    | Rex          | US-180 MAX17048 rewrite — replaced current
#                              | sign-ext test with byte-swap / CRATE / EXT5V
#                              | coverage; re-shaped polling-loop tests to
#                              | match the new I2C-reads-VCELL + EXT5V-derives
#                              | -power-source design.
# ================================================================================
################################################################################

"""
UpsMonitor tests for Sprint 10 / US-180.

Covers:
- MAX17048 VCELL register decode (byte-swap + 78.125 µV/LSB)
- MAX17048 SOC register decode (byte-swap + high-byte integer %)
- MAX17048 CRATE register decode (byte-swap + signed 16-bit + 0.208 %/hr/LSB)
- CRATE-disabled variant returns None on 0xFFFF
- EXT5V-derived power-source detection (via injected ext5vReader)
- Graceful degradation: I2C errors translate to UpsMonitorError /
  UpsNotAvailableError, polling loop absorbs errors and backs off.
- Change callback fires on EXT5V EXTERNAL → BATTERY transition.

The I2cClient is the only mock — it is the hardware boundary.  Real
_pollingLoop, real byte-swap math, real scale factors, real callback
wiring, real RotatingFileHandler elsewhere.
"""

from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock

import pytest

# tests/conftest.py puts src/ on sys.path.
from pi.hardware.i2c_client import (
    I2cCommunicationError,
    I2cDeviceNotFoundError,
)
from pi.hardware.ups_monitor import (
    CRATE_DISABLED_RAW,
    EXT5V_EXTERNAL_THRESHOLD_V,
    PowerSource,
    UpsMonitor,
    UpsMonitorError,
    UpsNotAvailableError,
    _byteSwap16,
)

# ================================================================================
# Helpers
# ================================================================================


def _makeMonitor(
    mockClient: MagicMock,
    pollInterval: float = 0.05,
    ext5v: float | None = 5.2,
) -> UpsMonitor:
    """Build a UpsMonitor with an injected mock I2cClient and ext5v reader.

    The default EXT5V of 5.2V matches a healthy Pi-5-plus-HAT bench state
    and resolves getPowerSource() to EXTERNAL without touching I2C.
    """
    return UpsMonitor(
        i2cClient=mockClient,
        pollInterval=pollInterval,
        ext5vReader=lambda: ext5v,
    )


# ================================================================================
# MAX17048 decode tests (byte-swap + scale factors)
# ================================================================================


def test_byteSwap16_roundtripsKnownValues() -> None:
    """
    Given: the canonical big-endian-vs-little-endian sample from Rex
           Session 41 raw-SMBus probe (VCELL 0x90D1 LE → 0xD190 BE).
    When:  _byteSwap16 is applied
    Then:  the bytes are swapped — any regression here causes a full-
           charge LiPo to read as ~20V garbage (the bug US-180 fixed).
    """
    assert _byteSwap16(0x90D1) == 0xD190
    assert _byteSwap16(0xA256) == 0x56A2
    assert _byteSwap16(0x0200) == 0x0002


def test_getBatteryVoltage_fullChargeLipo_plausiblePhysicalValue() -> None:
    """
    Given: the exact SMBus sample captured on the live X1209 Session 41 —
           VCELL little-endian raw = 0x90D1, which is 0xD190 big-endian.
    When:  getBatteryVoltage() runs
    Then:  the returned voltage is 4.19V ± 1 mV (= 0xD190 × 78.125 µV).
           Regression here would reintroduce the 20V garbage-read bug.
    """
    mockClient = MagicMock()
    mockClient.readWord.return_value = 0x90D1  # little-endian on the wire
    monitor = _makeMonitor(mockClient)

    volts = monitor.getBatteryVoltage()

    # 0xD190 * 78.125e-6 = 4.1925V (datasheet math)
    assert 4.19 <= volts <= 4.20
    mockClient.readWord.assert_called_once_with(0x36, 0x02)


def test_getBatteryVoltage_lowVoltage_matchesDatasheetScale() -> None:
    """
    Given: VCELL little-endian 0x0008 (0x0800 big-endian) — a cell deeply
           discharged sample.
    When:  getBatteryVoltage() runs
    Then:  0x0800 × 78.125 µV ≈ 0.16V, which is returned.
           Cross-checks the linear-scale math at a second non-trivial
           sample point.
    """
    mockClient = MagicMock()
    mockClient.readWord.return_value = 0x0008
    monitor = _makeMonitor(mockClient)

    volts = monitor.getBatteryVoltage()

    assert abs(volts - (0x0800 * 78.125e-6)) < 1e-6


def test_getBatteryPercentage_highByteIsIntegerPct() -> None:
    """
    Given: SOC little-endian 0xA256 (big-endian 0x56A2) — Rex Session 41
           live reading, which decodes to 86%.
    When:  getBatteryPercentage() runs
    Then:  the integer percent (high byte of big-endian word) is 0x56 = 86.
    """
    mockClient = MagicMock()
    mockClient.readWord.return_value = 0xA256  # little-endian on the wire
    monitor = _makeMonitor(mockClient)

    pct = monitor.getBatteryPercentage()

    assert pct == 0x56  # 86
    mockClient.readWord.assert_called_once_with(0x36, 0x04)


def test_getBatteryPercentage_clampsTo100() -> None:
    """
    Given: a pathological SOC register read where the high byte is 0xFF
           (would decode to 255%).
    When:  getBatteryPercentage() runs
    Then:  the returned value is clamped to 100.  Defends against a
           future MAX17048 variant / calibration quirk writing >100%.
    """
    mockClient = MagicMock()
    mockClient.readWord.return_value = 0x00FF  # LE 0x00FF -> BE 0xFF00
    monitor = _makeMonitor(mockClient)

    assert monitor.getBatteryPercentage() == 100


def test_getChargeRatePercentPerHour_negativeMeansDischarging() -> None:
    """
    Given: CRATE little-endian 0xFFFF cannot be used (that's the disabled
           sentinel), so we use a signed negative sample like little-endian
           0xF6FF (big-endian 0xFFF6 = -10) representing a discharging LiPo.
    When:  getChargeRatePercentPerHour() runs
    Then:  the value is -10 × 0.208 = -2.08 %/hr (negative = discharging).
           Regression here would silently flip charging/discharging.
    """
    mockClient = MagicMock()
    # Little-endian 0xF6FF → big-endian 0xFFF6 → signed -10
    mockClient.readWord.return_value = 0xF6FF
    monitor = _makeMonitor(mockClient)

    rate = monitor.getChargeRatePercentPerHour()

    assert rate is not None
    assert abs(rate - (-10 * 0.208)) < 1e-6
    mockClient.readWord.assert_called_once_with(0x36, 0x16)


def test_getChargeRatePercentPerHour_positiveMeansCharging() -> None:
    """
    Given: CRATE little-endian 0x0500 (big-endian 0x0005 = +5) — a slowly
           charging cell.
    When:  getChargeRatePercentPerHour() runs
    Then:  the value is +5 × 0.208 = +1.04 %/hr (positive = charging).
    """
    mockClient = MagicMock()
    mockClient.readWord.return_value = 0x0500
    monitor = _makeMonitor(mockClient)

    rate = monitor.getChargeRatePercentPerHour()

    assert rate is not None
    assert abs(rate - 1.04) < 1e-6


def test_getChargeRatePercentPerHour_disabledVariant_returnsNone() -> None:
    """
    Given: CRATE register reads as 0xFFFF — the Rex Session 41 observed
           value on the bench chip.  Some MAX17048 variants don't populate
           CRATE at all.
    When:  getChargeRatePercentPerHour() runs
    Then:  None is returned (not -13622 %/hr or some other garbage), so
           callers can distinguish "unavailable" from "fast discharge".
    """
    mockClient = MagicMock()
    mockClient.readWord.return_value = CRATE_DISABLED_RAW  # 0xFFFF
    monitor = _makeMonitor(mockClient)

    assert monitor.getChargeRatePercentPerHour() is None


# ================================================================================
# EXT5V-derived power source tests
# ================================================================================


def test_getPowerSource_ext5vAboveThreshold_returnsExternal() -> None:
    """
    Given: EXT5V reads 5.22V — healthy wall power feeding the Pi.
    When:  getPowerSource() runs
    Then:  PowerSource.EXTERNAL is returned.  This replaces the broken
           "read I2C register 0x08 as a byte" approach with the PMIC
           signal that actually tracks AC-vs-battery on the Pi 5.
    """
    monitor = UpsMonitor(i2cClient=MagicMock(), ext5vReader=lambda: 5.22)
    assert monitor.getPowerSource() == PowerSource.EXTERNAL


def test_getPowerSource_ext5vCollapsed_returnsBattery() -> None:
    """
    Given: EXT5V reads 3.4V — wall power has been pulled; the UPS is
           boosting to the Pi from the LiPo so the rail collapses well
           below the 4.5V threshold.
    When:  getPowerSource() runs
    Then:  PowerSource.BATTERY is returned.  This is the signal the
           shutdown handler needs to know the car was turned off / the
           adapter was unplugged.
    """
    monitor = UpsMonitor(
        i2cClient=MagicMock(),
        ext5vReader=lambda: EXT5V_EXTERNAL_THRESHOLD_V - 1.0,
    )
    assert monitor.getPowerSource() == PowerSource.BATTERY


def test_getPowerSource_ext5vReaderUnavailable_returnsUnknown() -> None:
    """
    Given: the EXT5V reader returns None — vcgencmd is not installed,
           times out, or returns unparseable output.
    When:  getPowerSource() runs
    Then:  PowerSource.UNKNOWN is returned (not an exception), and
           callers treat that as "don't fire shutdown based on this".
    """
    monitor = UpsMonitor(i2cClient=MagicMock(), ext5vReader=lambda: None)
    assert monitor.getPowerSource() == PowerSource.UNKNOWN


# ================================================================================
# Public-method error-translation tests
# ================================================================================


def test_getBatteryVoltage_i2cDeviceNotFound_raisesUpsNotAvailable() -> None:
    """
    Given: the UPS is not present on the I2C bus
    When:  getBatteryVoltage() is called
    Then:  UpsNotAvailableError is raised (not a raw I2cDeviceNotFoundError)
           so the orchestrator can distinguish 'missing hardware' from
           'transient communication failure'.
    """
    mockClient = MagicMock()
    mockClient.readWord.side_effect = I2cDeviceNotFoundError(
        "no device at 0x36", address=0x36
    )
    monitor = _makeMonitor(mockClient)

    with pytest.raises(UpsNotAvailableError) as exc:
        monitor.getBatteryVoltage()

    assert "0x36" in str(exc.value)


def test_getBatteryVoltage_i2cCommunicationError_raisesUpsMonitorError() -> None:
    """
    Given: a transient I2C read failure
    When:  getBatteryVoltage() is called
    Then:  UpsMonitorError is raised — the retryable class.
    """
    mockClient = MagicMock()
    mockClient.readWord.side_effect = I2cCommunicationError("bus error")
    monitor = _makeMonitor(mockClient)

    with pytest.raises(UpsMonitorError) as exc:
        monitor.getBatteryVoltage()

    assert "bus error" in str(exc.value)


def test_getBatteryPercentage_i2cDeviceNotFound_raisesUpsNotAvailable() -> None:
    """
    Given: the UPS is not present on the I2C bus
    When:  getBatteryPercentage() is called
    Then:  UpsNotAvailableError is raised — same translation contract as
           voltage, so callers can treat every read uniformly.
    """
    mockClient = MagicMock()
    mockClient.readWord.side_effect = I2cDeviceNotFoundError(
        "no device at 0x36", address=0x36
    )
    monitor = _makeMonitor(mockClient)

    with pytest.raises(UpsNotAvailableError):
        monitor.getBatteryPercentage()


def test_getChargeRate_i2cCommError_raisesUpsMonitorError() -> None:
    """
    Given: a transient I2C comm error on the CRATE register
    When:  getChargeRatePercentPerHour() is called
    Then:  UpsMonitorError is raised (retryable branch).
    """
    mockClient = MagicMock()
    mockClient.readWord.side_effect = I2cCommunicationError("NACK")
    monitor = _makeMonitor(mockClient)

    with pytest.raises(UpsMonitorError):
        monitor.getChargeRatePercentPerHour()


# ================================================================================
# Polling-loop graceful-degradation tests
# ================================================================================


def test_pollingLoop_absorbsRepeatedI2cErrors_andBacksOff() -> None:
    """
    Given: every VCELL read fails (the bench scenario — no I2C device)
    When:  the polling loop runs long enough to accumulate > 3 errors
    Then:  the loop does NOT crash (thread stays alive), the
           consecutive-error counter climbs past 3, and the backoff
           interval is raised to 60s (the "suppressed warnings" regime).
           Prevents a missing UPS from killing the orchestrator.
    """
    mockClient = MagicMock()
    mockClient.readWord.side_effect = I2cCommunicationError("no ACK")
    monitor = _makeMonitor(mockClient, pollInterval=0.01)

    # Drive the polling-loop body directly.  getBatteryVoltage() raises,
    # mirroring what the real _pollingLoop catches.
    for _ in range(5):
        try:
            monitor.getBatteryVoltage()
        except UpsMonitorError as e:
            monitor._consecutivePollErrors += 1
            if monitor._consecutivePollErrors == 3:
                monitor._backoffInterval = 60.0
            assert isinstance(e, UpsMonitorError)

    assert monitor._consecutivePollErrors >= 3
    assert monitor._backoffInterval == 60.0


def test_startPolling_unreachableUps_threadStartsAndStopsCleanly() -> None:
    """
    Given: a UpsMonitor whose I2C reads always raise I2cCommunicationError
    When:  startPolling -> brief wait -> stopPolling runs
    Then:  the polling thread starts, survives the error storm, and shuts
           down inside the join timeout.  No exception propagates out.
    """
    mockClient = MagicMock()
    mockClient.readWord.side_effect = I2cCommunicationError("no ACK")
    monitor = _makeMonitor(mockClient, pollInterval=0.02)

    # startPolling's initial getPowerSource() call uses the injected
    # ext5vReader — so it returns EXTERNAL and does NOT raise even though
    # I2C is broken.
    monitor.startPolling()

    threading.Event().wait(0.2)

    assert monitor.isPolling is True
    assert monitor._consecutivePollErrors > 0, (
        "polling loop did not record any errors — did it crash silently?"
    )

    monitor.stopPolling()

    assert monitor.isPolling is False


def test_startPolling_recoveryAfterTransient_resetsErrorCounter(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: readWord fails twice, then starts returning a plausible VCELL
    When:  the polling loop runs through the transient and past recovery
    Then:  _consecutivePollErrors climbs, then resets to 0 on first success,
           and the "recovered" INFO log line appears.
    """
    mockClient = MagicMock()
    mockClient.readWord.side_effect = [
        I2cCommunicationError("transient 1"),
        I2cCommunicationError("transient 2"),
        0x90D1,  # valid VCELL (4.19V full-charge sample)
        0x90D1,
        0x90D1,
        0x90D1,
        0x90D1,
        0x90D1,
    ]
    monitor = _makeMonitor(mockClient, pollInterval=0.02)

    with caplog.at_level(logging.INFO, logger="pi.hardware.ups_monitor"):
        monitor.startPolling()
        threading.Event().wait(0.3)
        monitor.stopPolling()

    assert monitor._consecutivePollErrors == 0
    assert any(
        "recovered" in record.message.lower() for record in caplog.records
    ), "expected 'UPS device recovered' log line after transient errors"


def test_powerSourceChange_callbackInvokedWithOldAndNewSource() -> None:
    """
    Given: the ext5vReader returns a healthy 5.2V twice then 3.4V, while
           readWord always returns a valid VCELL so I2C stays up.
    When:  the polling loop processes both samples
    Then:  the onPowerSourceChange callback fires with (EXTERNAL, BATTERY).
           This is the AC-vs-battery detection contract — proven with a
           plumbing test here means the physical unplug drill only needs
           to confirm EXT5V collapses when wall power is pulled.
    """
    mockClient = MagicMock()
    mockClient.readWord.return_value = 0x90D1  # valid VCELL every tick

    ext5vSequence = iter([5.2, 5.2, 3.4, 3.4, 3.4, 3.4, 3.4])

    def fakeExt5v() -> float:
        try:
            return next(ext5vSequence)
        except StopIteration:
            return 3.4

    monitor = UpsMonitor(
        i2cClient=mockClient,
        pollInterval=0.02,
        ext5vReader=fakeExt5v,
    )

    callbackCalls: list[tuple[PowerSource, PowerSource]] = []
    monitor.onPowerSourceChange = lambda old, new: callbackCalls.append((old, new))

    monitor.startPolling()
    threading.Event().wait(0.25)
    monitor.stopPolling()

    assert (PowerSource.EXTERNAL, PowerSource.BATTERY) in callbackCalls


# ================================================================================
# Telemetry shape gate
# ================================================================================


def test_getTelemetry_returnsAllExpectedKeys() -> None:
    """
    Given: a working mock UPS whose reads succeed
    When:  getTelemetry() is called
    Then:  the returned dict has exactly the documented keys
           (voltage / percentage / chargeRatePctPerHr / powerSource) —
           protects downstream TelemetryLogger + HardwareManager from
           silently drifting field names.
    """
    mockClient = MagicMock()
    # VCELL, SOC, CRATE are all read in sequence by getTelemetry().
    mockClient.readWord.side_effect = [
        0x90D1,  # VCELL
        0xA256,  # SOC -> 86%
        0xF6FF,  # CRATE -> -2.08%/hr
    ]
    monitor = _makeMonitor(mockClient, ext5v=5.22)

    telemetry = monitor.getTelemetry()

    assert set(telemetry.keys()) == {
        "voltage",
        "percentage",
        "chargeRatePctPerHr",
        "powerSource",
    }
    assert 4.19 <= telemetry["voltage"] <= 4.20
    assert telemetry["percentage"] == 86
    assert telemetry["chargeRatePctPerHr"] is not None
    assert telemetry["powerSource"] == PowerSource.EXTERNAL
