################################################################################
# File Name: test_primary_screen_basic_tier.py
# Purpose/Description: Unit tests for US-164 basic-tier primary screen layout
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Ralph Agent  | Initial implementation for US-164
# ================================================================================
################################################################################
"""
Unit tests for the US-164 basic-tier primary screen (Sprint 10 Pi Crawl).

Covers the pure-function layout pipeline — no pygame surface required:
    buildBasicTierScreenState(readings, thresholdConfigs, header, footer)
        -> BasicTierScreenState
    computeBasicTierLayout(state)
        -> list[LayoutElement]

Spool Gate 1 parameter order: RPM, Coolant, Boost, AFR, Speed, Battery Voltage.
See offices/pm/inbox/2026-04-16-from-spool-gate1-primary-screen.md.
"""

from pi.display.screens.primary_screen import (
    BASIC_TIER_DISPLAY_ORDER,
    BasicTierScreenState,
    LayoutElement,
    OverallStatus,
    ScreenFooter,
    ScreenHeader,
    buildBasicTierScreenState,
    computeBasicTierLayout,
)

# ================================================================================
# Fixtures
# ================================================================================


def _thresholdConfigs() -> dict:
    """Threshold configs matching obd_config.json shape."""
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


def _allSixReadings() -> dict:
    """Representative snapshot with all six basic-tier parameters."""
    return {
        "RPM": 2500.0,
        "COOLANT_TEMP": 185.0,
        "BOOST": 8.5,
        "AFR": 14.2,
        "SPEED": 35.0,
        "BATTERY_VOLTAGE": 14.1,
    }


# ================================================================================
# Spool Gate 1 order
# ================================================================================


class TestBasicTierDisplayOrder:
    """The 6-parameter order locked by Spool Gate 1 (2026-04-16)."""

    def test_basicTierDisplayOrder_hasAllSix(self):
        assert len(BASIC_TIER_DISPLAY_ORDER) == 6

    def test_basicTierDisplayOrder_spoolGate1Sequence(self):
        """
        Given: Spool Gate 1 confirmed order
        When: reading BASIC_TIER_DISPLAY_ORDER
        Then: matches RPM, Coolant, Boost, AFR, Speed, Battery Voltage
        """
        assert BASIC_TIER_DISPLAY_ORDER == (
            "RPM",
            "COOLANT_TEMP",
            "BOOST",
            "AFR",
            "SPEED",
            "BATTERY_VOLTAGE",
        )


# ================================================================================
# buildBasicTierScreenState
# ================================================================================


class TestBuildBasicTierScreenState:
    """Assembles screen state from readings + header/footer inputs."""

    def test_buildBasicTierScreenState_allSixReadings_allInOrder(self):
        """
        Given: readings for all six basic-tier parameters
        When: building basic-tier state
        Then: body.parameters lists all six in Spool Gate 1 order
        """
        state = buildBasicTierScreenState(
            readings=_allSixReadings(),
            thresholdConfigs=_thresholdConfigs(),
        )
        names = [p.name for p in state.body.parameters]
        assert names == list(BASIC_TIER_DISPLAY_ORDER)

    def test_buildBasicTierScreenState_missingReading_skipped(self):
        """
        Given: readings missing BOOST
        When: building basic-tier state
        Then: BOOST not in parameters (crawl shows only what it has)
        """
        readings = _allSixReadings()
        del readings["BOOST"]
        state = buildBasicTierScreenState(
            readings=readings,
            thresholdConfigs=_thresholdConfigs(),
        )
        names = [p.name for p in state.body.parameters]
        assert "BOOST" not in names
        assert len(names) == 5

    def test_buildBasicTierScreenState_speedAndVoltage_labeledCorrectly(self):
        """
        Given: readings include speed + battery voltage
        When: building state
        Then: labels are 'Speed' and 'Volts'
        """
        state = buildBasicTierScreenState(
            readings=_allSixReadings(),
            thresholdConfigs=_thresholdConfigs(),
        )
        speed = next(p for p in state.body.parameters if p.name == "SPEED")
        volts = next(p for p in state.body.parameters if p.name == "BATTERY_VOLTAGE")
        assert speed.label == "Speed"
        assert volts.label == "Volts"

    def test_buildBasicTierScreenState_afrLabel_stableAcrossTiers(self):
        """
        Spool Gate 1 note: AFR label must be plain 'AFR' (not 'Wideband' / 'UEGO')
        because stock 2G OBD-II narrowband O2 is rich/lean indicator only.
        """
        state = buildBasicTierScreenState(
            readings=_allSixReadings(),
            thresholdConfigs=_thresholdConfigs(),
        )
        afr = next(p for p in state.body.parameters if p.name == "AFR")
        assert afr.label == "AFR"

    def test_buildBasicTierScreenState_boostAndAfr_notHiddenByEcmlinkGate(self):
        """
        Basic tier (crawl) shows Boost + AFR regardless of ECMLink status.
        The isPhase2 hiding is a later-tier behavior — crawl shows what it has.
        """
        state = buildBasicTierScreenState(
            readings=_allSixReadings(),
            thresholdConfigs=_thresholdConfigs(),
        )
        names = [p.name for p in state.body.parameters]
        assert "BOOST" in names
        assert "AFR" in names

    def test_buildBasicTierScreenState_coolantCaution_bodyOverallStatusYellow(self):
        """
        Given: coolant=215F (caution)
        When: building state
        Then: body.overallStatus == YELLOW (worst-status-wins)
        """
        readings = _allSixReadings()
        readings["COOLANT_TEMP"] = 215.0
        state = buildBasicTierScreenState(
            readings=readings,
            thresholdConfigs=_thresholdConfigs(),
        )
        assert state.body.overallStatus == OverallStatus.YELLOW

    def test_buildBasicTierScreenState_rpmDanger_bodyOverallStatusRed(self):
        readings = _allSixReadings()
        readings["RPM"] = 7500.0
        state = buildBasicTierScreenState(
            readings=readings,
            thresholdConfigs=_thresholdConfigs(),
        )
        assert state.body.overallStatus == OverallStatus.RED

    def test_buildBasicTierScreenState_defaultHeader_usesEclipse01(self):
        state = buildBasicTierScreenState(
            readings=_allSixReadings(),
            thresholdConfigs=_thresholdConfigs(),
        )
        assert state.header.hostname == "Eclipse-01"
        assert state.header.obdConnected is False
        assert state.header.profileIndicator == "D"

    def test_buildBasicTierScreenState_customHeader_preserved(self):
        header = ScreenHeader(
            hostname="test-pi", obdConnected=True, profileIndicator="R"
        )
        state = buildBasicTierScreenState(
            readings=_allSixReadings(),
            thresholdConfigs=_thresholdConfigs(),
            header=header,
        )
        assert state.header.hostname == "test-pi"
        assert state.header.obdConnected is True
        assert state.header.profileIndicator == "R"

    def test_buildBasicTierScreenState_defaultFooter_empty(self):
        state = buildBasicTierScreenState(
            readings=_allSixReadings(),
            thresholdConfigs=_thresholdConfigs(),
        )
        assert state.footer.alertMessages == []
        assert state.footer.batterySocPercent is None
        assert state.footer.powerSource == "unknown"

    def test_buildBasicTierScreenState_customFooter_preserved(self):
        footer = ScreenFooter(
            alertMessages=["Coolant high"],
            batterySocPercent=87.0,
            powerSource="ac_power",
        )
        state = buildBasicTierScreenState(
            readings=_allSixReadings(),
            thresholdConfigs=_thresholdConfigs(),
            footer=footer,
        )
        assert state.footer.alertMessages == ["Coolant high"]
        assert state.footer.batterySocPercent == 87.0
        assert state.footer.powerSource == "ac_power"

    def test_buildBasicTierScreenState_noReadings_emptyBody(self):
        state = buildBasicTierScreenState(
            readings={},
            thresholdConfigs=_thresholdConfigs(),
        )
        assert state.body.overallStatus == OverallStatus.GREEN
        assert state.body.parameters == []


# ================================================================================
# computeBasicTierLayout
# ================================================================================


class TestComputeBasicTierLayout:
    """Pure-function layout produces a list of drawable LayoutElements."""

    def _buildState(
        self,
        readings: dict | None = None,
        header: ScreenHeader | None = None,
        footer: ScreenFooter | None = None,
    ) -> BasicTierScreenState:
        return buildBasicTierScreenState(
            readings=readings if readings is not None else _allSixReadings(),
            thresholdConfigs=_thresholdConfigs(),
            header=header,
            footer=footer,
        )

    def test_computeBasicTierLayout_returnsListOfLayoutElements(self):
        layout = computeBasicTierLayout(self._buildState())
        assert isinstance(layout, list)
        assert all(isinstance(e, LayoutElement) for e in layout)
        assert len(layout) > 0

    def test_computeBasicTierLayout_elementsWithinScreenBounds(self):
        """
        Given: 480x320 screen
        When: laying out the basic tier
        Then: every element's bounding box stays on-screen
        """
        layout = computeBasicTierLayout(self._buildState())
        for e in layout:
            assert e.x >= 0, f"{e} has negative x"
            assert e.y >= 0, f"{e} has negative y"
            assert e.x <= 480, f"{e} x past right edge"
            assert e.y <= 320, f"{e} y past bottom edge"

    def test_computeBasicTierLayout_hasHeaderHostname(self):
        layout = computeBasicTierLayout(
            self._buildState(header=ScreenHeader(hostname="Eclipse-01"))
        )
        headerTexts = [e.text for e in layout if e.region == "header" and e.kind == "text"]
        assert "Eclipse-01" in headerTexts

    def test_computeBasicTierLayout_hasObdStatusDot(self):
        """OBD connection status is rendered as a centered circle in the header."""
        layout = computeBasicTierLayout(self._buildState())
        dots = [e for e in layout if e.region == "header" and e.kind == "circle"]
        assert len(dots) == 1
        # Horizontally near center (allow generous tolerance for layout)
        assert 180 < dots[0].x < 300

    def test_computeBasicTierLayout_obdDotColor_connectedGreen(self):
        layout = computeBasicTierLayout(
            self._buildState(
                header=ScreenHeader(hostname="Eclipse-01", obdConnected=True)
            )
        )
        dot = next(e for e in layout if e.region == "header" and e.kind == "circle")
        assert dot.color == "green"

    def test_computeBasicTierLayout_obdDotColor_disconnectedRed(self):
        layout = computeBasicTierLayout(
            self._buildState(
                header=ScreenHeader(hostname="Eclipse-01", obdConnected=False)
            )
        )
        dot = next(e for e in layout if e.region == "header" and e.kind == "circle")
        assert dot.color == "red"

    def test_computeBasicTierLayout_hasProfileIndicator(self):
        layout = computeBasicTierLayout(
            self._buildState(
                header=ScreenHeader(
                    hostname="Eclipse-01", obdConnected=True, profileIndicator="D"
                )
            )
        )
        headerTexts = [e.text for e in layout if e.region == "header" and e.kind == "text"]
        assert any("D" in t for t in headerTexts)

    def test_computeBasicTierLayout_hasAllSixBodyLabels(self):
        """Body contains labels for RPM, Coolant, Boost, AFR, Speed, Volts."""
        layout = computeBasicTierLayout(self._buildState())
        bodyTexts = " ".join(
            e.text for e in layout if e.region == "body" and e.kind == "text"
        )
        for label in ("RPM", "Coolant", "Boost", "AFR", "Speed", "Volts"):
            assert label in bodyTexts, f"Missing label: {label}"

    def test_computeBasicTierLayout_bodyRendersValuesForAllSix(self):
        """Each parameter value appears in the body region."""
        layout = computeBasicTierLayout(self._buildState())
        bodyTexts = " ".join(
            e.text for e in layout if e.region == "body" and e.kind == "text"
        )
        # Values from _allSixReadings()
        assert "2500" in bodyTexts  # RPM
        assert "185" in bodyTexts  # Coolant
        assert "8.5" in bodyTexts  # Boost
        assert "14.2" in bodyTexts  # AFR
        assert "35" in bodyTexts  # Speed
        assert "14.1" in bodyTexts  # Battery Voltage

    def test_computeBasicTierLayout_spoolOrderPreservedInBody(self):
        """
        Given: basic-tier state with all six
        When: laying out body
        Then: labels appear in Spool Gate 1 order reading top-left to bottom-right.
              Verified via y coord first, then x coord on each element.
        """
        layout = computeBasicTierLayout(self._buildState())
        labels = ("RPM", "Coolant", "Boost", "AFR", "Speed", "Volts")

        labelElements = []
        bodyText = [
            e for e in layout if e.region == "body" and e.kind == "text"
        ]
        for label in labels:
            matching = [e for e in bodyText if label in e.text]
            assert matching, f"No layout element for label {label}"
            labelElements.append((label, matching[0]))

        # Sorted by reading order (y then x) must match Spool order
        sortedByPosition = sorted(
            labelElements, key=lambda pair: (pair[1].y, pair[1].x)
        )
        orderFromLayout = [pair[0] for pair in sortedByPosition]
        assert orderFromLayout == list(labels)

    def test_computeBasicTierLayout_bodyUsesLargeFonts(self):
        """AC: 'Large high-contrast text — readable at arm's length'."""
        layout = computeBasicTierLayout(self._buildState())
        valueElements = [
            e for e in layout
            if e.region == "body" and e.kind == "text" and any(c.isdigit() for c in e.text)
        ]
        assert valueElements, "no numeric value elements in body"
        for e in valueElements:
            assert e.fontSize in ("large", "xlarge"), (
                f"body value font too small: {e.fontSize}"
            )

    def test_computeBasicTierLayout_footerEmptyAlerts_noAlertText(self):
        layout = computeBasicTierLayout(self._buildState())
        footerAlertTexts = [
            e.text for e in layout
            if e.region == "footer" and "alert" in e.text.lower()
        ]
        # No alert messages supplied, so no footer alert text
        assert footerAlertTexts == []

    def test_computeBasicTierLayout_footerAlertMessage_appearsInLayout(self):
        state = self._buildState(
            footer=ScreenFooter(alertMessages=["Coolant high (215F)"])
        )
        layout = computeBasicTierLayout(state)
        footerTexts = " ".join(
            e.text for e in layout if e.region == "footer" and e.kind == "text"
        )
        assert "Coolant high" in footerTexts

    def test_computeBasicTierLayout_footerShowsBatterySoc(self):
        state = self._buildState(
            footer=ScreenFooter(batterySocPercent=87.0, powerSource="ac_power")
        )
        layout = computeBasicTierLayout(state)
        footerTexts = " ".join(
            e.text for e in layout if e.region == "footer" and e.kind == "text"
        )
        assert "87" in footerTexts

    def test_computeBasicTierLayout_footerShowsPowerSourceAc(self):
        state = self._buildState(
            footer=ScreenFooter(batterySocPercent=87.0, powerSource="ac_power")
        )
        layout = computeBasicTierLayout(state)
        footerTexts = " ".join(
            e.text for e in layout if e.region == "footer" and e.kind == "text"
        )
        assert "AC" in footerTexts.upper()

    def test_computeBasicTierLayout_footerShowsPowerSourceBattery(self):
        state = self._buildState(
            footer=ScreenFooter(batterySocPercent=22.0, powerSource="battery")
        )
        layout = computeBasicTierLayout(state)
        footerTexts = " ".join(
            e.text for e in layout if e.region == "footer" and e.kind == "text"
        )
        assert "BATT" in footerTexts.upper()

    def test_computeBasicTierLayout_footerUnknownPower_stillRenders(self):
        layout = computeBasicTierLayout(self._buildState())
        # Should not crash; footer region may be sparse.
        footerElements = [e for e in layout if e.region == "footer"]
        assert isinstance(footerElements, list)

    def test_computeBasicTierLayout_highContrastColors(self):
        """
        Dark background assumption: body value colors should be high-contrast
        (white or severity-mapped colors). No element should be 'black' on the
        default dark background.
        """
        layout = computeBasicTierLayout(self._buildState())
        textElements = [e for e in layout if e.kind == "text"]
        for e in textElements:
            assert e.color != "black", f"Low-contrast text: {e}"

    def test_computeBasicTierLayout_noPhase2Hiding(self):
        """
        Regression: the old PrimaryScreenState would hide BOOST/AFR when
        ecmlinkConnected=False. Basic tier must not hide them.
        """
        layout = computeBasicTierLayout(self._buildState())
        bodyTexts = " ".join(
            e.text for e in layout if e.region == "body" and e.kind == "text"
        )
        assert "Boost" in bodyTexts
        assert "AFR" in bodyTexts

    def test_computeBasicTierLayout_missingReading_noCrash_noStaleValue(self):
        """If SPEED is missing, no numeric value appears next to the 'Speed' label."""
        readings = _allSixReadings()
        del readings["SPEED"]
        layout = computeBasicTierLayout(
            buildBasicTierScreenState(
                readings=readings,
                thresholdConfigs=_thresholdConfigs(),
            )
        )
        bodyTexts = " ".join(
            e.text for e in layout if e.region == "body" and e.kind == "text"
        )
        # Speed label still shown, but value is a placeholder (---), not 35
        assert "Speed" in bodyTexts
        assert "35" not in bodyTexts


# ================================================================================
# LayoutElement dataclass
# ================================================================================


class TestLayoutElement:
    def test_layoutElement_hasRequiredFields(self):
        e = LayoutElement(kind="text", region="header", text="Eclipse-01", x=10, y=10)
        assert e.kind == "text"
        assert e.region == "header"
        assert e.text == "Eclipse-01"
        assert e.x == 10
        assert e.y == 10
