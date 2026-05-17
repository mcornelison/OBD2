################################################################################
# File Name: shutdown_handler.py
# Purpose/Description: Graceful shutdown handler for car power loss detection
# Author: Ralph Agent
# Creation Date: 2026-01-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-25    | Ralph Agent  | Initial implementation for US-RPI-007
# 2026-04-22    | Rex (US-216) | Added suppressLegacyTriggers flag to disable
#                              | the 30s-after-BATTERY timer + 10% low-battery
#                              | trigger when the US-216 PowerDownOrchestrator
#                              | is active. Prevents the race where the
#                              | legacy 10% path fires before the new
#                              | staged-ladder TRIGGER@20% (Spool audit TD-D,
#                              | 2026-04-21).
# 2026-05-15    | Ralph        | I-036 / I-037 V0.27.11 fix (US-341 + US-342).
#                 (US-341/342) | _executeShutdown now (a) emits
#                              | SHUTDOWN_SUCCESS_MARKER after returncode==0
#                              | so the boot_reason ladder probe has an
#                              | honest signal (was matching the orchestrator
#                              | INTENT marker emitted BEFORE the failing
#                              | subprocess.run -- I-037); (b) ERROR-logs and
#                              | raises ShutdownHandlerError on non-zero
#                              | returncode instead of silently warning --
#                              | the 11-day I-036 cover-up.  Polkit rule at
#                              | deploy/polkit-rules/50-eclipse-obd-poweroff.rules
#                              | grants mcornelison the
#                              | org.freedesktop.login1.power-off action.
# 2026-05-15    | Plan (T9)    | _executeShutdown emits POWEROFF_INVOKED
#                              | (pre-subprocess) + POWEROFF_RC0 (on rc==0)
#                              | via fail-safe writer; poweroff subprocess
#                              | timeout now config-driven
#                              | (poweroffTimeoutSeconds, default 30).
# ================================================================================
################################################################################

"""
Graceful shutdown handler for car power loss detection.

This module monitors UPS power source changes and initiates a graceful system
shutdown when the car power is lost (switching to battery). It provides a
configurable delay before shutdown to allow power restoration, and handles
low battery conditions with immediate shutdown.

Usage:
    from hardware.shutdown_handler import ShutdownHandler
    from hardware.ups_monitor import UpsMonitor

    handler = ShutdownHandler(shutdownDelay=30, lowBatteryThreshold=10)
    monitor = UpsMonitor()

    # Register handler with UPS monitor
    handler.registerWithUpsMonitor(monitor)

    # Or use manually
    monitor.onPowerSourceChange = handler.onPowerSourceChange

    # Check for low battery
    percentage = monitor.getBatteryPercentage()
    handler.onLowBattery(percentage)

Note:
    System shutdown requires appropriate permissions (typically root).
    On Raspberry Pi, the system user should have sudo NOPASSWD for systemctl.
"""

import logging
import subprocess
import threading
import time
from collections.abc import Callable

from src.pi.diagnostics.boot_progress import Stage as _BpStage
from src.pi.diagnostics.boot_progress import markMilestone as _bpMarkMilestone
from src.pi.diagnostics.boot_progress import readBootId as _bpBootId

from .ups_monitor import PowerSource, UpsMonitor

logger = logging.getLogger(__name__)


# ================================================================================
# Shutdown Handler Exceptions
# ================================================================================


class ShutdownHandlerError(Exception):
    """Base exception for shutdown handler errors."""
    pass


# ================================================================================
# Shutdown Handler Constants
# ================================================================================

DEFAULT_SHUTDOWN_DELAY = 30  # seconds to wait before shutdown
DEFAULT_LOW_BATTERY_THRESHOLD = 10  # percentage

#: Substring emitted by :meth:`ShutdownHandler._executeShutdown` ONLY after
#: ``systemctl poweroff`` returns 0.  This is the canary signature picked up
#: by :data:`src.pi.diagnostics.boot_reason.LADDER_GRACEFUL_GREP_PATTERN`
#: at next boot to classify the prior boot as cleanly shut down.  Keep this
#: in lockstep with that constant -- the runtime contract test in
#: ``tests/pi/diagnostics/test_boot_reason_canary.py`` enforces drift.
#:
#: Pre-V0.27.11 the probe matched the orchestrator's INTENT marker
#: ("PowerDownOrchestrator: TRIGGER at ...") which fires BEFORE this call,
#: so every drain since V0.24.1 deploy was labeled "clean" even when
#: poweroff failed (I-037 regression unmasked by Drain 22 forensic).
SHUTDOWN_SUCCESS_MARKER = (
    "PowerDownOrchestrator: poweroff accepted by systemd "
    "(graceful shutdown initiated)"
)


# ================================================================================
# Shutdown Handler Class
# ================================================================================


class ShutdownHandler:
    """
    Handler for graceful system shutdown on power loss.

    This class monitors power source changes from the UPS and schedules a
    graceful shutdown when external power is lost. Shutdown can be cancelled
    if power is restored before the delay expires.

    Attributes:
        shutdownDelay: Seconds to wait before shutdown (default: 30)
        lowBatteryThreshold: Battery percentage for immediate shutdown (default: 10)
        isShutdownPending: Whether a shutdown is currently scheduled
        timeUntilShutdown: Seconds until scheduled shutdown (or None)

    Example:
        handler = ShutdownHandler(shutdownDelay=30)
        handler.registerWithUpsMonitor(upsMonitor)
    """

    def __init__(
        self,
        shutdownDelay: int = DEFAULT_SHUTDOWN_DELAY,
        lowBatteryThreshold: int = DEFAULT_LOW_BATTERY_THRESHOLD,
        suppressLegacyTriggers: bool = False,
        poweroffTimeoutSeconds: int = 30,
        bootProgressWriter: Callable[["_BpStage", float | None], None] | None = None,
    ):
        """
        Initialize shutdown handler.

        Args:
            shutdownDelay: Seconds to wait before shutdown (must be positive)
            lowBatteryThreshold: Battery percentage for immediate shutdown (0-100)
            suppressLegacyTriggers: When True, the 30s-after-BATTERY timer and
                the 10% low-battery trigger become no-ops. ``_executeShutdown``
                can still be called explicitly (US-216's PowerDownOrchestrator
                uses this at TRIGGER@20%). Default False preserves pre-US-216
                behavior. Set True when the new staged ladder is enabled to
                prevent the Spool-audit-TD-D race where the legacy 10% path
                would fire before the new ladder's 20% TRIGGER.
            poweroffTimeoutSeconds: Timeout (seconds) for the ``systemctl
                poweroff`` subprocess. Default 30 preserves the pre-T9
                hard-coded timeout. A later task wires this from config.
            bootProgressWriter: Optional ``(stage, vcell)`` callable used to
                record boot-progress milestones. Defaults to a closure over
                :func:`boot_progress.markMilestone` keyed on the live boot id
                (the shared :func:`boot_progress.readBootId`). Tests inject a
                capturing fake. Every mark is routed through the fail-safe
                :meth:`_markBootProgress` wrapper so a breadcrumb failure can
                never block the poweroff attempt or the raise-on-failure path.

        Raises:
            ValueError: If shutdownDelay is not positive or threshold is invalid
        """
        if shutdownDelay <= 0:
            raise ValueError("Shutdown delay must be positive")
        if lowBatteryThreshold < 0 or lowBatteryThreshold > 100:
            raise ValueError("Low battery threshold must be between 0 and 100")

        self._shutdownDelay = shutdownDelay
        self._lowBatteryThreshold = lowBatteryThreshold
        self._suppressLegacyTriggers = bool(suppressLegacyTriggers)
        self._poweroffTimeoutSeconds = poweroffTimeoutSeconds
        # T9: production wires the default markMilestone closure (live boot
        # id via the shared boot_progress.readBootId); tests inject a
        # capturing fake. Built once so the per-seam call site is a one-liner.
        self._bootProgressWriter = bootProgressWriter or (
            lambda stage, vcell: _bpMarkMilestone(
                stage, vcell=vcell, bootId=_bpBootId(),
            )
        )

        # Timer for scheduled shutdown
        self._shutdownTimer: threading.Timer | None = None
        self._shutdownScheduledAt: float | None = None

        # Lock for thread-safe timer operations
        self._lock = threading.Lock()

        logger.debug(
            f"ShutdownHandler initialized: delay={shutdownDelay}s, "
            f"lowBatteryThreshold={lowBatteryThreshold}%, "
            f"suppressLegacyTriggers={self._suppressLegacyTriggers}"
        )

    def onPowerSourceChange(
        self,
        oldSource: PowerSource,
        newSource: PowerSource
    ) -> None:
        """
        Handle power source change event.

        Called by UpsMonitor when power source changes. Schedules shutdown
        when switching to battery power, cancels shutdown when power is restored.

        Args:
            oldSource: Previous power source
            newSource: Current power source

        Example:
            handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
        """
        if self._suppressLegacyTriggers:
            # US-216: the staged-ladder orchestrator owns the shutdown path.
            # Legacy auto-scheduling is disabled to prevent the TD-D race.
            return
        if newSource == PowerSource.BATTERY:
            self._scheduleShutdown()
        elif newSource == PowerSource.EXTERNAL:
            self._cancelScheduledShutdown()

    def onLowBattery(self, percentage: int) -> None:
        """
        Handle low battery condition.

        If battery percentage is at or below the threshold, triggers immediate
        shutdown without waiting for the configured delay.

        Args:
            percentage: Current battery percentage (0-100)

        Example:
            handler.onLowBattery(5)  # Triggers shutdown if threshold is 10%
        """
        if self._suppressLegacyTriggers:
            # US-216: the staged-ladder orchestrator owns the shutdown path
            # (TRIGGER@20%). Legacy 10% trigger is disabled to prevent the
            # TD-D race where it would fire AFTER the new ladder's 20%
            # trigger but still call systemctl poweroff a second time.
            return
        if percentage <= self._lowBatteryThreshold:
            logger.info(
                f"Low battery detected ({percentage}% <= {self._lowBatteryThreshold}% "
                f"threshold) - initiating immediate shutdown"
            )
            self._executeShutdown()

    def _scheduleShutdown(self) -> None:
        """Schedule a shutdown after the configured delay."""
        with self._lock:
            if self._shutdownTimer is not None:
                # Already scheduled
                logger.debug("Shutdown already scheduled, ignoring")
                return

            logger.info(
                f"External power lost - scheduling shutdown in {self._shutdownDelay} seconds"
            )

            self._shutdownScheduledAt = time.time()
            self._shutdownTimer = threading.Timer(
                self._shutdownDelay,
                self._executeShutdown
            )
            self._shutdownTimer.daemon = True
            self._shutdownTimer.start()

    def _cancelScheduledShutdown(self) -> None:
        """Cancel any pending scheduled shutdown."""
        with self._lock:
            if self._shutdownTimer is None:
                # Nothing to cancel
                return

            logger.info("External power restored - cancelling scheduled shutdown")

            self._shutdownTimer.cancel()
            self._shutdownTimer = None
            self._shutdownScheduledAt = None

    def _executeShutdown(self) -> None:
        """Execute the system shutdown.

        Emits :data:`SHUTDOWN_SUCCESS_MARKER` after subprocess returncode==0
        so :mod:`src.pi.diagnostics.boot_reason` can recognize the prior
        boot as cleanly shut down (US-342 honest-canary contract). On
        non-zero returncode or subprocess failure, logs at ERROR and
        raises :class:`ShutdownHandlerError` -- the V0.27.11 fix for the
        I-036 silent-failure anti-pattern that masked the PolicyKit
        denial for 11 days.

        Raises:
            ShutdownHandlerError: ``systemctl poweroff`` returned non-zero
                (auth fail / systemd refused) or the subprocess timed out
                / otherwise failed.
        """
        with self._lock:
            # Clear timer state
            self._shutdownTimer = None
            self._shutdownScheduledAt = None

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"Initiating system shutdown at {timestamp}")

        # T9: record that poweroff was attempted BEFORE the subprocess call,
        # so a hang/exception still leaves the POWEROFF_INVOKED breadcrumb.
        self._markBootProgress(_BpStage.POWEROFF_INVOKED, None)

        try:
            result = subprocess.run(
                ['systemctl', 'poweroff'],
                capture_output=True,
                text=True,
                timeout=self._poweroffTimeoutSeconds
            )
        except subprocess.TimeoutExpired as exc:
            logger.error(
                "Shutdown command TIMED OUT -- Pi will continue running on "
                "residual battery; hard-crash imminent at buck-dropout floor. "
                "Investigate systemd / journald responsiveness."
            )
            raise ShutdownHandlerError("systemctl poweroff timed out") from exc
        except Exception as exc:
            logger.error(
                "Failed to execute shutdown subprocess: %s. Pi will continue "
                "running on residual battery; hard-crash imminent at "
                "buck-dropout floor.",
                exc,
            )
            raise ShutdownHandlerError(
                f"systemctl poweroff subprocess failed: {exc}"
            ) from exc

        if result.returncode == 0:
            # T9: poweroff accepted -- the only path that climbs to
            # POWEROFF_RC0. Absence of this rung at next boot is the
            # signal that poweroff was invoked but never accepted.
            self._markBootProgress(_BpStage.POWEROFF_RC0, None)
            # I-037 fix: emit the success marker the boot_reason canary
            # grep probe is repointed at.  WARNING level (not INFO) so the
            # marker survives the typical pre-shutdown journald rate-limit
            # squeeze in the same band as the intent marker.
            logger.warning(SHUTDOWN_SUCCESS_MARKER)
            return

        # I-036 fix: non-zero returncode is no longer silently swallowed.
        # Pre-V0.27.11 this was a logger.warning() and the function returned
        # normally -- the Pi kept running until buck-dropout hard-crash.
        logger.error(
            "Shutdown FAILED code=%d stderr=%s -- Pi hard-crash imminent. "
            "Check polkit rule at /etc/polkit-1/rules.d/50-eclipse-obd-poweroff.rules "
            "and that eclipse-obd.service runs as the user the rule grants.",
            result.returncode,
            result.stderr.strip(),
        )
        raise ShutdownHandlerError(
            f"systemctl poweroff returned {result.returncode}: "
            f"{result.stderr.strip()}"
        )

    def _markBootProgress(self, stage: "_BpStage", vcell: float | None) -> None:
        """Best-effort boot-progress mark. A breadcrumb failure must NEVER
        prevent the poweroff attempt or the raise-on-failure path.

        Args:
            stage: The :class:`boot_progress.Stage` rung to record.
            vcell: Current battery cell voltage, or ``None``.
        """
        try:
            self._bootProgressWriter(stage, vcell)
        except Exception as e:  # noqa: BLE001 -- shutdown path must not be blocked
            logger.error("ShutdownHandler: boot_progress mark failed: %s", e)

    def registerWithUpsMonitor(self, upsMonitor: UpsMonitor) -> None:
        """
        Register this handler with a UpsMonitor.

        Sets the power source change callback on the UpsMonitor to this
        handler's onPowerSourceChange method.

        Args:
            upsMonitor: UpsMonitor instance to register with

        Example:
            handler.registerWithUpsMonitor(monitor)
        """
        upsMonitor.onPowerSourceChange = self.onPowerSourceChange
        logger.debug("Registered with UpsMonitor")

    def unregisterFromUpsMonitor(self, upsMonitor: UpsMonitor) -> None:
        """
        Unregister this handler from a UpsMonitor.

        Clears the power source change callback on the UpsMonitor.

        Args:
            upsMonitor: UpsMonitor instance to unregister from

        Example:
            handler.unregisterFromUpsMonitor(monitor)
        """
        upsMonitor.onPowerSourceChange = None
        logger.debug("Unregistered from UpsMonitor")

    def cancelShutdown(self) -> bool:
        """
        Explicitly cancel any pending shutdown.

        Returns:
            True if a shutdown was cancelled, False if none was pending

        Example:
            if handler.cancelShutdown():
                print("Shutdown cancelled")
        """
        with self._lock:
            if self._shutdownTimer is None:
                return False

            logger.info("Shutdown explicitly cancelled")

            self._shutdownTimer.cancel()
            self._shutdownTimer = None
            self._shutdownScheduledAt = None
            return True

    @property
    def shutdownDelay(self) -> int:
        """Get the shutdown delay in seconds."""
        return self._shutdownDelay

    @shutdownDelay.setter
    def shutdownDelay(self, value: int) -> None:
        """
        Set the shutdown delay in seconds.

        Args:
            value: Delay in seconds (must be positive)

        Raises:
            ValueError: If value is not positive
        """
        if value <= 0:
            raise ValueError("Shutdown delay must be positive")
        self._shutdownDelay = value

    @property
    def lowBatteryThreshold(self) -> int:
        """Get the low battery threshold percentage."""
        return self._lowBatteryThreshold

    @lowBatteryThreshold.setter
    def lowBatteryThreshold(self, value: int) -> None:
        """
        Set the low battery threshold percentage.

        Args:
            value: Threshold percentage (0-100)

        Raises:
            ValueError: If value is not in valid range
        """
        if value < 0 or value > 100:
            raise ValueError("Low battery threshold must be between 0 and 100")
        self._lowBatteryThreshold = value

    @property
    def suppressLegacyTriggers(self) -> bool:
        """Whether the US-216 legacy-suppression mode is active."""
        return self._suppressLegacyTriggers

    @property
    def isShutdownPending(self) -> bool:
        """Check if a shutdown is currently scheduled."""
        with self._lock:
            return self._shutdownTimer is not None

    @property
    def timeUntilShutdown(self) -> float | None:
        """
        Get time remaining until shutdown.

        Returns:
            Seconds until shutdown, or None if no shutdown is pending
        """
        with self._lock:
            if self._shutdownScheduledAt is None:
                return None

            elapsed = time.time() - self._shutdownScheduledAt
            remaining = self._shutdownDelay - elapsed
            return max(0.0, remaining)

    def close(self) -> None:
        """
        Close the handler and cancel any pending shutdown.

        Safe to call multiple times.
        """
        self.cancelShutdown()
        logger.debug("ShutdownHandler closed")

    def __enter__(self) -> 'ShutdownHandler':
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close the handler."""
        self.close()

    def __del__(self) -> None:
        """Destructor - ensure resources are released."""
        # Check if _lock exists to handle partially initialized objects
        if hasattr(self, '_lock'):
            self.close()
