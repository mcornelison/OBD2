################################################################################
# File Name: test_gear_derivation.py
# Purpose/Description: Tests for the US-630 GEAR derivation (F-138). The car
#                      exposes no gear PID, so gear is DERIVED from realtime
#                      SPEED + RPM. These tests pin the positive case (ratio
#                      inside a measured band) and -- the branch that matters --
#                      every NEGATIVE case: absent, stale, uncalibrated, below
#                      threshold, no band match, and ambiguous. A wrong gear is
#                      worse than no gear.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Rex (US-630) | Initial -- derivation guards, debounce, and the
#               |              | grounded F5M33 band formula cross-checks.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.obdii.gear_derivation`.

The derivation is a pure function of (SPEED, RPM, bands, clock) so it is
tested directly, with no bus and no state file.  The band table is
INJECTED -- these tests never assert a gear against a band table the
module invented for itself.
"""

from __future__ import annotations

import pytest

from src.pi.obdii import gear_derivation as gd

# A deliberately simple, non-overlapping band table for the guard tests, so a
# guard failure can never be confused with a band-table question. Units are
# rpm per km/h, which is what the derivation computes.
_BANDS = (
    gd.GearBand(gear=1, ratioMin=90.0, ratioMax=125.0),
    gd.GearBand(gear=2, ratioMin=54.0, ratioMax=74.0),
    gd.GearBand(gear=3, ratioMin=36.0, ratioMax=49.0),
)

# Inside band 3 (42.4 rpm/kph): the drive-18 cross-check point.
_SPEED_IN_3RD = 92.8
_RPM_IN_3RD = 3937.0


def _deriver(bands=_BANDS, **kwargs):
    """A deriver with the guard-test band table unless told otherwise."""
    return gd.GearDeriver(bands=bands, **kwargs)


def _settled(deriver, speedKph, rpm, startS=100.0):
    """Drive one steady operating point past the debounce and return the result.

    Feeds the same point twice, separated by more than the debounce window, so
    the caller gets the deriver's SETTLED opinion rather than its first-sample
    one.
    """
    deriver.update(
        speed=gd.Reading(speedKph, startS), rpm=gd.Reading(rpm, startS), nowS=startS
    )
    later = startS + gd.DEFAULT_DEBOUNCE_S + 0.1
    return deriver.update(
        speed=gd.Reading(speedKph, later), rpm=gd.Reading(rpm, later), nowS=later
    )


class TestPositiveCase:
    """The end state: a live, in-band ratio resolves to that gear."""

    def test_update_ratioInsideBand_returnsThatGear(self):
        """
        Given: SPEED and RPM are both live and their ratio sits inside band 3
        When:  the point has been stable longer than the debounce
        Then:  the reading is available and reports gear 3
        """
        result = _settled(_deriver(), _SPEED_IN_3RD, _RPM_IN_3RD)

        assert result.available is True
        assert result.gear == 3

    def test_update_ratioInsideBand_carriesNoAbsenceReason(self):
        """
        Given: a resolved gear
        When:  the reading is inspected
        Then:  it carries the engaged reason, not an absence reason
        """
        result = _settled(_deriver(), _SPEED_IN_3RD, _RPM_IN_3RD)

        assert result.reason == gd.REASON_ENGAGED

    def test_toStateDict_resolvedGear_matchesCarouselContract(self):
        """
        Given: a resolved gear
        When:  it is serialised for states/gear
        Then:  it carries exactly the keys carousel.js gearView() reads
        """
        result = _settled(_deriver(), _SPEED_IN_3RD, _RPM_IN_3RD)

        assert result.toStateDict() == {
            "available": True,
            "gear": 3,
            "reason": gd.REASON_ENGAGED,
        }


class TestTypedAbsence:
    """Every branch that must NOT produce a gear, each with its own reason."""

    def test_update_absentSpeed_returnsTypedNaWithNoDataReason(self):
        """
        Given: RPM is live but SPEED is absent
        When:  the deriver is updated
        Then:  the reading is unavailable with the no-data reason
        """
        result = _deriver().update(
            speed=None, rpm=gd.Reading(_RPM_IN_3RD, 100.0), nowS=100.0
        )

        assert result.available is False
        assert result.gear is None
        assert result.reason == gd.REASON_NO_DATA

    def test_update_absentRpm_returnsTypedNaWithNoDataReason(self):
        """
        Given: SPEED is live but RPM is absent
        When:  the deriver is updated
        Then:  the reading is unavailable with the no-data reason
        """
        result = _deriver().update(
            speed=gd.Reading(_SPEED_IN_3RD, 100.0), rpm=None, nowS=100.0
        )

        assert result.available is False
        assert result.reason == gd.REASON_NO_DATA

    def test_update_staleSpeed_returnsTypedNaWithStaleReason(self):
        """
        Given: SPEED last arrived longer ago than the freshness window
        When:  the deriver is updated
        Then:  the reading is unavailable and says STALE, not no-data

        Stale and absent are different facts: one says the pipe is dead, the
        other says the pipe never carried this reading.
        """
        nowS = 100.0
        stale = nowS - gd.DEFAULT_MAX_AGE_S - 0.1
        result = _deriver().update(
            speed=gd.Reading(_SPEED_IN_3RD, stale),
            rpm=gd.Reading(_RPM_IN_3RD, nowS),
            nowS=nowS,
        )

        assert result.available is False
        assert result.reason == gd.REASON_STALE

    def test_update_staleRpm_returnsTypedNaWithStaleReason(self):
        """
        Given: RPM last arrived longer ago than the freshness window
        When:  the deriver is updated
        Then:  the reading is unavailable and says STALE
        """
        nowS = 100.0
        stale = nowS - gd.DEFAULT_MAX_AGE_S - 0.1
        result = _deriver().update(
            speed=gd.Reading(_SPEED_IN_3RD, nowS),
            rpm=gd.Reading(_RPM_IN_3RD, stale),
            nowS=nowS,
        )

        assert result.available is False
        assert result.reason == gd.REASON_STALE

    def test_update_noBandsConfigured_returnsTypedNaNotCalibrated(self):
        """
        Given: no band table has been supplied (ship-dark default)
        When:  a perfectly good SPEED/RPM pair arrives
        Then:  the reading is unavailable and says it is not calibrated

        This is the shipped default until the measured bands land. It must
        never fall back to a guess.
        """
        result = _settled(_deriver(bands=()), _SPEED_IN_3RD, _RPM_IN_3RD)

        assert result.available is False
        assert result.reason == gd.REASON_NOT_CALIBRATED

    def test_update_speedBelowThreshold_returnsTypedNaBelowThreshold(self):
        """
        Given: the car is below the 5 km/h floor Spool set
        When:  the deriver is updated
        Then:  the reading is unavailable with the below-threshold reason

        Below the floor the ratio is dominated by measurement noise and the
        clutch is usually slipping; there is no gear fact to report.
        """
        result = _settled(_deriver(), gd.DEFAULT_MIN_SPEED_KPH - 0.1, 1500.0)

        assert result.available is False
        assert result.reason == gd.REASON_BELOW_THRESHOLD

    def test_update_rpmBelowThreshold_returnsTypedNaBelowThreshold(self):
        """
        Given: RPM is below the 900 floor Spool set
        When:  the deriver is updated
        Then:  the reading is unavailable with the below-threshold reason
        """
        result = _settled(_deriver(), 40.0, gd.DEFAULT_MIN_RPM - 1.0)

        assert result.available is False
        assert result.reason == gd.REASON_BELOW_THRESHOLD

    def test_update_zeroSpeed_returnsTypedNaAndNeverDividesByZero(self):
        """
        Given: the car is stopped with the engine running
        When:  the deriver is updated
        Then:  it reports typed NA rather than raising on the ratio division
        """
        result = _settled(_deriver(), 0.0, 1500.0)

        assert result.available is False
        assert result.reason == gd.REASON_BELOW_THRESHOLD

    def test_update_ratioMatchesNoBand_returnsTypedNaNoBandMatch(self):
        """
        Given: the ratio falls between two bands (clutch in, or coasting)
        When:  the deriver is updated
        Then:  the reading is unavailable and says no band matched

        Clutch-in and coasting LEGITIMATELY match no band. That is a real
        operating state, not an error, and it must not be rounded to the
        nearest gear.
        """
        # 80 rpm/kph sits in the gap between band 2 (max 74) and band 1 (min 90).
        result = _settled(_deriver(), 50.0, 50.0 * 80.0)

        assert result.available is False
        assert result.reason == gd.REASON_NO_BAND

    def test_update_ratioMatchesTwoBands_returnsTypedNaAmbiguous(self):
        """
        Given: overlapping bands, and a ratio inside both
        When:  the deriver is updated
        Then:  the reading is unavailable and says ambiguous

        Atlas's conditionalOutcome, made executable: if a ratio is ambiguous
        between two gears the honest outcome is NA.
        """
        overlapping = (
            gd.GearBand(gear=4, ratioMin=26.0, ratioMax=36.0),
            gd.GearBand(gear=5, ratioMin=22.0, ratioMax=30.0),
        )
        # 28 rpm/kph is inside BOTH bands.
        result = _settled(_deriver(bands=overlapping), 50.0, 50.0 * 28.0)

        assert result.available is False
        assert result.reason == gd.REASON_AMBIGUOUS

    def test_update_ambiguousRatio_doesNotPickTheNearestGear(self):
        """
        Given: a ratio ambiguous between two gears, but closer to one of them
        When:  the deriver is updated
        Then:  it still refuses -- proximity is not a tie-breaker
        """
        overlapping = (
            gd.GearBand(gear=4, ratioMin=26.0, ratioMax=36.0),
            gd.GearBand(gear=5, ratioMin=22.0, ratioMax=30.0),
        )
        # 29.5 is barely inside band 5 but comfortably inside band 4.
        result = _settled(_deriver(bands=overlapping), 50.0, 50.0 * 29.5)

        assert result.gear is None


class TestNeverHoldsAPreviousValue:
    """The AC that the punch list exists to enforce."""

    def test_update_engagedThenInputsGoAbsent_dropsTheGearImmediately(self):
        """
        Given: a settled gear 3
        When:  SPEED and RPM stop arriving
        Then:  the very next reading is typed NA, not a held 3

        No grace, no last-known-good. A held gear is a fabricated reading of
        a pipe that has gone quiet.
        """
        deriver = _deriver()
        settled = _settled(deriver, _SPEED_IN_3RD, _RPM_IN_3RD)
        assert settled.gear == 3  # precondition, not the assertion under test

        result = deriver.update(speed=None, rpm=None, nowS=200.0)

        assert result.available is False
        assert result.gear is None

    def test_update_engagedThenInputsGoStale_dropsTheGearImmediately(self):
        """
        Given: a settled gear 3
        When:  the readings stop being refreshed and go stale
        Then:  the reading is typed NA with the stale reason, not a held 3
        """
        deriver = _deriver()
        _settled(deriver, _SPEED_IN_3RD, _RPM_IN_3RD)

        nowS = 500.0
        stale = nowS - gd.DEFAULT_MAX_AGE_S - 0.1
        result = deriver.update(
            speed=gd.Reading(_SPEED_IN_3RD, stale),
            rpm=gd.Reading(_RPM_IN_3RD, stale),
            nowS=nowS,
        )

        assert result.gear is None
        assert result.reason == gd.REASON_STALE

    def test_update_engagedThenRatioLeavesEveryBand_dropsTheGearImmediately(self):
        """
        Given: a settled gear 3
        When:  the clutch goes in and the ratio leaves every band
        Then:  the reading drops to typed NA rather than holding 3 through the shift
        """
        deriver = _deriver()
        _settled(deriver, _SPEED_IN_3RD, _RPM_IN_3RD)

        nowS = 200.0
        result = deriver.update(
            speed=gd.Reading(50.0, nowS), rpm=gd.Reading(50.0 * 80.0, nowS), nowS=nowS
        )

        assert result.available is False
        assert result.reason == gd.REASON_NO_BAND


class TestDebounce:
    """Spool's >= 2 s debounce: a gear must prove itself before it is published."""

    def test_update_firstSampleOfAGear_isNotYetPublished(self):
        """
        Given: a fresh deriver
        When:  the first in-band sample arrives
        Then:  no gear is published yet -- it reports that it is settling
        """
        deriver = _deriver()

        result = deriver.update(
            speed=gd.Reading(_SPEED_IN_3RD, 100.0),
            rpm=gd.Reading(_RPM_IN_3RD, 100.0),
            nowS=100.0,
        )

        assert result.available is False
        assert result.reason == gd.REASON_SETTLING

    def test_update_gearStableForLessThanDebounce_isNotYetPublished(self):
        """
        Given: an in-band gear held for less than the debounce window
        When:  the deriver is updated
        Then:  the gear is still not published
        """
        deriver = _deriver()
        deriver.update(
            speed=gd.Reading(_SPEED_IN_3RD, 100.0),
            rpm=gd.Reading(_RPM_IN_3RD, 100.0),
            nowS=100.0,
        )

        justShort = 100.0 + gd.DEFAULT_DEBOUNCE_S - 0.1
        result = deriver.update(
            speed=gd.Reading(_SPEED_IN_3RD, justShort),
            rpm=gd.Reading(_RPM_IN_3RD, justShort),
            nowS=justShort,
        )

        assert result.available is False
        assert result.reason == gd.REASON_SETTLING

    def test_update_shiftToANewGear_requiresTheDebounceAgain(self):
        """
        Given: a settled gear 3
        When:  the ratio moves cleanly into band 2 and the debounce has NOT elapsed
        Then:  neither the old gear nor the new one is published

        The old gear must not survive the shift, and the new one must not be
        published before it has proved itself.
        """
        deriver = _deriver()
        _settled(deriver, _SPEED_IN_3RD, _RPM_IN_3RD)

        nowS = 200.0
        result = deriver.update(
            speed=gd.Reading(50.0, nowS), rpm=gd.Reading(50.0 * 63.9, nowS), nowS=nowS
        )

        assert result.gear is None
        assert result.reason == gd.REASON_SETTLING

    def test_update_shiftToANewGearHeldPastDebounce_publishesTheNewGear(self):
        """
        Given: a settled gear 3, then a clean move into band 2
        When:  the new ratio is held past the debounce window
        Then:  gear 2 is published
        """
        deriver = _deriver()
        _settled(deriver, _SPEED_IN_3RD, _RPM_IN_3RD)

        result = _settled(deriver, 50.0, 50.0 * 63.9, startS=200.0)

        assert result.available is True
        assert result.gear == 2


class TestGroundedBandFormula:
    """The band formula reproduces Spool's own two cross-checks.

    PM Rule 7: the ratios and the tyre circumference come from
    specs/grounded-knowledge.md (Road Race Engineering factory Shop Manual CD
    + Spool cross-check). These tests prove the module's arithmetic agrees
    with the two independent figures Spool published, so the formula cannot
    drift silently.
    """

    def test_rpmPerKph_fifthGear_reproducesSpoolsTwentyFourMphPerThousandRpm(self):
        """
        Given: the grounded F5M33 5th ratio, final drive and tyre circumference
        When:  1000 rpm is converted to road speed in 5th
        Then:  it lands on Spool's published ~24 mph/1000 rpm
        """
        rpmPerKph = gd.rpmPerKph(
            gearRatio=gd.F5M33_GEAR_RATIOS[5],
            finalDrive=gd.F5M33_FINAL_DRIVE,
            tireCircumferenceM=gd.TIRE_CIRCUMFERENCE_M,
        )
        mph = (1000.0 / rpmPerKph) * gd.MPH_PER_KPH

        assert mph == pytest.approx(24.0, abs=0.5)

    def test_rpmPerKph_thirdGear_reproducesSpoolsDrive18CrossCheck(self):
        """
        Given: the grounded 3rd-gear ratio
        When:  drive 18's 3937 rpm is converted to road speed
        Then:  it lands on Spool's published 57.6 mph computed figure
        """
        rpmPerKph = gd.rpmPerKph(
            gearRatio=gd.F5M33_GEAR_RATIOS[3],
            finalDrive=gd.F5M33_FINAL_DRIVE,
            tireCircumferenceM=gd.TIRE_CIRCUMFERENCE_M,
        )
        mph = (3937.0 / rpmPerKph) * gd.MPH_PER_KPH

        assert mph == pytest.approx(57.6, abs=0.3)

    def test_bandsFromGearRatios_buildsOneBandPerSuppliedRatio(self):
        """
        Given: the grounded five-speed ratio table
        When:  bands are built from it
        Then:  there is exactly one band per gear
        """
        bands = gd.bandsFromGearRatios(
            gearRatios=gd.F5M33_GEAR_RATIOS,
            finalDrive=gd.F5M33_FINAL_DRIVE,
            tireCircumferenceM=gd.TIRE_CIRCUMFERENCE_M,
            tolerancePct=15.0,
        )

        assert sorted(band.gear for band in bands) == [1, 2, 3, 4, 5]

    def test_bandsFromGearRatios_atSpoolsFifteenPercent_overlapFourthAndFifth(self):
        """
        Given: the grounded ratios at Spool's +/-15% tolerance
        When:  the resulting bands are checked for overlap
        Then:  4th and 5th overlap -- a REAL, structural ambiguity, not a hypothetical

        This is a finding, pinned so it cannot be forgotten: at 15% the
        derivation cannot separate 4th from 5th between ~26.3 and ~29.7
        rpm/kph, which is ordinary highway cruising. The tolerance is a
        calibration input and this test exists to make that consequence
        visible whenever it is changed.
        """
        bands = gd.bandsFromGearRatios(
            gearRatios=gd.F5M33_GEAR_RATIOS,
            finalDrive=gd.F5M33_FINAL_DRIVE,
            tireCircumferenceM=gd.TIRE_CIRCUMFERENCE_M,
            tolerancePct=15.0,
        )
        byGear = {band.gear: band for band in bands}

        assert byGear[4].ratioMin < byGear[5].ratioMax


class TestConfigFactory:
    """Ship dark: nothing is built until the CIO wires it on."""

    def test_createGearDeriverFromConfig_disabled_returnsNone(self):
        """
        Given: pi.gear.enabled is absent (the shipped default)
        When:  the factory runs
        Then:  no deriver is built
        """
        assert gd.createGearDeriverFromConfig({"pi": {}}) is None

    def test_createGearDeriverFromConfig_enabledWithoutBands_buildsAnUncalibratedDeriver(
        self,
    ):
        """
        Given: pi.gear.enabled is true but no measured bands are configured
        When:  the factory runs
        Then:  a deriver is built, and it reports not-calibrated rather than guessing
        """
        deriver = gd.createGearDeriverFromConfig({"pi": {"gear": {"enabled": True}}})

        assert deriver is not None
        result = _settled(deriver, _SPEED_IN_3RD, _RPM_IN_3RD)
        assert result.reason == gd.REASON_NOT_CALIBRATED

    def test_createGearDeriverFromConfig_withConfiguredBands_usesThem(self):
        """
        Given: pi.gear.enabled with an explicit measured band table
        When:  a ratio inside one of those bands is fed in
        Then:  the configured band resolves the gear
        """
        config = {
            "pi": {
                "gear": {
                    "enabled": True,
                    "bands": [{"gear": 3, "ratioMin": 36.0, "ratioMax": 49.0}],
                }
            }
        }
        deriver = gd.createGearDeriverFromConfig(config)

        result = _settled(deriver, _SPEED_IN_3RD, _RPM_IN_3RD)

        assert result.gear == 3
