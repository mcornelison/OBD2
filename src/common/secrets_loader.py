################################################################################
# File Name: secrets_loader.py
# Purpose/Description: Secure loading and resolution of environment variables
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
Secrets management module.

Provides secure loading and resolution of secrets:
- Loads environment variables from .env file
- Resolves ${VAR_NAME} placeholders in configuration
- Supports default values: ${VAR_NAME:default}
- Never logs or exposes secret values

Usage:
    from common.secrets_loader import loadConfigWithSecrets

    config = loadConfigWithSecrets('config.json')
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Pattern to match ${VAR_NAME} or ${VAR_NAME:default}
PLACEHOLDER_PATTERN = re.compile(r'\$\{([^}:]+)(?::([^}]*))?\}')


def loadEnvFile(envPath: Optional[str] = None) -> Dict[str, str]:
    """
    Load environment variables from .env file.

    Args:
        envPath: Path to .env file. Defaults to .env in current directory.

    Returns:
        Dictionary of loaded environment variables

    Note:
        Does not override existing environment variables.
    """
    if envPath is None:
        envPath = '.env'

    loadedVars: Dict[str, str] = {}
    envFile = Path(envPath)

    if not envFile.exists():
        logger.debug(f".env file not found at {envPath}")
        return loadedVars

    try:
        with open(envFile, 'r', encoding='utf-8') as f:
            for lineNum, line in enumerate(f, 1):
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue

                # Parse KEY=VALUE
                if '=' not in line:
                    logger.warning(f"Invalid line {lineNum} in .env: missing '='")
                    continue

                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()

                # Remove surrounding quotes if present
                if value and value[0] in ('"', "'") and value[-1] == value[0]:
                    value = value[1:-1]

                # Only set if not already in environment
                if key not in os.environ:
                    os.environ[key] = value
                    loadedVars[key] = '[LOADED]'  # Don't log actual value

        logger.info(f"Loaded {len(loadedVars)} variables from {envPath}")

    except Exception as e:
        logger.error(f"Error loading .env file: {e}")

    return loadedVars


def resolveSecrets(config: Any) -> Any:
    """
    Recursively resolve ${VAR_NAME} placeholders in configuration.

    Supports:
    - ${VAR_NAME} - resolves to environment variable
    - ${VAR_NAME:default} - uses default if VAR_NAME not set

    Args:
        config: Configuration value (dict, list, str, or other)

    Returns:
        Configuration with placeholders resolved
    """
    if isinstance(config, dict):
        return {key: resolveSecrets(value) for key, value in config.items()}

    elif isinstance(config, list):
        return [resolveSecrets(item) for item in config]

    elif isinstance(config, str):
        return _resolveString(config)

    else:
        return config


def _resolveString(value: str) -> str:
    """
    Resolve placeholders in a string value.

    Args:
        value: String potentially containing ${VAR} placeholders

    Returns:
        String with placeholders resolved
    """
    def replacer(match: re.Match) -> str:
        varName = match.group(1)
        defaultValue = match.group(2)

        envValue = os.environ.get(varName)

        if envValue is not None:
            logger.debug(f"Resolved {varName} from environment")
            return envValue
        elif defaultValue is not None:
            logger.debug(f"Using default for {varName}")
            return defaultValue
        else:
            logger.warning(f"Environment variable {varName} not set and no default")
            return match.group(0)  # Return original placeholder

    return PLACEHOLDER_PATTERN.sub(replacer, value)


def loadConfigWithSecrets(
    configPath: str,
    envPath: Optional[str] = None
) -> Dict[str, Any]:
    """
    Load configuration file and resolve all secret placeholders.

    Args:
        configPath: Path to configuration JSON file
        envPath: Optional path to .env file

    Returns:
        Configuration dictionary with secrets resolved

    Raises:
        FileNotFoundError: If config file doesn't exist
        json.JSONDecodeError: If config file is invalid JSON
    """
    # Load environment variables first
    loadEnvFile(envPath)

    # Load configuration file
    configFile = Path(configPath)
    if not configFile.exists():
        raise FileNotFoundError(f"Configuration file not found: {configPath}")

    logger.info(f"Loading configuration from {configPath}")

    with open(configFile, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # Resolve secret placeholders
    config = resolveSecrets(config)

    logger.info("Configuration loaded and secrets resolved")
    return config


def getSecret(varName: str, default: Optional[str] = None) -> Optional[str]:
    """
    Get a secret value from environment.

    Args:
        varName: Environment variable name
        default: Default value if not set

    Returns:
        Secret value or default
    """
    value = os.environ.get(varName, default)

    if value is None:
        logger.warning(f"Secret {varName} not found")
    else:
        logger.debug(f"Retrieved secret {varName}")

    return value


def maskSecret(value: str, showChars: int = 4) -> str:
    """
    Mask a secret value for logging.

    Args:
        value: Secret value to mask
        showChars: Number of characters to show at start

    Returns:
        Masked string (e.g., "secr***")
    """
    if not value:
        return '[EMPTY]'

    if len(value) <= showChars:
        return '*' * len(value)

    return value[:showChars] + '*' * (len(value) - showChars)
