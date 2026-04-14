################################################################################
# File Name: system_detail.py
# Purpose/Description: System detail page state and info building logic
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-126
# ================================================================================
################################################################################
"""
System detail page for the 3.5" touchscreen (480x320).

Shows Pi health, connectivity, and drive stats:
- Pi battery level (from UPS when available, placeholder when not)
- WiFi status (connected/disconnected, SSID if connected)
- Last sync time (to Chi-Srv-01)
- OBD connection status (connected/disconnected/simulated)
- Drive duration (current drive elapsed time)

Always available — not Phase 2 dependent. Gracefully degrades when
hardware (UPS, WiFi) is not present by showing placeholder values.
"""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

BATTERY_PLACEHOLDER: str = "--"


# ================================================================================
# Enums
# ================================================================================


class ConnectionStatus(Enum):
    """
    Connection status for OBD adapter or WiFi.

    CONNECTED: Hardware present and communicating
    DISCONNECTED: Hardware not available or not responding
    SIMULATED: Running in simulation mode (no real hardware)
    """

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    SIMULATED = "simulated"

    @property
    def displayLabel(self) -> str:
        """Human-readable label for display."""
        return {
            "connected": "Connected",
            "disconnected": "Disconnected",
            "simulated": "Simulated",
        }[self.value]


class SyncStatus(Enum):
    """
    Sync status for server synchronization.

    NEVER: No sync has ever occurred
    PENDING: Sync configured but not yet started
    IN_PROGRESS: Sync currently running
    COMPLETE: Last sync completed successfully
    """

    NEVER = "never"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


# ================================================================================
# Data Classes
# ================================================================================


@dataclass
class BatteryInfo:
    """
    Battery information from the UPS module.

    Attributes:
        available: Whether UPS hardware is present
        levelPercent: Battery level 0-100, or -1 if unknown
        estimatedHours: Estimated remaining hours, or -1 if unknown
        displayText: Formatted string for screen rendering
    """

    available: bool
    levelPercent: float
    estimatedHours: float
    displayText: str


@dataclass
class WifiInfo:
    """
    WiFi connection information.

    Attributes:
        status: Connection state
        ssid: Network name if connected, empty string otherwise
        displayText: Formatted string for screen rendering
    """

    status: ConnectionStatus
    ssid: str
    displayText: str


@dataclass
class SyncInfo:
    """
    Server sync status information.

    Attributes:
        status: Current sync state
        lastSyncTime: ISO timestamp of last sync, or None if never synced
        progressPercent: Current sync progress 0-100 (only for IN_PROGRESS)
        displayText: Formatted string for screen rendering
    """

    status: SyncStatus
    lastSyncTime: str | None
    progressPercent: float
    displayText: str


@dataclass
class SystemDetailState:
    """
    Display state for the system detail page.

    Attributes:
        batteryInfo: UPS battery information
        wifiInfo: WiFi connection information
        syncInfo: Server sync status
        obdStatus: OBD adapter connection status
        driveDurationSeconds: Current drive elapsed time in seconds
        formattedDriveDuration: Human-readable drive duration string
    """

    batteryInfo: BatteryInfo
    wifiInfo: WifiInfo
    syncInfo: SyncInfo
    obdStatus: ConnectionStatus
    driveDurationSeconds: float
    formattedDriveDuration: str


# ================================================================================
# Core Functions
# ================================================================================


def buildBatteryInfo(
    upsAvailable: bool,
    levelPercent: float | None = None,
    estimatedHours: float | None = None,
) -> BatteryInfo:
    """
    Build battery info from UPS data with graceful fallback.

    Args:
        upsAvailable: Whether UPS hardware is present
        levelPercent: Battery level 0-100, or None if not available
        estimatedHours: Estimated remaining hours, or None if not available

    Returns:
        BatteryInfo with formatted display text or placeholder
    """
    if not upsAvailable or levelPercent is None or estimatedHours is None:
        return BatteryInfo(
            available=upsAvailable,
            levelPercent=-1.0,
            estimatedHours=-1.0,
            displayText=BATTERY_PLACEHOLDER,
        )

    displayText = f"{levelPercent:g}% (~{estimatedHours} hrs)"
    return BatteryInfo(
        available=True,
        levelPercent=levelPercent,
        estimatedHours=estimatedHours,
        displayText=displayText,
    )


def buildWifiInfo(
    connected: bool,
    ssid: str | None = None,
) -> WifiInfo:
    """
    Build WiFi info from connection state.

    Args:
        connected: Whether WiFi is connected
        ssid: Network SSID if connected, or None

    Returns:
        WifiInfo with formatted display text
    """
    if not connected:
        return WifiInfo(
            status=ConnectionStatus.DISCONNECTED,
            ssid="",
            displayText="Disconnected",
        )

    cleanSsid = ssid if ssid else ""
    if cleanSsid:
        displayText = f"Connected ({cleanSsid})"
    else:
        displayText = "Connected"

    return WifiInfo(
        status=ConnectionStatus.CONNECTED,
        ssid=cleanSsid,
        displayText=displayText,
    )


def buildSyncInfo(
    lastSyncTimestamp: str | None = None,
    syncInProgress: bool = False,
    progressPercent: float = 0.0,
) -> SyncInfo:
    """
    Build sync info from server synchronization state.

    Args:
        lastSyncTimestamp: ISO timestamp of last completed sync, or None
        syncInProgress: Whether a sync is currently running
        progressPercent: Current sync progress 0-100

    Returns:
        SyncInfo with formatted display text
    """
    if syncInProgress:
        return SyncInfo(
            status=SyncStatus.IN_PROGRESS,
            lastSyncTime=lastSyncTimestamp,
            progressPercent=progressPercent,
            displayText=f"Syncing to server... {progressPercent:g}%",
        )

    if lastSyncTimestamp is None:
        return SyncInfo(
            status=SyncStatus.NEVER,
            lastSyncTime=None,
            progressPercent=0.0,
            displayText="Never",
        )

    return SyncInfo(
        status=SyncStatus.COMPLETE,
        lastSyncTime=lastSyncTimestamp,
        progressPercent=0.0,
        displayText="Sync complete",
    )


def formatDriveDuration(seconds: float) -> str:
    """
    Format drive duration as a human-readable string.

    Args:
        seconds: Drive duration in seconds

    Returns:
        Formatted string like '1h 23m', '45m', or '0m'
    """
    if seconds <= 0:
        return "0m"

    totalMinutes = int(seconds) // 60
    hours = totalMinutes // 60
    minutes = totalMinutes % 60

    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def buildSystemDetailState(
    upsAvailable: bool,
    batteryLevelPercent: float | None,
    batteryEstimatedHours: float | None,
    wifiConnected: bool,
    wifiSsid: str | None,
    lastSyncTimestamp: str | None,
    syncInProgress: bool,
    syncProgressPercent: float,
    obdConnected: bool,
    obdSimulated: bool,
    driveDurationSeconds: float,
) -> SystemDetailState:
    """
    Build the complete system detail page state.

    Aggregates information from multiple subsystems into a single display
    state. Each subsystem degrades gracefully when hardware is absent.

    Args:
        upsAvailable: Whether UPS hardware is present
        batteryLevelPercent: Battery level 0-100, or None
        batteryEstimatedHours: Estimated remaining hours, or None
        wifiConnected: Whether WiFi is connected
        wifiSsid: WiFi SSID if connected, or None
        lastSyncTimestamp: ISO timestamp of last sync, or None
        syncInProgress: Whether sync is currently running
        syncProgressPercent: Sync progress 0-100
        obdConnected: Whether OBD adapter is connected
        obdSimulated: Whether running in simulation mode
        driveDurationSeconds: Current drive elapsed seconds

    Returns:
        SystemDetailState with all subsystem info populated
    """
    batteryInfo = buildBatteryInfo(upsAvailable, batteryLevelPercent, batteryEstimatedHours)
    wifiInfo = buildWifiInfo(wifiConnected, wifiSsid)
    syncInfo = buildSyncInfo(lastSyncTimestamp, syncInProgress, syncProgressPercent)

    if obdConnected:
        obdStatus = ConnectionStatus.CONNECTED
    elif obdSimulated:
        obdStatus = ConnectionStatus.SIMULATED
    else:
        obdStatus = ConnectionStatus.DISCONNECTED

    return SystemDetailState(
        batteryInfo=batteryInfo,
        wifiInfo=wifiInfo,
        syncInfo=syncInfo,
        obdStatus=obdStatus,
        driveDurationSeconds=driveDurationSeconds,
        formattedDriveDuration=formatDriveDuration(driveDurationSeconds),
    )
