################################################################################
# File Name: validator.py
# Purpose/Description: Configuration validation with required fields and defaults
# Author: Michael Cornelison
# Creation Date: 2026-01-21
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-21    | M. Cornelison | Initial implementation
# ================================================================================
################################################################################

"""
Configuration validation module.

Provides validation of configuration files with:
- Required field checking
- Default value application
- Nested configuration support
- Clear error messages for missing/invalid fields

Usage:
    from common.config.validator import ConfigValidator

    validator = ConfigValidator()
    config = validator.validate(rawConfig)
"""

import ipaddress
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, message: str, missingFields: list[str] | None = None):
        super().__init__(message)
        self.missingFields = missingFields or []


# Top-level required keys for the tier-aware config.json shape.
# protocolVersion/schemaVersion gate Pi↔server handshake; deviceId identifies
# the Pi host. pi: and server: sections are checked structurally in validate().
REQUIRED_KEYS: list[str] = [
    'protocolVersion',
    'schemaVersion',
    'deviceId',
]

# Top-level sections that must exist as dicts on a valid config.json.
REQUIRED_SECTIONS: tuple[str, ...] = ('pi', 'server')

# Define default values for optional settings. Paths use the tier-aware
# nested shape (pi.*, server.*) introduced in sweep 4. Legacy leaf paths
# (hardware.*, backup.*, retry.*) predate the tier split and remain as
# template defaults for optional sections not yet tied to a tier.
DEFAULTS: dict[str, Any] = {
    'pi.application.name': 'MyApplication',
    'pi.application.version': '1.0.0',
    'logging.level': 'INFO',
    'logging.format': '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    'retry.maxRetries': 3,
    'retry.backoffMultiplier': 2.0,
    'retry.initialDelaySeconds': 1,
    # Database configuration
    'database.retentionDays': 365,
    # Hardware configuration (Raspberry Pi)
    'hardware.enabled': True,
    'hardware.i2c.bus': 1,
    'hardware.i2c.upsAddress': 0x36,
    'hardware.gpio.shutdownButton': 17,
    'hardware.gpio.statusLed': 27,
    'hardware.ups.pollInterval': 5,
    'hardware.ups.shutdownDelay': 30,
    'hardware.ups.lowBatteryThreshold': 10,
    # Pi-tier UpsMonitor power-source detection (US-184):
    # VCELL-trend + CRATE heuristic replaces the broken EXT5V signal.
    'pi.hardware.upsMonitor.historyWindowSeconds': 60,
    'pi.hardware.upsMonitor.vcellSlopeThresholdVoltsPerMinute': -0.02,
    'pi.hardware.upsMonitor.crateThresholdPercentPerHour': -0.05,
    # US-216 staged-shutdown ladder (PowerDownOrchestrator). When enabled,
    # the new ladder owns the shutdown path (WARNING@30% / IMMINENT@25% /
    # TRIGGER@20% + %s hysteresis band), and the legacy ShutdownHandler
    # 30s-after-BATTERY timer + 10% low-battery trigger are suppressed.
    'pi.power.shutdownThresholds.enabled': True,
    'pi.power.shutdownThresholds.warningSoc': 30,
    'pi.power.shutdownThresholds.imminentSoc': 25,
    'pi.power.shutdownThresholds.triggerSoc': 20,
    'pi.power.shutdownThresholds.hysteresisSoc': 5,
    # Pi-tier companion-service (Chi-Srv-01 reach) — US-151.
    # Consumed by src.pi.sync.SyncClient (US-149) to authenticate + reach
    # the server /api/v1/sync endpoint.  API key resolved from the env var
    # named by `apiKeyEnv` via secrets_loader.
    'pi.companionService.enabled': True,
    'pi.companionService.baseUrl': 'http://10.27.27.10:8000',  # b044-exempt: DEFAULTS registry mirrors config.json
    'pi.companionService.apiKeyEnv': 'COMPANION_API_KEY',
    'pi.companionService.syncTimeoutSeconds': 30,
    'pi.companionService.batchSize': 500,
    'pi.companionService.retryMaxAttempts': 3,
    'pi.companionService.retryBackoffSeconds': [1, 2, 4, 8, 16],
    # Pi-tier home-network detection (US-188, B-043 component 1).  Consumed
    # by src.pi.network.HomeNetworkDetector to decide at shutdown time
    # whether the Pi should attempt a sync push before powering off.
    'pi.homeNetwork.ssid': 'DeathStarWiFi',
    'pi.homeNetwork.subnet': '10.27.27.0/24',  # b044-exempt: DEFAULTS registry mirrors config.json
    'pi.homeNetwork.pingTimeoutSeconds': 3,
    'pi.homeNetwork.serverPingPath': '/api/v1/ping',
    'hardware.display.enabled': True,
    'hardware.display.refreshRate': 2,
    'hardware.telemetry.logInterval': 10,
    'hardware.telemetry.logPath': '/var/log/carpi/telemetry.log',
    'hardware.telemetry.maxBytes': 104857600,
    'hardware.telemetry.backupCount': 7,
    # Backup configuration (Google Drive via rclone)
    'backup.enabled': False,
    'backup.provider': 'google_drive',
    'backup.folderPath': 'OBD2_Backups',
    'backup.scheduleTime': '03:00',
    'backup.maxBackups': 30,
    'backup.compressBackups': True,
    'backup.catchupDays': 2,
}


class ConfigValidator:
    """
    Validates configuration dictionaries.

    Provides methods to:
    - Check for required fields
    - Apply default values
    - Validate field types
    - Return fully validated configuration

    Attributes:
        requiredKeys: List of required configuration keys (dot notation)
        defaults: Dictionary of default values for optional fields
    """

    def __init__(
        self,
        requiredKeys: list[str] | None = None,
        defaults: dict[str, Any] | None = None
    ):
        """
        Initialize the validator.

        Args:
            requiredKeys: List of required keys in dot notation (e.g., 'database.server')
            defaults: Dictionary of default values in dot notation
        """
        self.requiredKeys = requiredKeys or REQUIRED_KEYS
        self.defaults = defaults or DEFAULTS

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Validate and enhance configuration.

        Performs:
        1. Required field validation
        2. Default value application
        3. Returns validated configuration

        Args:
            config: Raw configuration dictionary

        Returns:
            Validated configuration with defaults applied

        Raises:
            ConfigValidationError: If required fields are missing
        """
        # Top-level shape sanity check. Fails loud and early on a flat-shape
        # config (e.g., a test fixture that forgot to migrate to the
        # tier-aware layout) instead of leaving callers to KeyError later.
        missingSections = [s for s in REQUIRED_SECTIONS if not isinstance(config.get(s), dict)]
        if missingSections:
            raise ConfigValidationError(
                f"Missing required top-level section(s): {', '.join(missingSections)}",
                missingFields=missingSections,
            )

        # Check required fields
        missingFields = self._validateRequired(config)
        if missingFields:
            fieldList = ', '.join(missingFields)
            raise ConfigValidationError(
                f"Missing required configuration fields: {fieldList}",
                missingFields=missingFields
            )

        # Apply defaults
        config = self._applyDefaults(config)

        # Post-default semantic validation of tier-specific sections that
        # carry numeric ranges / shape constraints beyond "key present".
        self._validateCompanionService(config)
        self._validateHomeNetwork(config)

        logger.info("Configuration validated successfully")
        return config

    def _validateCompanionService(self, config: dict[str, Any]) -> None:
        """
        Validate pi.companionService shape + numeric ranges (US-151).

        Called after defaults are applied, so every key is guaranteed to
        be populated when the section itself is present.  Any malformed
        value (non-positive timeout, batchSize < 1, non-list backoff,
        negative retry count) raises ConfigValidationError so downstream
        consumers (US-149 SyncClient) never see a corrupt surface.

        Args:
            config: Validated configuration (post-default-application)

        Raises:
            ConfigValidationError: If any pi.companionService value is
                outside its allowed range / type.
        """
        section = self._getNestedValue(config, 'pi.companionService')
        if not isinstance(section, dict):
            return

        syncTimeout = section.get('syncTimeoutSeconds')
        # bool is a subclass of int — reject booleans explicitly so a stray
        # "true"/"false" in JSON can't masquerade as 1/0 seconds.
        if syncTimeout is not None and (
            isinstance(syncTimeout, bool)
            or not isinstance(syncTimeout, (int, float))
            or syncTimeout <= 0
        ):
            raise ConfigValidationError(
                f"pi.companionService.syncTimeoutSeconds must be a positive "
                f"number (got {syncTimeout!r})",
                missingFields=['pi.companionService.syncTimeoutSeconds'],
            )

        batchSize = section.get('batchSize')
        if batchSize is not None and (
            isinstance(batchSize, bool)
            or not isinstance(batchSize, int)
            or batchSize < 1
        ):
            raise ConfigValidationError(
                f"pi.companionService.batchSize must be an integer >= 1 "
                f"(got {batchSize!r})",
                missingFields=['pi.companionService.batchSize'],
            )

        retryMax = section.get('retryMaxAttempts')
        if retryMax is not None and (
            isinstance(retryMax, bool)
            or not isinstance(retryMax, int)
            or retryMax < 0
        ):
            raise ConfigValidationError(
                f"pi.companionService.retryMaxAttempts must be an integer "
                f">= 0 (got {retryMax!r})",
                missingFields=['pi.companionService.retryMaxAttempts'],
            )

        backoff = section.get('retryBackoffSeconds')
        if backoff is not None and not isinstance(backoff, list):
            raise ConfigValidationError(
                f"pi.companionService.retryBackoffSeconds must be a list "
                f"(got {type(backoff).__name__})",
                missingFields=['pi.companionService.retryBackoffSeconds'],
            )

    def _validateHomeNetwork(self, config: dict[str, Any]) -> None:
        """Validate pi.homeNetwork shape + CIDR + numeric ranges (US-188).

        Called after defaults so every key is populated when the section
        exists.  Catches a malformed SSID, invalid CIDR, non-positive
        timeout, or empty ping path at config-load time rather than at
        shutdown when the orchestrator needs the signal.

        Raises:
            ConfigValidationError: If any pi.homeNetwork value is
                outside its allowed range / type.
        """
        section = self._getNestedValue(config, 'pi.homeNetwork')
        if not isinstance(section, dict):
            return

        ssid = section.get('ssid')
        if ssid is not None and (not isinstance(ssid, str) or not ssid.strip()):
            raise ConfigValidationError(
                f"pi.homeNetwork.ssid must be a non-empty string (got {ssid!r})",
                missingFields=['pi.homeNetwork.ssid'],
            )

        subnet = section.get('subnet')
        if subnet is not None:
            if not isinstance(subnet, str):
                raise ConfigValidationError(
                    f"pi.homeNetwork.subnet must be a CIDR string "
                    f"(got {type(subnet).__name__})",
                    missingFields=['pi.homeNetwork.subnet'],
                )
            try:
                ipaddress.ip_network(subnet, strict=False)
            except ValueError as exc:
                raise ConfigValidationError(
                    f"pi.homeNetwork.subnet is not a valid CIDR "
                    f"(got {subnet!r}): {exc}",
                    missingFields=['pi.homeNetwork.subnet'],
                ) from exc

        pingTimeout = section.get('pingTimeoutSeconds')
        # bool first -- isinstance(True, int) is True in Python.
        if pingTimeout is not None and (
            isinstance(pingTimeout, bool)
            or not isinstance(pingTimeout, (int, float))
            or pingTimeout <= 0
        ):
            raise ConfigValidationError(
                f"pi.homeNetwork.pingTimeoutSeconds must be a positive "
                f"number (got {pingTimeout!r})",
                missingFields=['pi.homeNetwork.pingTimeoutSeconds'],
            )

        pingPath = section.get('serverPingPath')
        if pingPath is not None and (
            not isinstance(pingPath, str) or not pingPath.startswith('/')
        ):
            raise ConfigValidationError(
                f"pi.homeNetwork.serverPingPath must be an absolute URL path "
                f"starting with '/' (got {pingPath!r})",
                missingFields=['pi.homeNetwork.serverPingPath'],
            )

    def _validateRequired(self, config: dict[str, Any]) -> list[str]:
        """
        Check for required configuration fields.

        Args:
            config: Configuration dictionary to check

        Returns:
            List of missing field names (empty if all present)
        """
        missingFields = []

        for key in self.requiredKeys:
            if not self._getNestedValue(config, key):
                missingFields.append(key)

        return missingFields

    def _applyDefaults(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Apply default values for missing optional fields.

        Args:
            config: Configuration dictionary

        Returns:
            Configuration with defaults applied
        """
        for key, defaultValue in self.defaults.items():
            if self._getNestedValue(config, key) is None:
                self._setNestedValue(config, key, defaultValue)
                logger.debug(f"Applied default for {key}: {defaultValue}")

        return config

    def _getNestedValue(self, config: dict[str, Any], key: str) -> Any:
        """
        Get a value from nested dictionary using dot notation.

        Args:
            config: Configuration dictionary
            key: Dot-notation key (e.g., 'database.server')

        Returns:
            Value if found, None otherwise
        """
        keys = key.split('.')
        value = config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return None

        return value

    def _setNestedValue(self, config: dict[str, Any], key: str, value: Any) -> None:
        """
        Set a value in nested dictionary using dot notation.

        Args:
            config: Configuration dictionary to modify
            key: Dot-notation key (e.g., 'database.server')
            value: Value to set
        """
        keys = key.split('.')
        current = config

        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        current[keys[-1]] = value

    def validateField(
        self,
        config: dict[str, Any],
        key: str,
        expectedType: type,
        allowNone: bool = False
    ) -> bool:
        """
        Validate a specific field's type.

        Args:
            config: Configuration dictionary
            key: Dot-notation key to validate
            expectedType: Expected Python type
            allowNone: Whether None is acceptable

        Returns:
            True if valid, False otherwise
        """
        value = self._getNestedValue(config, key)

        if value is None:
            return allowNone

        return isinstance(value, expectedType)


def validateConfig(config: dict[str, Any]) -> dict[str, Any]:
    """
    Convenience function to validate configuration.

    Args:
        config: Raw configuration dictionary

    Returns:
        Validated configuration

    Raises:
        ConfigValidationError: If validation fails
    """
    validator = ConfigValidator()
    return validator.validate(config)
