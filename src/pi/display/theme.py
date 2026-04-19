################################################################################
# File Name: theme.py
# Purpose/Description: Display-tier color mapping (spec 2.4 blue/white/orange/red)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-165
# ================================================================================
################################################################################
"""
Color mapping for the advanced-tier primary screen (US-165, spec 2.4).

Spec 2.4 retires the basic-tier yellow in favor of orange for caution, and
adds a dedicated cold/below-normal band in blue:

    AlertSeverity.INFO    -> blue   (cold / below normal)
    AlertSeverity.NORMAL  -> white  (normal operating range)
    AlertSeverity.CAUTION -> orange (WATCH)
    AlertSeverity.DANGER  -> red    (INVESTIGATE / CRITICAL)

The basic-tier mapping in ``primary_screen._severityToColor`` (yellow for
caution, no blue) is unchanged -- both tiers coexist. Pick the right
helper for the renderer you are writing.

Source of truth for thresholds is ``specs/obd2-research.md`` safe operating
ranges via the ``pi.alert.tiered_thresholds`` evaluators -- this module only
decides how each evaluated severity maps to a display color.
"""

from __future__ import annotations

from pi.alert.tiered_thresholds import AlertSeverity

ADVANCED_TIER_COLORS: dict[AlertSeverity, str] = {
    AlertSeverity.INFO: "blue",
    AlertSeverity.NORMAL: "white",
    AlertSeverity.CAUTION: "orange",
    AlertSeverity.DANGER: "red",
}


def advancedTierSeverityToColor(severity: AlertSeverity) -> str:
    """Map a tiered-threshold severity to the advanced-tier gauge color.

    Falls back to white on any unmapped severity -- this keeps the renderer
    from crashing if a new severity is ever added; a quiet white gauge is
    easier to diagnose than a raised KeyError on the 3.5" screen.

    Args:
        severity: Evaluated severity level from
            ``pi.alert.tiered_thresholds.AlertSeverity``.

    Returns:
        Color name understood by ``primary_renderer._COLOR_MAP`` -- one of
        ``'blue'``, ``'white'``, ``'orange'``, ``'red'``.
    """
    return ADVANCED_TIER_COLORS.get(severity, "white")


__all__ = [
    "ADVANCED_TIER_COLORS",
    "advancedTierSeverityToColor",
]
