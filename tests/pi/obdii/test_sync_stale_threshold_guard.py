################################################################################
# File Name: test_sync_stale_threshold_guard.py
# Purpose/Description: The Pi config validation rejects a sync-stale threshold
#                      at or below the sync interval (US-917-c, Atlas G4)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-10-27    | Rex (US-917-c) | Initial
# 2026-10-28    | Rex (US-817-c) | Moved pins: drive the production ConfigValidator
# ================================================================================
################################################################################

"""
US-917-c config guard.

The S3 sync member ("Not syncing at home") fires when ``lastOkTs`` is older
than ``pi.dashboard.syncStaleThresholdSeconds``. A threshold at or below
``pi.sync.intervalSeconds`` would make it flicker between two normal pushes,
so ConfigValidator refuses it (US-817-c: where main.py and powerwatch
validate) -- comparing the EFFECTIVE values (Atlas G4): the
configured key if present, else the default each consumer would fall back to.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from common.config.validator import (
    DEFAULT_SYNC_STALE_THRESHOLD_SECONDS,
    DEFAULTS,
    ConfigValidationError,
    ConfigValidator,
)

_MINIMAL_CONFIG: dict[str, Any] = {
    "protocolVersion": "1.0.0",
    "schemaVersion": "1.0.0",
    "deviceId": "test-device",
    "logging": {"level": "DEBUG"},
    "pi": {
        "database": {"path": "./test/obd.db"},
        "bluetooth": {"macAddress": "AA:BB:CC:DD:EE:FF"},
        "display": {"mode": "headless"},
        "realtimeData": {"parameters": [{"name": "RPM", "logData": True}]},
    },
    "server": {"ai": {}, "database": {}, "api": {}},
}

_THRESHOLD_KEY = "pi.dashboard.syncStaleThresholdSeconds"
_INTERVAL_KEY = "pi.sync.intervalSeconds"


def _config(*, threshold: Any = None, interval: Any = None) -> dict[str, Any]:
    config = copy.deepcopy(_MINIMAL_CONFIG)
    if threshold is not None:
        config["pi"]["dashboard"] = {"syncStaleThresholdSeconds": threshold}
    if interval is not None:
        config["pi"]["sync"] = {"intervalSeconds": interval}
    return config


def _validate(config: dict[str, Any]) -> dict[str, Any]:
    # MOVED PIN (US-817-c): the production validator, not loader.validateObdConfig.
    return ConfigValidator().validate(config)


def _rejected(config: dict[str, Any]) -> str:
    # MOVED PIN (US-817-c): ConfigValidator raises ConfigValidationError itself.
    with pytest.raises(ConfigValidationError) as excInfo:
        _validate(config)
    return str(excInfo.value)


def test_keyAbsent_interval60_passes() -> None:
    """G4 pin: the key is absent from config.json today; 120 > 60 passes."""
    _validate(_config(interval=60))


def test_keyAbsent_intervalAbsent_passes() -> None:
    _validate(_config())


def test_keyAbsent_interval120_rejects_namingBothKeys() -> None:
    """G4 pin: the effective threshold is the 120 s default, not 'no key'."""
    message = _rejected(_config(interval=120))

    assert _THRESHOLD_KEY in message
    assert _INTERVAL_KEY in message


@pytest.mark.parametrize("threshold", [60, 59, 30.0])
def test_thresholdAtOrBelowInterval_rejects_namingBothKeys(threshold: Any) -> None:
    message = _rejected(_config(threshold=threshold, interval=60))

    assert _THRESHOLD_KEY in message
    assert _INTERVAL_KEY in message


@pytest.mark.parametrize("threshold", [61, 120, 300.5])
def test_thresholdAboveInterval_passes(threshold: Any) -> None:
    _validate(_config(threshold=threshold, interval=60))


def test_thresholdAboveTheDefaultInterval_whenIntervalAbsent_passes() -> None:
    _validate(_config(threshold=61))


def test_thresholdAtTheDefaultInterval_whenIntervalAbsent_rejects() -> None:
    message = _rejected(_config(threshold=60))

    assert _THRESHOLD_KEY in message
    assert _INTERVAL_KEY in message


@pytest.mark.parametrize("threshold", ["120", True])
def test_nonNumericThreshold_rejects_namingTheKey(threshold: Any) -> None:
    assert _THRESHOLD_KEY in _rejected(_config(threshold=threshold))


def test_defaultsAreImportedFromTheirHomes() -> None:
    """No copied literal: the guard's fallbacks are the consumers' own."""
    # MOVED PIN (US-817-c): the fallbacks live on the validator, one home each.
    validator = ConfigValidator()

    assert validator._effectiveSyncStaleThresholdS({}) == DEFAULT_SYNC_STALE_THRESHOLD_SECONDS
    assert validator._effectiveSyncIntervalS({}) == DEFAULTS[_INTERVAL_KEY]
