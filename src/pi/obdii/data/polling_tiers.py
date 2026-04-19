################################################################################
# File Name: polling_tiers.py
# Purpose/Description: Tiered polling configuration for OBD-II parameter scheduling
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-136
# ================================================================================
################################################################################
"""
Tiered polling configuration for OBD-II parameter scheduling.

Implements Spool's tuning-driven 4-tier polling structure:
  Tier 1 (every cycle, ~1 Hz): Safety-critical PIDs
  Tier 2 (every 3 cycles, ~0.3 Hz): Driving context PIDs
  Tier 3 (every 10 cycles, ~0.1 Hz): Trend analysis PIDs
  Tier 4 (every 30 cycles, ~0.03 Hz): Background monitoring PIDs

Thresholds are loaded from obd_config.json under the pollingTiers key.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ================================================================================
# Data Classes
# ================================================================================


@dataclass
class PollingTierParameter:
    """A single parameter within a polling tier.

    Attributes:
        name: Parameter name matching realtimeData config (e.g., "RPM")
        pid: OBD-II PID hex code (e.g., "0x0C")
        caveat: Optional caveat about this parameter's behavior on this vehicle
    """

    name: str
    pid: str
    caveat: str | None = None


@dataclass
class PollingTier:
    """A single polling tier with its cycle interval and parameters.

    Attributes:
        tier: Tier number (1-4)
        cycleInterval: Poll every N cycles (1=every cycle, 3=every 3rd, etc.)
        description: Human-readable tier description
        parameters: List of parameters in this tier
    """

    tier: int
    cycleInterval: int
    description: str
    parameters: list[PollingTierParameter] = field(default_factory=list)


@dataclass
class PollingTierConfig:
    """Complete tiered polling configuration.

    Attributes:
        tiers: Ordered list of polling tiers (tier 1 first)
    """

    tiers: list[PollingTier] = field(default_factory=list)


# ================================================================================
# Config Loading
# ================================================================================


def loadPollingTiers(config: dict[str, Any]) -> PollingTierConfig:
    """Load polling tier configuration from obd_config.

    Args:
        config: Full application config dict containing pollingTiers key

    Returns:
        Parsed PollingTierConfig

    Raises:
        KeyError: If pollingTiers section is missing
        ValueError: If pollingTiers section is empty
    """
    tierSection = config["pi"]["pollingTiers"]

    if not tierSection:
        raise ValueError("pollingTiers section is empty")

    tiers: list[PollingTier] = []
    tierKeys = sorted(tierSection.keys())

    for tierKey in tierKeys:
        tierData = tierSection[tierKey]
        tierNumber = int(tierKey.replace("tier", ""))

        parameters: list[PollingTierParameter] = []
        for paramData in tierData["parameters"]:
            parameters.append(
                PollingTierParameter(
                    name=paramData["name"],
                    pid=paramData["pid"],
                    caveat=paramData.get("caveat"),
                )
            )

        tiers.append(
            PollingTier(
                tier=tierNumber,
                cycleInterval=tierData["cycleInterval"],
                description=tierData.get("description", ""),
                parameters=parameters,
            )
        )

    logger.info(
        "Loaded %d polling tiers with %d total parameters",
        len(tiers),
        sum(len(t.parameters) for t in tiers),
    )

    return PollingTierConfig(tiers=tiers)


# ================================================================================
# Tier Lookup
# ================================================================================


def getParameterTier(
    config: PollingTierConfig, parameterName: str
) -> PollingTier | None:
    """Look up which tier a parameter belongs to.

    Args:
        config: Loaded polling tier config
        parameterName: Parameter name to look up

    Returns:
        The PollingTier containing this parameter, or None if not found
    """
    for tier in config.tiers:
        for param in tier.parameters:
            if param.name == parameterName:
                return tier
    return None


def shouldPollParameter(
    config: PollingTierConfig, parameterName: str, cycleNumber: int
) -> bool:
    """Determine if a parameter should be polled on the given cycle.

    Args:
        config: Loaded polling tier config
        parameterName: Parameter name to check
        cycleNumber: Current cycle number (1-based)

    Returns:
        True if the parameter should be polled this cycle
    """
    tier = getParameterTier(config, parameterName)
    if tier is None:
        return False
    return cycleNumber % tier.cycleInterval == 0


def getParametersForCycle(
    config: PollingTierConfig, cycleNumber: int
) -> list[str]:
    """Get all parameters that should be polled on the given cycle.

    Args:
        config: Loaded polling tier config
        cycleNumber: Current cycle number (1-based)

    Returns:
        List of parameter names to poll this cycle
    """
    parameters: list[str] = []
    for tier in config.tiers:
        if cycleNumber % tier.cycleInterval == 0:
            parameters.extend(p.name for p in tier.parameters)
    return parameters
