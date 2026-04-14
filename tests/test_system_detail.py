################################################################################
# File Name: test_system_detail.py
# Purpose/Description: Tests for System Detail Page (US-126)
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
Tests for the System Detail Page (US-126).

Validates:
- Battery info display with UPS present and absent
- WiFi status with connected/disconnected/SSID
- Sync status with various states (never, pending, in progress, complete)
- OBD connection status (connected, disconnected, simulated)
- Drive duration formatting
- Graceful degradation when hardware not present
- SystemDetailState construction from various input combinations
"""

from pi.display.screens.system_detail import (
    BATTERY_PLACEHOLDER,
    BatteryInfo,
    ConnectionStatus,
    SyncInfo,
    SyncStatus,
    SystemDetailState,
    WifiInfo,
    buildBatteryInfo,
    buildSyncInfo,
    buildSystemDetailState,
    buildWifiInfo,
    formatDriveDuration,
)

# ================================================================================
# ConnectionStatus Enum Tests
# ================================================================================


class TestConnectionStatus:
    """Tests for ConnectionStatus enum values."""

    def test_connectionStatus_hasThreeValues(self):
        """
        Given: ConnectionStatus enum
        When: checking values
        Then: contains CONNECTED, DISCONNECTED, SIMULATED
        """
        assert ConnectionStatus.CONNECTED.value == "connected"
        assert ConnectionStatus.DISCONNECTED.value == "disconnected"
        assert ConnectionStatus.SIMULATED.value == "simulated"

    def test_connectionStatus_displayLabel(self):
        """
        Given: each ConnectionStatus value
        When: getting display label
        Then: returns human-readable string
        """
        assert ConnectionStatus.CONNECTED.displayLabel == "Connected"
        assert ConnectionStatus.DISCONNECTED.displayLabel == "Disconnected"
        assert ConnectionStatus.SIMULATED.displayLabel == "Simulated"


# ================================================================================
# SyncStatus Enum Tests
# ================================================================================


class TestSyncStatus:
    """Tests for SyncStatus enum values."""

    def test_syncStatus_hasFourValues(self):
        """
        Given: SyncStatus enum
        When: checking values
        Then: contains NEVER, PENDING, IN_PROGRESS, COMPLETE
        """
        assert SyncStatus.NEVER.value == "never"
        assert SyncStatus.PENDING.value == "pending"
        assert SyncStatus.IN_PROGRESS.value == "in_progress"
        assert SyncStatus.COMPLETE.value == "complete"


# ================================================================================
# buildBatteryInfo Tests
# ================================================================================


class TestBuildBatteryInfo:
    """Tests for battery info construction with UPS available/unavailable."""

    def test_buildBatteryInfo_upsAvailable_showsLevel(self):
        """
        Given: UPS is available with 78% battery and 1.5 hours remaining
        When: building battery info
        Then: shows formatted battery level and time
        """
        info = buildBatteryInfo(
            upsAvailable=True, levelPercent=78.0, estimatedHours=1.5
        )

        assert info.available is True
        assert info.levelPercent == 78.0
        assert info.estimatedHours == 1.5
        assert info.displayText == "78% (~1.5 hrs)"

    def test_buildBatteryInfo_upsAvailable_fullBattery(self):
        """
        Given: UPS is available with 100% battery and 3.0 hours remaining
        When: building battery info
        Then: shows 100% level
        """
        info = buildBatteryInfo(
            upsAvailable=True, levelPercent=100.0, estimatedHours=3.0
        )

        assert info.available is True
        assert info.levelPercent == 100.0
        assert info.displayText == "100% (~3.0 hrs)"

    def test_buildBatteryInfo_upsAvailable_lowBattery(self):
        """
        Given: UPS is available with 5% battery and 0.2 hours remaining
        When: building battery info
        Then: shows low battery level
        """
        info = buildBatteryInfo(
            upsAvailable=True, levelPercent=5.0, estimatedHours=0.2
        )

        assert info.available is True
        assert info.levelPercent == 5.0
        assert info.displayText == "5% (~0.2 hrs)"

    def test_buildBatteryInfo_upsNotAvailable_showsPlaceholder(self):
        """
        Given: UPS is not available
        When: building battery info
        Then: shows placeholder text and defaults
        """
        info = buildBatteryInfo(upsAvailable=False)

        assert info.available is False
        assert info.levelPercent == -1.0
        assert info.estimatedHours == -1.0
        assert info.displayText == BATTERY_PLACEHOLDER

    def test_buildBatteryInfo_upsAvailable_noLevelProvided_showsPlaceholder(self):
        """
        Given: UPS is available but level data is None
        When: building battery info
        Then: shows placeholder (data not yet available)
        """
        info = buildBatteryInfo(upsAvailable=True, levelPercent=None, estimatedHours=None)

        assert info.available is True
        assert info.levelPercent == -1.0
        assert info.estimatedHours == -1.0
        assert info.displayText == BATTERY_PLACEHOLDER

    def test_buildBatteryInfo_upsAvailable_zeroBattery(self):
        """
        Given: UPS is available with 0% battery
        When: building battery info
        Then: shows 0% level
        """
        info = buildBatteryInfo(
            upsAvailable=True, levelPercent=0.0, estimatedHours=0.0
        )

        assert info.available is True
        assert info.levelPercent == 0.0
        assert info.displayText == "0% (~0.0 hrs)"


# ================================================================================
# buildWifiInfo Tests
# ================================================================================


class TestBuildWifiInfo:
    """Tests for WiFi info construction with various connection states."""

    def test_buildWifiInfo_connected_showsSsid(self):
        """
        Given: WiFi is connected to DeathStarWiFi
        When: building WiFi info
        Then: shows connected status and SSID
        """
        info = buildWifiInfo(connected=True, ssid="DeathStarWiFi")

        assert info.status == ConnectionStatus.CONNECTED
        assert info.ssid == "DeathStarWiFi"
        assert info.displayText == "Connected (DeathStarWiFi)"

    def test_buildWifiInfo_connected_noSsid_showsConnected(self):
        """
        Given: WiFi is connected but SSID is not available
        When: building WiFi info
        Then: shows connected status without SSID
        """
        info = buildWifiInfo(connected=True, ssid=None)

        assert info.status == ConnectionStatus.CONNECTED
        assert info.ssid == ""
        assert info.displayText == "Connected"

    def test_buildWifiInfo_disconnected_showsDisconnected(self):
        """
        Given: WiFi is not connected
        When: building WiFi info
        Then: shows disconnected status
        """
        info = buildWifiInfo(connected=False)

        assert info.status == ConnectionStatus.DISCONNECTED
        assert info.ssid == ""
        assert info.displayText == "Disconnected"

    def test_buildWifiInfo_disconnected_ssidIgnored(self):
        """
        Given: WiFi is disconnected but SSID string is provided
        When: building WiFi info
        Then: ignores SSID and shows disconnected
        """
        info = buildWifiInfo(connected=False, ssid="SomeNetwork")

        assert info.status == ConnectionStatus.DISCONNECTED
        assert info.ssid == ""
        assert info.displayText == "Disconnected"

    def test_buildWifiInfo_connected_emptySsid_showsConnected(self):
        """
        Given: WiFi is connected but SSID is empty string
        When: building WiFi info
        Then: shows connected without SSID
        """
        info = buildWifiInfo(connected=True, ssid="")

        assert info.status == ConnectionStatus.CONNECTED
        assert info.ssid == ""
        assert info.displayText == "Connected"


# ================================================================================
# buildSyncInfo Tests
# ================================================================================


class TestBuildSyncInfo:
    """Tests for sync info construction with various sync states."""

    def test_buildSyncInfo_neverSynced_showsNever(self):
        """
        Given: No sync has ever occurred (lastSyncTimestamp is None)
        When: building sync info
        Then: shows 'Never' status
        """
        info = buildSyncInfo(lastSyncTimestamp=None)

        assert info.status == SyncStatus.NEVER
        assert info.lastSyncTime is None
        assert info.progressPercent == 0.0
        assert info.displayText == "Never"

    def test_buildSyncInfo_syncComplete_showsTimestamp(self):
        """
        Given: Last sync completed at a known timestamp
        When: building sync info
        Then: shows 'Sync complete' with timestamp
        """
        info = buildSyncInfo(lastSyncTimestamp="2026-04-12T10:30:00")

        assert info.status == SyncStatus.COMPLETE
        assert info.lastSyncTime == "2026-04-12T10:30:00"
        assert info.displayText == "Sync complete"

    def test_buildSyncInfo_syncInProgress_showsProgress(self):
        """
        Given: Sync is currently in progress at 45%
        When: building sync info
        Then: shows progress percentage
        """
        info = buildSyncInfo(
            lastSyncTimestamp="2026-04-12T10:30:00",
            syncInProgress=True,
            progressPercent=45.0,
        )

        assert info.status == SyncStatus.IN_PROGRESS
        assert info.progressPercent == 45.0
        assert info.displayText == "Syncing to server... 45%"

    def test_buildSyncInfo_syncInProgress_zeroPercent(self):
        """
        Given: Sync just started at 0%
        When: building sync info
        Then: shows 0% progress
        """
        info = buildSyncInfo(
            lastSyncTimestamp=None,
            syncInProgress=True,
            progressPercent=0.0,
        )

        assert info.status == SyncStatus.IN_PROGRESS
        assert info.displayText == "Syncing to server... 0%"

    def test_buildSyncInfo_syncInProgress_hundredPercent(self):
        """
        Given: Sync at 100% but still flagged in progress
        When: building sync info
        Then: shows 100% progress
        """
        info = buildSyncInfo(
            lastSyncTimestamp="2026-04-12T10:30:00",
            syncInProgress=True,
            progressPercent=100.0,
        )

        assert info.status == SyncStatus.IN_PROGRESS
        assert info.displayText == "Syncing to server... 100%"

    def test_buildSyncInfo_notConfigured_showsNotConfigured(self):
        """
        Given: Sync is not configured (lastSyncTimestamp is None, not in progress)
        When: building sync info
        Then: shows 'Never' as placeholder
        """
        info = buildSyncInfo(lastSyncTimestamp=None, syncInProgress=False)

        assert info.status == SyncStatus.NEVER
        assert info.displayText == "Never"


# ================================================================================
# formatDriveDuration Tests
# ================================================================================


class TestFormatDriveDuration:
    """Tests for drive duration formatting."""

    def test_formatDriveDuration_zeroSeconds_showsZero(self):
        """
        Given: 0 seconds drive duration
        When: formatting
        Then: shows '0m'
        """
        assert formatDriveDuration(0.0) == "0m"

    def test_formatDriveDuration_underOneMinute_showsSeconds(self):
        """
        Given: 45 seconds drive duration
        When: formatting
        Then: shows '0m' (sub-minute rounds to 0m)
        """
        assert formatDriveDuration(45.0) == "0m"

    def test_formatDriveDuration_exactlyOneMinute(self):
        """
        Given: 60 seconds drive duration
        When: formatting
        Then: shows '1m'
        """
        assert formatDriveDuration(60.0) == "1m"

    def test_formatDriveDuration_minutesOnly(self):
        """
        Given: 23 minutes drive duration
        When: formatting
        Then: shows '23m'
        """
        assert formatDriveDuration(23 * 60.0) == "23m"

    def test_formatDriveDuration_hoursAndMinutes(self):
        """
        Given: 1 hour 23 minutes drive duration
        When: formatting
        Then: shows '1h 23m'
        """
        assert formatDriveDuration(1 * 3600.0 + 23 * 60.0) == "1h 23m"

    def test_formatDriveDuration_exactlyOneHour(self):
        """
        Given: 3600 seconds drive duration
        When: formatting
        Then: shows '1h 0m'
        """
        assert formatDriveDuration(3600.0) == "1h 0m"

    def test_formatDriveDuration_multipleHours(self):
        """
        Given: 5 hours 45 minutes drive duration
        When: formatting
        Then: shows '5h 45m'
        """
        assert formatDriveDuration(5 * 3600.0 + 45 * 60.0) == "5h 45m"

    def test_formatDriveDuration_negativeSeconds_treatedAsZero(self):
        """
        Given: negative seconds (clock anomaly)
        When: formatting
        Then: shows '0m'
        """
        assert formatDriveDuration(-10.0) == "0m"

    def test_formatDriveDuration_fractionalSeconds_truncated(self):
        """
        Given: 90.7 seconds (1m 30.7s)
        When: formatting
        Then: shows '1m' (fractional seconds truncated)
        """
        assert formatDriveDuration(90.7) == "1m"


# ================================================================================
# buildSystemDetailState Tests
# ================================================================================


class TestBuildSystemDetailState:
    """Tests for building complete system detail state."""

    def test_buildSystemDetailState_allConnected(self):
        """
        Given: All systems connected and operational
        When: building system detail state
        Then: shows full information for all fields
        """
        state = buildSystemDetailState(
            upsAvailable=True,
            batteryLevelPercent=78.0,
            batteryEstimatedHours=1.5,
            wifiConnected=True,
            wifiSsid="DeathStarWiFi",
            lastSyncTimestamp="2026-04-12T10:30:00",
            syncInProgress=False,
            syncProgressPercent=0.0,
            obdConnected=True,
            obdSimulated=False,
            driveDurationSeconds=5040.0,
        )

        assert state.batteryInfo.available is True
        assert state.batteryInfo.displayText == "78% (~1.5 hrs)"
        assert state.wifiInfo.status == ConnectionStatus.CONNECTED
        assert state.wifiInfo.displayText == "Connected (DeathStarWiFi)"
        assert state.syncInfo.status == SyncStatus.COMPLETE
        assert state.obdStatus == ConnectionStatus.CONNECTED
        assert state.formattedDriveDuration == "1h 24m"

    def test_buildSystemDetailState_allDisconnected(self):
        """
        Given: Everything disconnected, no UPS
        When: building system detail state
        Then: shows placeholders and disconnected states
        """
        state = buildSystemDetailState(
            upsAvailable=False,
            batteryLevelPercent=None,
            batteryEstimatedHours=None,
            wifiConnected=False,
            wifiSsid=None,
            lastSyncTimestamp=None,
            syncInProgress=False,
            syncProgressPercent=0.0,
            obdConnected=False,
            obdSimulated=False,
            driveDurationSeconds=0.0,
        )

        assert state.batteryInfo.available is False
        assert state.batteryInfo.displayText == BATTERY_PLACEHOLDER
        assert state.wifiInfo.status == ConnectionStatus.DISCONNECTED
        assert state.syncInfo.status == SyncStatus.NEVER
        assert state.obdStatus == ConnectionStatus.DISCONNECTED
        assert state.formattedDriveDuration == "0m"

    def test_buildSystemDetailState_obdSimulated(self):
        """
        Given: OBD is in simulated mode
        When: building system detail state
        Then: shows simulated status
        """
        state = buildSystemDetailState(
            upsAvailable=False,
            batteryLevelPercent=None,
            batteryEstimatedHours=None,
            wifiConnected=True,
            wifiSsid="DeathStarWiFi",
            lastSyncTimestamp=None,
            syncInProgress=False,
            syncProgressPercent=0.0,
            obdConnected=False,
            obdSimulated=True,
            driveDurationSeconds=120.0,
        )

        assert state.obdStatus == ConnectionStatus.SIMULATED
        assert state.formattedDriveDuration == "2m"

    def test_buildSystemDetailState_syncInProgress(self):
        """
        Given: Sync is currently in progress
        When: building system detail state
        Then: shows sync progress
        """
        state = buildSystemDetailState(
            upsAvailable=True,
            batteryLevelPercent=50.0,
            batteryEstimatedHours=1.0,
            wifiConnected=True,
            wifiSsid="DeathStarWiFi",
            lastSyncTimestamp="2026-04-12T09:00:00",
            syncInProgress=True,
            syncProgressPercent=67.0,
            obdConnected=True,
            obdSimulated=False,
            driveDurationSeconds=300.0,
        )

        assert state.syncInfo.status == SyncStatus.IN_PROGRESS
        assert state.syncInfo.displayText == "Syncing to server... 67%"

    def test_buildSystemDetailState_obdConnectedTakesPrecedenceOverSimulated(self):
        """
        Given: Both obdConnected and obdSimulated are True
        When: building system detail state
        Then: connected takes precedence over simulated
        """
        state = buildSystemDetailState(
            upsAvailable=False,
            batteryLevelPercent=None,
            batteryEstimatedHours=None,
            wifiConnected=False,
            wifiSsid=None,
            lastSyncTimestamp=None,
            syncInProgress=False,
            syncProgressPercent=0.0,
            obdConnected=True,
            obdSimulated=True,
            driveDurationSeconds=0.0,
        )

        assert state.obdStatus == ConnectionStatus.CONNECTED


# ================================================================================
# SystemDetailState Property Tests
# ================================================================================


class TestSystemDetailStateProperties:
    """Tests for SystemDetailState computed properties."""

    def test_systemDetailState_formattedDriveDuration_computed(self):
        """
        Given: SystemDetailState with raw seconds
        When: accessing formattedDriveDuration
        Then: returns formatted string
        """
        state = SystemDetailState(
            batteryInfo=buildBatteryInfo(upsAvailable=False),
            wifiInfo=buildWifiInfo(connected=False),
            syncInfo=buildSyncInfo(lastSyncTimestamp=None),
            obdStatus=ConnectionStatus.DISCONNECTED,
            driveDurationSeconds=7260.0,
            formattedDriveDuration=formatDriveDuration(7260.0),
        )

        assert state.formattedDriveDuration == "2h 1m"


# ================================================================================
# Graceful Degradation Tests
# ================================================================================


class TestGracefulDegradation:
    """Tests for graceful handling when hardware is not present."""

    def test_degradation_noUps_showsPlaceholder(self):
        """
        Given: UPS hardware not installed
        When: building system detail state
        Then: battery shows placeholder, all other fields work
        """
        state = buildSystemDetailState(
            upsAvailable=False,
            batteryLevelPercent=None,
            batteryEstimatedHours=None,
            wifiConnected=True,
            wifiSsid="DeathStarWiFi",
            lastSyncTimestamp="2026-04-12T10:30:00",
            syncInProgress=False,
            syncProgressPercent=0.0,
            obdConnected=True,
            obdSimulated=False,
            driveDurationSeconds=600.0,
        )

        assert state.batteryInfo.displayText == BATTERY_PLACEHOLDER
        assert state.wifiInfo.status == ConnectionStatus.CONNECTED
        assert state.obdStatus == ConnectionStatus.CONNECTED

    def test_degradation_noWifi_showsDisconnected(self):
        """
        Given: WiFi hardware present but not connected
        When: building system detail state
        Then: WiFi shows disconnected, all other fields work
        """
        state = buildSystemDetailState(
            upsAvailable=True,
            batteryLevelPercent=90.0,
            batteryEstimatedHours=2.5,
            wifiConnected=False,
            wifiSsid=None,
            lastSyncTimestamp=None,
            syncInProgress=False,
            syncProgressPercent=0.0,
            obdConnected=True,
            obdSimulated=False,
            driveDurationSeconds=300.0,
        )

        assert state.wifiInfo.status == ConnectionStatus.DISCONNECTED
        assert state.batteryInfo.available is True
        assert state.syncInfo.status == SyncStatus.NEVER

    def test_degradation_neverSynced_showsNever(self):
        """
        Given: Sync has never been configured or run
        When: building system detail state
        Then: shows 'Never' for sync status
        """
        state = buildSystemDetailState(
            upsAvailable=False,
            batteryLevelPercent=None,
            batteryEstimatedHours=None,
            wifiConnected=False,
            wifiSsid=None,
            lastSyncTimestamp=None,
            syncInProgress=False,
            syncProgressPercent=0.0,
            obdConnected=False,
            obdSimulated=False,
            driveDurationSeconds=0.0,
        )

        assert state.syncInfo.displayText == "Never"

    def test_degradation_allMissing_stillConstructsState(self):
        """
        Given: All hardware missing, nothing connected
        When: building system detail state
        Then: state is still valid with all placeholder values
        """
        state = buildSystemDetailState(
            upsAvailable=False,
            batteryLevelPercent=None,
            batteryEstimatedHours=None,
            wifiConnected=False,
            wifiSsid=None,
            lastSyncTimestamp=None,
            syncInProgress=False,
            syncProgressPercent=0.0,
            obdConnected=False,
            obdSimulated=False,
            driveDurationSeconds=0.0,
        )

        assert isinstance(state, SystemDetailState)
        assert isinstance(state.batteryInfo, BatteryInfo)
        assert isinstance(state.wifiInfo, WifiInfo)
        assert isinstance(state.syncInfo, SyncInfo)
        assert isinstance(state.obdStatus, ConnectionStatus)

    def test_degradation_obdSimulatedMode_noHardware(self):
        """
        Given: No real hardware but running in simulator mode
        When: building system detail state
        Then: OBD shows simulated, everything else degrades gracefully
        """
        state = buildSystemDetailState(
            upsAvailable=False,
            batteryLevelPercent=None,
            batteryEstimatedHours=None,
            wifiConnected=False,
            wifiSsid=None,
            lastSyncTimestamp=None,
            syncInProgress=False,
            syncProgressPercent=0.0,
            obdConnected=False,
            obdSimulated=True,
            driveDurationSeconds=180.0,
        )

        assert state.obdStatus == ConnectionStatus.SIMULATED
        assert state.batteryInfo.displayText == BATTERY_PLACEHOLDER
        assert state.wifiInfo.displayText == "Disconnected"
        assert state.syncInfo.displayText == "Never"
        assert state.formattedDriveDuration == "3m"
