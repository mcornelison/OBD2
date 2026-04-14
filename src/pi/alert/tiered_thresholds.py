################################################################################
# File Name: tiered_thresholds.py
# Purpose/Description: Facade re-exporting the tiered threshold subsystem
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-107
# 2026-04-12    | Ralph Agent  | Added STFT thresholds for US-108
# 2026-04-12    | Ralph Agent  | Added RPM thresholds for US-110
# 2026-04-12    | Ralph Agent  | Added Battery Voltage thresholds for US-111
# 2026-04-12    | Ralph Agent  | US-145: Clarify descriptive-only fields in docstring
# 2026-04-14    | Sweep 5      | Split per-parameter into tiered_coolant/stft/rpm/battery
# ================================================================================
################################################################################
"""
Tiered threshold evaluation for multi-level parameter alerts.

Unlike single-threshold alerts (above/below one value), tiered thresholds
evaluate a parameter against multiple ranges, each with its own severity,
indicator color, and message. Used for parameters where different ranges
require different driver responses (e.g., coolant temp: cold/normal/caution/danger).

Thresholds are loaded from config.json under `pi.tieredThresholds`.

The implementation is now split per-parameter into sibling modules:
- tiered_core: AlertSeverity, TieredThresholdResult
- tiered_coolant: CoolantTempThresholds, evaluate/loadCoolantTemp*
- tiered_stft: STFTThresholds, evaluate/loadSTFT*
- tiered_rpm: RPMThresholds, evaluate/loadRPM*
- tiered_battery: BatteryVoltageThresholds, evaluate/loadBatteryVoltage*

This file remains as a compatibility facade so callers that import from
`pi.alert.tiered_thresholds` continue to resolve all symbols unchanged.
"""

from .tiered_battery import (
    BatteryVoltageThresholds,
    evaluateBatteryVoltage,
    loadBatteryVoltageThresholds,
)
from .tiered_coolant import (
    CoolantTempThresholds,
    evaluateCoolantTemp,
    loadCoolantTempThresholds,
)
from .tiered_core import AlertSeverity, TieredThresholdResult
from .tiered_rpm import (
    RPMThresholds,
    evaluateRPM,
    loadRPMThresholds,
)
from .tiered_stft import (
    STFTThresholds,
    evaluateSTFT,
    loadSTFTThresholds,
)

__all__ = [
    "AlertSeverity",
    "BatteryVoltageThresholds",
    "CoolantTempThresholds",
    "RPMThresholds",
    "STFTThresholds",
    "TieredThresholdResult",
    "evaluateBatteryVoltage",
    "evaluateCoolantTemp",
    "evaluateRPM",
    "evaluateSTFT",
    "loadBatteryVoltageThresholds",
    "loadCoolantTempThresholds",
    "loadRPMThresholds",
    "loadSTFTThresholds",
]
