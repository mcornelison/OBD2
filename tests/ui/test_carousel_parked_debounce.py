################################################################################
# File Name: test_carousel_parked_debounce.py
# Purpose/Description: US-511 tests for the DEBOUNCED `parked` signal that gates
#   the context-aware `⋮` kebab (specs/UI/dist/dashboard-pi/carousel.js). US-490
#   keyed the affordance off the raw system-status `idle` SSOT boolean, so every
#   brief OBD-availability blip flipped the button in and out of existence. This
#   story inserts a hysteresis debounce between the emitter's flag and the menu
#   policy: parked = idle held true for >= parkedOnS, reverting only after idle
#   false for >= parkedOffS. The two thresholds differ ON PURPOSE -- slow to
#   OFFER the single-tap path into a service stop, quick to WITHDRAW it.
#   Drives the pure reducer through the node probe (carousel_probe.js) and
#   guards the wiring by source inspection -- a debouncer the poll never
#   advances is inert, and one whose state is re-initialised every tick can
#   never accumulate a hold.
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)  | Initial -- US-511 debounced parked signal.
# ================================================================================
################################################################################

"""US-511 tests for the debounced `parked` signal behind the kebab (via node)."""

import json
import os
import shutil
import subprocess

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "specs", "UI", "dist", "dashboard-pi"
)
_JS = os.path.join(_DIST, "carousel.js")
_CONFIG = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")

# The grounded defaults (config.json pi.display.carousel -- mirrored by
# CAROUSEL_DEFAULTS in carousel.js). Named here so a retune fails on the VALUE
# rather than silently changing the feel of every test below.
_PARKED_ON_S = 8
_PARKED_OFF_S = 3

_ON_MS = _PARKED_ON_S * 1000
_OFF_MS = _PARKED_OFF_S * 1000

# An arbitrary non-zero epoch. Deliberately NOT 0: a reducer that anchors its
# hold at 0 instead of at the first observation would credit the whole epoch and
# park instantly, and a t0 of 0 would hide that.
_T0 = 1_754_000_000_000

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _view(fn: str, *args: object) -> object:
    """Evaluate one carousel.js export against fixtures via the node probe.

    `encoding` is pinned to utf-8 deliberately -- `text=True` alone decodes
    node's UTF-8 with the Windows locale codepage and mangles any non-ASCII
    copy under test (TD-068).
    """
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _fnBody(js: str, name: str) -> str:
    """The source text of one `function <name>(`, cut at ITS OWN closing brace.

    Indent-aware on purpose. The neighbouring suites slice "up to the next
    function declaration" at a FIXED indent, and that is not a body: carousel.js
    declares its pure logic at 2-space indent and its browser-only helpers at 4,
    so a 4-space terminator applied to a 2-space function runs on through
    everything between it and the DOM block. That is how the absence assertion
    below first went red against correct code -- it matched the comment that
    DOCUMENTS the identifier this story forbids inside menuAccess. Third
    occurrence of that shape (US-507, US-509): the fix is to strip what is not
    the body, never to soften the assertion.
    """
    start = js.index("function " + name + "(")
    indent = " " * (start - js.rindex("\n", 0, start) - 1)
    return js[start : js.index("\n" + indent + "}", start)]


def _feed(samples: list, cfg: object = None, state: object = None) -> list:
    """Run `(rawIdle, nowMs)` samples through parkedNext, keeping every step.

    Returns the list of states AFTER each sample, so a test can assert what the
    signal did DURING a blip and not merely where it landed -- a debounce that
    dips and recovers between two polls is exactly the flicker this story
    removes, and only the intermediate states can see it.
    """
    if state is None:
        state = _view("parkedInit")
    out = []
    for rawIdle, nowMs in samples:
        state = _view("parkedNext", state, rawIdle, nowMs, cfg)
        out.append(state)
    return out


def _parked(samples: list, cfg: object = None) -> list:
    """Just the `parked` booleans, one per sample."""
    return [s["parked"] for s in _feed(samples, cfg)]


def _settled(nowMs: int = _T0, cfg: object = None) -> dict:
    """A state that has already SETTLED parked (idle held past parkedOnS).

    Every un-park test needs this precondition, and building it from the public
    reducer rather than hand-writing a state literal means these tests cannot
    drift from the shape the implementation actually produces.
    """
    on = _ON_MS if cfg is None else int(cfg.get("parkedOnS", _PARKED_ON_S) * 1000)
    states = _feed([(True, nowMs), (True, nowMs + on)], cfg)
    assert states[-1]["parked"] is True, "precondition: the fixture must reach parked"
    return states[-1]


# ---------------------------------------------------------------------------
# AC-1 -- the ON edge. Idle must be HELD, not merely observed once.
# ---------------------------------------------------------------------------


def test_parkedInit_bootIsNotParked():
    """Before anything has been held, "am I parked?" is unanswered -- and the
    unanswered side of that question is the one that hands out a single tap into
    a service stop. Boot fails closed, matching the markup's hidden button."""
    assert _view("parkedInit")["parked"] is False


def test_parkedNext_firstIdleSampleDoesNotPark():
    """The hold is anchored at the FIRST OBSERVATION, never at the epoch. A
    reducer that leaves `sinceMs` at 0 reads a 55-year hold off the wall clock
    and parks on the very first poll -- green against every threshold test below
    while shipping no debounce at all."""
    assert _parked([(True, _T0)]) == [False]


def test_parkedNext_idleHeldForParkedOnS_becomesParked():
    assert _parked([(True, _T0), (True, _T0 + _ON_MS)]) == [False, True]


def test_parkedNext_idleHeldJustUnderParkedOnS_staysNotParked():
    assert _parked([(True, _T0), (True, _T0 + _ON_MS - 1)]) == [False, False]


def test_parkedNext_idleTrueForever_staysParked():
    """The OFF timer must be gated on the READING, not merely on elapsed time. A
    reducer that fires whichever threshold the clock passes would un-park a car
    that has sat parked in the driveway for two minutes."""
    settled = _settled()
    states = _feed([(True, _T0 + _ON_MS + 120_000)], state=settled)
    assert states[-1]["parked"] is True


# ---------------------------------------------------------------------------
# AC-1 -- the OFF edge, and the asymmetry. Quick to withdraw the affordance.
# ---------------------------------------------------------------------------


def test_parkedNext_notIdleHeldForParkedOffS_unparks():
    settled = _settled()
    t = _T0 + _ON_MS
    states = _feed([(False, t), (False, t + _OFF_MS)], state=settled)
    assert [s["parked"] for s in states] == [True, False]


def test_parkedNext_notIdleHeldJustUnderParkedOffS_staysParked():
    settled = _settled()
    t = _T0 + _ON_MS
    states = _feed([(False, t), (False, t + _OFF_MS - 1)], state=settled)
    assert [s["parked"] for s in states] == [True, True]


def test_parkedNext_offThresholdIsShorterThanOn():
    """Not a tautology about two constants -- a BEHAVIOURAL pin on the
    asymmetry. Withdrawing the single-tap path into a service stop must never be
    slower than offering it; a symmetric debounce would leave the ⋮ on screen
    for the same 8 s after the car starts moving."""
    assert _OFF_MS < _ON_MS
    settled = _settled()
    t = _T0 + _ON_MS
    # The un-park lands strictly inside the window the ON edge would still be
    # waiting out.
    states = _feed([(False, t), (False, t + _ON_MS - 1)], state=settled)
    assert states[-1]["parked"] is False


def test_parkedNext_notIdleForever_staysNotParked():
    """The mirror of the always-idle guard: a driving car never spontaneously
    acquires the affordance because the clock passed a threshold."""
    assert _parked([(False, _T0), (False, _T0 + 120_000)]) == [False, False]


# ---------------------------------------------------------------------------
# AC-4 -- THE STORY. A sub-threshold blip must not toggle the kebab.
# ---------------------------------------------------------------------------


def test_parkedNext_subThresholdIdleBlip_neverUnparks():
    """The reported defect, in one sequence: parked in the driveway, OBD
    availability drops out for 2 s, comes back. `parked` must not dip at ANY
    sample -- asserting only the final state would pass with a debounce that
    flickered off and on again between two polls."""
    settled = _settled()
    t = _T0 + _ON_MS
    blip = [
        (False, t + 250),   # the blip starts
        (False, t + 1000),
        (False, t + 2000),  # 2 s < parkedOffS -- still inside the deadzone
        (True, t + 2250),   # ...and it recovers
        (True, t + 3000),
    ]
    assert all(s["parked"] for s in _feed(blip, state=settled))


def test_parkedNext_repeatedBlips_neverUnpark():
    """Flicker is rarely a single dropout. Six blips over 27 s, none of them
    individually long enough to un-park: the kebab must sit still through all of
    them. A debouncer that ACCUMULATES not-idle time across recoveries (rather
    than re-anchoring on each change) un-parks part-way through this."""
    settled = _settled()
    t = _T0 + _ON_MS
    samples = []
    for i in range(6):
        base = t + i * 4500
        samples += [(False, base), (False, base + 2000), (True, base + 2250)]
    assert all(s["parked"] for s in _feed(samples, state=settled))


def test_parkedNext_subThresholdIdleBlipWhileDriving_neverParks():
    """The inverse defect, and the one that matters for safety: a 2 s idle blip
    mid-drive must not hand back the single-tap path into a service stop."""
    driving = _feed([(False, _T0), (False, _T0 + 60_000)])[-1]
    t = _T0 + 60_000
    blip = [(True, t + 250), (True, t + 2000), (False, t + 2250)]
    assert not any(s["parked"] for s in _feed(blip, state=driving))


def test_parkedNext_blipReanchorsTheHold():
    """Hysteresis is re-anchoring, not summing. 2 s not-idle, one idle sample,
    then 2 s not-idle again totals 4 s of not-idle but contains no 3 s RUN, so
    the signal holds; the un-park only lands once a full run completes."""
    settled = _settled()
    t = _T0 + _ON_MS
    states = _feed(
        [
            (False, t),
            (False, t + 2000),
            (True, t + 2250),      # re-anchors
            (False, t + 2500),
            (False, t + 4500),     # 2 s into the NEW run -- still parked
            (False, t + 5500),     # 3 s into it -- now it goes
        ],
        state=settled,
    )
    assert [s["parked"] for s in states] == [True, True, True, True, True, False]


# ---------------------------------------------------------------------------
# Honest instrument -- an unreadable input is never a confident reading.
# ---------------------------------------------------------------------------


def test_parkedNext_nonBooleanIdle_readsAsNotIdle():
    """`carouselIdle` hands this reducer a strict boolean today, but the fail-
    closed rule has to survive the day something else feeds it. Only a real
    `true` counts as idle -- the truthy string "false" is the classic lie."""
    for junk in ("true", "false", 1, {}, None):
        assert _parked([(junk, _T0), (junk, _T0 + _ON_MS)], None) == [False, False], junk


def test_parkedNext_unreadableClock_leavesTheSignalUntouched():
    """A hold is a MEASURED duration. With no readable clock there is no
    measurement, so the signal must hold its last value rather than advance on a
    fabricated one -- the same rule swipeGesture applies to an unmeasurable dt."""
    settled = _settled()
    for badClock in (None, "now", {}):
        states = _feed([(False, badClock)], state=settled)
        assert states[-1]["parked"] is True, badClock
        # ...and the anchor must not be poisoned: the next REAL reading has to
        # still be able to measure a run against it.
        after = _feed([(False, _T0 + _ON_MS), (False, _T0 + _ON_MS + _OFF_MS)],
                      state=states[-1])
        assert after[-1]["parked"] is False, badClock


def test_parkedNext_clockStepsBackMidRun_reAnchorsRatherThanStranding():
    """A backwards clock (an NTP step on a Pi with no RTC -- this hardware has
    none) taken MID-RUN yields a negative hold. Left alone, that run can never
    reach its threshold again until the clock catches back up, so the signal is
    stranded for the size of the step. Here that strands the SAFETY half: the ⋮
    stays on screen while the car drives away. An impossible elapsed time is not
    a measurement -- re-anchor and let the next poll measure a real one.

    Deliberately stepped mid-run, with the reading UNCHANGED across the step:
    a step that coincides with a reading change re-anchors for the ordinary
    reason and would pass with no negative-hold guard at all."""
    settled = _settled()
    t = _T0 + _ON_MS
    states = _feed(
        [
            (False, t),                     # the not-idle run starts here
            (False, t - 60_000),            # ...and the clock steps back into it
            (False, t - 60_000 + _OFF_MS),  # a full run measured on the new clock
        ],
        state=settled,
    )
    assert [s["parked"] for s in states] == [True, True, False]


def test_parkedNext_malformedPriorState_startsCleanRatherThanCrashing():
    """The state rides in a closure across every tick of a kiosk that runs for
    days. If it is ever lost or replaced, the reducer must resume from a
    fail-closed start, not throw and take the whole poll down with it."""
    for junk in (None, "state", 7, {}):
        state = _view("parkedNext", junk, True, _T0, None)
        assert state["parked"] is False


# ---------------------------------------------------------------------------
# AC-4 -- the thresholds are CONFIG, not code.
# ---------------------------------------------------------------------------


def test_parkedNext_thresholdsComeFromTheInjectedConfig():
    """Retuning the feel must be a config change. Pinned by BEHAVIOUR (a 1 s
    parkedOnS parks in 1 s) rather than by reading the resolved object back --
    a config the reducer resolves and then ignores would pass the latter."""
    cfg = {"parkedOnS": 1, "parkedOffS": 1}
    assert _parked([(True, _T0), (True, _T0 + 1000)], cfg) == [False, True]
    # ...and the default would NOT have parked by then.
    assert _parked([(True, _T0), (True, _T0 + 1000)], None) == [False, False]


def test_parkedNext_nonPositiveThreshold_fallsBackToTheDefault():
    """US-506's rule, inherited: a non-positive interval must fail to the
    grounded default, never to zero. `parkedOnS: 0` read literally means "park
    the instant idle is observed" -- the debounce silently deleted by a typo."""
    cfg = {"parkedOnS": 0}
    assert _parked([(True, _T0), (True, _T0 + 1000)], cfg) == [False, False]
    assert _parked([(True, _T0), (True, _T0 + _ON_MS)], cfg) == [False, True]


def test_resolveCarouselConfig_carriesTheParkedThresholds():
    cfg = _view("resolveCarouselConfig", None)
    assert cfg["parkedOnS"] == _PARKED_ON_S
    assert cfg["parkedOffS"] == _PARKED_OFF_S


def test_configJson_carriesTheParkedThresholds():
    """The tuning SSOT: "it is a config parameter" is a claim with nothing
    behind it unless the key exists in config.json at the mirrored value."""
    with open(_CONFIG, encoding="utf-8") as fh:
        config = json.load(fh)
    carousel = config["pi"]["display"]["carousel"]
    assert carousel["parkedOnS"] == _PARKED_ON_S
    assert carousel["parkedOffS"] == _PARKED_OFF_S


# ---------------------------------------------------------------------------
# AC-2 -- the kebab policy consumes the DEBOUNCED signal, and can no longer
# reach the raw one.
# ---------------------------------------------------------------------------


def test_menuAccess_parked_offersTheTapAffordance():
    assert _view("menuAccess", True)["tapVisible"] is True


def test_menuAccess_notParked_hidesTheTapAffordance():
    assert _view("menuAccess", False)["tapVisible"] is False


def test_menuAccess_rawSystemStatusPayload_failsClosed():
    """The footgun this signature change creates, closed. `menuAccess` used to
    take the system-status OBJECT; a caller left un-migrated would now hand it a
    truthy object, and a `!!parked` test would read that as PARKED FOREVER --
    the ⋮ pinned on screen at 70 mph, which is the exact hazard US-490 exists to
    prevent. Only a strict `true` counts."""
    payload = {"idle": True, "drive": {"state": "recording"}, "ts": "2026-08-01T00:00:00Z"}
    assert _view("menuAccess", payload)["tapVisible"] is False
    assert _view("menuAccess", "true")["tapVisible"] is False
    assert _view("menuAccess", 1)["tapVisible"] is False


def test_menuAccess_longPressStaysUnconditional():
    """US-490 AC-2, unchanged by this story and re-pinned because the debounce
    now DELAYS the tap path: making the affordance slower to appear is only safe
    while the deliberate ~5 s hold still opens the menu in every state."""
    for parked in (True, False, None, {}):
        assert _view("menuAccess", parked)["longPress"] is True, parked


def test_fnBodySlicerIsTightButNotEmpty():
    """The slicer above is load-bearing for the absence assertions, and
    OVER-stripping is the dangerous direction: a slice that cuts to nothing
    makes "identifier X is not in this body" pass VACUOUSLY, so the guard would
    keep smiling while menuAccess went back to reading the raw flag. Pin both
    edges -- the real body survives, the neighbours do not."""
    js = _read(_JS)
    body = _fnBody(js, "menuAccess")
    assert "tapVisible" in body and "longPress" in body, "sliced away the body"
    assert "parkedInit" not in body, "the slice ran on into the next function"
    wiring = _fnBody(js, "updateMenuAccess")
    assert "applyMenuAccess(" in wiring, "sliced away the body"
    assert "setupMenu" not in wiring, "the slice ran on into the next function"


def test_menuAccess_noLongerReadsTheRawIdleFlag():
    """AC-2 structurally. While `menuAccess` acquires its own idle it can be
    debounced only by convention -- and the next edit re-introduces the flicker
    for free. Reading the flag must be OUT OF REACH, not merely discouraged."""
    body = _fnBody(_read(_JS), "menuAccess")
    assert "carouselIdle" not in body, "menuAccess still re-derives idle for itself"
    assert "systemStatus" not in body, "menuAccess still takes the raw state payload"


# ---------------------------------------------------------------------------
# Wiring -- a reducer nothing advances is inert, and one re-initialised every
# tick can never accumulate a hold.
# ---------------------------------------------------------------------------


def test_carouselJs_exportsTheParkedDebounce():
    """The pure logic stays node-testable (the S-2 contract)."""
    js = _read(_JS)
    for name in ("parkedInit:", "parkedNext:"):
        assert name in js, name


def test_pollAdvancesTheDebounceWithTheTickClock():
    """The reducer takes its clock as an argument, so the poll must hand it one
    -- and it must be the SHARED tick clock (US-496), or the kebab resolves
    against a different instant than everything else painted that tick."""
    js = _read(_JS)
    assert "updateMenuAccess(sysData, nowMs)" in js


def test_updateMenuAccess_advancesTheDebounceAndFeedsItToThePolicy():
    """The two halves that make this story real: the raw flag goes INTO the
    reducer, and the reducer's output -- not the flag -- comes out into
    menuAccess."""
    body = _fnBody(_read(_JS), "updateMenuAccess")
    assert "parkedNext(" in body, "the debounce is never advanced"
    assert "carouselIdle(" in body, "the reducer is never fed the emitter's flag"
    assert ".parked" in body, "the policy is not fed the debounced signal"


def test_debounceStateOutlivesTheTick():
    """The one mistake that makes every test above pass while the kebab NEVER
    appears: initialising the state inside the per-tick function. A hold that
    resets every 250 ms can never reach 8 s. The state must be created in the
    enclosing scope."""
    js = _read(_JS)
    body = _fnBody(js, "updateMenuAccess")
    assert "parkedInit(" not in body, "the debounce state is reset on every tick"
    assert "parkedInit(" in js, "the debounce state is never initialised at all"
