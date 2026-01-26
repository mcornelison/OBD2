################################################################################
# File Name: config_validator.py
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
    from common.config_validator import ConfigValidator

    validator = ConfigValidator()
    config = validator.validate(rawConfig)
"""

from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, message: str, missingFields: Optional[List[str]] = None):
        super().__init__(message)
        self.missingFields = missingFields or []


# Define required configuration keys (customize for your project)
REQUIRED_KEYS: List[str] = [
    # 'application.name',
    # 'database.server',
    # 'database.database',
]

# Define default values for optional settings
DEFAULTS: Dict[str, Any] = {
    'application.name': 'MyApplication',
    'application.version': '1.0.0',
    'logging.level': 'INFO',
    'logging.format': '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    'retry.maxRetries': 3,
    'retry.backoffMultiplier': 2.0,
    'retry.initialDelaySeconds': 1,
    # Hardware configuration (Raspberry Pi)
    'hardware.enabled': True,
    'hardware.i2c.bus': 1,
    'hardware.i2c.upsAddress': 0x36,
    'hardware.gpio.shutdownButton': 17,
    'hardware.gpio.statusLed': 27,
    'hardware.ups.pollInterval': 5,
    'hardware.ups.shutdownDelay': 30,
    'hardware.ups.lowBatteryThreshold': 10,
    'hardware.display.enabled': True,
    'hardware.display.refreshRate': 2,
    'hardware.telemetry.logInterval': 10,
    'hardware.telemetry.logPath': '/var/log/carpi/telemetry.log',
    'hardware.telemetry.maxBytes': 104857600,
    'hardware.telemetry.backupCount': 7,
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
        requiredKeys: Optional[List[str]] = None,
        defaults: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the validator.

        Args:
            requiredKeys: List of required keys in dot notation (e.g., 'database.server')
            defaults: Dictionary of default values in dot notation
        """
        self.requiredKeys = requiredKeys or REQUIRED_KEYS
        self.defaults = defaults or DEFAULTS

    def validate(self, config: Dict[str, Any]) -> Dict[str, Any]:
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

        logger.info("Configuration validated successfully")
        return config

    def _validateRequired(self, config: Dict[str, Any]) -> List[str]:
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

    def _applyDefaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
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

    def _getNestedValue(self, config: Dict[str, Any], key: str) -> Any:
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

    def _setNestedValue(self, config: Dict[str, Any], key: str, value: Any) -> None:
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
        config: Dict[str, Any],
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


def validateConfig(config: Dict[str, Any]) -> Dict[str, Any]:
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
