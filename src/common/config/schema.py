################################################################################
# File Name: schema.py
# Purpose/Description: Dataclass types describing config.json structure
# Author: Ralph Agent
# Creation Date: 2026-04-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-13    | Ralph Agent  | Initial — sweep 4 config restructure
# ================================================================================
################################################################################
"""
Typed schema for config.json.

Provides dataclass types describing the tier-aware config structure. These
types are used by the validator and by typed config-reading helpers.

Intentional scope limit: these dataclasses describe the SHAPE, not every
leaf value's type. Where a section is a free-form dict (e.g., per-parameter
threshold values), the type is ``dict[str, Any]``. Tighter typing lands
incrementally as specific sections stabilize.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, kw_only=True)
class LoggingConfig:
    """Shared logging configuration (same shape on Pi and server)."""

    level: str = "INFO"
    format: str = ""
    file: str | None = None
    maskPII: bool = True


@dataclass(slots=True, kw_only=True)
class PiConfig:
    """Pi-specific config sections. Each field is a free-form dict for now."""

    application: dict[str, Any] = field(default_factory=dict)
    database: dict[str, Any] = field(default_factory=dict)
    bluetooth: dict[str, Any] = field(default_factory=dict)
    vinDecoder: dict[str, Any] = field(default_factory=dict)
    display: dict[str, Any] = field(default_factory=dict)
    autoStart: dict[str, Any] = field(default_factory=dict)
    staticData: dict[str, Any] = field(default_factory=dict)
    realtimeData: dict[str, Any] = field(default_factory=dict)
    analysis: dict[str, Any] = field(default_factory=dict)
    profiles: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    pollingTiers: dict[str, Any] = field(default_factory=dict)
    tieredThresholds: dict[str, Any] = field(default_factory=dict)
    alerts: dict[str, Any] = field(default_factory=dict)
    dataRetention: dict[str, Any] = field(default_factory=dict)
    powerMonitoring: dict[str, Any] = field(default_factory=dict)
    export: dict[str, Any] = field(default_factory=dict)
    simulator: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class ServerConfig:
    """Server-specific config sections."""

    ai: dict[str, Any] = field(default_factory=dict)
    database: dict[str, Any] = field(default_factory=dict)
    api: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class AppConfig:
    """Top-level config shape for config.json."""

    protocolVersion: str
    schemaVersion: str
    deviceId: str
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    pi: PiConfig = field(default_factory=PiConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    @classmethod
    def fromDict(cls, data: dict[str, Any]) -> AppConfig:
        """Build AppConfig from a loaded config.json dict."""
        return cls(
            protocolVersion=data["protocolVersion"],
            schemaVersion=data["schemaVersion"],
            deviceId=data["deviceId"],
            logging=LoggingConfig(**(data.get("logging") or {})),
            pi=PiConfig(**(data.get("pi") or {})),
            server=ServerConfig(**(data.get("server") or {})),
        )


__all__ = ["AppConfig", "LoggingConfig", "PiConfig", "ServerConfig"]
