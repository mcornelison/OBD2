################################################################################
# File Name: test_fuel_detail.py
# Purpose/Description: Tests for Fuel Detail Page (US-123)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-123
# ================================================================================
################################################################################
"""
Tests for the Fuel Detail Page (US-123).

Validates:
- AFR deviation calculation and severity (normal, caution, danger)
- STFT/LTFT display with bidirectional threshold coloring
- Injector duty cycle severity thresholds
- Ethanol content display
- Page availability based on ECMLink connection
- Full FuelDetailState construction with mock ECMLink data
- Page hidden when ECMLink not connected
"""

from alert.tiered_thresholds import AlertSeverity
from display.screens.fuel_detail import (
    AFR_CAUTION_DEVIATION_DEFAULT,
    AFR_DANGER_DEVIATION_DEFAULT,
    INJECTOR_CAUTION_DEFAULT,
    INJECTOR_DANGER_DEFAULT,
    AFRInfo,
    AFRThresholds,
    FuelDetailState,
    FuelTrimInfo,
    InjectorDutyInfo,
    InjectorDutyThresholds,
    buildAFRInfo,
    buildFuelDetailState,
    buildFuelTrimInfo,
    buildInjectorDutyInfo,
    evaluateAFRDeviation,
    evaluateInjectorDuty,
    isFuelPageAvailable,
)

# ================================================================================
# AFRThresholds Tests
# ================================================================================


class TestAFRThresholds:
    """Tests for AFR threshold configuration defaults."""

    def test_afrThresholds_defaultValues(self):
        """
        Given: AFRThresholds with no args
        When: checking defaults
        Then: uses module-level default constants
        """
        thresholds = AFRThresholds()
        assert thresholds.cautionDeviation == AFR_CAUTION_DEVIATION_DEFAULT
        assert thresholds.dangerDeviation == AFR_DANGER_DEVIATION_DEFAULT

    def test_afrThresholds_customValues(self):
        """
        Given: AFRThresholds with custom values
        When: constructing
        Then: uses provided values
        """
        thresholds = AFRThresholds(cautionDeviation=0.3, dangerDeviation=0.8)
        assert thresholds.cautionDeviation == 0.3
        assert thresholds.dangerDeviation == 0.8


# ================================================================================
# InjectorDutyThresholds Tests
# ================================================================================


class TestInjectorDutyThresholds:
    """Tests for injector duty cycle threshold defaults."""

    def test_injectorDutyThresholds_defaultValues(self):
        """
        Given: InjectorDutyThresholds with no args
        When: checking defaults
        Then: uses module-level default constants
        """
        thresholds = InjectorDutyThresholds()
        assert thresholds.cautionMin == INJECTOR_CAUTION_DEFAULT
        assert thresholds.dangerMin == INJECTOR_DANGER_DEFAULT

    def test_injectorDutyThresholds_customValues(self):
        """
        Given: InjectorDutyThresholds with custom values
        When: constructing
        Then: uses provided values
        """
        thresholds = InjectorDutyThresholds(cautionMin=75.0, dangerMin=90.0)
        assert thresholds.cautionMin == 75.0
        assert thresholds.dangerMin == 90.0


# ================================================================================
# evaluateAFRDeviation Tests
# ================================================================================


class TestEvaluateAFRDeviation:
    """Tests for AFR deviation-based severity evaluation."""

    def test_evaluateAFR_exactMatch_returnsNormal(self):
        """
        Given: AFR actual equals target (zero deviation)
        When: evaluating AFR deviation
        Then: returns NORMAL severity with green indicator
        """
        severity, color = evaluateAFRDeviation(14.7, 14.7, AFRThresholds())
        assert severity == AlertSeverity.NORMAL
        assert color == "green"

    def test_evaluateAFR_smallLeanDeviation_returnsNormal(self):
        """
        Given: AFR slightly lean but within caution threshold
        When: evaluating AFR deviation
        Then: returns NORMAL
        """
        severity, color = evaluateAFRDeviation(14.9, 14.7, AFRThresholds())
        assert severity == AlertSeverity.NORMAL
        assert color == "green"

    def test_evaluateAFR_smallRichDeviation_returnsNormal(self):
        """
        Given: AFR slightly rich but within caution threshold
        When: evaluating AFR deviation
        Then: returns NORMAL
        """
        severity, color = evaluateAFRDeviation(14.5, 14.7, AFRThresholds())
        assert severity == AlertSeverity.NORMAL
        assert color == "green"

    def test_evaluateAFR_leanCaution_returnsCaution(self):
        """
        Given: AFR deviation lean, exceeding caution but not danger
        When: evaluating AFR deviation
        Then: returns CAUTION severity with yellow indicator
        """
        thresholds = AFRThresholds(cautionDeviation=0.5, dangerDeviation=1.0)
        severity, color = evaluateAFRDeviation(15.3, 14.7, thresholds)
        assert severity == AlertSeverity.CAUTION
        assert color == "yellow"

    def test_evaluateAFR_richCaution_returnsCaution(self):
        """
        Given: AFR deviation rich, exceeding caution but not danger
        When: evaluating AFR deviation
        Then: returns CAUTION severity with yellow indicator
        """
        thresholds = AFRThresholds(cautionDeviation=0.5, dangerDeviation=1.0)
        severity, color = evaluateAFRDeviation(14.1, 14.7, thresholds)
        assert severity == AlertSeverity.CAUTION
        assert color == "yellow"

    def test_evaluateAFR_leanDanger_returnsDanger(self):
        """
        Given: AFR deviation lean, exceeding danger threshold
        When: evaluating AFR deviation
        Then: returns DANGER severity with red indicator
        """
        thresholds = AFRThresholds(cautionDeviation=0.5, dangerDeviation=1.0)
        severity, color = evaluateAFRDeviation(15.8, 14.7, thresholds)
        assert severity == AlertSeverity.DANGER
        assert color == "red"

    def test_evaluateAFR_richDanger_returnsDanger(self):
        """
        Given: AFR deviation rich, exceeding danger threshold
        When: evaluating AFR deviation
        Then: returns DANGER severity with red indicator
        """
        thresholds = AFRThresholds(cautionDeviation=0.5, dangerDeviation=1.0)
        severity, color = evaluateAFRDeviation(13.6, 14.7, thresholds)
        assert severity == AlertSeverity.DANGER
        assert color == "red"

    def test_evaluateAFR_exactAtCautionBoundary_returnsNormal(self):
        """
        Given: AFR deviation exactly at caution boundary
        When: evaluating AFR deviation
        Then: returns NORMAL (strictly greater than triggers caution)
        """
        thresholds = AFRThresholds(cautionDeviation=0.5, dangerDeviation=1.0)
        severity, color = evaluateAFRDeviation(15.2, 14.7, thresholds)
        assert severity == AlertSeverity.NORMAL

    def test_evaluateAFR_exactAtDangerBoundary_returnsCaution(self):
        """
        Given: AFR deviation exactly at danger boundary
        When: evaluating AFR deviation
        Then: returns CAUTION (strictly greater than triggers danger)
        """
        thresholds = AFRThresholds(cautionDeviation=0.5, dangerDeviation=1.0)
        severity, color = evaluateAFRDeviation(15.7, 14.7, thresholds)
        assert severity == AlertSeverity.CAUTION

    def test_evaluateAFR_boostTarget_normalAtTarget(self):
        """
        Given: AFR on target at 11.5 (WOT boost target)
        When: evaluating AFR deviation
        Then: returns NORMAL
        """
        severity, color = evaluateAFRDeviation(11.5, 11.5, AFRThresholds())
        assert severity == AlertSeverity.NORMAL
        assert color == "green"


# ================================================================================
# evaluateInjectorDuty Tests
# ================================================================================


class TestEvaluateInjectorDuty:
    """Tests for injector duty cycle severity evaluation."""

    def test_evaluateInjector_lowDuty_returnsNormal(self):
        """
        Given: Injector duty cycle at 50%
        When: evaluating
        Then: returns NORMAL severity with green indicator
        """
        severity, color = evaluateInjectorDuty(50.0, InjectorDutyThresholds())
        assert severity == AlertSeverity.NORMAL
        assert color == "green"

    def test_evaluateInjector_atCaution_returnsCaution(self):
        """
        Given: Injector duty cycle exceeding caution threshold
        When: evaluating
        Then: returns CAUTION severity with yellow indicator
        """
        thresholds = InjectorDutyThresholds(cautionMin=80.0, dangerMin=85.0)
        severity, color = evaluateInjectorDuty(82.0, thresholds)
        assert severity == AlertSeverity.CAUTION
        assert color == "yellow"

    def test_evaluateInjector_atDanger_returnsDanger(self):
        """
        Given: Injector duty cycle exceeding danger threshold
        When: evaluating
        Then: returns DANGER severity with red indicator
        """
        thresholds = InjectorDutyThresholds(cautionMin=80.0, dangerMin=85.0)
        severity, color = evaluateInjectorDuty(90.0, thresholds)
        assert severity == AlertSeverity.DANGER
        assert color == "red"

    def test_evaluateInjector_exactAtCautionBoundary_returnsNormal(self):
        """
        Given: Injector duty exactly at caution boundary
        When: evaluating
        Then: returns NORMAL (strictly greater than triggers caution)
        """
        thresholds = InjectorDutyThresholds(cautionMin=80.0, dangerMin=85.0)
        severity, color = evaluateInjectorDuty(80.0, thresholds)
        assert severity == AlertSeverity.NORMAL

    def test_evaluateInjector_exactAtDangerBoundary_returnsCaution(self):
        """
        Given: Injector duty exactly at danger boundary
        When: evaluating
        Then: returns CAUTION (strictly greater than triggers danger)
        """
        thresholds = InjectorDutyThresholds(cautionMin=80.0, dangerMin=85.0)
        severity, color = evaluateInjectorDuty(85.0, thresholds)
        assert severity == AlertSeverity.CAUTION

    def test_evaluateInjector_zeroDuty_returnsNormal(self):
        """
        Given: Injector duty at 0% (engine off)
        When: evaluating
        Then: returns NORMAL
        """
        severity, color = evaluateInjectorDuty(0.0, InjectorDutyThresholds())
        assert severity == AlertSeverity.NORMAL
        assert color == "green"


# ================================================================================
# buildAFRInfo Tests
# ================================================================================


class TestBuildAFRInfo:
    """Tests for AFR info construction."""

    def test_buildAFRInfo_normalAFR_greenIndicator(self):
        """
        Given: AFR actual matches target
        When: building AFR info
        Then: returns AFRInfo with NORMAL severity and correct display
        """
        info = buildAFRInfo(14.7, 14.7, AFRThresholds())
        assert info.actual == 14.7
        assert info.target == 14.7
        assert info.deviation == 0.0
        assert info.severity == AlertSeverity.NORMAL
        assert info.indicatorColor == "green"

    def test_buildAFRInfo_leanDeviation_computesCorrectly(self):
        """
        Given: AFR actual lean of target
        When: building AFR info
        Then: deviation is positive (lean direction)
        """
        info = buildAFRInfo(15.2, 14.7, AFRThresholds())
        assert abs(info.deviation - 0.5) < 0.01

    def test_buildAFRInfo_richDeviation_computesCorrectly(self):
        """
        Given: AFR actual rich of target
        When: building AFR info
        Then: deviation is negative (rich direction)
        """
        info = buildAFRInfo(14.2, 14.7, AFRThresholds())
        assert abs(info.deviation - (-0.5)) < 0.01

    def test_buildAFRInfo_displayText_showsActualVsTarget(self):
        """
        Given: AFR values
        When: building AFR info
        Then: displayText shows 'actual / target' format
        """
        info = buildAFRInfo(11.5, 11.5, AFRThresholds())
        assert "11.5" in info.displayText
        assert "/" in info.displayText

    def test_buildAFRInfo_dangerDeviation_redIndicator(self):
        """
        Given: AFR far from target (danger level)
        When: building AFR info
        Then: returns DANGER severity with red indicator
        """
        thresholds = AFRThresholds(cautionDeviation=0.5, dangerDeviation=1.0)
        info = buildAFRInfo(16.0, 14.7, thresholds)
        assert info.severity == AlertSeverity.DANGER
        assert info.indicatorColor == "red"


# ================================================================================
# buildFuelTrimInfo Tests
# ================================================================================


class TestBuildFuelTrimInfo:
    """Tests for fuel trim info construction (STFT and LTFT)."""

    def test_buildFuelTrimInfo_stftNormal_greenIndicator(self):
        """
        Given: STFT at 2% (within normal range)
        When: building fuel trim info for STFT
        Then: returns NORMAL severity with green indicator
        """
        info = buildFuelTrimInfo(2.0, "STFT")
        assert info.value == 2.0
        assert info.label == "STFT"
        assert info.severity == AlertSeverity.NORMAL
        assert info.indicatorColor == "green"

    def test_buildFuelTrimInfo_stftCautionLean_yellowIndicator(self):
        """
        Given: STFT at +8% (positive = lean correction, caution level)
        When: building fuel trim info
        Then: returns CAUTION severity with yellow indicator
        """
        info = buildFuelTrimInfo(8.0, "STFT")
        assert info.severity == AlertSeverity.CAUTION
        assert info.indicatorColor == "yellow"

    def test_buildFuelTrimInfo_stftCautionRich_yellowIndicator(self):
        """
        Given: STFT at -8% (negative = rich correction, caution level)
        When: building fuel trim info
        Then: returns CAUTION severity with yellow indicator
        """
        info = buildFuelTrimInfo(-8.0, "STFT")
        assert info.severity == AlertSeverity.CAUTION
        assert info.indicatorColor == "yellow"

    def test_buildFuelTrimInfo_stftDanger_redIndicator(self):
        """
        Given: STFT at +20% (danger level)
        When: building fuel trim info
        Then: returns DANGER severity with red indicator
        """
        info = buildFuelTrimInfo(20.0, "STFT")
        assert info.severity == AlertSeverity.DANGER
        assert info.indicatorColor == "red"

    def test_buildFuelTrimInfo_ltftNormal_greenIndicator(self):
        """
        Given: LTFT at 3% (within normal range)
        When: building fuel trim info for LTFT
        Then: returns NORMAL severity with green indicator and LTFT label
        """
        info = buildFuelTrimInfo(3.0, "LTFT")
        assert info.value == 3.0
        assert info.label == "LTFT"
        assert info.severity == AlertSeverity.NORMAL
        assert info.indicatorColor == "green"

    def test_buildFuelTrimInfo_ltftCaution_yellowIndicator(self):
        """
        Given: LTFT at -10% (caution level)
        When: building fuel trim info for LTFT
        Then: returns CAUTION severity
        """
        info = buildFuelTrimInfo(-10.0, "LTFT")
        assert info.severity == AlertSeverity.CAUTION
        assert info.indicatorColor == "yellow"

    def test_buildFuelTrimInfo_zeroTrim_normal(self):
        """
        Given: fuel trim at 0% (perfect fueling)
        When: building fuel trim info
        Then: returns NORMAL
        """
        info = buildFuelTrimInfo(0.0, "STFT")
        assert info.severity == AlertSeverity.NORMAL
        assert info.indicatorColor == "green"

    def test_buildFuelTrimInfo_displayText_includesValueAndPercent(self):
        """
        Given: fuel trim value
        When: building fuel trim info
        Then: displayText includes value and percent sign
        """
        info = buildFuelTrimInfo(3.5, "STFT")
        assert "3.5" in info.displayText
        assert "%" in info.displayText


# ================================================================================
# buildInjectorDutyInfo Tests
# ================================================================================


class TestBuildInjectorDutyInfo:
    """Tests for injector duty cycle info construction."""

    def test_buildInjectorDutyInfo_normalDuty_greenIndicator(self):
        """
        Given: Injector duty at 60%
        When: building injector duty info
        Then: returns NORMAL severity with green indicator
        """
        info = buildInjectorDutyInfo(60.0, InjectorDutyThresholds())
        assert info.dutyCyclePercent == 60.0
        assert info.severity == AlertSeverity.NORMAL
        assert info.indicatorColor == "green"

    def test_buildInjectorDutyInfo_cautionDuty_yellowIndicator(self):
        """
        Given: Injector duty at 82%
        When: building injector duty info
        Then: returns CAUTION severity with yellow indicator
        """
        thresholds = InjectorDutyThresholds(cautionMin=80.0, dangerMin=85.0)
        info = buildInjectorDutyInfo(82.0, thresholds)
        assert info.severity == AlertSeverity.CAUTION
        assert info.indicatorColor == "yellow"

    def test_buildInjectorDutyInfo_dangerDuty_redIndicator(self):
        """
        Given: Injector duty at 92%
        When: building injector duty info
        Then: returns DANGER severity with red indicator
        """
        thresholds = InjectorDutyThresholds(cautionMin=80.0, dangerMin=85.0)
        info = buildInjectorDutyInfo(92.0, thresholds)
        assert info.severity == AlertSeverity.DANGER
        assert info.indicatorColor == "red"

    def test_buildInjectorDutyInfo_displayText_includesPercent(self):
        """
        Given: Injector duty value
        When: building injector duty info
        Then: displayText includes value and percent
        """
        info = buildInjectorDutyInfo(65.0, InjectorDutyThresholds())
        assert "65" in info.displayText
        assert "%" in info.displayText


# ================================================================================
# isFuelPageAvailable Tests
# ================================================================================


class TestIsFuelPageAvailable:
    """Tests for fuel page availability based on ECMLink connection."""

    def test_isFuelPageAvailable_connected_returnsTrue(self):
        """
        Given: ECMLink is connected
        When: checking fuel page availability
        Then: returns True
        """
        assert isFuelPageAvailable(ecmlinkConnected=True) is True

    def test_isFuelPageAvailable_disconnected_returnsFalse(self):
        """
        Given: ECMLink is not connected
        When: checking fuel page availability
        Then: returns False
        """
        assert isFuelPageAvailable(ecmlinkConnected=False) is False


# ================================================================================
# buildFuelDetailState Tests
# ================================================================================


class TestBuildFuelDetailState:
    """Tests for complete fuel detail page state construction."""

    def test_buildFuelDetailState_ecmlinkConnected_availableTrue(self):
        """
        Given: ECMLink connected with mock fuel data
        When: building fuel detail state
        Then: state is available with all fields populated
        """
        state = buildFuelDetailState(
            afrActual=14.7,
            afrTarget=14.7,
            stft=2.0,
            ltft=1.0,
            injectorDutyCycle=55.0,
            ethanolContent=30.0,
            ecmlinkConnected=True,
        )

        assert state.available is True
        assert state.ecmlinkConnected is True
        assert state.afrInfo.actual == 14.7
        assert state.stftInfo.value == 2.0
        assert state.ltftInfo.value == 1.0
        assert state.injectorDutyInfo.dutyCyclePercent == 55.0
        assert state.ethanolContentPercent == 30.0

    def test_buildFuelDetailState_ecmlinkDisconnected_availableFalse(self):
        """
        Given: ECMLink not connected
        When: building fuel detail state
        Then: state is not available
        """
        state = buildFuelDetailState(
            afrActual=0.0,
            afrTarget=0.0,
            stft=0.0,
            ltft=0.0,
            injectorDutyCycle=0.0,
            ethanolContent=0.0,
            ecmlinkConnected=False,
        )

        assert state.available is False
        assert state.ecmlinkConnected is False

    def test_buildFuelDetailState_allNormal_greenAcrossBoard(self):
        """
        Given: All fuel parameters within normal range
        When: building fuel detail state
        Then: all indicators are green/NORMAL
        """
        state = buildFuelDetailState(
            afrActual=14.7,
            afrTarget=14.7,
            stft=1.0,
            ltft=2.0,
            injectorDutyCycle=50.0,
            ethanolContent=0.0,
            ecmlinkConnected=True,
        )

        assert state.afrInfo.severity == AlertSeverity.NORMAL
        assert state.stftInfo.severity == AlertSeverity.NORMAL
        assert state.ltftInfo.severity == AlertSeverity.NORMAL
        assert state.injectorDutyInfo.severity == AlertSeverity.NORMAL

    def test_buildFuelDetailState_mixedSeverities_correctPerParameter(self):
        """
        Given: Mix of normal and abnormal fuel parameters
        When: building fuel detail state
        Then: each parameter has its own correct severity
        """
        state = buildFuelDetailState(
            afrActual=16.0,
            afrTarget=14.7,
            stft=2.0,
            ltft=-10.0,
            injectorDutyCycle=82.0,
            ethanolContent=85.0,
            ecmlinkConnected=True,
        )

        assert state.afrInfo.severity == AlertSeverity.DANGER
        assert state.stftInfo.severity == AlertSeverity.NORMAL
        assert state.ltftInfo.severity == AlertSeverity.CAUTION
        assert state.injectorDutyInfo.severity == AlertSeverity.CAUTION

    def test_buildFuelDetailState_ethanolContentDisplay_showsPercent(self):
        """
        Given: Ethanol content at 85%
        When: building fuel detail state
        Then: ethanol display text shows percentage
        """
        state = buildFuelDetailState(
            afrActual=11.5,
            afrTarget=11.5,
            stft=0.0,
            ltft=0.0,
            injectorDutyCycle=70.0,
            ethanolContent=85.0,
            ecmlinkConnected=True,
        )

        assert "85" in state.ethanolDisplayText
        assert "%" in state.ethanolDisplayText

    def test_buildFuelDetailState_ethanolZero_displaysZero(self):
        """
        Given: No ethanol content (gasoline only)
        When: building fuel detail state
        Then: ethanol display shows 0%
        """
        state = buildFuelDetailState(
            afrActual=14.7,
            afrTarget=14.7,
            stft=0.0,
            ltft=0.0,
            injectorDutyCycle=50.0,
            ethanolContent=0.0,
            ecmlinkConnected=True,
        )

        assert "0" in state.ethanolDisplayText

    def test_buildFuelDetailState_customThresholds_applied(self):
        """
        Given: Custom AFR and injector thresholds
        When: building fuel detail state with values at custom boundaries
        Then: severity reflects custom thresholds, not defaults
        """
        afrThresholds = AFRThresholds(cautionDeviation=0.3, dangerDeviation=0.6)
        injectorThresholds = InjectorDutyThresholds(cautionMin=70.0, dangerMin=80.0)

        state = buildFuelDetailState(
            afrActual=15.0,
            afrTarget=14.7,
            stft=0.0,
            ltft=0.0,
            injectorDutyCycle=75.0,
            ethanolContent=0.0,
            ecmlinkConnected=True,
            afrThresholds=afrThresholds,
            injectorThresholds=injectorThresholds,
        )

        assert state.afrInfo.severity == AlertSeverity.CAUTION
        assert state.injectorDutyInfo.severity == AlertSeverity.CAUTION

    def test_buildFuelDetailState_stftLabelsCorrect(self):
        """
        Given: Fuel detail state with both STFT and LTFT
        When: checking labels
        Then: STFT info has 'STFT' label, LTFT info has 'LTFT' label
        """
        state = buildFuelDetailState(
            afrActual=14.7,
            afrTarget=14.7,
            stft=1.0,
            ltft=-1.0,
            injectorDutyCycle=50.0,
            ethanolContent=0.0,
            ecmlinkConnected=True,
        )

        assert state.stftInfo.label == "STFT"
        assert state.ltftInfo.label == "LTFT"

    def test_buildFuelDetailState_boostAFR_normalRange(self):
        """
        Given: AFR values typical for WOT/boost (11.5 target)
        When: building fuel detail state
        Then: on-target AFR shows NORMAL
        """
        state = buildFuelDetailState(
            afrActual=11.5,
            afrTarget=11.5,
            stft=0.0,
            ltft=0.0,
            injectorDutyCycle=75.0,
            ethanolContent=85.0,
            ecmlinkConnected=True,
        )

        assert state.afrInfo.severity == AlertSeverity.NORMAL
        assert state.afrInfo.indicatorColor == "green"

    def test_buildFuelDetailState_highInjectorDuty_redIndicator(self):
        """
        Given: Injector duty at 92% (danger level)
        When: building fuel detail state
        Then: injector shows DANGER/red
        """
        state = buildFuelDetailState(
            afrActual=11.5,
            afrTarget=11.5,
            stft=0.0,
            ltft=0.0,
            injectorDutyCycle=92.0,
            ethanolContent=0.0,
            ecmlinkConnected=True,
        )

        assert state.injectorDutyInfo.severity == AlertSeverity.DANGER
        assert state.injectorDutyInfo.indicatorColor == "red"


# ================================================================================
# AFRInfo Dataclass Tests
# ================================================================================


class TestAFRInfo:
    """Tests for AFRInfo dataclass fields."""

    def test_afrInfo_fieldsPopulated(self):
        """
        Given: AFRInfo with all fields
        When: accessing fields
        Then: all values are correct
        """
        info = AFRInfo(
            actual=14.7,
            target=14.7,
            deviation=0.0,
            severity=AlertSeverity.NORMAL,
            indicatorColor="green",
            displayText="14.7 / 14.7",
        )

        assert info.actual == 14.7
        assert info.target == 14.7
        assert info.deviation == 0.0
        assert info.severity == AlertSeverity.NORMAL
        assert info.indicatorColor == "green"
        assert info.displayText == "14.7 / 14.7"


# ================================================================================
# FuelTrimInfo Dataclass Tests
# ================================================================================


class TestFuelTrimInfo:
    """Tests for FuelTrimInfo dataclass fields."""

    def test_fuelTrimInfo_fieldsPopulated(self):
        """
        Given: FuelTrimInfo with all fields
        When: accessing fields
        Then: all values are correct
        """
        info = FuelTrimInfo(
            value=3.5,
            label="STFT",
            severity=AlertSeverity.NORMAL,
            indicatorColor="green",
            displayText="+3.5%",
        )

        assert info.value == 3.5
        assert info.label == "STFT"
        assert info.severity == AlertSeverity.NORMAL
        assert info.indicatorColor == "green"
        assert info.displayText == "+3.5%"


# ================================================================================
# InjectorDutyInfo Dataclass Tests
# ================================================================================


class TestInjectorDutyInfo:
    """Tests for InjectorDutyInfo dataclass fields."""

    def test_injectorDutyInfo_fieldsPopulated(self):
        """
        Given: InjectorDutyInfo with all fields
        When: accessing fields
        Then: all values are correct
        """
        info = InjectorDutyInfo(
            dutyCyclePercent=65.0,
            severity=AlertSeverity.NORMAL,
            indicatorColor="green",
            displayText="65%",
        )

        assert info.dutyCyclePercent == 65.0
        assert info.severity == AlertSeverity.NORMAL
        assert info.indicatorColor == "green"
        assert info.displayText == "65%"


# ================================================================================
# FuelDetailState Dataclass Tests
# ================================================================================


class TestFuelDetailState:
    """Tests for FuelDetailState dataclass fields."""

    def test_fuelDetailState_allFieldsAccessible(self):
        """
        Given: FuelDetailState with all sub-dataclasses
        When: accessing nested fields
        Then: all values are correct
        """
        afr = AFRInfo(
            actual=14.7,
            target=14.7,
            deviation=0.0,
            severity=AlertSeverity.NORMAL,
            indicatorColor="green",
            displayText="14.7 / 14.7",
        )
        stft = FuelTrimInfo(
            value=0.0,
            label="STFT",
            severity=AlertSeverity.NORMAL,
            indicatorColor="green",
            displayText="+0%",
        )
        ltft = FuelTrimInfo(
            value=0.0,
            label="LTFT",
            severity=AlertSeverity.NORMAL,
            indicatorColor="green",
            displayText="+0%",
        )
        injector = InjectorDutyInfo(
            dutyCyclePercent=50.0,
            severity=AlertSeverity.NORMAL,
            indicatorColor="green",
            displayText="50%",
        )

        state = FuelDetailState(
            afrInfo=afr,
            stftInfo=stft,
            ltftInfo=ltft,
            injectorDutyInfo=injector,
            ethanolContentPercent=30.0,
            ethanolDisplayText="30%",
            ecmlinkConnected=True,
            available=True,
        )

        assert state.afrInfo.actual == 14.7
        assert state.stftInfo.label == "STFT"
        assert state.ltftInfo.label == "LTFT"
        assert state.injectorDutyInfo.dutyCyclePercent == 50.0
        assert state.ethanolContentPercent == 30.0
        assert state.ecmlinkConnected is True
        assert state.available is True
