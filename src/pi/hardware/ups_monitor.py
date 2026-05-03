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
# 2026-04-29    | Rex (US-234) | Added getVcell() alias + getVcellHistory(seconds)
#                              | for the orchestrator's VCELL-based shutdown ladder.
#                              | History API exposes the raw rolling buffer that
#                              | already backs VCELL-slope power-source detection.
# 2026-04-29    | Rex (US-235) | BATTERY-detection rewrite. CRATE-rule deleted
#                              | entirely (returned 0xFFFF on this MAX17048
#                              | variant across 4 drain tests, never fired).
#                              | New rules: (a) VCELL sustained <3.95V for >=30s
#                              | -> BATTERY (Spool primary); (b) VCELL slope
#                              | <-0.005 V/min over 60s window -> BATTERY
#                              | (Marcus tuned secondary, was -0.02 V/min).
#                              | getChargeRatePercentPerHour() retained for
#                              | telemetry; only the rule consuming it is gone.
# 2026-05-03    | Rex (US-279) | Event-driven source-change callback API.
#                              | registerSourceChangeCallback(callback) appends
#                              | to self._sourceChangeCallbacks; the polling
#                              | loop's transition handler invokes every
#                              | registered callback with the new PowerSource
#                              | via _invokeSourceChangeCallbacks().  Each
#                              | callback wrapped in try/except so a raising
#                              | consumer does NOT halt the polling loop or
#                              | starve sibling consumers (forensics MUST NOT
#                              | crash safety paths).  Closes the 8-drain saga
#                              | bug class isolated by Drain Test 8 -- the
#                              | polling thread now PUSHES transitions to
#                              | PowerDownOrchestrator instead of the orchestrator
#                              | reading from a stale/decoupled view.  Legacy
#                              | onPowerSourceChange attribute preserved
#                              | unchanged (existing ShutdownHandler / lifecycle
#                              | fan-out path stays intact).
# ================================================================================
################################################################################

"""
UPS telemetry monitor for Geekworm X1209 UPS HAT.

The X1209 carries a MAX17048-family single-cell LiPo fuel gauge at I2C 0x36.
The chip reports battery cell voltage (VCELL) and state-of-charge (SOC) with
a built-in ModelGauge algorithm; it has no current-sense register and no
AC-vs-battery sense pin.

Power-source detection uses two independent VCELL rules. The monitor keeps
a rolling buffer of (timestamp, VCELL, SOC) samples populated by the
polling loop. On each tick:

  1. If VCELL has been continuously below
     `vcellBatteryThresholdVolts` (default 3.95V) for >=
     `vcellBatteryThresholdSustainedSeconds` (default 30s) -> BATTERY.
  2. Else, if the VCELL slope over the rolling window is below
     `vcellSlopeThresholdVoltsPerMinute` (default -0.005 V/min) -> BATTERY.
  3. Else, if either rule has decisive non-BATTERY evidence (most
     recent VCELL above threshold, OR slope is computable and >=
     threshold) -> EXTERNAL.
  4. If neither rule has decisive evidence (e.g. <2 samples),
     return the cached last source (starts EXTERNAL on first boot).

The CRATE register was the primary BATTERY trigger up through Sprint 18
(US-184) but reliably returned 0xFFFF (disabled) on this MAX17048
variant across all 4 drain tests Spool ran in April 2026 -- so the rule
never fired. US-235 deleted it. CRATE is still readable via
`getChargeRatePercentPerHour()` for telemetry purposes; only the
power-source decision branch was removed.

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

# US-235 power-source detection defaults. Across 4 drain tests
# (April 2026), the legacy CRATE rule never fired (CRATE = 0xFFFF on
# this MAX17048 variant) and the legacy slope rule at -0.02 V/min over
# 60s was too lenient -- real drains drifted at ~-0.01 to -0.015 V/min.
# US-235 replaces both with: (a) VCELL sustained below 3.95V for >=30s
# (Spool primary, derived from drain-test VCELL data; the LiPo discharge
# knee on this cell is around 3.7V so 3.95 is comfortably above it but
# below a healthy AC-fed float of ~4.10V); (b) VCELL slope < -0.005
# V/min over 60s (Marcus tuned secondary, catches the slow drift the
# old -0.02 V/min missed).
DEFAULT_HISTORY_WINDOW_SECONDS = 60.0
DEFAULT_VCELL_SLOPE_THRESHOLD_V_PER_MIN = -0.005
DEFAULT_VCELL_BATTERY_THRESHOLD_V = 3.95
DEFAULT_VCELL_BATTERY_THRESHOLD_SUSTAINED_S = 30.0


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
        vcellBatteryThresholdVolts: float = DEFAULT_VCELL_BATTERY_THRESHOLD_V,
        vcellBatteryThresholdSustainedSeconds: float = (
            DEFAULT_VCELL_BATTERY_THRESHOLD_SUSTAINED_S
        ),
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
                computed and within which sustained-below-threshold runs
                are evaluated. Default 60s.
            vcellSlopeThresholdVoltsPerMinute: If VCELL slope (V/min) over
                the window is strictly less than this (more negative), the
                source is declared BATTERY. Default -0.005 V/min (US-235
                tuned from -0.02 V/min after 4 drain tests showed real
                drift was slower than the old threshold).
            vcellBatteryThresholdVolts: If the most recent VCELL reading
                has been continuously below this voltage for at least
                `vcellBatteryThresholdSustainedSeconds`, declare BATTERY.
                Default 3.95V (US-235 primary rule, replaces the broken
                CRATE-polarity rule).
            vcellBatteryThresholdSustainedSeconds: Duration the VCELL must
                stay below `vcellBatteryThresholdVolts` to fire the
                sustained-threshold BATTERY rule. Default 30s.
            monotonicClock: Optional callable returning a monotonic time in
                seconds (for testing); defaults to `time.monotonic`.
        """
        self._address = address
        self._bus = bus
        self._pollInterval = pollInterval

        self.onPowerSourceChange: Callable[[PowerSource, PowerSource], None] | None = None

        # US-279: list-based fan-out callback API.  Consumers register via
        # registerSourceChangeCallback; the polling-loop transition handler
        # invokes every registered callback with the new PowerSource.  This
        # is the path PowerDownOrchestrator subscribes to for the staged-
        # shutdown ladder -- Drain Test 8 (2026-05-03) proved the legacy
        # read-from-cached-state pattern produced a decoupled view across 8
        # consecutive drains.  Push-based notification eliminates the gap.
        self._sourceChangeCallbacks: list[Callable[[PowerSource], None]] = []

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
        self._vcellBatteryThreshold = vcellBatteryThresholdVolts
        self._vcellBatterySustainedSeconds = (
            vcellBatteryThresholdSustainedSeconds
        )
        self._clock: Callable[[], float] = monotonicClock or time.monotonic

        self._history: deque[tuple[float, float, int]] = deque()
        self._historyLock = threading.Lock()

        # Initial cached source — used when the buffer doesn't have
        # enough decisive evidence either way. Starts EXTERNAL because
        # the bench/car state at first boot is "wall power is feeding
        # the UPS" until proven otherwise.
        self._cachedSource: PowerSource = PowerSource.EXTERNAL

        logger.debug(
            f"UpsMonitor initialized: address=0x{address:02x}, bus={bus}, "
            f"pollInterval={pollInterval}s, "
            f"historyWindow={historyWindowSeconds}s, "
            f"vcellSlopeThreshold={vcellSlopeThresholdVoltsPerMinute} V/min, "
            f"vcellBatteryThreshold={vcellBatteryThresholdVolts} V "
            f"sustained {vcellBatteryThresholdSustainedSeconds}s"
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

    def getVcell(self) -> float:
        """Return current cell voltage in volts.

        Thin alias for :meth:`getBatteryVoltage` introduced by US-234.
        The orchestrator (PowerDownOrchestrator) calls this directly at
        each tick to evaluate VCELL-based shutdown thresholds. Kept as
        an alias rather than the canonical name because existing callers
        (telemetry, status display) use ``getBatteryVoltage``.

        Returns:
            VCELL in volts (typical LiPo: 3.0-4.3).

        Raises:
            UpsMonitorError: If read fails.
            UpsNotAvailableError: If UPS is not available.
        """
        return self.getBatteryVoltage()

    def getVcellHistory(
        self, seconds: float | None = None,
    ) -> list[tuple[float, float]]:
        """Return rolling-window VCELL readings as (timestamp, vcell) pairs.

        Reads from the same history buffer that backs the VCELL-slope
        power-source detection (:meth:`recordHistorySample`). Introduced
        by US-234 for consumers (US-235 BATTERY-detection fix, future
        slope-aware orchestrator hysteresis) that need raw samples rather
        than a single slope value.

        Args:
            seconds: If supplied, return only samples newer than
                ``now - seconds`` (where ``now`` is the monitor's own
                monotonic clock). If None, return everything currently
                in the buffer (already bounded by
                ``historyWindowSeconds``).

        Returns:
            List of ``(monotonic_timestamp, vcell_volts)`` pairs in
            chronological order. Empty list if the buffer is empty.
        """
        with self._historyLock:
            samples = list(self._history)
        if seconds is None:
            return [(ts, vcell) for ts, vcell, _soc in samples]
        cutoff = self._clock() - seconds
        return [
            (ts, vcell) for ts, vcell, _soc in samples if ts >= cutoff
        ]

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
        Determine AC-vs-battery power source from VCELL-only rules.

        US-235 replaced the legacy CRATE + VCELL-slope rules with two
        VCELL-only rules. Decision order:

          1. Sustained-threshold rule — if VCELL has stayed continuously
             below `vcellBatteryThresholdVolts` for at least
             `vcellBatteryThresholdSustainedSeconds`, declare BATTERY.
             This is the primary rule (Spool, derived from drain tests).
          2. Slope rule — if the VCELL slope across the rolling window
             is strictly below `vcellSlopeThresholdVoltsPerMinute`,
             declare BATTERY. This catches faster drains before the
             sustained run completes.
          3. Decisive non-BATTERY evidence — if either rule has positive
             evidence the cell isn't draining (most recent VCELL is at
             or above the threshold, OR slope is computable and >=
             threshold), declare EXTERNAL.
          4. Otherwise — return the cached last source (initially
             EXTERNAL on first boot).

        The method updates the cached source on every call that produces
        a definite decision, so the "insufficient evidence" fallback
        always tracks the last observed state.

        Returns:
            PowerSource.EXTERNAL or PowerSource.BATTERY (the heuristic
            never returns UNKNOWN; UNKNOWN only appears when an upstream
            consumer constructs it explicitly, e.g. polling loop init).
        """
        thresholdBattery = self._isVcellSustainedBelowThreshold()
        slope = self._computeVcellSlopeVoltsPerMinute()
        slopeBattery = (
            slope is not None and slope < self._vcellSlopeThreshold
        )

        if thresholdBattery or slopeBattery:
            logger.debug(
                "getPowerSource: thresholdBattery=%s slopeBattery=%s "
                "slope=%s -> BATTERY",
                thresholdBattery,
                slopeBattery,
                f"{slope:.4f}" if slope is not None else None,
            )
            self._cachedSource = PowerSource.BATTERY
            return PowerSource.BATTERY

        thresholdExternal = self._isVcellDecisiveAboveThreshold()
        slopeExternal = (
            slope is not None and slope >= self._vcellSlopeThreshold
        )

        if thresholdExternal or slopeExternal:
            logger.debug(
                "getPowerSource: thresholdExternal=%s slopeExternal=%s "
                "slope=%s -> EXTERNAL",
                thresholdExternal,
                slopeExternal,
                f"{slope:.4f}" if slope is not None else None,
            )
            self._cachedSource = PowerSource.EXTERNAL
            return PowerSource.EXTERNAL

        logger.debug(
            "getPowerSource: insufficient evidence -> cached=%s",
            self._cachedSource.value,
        )
        return self._cachedSource

    def _isVcellSustainedBelowThreshold(self) -> bool:
        """
        Check if VCELL has been continuously sub-threshold long enough.

        Walks the rolling buffer from oldest to newest. If the most
        recent sample is at or above the threshold, the rule cannot
        fire (cell is currently within healthy range). Otherwise, find
        the latest sample that was at or above the threshold; the
        continuous-below run is everything after that. The rule fires
        when that run has spanned at least
        `vcellBatteryThresholdSustainedSeconds` of monotonic time.

        Returns:
            True if the sustained-below-threshold rule should fire
            BATTERY, False otherwise.
        """
        with self._historyLock:
            samples = list(self._history)

        if not samples:
            return False

        # Most recent sample must itself be sub-threshold; if not, the
        # continuous run has already broken, regardless of older state.
        lastTs, lastVcell, _ = samples[-1]
        if lastVcell >= self._vcellBatteryThreshold:
            return False

        # Find the latest sample at-or-above threshold (if any). The
        # continuous-below run starts at index latestAboveIdx + 1.
        latestAboveIdx = -1
        for i in range(len(samples) - 1, -1, -1):
            _ts, vcell, _ = samples[i]
            if vcell >= self._vcellBatteryThreshold:
                latestAboveIdx = i
                break

        runStartIdx = latestAboveIdx + 1
        if runStartIdx >= len(samples):
            # Defensive: should not reach here -- last sample is below.
            return False

        runStartTs, _, _ = samples[runStartIdx]
        return (lastTs - runStartTs) >= self._vcellBatterySustainedSeconds

    def _isVcellDecisiveAboveThreshold(self) -> bool:
        """
        Check if VCELL has decisive evidence the cell isn't draining.

        The "decisive" criterion is: the most recent sample is at or
        above the BATTERY threshold. A single above-threshold sample
        is sufficient because the threshold is set comfortably above
        the LiPo discharge knee -- if the cell can hold above 3.95V on
        the most recent reading, wall power is supplying enough current
        to prevent collapse. Adding a sustained-above-threshold band
        here would unnecessarily delay BATTERY -> EXTERNAL transitions
        on wall-power restore.

        Returns:
            True if the most recent VCELL is at or above the threshold,
            False if no samples exist or the most recent is sub-threshold.
        """
        with self._historyLock:
            samples = list(self._history)

        if not samples:
            return False
        _ts, lastVcell, _ = samples[-1]
        return lastVcell >= self._vcellBatteryThreshold

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

    def registerSourceChangeCallback(
        self, callback: Callable[[PowerSource], None],
    ) -> None:
        """Register a callback fired on every PowerSource transition (US-279).

        The callback is invoked synchronously from the polling thread on
        each EXTERNAL <-> BATTERY (or <-> UNKNOWN) transition with the new
        :class:`PowerSource` as its sole argument.  Multiple callbacks may
        register; all are invoked on every transition.  This is the
        push-based fan-out path that replaces the
        :attr:`onPowerSourceChange` single-attribute pattern for
        consumers that need authoritative transition events without the
        risk of reading from a stale/decoupled view (see Drain Test 8
        2026-05-03 forensic summary -- the bug class US-279 closes).

        The legacy ``onPowerSourceChange`` attribute is preserved
        unchanged: ShutdownHandler.registerWithUpsMonitor + lifecycle.py's
        existing fan-out wrapper continue to use it.  New consumers
        (PowerDownOrchestrator) use this API instead.

        Args:
            callback: Callable taking the new :class:`PowerSource` as its
                only argument and returning ``None``.  Exceptions raised
                by the callback are logged at ERROR level and suppressed
                so a regression in one consumer cannot starve others or
                halt the polling loop -- forensics MUST NOT block safety.
        """
        self._sourceChangeCallbacks.append(callback)
        logger.debug(
            "Registered source-change callback (now %d total)",
            len(self._sourceChangeCallbacks),
        )

    def _invokeSourceChangeCallbacks(self, newSource: PowerSource) -> None:
        """Invoke every registered source-change callback (US-279).

        Iterates :attr:`_sourceChangeCallbacks` and calls each with
        ``newSource``.  Each call is wrapped in a broad-exception guard:
        a raising consumer is logged at ERROR level and suppressed so
        sibling callbacks still fire AND the polling loop continues to
        the next sleep without a crash propagating up.  This invariant
        is load-bearing -- the staged-shutdown ladder MUST receive every
        BATTERY transition even when an unrelated audit consumer
        regresses.

        Called from :meth:`_pollingLoop` on detected transitions and
        directly from tests that simulate the polling-loop trigger.

        Args:
            newSource: The new :class:`PowerSource` to push to consumers.
        """
        for callback in self._sourceChangeCallbacks:
            try:
                callback(newSource)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    "Registered source-change callback raised "
                    "(continuing fan-out): %s", e,
                )

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

                    # US-279: list-based fan-out for consumers (orchestrator)
                    # that subscribed via registerSourceChangeCallback.  The
                    # helper isolates exceptions per-callback so a regressed
                    # consumer cannot halt the polling loop.
                    self._invokeSourceChangeCallbacks(currentSource)

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
