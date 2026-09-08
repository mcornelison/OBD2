################################################################################
# File Name: test_gear_park.py
# Purpose/Description: US-687-b (F-138) -- the GEAR producer emits "P" when the
#                      OBD link is healthy and RPM has been unusable for longer
#                      than the park dwell. Absence of RPM with a live dongle is
#                      a determinate state (CIO ruling 2026-09-06, refined
#                      2026-09-07); today the tile shows nothing at all.
#
#                      THE TRAP THE STORY NAMES, PINNED HERE TWICE. A P branch
#                      written only against the MISSING sentinel would ESSENTIALLY
#                      NEVER FIRE: `_lastRpmReading` is never cleared, it AGES
#                      OUT, so the normal post-drive state is _STALE and not
#                      _MISSING. Both are pinned, and the stale case is called
#                      out by name because it is the one a naive implementation
#                      drops.
#
#                      AND THE DWELL IS PINNED AGAINST THE MEASUREMENT THAT SIZED
#                      IT: worst in-drive RPM gap 13 s over 2,141 samples across
#                      drives 64-68. A 13 s stall must NOT paint P; the same
#                      stall held past the dwell MUST -- otherwise the 13 s test
#                      passes for a reason that has nothing to do with the dwell.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-07    | Rex (US-687-b) | Initial -- the PARK branch, its dwell, its
#               |                | link-health condition, its precedence, and
#               |                | every neighbour it must not steal a case from.
# ================================================================================
################################################################################

"""US-687-b: a healthy link that has stopped reporting RPM is PARK.

TWO SOURCES, BOTH NAMED, and this story does not have a single SSOT.  **RPM
(PID 0x0C)**, whose ABSENCE means P.  **SPEED (PID 0x0D)**, whose VALUE
distinguishes N from a derived gear.  Both arrive over the SAME OBDLink
Bluetooth transport, so a link failure removes BOTH at once -- which is exactly
why P also requires ``linkHealthy``.

WHAT "P" CLAIMS.  The link is up and the engine is not reporting a speed.  It
does NOT claim the lever is in Park; this car has no PRNDL and a manual gearbox
has no Park detent at all.  The glyph is the operator's word for "switched off",
and the CIO ruled it on the record while gear stays display-only (US-693 is the
lint that keeps that true).
"""

from __future__ import annotations

from src.pi.obdii import gear_derivation as gd

# The same deliberately simple, non-overlapping table the other guard tests use:
# a guard failure here can never be confused with a band-table question.
_BANDS = (
    gd.GearBand(gear=1, ratioMin=90.0, ratioMax=125.0),
    gd.GearBand(gear=2, ratioMin=54.0, ratioMax=74.0),
    gd.GearBand(gear=3, ratioMin=36.0, ratioMax=49.0),
)

# MEASURED (US-687-a): idle on this car averages 800 rpm, minimum 684, and
# 91.6 % of stationary samples sit BELOW the 900 rpm ratio floor.
_MEASURED_IDLE_RPM = 800.0

# MEASURED (Atlas, drives 64-68, 2,141 RPM samples): the WORST in-drive
# inter-sample gap. The dwell must exceed this or a bus stall paints Park at
# speed. 4 gaps were >= 10 s and 31 were >= 4 s, so this is not a lone outlier.
_WORST_MEASURED_RPM_GAP_S = 13.0

# The CEILING, and it is not driver perception (Spool 2026-09-07). At key-off
# the Pi loses fuse-box power and runs a bounded pre-shutdown pipeline --
# perTask=20s totalCap=45s from powerwatch's own startup line -- so the Pi has
# roughly 45 s of life after the event that stops the RPM data. A dwell at or
# past that ceiling produces a producer whose output the system is never alive
# long enough to SHOW: the renderer-with-no-producer defect, inverted.
_PRE_SHUTDOWN_BUDGET_S = 45.0

_MOVING_SPEED_KPH = 45.0
_MOVING_RPM = 2500.0


def _deriver(bands=_BANDS, **kwargs):
    """A deriver with the guard-test band table unless told otherwise."""
    return gd.GearDeriver(bands=bands, **kwargs)


def _tick(deriver, *, speed, rpm, nowS, linkHealthy=True):
    """One update at ``nowS``. Readings are passed already-built."""
    return deriver.update(speed=speed, rpm=rpm, nowS=nowS, linkHealthy=linkHealthy)


def _holdNoRpm(deriver, *, forS, speed=None, linkHealthy=True, startS=1000.0,
               stepS=0.25):
    """Hold "no RPM at all" for ``forS`` seconds and return the LAST reading.

    ``speed`` is a callable taking the current nowS so a caller can keep SPEED
    alive underneath the missing RPM (the in-drive stall case) or leave it
    absent (the parked case).
    """
    result = None
    nowS = startS
    while nowS <= startS + forS:
        result = _tick(
            deriver,
            speed=None if speed is None else speed(nowS),
            rpm=None,
            nowS=nowS,
            linkHealthy=linkHealthy,
        )
        nowS += stepS
    return result


# ---------------------------------------------------------------------------
# The constant itself. It sits inside a window with a MEASURED floor and a
# MEASURED ceiling, and both halves are asserted -- the floor is the obvious
# one, and the next person to "harden" this will reach for a bigger number.
# ---------------------------------------------------------------------------


class TestTheDwellConstant:
    """20.0 s is ruled, and it is bounded from BOTH sides."""

    def test_parkDwell_isSpoolsRatifiedValue(self):
        """
        Given: the shipped module default
        When:  it is read
        Then:  it is 20.0 seconds (Spool, ratified 2026-09-07)
        """
        assert gd.DEFAULT_PARK_DWELL_S == 20.0

    def test_parkDwell_exceedsTheWorstMeasuredRpmGap(self):
        """
        Given: the worst in-drive RPM gap measured over 2,141 samples (13 s)
        When:  the dwell is compared against it
        Then:  the dwell is strictly longer

        THE FLOOR. Below this a perfectly ordinary bus stall paints Park while
        the car is doing 60 mph. 20.0 is 1.5x the measured worst case.
        """
        assert gd.DEFAULT_PARK_DWELL_S > _WORST_MEASURED_RPM_GAP_S

    def test_parkDwell_fitsInsideThePreShutdownBudget(self):
        """
        Given: the Pi's ~45 s of life after key-off (perTask=20s totalCap=45s)
        When:  the dwell is compared against it
        Then:  the dwell leaves real display time inside that budget

        THE CEILING, and it is the half nobody writes down. At 20 s, P appears
        with ~25 s of panel left. At 45 s it NEVER RENDERS AT ALL -- a producer
        whose output the system is not alive long enough to show.

        SOFT AND COUPLED: this ceiling depends on the pre-shutdown budget, which
        is under active work. If `totalCap` is ever shortened, this test is the
        thing that must be re-read, and `parkDwellSec` re-checked against it.
        """
        assert gd.DEFAULT_PARK_DWELL_S < _PRE_SHUTDOWN_BUDGET_S
        assert _PRE_SHUTDOWN_BUDGET_S - gd.DEFAULT_PARK_DWELL_S >= 20.0

    def test_parkDwell_isNotTheGearToGearDebounce(self):
        """
        Given: debounceSec (2.0), sized for gear-to-gear transitions
        When:  it is compared to the park dwell
        Then:  they are different numbers

        The story forbids reusing `debounceSec` for this: Park is a persistent
        state and needs its own, longer constant. ONE NUMBER ANSWERS ONE
        QUESTION. A future edit that collapses them fails here rather than
        silently re-sizing Park to 2 s.
        """
        assert gd.DEFAULT_PARK_DWELL_S != gd.DEFAULT_DEBOUNCE_S

    def test_parkGlyph_isTheExactStringTheRendererBranchesOn(self):
        """
        Given: the module's park glyph constant
        When:  it is compared to the literal the renderer tests with ===
        Then:  it is exactly "P"

        Unlike "N" this contract is NEW on both sides -- carousel.js handled
        "P" nowhere before this story. Pinned so the two halves cannot drift
        apart the way the N branch and its absent producer did for a month.
        """
        assert gd.GEAR_PARK == "P"


# ---------------------------------------------------------------------------
# THE END STATE, through the two input shapes that produce it. The STALE one is
# the case the story says a MISSING-only branch would never fire on.
# ---------------------------------------------------------------------------


class TestParkFromAbsentRpm:
    """Cold boot / never-seen RPM: the _MISSING sentinel."""

    def test_update_noRpmAtAll_heldPastTheDwell_readsPark(self):
        """
        Given: no RPM reading at all and a healthy link
        When:  that is held past parkDwellSec
        Then:  it reports an AVAILABLE reading whose gear is the string "P"
        """
        result = _holdNoRpm(_deriver(), forS=gd.DEFAULT_PARK_DWELL_S + 1.0)

        assert result.available is True
        assert result.gear == gd.GEAR_PARK
        assert result.reason == gd.REASON_PARK

    def test_update_noRpm_belowTheDwell_isNotParkYet(self):
        """
        Given: no RPM reading and a healthy link
        When:  it has held for LESS than parkDwellSec
        Then:  no Park -- the dwell is the point

        Asserted as `gear is not P` AND on the surviving typed absence, so a
        change that swaps one absence reason for another does not read as this
        test breaking.
        """
        result = _holdNoRpm(_deriver(), forS=gd.DEFAULT_PARK_DWELL_S - 5.0)

        assert result.available is False
        assert result.gear != gd.GEAR_PARK
        assert result.reason == gd.REASON_NO_DATA

    def test_update_theVeryFirstTickWithNoRpm_isNotPark(self):
        """
        Given: a freshly built deriver
        When:  its FIRST update carries no RPM
        Then:  it is a typed absence, not Park

        The dwell clock cannot start before anybody looked. A deriver that
        treated `_rpmUnusableSinceS is None` as "unusable since forever" would
        paint Park on the first tick of every boot, which is the exact opposite
        of what the dwell is for.
        """
        result = _tick(_deriver(), speed=None, rpm=None, nowS=1000.0)

        assert result.available is False
        assert result.reason == gd.REASON_NO_DATA


class TestParkFromStaleRpm:
    """The NORMAL post-drive state, and the one the story says gets missed."""

    def test_update_staleRpm_notAbsent_heldPastTheDwell_readsPark(self):
        """
        Given: an RPM reading that has AGED OUT rather than gone away
        When:  a healthy link holds that past parkDwellSec
        Then:  it reports Park

        🔴 THE LOAD-BEARING TEST IN THIS FILE. `_lastRpmReading` is never
        cleared by the orchestrator -- it ages, so `_liveValue` returns _STALE
        and not _MISSING. A P branch written against _MISSING alone fires only
        on a cold boot before any reading was taken, which is not when anybody
        is looking at the tile. This test goes red for that implementation and
        every other test in this class stays green.
        """
        deriver = _deriver()
        # A real reading taken at t=1000, then never replaced -- exactly what the
        # emitter holds after the engine stops.
        lastRpm = gd.Reading(_MEASURED_IDLE_RPM, 1000.0)
        lastSpeed = gd.Reading(0.0, 1000.0)

        result = None
        nowS = 1000.0
        while nowS <= 1000.0 + gd.DEFAULT_PARK_DWELL_S + 5.0:
            result = _tick(deriver, speed=lastSpeed, rpm=lastRpm, nowS=nowS)
            nowS += 0.25

        assert result.available is True
        assert result.gear == gd.GEAR_PARK

    def test_update_theRealKeyOffDelay_isTheDwellPlusTheFreshnessWindow(self):
        """
        Given: a live RPM reading and then nothing -- the key turned off
        When:  exactly parkDwellSec has elapsed since the last reading
        Then:  still no Park; it arrives a freshness window later

        A PROPERTY WORTH STATING RATHER THAN DISCOVERING. The dwell clock starts
        when RPM becomes UNUSABLE, and a PRESENT reading does not become
        unusable until it ages out -- so the real key-off-to-glyph delay is
        `parkDwellSec + maxAgeSec`, NOT `parkDwellSec` alone.

        🔴 US-686 MOVED THIS NUMBER, EXACTLY AS US-687-b PREDICTED IT WOULD. The
        freshness window went 2.0 -> 3.0 s, so the real delay is now **23 s, not
        22 s and not 20 s.** That is the whole reason this property is pinned as
        arithmetic on the two constants rather than as a literal: the assertions
        below needed no edit, and only this prose did.

        The direction is SAFE (it lengthens the gap a bus stall must exceed by a
        further second) and 23 s is still well inside the ~45 s pre-shutdown
        ceiling. But the ceiling argument is arithmetic on this number, so the
        number has to be the true one: whoever re-checks the dwell after
        `totalCap` changes must re-check the SUM, and must recompute it rather
        than trust any figure written down here.
        """
        deriver = _deriver()
        lastRpm = gd.Reading(_MEASURED_IDLE_RPM, 1000.0)
        lastSpeed = gd.Reading(0.0, 1000.0)

        def _at(nowS):
            return _tick(deriver, speed=lastSpeed, rpm=lastRpm, nowS=nowS)

        atTheDwell = None
        nowS = 1000.0
        while nowS <= 1000.0 + gd.DEFAULT_PARK_DWELL_S:
            atTheDwell = _at(nowS)
            nowS += 0.25
        assert atTheDwell.gear != gd.GEAR_PARK

        later = 1000.0 + gd.DEFAULT_PARK_DWELL_S + gd.DEFAULT_MAX_AGE_S + 0.5
        while nowS <= later:
            result = _at(nowS)
            nowS += 0.25

        assert result.gear == gd.GEAR_PARK

    def test_update_theStaleFixtureIsGenuinelyStaleAndNotAbsent(self):
        """
        Given: the aged reading the test above feeds
        When:  it is judged one tick past the freshness window
        Then:  the deriver calls it STALE, not missing

        A GUARD ON THE FIXTURE, NOT ON THE CODE (US-687-a's technique). The
        test above is only worth something because its RPM reading is PRESENT
        and OLD. If a later edit "tidies" it to `None`, that test still passes
        and quietly stops testing the branch it was written for.
        """
        deriver = _deriver()
        justStale = 1000.0 + gd.DEFAULT_MAX_AGE_S + 0.1
        result = _tick(
            deriver,
            speed=gd.Reading(0.0, justStale),
            rpm=gd.Reading(_MEASURED_IDLE_RPM, 1000.0),
            nowS=justStale,
        )

        assert result.reason == gd.REASON_STALE, (
            "the fixture is no longer exercising the STALE path, so the "
            "post-drive Park test above has stopped measuring what it names"
        )


# ---------------------------------------------------------------------------
# THE LINK CONDITION. The 2026-09-04 loose-dongle incident is the reason it
# exists, and a flapping link is not evidence of parking.
# ---------------------------------------------------------------------------


class TestParkRequiresAHealthyLink:
    """`linkHealthy = obdAvailable and linkState == OBD_LINKED`."""

    def test_update_noRpm_withAnUnhealthyLink_neverReadsPark(self):
        """
        Given: no RPM and a link that is NOT healthy -- the 2026-09-04 incident
        When:  it is held far past the dwell
        Then:  no Park, ever

        On 2026-09-04 a loose dongle gave `Connected: no` with 41 failed
        attempts. Without this condition the panel would have read PARK through
        two days of a capture outage: a confident glyph manufactured out of a
        broken connector.
        """
        result = _holdNoRpm(
            _deriver(), forS=gd.DEFAULT_PARK_DWELL_S * 3.0, linkHealthy=False
        )

        assert result.available is False
        assert result.gear != gd.GEAR_PARK

    def test_update_linkHealthyDefaultsToFalse_soAForgetfulCallerGetsNoPark(self):
        """
        Given: a caller that does not pass linkHealthy at all
        When:  no RPM is held far past the dwell
        Then:  no Park

        The default is FAIL-SAFE by choice. Every pre-US-687-b call site in the
        tree omits the argument, and the safe direction for a glyph that claims
        the car is switched off is to stay dark rather than to appear on a
        caller that never considered the question.
        """
        deriver = _deriver()
        result = None
        nowS = 1000.0
        while nowS <= 1000.0 + gd.DEFAULT_PARK_DWELL_S * 2.0:
            result = deriver.update(speed=None, rpm=None, nowS=nowS)
            nowS += 0.25

        assert result.gear != gd.GEAR_PARK

    def test_update_linkGoesHealthyLate_parkStillNeedsTheFullDwell(self):
        """
        Given: RPM missing throughout, but the link only becomes healthy late
        When:  the link has been healthy for less than the dwell
        Then:  still no Park

        The dwell measures how long RPM has been unusable, and a link that has
        only just steadied is not a reason to shorten it. Written because the
        tempting implementation restarts the clock on the link instead, which
        would make a FLAPPING link postpone Park forever -- the opposite error,
        invisible to every other test here.
        """
        deriver = _deriver()
        result = None
        nowS = 1000.0
        while nowS <= 1000.0 + gd.DEFAULT_PARK_DWELL_S + 5.0:
            healthy = nowS >= 1000.0 + gd.DEFAULT_PARK_DWELL_S
            result = _tick(deriver, speed=None, rpm=None, nowS=nowS,
                           linkHealthy=healthy)
            nowS += 0.25

        assert result.gear == gd.GEAR_PARK, (
            "the dwell must time the RPM outage, not the link's steadiness"
        )


# ---------------------------------------------------------------------------
# THE IN-DRIVE BUS STALL -- the failure mode that makes this change worse than
# no change if the dwell is got wrong.
# ---------------------------------------------------------------------------


class TestTheInDriveBusStall:
    """A stall is not a parking event, and the dwell is the only thing that
    tells them apart."""

    def _movingSpeed(self, _nowS):
        return gd.Reading(_MOVING_SPEED_KPH, _nowS)

    def test_update_thirteenSecondStallAtSpeed_doesNotReadPark(self):
        """
        Given: a 13 s RPM outage -- the WORST gap measured over 2,141 samples
        When:  the link is healthy and SPEED is still reporting 45 km/h
        Then:  no Park

        This is the whole reason the dwell is 20 s and not 5.
        """
        result = _holdNoRpm(
            _deriver(), forS=_WORST_MEASURED_RPM_GAP_S, speed=self._movingSpeed
        )

        assert result.gear != gd.GEAR_PARK

    def test_update_theSameStallHeldPastTheDwell_doesReadPark(self):
        """
        Given: the identical fixture, held past parkDwellSec instead
        When:  the link is still healthy and SPEED is still 45 km/h
        Then:  Park

        🔴 WHY THIS TEST EXISTS. Without it the 13 s test above passes for an
        implementation that refuses Park whenever SPEED > 0 -- a condition
        nobody ruled, which would make the dwell decorative and the 13 s figure
        irrelevant. An assertion that can only be satisfied one way is not
        evidence (US-635).

        It also records the DESIGN PROPERTY the story states out loud: RPM and
        SPEED share one transport, so `RPM absent` means *engine off OR link
        down*, and a sufficiently long outage renders P. The link condition
        narrows that; it does not remove it.
        """
        result = _holdNoRpm(
            _deriver(),
            forS=gd.DEFAULT_PARK_DWELL_S + 5.0,
            speed=self._movingSpeed,
        )

        assert result.gear == gd.GEAR_PARK

    def test_update_rpmReturning_resetsTheDwellClock(self):
        """
        Given: an 18 s outage, one good RPM sample, then another 18 s outage
        When:  each outage alone is shorter than the dwell
        Then:  no Park at any point

        Neither stall earns Park and they must not ADD UP. An implementation
        that accumulated total unusable time instead of timing the CURRENT
        outage would paint Park on a flaky link that never once went quiet for
        20 s.
        """
        deriver = _deriver()
        speed = gd.Reading(_MOVING_SPEED_KPH, 1000.0)

        result = _holdNoRpm(deriver, forS=18.0, speed=self._movingSpeed,
                            startS=1000.0)
        assert result.gear != gd.GEAR_PARK

        # One good sample -- the link coughs back into life.
        _tick(deriver, speed=gd.Reading(_MOVING_SPEED_KPH, 1018.5),
              rpm=gd.Reading(_MOVING_RPM, 1018.5), nowS=1018.5)

        result = _holdNoRpm(deriver, forS=18.0, speed=self._movingSpeed,
                            startS=1019.0)
        assert result.gear != gd.GEAR_PARK
        assert speed is not None  # fixture is present, not an accidental None


# ---------------------------------------------------------------------------
# PRECEDENCE. Every neighbour P must not steal a case from.
# ---------------------------------------------------------------------------


class TestParkPrecedence:
    """P is one row of a state table; the other rows still work."""

    def test_update_engineOff_reportingZeroRpm_readsParkNotNeutral(self):
        """
        Given: RPM 0 and SPEED 0, both PRESENT and fresh -- the ECU answering
               with the engine not turning
        When:  the deriver is updated
        Then:  Park, not Neutral

        🔴 THE NEGATIVE CASE THE STORY STATES: a car that is OFF is not in
        neutral. US-687-a's branch requires `rpm > 0` precisely so this case
        could be claimed here.

        NO DWELL ON THIS BRANCH, and that is a decision rather than an
        oversight: a fresh, PRESENT zero is the ECU affirmatively reporting a
        stopped engine, not an absence that might be a bus stall. The dwell
        exists only to disambiguate absence.
        """
        result = _tick(_deriver(), speed=gd.Reading(0.0, 1000.0),
                       rpm=gd.Reading(0.0, 1000.0), nowS=1000.0)

        assert result.available is True
        assert result.gear == gd.GEAR_PARK
        assert result.reason == gd.REASON_PARK

    def test_update_measuredIdleAtAStandstill_stillReadsNeutralNotPark(self):
        """
        Given: RPM 800 and SPEED 0 -- the CIO at a stoplight
        When:  the deriver is updated
        Then:  N, NOT P -- US-687-a's branch is not regressed

        Pinned at the measured idle average (800, below the 900 floor) for the
        same reason US-687-a pinned it there: a fixture at 1,200 rpm passes for
        an implementation this car would fail.
        """
        result = _tick(_deriver(), speed=gd.Reading(0.0, 1000.0),
                       rpm=gd.Reading(_MEASURED_IDLE_RPM, 1000.0), nowS=1000.0)

        assert result.gear == gd.GEAR_NEUTRAL
        assert result.reason == gd.REASON_NEUTRAL

    def test_update_aDerivedGear_isNotDisplacedByPark(self):
        """
        Given: 2500 rpm at 45 km/h, held past the debounce, healthy link
        When:  the deriver is updated
        Then:  the derived gear, with no Park anywhere near it
        """
        deriver = _deriver()
        _tick(deriver, speed=gd.Reading(_MOVING_SPEED_KPH, 1000.0),
              rpm=gd.Reading(_MOVING_RPM, 1000.0), nowS=1000.0)
        later = 1000.0 + gd.DEFAULT_DEBOUNCE_S + 0.1
        result = _tick(deriver, speed=gd.Reading(_MOVING_SPEED_KPH, later),
                       rpm=gd.Reading(_MOVING_RPM, later), nowS=later)

        assert result.available is True
        assert result.gear == 2
        assert result.reason == gd.REASON_ENGAGED

    def test_update_notCalibrated_stillDominatesPark(self):
        """
        Given: a deriver with NO band table, no RPM, a healthy link
        When:  that is held far past the dwell
        Then:  `not_calibrated`, not Park

        THE SAME PRECEDENCE DECISION US-687-a MADE FOR N, MADE THE SAME WAY AND
        FOR THE SAME REASON. Park needs no band table, so an uncalibrated
        deriver COULD report it -- but the module's standing rule is that a
        config error fails fast and plainly, and a tile that lit whenever the
        car was off while staying dark every time it moved would look like a
        working feature while the real defect stayed invisible.
        """
        result = _holdNoRpm(
            _deriver(bands=()), forS=gd.DEFAULT_PARK_DWELL_S * 2.0
        )

        assert result.available is False
        assert result.reason == gd.REASON_NOT_CALIBRATED

    def test_update_park_clearsTheDebounceCandidate(self):
        """
        Given: a settled 2nd gear, then a switch-off long enough to read Park
        When:  a single moving sample arrives again
        Then:  the deriver is SETTLING, not republishing the pre-park 2

        Same claim US-687-a pinned for N, and it matters more here: pulling away
        after a stop is exactly when a stale candidate would resurface, and a
        gear the car is not yet in is the one thing this producer must never
        print.
        """
        deriver = _deriver()
        _tick(deriver, speed=gd.Reading(_MOVING_SPEED_KPH, 1000.0),
              rpm=gd.Reading(_MOVING_RPM, 1000.0), nowS=1000.0)
        settledS = 1000.0 + gd.DEFAULT_DEBOUNCE_S + 0.1
        assert _tick(deriver, speed=gd.Reading(_MOVING_SPEED_KPH, settledS),
                     rpm=gd.Reading(_MOVING_RPM, settledS),
                     nowS=settledS).gear == 2

        parked = _holdNoRpm(deriver, forS=gd.DEFAULT_PARK_DWELL_S + 2.0,
                            startS=settledS)
        assert parked.gear == gd.GEAR_PARK

        restartS = settledS + gd.DEFAULT_PARK_DWELL_S + 5.0
        result = _tick(deriver, speed=gd.Reading(_MOVING_SPEED_KPH, restartS),
                       rpm=gd.Reading(_MOVING_RPM, restartS), nowS=restartS)

        assert result.available is False
        assert result.reason == gd.REASON_SETTLING

    def test_update_park_isNotDebounced(self):
        """
        Given: RPM unusable for exactly the dwell, and not a moment more
        When:  the deriver is updated
        Then:  Park is published immediately, with no further settling window

        The dwell IS the wait. Stacking debounceSec on top of it would silently
        add another debounce window to the delay and put the ceiling argument
        out by that much of a 45 s budget. (The figure that used to sit here was
        invalidated by US-686 raising maxAgeSec, which is why it is now stated as
        the relationship rather than as a number -- see
        test_update_theRealKeyOffDelay_isTheDwellPlusTheFreshnessWindow.)
        """
        result = _holdNoRpm(_deriver(), forS=gd.DEFAULT_PARK_DWELL_S,
                            stepS=gd.DEFAULT_PARK_DWELL_S)

        assert result.gear == gd.GEAR_PARK


# ---------------------------------------------------------------------------
# CONFIG. The value is injectable, and the injected one is what runs.
# ---------------------------------------------------------------------------


class TestParkDwellIsConfigurable:
    """`pi.gear.parkDwellSec` reaches the deriver."""

    def test_createGearDeriverFromConfig_readsParkDwellSec(self):
        """
        Given: a config whose pi.gear.parkDwellSec is not the module default
        When:  the deriver is built from it
        Then:  the CONFIGURED dwell is what governs, not the default

        Asserted through BEHAVIOUR rather than by reading a private attribute:
        a wiring that stored the value and then ignored it would pass an
        attribute check and fail the car.
        """
        config = {
            "pi": {
                "gear": {
                    "enabled": True,
                    "bands": [{"gear": 1, "ratioMin": 90.0, "ratioMax": 125.0}],
                    "parkDwellSec": 5.0,
                }
            }
        }
        deriver = gd.createGearDeriverFromConfig(config)
        assert deriver is not None

        result = _holdNoRpm(deriver, forS=6.0)

        assert result.gear == gd.GEAR_PARK, (
            "a 5 s configured dwell did not govern -- the module default is 20 s "
            "and this outage is only 6 s long"
        )

    def test_createGearDeriverFromConfig_absentKeyFallsBackToTheRuledDefault(self):
        """
        Given: a config with no parkDwellSec at all -- a hand-edited install
        When:  the deriver is built
        Then:  a 6 s outage does NOT read Park; the 20 s default governs

        The install that gets the wrong number is the fresh or hand-edited one
        where the key is missing, so the fallback is tested as behaviour too.
        """
        config = {
            "pi": {
                "gear": {
                    "enabled": True,
                    "bands": [{"gear": 1, "ratioMin": 90.0, "ratioMax": 125.0}],
                }
            }
        }
        deriver = gd.createGearDeriverFromConfig(config)
        assert deriver is not None

        assert _holdNoRpm(deriver, forS=6.0).gear != gd.GEAR_PARK


# ---------------------------------------------------------------------------
# The published shape. `gear` is now int | str | None with TWO string members.
# ---------------------------------------------------------------------------


def test_toStateDict_park_carriesTheStringGlyphAndTheParkReason():
    """
    Given: a Park reading
    When:  it is serialised for states/gear
    Then:  the dict carries "P" and the machine token `park`

    The RENDERER turns `park` into driver English (US-687-a's rule: humanise at
    the renderer, never at the producer), so the state file must keep the exact
    token for tests, logs and any future consumer.
    """
    reading = _holdNoRpm(_deriver(), forS=gd.DEFAULT_PARK_DWELL_S + 1.0)

    assert reading.toStateDict() == {
        "available": True,
        "gear": "P",
        "reason": gd.REASON_PARK,
    }
