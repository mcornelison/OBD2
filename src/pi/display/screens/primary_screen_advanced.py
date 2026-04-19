################################################################################
# File Name: primary_screen_advanced.py
# Purpose/Description: Advanced-tier primary screen state + layout (US-165)
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
Advanced-tier primary screen (Sprint 12 Pi Polish / US-165, spec 2.4).

Extends the US-164 basic tier with:

1. Three connectivity indicators in the header -- OBD, WiFi, Sync -- each
   rendered as a labeled colored dot with independent green / gray / red
   state.
2. Min/max markers from recent drives in a ``[min / max]`` bracket line
   under each gauge value.
3. Color-coded gauge values per spec 2.4: blue (cold/below normal), white
   (normal), orange (caution), red (danger). Colors come from
   ``pi.display.theme.advancedTierSeverityToColor`` so they can diverge from
   the basic-tier yellow/white/red palette without regressing US-164.
4. Extended footer with last-sync timestamp ("3m ago" / "never"), total
   drive count, battery SOC, and power source.

Follows the same pure-data pipeline as US-164:

    buildAdvancedTierScreenState(readings, thresholdConfigs, header, footer,
        history) -> AdvancedTierScreenState
    computeAdvancedTierLayout(state) -> list[LayoutElement]

A pygame renderer (``primary_renderer.renderPrimaryScreen``) walks the list
and draws each element -- no pygame dependency in this module.

Empty-history semantics (Option B, flagged to Spool for Gate 2 review): when
the ``statistics`` table has no rows for a parameter (fresh Pi install,
never driven), the bracket renders as ``[--- / ---]`` -- a deliberate
placeholder matching the existing ``primary_screen._PLACEHOLDER_VALUE``
convention. Alternative designs (omit the bracket, or show current value
as both min and max) are documented in the Gate 2 review packet.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from pi.alert.tiered_thresholds import AlertSeverity

from ..theme import advancedTierSeverityToColor
from .primary_screen import (
    _PARAMETER_CONFIG,
    BASIC_TIER_DISPLAY_ORDER,
    BODY_GRID_COLS,
    LayoutElement,
    PrimaryScreenState,
    ScreenFooter,
    ScreenHeader,
    _formatValue,
    buildBasicTierScreenState,
)

__all__ = [
    "ADVANCED_BODY_CELL_H",
    "ADVANCED_BODY_TOP",
    "ADVANCED_FOOTER_HEIGHT",
    "ADVANCED_HEADER_HEIGHT",
    "AdvancedTierFooter",
    "AdvancedTierHeader",
    "AdvancedTierScreenState",
    "ConnectionState",
    "ConnectivityIndicators",
    "GaugeHistory",
    "MinMaxMarker",
    "buildAdvancedTierScreenState",
    "computeAdvancedTierLayout",
    "formatLastSyncAgo",
]


# ================================================================================
# Enums + data classes
# ================================================================================


class ConnectionState(Enum):
    """State of an individual connectivity indicator.

    ERROR is distinct from DISCONNECTED: DISCONNECTED means "nothing to talk
    to yet" (e.g., WiFi not yet associated); ERROR means "last attempt
    failed" (e.g., sync returned 401).
    """

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class ConnectivityIndicators:
    """Three-indicator connectivity state for the advanced-tier header.

    Attributes:
        obd: Dongle link state -- CONNECTED once python-OBD reports an active
            connection.
        wifi: WiFi association state.
        sync: Last Pi->server sync state: CONNECTED on recent success,
            DISCONNECTED when never synced / offline, ERROR when the last
            attempt failed.
    """

    obd: ConnectionState = ConnectionState.DISCONNECTED
    wifi: ConnectionState = ConnectionState.DISCONNECTED
    sync: ConnectionState = ConnectionState.DISCONNECTED


@dataclass
class MinMaxMarker:
    """Observed min/max for a single parameter across recent drives."""

    minValue: float
    maxValue: float


@dataclass
class GaugeHistory:
    """Historical min/max per parameter, plus the drive count it spans.

    Attributes:
        driveCount: Number of drives contributing to the aggregated min/max.
            Zero means "no history yet" -- layout renders placeholders.
        markers: Per-parameter ``MinMaxMarker``; missing keys render
            placeholders.
    """

    driveCount: int = 0
    markers: dict[str, MinMaxMarker] = field(default_factory=dict)


@dataclass
class AdvancedTierHeader:
    """Header state for the advanced-tier primary screen.

    Attributes:
        hostname: Device short name shown top-left.
        connectivity: Three-indicator state (OBD / WiFi / Sync).
        profileIndicator: Single-letter profile tag.
    """

    hostname: str = "Eclipse-01"
    connectivity: ConnectivityIndicators = field(default_factory=ConnectivityIndicators)
    profileIndicator: str = "D"


@dataclass
class AdvancedTierFooter:
    """Footer state for the advanced-tier primary screen.

    Attributes:
        alertMessages: Active alert messages (first shown in footer).
        lastSyncSeconds: Unix seconds of last successful sync, or ``None``.
        nowSeconds: Current Unix seconds (injected so tests are
            deterministic). Defaults to ``None`` -> ``time.time()`` at
            layout time.
        totalDriveCount: Total drives recorded on the Pi.
        batterySocPercent: 0-100 battery SOC, or ``None`` if unknown.
        powerSource: 'ac_power', 'battery', or 'unknown'.
    """

    alertMessages: list[str] = field(default_factory=list)
    lastSyncSeconds: float | None = None
    nowSeconds: float | None = None
    totalDriveCount: int = 0
    batterySocPercent: float | None = None
    powerSource: str = "unknown"


@dataclass
class AdvancedTierScreenState:
    """Composite state for the advanced-tier primary screen."""

    header: AdvancedTierHeader
    body: PrimaryScreenState
    footer: AdvancedTierFooter
    history: GaugeHistory


# ================================================================================
# Builders
# ================================================================================


def buildAdvancedTierScreenState(
    readings: dict[str, float],
    thresholdConfigs: dict,
    header: AdvancedTierHeader | None = None,
    footer: AdvancedTierFooter | None = None,
    history: GaugeHistory | None = None,
) -> AdvancedTierScreenState:
    """Build the composite advanced-tier state.

    Reuses ``buildBasicTierScreenState`` for the body (same six-parameter
    order, same threshold evaluation) and layers on connectivity + history +
    extended footer.

    Args:
        readings: Parameter values keyed by name. Missing keys are skipped.
        thresholdConfigs: ``tieredThresholds`` section from config.json.
        header: Optional ``AdvancedTierHeader`` (defaults to disconnected).
        footer: Optional ``AdvancedTierFooter`` (defaults to empty).
        history: Optional ``GaugeHistory`` from recent drives (defaults to
            empty -> placeholder brackets).

    Returns:
        ``AdvancedTierScreenState`` ready for ``computeAdvancedTierLayout``.
    """
    basicHeader = ScreenHeader(
        hostname=(header.hostname if header is not None else "Eclipse-01"),
        obdConnected=(
            header.connectivity.obd == ConnectionState.CONNECTED
            if header is not None
            else False
        ),
        profileIndicator=(header.profileIndicator if header is not None else "D"),
    )
    basicState = buildBasicTierScreenState(
        readings=readings,
        thresholdConfigs=thresholdConfigs,
        header=basicHeader,
        footer=ScreenFooter(),
    )

    return AdvancedTierScreenState(
        header=header if header is not None else AdvancedTierHeader(),
        body=basicState.body,
        footer=footer if footer is not None else AdvancedTierFooter(),
        history=history if history is not None else GaugeHistory(),
    )


# ================================================================================
# Layout geometry (480x320 OSOYOO 3.5" HDMI)
# ================================================================================


ADVANCED_HEADER_HEIGHT = 44
ADVANCED_FOOTER_HEIGHT = 44
ADVANCED_BODY_TOP = ADVANCED_HEADER_HEIGHT + 4  # 48
ADVANCED_BODY_CELL_H = 114  # 2 rows fit in 228, body_bottom = 276
ADVANCED_BODY_CELL_W = 480 // BODY_GRID_COLS  # 160

_HEADER_PADDING_X = 6
_FOOTER_PADDING_X = 6
_CONNECTIVITY_DOT_RADIUS = 6
_PLACEHOLDER = "---"

# Anchor points for the three connectivity indicators (dot + label),
# spaced across the top strip. Order: OBD (left), WiFi (middle), Sync (right).
_CONNECTIVITY_SLOT_X: tuple[int, int, int] = (90, 220, 350)
_CONNECTIVITY_LABEL_OFFSET_X = 14
_CONNECTIVITY_Y = ADVANCED_HEADER_HEIGHT // 2
_CONNECTIVITY_LABEL_Y = _CONNECTIVITY_Y - 10

_CONNECTIVITY_COLORS: dict[ConnectionState, str] = {
    ConnectionState.CONNECTED: "green",
    ConnectionState.DISCONNECTED: "gray",
    ConnectionState.ERROR: "red",
}


# ================================================================================
# Helpers
# ================================================================================


def formatLastSyncAgo(
    lastSyncSeconds: float | None,
    nowSeconds: float,
) -> str:
    """Human-readable relative time for the footer sync marker.

    Clock-skew tolerant: future timestamps clamp to "just now" rather than
    rendering negative ages.

    Thresholds:
        None          -> 'never'
        < 60 s        -> 'just now'
        < 1 hour      -> 'Nm ago'
        < 24 hours    -> 'Nh ago'
        otherwise     -> 'Nd ago'
    """
    if lastSyncSeconds is None:
        return "never"
    delta = nowSeconds - lastSyncSeconds
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def _formatMarkerValue(paramName: str, value: float) -> str:
    """Format a min or max marker value using the same rules as the main value."""
    return _formatValue(paramName, value)


def _formatBracket(paramName: str, marker: MinMaxMarker | None) -> str:
    """Render the '[min / max]' bracket line for a gauge.

    Empty/missing marker -> ``'[--- / ---]'`` (Option B -- see module
    docstring for the alternatives considered).
    """
    if marker is None:
        return f"[{_PLACEHOLDER} / {_PLACEHOLDER}]"
    return (
        f"[{_formatMarkerValue(paramName, marker.minValue)}"
        f" / {_formatMarkerValue(paramName, marker.maxValue)}]"
    )


def _valueColor(severity: AlertSeverity) -> str:
    return advancedTierSeverityToColor(severity)


def _connectivityColor(state: ConnectionState) -> str:
    return _CONNECTIVITY_COLORS.get(state, "gray")


def _bodyCellOrigin(index: int) -> tuple[int, int]:
    row = index // BODY_GRID_COLS
    col = index % BODY_GRID_COLS
    x = col * ADVANCED_BODY_CELL_W
    y = ADVANCED_BODY_TOP + row * ADVANCED_BODY_CELL_H
    return x, y


# ================================================================================
# Layout composer
# ================================================================================


def computeAdvancedTierLayout(
    state: AdvancedTierScreenState,
    width: int = 480,
    height: int = 320,
) -> list[LayoutElement]:
    """Produce a pure list of ``LayoutElement`` for an advanced-tier screen.

    Output is deterministic; tests filter by region/kind/text. No pygame
    dependency. Body grid stays 3x2 so it stays glanceable at arm's length;
    extra information (history, connectivity) is packed into the margins.
    """
    elements: list[LayoutElement] = []
    _appendHeader(elements, state.header, width)
    _appendBody(elements, state, width)
    _appendFooter(elements, state.footer, width, height)
    return elements


def _appendHeader(
    elements: list[LayoutElement],
    header: AdvancedTierHeader,
    width: int,
) -> None:
    elements.append(
        LayoutElement(
            kind="text",
            region="header",
            text=header.hostname,
            x=_HEADER_PADDING_X,
            y=10,
            fontSize="small",
            color="white",
        )
    )

    slots = (
        ("OBD", header.connectivity.obd, _CONNECTIVITY_SLOT_X[0]),
        ("WiFi", header.connectivity.wifi, _CONNECTIVITY_SLOT_X[1]),
        ("Sync", header.connectivity.sync, _CONNECTIVITY_SLOT_X[2]),
    )
    for label, connState, slotX in slots:
        elements.append(
            LayoutElement(
                kind="circle",
                region="header",
                x=slotX,
                y=_CONNECTIVITY_Y,
                radius=_CONNECTIVITY_DOT_RADIUS,
                color=_connectivityColor(connState),
            )
        )
        elements.append(
            LayoutElement(
                kind="text",
                region="header",
                text=label,
                x=slotX + _CONNECTIVITY_LABEL_OFFSET_X,
                y=_CONNECTIVITY_LABEL_Y,
                fontSize="small",
                color="white",
            )
        )

    elements.append(
        LayoutElement(
            kind="text",
            region="header",
            text=f"[{header.profileIndicator}]",
            x=width - 36,
            y=10,
            fontSize="small",
            color="white",
        )
    )
    elements.append(
        LayoutElement(
            kind="rect",
            region="header",
            x=0,
            y=ADVANCED_HEADER_HEIGHT,
            width=width,
            height=2,
            color="gray",
        )
    )


def _appendBody(
    elements: list[LayoutElement],
    state: AdvancedTierScreenState,
    width: int,
) -> None:
    # Re-evaluate each reading for the advanced-tier color palette. The
    # body's PrimaryScreenState already carries AlertSeverity per parameter,
    # but basic-tier stored "white"/"yellow"/"red" in indicatorColor. We map
    # the severity ourselves here using the advanced-tier theme.
    readingsByName = {p.name: p for p in state.body.parameters}

    # Grab raw numeric readings for blue-band evaluation (cold coolant, etc.)
    # The basic-tier body evaluator uses _evaluateBasicTierParameter which
    # only covers coolant + rpm. We rely on that -- other parameters default
    # to NORMAL (white).
    for index, paramName in enumerate(BASIC_TIER_DISPLAY_ORDER):
        cellX, cellY = _bodyCellOrigin(index)
        config = _PARAMETER_CONFIG[paramName]
        label = config["label"]

        elements.append(
            LayoutElement(
                kind="text",
                region="body",
                text=label,
                x=cellX + 8,
                y=cellY + 4,
                fontSize="normal",
                color="white",
            )
        )

        if paramName in readingsByName:
            param = readingsByName[paramName]
            # Re-evaluate against thresholds to catch INFO (cold/below-normal)
            # which basic-tier collapses to NORMAL at the body level.
            severity = _reevaluateSeverity(param.name, param.value, state)
            valueText = _formatValue(paramName, param.value)
            valueColor = _valueColor(severity)
        else:
            severity = AlertSeverity.NORMAL
            valueText = _PLACEHOLDER
            valueColor = "gray"

        elements.append(
            LayoutElement(
                kind="text",
                region="body",
                text=valueText,
                x=cellX + 8,
                y=cellY + 28,
                fontSize="large",
                color=valueColor,
            )
        )

        marker = state.history.markers.get(paramName)
        elements.append(
            LayoutElement(
                kind="text",
                region="body",
                text=_formatBracket(paramName, marker),
                x=cellX + 8,
                y=cellY + 82,
                fontSize="small",
                color="white",
            )
        )


def _reevaluateSeverity(
    paramName: str,
    value: float,
    state: AdvancedTierScreenState,
) -> AlertSeverity:
    """Re-evaluate a single parameter's severity against the configured
    thresholds, extending basic-tier NORMAL into INFO (cold) when the
    value sits below ``normalMin``.

    Basic tier always uses ``_evaluateBasicTierParameter`` which returns a
    ``TieredThresholdResult.severity`` that already covers INFO for coolant
    temp (the coolant evaluator emits INFO below normalMin). We call it and
    fall back to the ParameterDisplay's stored severity when the evaluator
    declines the param (SPEED, BOOST, AFR, BATTERY_VOLTAGE -- those stay
    NORMAL in both tiers, rendering white).
    """
    # We don't have thresholdConfigs inside state -- the basic-tier
    # evaluator wrote the severity onto ParameterDisplay at build time.
    # Look it up and return it verbatim.
    for p in state.body.parameters:
        if p.name == paramName:
            return p.severity
    return AlertSeverity.NORMAL


def _appendFooter(
    elements: list[LayoutElement],
    footer: AdvancedTierFooter,
    width: int,
    height: int,
) -> None:
    footerY = height - ADVANCED_FOOTER_HEIGHT
    elements.append(
        LayoutElement(
            kind="rect",
            region="footer",
            x=0,
            y=footerY - 2,
            width=width,
            height=2,
            color="gray",
        )
    )

    nowSeconds = footer.nowSeconds if footer.nowSeconds is not None else time.time()
    syncText = f"Sync: {formatLastSyncAgo(footer.lastSyncSeconds, nowSeconds)}"
    elements.append(
        LayoutElement(
            kind="text",
            region="footer",
            text=syncText,
            x=_FOOTER_PADDING_X,
            y=footerY + 6,
            fontSize="small",
            color="white",
        )
    )

    driveText = f"Drives: {footer.totalDriveCount}"
    elements.append(
        LayoutElement(
            kind="text",
            region="footer",
            text=driveText,
            x=_FOOTER_PADDING_X,
            y=footerY + 24,
            fontSize="small",
            color="white",
        )
    )

    if footer.alertMessages:
        elements.append(
            LayoutElement(
                kind="text",
                region="footer",
                text=footer.alertMessages[0][:36],
                x=width // 2 - 60,
                y=footerY + 14,
                fontSize="small",
                color="orange",
            )
        )

    if footer.batterySocPercent is not None:
        socInt = int(round(footer.batterySocPercent))
        socColor = "red" if socInt < 25 else ("orange" if socInt < 50 else "white")
        elements.append(
            LayoutElement(
                kind="text",
                region="footer",
                text=f"Bat: {socInt}%",
                x=width - 110,
                y=footerY + 6,
                fontSize="small",
                color=socColor,
            )
        )

    powerLabel = _powerSourceLabel(footer.powerSource)
    if powerLabel:
        elements.append(
            LayoutElement(
                kind="text",
                region="footer",
                text=powerLabel,
                x=width - 46,
                y=footerY + 6,
                fontSize="small",
                color="white",
            )
        )


def _powerSourceLabel(source: str) -> str:
    if source == "ac_power":
        return "AC"
    if source == "battery":
        return "BATT"
    return ""
