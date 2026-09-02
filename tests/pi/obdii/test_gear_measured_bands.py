################################################################################
# File Name: test_gear_measured_bands.py
# Purpose/Description: US-630 -- Atlas's MEASURED gear bands, published
#   2026-08-31, pinned as the live calibration. The derivation landed last
#   iteration with an EMPTY band table because the numbers existed only as the
#   punch list's assertion that they existed (BL-us630). They now exist, so this
#   file pins them where the Pi actually reads them: config.json, through the
#   validator, through createGearDeriverFromConfig, to a resolved gear.
#
#   THE EDGE SEMANTICS ARE THE DEFECT THIS FILE EXISTS TO CATCH. Atlas published
#   the bands as CONTIGUOUS with "low INCLUSIVE, high EXCLUSIVE" -- 5th ends at
#   29.5 and 4th begins at 29.5. GearBand.contains() shipped as
#   `ratioMin <= ratio <= ratioMax`, inclusive at BOTH ends, so every one of the
#   four shared edges matched TWO bands and the derivation reported `ambiguous`.
#   Nothing caught it: the previous file's guard bands were deliberately
#   separated by gaps, so no test in this repository had ever fed a ratio that
#   two bands could claim. The table is only safe to ship once the edges are.
#
#   The numbers here are TRANSCRIBED from the story's acceptance line, not
#   recomputed. If they ever disagree with sprint.json / backlog.json, that
#   record wins and this file is wrong (PM Rule 7).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Rex (US-630) | Initial -- the measured table, its half-open
#               |              | edges, and its path from config.json to a gear.
# ================================================================================
################################################################################

"""US-630: the measured drives-50/51 band table, from config.json to a gear."""

from __future__ import annotations

import json
import os

import pytest

from common.config.validator import ConfigValidator
from pi.obdii import gear_derivation as gd

_REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
CONFIG_PATH = os.path.join(_REPO, "config.json")

# ---------------------------------------------------------------------------
# Atlas's published table, verbatim (rpm per km/h; low inclusive, high
# exclusive; 1571 paired samples across drives 50 and 51).
#
#   gear   low     high     n     median   p05     p95
#   5th     0.0     29.5   292     27.0    25.3    27.4
#   4th    29.5     37.8   301     32.3    31.7    33.3
#   3rd    37.8     54.3   636     44.3    43.3    45.1
#   2nd    54.3     86.7   264     66.5    61.8    68.5
#   1st    86.7    999.0    78    113.0    97.6   116.7
#
# Band EDGES are DERIVED (geometric midpoints between adjacent medians) and are
# labelled as derived by Atlas, not presented as measured gaps. The medians and
# percentiles are the measurements.
# ---------------------------------------------------------------------------
MEASURED_BANDS = (
    {"gear": 5, "ratioMin": 0.0, "ratioMax": 29.5},
    {"gear": 4, "ratioMin": 29.5, "ratioMax": 37.8},
    {"gear": 3, "ratioMin": 37.8, "ratioMax": 54.3},
    {"gear": 2, "ratioMin": 54.3, "ratioMax": 86.7},
    {"gear": 1, "ratioMin": 86.7, "ratioMax": 999.0},
)

# gear -> (median, p05, p95). Every one of these is a REAL OBSERVED ratio, so
# every one of them must resolve to its own gear and nothing else.
MEASURED_OBSERVATIONS = {
    5: (27.0, 25.3, 27.4),
    4: (32.3, 31.7, 33.3),
    3: (44.3, 43.3, 45.1),
    2: (66.5, 61.8, 68.5),
    1: (113.0, 97.6, 116.7),
}

# The four ratios where two published bands meet. Under "low inclusive, high
# exclusive" each belongs to the band it OPENS -- the lower gear number.
SHARED_EDGES = ((29.5, 4), (37.8, 3), (54.3, 2), (86.7, 1))

_CONFIGURED_BANDS = tuple(
    gd.GearBand(gear=b["gear"], ratioMin=b["ratioMin"], ratioMax=b["ratioMax"])
    for b in MEASURED_BANDS
)


def _settledAtRatio(ratio: float, bands=_CONFIGURED_BANDS):
    """Hold one steady ratio past the debounce and return the settled opinion.

    Speed is fixed well above the 5 km/h floor and RPM derived from it, so the
    point under test is the RATIO -- never an accidental threshold trip.
    """
    speedKph = 60.0
    rpm = ratio * speedKph
    assert rpm >= gd.DEFAULT_MIN_RPM, "test point must clear the rpm floor"
    deriver = gd.GearDeriver(bands=bands)
    deriver.update(
        speed=gd.Reading(speedKph, 100.0), rpm=gd.Reading(rpm, 100.0), nowS=100.0
    )
    later = 100.0 + gd.DEFAULT_DEBOUNCE_S + 0.1
    return deriver.update(
        speed=gd.Reading(speedKph, later), rpm=gd.Reading(rpm, later), nowS=later
    )


def _validatedConfig() -> dict:
    """The shipped config.json, through the real validator."""
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        raw = json.load(fh)
    return ConfigValidator().validate(raw)


# ---------------------------------------------------------------------------
# The table is ON THE PI, not just in the ticket. BL-us630 was filed precisely
# because a band table that exists only as prose is not a calibration.
# ---------------------------------------------------------------------------


class TestTheTableIsShipped:
    """config.json carries the measured table, and the gate is open."""

    def test_configJson_carriesEveryMeasuredBand_verbatim(self):
        """
        Given: Atlas's published drives-50/51 table
        When:  config.json's pi.gear.bands is read
        Then:  it is that table, gear for gear and edge for edge
        """
        bands = _validatedConfig()["pi"]["gear"]["bands"]

        assert [
            {
                "gear": b["gear"],
                "ratioMin": float(b["ratioMin"]),
                "ratioMax": float(b["ratioMax"]),
            }
            for b in bands
        ] == list(MEASURED_BANDS)

    def test_configJson_enablesTheDerivation_soTheTileCanResolve(self):
        """
        Given: the bands are now recorded
        When:  pi.gear.enabled is read
        Then:  it is on -- the story's END STATE needs a producer that runs
        """
        assert _validatedConfig()["pi"]["gear"]["enabled"] is True

    def test_createGearDeriverFromConfig_shippedConfig_carriesTheMeasuredBands(self):
        """
        Given: the shipped config.json
        When:  the production factory builds the deriver
        Then:  it holds the five measured bands, not an empty table
        """
        deriver = gd.createGearDeriverFromConfig(_validatedConfig())

        assert deriver is not None
        assert deriver._bands == _CONFIGURED_BANDS

    def test_defaults_stillShipDark_soAnUnkeyedDeploymentCannotGuess(self):
        """
        Given: a config that never mentions pi.gear at all
        When:  the factory is asked for a deriver
        Then:  there is none -- the numbers live in config.json, not the defaults

        The measured table is a property of THIS car. A validator default
        carrying it would hand it to any deployment that forgot the key.
        """
        assert gd.createGearDeriverFromConfig({"pi": {}}) is None


# ---------------------------------------------------------------------------
# THE EDGES. Atlas's bands are contiguous, so an inclusive upper bound makes
# every shared edge ambiguous and the tile blanks at exactly the ratios a shift
# passes through.
# ---------------------------------------------------------------------------


class TestHalfOpenBands:
    """Low inclusive, high exclusive -- as published."""

    @pytest.mark.parametrize(("ratio", "gear"), SHARED_EDGES)
    def test_sharedEdge_resolvesToTheBandItOpens_notAmbiguous(self, ratio, gear):
        """
        Given: a ratio exactly on the boundary between two published bands
        When:  the derivation settles on it
        Then:  it reports the gear whose band STARTS there, not an absence
        """
        result = _settledAtRatio(ratio)

        assert result.reason != gd.REASON_AMBIGUOUS
        assert result.available is True
        assert result.gear == gear

    def test_contains_upperBound_isExclusive(self):
        """
        Given: a single band
        When:  its own upper bound is tested for membership
        Then:  it is OUTSIDE -- that value belongs to the next band up
        """
        band = gd.GearBand(gear=5, ratioMin=0.0, ratioMax=29.5)

        assert band.contains(29.5) is False

    def test_contains_lowerBound_isInclusive(self):
        """
        Given: a single band
        When:  its own lower bound is tested for membership
        Then:  it is INSIDE -- a half-open band must still own one of its edges

        Held beside the exclusive-upper test so a mutation that flips BOTH ends
        (making the bands right-open instead of left-open) cannot pass by
        symmetry: it would leave 0.0 unclaimed and open a hole at rest.
        """
        band = gd.GearBand(gear=5, ratioMin=0.0, ratioMax=29.5)

        assert band.contains(0.0) is True

    def test_noPublishedRatio_isClaimedByTwoBands(self):
        """
        Given: the full published table
        When:  the whole covered ratio range is swept at 0.1 rpm/kph
        Then:  no ratio anywhere matches more than one band

        A sweep rather than four spot checks: the edges are the KNOWN overlap,
        and this is what would catch an unknown one introduced by a future
        re-measurement.
        """
        overlaps = []
        step = 0
        while step <= 9990:
            ratio = step / 10.0
            matches = [b.gear for b in _CONFIGURED_BANDS if b.contains(ratio)]
            if len(matches) > 1:
                overlaps.append((ratio, matches))
            step += 1

        assert overlaps == []


# ---------------------------------------------------------------------------
# THE MEASUREMENTS THEMSELVES. Every observed statistic Atlas published must
# land in its own gear -- otherwise the table does not describe its own data.
# ---------------------------------------------------------------------------


class TestEveryMeasuredObservationResolves:
    """The medians and the 5th/95th percentiles, gear by gear."""

    @pytest.mark.parametrize(
        ("gear", "ratio"),
        [
            (gear, ratio)
            for gear, stats in MEASURED_OBSERVATIONS.items()
            for ratio in stats
        ],
    )
    def test_measuredObservation_resolvesToItsOwnGear(self, gear, ratio):
        """
        Given: a ratio Atlas actually measured in a known gear
        When:  the derivation settles on it
        Then:  it reports that gear
        """
        result = _settledAtRatio(ratio)

        assert result.available is True
        assert result.gear == gear

    def test_firstGear_isTheLeastReliableBand_andStillResolvesAcrossItsSpread(self):
        """
        Given: 1st gear's caveat -- n=78, spread 97.6 to 116.7
        When:  both ends of that spread are derived
        Then:  both report 1st

        The caveat says to EXPECT this band to be the weakest, which is a reason
        to pin its extremes rather than only its median: a narrower future
        re-measurement that cannot hold its own p05 would fail here.
        """
        assert _settledAtRatio(97.6).gear == 1
        assert _settledAtRatio(116.7).gear == 1

    def test_secondGear_isWide_andBothEndsOfItsSpreadStillResolve(self):
        """
        Given: 2nd gear's caveat -- a wide 61.8 to 68.5 spread
        When:  both ends are derived
        Then:  both report 2nd
        """
        assert _settledAtRatio(61.8).gear == 2
        assert _settledAtRatio(68.5).gear == 2


# ---------------------------------------------------------------------------
# The negative cases survive the real table. A calibration that resolved
# EVERYTHING would have replaced the honest absence with a confident guess.
# ---------------------------------------------------------------------------


class TestTheRealTableStillRefusesToGuess:
    """The typed absences must outlive calibration."""

    def test_ratioAboveTheWholeTable_reportsNoBandMatch_notFirstGear(self):
        """
        Given: a ratio above 999.0, outside every published band
        When:  the derivation runs
        Then:  it reports no_band_match rather than clamping to 1st

        1st gear's band is open-ended to 999.0, so "nearest match" and "in band"
        agree everywhere inside the table. This is the one point where they
        disagree, and it is the only place a clamp could be caught.
        """
        result = _settledAtRatio(1200.0)

        assert result.available is False
        assert result.reason == gd.REASON_NO_BAND

    def test_belowTheSpeedFloor_reportsBelowThreshold_notFifthGear(self):
        """
        Given: a car creeping at 2 km/h with the engine at 1200 rpm
        When:  the derivation runs against the real table
        Then:  it refuses on the threshold, before the ratio is ever consulted

        Load-bearing with THIS table specifically: 5th gear's band starts at
        0.0, so without the floor a creep would resolve to a confident 5th.
        """
        deriver = gd.createGearDeriverFromConfig(_validatedConfig())
        assert deriver is not None

        result = deriver.update(
            speed=gd.Reading(2.0, 100.0), rpm=gd.Reading(1200.0, 100.0), nowS=100.0
        )

        assert result.available is False
        assert result.reason == gd.REASON_BELOW_THRESHOLD
