################################################################################
# File Name: test_gear_neutral.py
# Purpose/Description: US-687-a (F-138) -- the GEAR producer emits "N" when the
#                      engine is turning and the car is stopped. Engine running
#                      with SPEED == 0 transmits no drive ratio: a DETERMINATE
#                      state, not an absence, and today the tile shows the
#                      internal token `below_threshold` instead.
#
#                      TWO FIXTURE TRAPS, BOTH MEASURED, BOTH WOULD PASS A NAIVE
#                      TEST, and both are pinned here on the awkward real values:
#                      (1) the trigger is RPM > 0, NEVER RPM >= minRpm (900) --
#                      measured idle averages 800 rpm and 91.6 % of stationary
#                      samples fall below that floor, so a fixture at 1,200 rpm
#                      passes while the car fails; (2) the trigger is SPEED == 0,
#                      NEVER SPEED being ABSENT -- drive 64 carried 614 SPEED
#                      rows of which 388 read zero, so a "speed missing" branch
#                      would never once fire at a stoplight.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-07    | Rex (US-687-a) | Initial -- the NEUTRAL branch, its trigger,
#               |                | its precedence, and every neighbour it must
#               |                | not steal a case from.
# ================================================================================
################################################################################

"""US-687-a: ``RPM > 0`` with ``SPEED == 0`` is NEUTRAL, not a typed absence.

Producer-only by the story's ruling: ``carousel.js`` ``gearView`` has handled
``"N"`` since US-508 and no renderer branch is added here.  The rendered half is
pinned end-to-end in ``tests/ui/test_carousel_gear_neutral.py``.

WHAT "N" CLAIMS, AND WHAT IT DOES NOT (Spool's limit, retained by the CIO's
ruling rather than dissolved by it): N means **the engine is running and no
drive ratio is being transmitted**.  It does NOT mean the lever is in neutral.
On a manual gearbox ``RPM > 0 AND SPEED == 0`` is bit-for-bit identical between
true neutral and first-with-the-clutch-down -- there is no torque path either
way, so the glyph is honest, but anyone analysing N-time must not read it as
lever position.
"""

from __future__ import annotations

from src.pi.obdii import gear_derivation as gd

# The same deliberately simple, non-overlapping table test_gear_derivation.py
# uses: a guard failure here can never be confused with a band-table question.
# Units are rpm per km/h.
_BANDS = (
    gd.GearBand(gear=1, ratioMin=90.0, ratioMax=125.0),
    gd.GearBand(gear=2, ratioMin=54.0, ratioMax=74.0),
    gd.GearBand(gear=3, ratioMin=36.0, ratioMax=49.0),
)

# MEASURED, not chosen for the test. Idle on this car averages 800 rpm with a
# minimum of 684; 91.6 % of stationary samples sit BELOW the 900 rpm floor.
# Every neutral fixture below is pinned to 800 for exactly that reason.
_MEASURED_IDLE_RPM = 800.0

# 2500 rpm at 45 km/h is 55.6 rpm/kph -- inside band 2 above.
_MOVING_SPEED_KPH = 45.0
_MOVING_RPM = 2500.0


def _deriver(bands=_BANDS, **kwargs):
    """A deriver with the guard-test band table unless told otherwise."""
    return gd.GearDeriver(bands=bands, **kwargs)


def _at(deriver, speedKph, rpm, nowS=100.0):
    """One update with both readings PRESENT and fresh at ``nowS``."""
    return deriver.update(
        speed=gd.Reading(speedKph, nowS), rpm=gd.Reading(rpm, nowS), nowS=nowS
    )


def _settled(deriver, speedKph, rpm, startS=100.0):
    """Hold one steady operating point past the debounce and return the result."""
    _at(deriver, speedKph, rpm, startS)
    later = startS + gd.DEFAULT_DEBOUNCE_S + 0.1
    return _at(deriver, speedKph, rpm, later)


class TestTheNeutralBranch:
    """The end state: stopped with the engine turning reads N."""

    def test_update_measuredIdleAtAStandstill_readsNeutral(self):
        """
        Given: RPM 800 and SPEED 0, both PRESENT -- the car at a light
        When:  the deriver is updated
        Then:  it reports an AVAILABLE reading whose gear is the string "N"

        The single most load-bearing fixture in this sprint. 800 rpm is the
        measured idle average and it is BELOW the 900 rpm ratio floor, so an
        implementation that gated N on `rpm >= minRpm` passes a bench fixture at
        1,200 rpm and is invisible in the car.
        """
        result = _at(_deriver(), 0.0, _MEASURED_IDLE_RPM)

        assert result.available is True
        assert result.gear == gd.GEAR_NEUTRAL
        assert result.reason == gd.REASON_NEUTRAL

    def test_update_neutralGearIsTheExactStringCarouselBranchesOn(self):
        """
        Given: the neutral reading
        When:  its gear value is compared to the renderer's literal
        Then:  it is the string "N", not the character in some other form

        `carousel.js` gearView tests `gear === "N"` -- a strict comparison, so a
        producer emitting "n", "N " or 0 would fall through to the final branch
        and render `--` while every producer-side test still passed.
        """
        result = _at(_deriver(), 0.0, _MEASURED_IDLE_RPM)

        assert result.gear == "N"
        assert isinstance(result.gear, str)

    def test_toStateDict_neutral_matchesTheCarouselContract(self):
        """
        Given: a neutral reading
        When:  it is serialised for states/gear
        Then:  it is exactly the {available, gear, reason} shape gearView reads
        """
        state = _at(_deriver(), 0.0, _MEASURED_IDLE_RPM).toStateDict()

        assert state == {"available": True, "gear": "N", "reason": "neutral"}

    def test_update_neutralIsPublishedOnTheFirstSample_notDebounced(self):
        """
        Given: a single stationary sample and nothing before it
        When:  the deriver is updated once
        Then:  N is already available

        The debounce exists to stop the glyph flickering between NUMBERED gears
        while a ratio settles. SPEED == 0 is exact -- there is nothing to
        settle, and a debounced N would be dark for the first two seconds of
        every stop, which is a large share of the stops this car makes.
        """
        result = _at(_deriver(), 0.0, _MEASURED_IDLE_RPM)

        assert result.available is True
        assert result.gear == gd.GEAR_NEUTRAL


class TestTheTriggerIsRpmAboveZeroNotAboveTheRatioFloor:
    """`RPM > 0`, NEVER `RPM >= 900`. Spool ratified; the car proves it."""

    def test_update_wellBelowTheRatioFloor_stillReadsNeutral(self):
        """
        Given: RPM 684 -- the LOWEST idle sample measured on this car
        When:  the car is stopped
        Then:  it still reads N

        The 900 floor makes the RATIO trustworthy; below it, driveline lash,
        clutch slip and quantisation dominate. In neutral NO RATIO IS BEING
        COMPUTED, so the floor answers a question that is not being asked.
        """
        result = _at(_deriver(), 0.0, 684.0)

        assert result.available is True
        assert result.gear == gd.GEAR_NEUTRAL

    def test_update_oneRpmAboveZero_readsNeutral(self):
        """
        Given: the smallest engine speed that is not zero
        When:  the car is stopped
        Then:  it reads N -- the trigger is a turning engine, nothing more
        """
        result = _at(_deriver(), 0.0, 1.0)

        assert result.available is True
        assert result.gear == gd.GEAR_NEUTRAL

    def test_update_theFloorIsNotTheTrigger_bothSidesOfItAgree(self):
        """
        Given: two stationary samples that straddle the 900 rpm floor
        When:  each is derived
        Then:  both read N, identically

        Held as a DIRECT COMPARISON rather than as two separate assertions: the
        claim is that the floor is irrelevant to this branch, and only reading
        both sides in one place can witness that. An implementation gated on
        `rpm >= minRpm` splits this pair.
        """
        below = _at(_deriver(), 0.0, gd.DEFAULT_MIN_RPM - 1.0)
        above = _at(_deriver(), 0.0, gd.DEFAULT_MIN_RPM + 1.0)

        assert below.gear == gd.GEAR_NEUTRAL
        assert above.gear == gd.GEAR_NEUTRAL
        assert below.reason == above.reason


class TestTheTriggerIsSpeedZeroNotSpeedMissing:
    """`SPEED == 0`, NEVER SPEED being ABSENT. Absent is not zero."""

    def test_update_rpmPresentAndTheSpeedKeyAbsent_isNoDataNotNeutral(self):
        """
        Given: a live RPM and NO speed reading at all
        When:  the deriver is updated
        Then:  it takes the no_data branch -- an absence, not neutral

        WHICH BRANCH AND WHY, as the story asks: `_liveValue` resolves a None
        reading to the _MISSING sentinel, and the no_data guard fires before
        the neutral branch is ever reached. This is correct. A missing SPEED
        means the pipe did not tell us how fast the car is going -- which is a
        different fact from being told it is going nowhere, and the car is
        stopped for 63 % of a drive without ever once omitting the key.
        """
        result = _deriver().update(
            speed=None, rpm=gd.Reading(_MEASURED_IDLE_RPM, 100.0), nowS=100.0
        )

        assert result.available is False
        assert result.gear is None
        assert result.reason == gd.REASON_NO_DATA

    def test_update_speedReadingWithANullValue_isNoDataNotNeutral(self):
        """
        Given: a SPEED reading that arrived carrying no value
        When:  the deriver is updated
        Then:  no_data again -- a null value is an absence, not a zero

        The second shape of "missing". A producer that treated a null as 0.0
        would manufacture a stationary car out of a decode failure, and it
        would do it while the car was moving.
        """
        result = _deriver().update(
            speed=gd.Reading(None, 100.0),
            rpm=gd.Reading(_MEASURED_IDLE_RPM, 100.0),
            nowS=100.0,
        )

        assert result.available is False
        assert result.reason == gd.REASON_NO_DATA

    def test_update_creepingJustAboveZero_isBelowThresholdNotNeutral(self):
        """
        Given: 0.1 km/h -- moving, barely
        When:  the deriver is updated
        Then:  below_threshold, not N

        The bound on the branch in the other direction. Nearly-zero is not
        zero: the car IS transmitting a drive ratio, it is just too slow for
        the ratio to be trustworthy, which is precisely what below_threshold
        already says.
        """
        result = _settled(_deriver(), 0.1, _MEASURED_IDLE_RPM)

        assert result.available is False
        assert result.reason == gd.REASON_BELOW_THRESHOLD


class TestNeutralStealsNoCaseFromItsNeighbours:
    """Every branch the new one sits beside, still reaching its own answer."""

    def test_update_movingAboveEveryGate_readsTheDerivedGear(self):
        """
        Given: RPM 2500 at 45 km/h -- both present, both above the floors
        When:  the point is held past the debounce
        Then:  the DERIVED gear is published, not N
        """
        result = _settled(_deriver(), _MOVING_SPEED_KPH, _MOVING_RPM)

        assert result.available is True
        assert result.gear == 2
        assert result.reason == gd.REASON_ENGAGED

    def test_update_engineOffAndStopped_isNotNeutral(self):
        """
        Given: RPM 0 with SPEED 0 -- the car is OFF
        When:  the deriver is updated
        Then:  it does NOT read N. A car that is off is not in neutral.

        The negative case US-687-b then converts into P. Asserted here as "not
        neutral" rather than as a named reason so that US-687-b changing the
        answer to P does not read as a regression of this story -- the claim
        this story makes is only that N does not reach here.

        CONTRACT CHANGED 2026-09-07 BY US-687-b, exactly as the paragraph above
        anticipated. This test also asserted `available is False`, which was a
        claim about the TYPED ABSENCE that used to answer here and not about
        neutral at all -- an off engine now publishes an AVAILABLE "P". The
        surviving claim, and the only one this story ever owned, is that N does
        not reach a stopped engine; it is kept, so the file still fails if the
        `rpm > 0` trigger is ever loosened.
        """
        result = _settled(_deriver(), 0.0, 0.0)

        assert result.gear != gd.GEAR_NEUTRAL
        assert result.reason != gd.REASON_NEUTRAL

    def test_update_stationaryButTheSpeedReadingIsStale_isStaleNotNeutral(self):
        """
        Given: a live RPM and a SPEED reading older than the freshness window
        When:  the deriver is updated
        Then:  stale, not N

        Freshness dominates. A zero that arrived a minute ago is not evidence
        the car is stopped NOW -- it is evidence the pipe went quiet while the
        car was stopped, and the car may have moved since.
        """
        nowS = 100.0
        result = _deriver().update(
            speed=gd.Reading(0.0, nowS - gd.DEFAULT_MAX_AGE_S - 1.0),
            rpm=gd.Reading(_MEASURED_IDLE_RPM, nowS),
            nowS=nowS,
        )

        assert result.available is False
        assert result.reason == gd.REASON_STALE

    def test_update_stationaryWithNoBandTable_isNotCalibratedNotNeutral(self):
        """
        Given: a deriver with no bands configured, stopped with the engine on
        When:  the deriver is updated
        Then:  not_calibrated -- configuration still dominates

        A DELIBERATE PRECEDENCE CHOICE, recorded here so it is a decision and
        not an accident. N needs no band table, so it COULD be reported by an
        uncalibrated deriver -- but the module's standing rule is that a config
        error fails fast and plainly rather than resolving whichever branch
        happens not to need the missing configuration. A tile that lights at
        every stop and goes dark the instant the car moves would look like a
        working feature while the real defect (no bands) stayed invisible.
        """
        result = _at(gd.GearDeriver(bands=()), 0.0, _MEASURED_IDLE_RPM)

        assert result.available is False
        assert result.reason == gd.REASON_NOT_CALIBRATED


class TestNeutralDoesNotContaminateTheDebounce:
    """Rolling to a stop and away again must not leave a candidate behind."""

    def test_update_gearThenNeutralThenTheSameGear_debouncesAgain(self):
        """
        Given: a settled 2nd gear, then a stop, then 2nd gear again
        When:  the first moving sample after the stop is derived
        Then:  it is SETTLING, not an instantly republished 2

        N must clear the debounce candidate exactly as every typed absence
        does. If it did not, the stop would preserve the pre-stop candidate and
        the tile would republish a gear the car has not yet been in -- a wrong
        number, which is the one thing this producer must never print.
        """
        deriver = _deriver()
        _settled(deriver, _MOVING_SPEED_KPH, _MOVING_RPM)

        neutral = _at(deriver, 0.0, _MEASURED_IDLE_RPM, nowS=200.0)
        movingAgain = _at(deriver, _MOVING_SPEED_KPH, _MOVING_RPM, nowS=201.0)

        assert neutral.gear == gd.GEAR_NEUTRAL
        assert movingAgain.available is False
        assert movingAgain.reason == gd.REASON_SETTLING

    def test_update_engagedThenTheCarStops_dropsTheGearOnTheNextSample(self):
        """
        Given: a settled 2nd gear
        When:  the very next sample is stationary
        Then:  the reading is N immediately -- no held 2, no settling gap

        The complement of the test above: the transition INTO neutral is
        instant, so the driver never sees a gear the car has left.
        """
        deriver = _deriver()
        engaged = _settled(deriver, _MOVING_SPEED_KPH, _MOVING_RPM)
        assert engaged.gear == 2

        result = _at(deriver, 0.0, _MEASURED_IDLE_RPM, nowS=200.0)

        assert result.gear == gd.GEAR_NEUTRAL


class TestTheReasonVocabularyIsPublished:
    """The new reason is a module constant, not a literal sprinkled about."""

    def test_theNeutralConstantsAreExported(self):
        """
        Given: the derivation module
        When:  its __all__ is read
        Then:  both new names are published

        Consumers must be able to compare against a name rather than retyping
        "N" and "neutral" -- which is how a vocabulary drifts one caller at a
        time.
        """
        assert "GEAR_NEUTRAL" in gd.__all__
        assert "REASON_NEUTRAL" in gd.__all__

    def test_theNeutralReasonIsDistinctFromEveryOtherReason(self):
        """
        Given: every reason the module publishes
        When:  they are compared
        Then:  no two share a value

        A duplicated token would make two different operator facts
        indistinguishable in the state file, which is the exact defect the
        typed-absence design exists to prevent.
        """
        reasons = [
            gd.REASON_ENGAGED,
            gd.REASON_NEUTRAL,
            gd.REASON_NO_DATA,
            gd.REASON_STALE,
            gd.REASON_NOT_CALIBRATED,
            gd.REASON_BELOW_THRESHOLD,
            gd.REASON_NO_BAND,
            gd.REASON_AMBIGUOUS,
            gd.REASON_SETTLING,
        ]

        assert len(set(reasons)) == len(reasons)
