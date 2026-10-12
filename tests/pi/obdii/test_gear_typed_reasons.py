################################################################################
# File Name: test_gear_typed_reasons.py
# Purpose/Description: US-739 -- the two typed reasons that were approved but
#     never shipped. A dead OBD link, a car one dwell away from Park and a cold
#     start all reached the tile as `no_data` -> "no reading", and the operator
#     could not tell them apart (the live evidence: states/gear read `no_data`
#     WITH the OBD link down). These tests pin the approved state table row by
#     row, and pin that the speed-side absences were not swallowed by the new
#     branches.
# Author: Rex (US-739)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-22    | Rex (US-739)   | Initial -- the state table, the speed-side
#               |                | absences, and the exported tokens.
# ================================================================================
################################################################################
"""US-739: link_down and settling_park, per the approved state table."""

from __future__ import annotations

import pytest

import pi.obdii.gear_derivation as gd

# The same deliberately simple, non-overlapping table the other guard tests
# use: a failure here can never be confused with a band-table question.
_BANDS = (
    gd.GearBand(gear=1, ratioMin=90.0, ratioMax=125.0),
    gd.GearBand(gear=2, ratioMin=54.0, ratioMax=74.0),
    gd.GearBand(gear=3, ratioMin=36.0, ratioMax=49.0),
)
_SPEED_IN_3RD = 60.0
_RPM_IN_3RD = 42.0 * _SPEED_IN_3RD  # mid-band for gear 3

_NOW = 1000.0


def _deriver() -> gd.GearDeriver:
    return gd.GearDeriver(bands=_BANDS)


def _fresh(value: float) -> gd.Reading:
    return gd.Reading(value, _NOW)


def _aged(value: float) -> gd.Reading:
    return gd.Reading(value, _NOW - gd.DEFAULT_MAX_AGE_S - 0.1)


class TestTheTokensExist:
    def test_bothTokensAreExportedWithTheirApprovedValues(self) -> None:
        """The wire values are the contract with carousel.js; they are not the
        developer's to restyle."""
        assert gd.REASON_LINK_DOWN == "link_down"
        assert gd.REASON_SETTLING_PARK == "settling_park"
        assert "REASON_LINK_DOWN" in gd.__all__
        assert "REASON_SETTLING_PARK" in gd.__all__

    def test_everyReasonTokenIsDistinct(self) -> None:
        """Two reasons sharing a value would be two facts the tile cannot tell
        apart -- the defect this story exists to remove."""
        tokens = [
            getattr(gd, name) for name in gd.__all__ if name.startswith("REASON_")
        ]
        assert len(tokens) == len(set(tokens))


class TestTheApprovedStateTable:
    """RPM UNUSABLE is the trigger for both new rows; the link decides which."""

    @pytest.mark.parametrize("rpm", [None, _aged(800.0)], ids=["missing", "stale"])
    def test_rpmUnusable_linkDown_saysLinkDown(self, rpm) -> None:
        """
        Given: RPM unusable -- absent OR aged out -- and the link NOT healthy
        When:  the deriver is updated
        Then:  link_down. Both sentinels, because after a real drive the reading
            is STALE rather than missing, and that is the normal parked state
        """
        result = _deriver().update(
            speed=_fresh(_SPEED_IN_3RD), rpm=rpm, nowS=_NOW, linkHealthy=False
        )

        assert result.available is False
        assert result.gear is None
        assert result.reason == gd.REASON_LINK_DOWN

    @pytest.mark.parametrize("rpm", [None, _aged(800.0)], ids=["missing", "stale"])
    def test_rpmUnusable_linkHealthy_dwellNotMet_saysSettlingPark(self, rpm) -> None:
        """
        Given: RPM unusable, the link healthy, and the dwell not yet met
        When:  the deriver is updated
        Then:  settling_park -- the one state that resolves itself by waiting
        """
        result = _deriver().update(
            speed=_fresh(_SPEED_IN_3RD), rpm=rpm, nowS=_NOW, linkHealthy=True
        )

        assert result.available is False
        assert result.gear != gd.GEAR_PARK
        assert result.reason == gd.REASON_SETTLING_PARK

    def test_rpmUnusable_linkHealthy_dwellMet_isStillPark(self) -> None:
        """The row this story must NOT disturb: hold past the dwell and Park
        still fires, from the STALE sentinel."""
        deriver = _deriver()
        nowS = _NOW
        result = None
        while nowS <= _NOW + gd.DEFAULT_PARK_DWELL_S + 0.5:
            result = deriver.update(
                speed=None, rpm=gd.Reading(800.0, _NOW - gd.DEFAULT_MAX_AGE_S - 0.1),
                nowS=nowS, linkHealthy=True,
            )
            nowS += 0.25

        assert result.gear == gd.GEAR_PARK
        assert result.reason == gd.REASON_PARK

    def test_aLinkThatReturnsMidDwell_reachesParkOnTheSameOutage(self) -> None:
        """
        Given: an outage that begins with the link down, then the link returns
        When:  the dwell elapses, measured from when RPM became unusable
        Then:  Park -- emitting link_down does not restart the dwell clock
        """
        deriver = _deriver()
        nowS = _NOW
        rpm = gd.Reading(800.0, _NOW - gd.DEFAULT_MAX_AGE_S - 0.1)
        # First half of the dwell with the link down.
        while nowS < _NOW + gd.DEFAULT_PARK_DWELL_S / 2:
            assert deriver.update(
                speed=None, rpm=rpm, nowS=nowS, linkHealthy=False
            ).reason == gd.REASON_LINK_DOWN
            nowS += 0.25
        # The link returns; the dwell keeps counting from the ORIGINAL outage.
        result = None
        while nowS <= _NOW + gd.DEFAULT_PARK_DWELL_S + 0.5:
            result = deriver.update(speed=None, rpm=rpm, nowS=nowS, linkHealthy=True)
            nowS += 0.25

        assert result.gear == gd.GEAR_PARK


class TestTheSpeedSideAbsencesSurvive:
    """AC2: no_data / stale stay reachable, and ONLY when RPM is usable."""

    @pytest.mark.parametrize("healthy", [False, True], ids=["linkDown", "linkHealthy"])
    def test_speedMissing_rpmFresh_isStillNoData(self, healthy: bool) -> None:
        """A speed-only absence is a different fact and keeps its own reason --
        whatever the link is doing."""
        result = _deriver().update(
            speed=None, rpm=_fresh(_RPM_IN_3RD), nowS=_NOW, linkHealthy=healthy
        )

        assert result.available is False
        assert result.reason == gd.REASON_NO_DATA

    @pytest.mark.parametrize("healthy", [False, True], ids=["linkDown", "linkHealthy"])
    def test_speedStale_rpmFresh_isStillStale(self, healthy: bool) -> None:
        result = _deriver().update(
            speed=_aged(_SPEED_IN_3RD), rpm=_fresh(_RPM_IN_3RD), nowS=_NOW,
            linkHealthy=healthy,
        )

        assert result.available is False
        assert result.reason == gd.REASON_STALE

    def test_aFreshZeroRpm_isStillPark_notSettling(self) -> None:
        """RPM present, fresh and zero is a MEASUREMENT, not an absence: Park
        immediately, with no dwell and no link flag consulted."""
        result = _deriver().update(
            speed=_fresh(0.0), rpm=_fresh(0.0), nowS=_NOW, linkHealthy=False
        )

        assert result.gear == gd.GEAR_PARK

    def test_aGoodPair_stillResolvesAGear(self) -> None:
        """The new branches sit in the RPM-unusable window only."""
        deriver = _deriver()
        nowS = _NOW
        result = None
        while nowS <= _NOW + gd.DEFAULT_DEBOUNCE_S + 0.5:
            result = deriver.update(
                speed=gd.Reading(_SPEED_IN_3RD, nowS),
                rpm=gd.Reading(_RPM_IN_3RD, nowS),
                nowS=nowS,
                linkHealthy=True,
            )
            nowS += 0.25

        assert result.gear == 3
        assert result.reason == gd.REASON_ENGAGED
