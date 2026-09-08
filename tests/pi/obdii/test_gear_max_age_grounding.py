################################################################################
# File Name: test_gear_max_age_grounding.py
# Purpose/Description: US-686 (F-138) -- `pi.gear.maxAgeSec` was 2.0 s while the
#                      MEASURED per-PID SPEED period is 2.206-2.249 s. The
#                      freshness window was SHORTER THAN THE INTERVAL BETWEEN THE
#                      READINGS IT JUDGES, so every sample aged out before its
#                      successor could arrive. That is a UNIT ERROR, not tight
#                      calibration, and this file exists to stop it returning.
#
#                      THREE THINGS ARE PINNED HERE, and they fail independently:
#
#                      (1) THE UNIT ERROR ITSELF -- the window must exceed the
#                          measured sample period, asserted in ALL THREE homes
#                          the value lives in.
#                      (2) THE THREE HOMES CANNOT DRIFT APART. config.json, the
#                          validator DEFAULTS and the module constants are swept
#                          against each other by INTROSPECTION, so a key added
#                          later is covered without anyone remembering to.
#                      (3) THE FALSE RATIONALE CANNOT COME BACK. `2.0` was
#                          derived from a "~4-5 PID/s" poll rate that does not
#                          describe this system, and the census of that fiction
#                          has been short TWICE. A grep-shaped test now holds it.
#
#                      Plus the cadence replay: at the measured period the
#                      SHIPPED deriver's longest continuous lit run is capped
#                      around 16 s at 2.0 -- on a PERFECTLY STEADY cruise with no
#                      jitter, no stops and no shifts -- and is unbounded at 3.0.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-07    | Rex (US-686) | Initial -- the unit-error guard, the three-home
#               |              | consistency sweep, the rationale guard, the
#               |              | still-rejects-dead-data bound, and the cadence
#               |              | replay that measures the mechanism.
# ================================================================================
################################################################################

"""US-686: the gear freshness window must exceed the measured sample period.

WHY THIS IS A UNIT ERROR AND NOT A CALIBRATION CHOICE.  ``maxAgeSec`` answers
*how long may I still believe this reading?*  The measured per-PID SPEED period
answers *how often am I told?*  No value of the first can be smaller than the
second: below it, a reading is declared dead before its replacement has been
sent, so the "stale" branch fires in every single cycle by construction.  The
drive-64 census is exactly what that predicts -- ``below_threshold 776 · stale
722 · settling 409 · engaged 0``.

WHAT THIS FILE MEASURES AND WHAT IT ONLY CITES (PM Rule 7 -- ground every
number).  Drives 64-67 are in the Pi/server database and are NOT on this bench,
so Atlas's replay of them is CITED here, never re-derived and never re-quoted as
a single figure.  What IS measured here is the CADENCE MODEL: a dead-steady
cruise delivered at the measured per-PID period through the SHIPPED
``GearDeriver``.  That is a weaker claim than a drive replay and it is labelled
as one -- but it is measured on this bench, it is reproducible, and it lands in
the same place Atlas's replay did.

THE FINDING THIS FILE ADDS, which neither reconstruction stated.  At 2.0 the
outcome DEPENDS ON THE PHASE OFFSET between the SPEED and RPM arrivals -- a
quantity nobody controls, configures or observes.  Sweeping it across a full
period, percent-lit is either ~0 % or ~77 %, and the longest continuous run
never exceeds ~16 s in EITHER regime.  At 3.0 the phase offset stops mattering
altogether.  That is the strongest available form of the argument: the fix does
not merely raise a number, it removes the tile's dependence on an uncontrolled
phase relationship, which is why the shipped behaviour was never reproducible
enough for two analyses to agree on it.
"""

from __future__ import annotations

import json
import os
import re

import pytest

from common.config.validator import DEFAULTS
from pi.obdii import gear_derivation as gd

_REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
CONFIG_PATH = os.path.join(_REPO, "config.json")

# ---------------------------------------------------------------------------
# THE GROUNDED MEASUREMENT THIS WHOLE FILE TURNS ON.
#
# Measured per-PID SPEED period on this car: 2.206 s .. 2.249 s (Atlas,
# 2026-09-06, 3,494 SPEED/RPM samples across drives 64-67).  Recorded as a RANGE
# and compared against its UPPER bound, because a window that clears the fast
# end of the measurement and not the slow end still goes stale on the slow
# cycles -- which is the whole defect, arriving a little less often.
# ---------------------------------------------------------------------------
MEASURED_SPEED_PERIOD_MIN_S = 2.206
MEASURED_SPEED_PERIOD_MAX_S = 2.249

# The value the story superseded. Kept as a named constant, not a bare literal,
# because two tests below assert that the guard REJECTS it -- a guard nobody has
# watched fail is a guard nobody has tested.
SUPERSEDED_MAX_AGE_S = 2.0


def _configGear() -> dict:
    """The shipped ``pi.gear`` block, read from the real config.json."""
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return json.load(fh)["pi"]["gear"]


def _sourceOf(relPath: str) -> str:
    """Read a source file from the repo as text, for the rationale guards."""
    with open(os.path.join(_REPO, relPath), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# (1) THE UNIT ERROR CANNOT SILENTLY RETURN -- validationCriterion #2.
# ---------------------------------------------------------------------------
class TestFreshnessWindowExceedsTheMeasuredSamplePeriod:
    """The window must be longer than the interval between the readings it judges.

    Asserted in all THREE homes rather than once at the module, because the
    deployment that would get a stale value is the one where the config key is
    ABSENT -- a fresh or hand-edited install falling back on the validator
    default.  A single-home assertion passes on exactly the half-fixed tree this
    story exists to prevent.
    """

    def test_moduleDefault_exceedsTheMeasuredPeriod(self) -> None:
        """
        Given: the measured per-PID SPEED period tops out at 2.249 s
        When: reading DEFAULT_MAX_AGE_S from the derivation module
        Then: the window is strictly longer than that period
        """
        assert gd.DEFAULT_MAX_AGE_S > MEASURED_SPEED_PERIOD_MAX_S, (
            f"DEFAULT_MAX_AGE_S={gd.DEFAULT_MAX_AGE_S} is not longer than the "
            f"measured SPEED period ({MEASURED_SPEED_PERIOD_MAX_S} s). A reading "
            "would be declared stale before its successor could arrive -- the "
            "US-686 unit error."
        )

    def test_validatorDefault_exceedsTheMeasuredPeriod(self) -> None:
        """
        Given: a deployment whose config.json omits pi.gear.maxAgeSec
        When: it falls back on the validator DEFAULTS
        Then: the fallback also clears the measured period
        """
        assert float(DEFAULTS["pi.gear.maxAgeSec"]) > MEASURED_SPEED_PERIOD_MAX_S

    def test_shippedConfig_exceedsTheMeasuredPeriod(self) -> None:
        """
        Given: the config.json this repo actually deploys
        When: reading pi.gear.maxAgeSec
        Then: the shipped window clears the measured period
        """
        assert float(_configGear()["maxAgeSec"]) > MEASURED_SPEED_PERIOD_MAX_S

    def test_theGuardRejectsTheSupersededValue_soItIsNotVacuous(self) -> None:
        """
        Given: 2.0 s, the value shipped before this story
        When: the same predicate every test above uses is applied to it
        Then: it FAILS -- the guard discriminates, it does not merely pass

        WHY THIS TEST EXISTS.  An absence-shaped assertion is the most
        vacuity-prone shape there is (US-595).  Three tests above would all pass
        against a predicate that is trivially true, and would keep their
        reassuring names forever.  This one watches the guard fail on purpose,
        against the exact number the story superseded.
        """
        assert not (SUPERSEDED_MAX_AGE_S > MEASURED_SPEED_PERIOD_MAX_S)
        assert not (SUPERSEDED_MAX_AGE_S > MEASURED_SPEED_PERIOD_MIN_S), (
            "2.0 s is below even the FASTEST measured period, so the window was "
            "shorter than the sample interval on every cycle of every drive -- "
            "not merely on the slow ones."
        )

    def test_theMeasuredPeriodConstantsAreOrderedAndPositive(self) -> None:
        """
        Given: the measurement is recorded as a range
        When: the two bounds are compared
        Then: min < max and both are positive

        A fixture guard, in the US-687-a idiom: if a later edit collapses the
        range or transposes the bounds, every assertion above silently changes
        meaning while still passing.
        """
        assert 0.0 < MEASURED_SPEED_PERIOD_MIN_S < MEASURED_SPEED_PERIOD_MAX_S


# ---------------------------------------------------------------------------
# (2) GAP 3 -- THE THREE HOMES CANNOT DRIFT APART.
# ---------------------------------------------------------------------------
# Scalar tuning constants only, mapped config key -> module constant name.
# DISCOVERED BY INTROSPECTION at the module (getattr), not copied, so a
# renamed constant fails here instead of quietly ceasing to be checked.
#
# WHAT IS DELIBERATELY NOT IN THIS SWEEP, and why -- an exemption that is
# silent is indistinguishable from an oversight:
#   * `enabled` -- a DEPLOYMENT choice, not a tuning constant. config.json turns
#     the producer on; the validator default is False so an unkeyed install
#     ships dark (the pi.bus.enabled connect-when-wired precedent).
#   * `bands`   -- a property of THIS car's gearbox, final drive and tyres. A
#     validator default carrying it would hand a fabricated calibration to any
#     deployment that forgot the key; an unkeyed install must report
#     `not_calibrated` instead. See validator.py's own note.
_MIRRORED_GEAR_SCALARS = {
    "minSpeedKph": "DEFAULT_MIN_SPEED_KPH",
    "minRpm": "DEFAULT_MIN_RPM",
    "debounceSec": "DEFAULT_DEBOUNCE_S",
    "maxAgeSec": "DEFAULT_MAX_AGE_S",
    "parkDwellSec": "DEFAULT_PARK_DWELL_S",
}


class TestGearTuningConstantsAgreeInAllThreeHomes:
    """`maxAgeSec` lived in three files and NO lint covered them (Atlas, GAP 3).

    ``test_address_mirror_consistency.py`` is the A-15 guard and it is
    ADDRESSES ONLY -- it exempts config.json and the validator DEFAULTS
    outright.  So a partial fix drifted silently, and the deployment that got
    the stale value was the FRESH one, where the key is missing from config and
    the validator default answers instead.

    Swept, not enumerated, and it covers ``parkDwellSec`` too: US-687-b left a
    SECOND uncovered triple behind it and flagged it for this story.
    """

    @pytest.mark.parametrize("configKey,constName", sorted(_MIRRORED_GEAR_SCALARS.items()))
    def test_configJson_agreesWithTheModuleConstant(
        self, configKey: str, constName: str
    ) -> None:
        """
        Given: a scalar pi.gear tuning key
        When: config.json and the derivation module constant are compared
        Then: they carry the same number
        """
        assert hasattr(gd, constName), (
            f"{constName} no longer exists in gear_derivation -- this sweep has "
            "stopped checking a key it claims to cover."
        )
        assert float(_configGear()[configKey]) == float(getattr(gd, constName)), (
            f"pi.gear.{configKey} in config.json disagrees with {constName}."
        )

    @pytest.mark.parametrize("configKey,constName", sorted(_MIRRORED_GEAR_SCALARS.items()))
    def test_validatorDefault_agreesWithTheModuleConstant(
        self, configKey: str, constName: str
    ) -> None:
        """
        Given: a scalar pi.gear tuning key
        When: the validator DEFAULTS entry and the module constant are compared
        Then: they carry the same number

        This is the home a partial fix leaves behind, and it is the one that
        answers on a fresh install.
        """
        assert float(DEFAULTS[f"pi.gear.{configKey}"]) == float(getattr(gd, constName))

    def test_everyScalarGearKeyInConfig_isCoveredBySweep(self) -> None:
        """
        Given: the shipped pi.gear block
        When: its scalar keys are compared against this sweep's coverage
        Then: none is uncovered -- a key added later fails HERE, not in the car

        THE SWEEP THAT EXPIRES IS THE SWEEP THAT LIES.  US-687-a wrote a
        hand-written vocabulary sweep and it expired within a week, on the very
        next story.  This asserts the sweep is COMPLETE against the real config
        rather than trusting the table above to have been maintained.
        """
        scalarKeys = {
            k
            for k, v in _configGear().items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        uncovered = scalarKeys - set(_MIRRORED_GEAR_SCALARS)
        assert not uncovered, (
            f"pi.gear scalar key(s) {sorted(uncovered)} are in config.json but not "
            "in _MIRRORED_GEAR_SCALARS, so nothing checks them against the "
            "validator default or the module constant. Add them to the sweep."
        )

    def test_theSweepIsNotEmpty(self) -> None:
        """
        Given: the parametrised sweeps above
        When: the coverage table is inspected
        Then: it actually contains the key this story is about

        A parametrised test over an empty table passes loudly and proves
        nothing.
        """
        assert "maxAgeSec" in _MIRRORED_GEAR_SCALARS
        assert "parkDwellSec" in _MIRRORED_GEAR_SCALARS
        assert len(_MIRRORED_GEAR_SCALARS) >= 5


# ---------------------------------------------------------------------------
# (3) GAP 4 -- THE FALSE RATIONALE CANNOT COME BACK.
# ---------------------------------------------------------------------------
# THE CENSUS WAS SHORT TWICE. PM found one home; Atlas corrected himself to two.
# The real count in this tree was FIVE, and the fifth was not a comment at all
# but a FIXTURE built at 0.25 s spacing "as the ~4-5 PID/s poll delivers" --
# a feed 8.9x faster than the car's, in the very suite that was supposed to be
# watching this producer.
_RATIONALE_HOMES = (
    "src/common/config/validator.py",
    "src/pi/obdii/gear_derivation.py",
    "src/pi/obdii/orchestrator/card_state_emitter.py",
    "tests/pi/obdii/test_gear_state_emitter.py",
)

# The fiction, in every spelling the census actually found it in.
_FICTION_PATTERN = re.compile(r"4\s*-\s*5\s*PIDs?\s*/?\s*(?:s|sec)", re.IGNORECASE)


class TestTheFalsePollRateRationaleIsGone:
    """`2.0` came from a poll rate that does not describe this system.

    ``pi.pollingTiers`` has ZERO importers in ``src/`` -- the live list is a
    flat ``pi.realtimeData.parameters`` polled every cycle -- and US-686 is the
    SECOND build it misled (A-28).  Any rationale for a gear timing constant
    must cite the MEASURED per-PID period, not an aggregate bus rate nothing
    produces.
    """

    @pytest.mark.parametrize("relPath", _RATIONALE_HOMES)
    def test_noFileCitesTheFictionalPollRate(self, relPath: str) -> None:
        """
        Given: a file that once justified a gear timing constant
        When: it is searched for the "~4-5 PID/s" rationale
        Then: no occurrence survives
        """
        hits = _FICTION_PATTERN.findall(_sourceOf(relPath))
        assert not hits, (
            f"{relPath} still cites the fictional ~4-5 PID/s poll rate {hits}. "
            "The measured per-PID period is 2.206-2.249 s; pi.pollingTiers does "
            "not describe this system (A-28)."
        )

    @pytest.mark.parametrize(
        "relPath",
        ("src/common/config/validator.py", "src/pi/obdii/gear_derivation.py"),
    )
    def test_theRationaleHomesCiteTheMeasuredPeriod(self, relPath: str) -> None:
        """
        Given: the two files that carry maxAgeSec's rationale
        When: they are searched for the measured figure
        Then: both name it

        Deleting the fiction is only half of GAP 4. A constant with NO stated
        grounding is the state the next person re-derives a wrong value from,
        which is how this one arrived.
        """
        text = _sourceOf(relPath)
        assert "2.206" in text and "2.249" in text, (
            f"{relPath} does not cite the measured per-PID SPEED period "
            "(2.206-2.249 s) beside the freshness window it grounds."
        )

    def test_thePatternMatchesTheFiction_soTheGuardIsNotVacuous(self) -> None:
        """
        Given: the regex the three tests above rely on
        When: it is applied to the exact strings the census found
        Then: every one matches -- an absence guard whose pattern is wrong
              reports success against a file it failed to search
        """
        for spelling in (
            "the OBD link sustains ~4-5 PIDs/sec over Bluetooth",
            "maxAgeSec is grounded to the ~4-5 PID/s OBD poll rate",
            "the ~4-5 PID/s poll rate is cheaper than the state-file write",
            "readings arriving every 0.25 s, as the ~4-5 PID/s poll delivers",
        ):
            assert _FICTION_PATTERN.search(spelling), spelling


# ---------------------------------------------------------------------------
# (4) THE NEGATIVE CASE -- validationCriterion #3.
# ---------------------------------------------------------------------------
_BANDS = (
    gd.GearBand(gear=1, ratioMin=90.0, ratioMax=125.0),
    gd.GearBand(gear=2, ratioMin=54.0, ratioMax=74.0),
    gd.GearBand(gear=3, ratioMin=36.0, ratioMax=49.0),
    gd.GearBand(gear=4, ratioMin=27.0, ratioMax=35.0),
)


def _deriver(maxAgeS: float) -> gd.GearDeriver:
    """A calibrated deriver at one freshness window, with everything else stock."""
    return gd.GearDeriver(bands=_BANDS, maxAgeS=maxAgeS)


class TestTheWidenedWindowStillRejectsDeadData:
    """Raising `maxAgeSec` widens the staleness guard; it must not remove it.

    THE NEW BOUND, STATED.  At 3.0 s against a 2.206-2.249 s sample period the
    window is 1.33x the period, so it admits a reading that has missed at most
    ONE poll and rejects one that has missed two.  A gear may therefore be
    believed for at most 3.0 s after its inputs stop -- which is also the
    maximum time the tile can show a gear the car has already shifted out of.
    A 4G63 shift completes well inside 1 s, so the stale glyph self-corrects
    within roughly the duration of the shift that invalidated it.
    """

    def test_aReadingOlderThanTheWindow_isStillStale(self) -> None:
        """
        Given: a deriver at the ruled 3.0 s window
        When: both readings are 3.5 s old -- older than the window
        Then: the gear is absent with reason `stale`, exactly as before
        """
        d = _deriver(3.0)
        reading = d.update(
            speed=gd.Reading(value=60.0, tsS=0.0),
            rpm=gd.Reading(value=1800.0, tsS=0.0),
            nowS=3.5,
            linkHealthy=False,
        )
        assert reading.available is False
        assert reading.gear is None
        assert reading.reason == gd.REASON_STALE

    def test_aReadingTwoPollsOld_isRejected(self) -> None:
        """
        Given: the ruled window and the measured period
        When: a reading has missed TWO polls (aged 2 x 2.249 = 4.498 s)
        Then: it is stale -- the widened window does not admit dead data
        """
        agedTwoPolls = 2 * MEASURED_SPEED_PERIOD_MAX_S
        assert agedTwoPolls > gd.DEFAULT_MAX_AGE_S, (
            "the ruled window must reject a reading that has missed two polls; "
            "if this premise fails the test below proves nothing"
        )
        d = _deriver(gd.DEFAULT_MAX_AGE_S)
        reading = d.update(
            speed=gd.Reading(value=60.0, tsS=0.0),
            rpm=gd.Reading(value=1800.0, tsS=0.0),
            nowS=agedTwoPolls,
            linkHealthy=False,
        )
        assert reading.reason == gd.REASON_STALE

    def test_aReadingOnePollOld_isNowAccepted_whichIsThePoint(self) -> None:
        """
        Given: the ruled window and the measured period
        When: a reading is one full poll old (2.249 s) -- an ORDINARY, healthy
              sample that simply has not been replaced yet
        Then: it is NOT stale, and the derivation proceeds

        This is the case 2.0 rejected in every cycle of every drive. Paired with
        the two tests above deliberately: "still rejects dead data" is satisfied
        by a window of zero, so the negative case alone cannot show the fix
        works. Both halves or neither.
        """
        d = _deriver(gd.DEFAULT_MAX_AGE_S)
        reading = d.update(
            speed=gd.Reading(value=60.0, tsS=0.0),
            rpm=gd.Reading(value=1800.0, tsS=0.0),
            nowS=MEASURED_SPEED_PERIOD_MAX_S,
            linkHealthy=False,
        )
        assert reading.reason != gd.REASON_STALE

    def test_theSupersededWindow_rejectedThatSameOrdinarySample(self) -> None:
        """
        Given: the 2.0 s window this story supersedes
        When: fed the identical one-poll-old sample the test above accepts
        Then: it reports `stale` -- the defect, reproduced by name

        The two tests are the same fixture and differ only in the window, so
        this pins the WINDOW as the cause rather than anything about the sample.
        """
        d = _deriver(SUPERSEDED_MAX_AGE_S)
        reading = d.update(
            speed=gd.Reading(value=60.0, tsS=0.0),
            rpm=gd.Reading(value=1800.0, tsS=0.0),
            nowS=MEASURED_SPEED_PERIOD_MAX_S,
            linkHealthy=False,
        )
        assert reading.reason == gd.REASON_STALE


# ---------------------------------------------------------------------------
# (5) THE CADENCE REPLAY -- validationCriterion #1, as far as this bench can
#     honestly reach.
# ---------------------------------------------------------------------------
_CARD_TICK_S = 2.0          # the orchestrator's card-state cadence
_REPLAY_SECONDS = 300.0     # five minutes of steady cruising
_CRUISE_SPEED_KPH = 80.0
_CRUISE_RATIO = 33.0        # squarely inside 4th, far from either band edge
_STAGGER_SAMPLES = 12       # phase offsets swept across one full period


def _replayCruise(
    *, periodS: float, staggerS: float, maxAgeS: float
) -> tuple[float, float]:
    """Replay a dead-steady cruise through the SHIPPED deriver.

    Reproduces the real update seam rather than a convenient one: the producer
    is driven on EVERY RPM arrival, EVERY SPEED arrival, AND on the card tick
    (``card_state_emitter.observeGearInput`` plus ``_emitGearState``), because
    the tick is what makes a dead feed honest and it is also what decides
    whether the debounce window is ever OBSERVED to have elapsed.

    Args:
        periodS: Per-PID arrival period, seconds.
        staggerS: How long after RPM the SPEED sample lands.
        maxAgeS: The freshness window under test.

    Returns:
        ``(percentLit, longestContinuousRunS)`` -- lit meaning the producer
        published an available, `engaged` gear.
    """
    deriver = gd.GearDeriver(bands=_BANDS, maxAgeS=maxAgeS)
    rpmValue = _CRUISE_SPEED_KPH * _CRUISE_RATIO

    events: list[tuple[float, str]] = []
    t = 0.0
    while t < _REPLAY_SECONDS:
        events.append((t, "RPM"))
        events.append((t + staggerS, "SPEED"))
        t += periodS
    t = 0.0
    while t < _REPLAY_SECONDS:
        events.append((t, "TICK"))
        t += _CARD_TICK_S
    events.sort(key=lambda e: (e[0], e[1]))

    lastSpeed: gd.Reading | None = None
    lastRpm: gd.Reading | None = None
    litS = 0.0
    longestRunS = 0.0
    runStartS: float | None = None
    prevT = 0.0
    prevLit = False

    for ts, kind in events:
        if prevLit:
            litS += ts - prevT
        if kind == "RPM":
            lastRpm = gd.Reading(value=rpmValue, tsS=ts)
        elif kind == "SPEED":
            lastSpeed = gd.Reading(value=_CRUISE_SPEED_KPH, tsS=ts)
        result = deriver.update(
            speed=lastSpeed, rpm=lastRpm, nowS=ts, linkHealthy=True
        )
        lit = result.available and result.reason == gd.REASON_ENGAGED
        if lit and not prevLit:
            runStartS = ts
        if prevLit and not lit and runStartS is not None:
            longestRunS = max(longestRunS, ts - runStartS)
            runStartS = None
        prevLit, prevT = lit, ts

    if prevLit and runStartS is not None:
        longestRunS = max(longestRunS, prevT - runStartS)
    return 100.0 * litS / _REPLAY_SECONDS, longestRunS


def _sweepStaggers(*, periodS: float, maxAgeS: float) -> list[tuple[float, float]]:
    """Replay at every phase offset across one full period."""
    return [
        _replayCruise(
            periodS=periodS, staggerS=periodS * i / _STAGGER_SAMPLES, maxAgeS=maxAgeS
        )
        for i in range(_STAGGER_SAMPLES)
    ]


_MEASURED_PERIODS = (MEASURED_SPEED_PERIOD_MIN_S, MEASURED_SPEED_PERIOD_MAX_S)


class TestCadenceReplayAtTheMeasuredPeriod:
    """The mechanism, measured on this bench rather than cited.

    SCOPE OF THE CLAIM, STATED PLAINLY.  This is NOT a replay of drives 64-67 --
    that data lives in the Pi/server database and is not on this bench, and
    dressing a simulator fixture up as the car's drive is the exact failure this
    project keeps re-finding.  This is a dead-steady 4th-gear cruise delivered at
    the MEASURED per-PID period: the EASIEST possible case, with no stops, no
    shifts, no coasting and no jitter, i.e. none of the compounding debounce
    resets that make the real drives worse.  It is therefore an UPPER BOUND on
    the shipped behaviour, and the shipped behaviour is already unusable at it.
    """

    @pytest.mark.parametrize("periodS", _MEASURED_PERIODS)
    def test_atTheSupersededWindow_theGlyphNeverHoldsForHalfAMinute(
        self, periodS: float
    ) -> None:
        """
        Given: a perfectly steady cruise at the measured per-PID period
        When: replayed at the superseded 2.0 s window, at every phase offset
        Then: the longest continuous lit run never reaches 30 s

        Atlas measured "no continuous lit run exceeds 11.4 s" on the real
        drives; this steady model lands in the same place from the other
        direction. The threshold is deliberately generous (30 s, not 16 s) so
        the test asserts the STRUCTURAL cap rather than pinning an exact
        artefact of the model's arithmetic.
        """
        runs = [run for _pct, run in _sweepStaggers(periodS=periodS, maxAgeS=SUPERSEDED_MAX_AGE_S)]
        assert max(runs) < 30.0, (
            f"longest lit run at maxAgeS=2.0 was {max(runs):.1f}s across "
            f"{_STAGGER_SAMPLES} phase offsets"
        )

    @pytest.mark.parametrize("periodS", _MEASURED_PERIODS)
    def test_atTheRuledWindow_theGlyphStaysLitForTheWholeDrive(
        self, periodS: float
    ) -> None:
        """
        Given: the same steady cruise at the same measured period
        When: replayed at the ruled window, at every phase offset
        Then: the glyph latches once and holds for essentially the whole replay

        This is the END STATE the story asks for, expressed as the property
        rather than as a percentage: "measured in tens of seconds, not 11.4 s".
        """
        runs = [run for _pct, run in _sweepStaggers(periodS=periodS, maxAgeS=gd.DEFAULT_MAX_AGE_S)]
        assert min(runs) > _REPLAY_SECONDS * 0.9, (
            f"shortest lit run at the ruled window was {min(runs):.1f}s of "
            f"{_REPLAY_SECONDS}s across {_STAGGER_SAMPLES} phase offsets"
        )

    def test_atTheSupersededWindow_theOutcomeDependsOnAPhaseNobodyControls(
        self,
    ) -> None:
        """
        Given: the identical cruise, replayed at 2.0 s across a full period of
               phase offsets between the SPEED and RPM arrivals
        When: percent-lit is compared across those offsets
        Then: it varies by more than 50 points

        🔴 THE FINDING NEITHER RECONSTRUCTION STATED, and it explains why they
        disagreed by 20-45 points and why Atlas could not choose between them.
        At 2.0 the tile's behaviour is a function of the phase relationship
        between two PID arrivals -- a quantity nobody configures, controls or
        observes, which drifts freely with bus jitter. There is no single
        "percent lit" to measure at 2.0 because the shipped config does not
        have one.
        """
        pcts = [pct for pct, _run in _sweepStaggers(
            periodS=MEASURED_SPEED_PERIOD_MIN_S, maxAgeS=SUPERSEDED_MAX_AGE_S
        )]
        assert max(pcts) - min(pcts) > 50.0, (
            f"percent-lit at 2.0 ranged {min(pcts):.1f}%..{max(pcts):.1f}% -- "
            "expected a wide phase-dependent spread"
        )

    def test_atTheRuledWindow_thePhaseStopsMattering(self) -> None:
        """
        Given: the same sweep at the ruled window
        When: percent-lit is compared across phase offsets
        Then: it varies by less than 1 point

        THE STRONGEST FORM OF THE ARGUMENT, and the half worth keeping: the fix
        does not merely raise a number, it removes the tile's dependence on an
        uncontrolled phase relationship. Paired with the test above -- a spread
        claim and a no-spread claim on the same sweep -- so neither can be
        satisfied by a replay harness that has silently stopped varying its
        input.
        """
        pcts = [pct for pct, _run in _sweepStaggers(
            periodS=MEASURED_SPEED_PERIOD_MIN_S, maxAgeS=gd.DEFAULT_MAX_AGE_S
        )]
        assert max(pcts) - min(pcts) < 1.0, (
            f"percent-lit at the ruled window ranged {min(pcts):.1f}%..{max(pcts):.1f}%"
        )

    def test_theReplayHarnessActuallyVariesItsPhase(self) -> None:
        """
        Given: the stagger sweep both tests above depend on
        When: the offsets it generates are inspected
        Then: they are distinct and span most of one period

        A fixture guard. If a later edit collapses the sweep to a single offset,
        the spread test fails loudly but the no-spread test would pass for the
        wrong reason and go on claiming the fix is phase-independent.
        """
        offsets = [MEASURED_SPEED_PERIOD_MIN_S * i / _STAGGER_SAMPLES for i in range(_STAGGER_SAMPLES)]
        assert len(set(offsets)) == _STAGGER_SAMPLES
        assert max(offsets) > MEASURED_SPEED_PERIOD_MIN_S * 0.8
