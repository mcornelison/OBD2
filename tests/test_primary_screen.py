################################################################################
# File Name: test_primary_screen.py
# Purpose/Description: Tests for Primary Driving Screen with Status Indicator
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-121
# ================================================================================
################################################################################
"""
Tests for the Primary Driving Screen (US-121).

Validates:
- Status indicator aggregation (worst-status-wins)
- Phase 2 element visibility (Boost/AFR hidden when ECMLink disconnected)
- Parameter color coding at threshold boundaries
- Screen element priorities and 480x320 rendering constraints
"""

from alert.tiered_thresholds import AlertSeverity
from display.screens.primary_screen import (
    OverallStatus,
    ParameterDisplay,
    PrimaryScreenState,
    buildPrimaryScreenState,
    computeOverallStatus,
    getVisibleParameters,
)

# ================================================================================
# OverallStatus Enum Tests
# ================================================================================


class TestOverallStatus:
    """Tests for OverallStatus enum values and ordering."""

    def test_overallStatus_hasThreeValues(self):
        """
        Given: OverallStatus enum
        When: checking values
        Then: contains GREEN, YELLOW, RED
        """
        assert OverallStatus.GREEN.value == "green"
        assert OverallStatus.YELLOW.value == "yellow"
        assert OverallStatus.RED.value == "red"

    def test_overallStatus_ordering_redIsWorst(self):
        """
        Given: all OverallStatus values
        When: comparing severity ordering
        Then: RED > YELLOW > GREEN
        """
        assert OverallStatus.RED.severityOrder > OverallStatus.YELLOW.severityOrder
        assert OverallStatus.YELLOW.severityOrder > OverallStatus.GREEN.severityOrder


# ================================================================================
# computeOverallStatus Tests (worst-status-wins)
# ================================================================================


class TestComputeOverallStatus:
    """Tests for worst-status-wins aggregation logic."""

    def test_computeOverallStatus_allNormal_returnsGreen(self):
        """
        Given: all parameter severities are NORMAL
        When: computing overall status
        Then: returns GREEN
        """
        severities = [AlertSeverity.NORMAL, AlertSeverity.NORMAL, AlertSeverity.NORMAL]
        result = computeOverallStatus(severities)
        assert result == OverallStatus.GREEN

    def test_computeOverallStatus_oneCaution_returnsYellow(self):
        """
        Given: one parameter at CAUTION, rest NORMAL
        When: computing overall status
        Then: returns YELLOW (worst wins)
        """
        severities = [AlertSeverity.NORMAL, AlertSeverity.CAUTION, AlertSeverity.NORMAL]
        result = computeOverallStatus(severities)
        assert result == OverallStatus.YELLOW

    def test_computeOverallStatus_oneDanger_returnsRed(self):
        """
        Given: one parameter at DANGER, rest NORMAL
        When: computing overall status
        Then: returns RED (worst wins)
        """
        severities = [AlertSeverity.NORMAL, AlertSeverity.DANGER, AlertSeverity.NORMAL]
        result = computeOverallStatus(severities)
        assert result == OverallStatus.RED

    def test_computeOverallStatus_dangerAndCaution_returnsRed(self):
        """
        Given: mix of DANGER and CAUTION severities
        When: computing overall status
        Then: returns RED (worst wins)
        """
        severities = [AlertSeverity.CAUTION, AlertSeverity.DANGER, AlertSeverity.CAUTION]
        result = computeOverallStatus(severities)
        assert result == OverallStatus.RED

    def test_computeOverallStatus_emptySeverities_returnsGreen(self):
        """
        Given: no severity evaluations (empty list)
        When: computing overall status
        Then: returns GREEN (no alerts = all clear)
        """
        result = computeOverallStatus([])
        assert result == OverallStatus.GREEN

    def test_computeOverallStatus_infoSeverity_returnsGreen(self):
        """
        Given: INFO severity (cold engine, etc.)
        When: computing overall status
        Then: returns GREEN (INFO is informational, not a warning)
        """
        severities = [AlertSeverity.INFO, AlertSeverity.NORMAL]
        result = computeOverallStatus(severities)
        assert result == OverallStatus.GREEN

    def test_computeOverallStatus_singleDanger_returnsRed(self):
        """
        Given: single DANGER severity
        When: computing overall status
        Then: returns RED
        """
        result = computeOverallStatus([AlertSeverity.DANGER])
        assert result == OverallStatus.RED


# ================================================================================
# ParameterDisplay Tests
# ================================================================================


class TestParameterDisplay:
    """Tests for ParameterDisplay dataclass."""

    def test_parameterDisplay_defaultValues(self):
        """
        Given: ParameterDisplay with required fields
        When: creating instance
        Then: optional fields have sensible defaults
        """
        param = ParameterDisplay(
            name="COOLANT_TEMP",
            label="Coolant",
            value=185.0,
            unit="F",
            severity=AlertSeverity.NORMAL,
            indicatorColor="green",
        )
        assert param.name == "COOLANT_TEMP"
        assert param.value == 185.0
        assert param.isPhase2 is False
        assert param.priority == "medium"

    def test_parameterDisplay_phase2Boost(self):
        """
        Given: Boost parameter marked as Phase 2
        When: creating instance
        Then: isPhase2 is True
        """
        param = ParameterDisplay(
            name="BOOST",
            label="Boost",
            value=12.3,
            unit="psi",
            severity=AlertSeverity.NORMAL,
            indicatorColor="green",
            isPhase2=True,
        )
        assert param.isPhase2 is True

    def test_parameterDisplay_largePriority(self):
        """
        Given: status indicator with large priority
        When: creating instance
        Then: priority is set to large
        """
        param = ParameterDisplay(
            name="STATUS",
            label="Status",
            value=0.0,
            unit="",
            severity=AlertSeverity.NORMAL,
            indicatorColor="green",
            priority="large",
        )
        assert param.priority == "large"


# ================================================================================
# Phase 2 Element Visibility Tests
# ================================================================================


class TestGetVisibleParameters:
    """Tests for Phase 2 element hiding when hardware not present."""

    def _makeParams(self) -> list[ParameterDisplay]:
        """Create a standard set of parameters including Phase 2."""
        return [
            ParameterDisplay(
                name="COOLANT_TEMP", label="Coolant", value=185.0,
                unit="F", severity=AlertSeverity.NORMAL,
                indicatorColor="green", priority="large",
            ),
            ParameterDisplay(
                name="RPM", label="RPM", value=2500.0,
                unit="rpm", severity=AlertSeverity.NORMAL,
                indicatorColor="green", priority="medium",
            ),
            ParameterDisplay(
                name="BOOST", label="Boost", value=12.3,
                unit="psi", severity=AlertSeverity.NORMAL,
                indicatorColor="green", priority="medium",
                isPhase2=True,
            ),
            ParameterDisplay(
                name="AFR", label="AFR", value=11.5,
                unit="", severity=AlertSeverity.NORMAL,
                indicatorColor="green", priority="medium",
                isPhase2=True,
            ),
        ]

    def test_getVisibleParameters_ecmlinkConnected_showsAll(self):
        """
        Given: ECMLink connected (Phase 2 hardware present)
        When: getting visible parameters
        Then: all parameters including Boost and AFR are visible
        """
        params = self._makeParams()
        visible = getVisibleParameters(params, ecmlinkConnected=True)
        names = [p.name for p in visible]
        assert "BOOST" in names
        assert "AFR" in names
        assert len(visible) == 4

    def test_getVisibleParameters_ecmlinkDisconnected_hidesPhase2(self):
        """
        Given: ECMLink NOT connected (Phase 2 hardware absent)
        When: getting visible parameters
        Then: Boost and AFR are hidden, Phase 1 params remain
        """
        params = self._makeParams()
        visible = getVisibleParameters(params, ecmlinkConnected=False)
        names = [p.name for p in visible]
        assert "BOOST" not in names
        assert "AFR" not in names
        assert "COOLANT_TEMP" in names
        assert "RPM" in names
        assert len(visible) == 2

    def test_getVisibleParameters_noPhase2Params_unchangedByFlag(self):
        """
        Given: no Phase 2 parameters in the list
        When: getting visible parameters with ECMLink disconnected
        Then: all Phase 1 parameters remain visible
        """
        params = [
            ParameterDisplay(
                name="COOLANT_TEMP", label="Coolant", value=185.0,
                unit="F", severity=AlertSeverity.NORMAL,
                indicatorColor="green",
            ),
        ]
        visible = getVisibleParameters(params, ecmlinkConnected=False)
        assert len(visible) == 1
        assert visible[0].name == "COOLANT_TEMP"

    def test_getVisibleParameters_allPhase2_emptyWhenDisconnected(self):
        """
        Given: only Phase 2 parameters
        When: ECMLink disconnected
        Then: returns empty list
        """
        params = [
            ParameterDisplay(
                name="BOOST", label="Boost", value=0.0,
                unit="psi", severity=AlertSeverity.NORMAL,
                indicatorColor="green", isPhase2=True,
            ),
        ]
        visible = getVisibleParameters(params, ecmlinkConnected=False)
        assert len(visible) == 0


# ================================================================================
# PrimaryScreenState Tests
# ================================================================================


class TestPrimaryScreenState:
    """Tests for PrimaryScreenState dataclass."""

    def test_primaryScreenState_defaultsToGreen(self):
        """
        Given: PrimaryScreenState with default values
        When: checking overall status
        Then: defaults to GREEN
        """
        state = PrimaryScreenState()
        assert state.overallStatus == OverallStatus.GREEN
        assert state.parameters == []
        assert state.ecmlinkConnected is False

    def test_primaryScreenState_screenDimensions(self):
        """
        Given: PrimaryScreenState
        When: checking screen dimensions
        Then: defaults to 480x320
        """
        state = PrimaryScreenState()
        assert state.screenWidth == 480
        assert state.screenHeight == 320

    def test_primaryScreenState_withParameters(self):
        """
        Given: PrimaryScreenState with parameters
        When: inspecting state
        Then: parameters are accessible
        """
        params = [
            ParameterDisplay(
                name="RPM", label="RPM", value=2500.0,
                unit="rpm", severity=AlertSeverity.NORMAL,
                indicatorColor="green",
            ),
        ]
        state = PrimaryScreenState(
            overallStatus=OverallStatus.GREEN,
            parameters=params,
        )
        assert len(state.parameters) == 1
        assert state.parameters[0].name == "RPM"


# ================================================================================
# buildPrimaryScreenState Integration Tests
# ================================================================================


class TestBuildPrimaryScreenState:
    """Tests for building complete screen state from parameter readings."""

    def _makeThresholdConfigs(self) -> dict:
        """Create threshold configs matching obd_config.json structure."""
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

    def test_buildPrimaryScreenState_allNormal_greenStatus(self):
        """
        Given: coolant=185F, RPM=2500 (both normal)
        When: building primary screen state
        Then: overall status is GREEN, all indicators green
        """
        readings = {"COOLANT_TEMP": 185.0, "RPM": 2500.0}
        thresholds = self._makeThresholdConfigs()
        state = buildPrimaryScreenState(
            readings=readings,
            thresholdConfigs=thresholds,
            ecmlinkConnected=False,
        )
        assert state.overallStatus == OverallStatus.GREEN
        coolantParam = next(p for p in state.parameters if p.name == "COOLANT_TEMP")
        assert coolantParam.indicatorColor == "green"

    def test_buildPrimaryScreenState_coolantCaution_yellowStatus(self):
        """
        Given: coolant=215F (caution), RPM=2500 (normal)
        When: building primary screen state
        Then: overall status is YELLOW (worst-status-wins)
        """
        readings = {"COOLANT_TEMP": 215.0, "RPM": 2500.0}
        thresholds = self._makeThresholdConfigs()
        state = buildPrimaryScreenState(
            readings=readings,
            thresholdConfigs=thresholds,
            ecmlinkConnected=False,
        )
        assert state.overallStatus == OverallStatus.YELLOW

    def test_buildPrimaryScreenState_coolantDanger_redStatus(self):
        """
        Given: coolant=225F (danger), RPM=2500 (normal)
        When: building primary screen state
        Then: overall status is RED
        """
        readings = {"COOLANT_TEMP": 225.0, "RPM": 2500.0}
        thresholds = self._makeThresholdConfigs()
        state = buildPrimaryScreenState(
            readings=readings,
            thresholdConfigs=thresholds,
            ecmlinkConnected=False,
        )
        assert state.overallStatus == OverallStatus.RED

    def test_buildPrimaryScreenState_rpmDanger_redStatus(self):
        """
        Given: coolant=185F (normal), RPM=7500 (danger/over-rev)
        When: building primary screen state
        Then: overall status is RED
        """
        readings = {"COOLANT_TEMP": 185.0, "RPM": 7500.0}
        thresholds = self._makeThresholdConfigs()
        state = buildPrimaryScreenState(
            readings=readings,
            thresholdConfigs=thresholds,
            ecmlinkConnected=False,
        )
        assert state.overallStatus == OverallStatus.RED

    def test_buildPrimaryScreenState_ecmlinkConnected_showsPhase2(self):
        """
        Given: ECMLink connected, boost and AFR readings present
        When: building primary screen state
        Then: Boost and AFR parameters are in visible list
        """
        readings = {
            "COOLANT_TEMP": 185.0,
            "RPM": 2500.0,
            "BOOST": 12.3,
            "AFR": 11.5,
        }
        thresholds = self._makeThresholdConfigs()
        state = buildPrimaryScreenState(
            readings=readings,
            thresholdConfigs=thresholds,
            ecmlinkConnected=True,
        )
        visibleNames = [p.name for p in state.visibleParameters]
        assert "BOOST" in visibleNames
        assert "AFR" in visibleNames

    def test_buildPrimaryScreenState_ecmlinkDisconnected_hidesPhase2(self):
        """
        Given: ECMLink NOT connected
        When: building primary screen state
        Then: Boost and AFR parameters are hidden even if readings exist
        """
        readings = {
            "COOLANT_TEMP": 185.0,
            "RPM": 2500.0,
            "BOOST": 12.3,
            "AFR": 11.5,
        }
        thresholds = self._makeThresholdConfigs()
        state = buildPrimaryScreenState(
            readings=readings,
            thresholdConfigs=thresholds,
            ecmlinkConnected=False,
        )
        visibleNames = [p.name for p in state.visibleParameters]
        assert "BOOST" not in visibleNames
        assert "AFR" not in visibleNames
        assert "COOLANT_TEMP" in visibleNames
        assert "RPM" in visibleNames

    def test_buildPrimaryScreenState_noReadings_greenStatus(self):
        """
        Given: no parameter readings available
        When: building primary screen state
        Then: overall status is GREEN (no data = no alerts)
        """
        state = buildPrimaryScreenState(
            readings={},
            thresholdConfigs=self._makeThresholdConfigs(),
            ecmlinkConnected=False,
        )
        assert state.overallStatus == OverallStatus.GREEN
        assert len(state.parameters) == 0

    def test_buildPrimaryScreenState_coolantColorAtBoundary(self):
        """
        Given: coolant exactly at cautionMin boundary (210F)
        When: building primary screen state
        Then: remains NORMAL (boundary semantics: value > boundary triggers higher)
        """
        readings = {"COOLANT_TEMP": 210.0, "RPM": 2500.0}
        thresholds = self._makeThresholdConfigs()
        state = buildPrimaryScreenState(
            readings=readings,
            thresholdConfigs=thresholds,
            ecmlinkConnected=False,
        )
        coolantParam = next(p for p in state.parameters if p.name == "COOLANT_TEMP")
        assert coolantParam.severity == AlertSeverity.NORMAL
        assert coolantParam.indicatorColor == "green"

    def test_buildPrimaryScreenState_coolantJustAboveCaution(self):
        """
        Given: coolant at 210.1F (just above cautionMin)
        When: building primary screen state
        Then: coolant shows CAUTION with yellow indicator
        """
        readings = {"COOLANT_TEMP": 210.1, "RPM": 2500.0}
        thresholds = self._makeThresholdConfigs()
        state = buildPrimaryScreenState(
            readings=readings,
            thresholdConfigs=thresholds,
            ecmlinkConnected=False,
        )
        coolantParam = next(p for p in state.parameters if p.name == "COOLANT_TEMP")
        assert coolantParam.severity == AlertSeverity.CAUTION
        assert coolantParam.indicatorColor == "yellow"

    def test_buildPrimaryScreenState_screenDimensions(self):
        """
        Given: building screen state
        When: checking dimensions
        Then: uses 480x320 for 3.5" touchscreen
        """
        state = buildPrimaryScreenState(
            readings={},
            thresholdConfigs=self._makeThresholdConfigs(),
            ecmlinkConnected=False,
        )
        assert state.screenWidth == 480
        assert state.screenHeight == 320

    def test_buildPrimaryScreenState_rpmCaution_yellowIndicator(self):
        """
        Given: RPM=6600 (above cautionMin 6500)
        When: building primary screen state
        Then: RPM indicator is yellow, overall status YELLOW
        """
        readings = {"COOLANT_TEMP": 185.0, "RPM": 6600.0}
        thresholds = self._makeThresholdConfigs()
        state = buildPrimaryScreenState(
            readings=readings,
            thresholdConfigs=thresholds,
            ecmlinkConnected=False,
        )
        rpmParam = next(p for p in state.parameters if p.name == "RPM")
        assert rpmParam.severity == AlertSeverity.CAUTION
        assert rpmParam.indicatorColor == "yellow"
        assert state.overallStatus == OverallStatus.YELLOW

    def test_buildPrimaryScreenState_multipleAlerts_worstWins(self):
        """
        Given: coolant=215F (CAUTION), RPM=7500 (DANGER)
        When: building primary screen state
        Then: overall status is RED (DANGER > CAUTION)
        """
        readings = {"COOLANT_TEMP": 215.0, "RPM": 7500.0}
        thresholds = self._makeThresholdConfigs()
        state = buildPrimaryScreenState(
            readings=readings,
            thresholdConfigs=thresholds,
            ecmlinkConnected=False,
        )
        assert state.overallStatus == OverallStatus.RED

    def test_buildPrimaryScreenState_parameterDisplayFormats(self):
        """
        Given: normal readings
        When: building screen state
        Then: coolant shows value with unit, RPM shows value with unit
        """
        readings = {"COOLANT_TEMP": 185.0, "RPM": 2500.0}
        thresholds = self._makeThresholdConfigs()
        state = buildPrimaryScreenState(
            readings=readings,
            thresholdConfigs=thresholds,
            ecmlinkConnected=False,
        )
        coolant = next(p for p in state.parameters if p.name == "COOLANT_TEMP")
        rpm = next(p for p in state.parameters if p.name == "RPM")
        assert coolant.unit == "F"
        assert coolant.label == "Coolant"
        assert coolant.priority == "large"
        assert rpm.unit == "rpm"
        assert rpm.label == "RPM"

    def test_buildPrimaryScreenState_boostAndAfrFormats(self):
        """
        Given: ECMLink connected with boost and AFR readings
        When: building screen state
        Then: Boost shows psi, AFR shows ratio, both medium priority
        """
        readings = {
            "COOLANT_TEMP": 185.0,
            "RPM": 2500.0,
            "BOOST": 12.3,
            "AFR": 11.5,
        }
        thresholds = self._makeThresholdConfigs()
        state = buildPrimaryScreenState(
            readings=readings,
            thresholdConfigs=thresholds,
            ecmlinkConnected=True,
        )
        boost = next(p for p in state.parameters if p.name == "BOOST")
        afr = next(p for p in state.parameters if p.name == "AFR")
        assert boost.unit == "psi"
        assert boost.isPhase2 is True
        assert afr.isPhase2 is True
