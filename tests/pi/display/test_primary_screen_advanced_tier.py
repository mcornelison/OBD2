################################################################################
# File Name: test_primary_screen_advanced_tier.py
# Purpose/Description: Unit tests for US-165 advanced-tier primary screen state
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
Unit tests for the US-165 advanced-tier primary screen (Sprint 12 Pi Polish).

Covers the pure-function pipeline that extends US-164's basic tier with:

1. Three connectivity indicators in the header (OBD / WiFi / Sync)
2. Min/max markers from recent drives, rendered in brackets next to each value
3. Color-coded gauge values per tiered threshold (blue / white / orange / red)
4. Footer extended with last-sync timestamp, total drive count, battery SOC
   + power source

Layout stays pure-data (``list[LayoutElement]``). No pygame required.
"""

from __future__ import annotations

from pi.alert.tiered_thresholds import AlertSeverity
from pi.display.screens.primary_screen import LayoutElement
from pi.display.screens.primary_screen_advanced import (
    AdvancedTierFooter,
    AdvancedTierHeader,
    AdvancedTierScreenState,
    ConnectionState,
    ConnectivityIndicators,
    GaugeHistory,
    MinMaxMarker,
    buildAdvancedTierScreenState,
    computeAdvancedTierLayout,
    formatLastSyncAgo,
)
from pi.display.theme import ADVANCED_TIER_COLORS, advancedTierSeverityToColor

# ================================================================================
# Fixtures
# ================================================================================


def _thresholdConfigs() -> dict:
    return {
        "coolantTemp": {
            "normalMin": 180.0,
            "cautionMin": 210.0,
            "dangerMin": 220.0,
        },
        "rpm": {
            "normalMin": 600.0,
            "cautionMin": 6500.0,
            "dangerMin": 7000.0,
        },
    }


def _sixReadings() -> dict:
    return {
        "RPM": 2500.0,
        "COOLANT_TEMP": 185.0,
        "BOOST": 8.5,
        "AFR": 14.2,
        "SPEED": 35.0,
        "BATTERY_VOLTAGE": 14.1,
    }


def _fiveDriveHistory() -> GaugeHistory:
    return GaugeHistory(
        driveCount=5,
        markers={
            "RPM": MinMaxMarker(minValue=780.0, maxValue=6200.0),
            "COOLANT_TEMP": MinMaxMarker(minValue=150.0, maxValue=212.0),
            "BOOST": MinMaxMarker(minValue=-5.0, maxValue=14.8),
            "AFR": MinMaxMarker(minValue=10.4, maxValue=18.0),
            "SPEED": MinMaxMarker(minValue=0.0, maxValue=75.0),
            "BATTERY_VOLTAGE": MinMaxMarker(minValue=12.4, maxValue=14.6),
        },
    )


# ================================================================================
# Theme — advanced-tier color mapping (spec 2.4 blue/white/orange/red)
# ================================================================================


class TestAdvancedTierColorMapping:
    def test_advancedTierSeverityToColor_dangerIsRed(self):
        assert advancedTierSeverityToColor(AlertSeverity.DANGER) == "red"

    def test_advancedTierSeverityToColor_cautionIsOrange(self):
        """Spec 2.4: caution = orange (not yellow — yellow is basic-tier only)."""
        assert advancedTierSeverityToColor(AlertSeverity.CAUTION) == "orange"

    def test_advancedTierSeverityToColor_normalIsWhite(self):
        assert advancedTierSeverityToColor(AlertSeverity.NORMAL) == "white"

    def test_advancedTierSeverityToColor_infoIsBlue(self):
        """Spec 2.4: blue = cold / below normal (AlertSeverity.INFO)."""
        assert advancedTierSeverityToColor(AlertSeverity.INFO) == "blue"

    def test_advancedTierColors_hasFourBands(self):
        """Every band in the advanced-tier spec has a color."""
        assert set(ADVANCED_TIER_COLORS.values()) == {"blue", "white", "orange", "red"}


# ================================================================================
# ConnectivityIndicators — green / gray / red three-way state
# ================================================================================


class TestConnectivityIndicators:
    def test_connectivityIndicators_defaultsAllDisconnected(self):
        c = ConnectivityIndicators()
        assert c.obd == ConnectionState.DISCONNECTED
        assert c.wifi == ConnectionState.DISCONNECTED
        assert c.sync == ConnectionState.DISCONNECTED

    def test_connectivityIndicators_allConnected(self):
        c = ConnectivityIndicators(
            obd=ConnectionState.CONNECTED,
            wifi=ConnectionState.CONNECTED,
            sync=ConnectionState.CONNECTED,
        )
        assert c.obd == ConnectionState.CONNECTED
        assert c.wifi == ConnectionState.CONNECTED
        assert c.sync == ConnectionState.CONNECTED

    def test_connectivityIndicators_errorState(self):
        """ERROR is distinct from DISCONNECTED — last sync attempt failed."""
        c = ConnectivityIndicators(sync=ConnectionState.ERROR)
        assert c.sync == ConnectionState.ERROR


# ================================================================================
# formatLastSyncAgo — human-readable "3m ago" / "never" / "just now"
# ================================================================================


class TestFormatLastSyncAgo:
    def test_formatLastSyncAgo_none_isNever(self):
        assert formatLastSyncAgo(None, nowSeconds=1_700_000_000.0) == "never"

    def test_formatLastSyncAgo_underOneMinute_isJustNow(self):
        now = 1_700_000_000.0
        assert formatLastSyncAgo(now - 5, nowSeconds=now) == "just now"
        assert formatLastSyncAgo(now - 30, nowSeconds=now) == "just now"

    def test_formatLastSyncAgo_threeMinutes_isMinutesAgo(self):
        now = 1_700_000_000.0
        assert formatLastSyncAgo(now - 180, nowSeconds=now) == "3m ago"

    def test_formatLastSyncAgo_twoHours_isHoursAgo(self):
        now = 1_700_000_000.0
        assert formatLastSyncAgo(now - 2 * 3600, nowSeconds=now) == "2h ago"

    def test_formatLastSyncAgo_threeDays_isDaysAgo(self):
        now = 1_700_000_000.0
        assert formatLastSyncAgo(now - 3 * 86400, nowSeconds=now) == "3d ago"

    def test_formatLastSyncAgo_futureTimestamp_clampsToJustNow(self):
        """Clock skew or bogus input: never render negative time."""
        now = 1_700_000_000.0
        assert formatLastSyncAgo(now + 100, nowSeconds=now) == "just now"


# ================================================================================
# buildAdvancedTierScreenState
# ================================================================================


class TestBuildAdvancedTierScreenState:
    def test_buildAdvancedTierScreenState_returnsAdvancedState(self):
        state = buildAdvancedTierScreenState(
            readings=_sixReadings(),
            thresholdConfigs=_thresholdConfigs(),
        )
        assert isinstance(state, AdvancedTierScreenState)

    def test_buildAdvancedTierScreenState_retainsBasicTierBody(self):
        """Advanced tier reuses the US-164 body — same 6 parameters, same order."""
        state = buildAdvancedTierScreenState(
            readings=_sixReadings(),
            thresholdConfigs=_thresholdConfigs(),
        )
        names = [p.name for p in state.body.parameters]
        assert names == ["RPM", "COOLANT_TEMP", "BOOST", "AFR", "SPEED", "BATTERY_VOLTAGE"]

    def test_buildAdvancedTierScreenState_defaultHeader_allDisconnected(self):
        state = buildAdvancedTierScreenState(
            readings=_sixReadings(),
            thresholdConfigs=_thresholdConfigs(),
        )
        assert state.header.hostname == "Eclipse-01"
        assert state.header.connectivity.obd == ConnectionState.DISCONNECTED
        assert state.header.connectivity.wifi == ConnectionState.DISCONNECTED
        assert state.header.connectivity.sync == ConnectionState.DISCONNECTED

    def test_buildAdvancedTierScreenState_customHeader_preserved(self):
        header = AdvancedTierHeader(
            hostname="eclipse-bench",
            connectivity=ConnectivityIndicators(
                obd=ConnectionState.CONNECTED,
                wifi=ConnectionState.CONNECTED,
                sync=ConnectionState.ERROR,
            ),
            profileIndicator="R",
        )
        state = buildAdvancedTierScreenState(
            readings=_sixReadings(),
            thresholdConfigs=_thresholdConfigs(),
            header=header,
        )
        assert state.header.hostname == "eclipse-bench"
        assert state.header.connectivity.sync == ConnectionState.ERROR
        assert state.header.profileIndicator == "R"

    def test_buildAdvancedTierScreenState_defaultFooter_emptyDriveCountZero(self):
        state = buildAdvancedTierScreenState(
            readings=_sixReadings(),
            thresholdConfigs=_thresholdConfigs(),
        )
        assert state.footer.totalDriveCount == 0
        assert state.footer.lastSyncSeconds is None
        assert state.footer.batterySocPercent is None
        assert state.footer.powerSource == "unknown"

    def test_buildAdvancedTierScreenState_historyStoredOnState(self):
        """History is part of the state so the layout step can render it."""
        history = _fiveDriveHistory()
        state = buildAdvancedTierScreenState(
            readings=_sixReadings(),
            thresholdConfigs=_thresholdConfigs(),
            history=history,
        )
        assert state.history.driveCount == 5
        assert state.history.markers["RPM"].minValue == 780.0
        assert state.history.markers["RPM"].maxValue == 6200.0


# ================================================================================
# computeAdvancedTierLayout — header indicators
# ================================================================================


class TestAdvancedTierLayoutHeader:
    """Three connectivity labels + three dots, each independently colored."""

    def _headerState(
        self,
        obd: ConnectionState = ConnectionState.DISCONNECTED,
        wifi: ConnectionState = ConnectionState.DISCONNECTED,
        sync: ConnectionState = ConnectionState.DISCONNECTED,
    ) -> AdvancedTierScreenState:
        header = AdvancedTierHeader(
            connectivity=ConnectivityIndicators(obd=obd, wifi=wifi, sync=sync),
        )
        return buildAdvancedTierScreenState(
            readings=_sixReadings(),
            thresholdConfigs=_thresholdConfigs(),
            header=header,
        )

    def test_advancedTierLayout_headerHasThreeConnectivityDots(self):
        layout = computeAdvancedTierLayout(self._headerState())
        dots = [e for e in layout if e.region == "header" and e.kind == "circle"]
        assert len(dots) == 3

    def test_advancedTierLayout_headerHasThreeConnectivityLabels(self):
        layout = computeAdvancedTierLayout(self._headerState())
        headerLabels = [
            e.text for e in layout if e.region == "header" and e.kind == "text"
        ]
        joined = " ".join(headerLabels)
        assert "OBD" in joined
        assert "WiFi" in joined
        assert "Sync" in joined

    def test_advancedTierLayout_obdConnected_isGreen(self):
        layout = computeAdvancedTierLayout(
            self._headerState(obd=ConnectionState.CONNECTED)
        )
        dots = [e for e in layout if e.region == "header" and e.kind == "circle"]
        # The OBD dot is the leftmost — smallest x
        dots.sort(key=lambda e: e.x)
        assert dots[0].color == "green"

    def test_advancedTierLayout_wifiDisconnected_isGray(self):
        layout = computeAdvancedTierLayout(
            self._headerState(
                obd=ConnectionState.CONNECTED,
                wifi=ConnectionState.DISCONNECTED,
            )
        )
        dots = [e for e in layout if e.region == "header" and e.kind == "circle"]
        dots.sort(key=lambda e: e.x)
        # Middle dot = WiFi
        assert dots[1].color == "gray"

    def test_advancedTierLayout_syncError_isRed(self):
        layout = computeAdvancedTierLayout(
            self._headerState(sync=ConnectionState.ERROR)
        )
        dots = [e for e in layout if e.region == "header" and e.kind == "circle"]
        dots.sort(key=lambda e: e.x)
        # Right dot = Sync
        assert dots[2].color == "red"

    def test_advancedTierLayout_threeIndicatorMatrix(self):
        """All 3 * 3 = 9 state combinations map cleanly to green/gray/red per dot."""
        stateMap = {
            ConnectionState.CONNECTED: "green",
            ConnectionState.DISCONNECTED: "gray",
            ConnectionState.ERROR: "red",
        }
        for obdState, obdColor in stateMap.items():
            for wifiState, wifiColor in stateMap.items():
                for syncState, syncColor in stateMap.items():
                    layout = computeAdvancedTierLayout(
                        self._headerState(obd=obdState, wifi=wifiState, sync=syncState)
                    )
                    dots = sorted(
                        (e for e in layout if e.region == "header" and e.kind == "circle"),
                        key=lambda e: e.x,
                    )
                    assert dots[0].color == obdColor
                    assert dots[1].color == wifiColor
                    assert dots[2].color == syncColor


# ================================================================================
# computeAdvancedTierLayout — body color-coded thresholds (spec 2.4)
# ================================================================================


class TestAdvancedTierLayoutColorCoding:
    """Per-threshold color coding replaces US-164's basic-tier yellow with orange."""

    def _state(self, readings: dict) -> AdvancedTierScreenState:
        return buildAdvancedTierScreenState(
            readings=readings,
            thresholdConfigs=_thresholdConfigs(),
        )

    def _valueElementFor(
        self, layout: list[LayoutElement], labelText: str
    ) -> LayoutElement:
        """Find the value element in the same grid cell as ``labelText``."""
        labels = [
            e
            for e in layout
            if e.region == "body" and e.kind == "text" and e.text == labelText
        ]
        assert len(labels) == 1, f"label {labelText!r} not unique in body"
        label = labels[0]
        # The value is the next 'large' text element directly below the label
        # (same cell, within BODY_CELL_H of the label's y).
        candidates = [
            e
            for e in layout
            if e.region == "body"
            and e.kind == "text"
            and e.fontSize == "large"
            and e.x == label.x
            and 0 < e.y - label.y < 100
        ]
        assert candidates, f"no value element below {labelText!r}"
        return candidates[0]

    def test_advancedTierLayout_coolantBelowNormal_isBlue(self):
        """150F coolant (below normalMin=180) — cold-band blue."""
        readings = _sixReadings()
        readings["COOLANT_TEMP"] = 150.0
        layout = computeAdvancedTierLayout(self._state(readings))
        value = self._valueElementFor(layout, "Coolant")
        assert value.color == "blue", (
            f"Expected blue for 150F coolant (below normalMin=180), got {value.color}"
        )

    def test_advancedTierLayout_coolantNormal_isWhite(self):
        readings = _sixReadings()
        readings["COOLANT_TEMP"] = 195.0
        layout = computeAdvancedTierLayout(self._state(readings))
        value = self._valueElementFor(layout, "Coolant")
        assert value.color == "white"

    def test_advancedTierLayout_coolantCaution_isOrange(self):
        """215F coolant — caution band (>= cautionMin=210). Spec says orange."""
        readings = _sixReadings()
        readings["COOLANT_TEMP"] = 215.0
        layout = computeAdvancedTierLayout(self._state(readings))
        value = self._valueElementFor(layout, "Coolant")
        assert value.color == "orange", (
            f"Expected orange for 215F coolant (caution band), got {value.color}"
        )

    def test_advancedTierLayout_coolantDanger_isRed(self):
        readings = _sixReadings()
        readings["COOLANT_TEMP"] = 225.0
        layout = computeAdvancedTierLayout(self._state(readings))
        value = self._valueElementFor(layout, "Coolant")
        assert value.color == "red"

    def test_advancedTierLayout_rpmDanger_isRed(self):
        readings = _sixReadings()
        readings["RPM"] = 7500.0
        layout = computeAdvancedTierLayout(self._state(readings))
        value = self._valueElementFor(layout, "RPM")
        assert value.color == "red"

    def test_advancedTierLayout_rpmCaution_isOrange(self):
        readings = _sixReadings()
        readings["RPM"] = 6700.0
        layout = computeAdvancedTierLayout(self._state(readings))
        value = self._valueElementFor(layout, "RPM")
        assert value.color == "orange"

    def test_advancedTierLayout_noYellowInAdvancedTier(self):
        """Spec 2.4 retires yellow in favor of orange. Basic tier still uses yellow."""
        readings = _sixReadings()
        readings["COOLANT_TEMP"] = 215.0  # caution
        readings["RPM"] = 6700.0  # caution
        layout = computeAdvancedTierLayout(self._state(readings))
        valueColors = [
            e.color
            for e in layout
            if e.region == "body" and e.kind == "text" and e.fontSize == "large"
        ]
        assert "yellow" not in valueColors


# ================================================================================
# computeAdvancedTierLayout — min/max markers
# ================================================================================


class TestAdvancedTierLayoutMinMaxMarkers:
    """Each gauge renders a '[min / max]' line when history is present."""

    def _stateWithHistory(self, history: GaugeHistory) -> AdvancedTierScreenState:
        return buildAdvancedTierScreenState(
            readings=_sixReadings(),
            thresholdConfigs=_thresholdConfigs(),
            history=history,
        )

    def test_advancedTierLayout_historyPresent_rpmBracketRendered(self):
        layout = computeAdvancedTierLayout(self._stateWithHistory(_fiveDriveHistory()))
        bodyTexts = [e.text for e in layout if e.region == "body" and e.kind == "text"]
        joined = " ".join(bodyTexts)
        # RPM min=780, max=6200 from the fixture
        assert "780" in joined
        assert "6200" in joined

    def test_advancedTierLayout_bracketFormat_hasSlashSeparator(self):
        """Format is '[min / max]' per spec example 'RPM 2400 [min 780 / max 6200]'."""
        layout = computeAdvancedTierLayout(self._stateWithHistory(_fiveDriveHistory()))
        bracketTexts = [
            e.text
            for e in layout
            if e.region == "body" and e.kind == "text" and "/" in e.text
        ]
        assert bracketTexts, "no bracket-format text rendered"
        for text in bracketTexts:
            assert "/" in text

    def test_advancedTierLayout_emptyHistory_placeholderMarkers(self):
        """No drives recorded yet — placeholders [--- / ---] (Option B)."""
        empty = GaugeHistory(driveCount=0, markers={})
        layout = computeAdvancedTierLayout(self._stateWithHistory(empty))
        bodyTexts = [
            e.text for e in layout if e.region == "body" and e.kind == "text"
        ]
        joined = " ".join(bodyTexts)
        assert "---" in joined

    def test_advancedTierLayout_historyPartial_missingParamGetsPlaceholder(self):
        """RPM history present but BOOST missing — BOOST still gets placeholder."""
        partial = GaugeHistory(
            driveCount=3,
            markers={"RPM": MinMaxMarker(minValue=800.0, maxValue=5000.0)},
        )
        layout = computeAdvancedTierLayout(self._stateWithHistory(partial))
        bracketTexts = [
            e.text
            for e in layout
            if e.region == "body" and e.kind == "text" and "/" in e.text
        ]
        # Every visible parameter gets a bracket line
        assert len(bracketTexts) >= 6

    def test_advancedTierLayout_bracketLineSmallerFont(self):
        """Min/max line uses small font to fit under the large value."""
        layout = computeAdvancedTierLayout(self._stateWithHistory(_fiveDriveHistory()))
        bracketElements = [
            e for e in layout if e.region == "body" and e.kind == "text" and "/" in e.text
        ]
        for e in bracketElements:
            assert e.fontSize == "small"


# ================================================================================
# computeAdvancedTierLayout — footer (last sync / drive count / SOC / power)
# ================================================================================


class TestAdvancedTierLayoutFooter:
    def _state(self, footer: AdvancedTierFooter) -> AdvancedTierScreenState:
        return buildAdvancedTierScreenState(
            readings=_sixReadings(),
            thresholdConfigs=_thresholdConfigs(),
            footer=footer,
        )

    def test_advancedTierLayout_footerShowsLastSyncAgo(self):
        now = 1_700_000_000.0
        footer = AdvancedTierFooter(lastSyncSeconds=now - 180, nowSeconds=now)
        layout = computeAdvancedTierLayout(self._state(footer))
        footerTexts = " ".join(
            e.text for e in layout if e.region == "footer" and e.kind == "text"
        )
        assert "3m ago" in footerTexts

    def test_advancedTierLayout_footerShowsNeverWhenNoSync(self):
        footer = AdvancedTierFooter(lastSyncSeconds=None)
        layout = computeAdvancedTierLayout(self._state(footer))
        footerTexts = " ".join(
            e.text for e in layout if e.region == "footer" and e.kind == "text"
        )
        assert "never" in footerTexts.lower()

    def test_advancedTierLayout_footerShowsDriveCount(self):
        footer = AdvancedTierFooter(totalDriveCount=42)
        layout = computeAdvancedTierLayout(self._state(footer))
        footerTexts = " ".join(
            e.text for e in layout if e.region == "footer" and e.kind == "text"
        )
        assert "42" in footerTexts

    def test_advancedTierLayout_footerShowsBatterySocAndAcPower(self):
        footer = AdvancedTierFooter(
            batterySocPercent=87.0, powerSource="ac_power"
        )
        layout = computeAdvancedTierLayout(self._state(footer))
        footerTexts = " ".join(
            e.text for e in layout if e.region == "footer" and e.kind == "text"
        )
        assert "87" in footerTexts
        assert "AC" in footerTexts.upper()

    def test_advancedTierLayout_footerShowsBatteryAndBattMode(self):
        footer = AdvancedTierFooter(
            batterySocPercent=22.0, powerSource="battery"
        )
        layout = computeAdvancedTierLayout(self._state(footer))
        footerTexts = " ".join(
            e.text for e in layout if e.region == "footer" and e.kind == "text"
        )
        assert "22" in footerTexts
        assert "BATT" in footerTexts.upper()


# ================================================================================
# Layout bounds + no regression on basic-tier semantics
# ================================================================================


class TestAdvancedTierLayoutBounds:
    def test_advancedTierLayout_allElementsWithinScreenBounds(self):
        history = _fiveDriveHistory()
        footer = AdvancedTierFooter(
            totalDriveCount=42,
            lastSyncSeconds=1_700_000_000.0 - 60,
            nowSeconds=1_700_000_000.0,
            batterySocPercent=87.0,
            powerSource="ac_power",
        )
        state = buildAdvancedTierScreenState(
            readings=_sixReadings(),
            thresholdConfigs=_thresholdConfigs(),
            history=history,
            footer=footer,
        )
        layout = computeAdvancedTierLayout(state)
        for e in layout:
            assert 0 <= e.x <= 480, f"{e} x out of bounds"
            assert 0 <= e.y <= 320, f"{e} y out of bounds"

    def test_advancedTierLayout_hasAllSixBodyLabels(self):
        layout = computeAdvancedTierLayout(
            buildAdvancedTierScreenState(
                readings=_sixReadings(),
                thresholdConfigs=_thresholdConfigs(),
            )
        )
        bodyTexts = " ".join(
            e.text for e in layout if e.region == "body" and e.kind == "text"
        )
        for label in ("RPM", "Coolant", "Boost", "AFR", "Speed", "Volts"):
            assert label in bodyTexts, f"Missing label: {label}"

    def test_advancedTierLayout_highContrastColors(self):
        """No 'black' text on the dark background."""
        layout = computeAdvancedTierLayout(
            buildAdvancedTierScreenState(
                readings=_sixReadings(),
                thresholdConfigs=_thresholdConfigs(),
            )
        )
        for e in layout:
            if e.kind == "text":
                assert e.color != "black"
