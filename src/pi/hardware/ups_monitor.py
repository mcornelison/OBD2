################################################################################
# File Name: ups_monitor.py
# Purpose/Description: UPS telemetry monitor for Geekworm X1209 UPS HAT
#                      (MAX17048-family LiPo fuel gauge at I2C 0x36)
# Author: Ralph Agent
# Creation Date: 2026-01-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-25    | Ralph Agent  | Initial implementation for US-RPI-006
# 2026-04-18    | Rex (Ralph)  | US-180 rewrite for actual chip: MAX17048 fuel
#                              | gauge register map (VCELL/SOC/CRATE, big-endian
#                              | byte-swap, 78.125uV/LSB + 0.208%/hr/LSB scale).
#                              | Replaced getBatteryCurrent() with
#                              | getChargeRatePercentPerHour(); getPowerSource()
#                              | now derived from Pi 5 PMIC EXT5V_V (via
#                              | vcgencmd) since MAX17048 has no power-source
#                              | register. See BL-005/TD-016 for chip details.
# 2026-04-18    | Rex (Ralph)  | US-184: replaced EXT5V-based power-source
#                              | detection (broken — X1209 regulates the rail
#                              | under both wall and UPS boost, I-015) with a
#                              | VCELL-trend + CRATE-polarity heuristic over a
#                              | rolling window. readExt5vVoltageFromVcgencmd()
#                              | retained as diagnostic telemetry only.
# ================================================================================
################################################################################

"""
UPS telemetry monitor for Geekworm X1209 UPS HAT.

The X1209 carries a MAX17048-family single-cell LiPo fuel gauge at I2C 0x36.
The chip reports battery cell voltage (VCELL) and state-of-charge (SOC) with
a built-in ModelGauge algorithm; it has no current-sense register and no
AC-vs-battery sense pin.

Power-source detection uses a VCELL-trend + CRATE-polarity heuristic. The
monitor keeps a rolling buffer of (timestamp, VCELL, SOC) samples populated
by the polling loop. On each tick:

  1. If CRATE is available and below `crateThresholdPercentPerHour`
     (e.g. < -0.05 %/hr), the cell is discharging -> BATTERY.
  2. Else, if the VCELL slope over the window is below
     `vcellSlopeThresholdVoltsPerMinute` (e.g. < -0.02 V/min), the cell is
     draining -> BATTERY.
  3. Else -> EXTERNAL.
  4. If neither signal is available (no CRATE and < 2 samples), the
     cached last source is returned (starts EXTERNAL on first boot).

EXT5V via `vcgencmd pmic_read_adc EXT5V_V` is retained as diagnostic
telemetry only — the X1209 regulates that rail in both wall-power and
UPS-boost modes, so it cannot distinguish AC vs battery (I-015).

Word registers on MAX17048 are stored big-endian, but SMBus `read_word_data`
returns little-endian, so every raw word read is byte-swapped inside this
module.

Usage:
    from hardware.ups_monitor import UpsMonitor, PowerSource

    def onPowerChange(oldSource, newSource):
        print(f"Power changed: {oldSource.value} -> {newSource.value}")

    monitor = UpsMonitor(address=0x36)
    monitor.onPowerSourceChange = onPowerChange
    monitor.startPolling(interval=5.0)

    # Read telemetry
    voltage = monitor.getBatteryVoltage()              # volts, ~3.0-4.3 for LiPo
    percentage = monitor.getBatteryPercentage()        # 0-100 (ModelGauge SOC)
    chargeRate = monitor.getChargeRatePercentPerHour() # %/hr, signed, may be None
    source = monitor.getPowerSource()                  # VCELL-trend + CRATE

    # Stop monitoring
    monitor.stopPolling()

Note:
    Requires I2cClient on a Raspberry Pi for the fuel-gauge reads. Samples
    used for trend detection are recorded by the background polling loop,
    so getPowerSource() returns the cached source (EXTERNAL by default)
    until at least two polls have elapsed.
"""

import logging
import re
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from enum import Enum

from .i2c_client import (
    I2cClient,
    I2cDeviceNotFoundError,
    I2cError,
    I2cNotAvailableError,
)
from .platform_utils import isRaspberryPi

logger = logging.getLogger(__name__)


# ================================================================================
# UPS Exceptions
# ================================================================================


class UpsMonitorError(Exception):
    """Base exception for UPS monitor errors."""
    pass


class UpsNotAvailableError(UpsMonitorError):
    """Exception raised when UPS is not available."""
    pass


# ================================================================================
# UPS Constants
# ================================================================================


class PowerSource(Enum):
    """Power source enumeration for UPS."""
    EXTERNAL = "external"
    BATTERY = "battery"
    UNKNOWN = "unknown"


# MAX17048-family fuel gauge register map (authoritative: MAX17048 datasheet).
# All 16-bit registers are big-endian on the wire; SMBus read_word_data
# returns little-endian, so every raw word read is byte-swapped before use.
REGISTER_VCELL = 0x02    # Cell voltage (RO word, 78.125 uV/LSB)
REGISTER_SOC = 0x04      # State of charge (RO word, high byte = integer %)
REGISTER_MODE = 0x06     # Mode/Quickstart (WO on MAX17048; reads 0)
REGISTER_VERSION = 0x08  # Chip version (RO word; expect 0x0002 family)
REGISTER_CONFIG = 0x0C   # Config (RW word; boots to 0x971C family default)
REGISTER_CRATE = 0x16    # Charge rate (RO word, signed, 0.208 %/hr/LSB)

# MAX17048 scale factors (from datasheet).
MAX17048_VCELL_LSB_V = 78.125e-6
MAX17048_CRATE_LSB_PCT_PER_HR = 0.208

# Some MAX17048 variants do not populate CRATE and return 0xFFFF; treat as None.
CRATE_DISABLED_RAW = 0xFFFF

# Pi 5 PMIC EXT5V_V threshold — kept for diagnostic telemetry only.
# The X1209 regulates the Pi-side rail under both wall power and UPS boost
# so this signal does NOT distinguish AC vs battery on this HAT (I-015);
# AC-vs-battery detection is now via VCELL-trend + CRATE in getPowerSource().
EXT5V_EXTERNAL_THRESHOLD_V = 4.5

# Default configuration
DEFAULT_UPS_ADDRESS = 0x36
DEFAULT_I2C_BUS = 1
DEFAULT_POLL_INTERVAL = 5.0  # seconds

# US-184 power-source detection defaults.  Session 20 bench drill saw
# VCELL drop from 4.181V to 3.66V over ~10min of UPS discharge (slope
# ≈ -0.05 V/min); -0.02 V/min is a safety margin that flips BATTERY
# well inside a single window without tripping on bench noise.  -0.05 %/hr
# is a CRATE margin that catches any real discharge (Session 20 saw
# -0.21 %/hr) but ignores near-idle float.
DEFAULT_HISTORY_WINDOW_SECONDS = 60.0
DEFAULT_VCELL_SLOPE_THRESHOLD_V_PER_MIN = -0.02
DEFAULT_CRATE_THRESHOLD_PCT_PER_HR = -0.05


# ================================================================================
# Helpers
# ================================================================================


def _byteSwap16(word: int) -> int:
    """Swap the two bytes of a 16-bit word.

    MAX17048 stores every 16-bit register big-endian, but SMBus
    `read_word_data()` returns little-endian. Without this swap, a fully
    charged LiPo cell reads as ~20 V instead of ~4.2 V.

    Args:
        word: 16-bit value as returned by SMBus `read_word_data`.

    Returns:
        Byte-swapped 16-bit value.
    """
    return ((word & 0xFF) << 8) | ((word >> 8) & 0xFF)


def _signExtend16(word: int) -> int:
    """Treat a 16-bit word as two's-complement signed."""
    return word - 65536 if word > 32767 else word


def readExt5vVoltageFromVcgencmd() -> float | None:
    """Read the Pi 5 PMIC's EXT5V_V ADC channel via `vcgencmd`.

    MAX17048 has no AC-vs-battery sense register, so EXT5V is the only
    signal available that tells us whether wall power is currently
    feeding the UPS. This helper is the default for
    `UpsMonitor.getPowerSource()`.

    Returns:
        EXT5V voltage in volts, or None if `vcgencmd` is unavailable or
        the output cannot be parsed.
    """
    try:
        result = subprocess.run(
            ['vcgencmd', 'pmic_read_adc', 'EXT5V_V'],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.debug(f"vcgencmd EXT5V_V unavailable: {e}")
        return None

    if result.returncode != 0:
        logger.debug(
            f"vcgencmd EXT5V_V failed: rc={result.returncode} "
            f"stderr={result.stderr.strip()!r}"
        )
        return None

    match = re.search(r'=\s*([\d.]+)\s*V', result.stdout)
    if not match:
        logger.debug(f"vcgencmd EXT5V_V output not parseable: {result.stdout!r}")
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


# ================================================================================
# UPS Monitor Class
# ================================================================================


class UpsMonitor:
    """
    Monitor for the Geekworm X1209 UPS HAT (MAX17048 fuel gauge) via I2C.

    Reads cell voltage / SOC / charge-rate from the fuel gauge and derives
    AC-vs-battery state from the Pi 5 PMIC's EXT5V_V rail.  Polling in a
    background thread invokes `onPowerSourceChange` on transitions.

    Attributes:
        address: I2C address of the fuel gauge (default: 0x36)
        bus: I2C bus number (default: 1)
        pollInterval: Polling interval in seconds (default: 5.0)
        onPowerSourceChange: Callback for power source changes

    Example:
        monitor = UpsMonitor()
        monitor.onPowerSourceChange = lambda old, new: print(f"{old} -> {new}")
        monitor.startPolling()
    """

    def __init__(
        self,
        address: int = DEFAULT_UPS_ADDRESS,
        bus: int = DEFAULT_I2C_BUS,
        pollInterval: float = DEFAULT_POLL_INTERVAL,
        i2cClient: I2cClient | None = None,
        ext5vReader: Callable[[], float | None] | None = None,
        historyWindowSeconds: float = DEFAULT_HISTORY_WINDOW_SECONDS,
        vcellSlopeThresholdVoltsPerMinute: float = (
            DEFAULT_VCELL_SLOPE_THRESHOLD_V_PER_MIN
        ),
        crateThresholdPercentPerHour: float = DEFAULT_CRATE_THRESHOLD_PCT_PER_HR,
        monotonicClock: Callable[[], float] | None = None,
    ):
        """
        Initialize UPS monitor.

        Args:
            address: I2C address of the fuel gauge (default: 0x36)
            bus: I2C bus number (default: 1)
            pollInterval: Polling interval in seconds (default: 5.0)
            i2cClient: Optional pre-configured I2C client (for testing)
            ext5vReader: Optional callable returning EXT5V voltage in volts
                (for diagnostic telemetry only); defaults to
                `readExt5vVoltageFromVcgencmd`. EXT5V is no longer used for
                AC-vs-battery detection — see I-015.
            historyWindowSeconds: Rolling window over which VCELL slope is
                computed for power-source detection. Default 60s.
            vcellSlopeThresholdVoltsPerMinute: If VCELL slope (V/min) over
                the window is strictly less than this (more negative), the
                source is declared BATTERY. Default -0.02 V/min.
            crateThresholdPercentPerHour: If CRATE is available and strictly
                less than this value (more negative), the source is declared
                BATTERY without waiting for VCELL history. Default
                -0.05 %/hr.
            monotonicClock: Optional callable returning a monotonic time in
                seconds (for testing); defaults to `time.monotonic`.
        """
        self._address = address
        self._bus = bus
        self._pollInterval = pollInterval

        self.onPowerSourceChange: Callable[[PowerSource, PowerSource], None] | None = None

        self._pollingThread: threading.Thread | None = None
        self._stopEvent = threading.Event()
        self._isPolling = False

        self._lastPowerSource: PowerSource | None = None

        self._consecutivePollErrors: int = 0
        self._backoffInterval: float = pollInterval

        self._i2cClient: I2cClient | None = i2cClient
        self._clientOwned = i2cClient is None

        self._ext5vReader: Callable[[], float | None] = (
            ext5vReader or readExt5vVoltageFromVcgencmd
        )

        self._historyWindowSeconds = historyWindowSeconds
        self._vcellSlopeThreshold = vcellSlopeThresholdVoltsPerMinute
        self._crateThreshold = crateThresholdPercentPerHour
        self._clock: Callable[[], float] = monotonicClock or time.monotonic

        self._history: deque[tuple[float, float, int]] = deque()
        self._historyLock = threading.Lock()

        # Initial cached source — used when the buffer is too small AND
        # CRATE isn't available.  Starts EXTERNAL because the bench/car
        # state at first boot is "wall power is feeding the UPS" until
        # proven otherwise.
        self._cachedSource: PowerSource = PowerSource.EXTERNAL

        logger.debug(
            f"UpsMonitor initialized: address=0x{address:02x}, bus={bus}, "
            f"pollInterval={pollInterval}s, "
            f"historyWindow={historyWindowSeconds}s, "
            f"vcellSlopeThreshold={vcellSlopeThresholdVoltsPerMinute} V/min, "
            f"crateThreshold={crateThresholdPercentPerHour} %/hr"
        )

    def _getClient(self) -> I2cClient:
        """
        Get or create the I2C client.

        Returns:
            I2C client instance.

        Raises:
            UpsNotAvailableError: If I2C is not available.
        """
        if self._i2cClient is not None:
            return self._i2cClient

        if not isRaspberryPi():
            raise UpsNotAvailableError(
                "UPS monitoring not available - not running on Raspberry Pi"
            )

        try:
            self._i2cClient = I2cClient(bus=self._bus)
            return self._i2cClient
        except I2cNotAvailableError as e:
            raise UpsNotAvailableError(f"UPS not available: {e}") from e

    def _readSwappedWord(self, register: int) -> int:
        """Read a 16-bit MAX17048 register and byte-swap it to chip order."""
        client = self._getClient()
        raw = client.readWord(self._address, register)
        return _byteSwap16(raw)

    def getBatteryVoltage(self) -> float:
        """
        Read battery cell voltage from the MAX17048 VCELL register (0x02).

        Big-endian 16-bit value times 78.125 µV/LSB.

        Returns:
            Battery voltage in volts (typical LiPo: 3.0-4.3 V).

        Raises:
            UpsMonitorError: If read fails.
            UpsNotAvailableError: If UPS is not available.
        """
        try:
            raw = self._readSwappedWord(REGISTER_VCELL)
            volts = raw * MAX17048_VCELL_LSB_V
            logger.debug(f"VCELL raw={raw} -> {volts:.4f}V")
            return volts
        except I2cDeviceNotFoundError as e:
            raise UpsNotAvailableError(
                f"UPS device not found at address 0x{self._address:02x}"
            ) from e
        except I2cError as e:
            raise UpsMonitorError(f"Failed to read battery voltage: {e}") from e

    def getBatteryPercentage(self) -> int:
        """
        Read battery state-of-charge from the MAX17048 SOC register (0x04).

        High byte of the big-endian 16-bit register is the integer percent;
        the low byte is fractional 1/256 % and is dropped here.

        The ModelGauge algorithm needs a few minutes of observation after
        fresh power-up before SOC is meaningful; early reads may be
        significantly off until the chip calibrates.

        Returns:
            Battery percentage clamped to 0-100.

        Raises:
            UpsMonitorError: If read fails.
            UpsNotAvailableError: If UPS is not available.
        """
        try:
            raw = self._readSwappedWord(REGISTER_SOC)
            integerPct = (raw >> 8) & 0xFF
            pct = max(0, min(100, integerPct))
            logger.debug(f"SOC raw=0x{raw:04x} -> {pct}%")
            return pct
        except I2cDeviceNotFoundError as e:
            raise UpsNotAvailableError(
                f"UPS device not found at address 0x{self._address:02x}"
            ) from e
        except I2cError as e:
            raise UpsMonitorError(f"Failed to read battery percentage: {e}") from e

    def getChargeRatePercentPerHour(self) -> float | None:
        """
        Read charge rate from the MAX17048 CRATE register (0x16).

        Signed 16-bit big-endian value times 0.208 %/hr/LSB.  Positive
        means charging, negative means discharging.  Some MAX17048
        variants return 0xFFFF on CRATE — those are treated as
        unavailable and this method returns None in that case.

        Returns:
            Charge rate in %/hr, or None if CRATE is unsupported on this chip.

        Raises:
            UpsMonitorError: If read fails.
            UpsNotAvailableError: If UPS is not available.
        """
        try:
            client = self._getClient()
            rawLe = client.readWord(self._address, REGISTER_CRATE)
            if rawLe == CRATE_DISABLED_RAW:
                logger.debug("CRATE register disabled on this variant (0xFFFF)")
                return None
            raw = _byteSwap16(rawLe)
            signed = _signExtend16(raw)
            rate = signed * MAX17048_CRATE_LSB_PCT_PER_HR
            logger.debug(f"CRATE raw={signed} -> {rate:.3f}%/hr")
            return rate
        except I2cDeviceNotFoundError as e:
            raise UpsNotAvailableError(
                f"UPS device not found at address 0x{self._address:02x}"
            ) from e
        except I2cError as e:
            raise UpsMonitorError(f"Failed to read charge rate: {e}") from e

    def getVersion(self) -> int | None:
        """
        Read the MAX17048 VERSION register (0x08).

        Useful for chip-identity diagnostics.  Returns None if the read
        fails for any reason — callers should treat this as best-effort.

        Returns:
            Byte-swapped 16-bit VERSION value (MAX17048 family is 0x000?),
            or None if the read fails.
        """
        try:
            return self._readSwappedWord(REGISTER_VERSION)
        except (UpsMonitorError, UpsNotAvailableError) as e:
            logger.debug(f"VERSION read failed: {e}")
            return None

    def getDiagnosticExt5vVoltage(self) -> float | None:
        """
        Return the Pi 5 PMIC EXT5V_V rail voltage for diagnostic telemetry.

        This is NOT used for AC-vs-battery detection on the X1209 HAT —
        the HAT regulates the rail in both wall-power and UPS-boost modes,
        so EXT5V cannot distinguish source (I-015). It's still a useful
        "is the HAT delivering power?" sanity signal and is therefore
        retained in telemetry.

        Returns:
            EXT5V voltage in volts, or None if the reader is unavailable
            (e.g. non-Pi host, vcgencmd missing, or parse failure).
        """
        try:
            return self._ext5vReader()
        except Exception as e:
            logger.debug(f"EXT5V diagnostic read failed: {e}")
            return None

    def recordHistorySample(
        self,
        timestamp: float,
        vcellVolts: float,
        socPercent: int,
    ) -> None:
        """
        Append a (timestamp, VCELL, SOC) sample to the rolling buffer.

        Samples older than `historyWindowSeconds` are pruned on each call.
        Buffer size is therefore naturally bounded by (window / poll
        interval) plus a small tail; no maxlen needed.  Called by the
        polling loop; exposed as a public method so tests (and the CIO
        drill helpers) can feed synthetic history without spinning up a
        real thread.

        Args:
            timestamp: Monotonic timestamp in seconds (same clock as
                `self._clock`).
            vcellVolts: VCELL reading in volts.
            socPercent: SOC percentage 0-100.
        """
        with self._historyLock:
            cutoff = timestamp - self._historyWindowSeconds
            while self._history and self._history[0][0] < cutoff:
                self._history.popleft()
            self._history.append((timestamp, vcellVolts, socPercent))

    def _computeVcellSlopeVoltsPerMinute(self) -> float | None:
        """
        Compute VCELL slope across the rolling window in V/min.

        Uses the first-vs-last sample rather than a linear regression —
        over a 60s window where VCELL changes monotonically under real
        discharge, first-vs-last is both O(1) and noise-tolerant enough.

        Returns:
            Slope in V/min, or None if fewer than 2 samples exist or the
            samples span zero wall-clock time (both samples captured at
            the same monotonic tick — not physically possible on-device,
            but defended against for test determinism).
        """
        with self._historyLock:
            if len(self._history) < 2:
                return None
            t0, v0, _ = self._history[0]
            t1, v1, _ = self._history[-1]

        deltaMinutes = (t1 - t0) / 60.0
        if deltaMinutes <= 0.0:
            return None
        return (v1 - v0) / deltaMinutes

    def getPowerSource(self) -> PowerSource:
        """
        Determine AC-vs-battery power source via VCELL-trend + CRATE.

        Decision (first rule that fires wins):

          1. CRATE polarity — if CRATE is available and strictly below
             `crateThresholdPercentPerHour`, declare BATTERY (cell is
             actively discharging).  CRATE is "unavailable" either
             because the chip variant disables it (0xFFFF) or because
             the read raises; in either case the next rule is tried.
          2. VCELL slope — if the slope over the window is strictly
             below `vcellSlopeThresholdVoltsPerMinute`, declare BATTERY.
          3. Otherwise declare EXTERNAL.

        When neither signal is available — CRATE is None AND fewer than
        two VCELL samples are in the buffer — the cached last source is
        returned (initially EXTERNAL).

        The method is stateless in the sense that repeat calls on the
        same inputs yield the same result; but it does update the cached
        source on each call that produces a definite decision, so the
        "no signal yet" fallback tracks the last observed state.

        Returns:
            PowerSource.EXTERNAL, PowerSource.BATTERY, or
            PowerSource.UNKNOWN (only when VCELL cannot be read AND
            CRATE is unavailable AND no history exists).
        """
        crate = self._safeReadCrate()
        slope = self._computeVcellSlopeVoltsPerMinute()

        if crate is not None and crate < self._crateThreshold:
            logger.debug(
                f"getPowerSource: CRATE={crate:.3f} %/hr < "
                f"{self._crateThreshold} -> BATTERY"
            )
            self._cachedSource = PowerSource.BATTERY
            return PowerSource.BATTERY

        if slope is not None and slope < self._vcellSlopeThreshold:
            logger.debug(
                f"getPowerSource: VCELL slope={slope:.4f} V/min < "
                f"{self._vcellSlopeThreshold} -> BATTERY"
            )
            self._cachedSource = PowerSource.BATTERY
            return PowerSource.BATTERY

        if crate is None and slope is None:
            # No CRATE, no history — can't decide; return cache.
            logger.debug(
                f"getPowerSource: no CRATE + insufficient history -> "
                f"cached={self._cachedSource.value}"
            )
            return self._cachedSource

        # At least one signal was readable and neither is in the BATTERY
        # regime — the cell isn't actively draining.
        self._cachedSource = PowerSource.EXTERNAL
        logger.debug(
            f"getPowerSource: crate={crate} slope={slope} -> EXTERNAL"
        )
        return PowerSource.EXTERNAL

    def _safeReadCrate(self) -> float | None:
        """Read CRATE without raising — I/O errors degrade to None."""
        try:
            return self.getChargeRatePercentPerHour()
        except (UpsMonitorError, UpsNotAvailableError) as e:
            logger.debug(f"CRATE read failed during getPowerSource: {e}")
            return None

    def getTelemetry(self) -> dict:
        """
        Read all UPS telemetry values.

        Returns:
            Dict with keys `voltage`, `percentage`, `chargeRatePctPerHr`,
            `powerSource`, and `ext5vVoltage`.  `chargeRatePctPerHr` may
            be None on variants whose CRATE register is not populated.
            `ext5vVoltage` is a diagnostic reading of the Pi 5 PMIC EXT5V
            rail — it's NOT used for power-source detection on the
            X1209 HAT (I-015), only exposed for observability.

        Raises:
            UpsMonitorError: If any I2C read fails.
            UpsNotAvailableError: If UPS is not available.
        """
        return {
            'voltage': self.getBatteryVoltage(),
            'percentage': self.getBatteryPercentage(),
            'chargeRatePctPerHr': self.getChargeRatePercentPerHour(),
            'powerSource': self.getPowerSource(),
            'ext5vVoltage': self.getDiagnosticExt5vVoltage(),
        }

    def startPolling(self, interval: float | None = None) -> None:
        """
        Start polling UPS telemetry in a background thread.

        When power source changes, the onPowerSourceChange callback is invoked.

        Args:
            interval: Polling interval in seconds (default: self.pollInterval).

        Raises:
            RuntimeError: If polling is already running.
            UpsNotAvailableError: If UPS is not available.
        """
        if self._isPolling:
            raise RuntimeError("Polling is already running")

        if interval is not None:
            self._pollInterval = interval

        # Verify UPS is accessible before starting (exercises _getClient,
        # which raises UpsNotAvailableError on non-Pi without an injected client).
        self._getClient()

        try:
            self._lastPowerSource = self.getPowerSource()
        except UpsMonitorError as e:
            logger.warning(f"Could not get initial power source: {e}")
            self._lastPowerSource = PowerSource.UNKNOWN

        self._stopEvent.clear()
        self._isPolling = True

        self._pollingThread = threading.Thread(
            target=self._pollingLoop,
            name="UpsMonitorPolling",
            daemon=True,
        )
        self._pollingThread.start()

        logger.info(f"UPS polling started with interval={self._pollInterval}s")

    def stopPolling(self) -> None:
        """
        Stop polling UPS telemetry.

        Safe to call even if polling is not running.
        """
        if not self._isPolling:
            return

        self._stopEvent.set()

        if self._pollingThread is not None and self._pollingThread.is_alive():
            self._pollingThread.join(timeout=5.0)

        self._isPolling = False
        self._pollingThread = None

        logger.info("UPS polling stopped")

    def _pollingLoop(self) -> None:
        """Background polling loop.

        Each tick reads VCELL + SOC, records them to the rolling history
        buffer (feeds VCELL-slope power-source detection), then samples
        the current power source and fires the onPowerSourceChange
        callback on transitions.  I2C errors suppress history recording
        for that tick — subsequent successful ticks will refill the
        buffer.
        """
        self._backoffInterval = self._pollInterval
        self._consecutivePollErrors = 0

        while not self._stopEvent.is_set():
            try:
                # Exercise the I2C path so missing/broken fuel gauges
                # surface as UpsMonitorError + backoff.  Also feeds the
                # rolling buffer used by the VCELL-trend heuristic.
                vcell = self.getBatteryVoltage()
                try:
                    soc = self.getBatteryPercentage()
                except UpsMonitorError:
                    # SOC is non-critical for source detection; fall
                    # back to 0 rather than skipping the whole sample.
                    soc = 0

                self.recordHistorySample(self._clock(), vcell, soc)

                currentSource = self.getPowerSource()

                if self._consecutivePollErrors > 0:
                    logger.info("UPS device recovered, resuming normal polling")
                    self._consecutivePollErrors = 0
                    self._backoffInterval = self._pollInterval

                if (self._lastPowerSource is not None and
                        currentSource != self._lastPowerSource):

                    logger.info(
                        f"Power source changed: {self._lastPowerSource.value} -> "
                        f"{currentSource.value}"
                    )

                    if self.onPowerSourceChange is not None:
                        try:
                            self.onPowerSourceChange(
                                self._lastPowerSource,
                                currentSource,
                            )
                        except Exception as e:
                            logger.error(f"Error in power change callback: {e}")

                self._lastPowerSource = currentSource

            except UpsMonitorError as e:
                self._consecutivePollErrors += 1
                if self._consecutivePollErrors == 1:
                    logger.warning(f"Error during UPS polling: {e}")
                elif self._consecutivePollErrors == 3:
                    self._backoffInterval = 60.0
                    logger.warning(
                        f"UPS unreachable after {self._consecutivePollErrors} attempts. "
                        f"Backing off to {self._backoffInterval}s polling "
                        "(further errors logged at DEBUG)."
                    )
                else:
                    logger.debug(f"UPS polling error (repeated): {e}")
            except Exception as e:
                logger.error(f"Unexpected error during UPS polling: {e}")

            self._stopEvent.wait(timeout=self._backoffInterval)

    @property
    def address(self) -> int:
        """Get the I2C address."""
        return self._address

    @property
    def bus(self) -> int:
        """Get the I2C bus number."""
        return self._bus

    @property
    def pollInterval(self) -> float:
        """Get the polling interval in seconds."""
        return self._pollInterval

    @pollInterval.setter
    def pollInterval(self, value: float) -> None:
        """Set the polling interval in seconds."""
        if value <= 0:
            raise ValueError("Poll interval must be positive")
        self._pollInterval = value

    @property
    def isPolling(self) -> bool:
        """Check if polling is active."""
        return self._isPolling

    def close(self) -> None:
        """
        Close the UPS monitor and release resources.

        Stops polling if active and closes the I2C client if we own it.
        """
        self.stopPolling()

        if self._clientOwned and self._i2cClient is not None:
            self._i2cClient.close()
            self._i2cClient = None

        logger.debug("UpsMonitor closed")

    def __enter__(self) -> 'UpsMonitor':
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close the monitor."""
        self.close()

    def __del__(self) -> None:
        """Destructor - ensure resources are released."""
        self.close()
