################################################################################
# File Name: test_gear_hint.py
# Purpose/Description: US-904-a -- gearHint, the between-gears hint rule
#   (specs/v030-driving-page-design.md s4.2, Spool 2026-10-13; pairing guard
#   Spool S2 2026-10-26; out-of-range is no hint, Spool S3 2026-10-26). A pure
#   function of the reading sequence: every case here is built from Reading
#   values and arrival times, with no clock anywhere (Atlas A2).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-26    | Rex (US-904-a) | Initial -- up/down/none and every negative.
# ================================================================================
################################################################################

"""US-904-a: gearHint returns (hintGear, hintDirection) or (None, None)."""

from __future__ import annotations

from typing import Any

import pytest

from pi.obdii import gear_derivation as gd
from pi.obdii.gear_derivation import Reading, gearHint

_NONE = (None, None)

# The arrival time of the reading that triggered the emit. Arbitrary: only
# differences between arrival times mean anything.
_T = 5000.0


def _hint(**overrides: Any) -> tuple[Any, Any]:
    """The story's first example, with any argument overridden.

    G=2 solid 3 s ago at 4,800 rpm; now settling, RPM 3,200, speed 72 -> 71
    km/h, RPM and SPEED arriving 0.14 s apart (Spool S2's measured spacing).
    """
    args: dict[str, Any] = {
        "reason": gd.REASON_SETTLING,
        "solidGear": 2,
        "solidAtS": _T - 3.0,
        "rpmAtSolid": 4800.0,
        "rpm": Reading(value=3200.0, tsS=_T),
        "speed": Reading(value=71.0, tsS=_T - 0.14),
        "prevSpeed": Reading(value=72.0, tsS=_T - 0.14 - 2.2),
        "nowS": _T,
    }
    args.update(overrides)
    return gearHint(**args)


class TestTheStoryExamples:
    def test_upshift_example_hintsTheNextGearUp(self):
        """
        Given: G=2 solid 3 s ago at 4,800 rpm; settling, RPM 3,200, 72 -> 71 km/h
        When:  the hint is computed
        Then:  (3, 'up')
        """
        assert _hint() == (3, gd.HINT_DIRECTION_UP)

    def test_downshift_example_hintsTheNextGearDown(self):
        """
        Given: G=3 solid 2 s ago at 2,500 rpm; ambiguous, RPM 3,500, 54 -> 52 km/h
        When:  the hint is computed
        Then:  (2, 'down')
        """
        assert _hint(
            reason=gd.REASON_AMBIGUOUS,
            solidGear=3,
            solidAtS=_T - 2.0,
            rpmAtSolid=2500.0,
            rpm=Reading(value=3500.0, tsS=_T),
            speed=Reading(value=52.0, tsS=_T),
            prevSpeed=Reading(value=54.0, tsS=_T - 2.2),
        ) == (2, gd.HINT_DIRECTION_DOWN)

    def test_brakingWithClutchIn_bothDrop_noHint(self):
        """
        Given: RPM AND speed both dropping (braking with the clutch in)
        When:  the hint is computed
        Then:  (None, None) -- RPM down says up, speed falling says not up
        """
        assert _hint(
            reason=gd.REASON_NO_BAND,
            speed=Reading(value=60.0, tsS=_T),
            prevSpeed=Reading(value=66.0, tsS=_T - 2.2),
        ) == _NONE

    def test_noBandMatch_isAHintingReason(self):
        assert _hint(reason=gd.REASON_NO_BAND) == (3, gd.HINT_DIRECTION_UP)


class TestTheSpeedTolerance:
    def test_speedDroppedExactlyTwo_stillCountsAsNotFalling(self):
        """speed >= previous - 2 km/h: a 2 km/h drop is 'not falling'."""
        assert _hint(
            speed=Reading(value=70.0, tsS=_T),
            prevSpeed=Reading(value=72.0, tsS=_T - 2.2),
        ) == (3, gd.HINT_DIRECTION_UP)

    def test_speedDroppedMoreThanTwo_noUpHint(self):
        assert _hint(
            speed=Reading(value=69.9, tsS=_T),
            prevSpeed=Reading(value=72.0, tsS=_T - 2.2),
        ) == _NONE

    def test_rpmUpButSpeedSteady_noDownHint(self):
        """latest RPM > RPM at G needs speed STRICTLY falling for a down hint."""
        assert _hint(
            rpm=Reading(value=5200.0, tsS=_T),
            speed=Reading(value=72.0, tsS=_T),
            prevSpeed=Reading(value=72.0, tsS=_T - 2.2),
        ) == _NONE

    def test_rpmEqualToRpmAtG_noHint(self):
        assert _hint(rpm=Reading(value=4800.0, tsS=_T)) == _NONE


class TestNegativeCases:
    @pytest.mark.parametrize(
        "reason",
        [
            gd.REASON_ENGAGED,
            gd.REASON_NEUTRAL,
            gd.REASON_PARK,
            gd.REASON_STALE,
            gd.REASON_LINK_DOWN,
            gd.REASON_NO_DATA,
            gd.REASON_BELOW_THRESHOLD,
            gd.REASON_NOT_CALIBRATED,
            gd.REASON_SETTLING_PARK,
            gd.REASON_ENGINE_OFF_ROLLING,
        ],
    )
    def test_nonHintingReason_noHint(self, reason):
        assert _hint(reason=reason) == _NONE

    def test_noSolidGearYet_noHint(self):
        assert _hint(solidGear=None, solidAtS=None, rpmAtSolid=None) == _NONE

    def test_solidGear5Point01SecondsAgo_noHint(self):
        assert _hint(solidAtS=_T - 5.01) == _NONE

    def test_solidGearExactly5SecondsAgo_stillHints(self):
        """<= 5 s: the boundary itself is inside."""
        assert _hint(solidAtS=_T - 5.0) == (3, gd.HINT_DIRECTION_UP)

    def test_speedExactly15_noHint(self):
        """speed > 15 km/h is strict."""
        assert _hint(
            speed=Reading(value=15.0, tsS=_T),
            prevSpeed=Reading(value=15.0, tsS=_T - 2.2),
        ) == _NONE

    def test_speedJustAbove15_hints(self):
        assert _hint(
            speed=Reading(value=15.5, tsS=_T),
            prevSpeed=Reading(value=15.5, tsS=_T - 2.2),
        ) == (3, gd.HINT_DIRECTION_UP)

    def test_g5GoingUp_isNoHint_neverAClampedFive(self):
        assert _hint(solidGear=5) == _NONE

    def test_g1GoingDown_isNoHint_neverAClampedOne(self):
        assert _hint(
            solidGear=1,
            rpm=Reading(value=5200.0, tsS=_T),
            speed=Reading(value=60.0, tsS=_T),
            prevSpeed=Reading(value=66.0, tsS=_T - 2.2),
        ) == _NONE

    @pytest.mark.parametrize("notSolid", [gd.GEAR_NEUTRAL, gd.GEAR_PARK, 0, 6, True, 2.0])
    def test_nOrPOrNonGear_isNotASolidGear(self, notSolid):
        assert _hint(solidGear=notSolid) == _NONE

    def test_noPreviousSpeed_noHint(self):
        assert _hint(prevSpeed=None) == _NONE

    @pytest.mark.parametrize("which", ["rpm", "speed", "prevSpeed"])
    def test_aNullReadingValue_noHint(self, which):
        assert _hint(**{which: Reading(value=None, tsS=_T)}) == _NONE

    @pytest.mark.parametrize("which", ["rpm", "speed"])
    def test_aMissingReading_noHint(self, which):
        assert _hint(**{which: None}) == _NONE

    def test_noRpmAtG_noHint(self):
        assert _hint(rpmAtSolid=None) == _NONE

    def test_nonFiniteRpm_noHint(self):
        assert _hint(rpm=Reading(value=float("nan"), tsS=_T)) == _NONE


class TestThePairingGuard:
    def test_speedArrives1Point5SecondsAfterRpm_noHint(self):
        """Spool S2 2026-10-26: RPM at t, SPEED at t + 1.5 s -> (null, null)."""
        assert _hint(
            rpm=Reading(value=3200.0, tsS=_T - 1.5),
            speed=Reading(value=71.0, tsS=_T),
        ) == _NONE

    def test_pairExactly1Point1SecondsApart_stillHints(self):
        """Arrival times 0.0 and 1.1 so the gap is exactly the float 1.1."""
        assert _hint(
            solidAtS=0.0,
            nowS=1.1,
            rpm=Reading(value=3200.0, tsS=1.1),
            speed=Reading(value=71.0, tsS=0.0),
            prevSpeed=Reading(value=72.0, tsS=-2.2),
        ) == (3, gd.HINT_DIRECTION_UP)

    def test_theConstantsAreTheRuledNumbers(self):
        """s4.2 (Spool 2026-10-13) and S2 (Spool 2026-10-26)."""
        assert gd.HINT_MAX_SOLID_AGE_S == 5.0
        assert gd.HINT_MIN_SPEED_KPH == 15.0
        assert gd.HINT_SPEED_TOLERANCE_KPH == 2.0
        assert gd.HINT_MAX_PAIR_GAP_S == 1.1


class TestPurity:
    def test_sameReadingSequence_sameHint_noClockInvolved(self):
        """The hint is a pure function of its arguments: call it twice."""
        assert _hint() == _hint()

    def test_aHintNeverEqualsG(self):
        for gear in range(1, 6):
            for rpm, speeds in ((3000.0, (72.0, 71.0)), (5500.0, (66.0, 60.0))):
                hintGear, _dir = _hint(
                    solidGear=gear,
                    rpm=Reading(value=rpm, tsS=_T),
                    speed=Reading(value=speeds[1], tsS=_T),
                    prevSpeed=Reading(value=speeds[0], tsS=_T - 2.2),
                )
                assert hintGear != gear
                assert hintGear is None or 1 <= hintGear <= 5


class TestIsSolidGear:
    @pytest.mark.parametrize("gear", [1, 2, 3, 4, 5])
    def test_numberedGears_areSolid(self, gear):
        assert gd.isSolidGear(gear) is True

    @pytest.mark.parametrize("gear", [None, "N", "P", 0, 6, True, 3.0])
    def test_everythingElse_isNot(self, gear):
        assert gd.isSolidGear(gear) is False
